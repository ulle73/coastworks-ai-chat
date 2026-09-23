"""Durable PostgreSQL queue: bounded attempts, renewable leases, fenced publication."""

import asyncio
import contextlib
import logging
import uuid

import numpy as np
from psycopg.types.json import Jsonb

from app.config import settings
from app.crawl import CrawlFailure, crawl
from app.db import one, pool, transaction
from app.knowledge import build

log = logging.getLogger("coastworks.worker")


async def claim():
    async with transaction() as db:
        # A dead final attempt must become terminal, never remain running forever.
        exhausted = await db.execute("""UPDATE jobs SET state='failed',error_code='WORKER_TIMEOUT',finished_at=now()
          WHERE state='running' AND lease_until<now() AND attempts>=3 RETURNING bot_id""")
        for row in await exhausted.fetchall():
            await db.execute(
                "UPDATE bots SET state=CASE WHEN active_version IS NULL THEN 'failed' ELSE 'ready' END,error_code='WORKER_TIMEOUT' WHERE id=%s",
                (row["bot_id"],),
            )
        job = await one(
            db,
            """SELECT j.* FROM jobs j JOIN bots b ON b.id=j.bot_id WHERE j.state='queued' OR
          (j.state='running' AND j.lease_until<now() AND j.attempts<3)
          ORDER BY (b.active_version IS NULL) DESC, j.created_at FOR UPDATE OF j SKIP LOCKED LIMIT 1""",
        )
        if not job:
            return None
        token = uuid.uuid4()
        await db.execute(
            "UPDATE jobs SET state='running',attempts=attempts+1,lease_token=%s,lease_until=now()+interval '60 seconds' WHERE id=%s",
            (token, job["id"]),
        )
        bot = await one(db, "SELECT * FROM bots WHERE id=%s", (job["bot_id"],))
        await db.execute("UPDATE bots SET state='reading',error_code=NULL WHERE id=%s", (bot["id"],))
        return {**job, "lease_token": token, "bot": bot}


async def heartbeat(job):
    while True:
        await asyncio.sleep(15)
        async with transaction() as db:
            updated = await db.execute(
                "UPDATE jobs SET lease_until=now()+interval '60 seconds' WHERE id=%s AND lease_token=%s AND state='running' AND lease_until>now()",
                (job["id"], job["lease_token"]),
            )
            if updated.rowcount != 1:
                raise CrawlFailure("LEASE_LOST")


async def publish(job, result, chunks, vectors):
    async with transaction() as db:
        fence = await one(
            db,
            "SELECT id FROM jobs WHERE id=%s AND lease_token=%s AND lease_until>now() AND state='running' FOR UPDATE",
            (job["id"], job["lease_token"]),
        )
        if not fence:
            raise CrawlFailure("LEASE_LOST")
        if not result.quality()["passed"] or not chunks or len(chunks) != len(vectors):
            raise CrawlFailure("INVALID_INDEX")
        for i, (chunk, vector) in enumerate(zip(chunks, vectors, strict=True)):
            await db.execute(
                "INSERT INTO chunks(bot_id,version,ordinal,url,title,content,embedding,embedding_model) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    job["bot_id"],
                    job["id"],
                    i,
                    chunk.metadata["url"],
                    chunk.metadata["title"],
                    chunk.page_content,
                    np.asarray(vector),
                    settings.EMBEDDINGS_MODEL,
                ),
            )
        # Verify retrieval from the persisted candidate in the SAME transaction before publication.
        probe = await one(
            db,
            "SELECT ordinal, embedding <=> %s AS distance FROM chunks WHERE bot_id=%s AND version=%s ORDER BY embedding <=> %s LIMIT 1",
            (np.asarray(vectors[0]), job["bot_id"], job["id"], np.asarray(vectors[0])),
        )
        if not probe or probe["distance"] > 0.01:
            raise CrawlFailure("INDEX_READBACK_FAILED")
        await db.execute(
            "UPDATE bots SET active_version=%s,quality=%s,state='ready',error_code=NULL,refreshed_at=now() WHERE id=%s",
            (job["id"], Jsonb(result.quality()), job["bot_id"]),
        )
        # robots canonicalization may legitimately upgrade http or add/remove www.
        from app.security import origin

        canonical_url = (
            result.pages[0]["url"] if result.pages and "url" in result.pages[0] else job["bot"]["url"]
        )
        await db.execute(
            "UPDATE bots SET url=%s,origin=%s WHERE id=%s",
            (canonical_url, origin(canonical_url), job["bot_id"]),
        )
        await db.execute(
            "UPDATE jobs SET state='done',finished_at=now(),lease_until=NULL WHERE id=%s", (job["id"],)
        )
        await db.execute("DELETE FROM chunks WHERE bot_id=%s AND version<>%s", (job["bot_id"], job["id"]))


