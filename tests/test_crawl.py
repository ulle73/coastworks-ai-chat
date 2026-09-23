from unittest.mock import AsyncMock

import pytest

from app.crawl import CrawlFailure, CrawlResult, crawl
from app.knowledge import valid_vectors


def html(name, words=170, links=""):
    return (
        f"<html><title>{name}</title><body><main>"
        + ((name + " tjänster kunder kontakt information ") * words)
        + f"</main>{links}</body></html>"
    )


class Fetch:
    def __init__(self, pages, robots="User-agent: *\nAllow: /"):
        self.pages, self.robots = pages, robots
        self.urls = []

    async def get(self, url, **kwargs):
        self.urls.append(url)
        if url.endswith("/robots.txt"):
            return 200, self.robots, url
        if url.endswith("/sitemap.xml"):
            return 404, "", url
        return (200, self.pages[url], url) if url in self.pages else (404, "", url)


async def test_static_site_avoids_browser():
    renderer = AsyncMock()
    result = await crawl(
        "https://company.example/", Fetch({"https://company.example/": html("Company")}), renderer
    )
    assert result.quality()["passed"]
    renderer.render.assert_not_called()


async def test_react_shell_renders_and_discovers_links():
    renderer = AsyncMock()
    renderer.render.return_value = html("Hem", links='<a href="/contact">Kontakt</a>')
    fetch = Fetch(
        {
            "https://company.example/": '<div id="root"></div><script type="module" src="/app.js"></script>',
            "https://company.example/contact": html("Kontakt"),
        }
    )
    result = await crawl("https://company.example/", fetch, renderer)
    assert len(result.pages) == 2
    renderer.render.assert_awaited_once()


async def test_next_partial_shell_uses_rendering():
    renderer = AsyncMock()
    renderer.render.return_value = html("Company")
    await crawl(
        "https://company.example/",
        Fetch(
            {"https://company.example/": '<main>Loading products</main><script src="/_next/a.js"></script>'}
        ),
        renderer,
    )
    renderer.render.assert_awaited_once()


async def test_robots_denial_cannot_be_bypassed_with_renderer():
    renderer = AsyncMock()
    with pytest.raises(CrawlFailure, match="ROBOTS_DENIED"):
        await crawl("https://company.example/", Fetch({}, "User-agent: *\nDisallow: /"), renderer)
    renderer.render.assert_not_called()


async def test_challenge_is_not_knowledge():
    renderer = AsyncMock()
    with pytest.raises(CrawlFailure):
        await crawl(
            "https://company.example/",
            Fetch(
                {"https://company.example/": "<title>Just a moment</title>" + html("verify you are human")}
            ),
            renderer,
        )
    renderer.render.assert_not_called()


async def test_empty_render_never_ready():
    renderer = AsyncMock()
    renderer.render.return_value = "<html><body></body></html>"
    with pytest.raises(CrawlFailure, match="INSUFFICIENT_CONTENT"):
        await crawl(
            "https://company.example/",
            Fetch({"https://company.example/": '<div id="app"></div><script type="module"></script>'}),
            renderer,
        )


def test_single_page_of_large_broken_site_not_sufficient():
    result = CrawlResult(pages=[{"content": "word " * 1000}], attempted=8, discovered=80, failed=7)
    assert not result.quality()["passed"]


def test_invalid_embeddings_rejected():
    assert not valid_vectors([], 0)
    assert not valid_vectors([[float("nan"), 1]], 1)
    assert not valid_vectors([[0, 0]], 1)
    assert not valid_vectors([[1], [1, 2]], 2)
    assert valid_vectors([[1, 2]], 1)
