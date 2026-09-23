"""Bounded, static-first crawl. All connections revalidate DNS; redirects are explicit."""

import asyncio
import hashlib
import json
import logging
import re
from collections import deque
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser
from xml.etree import ElementTree

import aiohttp
from bs4 import BeautifulSoup

from app.config import settings
from app.core.crawl_target import PublicAddressResolver, validate_crawl_target
from app.crawling.classification import requires_browser_rendering
from app.crawling.cloudflare import CloudflareBrowserCrawler, CloudflareCrawlError
from app.security import normalize_url, origin

USER_AGENT = "CoastworksBot/1.0"
MAX_BYTES = 2_000_000
log = logging.getLogger("coastworks.crawl")


class CrawlFailure(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


@dataclass
class CrawlResult:
    pages: list[dict] = field(default_factory=list)
    attempted: int = 0
    discovered: int = 0
    rendered: int = 0
    failed: int = 0
    denied: int = 0
    core_total: int = 0
    core_succeeded: int = 0
    core_failed: int = 0

    def quality(self):
        words = sum(len(p["content"].split()) for p in self.pages)
        attempted_allowed = max(1, self.attempted - self.denied)
        success_ratio = len(self.pages) / attempted_allowed

        # Preview quality should reflect whether we have enough useful knowledge,
        # not whether every sampled URL happened to return usable content.
        # Real sites commonly contain stale links, duplicate pages and guarded paths.
        enough_content = words >= 300
        enough_coverage = (
            len(self.pages) >= 2
            or (len(self.pages) == 1 and (self.discovered <= 1 or words >= 700))
        )
        not_catastrophic = success_ratio >= 0.35
        sufficient = enough_content and enough_coverage and not_catastrophic

        return {
            "passed": sufficient,
            "pages": len(self.pages),
            "words": words,
            "attempted": self.attempted,
            "discovered": self.discovered,
            "rendered": self.rendered,
            "failed": self.failed,
            "denied": self.denied,
            "success_ratio": round(success_ratio, 3),
            "core_total": self.core_total,
            "core_succeeded": self.core_succeeded,
            "core_failed": self.core_failed,
        }


def extract(html: str, url: str):
    # Reuse Coastworks' cleaned text extraction and metadata contract.
    return CloudflareBrowserCrawler._html_to_page(
        html, url=url, root=urlsplit(url), include_regex=None, exclude_regex=None
    )


def blocked(html: str):
    soup = BeautifulSoup(html, "html.parser")
    title = soup.title.get_text(" ", strip=True).lower() if soup.title else ""
    text = soup.get_text(" ", strip=True).lower()
    return any(marker in title for marker in ("just a moment", "access denied", "attention required")) or (
        len(text) < 1200
        and any(
            marker in text
            for marker in ("verify you are human", "checking your browser", "enable cookies to continue")
        )
    )


COUNTRY_LANGUAGE = {
    "se": "sv",
    "no": "nb",
    "dk": "da",
    "fi": "fi",
    "de": "de",
    "fr": "fr",
    "nl": "nl",
    "es": "es",
    "pt": "pt",
    "it": "it",
    "pl": "pl",
    "gb": "en",
    "uk": "en",
}


def preferred_locale_url(html: str, current_url: str, submitted_host: str):
    """Choose an hreflang alternate matching the submitted ccTLD, if available."""
    labels = (submitted_host or "").lower().rstrip(".").split(".")
    cc = labels[-1] if labels and len(labels[-1]) == 2 else None
    if not cc:
        return None

    wanted_language = COUNTRY_LANGUAGE.get(cc)
    soup = BeautifulSoup(html, "html.parser")
    candidates = []
    for link in soup.select('link[rel~="alternate"][hreflang][href]'):
        hreflang = str(link.get("hreflang") or "").strip().lower().replace("_", "-")
        if not hreflang or hreflang == "x-default":
            continue
        parts = hreflang.split("-")
        language = parts[0]
        region = parts[-1] if len(parts) > 1 and len(parts[-1]) == 2 else None
        score = 0
        if region == cc:
            score = 3
        elif wanted_language and language == wanted_language:
            score = 2
        elif language == cc:
            score = 1
        if not score:
            continue
        try:
            target = normalize_url(urljoin(current_url, str(link.get("href") or "")))
        except ValueError:
            continue
        if origin(target) == origin(current_url):
            candidates.append((score, target))

    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][1]


def locale_path_scope(url: str):
    path_parts = [part for part in urlsplit(url).path.split("/") if part]
    if not path_parts:
        return None
    first = path_parts[0].lower()
    if re.fullmatch(r"[a-z]{2,3}(?:-[a-z]{2})?", first):
        return "/" + first
    return None