async def process(job):
    renewal = asyncio.create_task(heartbeat(job))
    try:
        async with asyncio.timeout(170):
            result = await crawl(job["bot"]["url"])
            log.info(
                "crawl_quality job=%s pages=%s words=%s attempted=%s discovered=%s rendered=%s failed=%s denied=%s success_ratio=%s",
                job["id"],
                result.quality()["pages"],
                result.quality()["words"],
                result.quality()["attempted"],
                result.quality()["discovered"],
                result.quality()["rendered"],
                result.quality()["failed"],
                result.quality()["denied"],
                result.quality()["success_ratio"],
            )
            async with transaction() as db:
                sources = await (
                    await db.execute(
                        "SELECT title,source_url AS url,content FROM managed_sources WHERE bot_id=%s AND approved_public=true",
                        (job["bot_id"],),
                    )
                ).fetchall()
                await db.execute(
                    "UPDATE bots SET state='checking' WHERE id=%s AND EXISTS(SELECT 1 FROM jobs WHERE id=%s AND lease_token=%s AND state='running')",
                    (job["bot_id"], job["id"], job["lease_token"]),
                )
            chunks, vectors = await build(
                result.pages + [{**s, "metadata": {"source_type": "document"}} for s in sources],
                job["bot_id"],
            )
            if renewal.done():
                renewal.result()
            await publish(job, result, chunks, vectors)
        log.info("job_complete job=%s pages=%s", job["id"], len(result.pages))
    except Exception as exc:
        code = exc.code if isinstance(exc, CrawlFailure) else "BUILD_FAILED"
        # No provider exceptions, source text, URLs, emails or secrets in logs.
        log.warning("job_failed job=%s code=%s type=%s", job["id"], code, type(exc).__name__)
        async with transaction() as db:
            row = await one(
                db,
                "UPDATE jobs SET state='failed',error_code=%s,finished_at=now() WHERE id=%s AND lease_token=%s AND state='running' RETURNING bot_id",
                (code, job["id"], job["lease_token"]),
            )
            if row:
                await db.execute(
                    "UPDATE bots SET state=CASE WHEN active_version IS NULL THEN 'failed' ELSE 'ready' END,error_code=%s WHERE id=%s",
                    (code, job["bot_id"]),
                )
    finally:
        renewal.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await renewal


async def maintenance():
    async with transaction() as db:
        await db.execute("DELETE FROM bots WHERE owner_email IS NULL AND expires_at<now()")
        await db.execute("DELETE FROM email_tokens WHERE expires_at<now()-interval '1 day'")
        await db.execute("DELETE FROM rate_limits WHERE expires_at<now()-interval '1 day'")
        await db.execute("DELETE FROM messages WHERE created_at<now()-interval '30 days'")
        await db.execute(
            "DELETE FROM managed_requests WHERE state='closed' AND created_at<now()-interval '90 days'"
        )
        # Only published bots get weekly refresh; failed refresh keeps the last good snapshot.
        await db.execute("""INSERT INTO jobs(id,bot_id)
          SELECT gen_random_uuid(),b.id FROM bots b WHERE b.published AND b.refreshed_at<now()-interval '7 days'
          AND NOT EXISTS(SELECT 1 FROM jobs j WHERE j.bot_id=b.id AND j.created_at>now()-interval '1 day')
          ON CONFLICT DO NOTHING""")


async def run_loop():
    logging.basicConfig(level=logging.INFO)
    while True:
        await maintenance()
        job = await claim()
        if job:
            await process(job)
        else:
            await asyncio.sleep(3)


async def main():
    await pool.open(wait=True)
    try:
        await run_loop()
    finally:
        await pool.close()


if __name__ == "__main__":
    from app.runtime import run

    run(main())
