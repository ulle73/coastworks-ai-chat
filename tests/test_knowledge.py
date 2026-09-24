import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import numpy as np
import pytest

from app import knowledge
from app.chunking import Chunker
from app.config import settings
from app.crawl import extract
from app.db import transaction
from app.knowledge import Evidence, GroundedAnswer, Ranking, SearchQuery


def test_html_heading_and_faq_survive_splitting():
    page = extract(
        "<main><h1>Företagsbeställning</h1><h2>Presentkort</h2>"
        "<h3>Giltighetstid</h3><p>Inköpsåret plus nästa år.</p>"
        "<details><summary>Kan de förlängas?</summary><p>Nej, de kan inte förlängas.</p></details>"
        "</main>",
        "https://example.com/info",
    )
    chunks = Chunker()._create_chunks(page, "tenant")
    assert any(
        "Företagsbeställning > Presentkort > Giltighetstid" in d.page_content
        and "Inköpsåret plus nästa år." in d.page_content
        for d in chunks
    )
    assert any(
        "Kan de förlängas?" in d.page_content and "Nej, de kan inte förlängas." in d.page_content
        for d in chunks
    )


def test_large_section_repeats_context_without_losing_content():
    page = {
        "url": "https://example.com",
        "title": "Regler",
        "content": "# Företag\n## Giltighet\n" + ("En hel mening om villkor. " * 250) + "SLUTFAKTA",
    }
    chunks = Chunker()._create_chunks(page, "a")
    assert len(chunks) > 2
    assert all("Regler > Företag > Giltighet" in d.page_content for d in chunks)
    assert "SLUTFAKTA" in chunks[-1].page_content
    assert max(len(d.page_content) for d in chunks) <= 2402


def test_rrf_can_rescue_lexical_only_candidate_and_is_deterministic():
    dense = [{"ordinal": i} for i in range(32)]
    lexical = [{"ordinal": 99}]
    result = knowledge.fuse(dense, lexical, limit=24)
    assert {"ordinal": 99} in result
    assert len(result) == 24
    assert knowledge.fuse(dense, lexical) == knowledge.fuse(dense, lexical)


async def test_rewrite_is_bounded_and_empty_history_costs_nothing(monkeypatch):
    call = AsyncMock(return_value=SearchQuery(query="Gäller företagspresentkortens giltighet alla kuponger?"))
    monkeypatch.setattr(knowledge, "structured", call)
    assert await knowledge.rewrite("Hej", []) == "Hej"
    call.assert_not_awaited()
    query = await knowledge.rewrite("Gäller det alla?", [{"role": "user", "content": "Företagspresentkort?"}])
    assert "företagspresentkort" in query


async def test_invalid_reranker_ids_fail_closed(monkeypatch):
    monkeypatch.setattr(knowledge, "structured", AsyncMock(return_value=Ranking(ids=[99])))
    with pytest.raises(ValueError, match="INVALID_RANKING"):
        await knowledge.rerank("fråga", [{"title": "a", "content": "b"}])


@pytest.mark.parametrize("evidence", [[Evidence(id=9)], [Evidence(id=-1)], []])
async def test_unknown_citations_and_unbacked_answers_abstain(monkeypatch, evidence):
    monkeypatch.setattr(
        knowledge,
        "structured",
        AsyncMock(return_value=GroundedAnswer(answer="Gäller 24 månader", evidence=evidence)),
    )
    result = await knowledge.generate(
        "giltighet",
        "giltighet",
        [{"url": "https://example.com", "title": "Villkor", "content": "Gäller 12 månader"}],
    )
    assert result == {"answer": knowledge.FALLBACK, "sources": []}


async def test_embedding_batches_and_full_budget(monkeypatch):
    monkeypatch.setattr(settings, "EMBEDDING_BATCH_SIZE", 2)
    monkeypatch.setattr(settings, "PREVIEW_CHUNKS", 2)
    embedding = AsyncMock(side_effect=lambda texts: [[1.0, 0.0] for _ in texts])
    monkeypatch.setattr(knowledge, "get_embeddings", lambda: SimpleNamespace(aembed_documents=embedding))
    pages = [
        {"url": f"https://example.com/{i}", "title": "Info", "content": "Relevant information. " * 5}
        for i in range(5)
    ]
    with pytest.raises(ValueError, match="INDEX_BUDGET_EXCEEDED"):
        await knowledge.build(pages, "a")
    docs, vectors = await knowledge.build(pages, "a", full=True)
    assert len(docs) == len(vectors) == 5
    assert [len(c.args[0]) for c in embedding.call_args_list] == [2, 2, 1]


