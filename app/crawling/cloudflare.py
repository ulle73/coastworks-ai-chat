"""Cloudflare Browser Rendering adapter for JavaScript-rendered crawl fallback.

The application deliberately keeps this as a small HTTP boundary instead of
shipping a browser runtime in the Azure worker. SiteChat regex include/exclude
rules are applied after Cloudflare returns records because Cloudflare's crawl
options use wildcard semantics rather than Python regular expressions.
"""
from __future__ import annotations

import asyncio
from collections import deque
import re
import time
from typing import Awaitable, Callable, Dict, Iterable, List, Optional
from urllib.parse import unquote, urljoin, urlparse, urlunparse

import aiohttp
from bs4 import BeautifulSoup

from app.core.crawl_target import CrawlTargetValidationError, validate_crawl_target


class CloudflareCrawlError(RuntimeError):
    """Safe application-facing failure from the managed browser provider."""


class CloudflareRateLimitError(CloudflareCrawlError):
    """Cloudflare instructed the caller to wait before retrying a request."""

    def __init__(self, *, retry_after_seconds: Optional[float] = None) -> None:
        super().__init__("Cloudflare Browser Rendering request was rate limited")
        self.retry_after_seconds = retry_after_seconds


class AiohttpCloudflareTransport:
    """Minimal JSON transport that never exposes response bodies in errors."""

    def __init__(self, *, request_timeout_seconds: float = 65.0) -> None:
        self.request_timeout_seconds = request_timeout_seconds
        self._session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=self.request_timeout_seconds)
            self._session = aiohttp.ClientSession(timeout=timeout)
        return self._session

    async def post_content(
        self,
        url: str,
        *,
        headers: Dict[str, str],
        payload: Dict,
    ) -> str:
        """Return the raw rendered HTML from Browser Run's stateless endpoint."""
        session = await self._get_session()
        try:
            async with session.post(url, headers=headers, json=payload) as response:
                if response.status == 429:
                    retry_after = response.headers.get("Retry-After")
                    try:
                        retry_after_seconds = float(retry_after) if retry_after is not None else None
                    except (TypeError, ValueError):
                        retry_after_seconds = None
                    raise CloudflareRateLimitError(retry_after_seconds=retry_after_seconds)
                if response.status < 200 or response.status >= 300:
                    raise CloudflareCrawlError(
                        f"Cloudflare Browser Rendering request failed (HTTP {response.status})"
                    )
                body = bytearray()
                async for block in response.content.iter_chunked(65536):
                    body.extend(block)
                    if len(body) > 4_000_000:
                        raise CloudflareCrawlError("Rendered response exceeds size limit")
                return body.decode("utf-8", errors="replace")
        except CloudflareCrawlError:
            raise
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, TypeError) as exc:
            raise CloudflareCrawlError("Cloudflare Browser Rendering request failed") from exc

    async def close(self) -> None:
        if self._session is not None and not self._session.closed:
            await self._session.close()