def page_priority(candidate: str):
    path = urlsplit(candidate).path.lower()
    info_hint = bool(
        re.search(
            r"contact|kontakt|about|om-oss|service|tjanst|faq|help|support|"
            r"company|business|foretag|företag|gift|present|pricing|price|pris|"
            r"terms|villkor|policy|shipping|leverans|returns|retur|pages/",
            path,
            re.I,
        )
    )
    transactional = bool(
        re.search(r"/cart|/checkout|/account|/login|/search", path, re.I)
    )
    product = "/products/" in path
    collection = "/collections/" in path
    blog = "/blogs/" in path
    depth = len([part for part in path.split("/") if part])
    return (
        1 if transactional else 0,
        0 if info_hint else 1,
        1 if product else 0,
        1 if collection else 0,
        1 if blog else 0,
        depth,
        len(path),
    )


def clean_internal_url(link: str, root: str):
    try:
        clean = normalize_url(link)
    except ValueError:
        return None
    if origin(clean) != root:
        return None
    path = urlsplit(clean).path.lower()
    if re.search(r"\.(?:xml|json|css|js|svg|webp|ico|docx?|xlsx?|zip|mp4)$", path, re.I):
        return None
    if any(
        x in path
        for x in (
            "/cart",
            "/checkout",
            "/login",
            "/account",
            "/search",
            "/wp-admin",
            "/localization",
            "/challenge",
        )
    ):
        return None
    return clean


def navigation_links(html: str, current_url: str, root: str):
    """Return actual site-navigation links, excluding header utility actions."""
    soup = BeautifulSoup(html, "html.parser")
    links = []
    for anchor in soup.select("nav a[href], [role='navigation'] a[href]"):
        href = str(anchor.get("href") or "").strip()
        label = anchor.get_text(" ", strip=True)
        ancestors = [anchor, *list(anchor.parents)[:4]]
        utility_context = " ".join(
            " ".join(
                [
                    str(node.get("id") or ""),
                    " ".join(node.get("class") or []),
                    str(node.get("data-localization-form") or ""),
                ]
            )
            for node in ancestors
            if getattr(node, "get", None)
        ).lower()
        if (
            not href
            or not label
            or href.startswith(("#", "javascript:", "mailto:", "tel:"))
            or re.search(r"localization|language|locale|country-selector", utility_context)
        ):
            continue
        clean = clean_internal_url(urljoin(current_url, href), root)
        if clean and clean != normalize_url(current_url):
            links.append(clean)
    return list(dict.fromkeys(links))


def footer_links(html: str, current_url: str, root: str):
    soup = BeautifulSoup(html, "html.parser")
    links = []
    for anchor in soup.select("footer a[href]"):
        href = str(anchor.get("href") or "").strip()
        if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue
        clean = clean_internal_url(urljoin(current_url, href), root)
        if clean:
            links.append(clean)
    return list(dict.fromkeys(links))


async def discover_sitemap_urls(fetcher, sitemap_urls, root, max_sitemaps=12, max_urls=500):
    pending = deque(sitemap_urls)
    seen_maps = set()
    discovered = []
    discovered_set = set()

    while pending and len(seen_maps) < max_sitemaps and len(discovered) < max_urls:
        sitemap = pending.popleft()
        try:
            sitemap = normalize_url(sitemap)
        except ValueError:
            continue
        if sitemap in seen_maps or origin(sitemap) != root:
            continue
        seen_maps.add(sitemap)

        try:
            code, xml, _ = await fetcher.get(sitemap, allowed_origin=root)
            if code != 200 or "<!DOCTYPE" in xml.upper() or "<!ENTITY" in xml.upper():
                continue
            tree = ElementTree.fromstring(xml)
        except (CrawlFailure, ValueError, ElementTree.ParseError, aiohttp.ClientError, TimeoutError):
            continue

        locs = [
            (item.text or "").strip()
            for item in tree.iter()
            if item.tag.endswith("}loc") or item.tag == "loc"
        ]
        if tree.tag.endswith("sitemapindex"):
            for loc in locs:
                try:
                    child = normalize_url(loc)
                except ValueError:
                    continue
                if origin(child) == root and child not in seen_maps:
                    pending.append(child)
            continue

        for loc in locs:
            clean = clean_internal_url(loc, root)
            if clean and clean not in discovered_set:
                discovered_set.add(clean)
                discovered.append(clean)
                if len(discovered) >= max_urls:
                    break

    discovered.sort(key=page_priority)
    return discovered


