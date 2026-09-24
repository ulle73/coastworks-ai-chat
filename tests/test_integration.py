import asyncio
import uuid
from unittest.mock import AsyncMock

import httpx
import numpy as np
import pytest
from langchain_core.documents import Document

from app.config import settings
from app.crawl import CrawlFailure, CrawlResult
from app.db import one, transaction
from app.main import app
from app.security import digest
from app.worker import claim, publish

pytestmark = pytest.mark.usefixtures("database")


def client():
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url=settings.APP_ORIGIN,
        headers={"Origin": settings.APP_ORIGIN},
    )


async def seed(db, identity="preview"):
    bot_id, job_id = uuid.uuid4(), uuid.uuid4()
    await db.execute(
        "INSERT INTO bots(id,url,origin,preview_hash,install_nonce,expires_at) VALUES(%s,'https://example.com/','https://example.com',%s,'install',now()+interval '1 day')",
        (bot_id, digest(identity)),
    )
    await db.execute("INSERT INTO jobs(id,bot_id) VALUES(%s,%s)", (job_id, bot_id))
    return bot_id, job_id


async def test_atomic_admission_and_private_preview(monkeypatch):
    monkeypatch.setattr("app.main.validate_crawl_target", AsyncMock())
    async with client() as alice, client() as bob:
        response = await alice.post("/api/previews", json={"url": "example.com"})
        assert response.status_code == 202
        bot_id = response.json()["id"]
        assert (await alice.get(f"/api/bots/{bot_id}")).status_code == 200
        assert (await bob.get(f"/api/bots/{bot_id}")).status_code in {401, 404}
        assert (await alice.post(f"/api/bots/{bot_id}/chat", json={"message": "Hej"})).status_code == 409
        async with transaction() as db:
            assert (await one(db, "SELECT count(*) AS n FROM jobs WHERE bot_id=%s", (uuid.UUID(bot_id),)))[
                "n"
            ] == 1


async def test_csrf_and_body_limits():
    async with client() as c:
        assert (
            await c.post(
                "/api/previews", json={"url": "example.com"}, headers={"Origin": "https://evil.example"}
            )
        ).status_code == 403
        assert (await c.post("/api/previews", content="x" * 17000)).status_code == 413


async def test_fenced_atomic_publication_and_isolated_vectors():
    async with transaction() as db:
        bot_a, _ = await seed(db, "a")
        bot_b, _ = await seed(db, "b")
    first, second = await asyncio.gather(claim(), claim())
    assert first["id"] != second["id"]
    job_a, job_b = sorted([first, second], key=lambda j: j["bot_id"] != bot_a)
    result = CrawlResult(pages=[{"content": "word " * 350}], attempted=1, discovered=1)
    doc_a = Document(page_content="Tenant A only", metadata={"url": "https://example.com/a", "title": "A"})
    doc_b = Document(page_content="Tenant B secret", metadata={"url": "https://example.com/b", "title": "B"})
    await publish(job_a, result, [doc_a], [[1, 0, 0]])
    await publish(job_b, result, [doc_b], [[1, 0, 0]])
    async with transaction() as db:
        rows = await (
            await db.execute(
                "SELECT content FROM chunks WHERE bot_id=%s ORDER BY embedding <=> %s",
                (bot_a, np.array([1, 0, 0])),
            )
        ).fetchall()
        assert [r["content"] for r in rows] == ["Tenant A only"]
        bot = await one(db, "SELECT * FROM bots WHERE id=%s", (bot_a,))
        assert bot["state"] == "ready" and bot["active_version"] == job_a["id"]
    with pytest.raises(CrawlFailure, match="LEASE_LOST"):
        await publish(job_a, result, [doc_a], [[1, 0, 0]])


async def test_dead_worker_recovery_and_stale_fence():
    async with transaction() as db:
        bot_id, _ = await seed(db)
    stale = await claim()
    async with transaction() as db:
        await db.execute("UPDATE jobs SET lease_until=now()-interval '1 second' WHERE id=%s", (stale["id"],))
    resumed = await claim()
    assert resumed["id"] == stale["id"] and resumed["lease_token"] != stale["lease_token"]
    result = CrawlResult(pages=[{"content": "word " * 350}], attempted=1, discovered=1)
    doc = Document(page_content="A", metadata={"url": "https://example.com", "title": "A"})
    with pytest.raises(CrawlFailure, match="LEASE_LOST"):
        await publish(stale, result, [doc], [[1, 0]])
    await publish(resumed, result, [doc], [[1, 0]])


async def test_failed_candidate_preserves_previous_index():
    async with transaction() as db:
        bot_id, _ = await seed(db)
    old = await claim()
    result = CrawlResult(pages=[{"content": "word " * 350}], attempted=1, discovered=1)
    doc = Document(page_content="A", metadata={"url": "https://example.com", "title": "A"})
    await publish(old, result, [doc], [[1, 0]])
    async with transaction() as db:
        await db.execute("INSERT INTO jobs(id,bot_id) VALUES(%s,%s)", (uuid.uuid4(), bot_id))
    new = await claim()
    with pytest.raises(CrawlFailure, match="INVALID_INDEX"):
        await publish(new, CrawlResult(), [], [])
    async with transaction() as db:
        assert (await one(db, "SELECT active_version FROM bots WHERE id=%s", (bot_id,)))[
            "active_version"
        ] == old["id"]


