"""Bounded, static-first crawl. All connections revalidate DNS; redirects are explicit."""

import asyncio
import hashlib
import json
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
        not_catastrophic = success_ratio >= 0.35 or (
            len(self.pages) >= 1 and words >= 700
        )
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
        for _ in range(5):
            url = normalize_url(url)
            if allowed_origin and origin(url) != allowed_origin:
                original, target = urlsplit(allowed_origin), urlsplit(url)
                alias = (original.hostname or "").removeprefix("www.") == (
                    target.hostname or ""
                ).removeprefix("www.") and not (original.scheme == "https" and target.scheme == "http")
                if not canonical_redirect or not alias:
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
    if fetcher is None:
        async with Fetcher() as fetcher:
            async with asyncio.timeout(settings.CRAWL_SECONDS):
                return await crawl(start_url, fetcher, renderer)
    renderer = renderer or Renderer()
    root = origin(start_url)
    status, robots_text, final_robots = await fetcher.get(
        root + "/robots.txt", allowed_origin=root, canonical_redirect=True
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
    delay = max(0.2, float(robots.crawl_delay(USER_AGENT) or 0))
    if delay > 5:
        raise CrawlFailure("SITE_REQUIRES_SLOW_CRAWL")
    queue = deque([start_url])
    seen = {start_url}
    # Bounded sitemap discovery helps sites whose useful pages are not in the first navigation.
    maps = [u for u in (robots.site_maps() or [root + "/sitemap.xml"]) if origin(u) == root][:2]
    for sitemap in maps:
        try:
            code, xml, _ = await fetcher.get(sitemap, allowed_origin=root)
            if code != 200 or "<!DOCTYPE" in xml.upper() or "<!ENTITY" in xml.upper():
                continue
            tree = ElementTree.fromstring(xml)
            if tree.tag.endswith("sitemapindex"):
                continue  # Large sitemap indexes belong to the deeper managed ingestion path.
            for item in tree.iter():
                if item.tag.endswith("}loc") or item.tag == "loc":
                    candidate = normalize_url(item.text or "")
                    if origin(candidate) == root and candidate not in seen and len(seen) < 100:
                        seen.add(candidate)
                        queue.append(candidate)
        except (CrawlFailure, ValueError, ElementTree.ParseError, aiohttp.ClientError, TimeoutError):
            continue
    hashes = set()
    result = CrawlResult()
    max_attempts = min(max(settings.CRAWL_PAGES * 3, 12), 30)
    while queue and len(result.pages) < settings.CRAWL_PAGES and result.attempted < max_attempts:
        url = queue.popleft()
        result.attempted += 1
        if not robots.can_fetch(USER_AGENT, url):
            result.denied += 1
            continue
        if result.attempted > 1:
            await asyncio.sleep(delay)
        try:
            status, html, final = await fetcher.get(url, allowed_origin=root)
            if status != 200 or blocked(html):
                raise CrawlFailure("SITE_BLOCKED")
            page = extract(html, final)
            text = page["content"] if page else ""
            # The old classifier alone misses partial SSR and Next/Nuxt shells.
            shell = requires_browser_rendering(html, text, useful_text_threshold=400)
            sparse_js = len(text.split()) < 90 and "<script" in html.lower()
            if shell or sparse_js:
                if result.rendered >= 4:
                    raise CrawlFailure("RENDER_BUDGET_EXHAUSTED")
                html = await renderer.render(final)
                result.rendered += 1
                if blocked(html):
                    raise CrawlFailure("SITE_BLOCKED")
                page = extract(html, final)
            links = CloudflareBrowserCrawler._discover_urls(html, current_url=final, root=urlsplit(root))
            candidates = []
            for link in links:
                try:
                    clean = normalize_url(link)
                except ValueError:
                    continue
                if re.search(r"\.(?:xml|json|css|js|svg|webp|ico|docx?|xlsx?)$", urlsplit(clean).path, re.I):
                    continue
                if any(
                    x in urlsplit(clean).path.lower() for x in ("/cart", "/checkout", "/login", "/wp-admin")
                ):
                    continue
                candidates.append(clean)
            def priority(candidate):
                path = urlsplit(candidate).path.lower()
                # Prefer shallow informational/navigation pages over transactional/noisy URLs.
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
                    re.search(r"/cart|/checkout|/account|/login|/search|/collections/", path, re.I)
                )
                depth = len([part for part in path.split("/") if part])
                return (
                    1 if transactional else 0,
                    0 if info_hint else 1,
                    depth,
                    len(path),
                )

            candidates.sort(key=priority)
            for clean in candidates:
                if clean not in seen and len(seen) < 100:
                    seen.add(clean)
                    queue.append(clean)
            if page and len(page["content"].split()) >= 60:
                page["content"] = page["content"][:24000]
                fingerprint = hashlib.sha256(page["content"].encode()).hexdigest()
                if fingerprint not in hashes:
                    hashes.add(fingerprint)
                    result.pages.append(page)
        except (CrawlFailure, aiohttp.ClientError, TimeoutError):
            result.failed += 1
    result.discovered = len(seen)
    if not result.quality()["passed"]:
        raise CrawlFailure("INSUFFICIENT_CONTENT")
    return result