class Fetcher:
    async def __aenter__(self):
        self.session = aiohttp.ClientSession(
            connector=aiohttp.TCPConnector(resolver=PublicAddressResolver(), use_dns_cache=False),
            timeout=aiohttp.ClientTimeout(total=15),
            headers={"User-Agent": USER_AGENT},
            trust_env=False,
            cookie_jar=aiohttp.DummyCookieJar(),
        )
        return self

    async def __aexit__(self, *args):
        await self.session.close()

    async def get(self, url, *, allowed_origin=None, canonical_redirect=False):
        migrated_origin = None
        for _ in range(5):
            url = normalize_url(url)
            current_origin = origin(url)
            expected_origin = migrated_origin or allowed_origin
            if expected_origin and current_origin != expected_origin:
                original, target = urlsplit(expected_origin), urlsplit(url)
                alias = (original.hostname or "").removeprefix("www.") == (
                    target.hostname or ""
                ).removeprefix("www.") and not (
                    original.scheme == "https" and target.scheme == "http"
                )
                safe_migration = (
                    canonical_redirect
                    and migrated_origin is None
                    and target.scheme == "https"
                )
                if alias:
                    pass
                elif safe_migration:
                    # Only the initial canonical-resolution request may migrate
                    # to a new public HTTPS origin (e.g. dormy.se -> dormy.com).
                    # validate_crawl_target below still blocks private/internal IPs.
                    migrated_origin = current_origin
                else:
                    raise CrawlFailure("OFFSITE_REDIRECT")
            await validate_crawl_target(url)
            async with self.session.get(url, allow_redirects=False) as response:
                if response.status in {301, 302, 303, 307, 308}:
                    url = urljoin(url, response.headers.get("Location", ""))
                    continue
                body = bytearray()
                async for block in response.content.iter_chunked(65536):
                    body.extend(block)
                    if len(body) > MAX_BYTES:
                        raise CrawlFailure("PAGE_TOO_LARGE")
                return response.status, body.decode(response.charset or "utf-8", errors="replace"), url
        raise CrawlFailure("REDIRECT_LIMIT")


async def fetch_with_retries(fetcher, url, root, *, retries=3):
    """Fetch with bounded exponential backoff for transient network/server failures."""
    last_error = None
    transient_statuses = {408, 425, 429, 500, 502, 503, 504}
    for attempt in range(retries + 1):
        try:
            status, html, final = await fetcher.get(url, allowed_origin=root)
            if status == 200:
                return status, html, final
            error = CrawlFailure(f"HTTP_{status}")
            if status not in transient_statuses:
                raise error
            last_error = error
        except (aiohttp.ClientError, TimeoutError) as exc:
            last_error = exc

        if attempt < retries:
            await asyncio.sleep(min(2.0, 0.35 * (2**attempt)))

    if isinstance(last_error, CrawlFailure):
        raise last_error
    raise CrawlFailure("FETCH_FAILED") from last_error


class Renderer:
    """Adapt Coastworks' stateless renderer; fix JSON envelopes and bound body size."""

    async def render(self, url):
        if not settings.CLOUDFLARE_API_TOKEN or not settings.CLOUDFLARE_ACCOUNT_ID:
            raise CrawlFailure("RENDERER_UNAVAILABLE")
        crawler = CloudflareBrowserCrawler(
            account_id=settings.CLOUDFLARE_ACCOUNT_ID,
            api_token=settings.CLOUDFLARE_API_TOKEN,
            content_request_interval_seconds=1,
            rate_limit_retries=1,
        )
        try:
            async with asyncio.timeout(40):
                await validate_crawl_target(url)
                raw = await crawler._render_content(url)
            if raw.lstrip().startswith("{"):
                data = json.loads(raw)
                if not data.get("success") or not isinstance(data.get("result"), str):
                    raise CrawlFailure("RENDER_FAILED")
                meta = data.get("meta") or {}
                if meta.get("status", 200) >= 400:
                    raise CrawlFailure("SITE_BLOCKED")
                final_url = meta.get("finalUrl", url)
                await validate_crawl_target(final_url)
                if origin(normalize_url(final_url)) != origin(url):
                    raise CrawlFailure("OFFSITE_REDIRECT")
                raw = data["result"]
            if len(raw.encode()) > MAX_BYTES:
                raise CrawlFailure("PAGE_TOO_LARGE")
            return raw
        except (CloudflareCrawlError, TimeoutError, ValueError) as exc:
            raise CrawlFailure("RENDER_FAILED") from exc
        finally:
            await crawler.close()