async def test_email_single_use_and_install_gate(monkeypatch):
    mail = AsyncMock()
    monkeypatch.setattr("app.main.send_claim", mail)
    async with transaction() as db:
        bot_id, _ = await seed(db)
        await db.execute(
            "UPDATE bots SET state='ready',active_version=%s WHERE id=%s", (uuid.uuid4(), bot_id)
        )
    async with client() as c:
        c.cookies.set("cw_preview", "preview")
        assert (await c.get(f"/api/bots/{bot_id}/installation")).status_code == 401
        response = await c.post(f"/api/bots/{bot_id}/claim", json={"email": "owner@example.com"})
        assert response.status_code == 202
        token = mail.call_args.args[1]
        confirmed = await c.post("/api/confirm", json={"token": token})
        assert confirmed.status_code == 200
        assert (await c.post("/api/confirm", json={"token": token})).status_code == 400
        assert (await c.get(f"/api/bots/{bot_id}/installation")).status_code == 200
        assert (
            await c.post(f"/api/widget/{bot_id}/session", headers={"Origin": "https://example.com"})
        ).status_code == 403


async def test_widget_cors_is_exact_and_no_wildcards():
    async with transaction() as db:
        bot_id, _ = await seed(db)
        await db.execute(
            "UPDATE bots SET state='ready',active_version=%s,owner_email='a@example.com',published=true WHERE id=%s",
            (uuid.uuid4(), bot_id),
        )
    async with client() as c:
        good = await c.options(f"/api/widget/{bot_id}/session", headers={"Origin": "https://example.com"})
        assert good.status_code == 204
        assert good.headers["access-control-allow-origin"] == "https://example.com"
        bad = await c.options(
            f"/api/widget/{bot_id}/session", headers={"Origin": "https://example.com.evil.test"}
        )
        assert bad.status_code == 403 and "access-control-allow-origin" not in bad.headers


async def test_rate_limit_cannot_be_bypassed_by_concurrency():
    from fastapi import HTTPException

    from app.security import rate_limit

    async def attempt():
        try:
            async with transaction() as db:
                await rate_limit(db, "race", 3, 60)
            return True
        except HTTPException:
            return False

    assert sum(await asyncio.gather(*(attempt() for _ in range(10)))) == 3


async def test_real_rag_path_scopes_context_history_and_current_version(monkeypatch):
    import json
    from types import SimpleNamespace

    from app.knowledge import Evidence, GroundedAnswer, Ranking, answer

    async with transaction() as db:
        bot_a, _ = await seed(db, "a")
        bot_b, _ = await seed(db, "b")
    jobs = [await claim(), await claim()]
    result = CrawlResult(pages=[{"content": "word " * 350}], attempted=1, discovered=1)
    for job in jobs:
        text = "ALICE_PUBLIC" if job["bot_id"] == bot_a else "BOB_PRIVATE"
        await publish(
            job,
            result,
            [Document(page_content=text, metadata={"url": "https://example.com", "title": text})],
            [[1, 0, 0]],
        )
    async with transaction() as db:
        await db.execute(
            "INSERT INTO messages(bot_id,session_hash,role,content) VALUES(%s,'shared','user','BOB_HISTORY')",
            (bot_b,),
        )
        bot = await one(db, "SELECT * FROM bots WHERE id=%s", (bot_a,))
    # A bot snapshot may predate a concurrent refresh. Retrieval must read the current pointer atomically.
    bot["active_version"] = uuid.uuid4()
    embeddings = SimpleNamespace(aembed_query=AsyncMock(return_value=[1, 0, 0]))
    invoke = AsyncMock(side_effect=[Ranking(ids=[0]), GroundedAnswer(
        answer="Alice svar", evidence=[Evidence(id=0)])])
    llm = SimpleNamespace(with_structured_output=lambda schema: SimpleNamespace(ainvoke=invoke))
    monkeypatch.setattr("app.knowledge.get_embeddings", lambda: embeddings)
    monkeypatch.setattr("app.knowledge.get_llm", lambda **kwargs: llm)
    response = await answer(bot, "Hej", "shared")
    prompt = json.loads(invoke.call_args.args[0][1].content)
    assert "ALICE_PUBLIC" in str(prompt)
    assert "BOB" not in str(prompt)
    assert response["answer"] == "Alice svar"


async def test_installation_requires_matching_nonce(monkeypatch):
    from app.security import signer

    async with transaction() as db:
        bot_id, _ = await seed(db)
        await db.execute(
            "UPDATE bots SET owner_email='owner@example.com',state='ready',active_version=%s WHERE id=%s",
            (uuid.uuid4(), bot_id),
        )
    fetch = AsyncMock(
        return_value=(200, '<script src="https://evil.example/widget.js"></script>', "https://example.com/")
    )
    monkeypatch.setattr("app.main.Fetcher.get", fetch)
    async with client() as c:
        c.cookies.set("cw_owner", signer.dumps({"email": "owner@example.com"}, salt="owner-v1"))
        assert (await c.post(f"/api/bots/{bot_id}/publish")).status_code == 409
        fetch.return_value = (
            200,
            f'<script src="{settings.APP_ORIGIN}/widget.js" data-bot="{bot_id}" data-install="install"></script>',
            "https://example.com/",
        )
        assert (await c.post(f"/api/bots/{bot_id}/publish")).json()["published"] is True
        session = await c.post(f"/api/widget/{bot_id}/session", headers={"Origin": "https://example.com"})
        assert session.status_code == 200 and session.json()["token"]


async def test_recovery_does_not_reveal_account_membership(monkeypatch):
    mail = AsyncMock()
    monkeypatch.setattr("app.main.send_claim", mail)
    async with transaction() as db:
        bot_id, _ = await seed(db)
        await db.execute("UPDATE bots SET owner_email='owner@example.com' WHERE id=%s", (bot_id,))
    async with client() as c:
        known = await c.post("/api/access", json={"email": "owner@example.com"})
        unknown = await c.post("/api/access", json={"email": "unknown@example.com"})
        assert known.status_code == unknown.status_code == 202
        assert known.json() == unknown.json()
        mail.assert_awaited_once()
