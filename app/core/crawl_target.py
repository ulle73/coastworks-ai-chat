"""Network-boundary validation for every URL fetched by the crawler."""

import asyncio
import ipaddress
import socket
from collections.abc import Awaitable, Callable
from typing import Optional
from urllib.parse import urlparse

import aiohttp
from aiohttp.abc import AbstractResolver


class CrawlTargetValidationError(ValueError):
    """Raised when a crawl target can reach a non-public network."""


def _is_public_address(address: str) -> bool:
    try:
        return ipaddress.ip_address(address).is_global
    except ValueError:
        return False


async def _resolve_public_host(hostname: str) -> list[str]:
    loop = asyncio.get_running_loop()
    answers = await loop.getaddrinfo(
        hostname,
        None,
        family=socket.AF_UNSPEC,
        type=socket.SOCK_STREAM,
    )
    return list({answer[4][0] for answer in answers})


async def validate_crawl_target(
    url: str,
    *,
    resolve_host: Optional[Callable[[str], Awaitable[list[str]]]] = None,
) -> None:
    """Reject URLs that do not resolve exclusively to public HTTP(S) endpoints."""
    parsed = urlparse(url)
    if parsed.scheme.lower() not in {"http", "https"}:
        raise CrawlTargetValidationError("Crawler only supports HTTP(S) targets")
    if not parsed.hostname:
        raise CrawlTargetValidationError("Crawl target must include a hostname")
    if parsed.username or parsed.password:
        raise CrawlTargetValidationError("Crawl targets must not include credentials")

    host = parsed.hostname
    try:
        addresses = [str(ipaddress.ip_address(host))]
    except ValueError:
        resolver = resolve_host or _resolve_public_host
        try:
            addresses = await resolver(host)
        except (OSError, socket.gaierror) as exc:
            raise CrawlTargetValidationError("Crawl target hostname could not be resolved") from exc

    if not addresses:
        raise CrawlTargetValidationError("Crawl target hostname resolved to no addresses")
    if any(not _is_public_address(address) for address in addresses):
        raise CrawlTargetValidationError("Crawl target resolves to a forbidden network address")


class PublicAddressResolver(AbstractResolver):
    """Revalidates DNS answers immediately before aiohttp opens a connection."""

    def __init__(self) -> None:
        self._delegate = aiohttp.resolver.DefaultResolver()

    async def resolve(self, host: str, port: int = 0, family: int = socket.AF_INET):
        answers = await self._delegate.resolve(host, port, family)
        if not answers or any(not _is_public_address(answer["host"]) for answer in answers):
            raise CrawlTargetValidationError("Crawl target resolves to a forbidden network address")
        return answers

    async def close(self) -> None:
        await self._delegate.close()
