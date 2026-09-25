import httpx

from app.config import settings
from app.main import app


async def test_api_root_redirects_to_canonical_app():
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="https://coastworks-ai-chat-api.onrender.com",
        follow_redirects=False,
    ) as client:
        response = await client.get("/")

    assert response.status_code == 307
    assert response.headers["location"] == settings.APP_ORIGIN.rstrip("/") + "/"


async def test_canonical_root_still_serves_the_app():
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url=settings.APP_ORIGIN,
    ) as client:
        response = await client.get("/")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]


async def test_embed_stays_on_api_origin():
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="https://coastworks-ai-chat-api.onrender.com",
        follow_redirects=False,
    ) as client:
        response = await client.get("/embed/00000000-0000-0000-0000-000000000001")

    assert response.status_code == 200
    assert "location" not in response.headers