@pytest.mark.usefixtures("database")
async def test_independent_lexical_retrieval_tenant_version_and_embedding_scope(monkeypatch):
    bot, version, stale, other = uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    async with transaction() as db:
        for identity in [bot, other]:
            await db.execute(
                "INSERT INTO bots(id,url,origin,preview_hash,install_nonce,expires_at,active_version) VALUES(%s,'https://example.com','https://example.com','x','x',now(),%s)",
                (identity, version),
            )
        for identity, v, n, text, vector, model in [
            *[
                (bot, version, i, "Allmän sida om golf och gåvor", [1.0, 0.0, 0.0], settings.EMBEDDINGS_MODEL)
                for i in range(40)
            ],
            (
                bot,
                version,
                99,
                "Artikel ZX900 har livstidsgaranti",
                [0.0, 1.0, 0.0],
                settings.EMBEDDINGS_MODEL,
            ),
            (bot, stale, 99, "ZX900 STALE", [1.0, 0.0, 0.0], settings.EMBEDDINGS_MODEL),
            (other, version, 99, "ZX900 OTHER TENANT", [1.0, 0.0, 0.0], settings.EMBEDDINGS_MODEL),
            (bot, version, 100, "ZX900 har blå färg", [1.0, 0.0], "old-model"),
        ]:
            await db.execute(
                "INSERT INTO chunks(bot_id,version,ordinal,url,title,content,embedding,embedding_model) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)",
                (identity, v, n, f"https://example.com/{n}", "Info", text, np.asarray(vector), model),
            )
    monkeypatch.setattr(
        knowledge,
        "get_embeddings",
        lambda: SimpleNamespace(aembed_query=AsyncMock(return_value=[1.0, 0.0, 0.0])),
    )
    rows = await knowledge.retrieve(bot, "ZX900 livstidsgaranti")
    assert any(r["ordinal"] == 99 for r in rows)
    assert all("STALE" not in r["content"] and "OTHER TENANT" not in r["content"] for r in rows)
    # Old embedding models can still contribute independently through lexical retrieval.
    assert any(r["ordinal"] == 100 for r in rows)


@pytest.mark.usefixtures("database")
async def test_publication_during_preview_build_queues_full_ingestion():
    from langchain_core.documents import Document

    from app.crawl import CrawlResult
    from app.db import one
    from app.worker import claim, publish
    from tests.test_integration import seed

    async with transaction() as db:
        bot_id, _ = await seed(db)
    job = await claim()
    async with transaction() as db:
        await db.execute(
            "UPDATE bots SET owner_email='owner@example.com',published=true,active_version=%s WHERE id=%s",
            (uuid.uuid4(), bot_id),
        )
    await publish(
        job,
        CrawlResult(pages=[{"content": "word " * 350}], attempted=1, discovered=1),
        [Document(page_content="Valid source", metadata={"url": "https://example.com", "title": "Title"})],
        [[1.0, 0.0]],
    )
    async with transaction() as db:
        bot = await one(db, "SELECT * FROM bots WHERE id=%s", (bot_id,))
        assert bot["quality"]["ingestion_profile"] == "preview"
        assert (
            await one(db, "SELECT count(*) AS n FROM jobs WHERE bot_id=%s AND state='queued'", (bot_id,))
        )["n"] == 1
    full_job = await claim()
    assert full_job["bot"]["published"] is True


async def test_embedding_retry_is_bounded_and_only_for_transient_errors(monkeypatch):
    class RateLimited(Exception):
        code = 429

    call = AsyncMock(side_effect=[RateLimited(), [[1.0, 0.0]]])
    monkeypatch.setattr(knowledge, "get_embeddings", lambda: SimpleNamespace(aembed_documents=call))
    sleep = AsyncMock()
    monkeypatch.setattr(knowledge.asyncio, "sleep", sleep)
    assert await knowledge.embed_batch(["text"]) == [[1.0, 0.0]]
    assert call.await_count == 2
    sleep.assert_awaited_once_with(1)
    call.side_effect = ValueError("permanent")
    with pytest.raises(ValueError, match="permanent"):
        await knowledge.embed_batch(["text"])
    assert call.await_count == 3


def test_citations_are_resolved_from_the_retrieved_passages():
    rows = [{"url": "https://example.com/correct", "title": "Rätt källa", "content": "Fakta"}]
    value = GroundedAnswer(answer="Svar", evidence=[Evidence(id=0), Evidence(id=0)])
    assert knowledge.validated_answer(value, rows)["sources"] == [
        {"url": rows[0]["url"], "title": rows[0]["title"]}
    ]


def test_heading_only_facts_survive_without_indexing_empty_parent_sections():
    chunks = Chunker()._create_chunks(
        {
            "url": "https://example.com/partners",
            "title": "Partners",
            "content": "# Partners\n## Region\n### Klubb Alpha\n### Klubb Beta",
            "metadata": {"source_type": "document"},
        },
        "tenant",
    )
    assert len(chunks) == 2
    assert all("Partners > Region" in d.page_content for d in chunks)
    assert "Klubb Alpha" in chunks[0].page_content
    assert "Klubb Beta" in chunks[1].page_content