class CloudflareBrowserCrawler:
    """Run a bounded same-origin rendered crawl via stateless Browser Run calls."""

    API_BASE = "https://api.cloudflare.com/client/v4"
    _SKIPPED_FILE_SUFFIXES = (".pdf", ".jpg", ".jpeg", ".png", ".gif", ".zip", ".mp4")
    _INVALID_NAVIGATION_CHARACTERS = frozenset('"\'<>`\\')

    def __init__(
        self,
        *,
        account_id: str,
        api_token: str,
        transport=None,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        timeout_seconds: float = 900.0,
        target_validator: Callable[[str], Awaitable[None]] = validate_crawl_target,
        max_depth: int = 10,
        content_request_interval_seconds: float = 10.0,
        rate_limit_retries: int = 3,
    ) -> None:
        if not account_id or not str(account_id).strip():
            raise ValueError("Cloudflare account_id is required")
        if not api_token or not str(api_token).strip():
            raise ValueError("Cloudflare api_token is required")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if max_depth < 0:
            raise ValueError("max_depth cannot be negative")
        if content_request_interval_seconds < 0:
            raise ValueError("content_request_interval_seconds cannot be negative")
        if rate_limit_retries < 0:
            raise ValueError("rate_limit_retries cannot be negative")

        self.account_id = str(account_id).strip()
        self._api_token = str(api_token).strip()
        self.transport = transport or AiohttpCloudflareTransport()
        self.monotonic = monotonic
        self.sleep = sleep
        self.timeout_seconds = timeout_seconds
        self.target_validator = target_validator
        self.max_depth = max_depth
        self.content_request_interval_seconds = content_request_interval_seconds
        self.rate_limit_retries = rate_limit_retries
        self._last_content_request_started_at: Optional[float] = None

    @property
    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_token}",
            "Content-Type": "application/json",
        }

    @property
    def _content_url(self) -> str:
        return f"{self.API_BASE}/accounts/{self.account_id}/browser-rendering/content"

    async def close(self) -> None:
        close = getattr(self.transport, "close", None)
        if close is not None:
            await close()

    @staticmethod
    def _validate_start_url(start_url: str, max_pages: int):
        max_pages = int(max_pages)
        if max_pages < 1:
            raise ValueError("max_pages must be at least 1")
        root = urlparse(start_url)
        if root.scheme not in {"http", "https"} or not root.hostname:
            raise ValueError("start_url must be an absolute http(s) URL")
        return root, max_pages

    async def crawl(
        self,
        start_url: str,
        max_pages: int,
        include_patterns: Optional[List[str]] = None,
        exclude_patterns: Optional[List[str]] = None,
    ) -> List[Dict]:
        """Render one bounded same-origin URL frontier without external job state."""
        root, max_pages = self._validate_start_url(start_url, max_pages)
        include_regex = self._compile_patterns(include_patterns)
        exclude_regex = self._compile_patterns(exclude_patterns)
        root_url = self._canonical_url(start_url)
        pending = deque([(root_url, 0)])
        queued = {root_url}
        visited = set()
        pages: List[Dict] = []

        deadline = self.monotonic() + self.timeout_seconds
        while pending and len(pages) < max_pages:
            if self.monotonic() >= deadline:
                raise CloudflareCrawlError("Cloudflare Browser Rendering content crawl timed out")
            url, depth = pending.popleft()
            if url in visited:
                continue
            await self._validate_target(url)
            html = await self._render_content(url)
            visited.add(url)

            page = self._html_to_page(
                html,
                url=url,
                root=root,
                include_regex=include_regex,
                exclude_regex=exclude_regex,
            )
            if page is not None:
                pages.append(page)

            if depth >= self.max_depth:
                continue
            for discovered in self._discover_urls(html, current_url=url, root=root):
                if discovered in queued or discovered in visited:
                    continue
                if not self._matches_patterns(discovered, include_regex, exclude_regex):
                    continue
                queued.add(discovered)
                pending.append((discovered, depth + 1))

        return pages

    @staticmethod
    def _compile_patterns(patterns: Optional[Iterable[str]]) -> Optional[List[re.Pattern]]:
        values = list(patterns or [])
        return [re.compile(pattern) for pattern in values] if values else None

    async def _validate_target(self, url: str) -> None:
        try:
            await self.target_validator(url)
        except CrawlTargetValidationError as exc:
            raise CloudflareCrawlError("Rendered crawl target is not publicly reachable") from exc

    async def _render_content(self, url: str) -> str:
        attempts = 0
        while True:
            await self._wait_for_content_slot()
            try:
                html = await self.transport.post_content(
                    self._content_url,
                    headers=self._headers,
                    payload={
                        "url": url,
                        # Cloudflare documents networkidle2 for SPAs that otherwise
                        # return their initial shell before React has rendered content.
                        "gotoOptions": {"waitUntil": "networkidle2", "timeout": 30000},
                        # Scripts and styles must remain available for SPA hydration.
                        "rejectResourceTypes": ["image", "media", "font"],
                    },
                )
            except CloudflareRateLimitError as exc:
                if attempts >= self.rate_limit_retries:
                    raise
                attempts += 1
                delay = exc.retry_after_seconds
                if delay is None or delay <= 0:
                    delay = self.content_request_interval_seconds
                await self.sleep(delay)
                continue
            if not isinstance(html, str) or not html.strip():
                raise CloudflareCrawlError("Cloudflare Browser Rendering returned empty content")
            return html

    async def _wait_for_content_slot(self) -> None:
        if self._last_content_request_started_at is not None:
            elapsed = self.monotonic() - self._last_content_request_started_at
            remaining = self.content_request_interval_seconds - elapsed
            if remaining > 0:
                await self.sleep(remaining)
        self._last_content_request_started_at = self.monotonic()

    @staticmethod
    def _effective_port(parsed) -> Optional[int]:
        try:
            if parsed.port is not None:
                return parsed.port
        except ValueError:
            return None
        if parsed.scheme == "https":
            return 443
        if parsed.scheme == "http":
            return 80
        return None

    @classmethod
    def _same_origin(cls, root, candidate) -> bool:
        return (
            candidate.scheme.lower() == root.scheme.lower()
            and (candidate.hostname or "").lower() == (root.hostname or "").lower()
            and cls._effective_port(candidate) == cls._effective_port(root)
        )

    @staticmethod
    def _matches_patterns(
        url: str,
        include_regex: Optional[List[re.Pattern]],
        exclude_regex: Optional[List[re.Pattern]],
    ) -> bool:
        if exclude_regex and any(pattern.search(url) for pattern in exclude_regex):
            return False
        if include_regex and not any(pattern.search(url) for pattern in include_regex):
            return False
        return True

    @classmethod
    def _canonical_url(cls, url: str) -> str:
        parsed = urlparse(url)
        path = parsed.path or "/"
        return urlunparse((parsed.scheme.lower(), parsed.netloc.lower(), path, "", parsed.query, ""))

    @classmethod
    def _is_valid_navigation_url(cls, url: str) -> bool:
        """Reject malformed hrefs before they reach the rendered-browser API."""
        decoded = unquote(url)
        return not any(
            character in cls._INVALID_NAVIGATION_CHARACTERS or ord(character) < 32
            for character in decoded
        )

    @classmethod
    def _discover_urls(cls, html: str, *, current_url: str, root) -> List[str]:
        soup = BeautifulSoup(html, "html.parser")
        discovered: List[str] = []
        for anchor in soup.find_all("a", href=True):
            href = str(anchor["href"]).strip()
            if (
                not href
                or href.startswith(("#", "javascript:", "mailto:", "tel:"))
                or not cls._is_valid_navigation_url(href)
            ):
                continue
            candidate = cls._canonical_url(urljoin(current_url, href))
            if not cls._is_valid_navigation_url(candidate):
                continue
            parsed = urlparse(candidate)
            if not cls._same_origin(root, parsed):
                continue
            if parsed.path.lower().endswith(cls._SKIPPED_FILE_SUFFIXES):
                continue
            discovered.append(candidate)
        return list(dict.fromkeys(discovered))

    @classmethod
    def _html_to_page(
        cls,
        html: str,
        *,
        url: str,
        root,
        include_regex: Optional[List[re.Pattern]],
        exclude_regex: Optional[List[re.Pattern]],
    ) -> Optional[Dict]:
        parsed = urlparse(url)
        if not cls._same_origin(root, parsed):
            return None
        if not cls._matches_patterns(url, include_regex, exclude_regex):
            return None

        soup = BeautifulSoup(html, "html.parser")
        title = soup.title.get_text(" ", strip=True) if soup.title else ""
        extraction_soup = BeautifulSoup(html, "html.parser")
        for element in extraction_soup.find_all(["script", "style", "nav", "footer", "header", "aside"]):
            element.decompose()
        main_content = (
            extraction_soup.find("main")
            or extraction_soup.find("article")
            or extraction_soup.find("body")
        )
        content = main_content.get_text(separator="\n", strip=True) if main_content else ""
        content = re.sub(r"\n{3,}", "\n\n", content)
        content = re.sub(r" {2,}", " ", content).strip()
        if len(content) < 50:
            return None

        return {
            "url": url,
            "title": title,
            "content": content,
            "html": html,
            "metadata": {
                "content_length": len(content),
                "word_count": len(content.split()),
                "crawl_strategy": "cloudflare-content",
            },
        }