async def crawl(start_url, fetcher=None, renderer=None):
    """Crawl a site with sitemap-first discovery, bounded concurrency and retries.

    Strategy:
    1. Fetch robots + homepage.
    2. Prioritize real navigation links.
    3. Merge recursive sitemap URLs and ordinary internal links.
    4. Crawl the resulting frontier concurrently with bounded retries.
    5. Escalate only convincing client-rendered shells to a browser renderer.
    """
    if fetcher is None:
        async with Fetcher() as fetcher:
            async with asyncio.timeout(settings.CRAWL_SECONDS):
                return await crawl(start_url, fetcher, renderer)

    supplied_renderer = renderer is not None
    renderer = renderer or Renderer()
    submitted_host = urlsplit(start_url).hostname or ""
    root = origin(start_url)

    # Check robots on the submitted origin first. A legacy domain may itself
    # redirect robots.txt to the canonical domain; allow that one safe migration.
    status, robots_text, final_robots = await fetcher.get(
        root + "/robots.txt",
        allowed_origin=root,
        canonical_redirect=True,
    )
    if origin(final_robots) != root:
        root = origin(final_robots)
        start_url = root + urlsplit(start_url).path
    if status not in {200, 404, 410}:
        raise CrawlFailure("ROBOTS_UNAVAILABLE")

    robots = RobotFileParser()
    robots.parse(robots_text.splitlines() if status == 200 else [])
    if not robots.can_fetch(USER_AGENT, start_url):
        raise CrawlFailure("ROBOTS_DENIED")

    # Resolve the actual entrypoint. If a legacy/marketing domain redirects to a
    # different canonical HTTPS origin (e.g. dormy.se -> dormy.com), rebase the
    # crawl there and fetch that origin's robots before crawling any content.
    entry_status, entry_html, canonical_start = await fetcher.get(
        start_url,
        allowed_origin=root,
        canonical_redirect=True,
    )
    if entry_status >= 400:
        raise CrawlFailure(f"HTTP_{entry_status}")
    canonical_start = normalize_url(canonical_start)
    locale_target = preferred_locale_url(entry_html, canonical_start, submitted_host)
    if locale_target:
        log.info(
            "locale_rebased submitted_host=%s from=%s to=%s",
            submitted_host,
            canonical_start,
            locale_target,
        )
        canonical_start = locale_target
    canonical_root = origin(canonical_start)
    if canonical_root != root:
        root = canonical_root
        start_url = canonical_start
        status, robots_text, _ = await fetcher.get(
            root + "/robots.txt",
            allowed_origin=root,
        )
        if status not in {200, 404, 410}:
            raise CrawlFailure("ROBOTS_UNAVAILABLE")
        robots = RobotFileParser()
        robots.parse(robots_text.splitlines() if status == 200 else [])
        if not robots.can_fetch(USER_AGENT, start_url):
            raise CrawlFailure("ROBOTS_DENIED")
    else:
        start_url = canonical_start

    locale_scope = locale_path_scope(start_url) if locale_target else None

    def in_locale_scope(candidate: str):
        if not locale_scope:
            return True
        path = urlsplit(candidate).path
        return path == locale_scope or path.startswith(locale_scope + "/")

    robots_delay = float(robots.crawl_delay(USER_AGENT) or 0)
    if robots_delay > 5:
        raise CrawlFailure("SITE_REQUIRES_SLOW_CRAWL")

    sitemap_roots = [
        u
        for u in (robots.site_maps() or [root + "/sitemap.xml"])
        if origin(u) == root
    ][:8]
    sitemap_candidates = await discover_sitemap_urls(
        fetcher,
        sitemap_roots,
        root,
        max_sitemaps=24,
        max_urls=max(500, settings.CRAWL_PAGES * 10),
    )
    sitemap_candidates = [url for url in sitemap_candidates if in_locale_scope(url)]

    result = CrawlResult()
    hashes = set()
    attempted_urls = set()
    browser_slots = asyncio.Semaphore(2)
    request_slots = asyncio.Semaphore(1 if robots_delay >= 1 else 6)
    browser_available = supplied_renderer or bool(
        settings.CLOUDFLARE_API_TOKEN and settings.CLOUDFLARE_ACCOUNT_ID
    )

    async def load_page(url: str, *, is_core: bool = False):
        if url in attempted_urls:
            return None
        attempted_urls.add(url)

        if not robots.can_fetch(USER_AGENT, url):
            result.denied += 1
            if is_core:
                result.core_failed += 1
            log.info("page_denied url=%s core=%s", url, is_core)
            return None

        result.attempted += 1
        try:
            async with request_slots:
                if robots_delay:
                    await asyncio.sleep(robots_delay)
                _, html, final = await fetch_with_retries(
                    fetcher, url, root, retries=1
                )

            if blocked(html):
                raise CrawlFailure("SITE_BLOCKED")

            page = extract(html, final)
            text = page["content"] if page else ""
            shell = requires_browser_rendering(
                html, text, useful_text_threshold=300
            )

            if shell:
                if not browser_available:
                    # A real JS shell with no useful static fallback cannot be indexed
                    # safely. Ordinary short SSR pages never enter this branch.
                    if not page or len(text.split()) < 20:
                        raise CrawlFailure("RENDERER_UNAVAILABLE")
                else:
                    async with browser_slots:
                        html = await renderer.render(final)
                    result.rendered += 1
                    if blocked(html):
                        raise CrawlFailure("SITE_BLOCKED")
                    page = extract(html, final)
                    text = page["content"] if page else ""

            minimum_words = 5 if is_core else 45
            stored = False
            if page and len(text.split()) >= minimum_words:
                page["content"] = page["content"][:24000]
                fingerprint = hashlib.sha256(page["content"].encode()).hexdigest()
                # Navigation pages are few and user-visible; preserve them even if
                # their body text duplicates another page (e.g. a short contact page).
                identity = (final, fingerprint) if is_core else fingerprint
                if identity not in hashes:
                    hashes.add(identity)
                    result.pages.append(page)
                    stored = True

            if is_core:
                if stored:
                    result.core_succeeded += 1
                else:
                    result.core_failed += 1

            links = CloudflareBrowserCrawler._discover_urls(
                html, current_url=final, root=urlsplit(root)
            )
            discovered = [
                clean
                for link in links
                if (clean := clean_internal_url(link, root)) is not None
                and in_locale_scope(clean)
            ]
            return {
                "url": url,
                "final": final,
                "html": html,
                "links": list(dict.fromkeys(discovered)),
                "stored": stored,
            }
        except (CrawlFailure, aiohttp.ClientError, TimeoutError) as exc:
            result.failed += 1
            code = exc.code if isinstance(exc, CrawlFailure) else type(exc).__name__
            if is_core:
                result.core_failed += 1
                log.warning("priority_page_failed url=%s code=%s", url, code)
            else:
                log.info("page_failed url=%s code=%s", url, code)
            return None

    # Homepage is the authoritative source for first-party navigation.
    home = await load_page(start_url)
    if not home:
        raise CrawlFailure("INSUFFICIENT_CONTENT")

    core_urls = [
        url for url in navigation_links(home["html"], home["final"], root)
        if in_locale_scope(url)
    ]
    result.core_total = len(core_urls)

    # Queue ordering matters: navigation first, then footer/info pages, then sitemap.
    # The sitemap is still the main completeness mechanism and is parsed recursively.
    frontier = []
    queued = {normalize_url(start_url)}

    def enqueue_many(urls):
        for candidate in urls:
            if candidate not in queued:
                queued.add(candidate)
                frontier.append(candidate)

    enqueue_many(core_urls)
    enqueue_many(
        url for url in footer_links(home["html"], home["final"], root)
        if in_locale_scope(url)
    )
    enqueue_many(sorted(sitemap_candidates, key=page_priority))
    enqueue_many(sorted(home["links"], key=page_priority))

    core_set = set(core_urls)
    max_attempts = min(max(settings.CRAWL_PAGES * 2, 30), 200)
    cursor = 0

    while cursor < len(frontier):
        if result.attempted >= max_attempts:
            break
        if len(result.pages) >= settings.CRAWL_PAGES and not any(
            candidate in core_set and candidate not in attempted_urls
            for candidate in frontier[cursor:]
        ):
            break

        remaining_attempts = max_attempts - result.attempted
        # A moderate batch keeps memory bounded while allowing useful concurrency.
        batch_size = min(18, remaining_attempts, len(frontier) - cursor)
        batch = frontier[cursor : cursor + batch_size]
        cursor += batch_size

        loaded = await asyncio.gather(
            *[
                load_page(url, is_core=url in core_set)
                for url in batch
            ]
        )

        # Links discovered outside a sitemap are useful for sites with incomplete
        # sitemap coverage. They are appended only after the current priority batch.
        for item in loaded:
            if not item:
                continue
            enqueue_many(sorted(item["links"], key=page_priority))

    result.discovered = len(queued)
    quality = result.quality()
    log.info(
        "crawl_complete quality=%s urls=%s",
        quality,
        [page.get("url") for page in result.pages],
    )
    if not quality["passed"]:
        log.warning("crawl_rejected quality=%s", quality)
        raise CrawlFailure("INSUFFICIENT_CONTENT")
    return result

