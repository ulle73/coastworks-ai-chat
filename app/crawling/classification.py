"""Pure classification helpers for deciding when browser rendering is required."""

from __future__ import annotations

import re

from bs4 import BeautifulSoup

_CLIENT_BUNDLE_RE = re.compile(
    r"(?:^|/)(?:assets?|static/js|build|dist)/.*\.m?js(?:\?|$)|"
    r"(?:^|/)(?:main|index|app|bundle|chunk)[._-].*\.m?js(?:\?|$)|"
    r"(?:vite|webpack|react|vue|angular)",
    re.IGNORECASE,
)


def requires_browser_rendering(
    html: str,
    extracted_text: str,
    *,
    useful_text_threshold: int = 100,
) -> bool:
    """Return True only for a convincing client-rendered application shell.

    Short HTML alone is not enough: error pages, login blocks, rate-limit pages,
    and genuinely small static pages must not be hidden behind a browser fallback.
    The classifier requires both insufficient static text and an empty common
    application mount plus a client JavaScript signal.
    """
    text = (extracted_text or "").strip()
    if len(text) >= useful_text_threshold:
        return False
    if not html:
        return False

    soup = BeautifulSoup(html, "html.parser")
    # Next.js app-router shells need not have a #root/#app mount.
    next_bundle = soup.find("script", src=re.compile(r"/_next/"))
    mount = soup.find(id="root") or soup.find(id="app") or (soup.find("main") if next_bundle else None)
    if mount is None:
        return False

    mount_text = mount.get_text(" ", strip=True)
    if len(mount_text) >= useful_text_threshold:
        return False

    for script in soup.find_all("script"):
        script_type = str(script.get("type") or "").lower()
        src = str(script.get("src") or "")
        if script_type == "module":
            return True
        if src and (_CLIENT_BUNDLE_RE.search(src) or "/_next/" in src):
            return True

    return False
