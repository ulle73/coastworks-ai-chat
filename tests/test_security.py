from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.core.crawl_target import CrawlTargetValidationError, validate_crawl_target
from app.crawl import Fetcher
from app.security import digest, normalize_url, require_preview, signer, widget_identity


@pytest.mark.parametrize(
    "url", ["http://127.0.0.1", "http://[::1]", "http://169.254.169.254", "ftp://example.com"]
)
async def test_private_targets_rejected(url):
    with pytest.raises(CrawlTargetValidationError):
        await validate_crawl_target(url)


async def test_mixed_dns_rejected():
    with pytest.raises(CrawlTargetValidationError):
        await validate_crawl_target(
            "https://business.example", resolve_host=AsyncMock(return_value=["1.1.1.1", "10.0.0.1"])
        )


@pytest.mark.parametrize(
    "value",
    [
        "https://user:pass@example.com",
        "https://example.com:22/",
        "javascript:alert(1)",
        "https://example.com\\@evil.com",
        "https://example.com/a\n",
    ],
)
def test_url_boundary(value):
    # Trailing whitespace is intentionally normalized; embedded controls are not.
    if value.endswith("\n"):
        value = value.replace("a\n", "a\nb")
    with pytest.raises(ValueError):
        normalize_url(value)


def request(headers):
    return Request({"type": "http", "headers": [(k.encode(), v.encode()) for k, v in headers.items()]})


def test_preview_cannot_cross_tenants():
    with pytest.raises(HTTPException):
        require_preview(request({"cookie": "cw_preview=alice"}), {"preview_hash": digest("bob")})


def test_widget_token_bound_to_bot():
    token = signer.dumps({"bot": "a", "session": "visitor"})
    with pytest.raises(HTTPException):
        widget_identity(request({"authorization": "Bearer " + token}), "b")


async def test_redirect_to_metadata_never_connects():
    class Redirect:
        status = 302
        headers = {"Location": "http://169.254.169.254/latest/meta-data"}

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

    class Session:
        calls = 0

        def get(self, *args, **kwargs):
            self.calls += 1
            return Redirect()

    fetcher = Fetcher()
    fetcher.session = Session()
    with pytest.raises(CrawlTargetValidationError):
        await fetcher.get("http://1.1.1.1")
    assert fetcher.session.calls == 1
