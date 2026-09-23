"""Operator-only commands; requires database credentials, never exposed as a public API."""

import argparse
import json
import uuid
from pathlib import Path

from app.db import one, pool, transaction
from app.runtime import run as run_async
from app.security import normalize_url


async def run(args):
    await pool.open(wait=True)
    try:
        async with transaction() as db:
            if args.command == "requests":
                rows = await (
                    await db.execute(
                        "SELECT id,email,website,message,state,created_at FROM managed_requests ORDER BY created_at DESC LIMIT 50"
                    )
                ).fetchall()
                print(json.dumps(rows, default=str, ensure_ascii=False, indent=2))
                return
            if args.command == "request-status":
                result = await db.execute(
                    "UPDATE managed_requests SET state=%s WHERE id=%s", (args.state, uuid.UUID(args.id))
                )
                if not result.rowcount:
                    raise ValueError("Request not found")
                print("Request updated")
                return
            bot_id = uuid.UUID(args.bot)
            bot = await one(db, "SELECT * FROM bots WHERE id=%s", (bot_id,))
            if not bot:
                raise ValueError("Bot not found")
            if args.command == "unpublish":
                await db.execute("UPDATE bots SET published=false WHERE id=%s", (bot_id,))
                print("Widget disabled")
            if args.command == "import-text":
                if not args.approved_public:
                    raise ValueError(
                        "Only explicitly approved public material may enter the website assistant"
                    )
                source = Path(args.file)
                if source.stat().st_size > 100_000:
                    raise ValueError("Document exceeds the managed ingestion budget")
                content = source.read_text(encoding="utf-8")
                await db.execute(
                    "INSERT INTO managed_sources(id,bot_id,title,source_url,content,approved_public) VALUES(%s,%s,%s,%s,%s,true)",
                    (uuid.uuid4(), bot_id, args.title, normalize_url(args.source_url), content),
                )
            if args.command in {"refresh", "import-text"}:
                await db.execute(
                    "INSERT INTO jobs(id,bot_id) VALUES(%s,%s) ON CONFLICT DO NOTHING", (uuid.uuid4(), bot_id)
                )
                print("Refresh queued; existing published knowledge remains active until validation passes")
    finally:
        await pool.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("requests")
    update = commands.add_parser("request-status")
    update.add_argument("id")
    update.add_argument("state", choices=["new", "contacted", "onboarding", "active", "closed"])
    for command in ["refresh", "unpublish", "import-text"]:
        sub = commands.add_parser(command)
        sub.add_argument("bot")
        if command == "import-text":
            sub.add_argument("file")
            sub.add_argument("--title", required=True)
            sub.add_argument(
                "--source-url", required=True, help="Public source or contact URL shown to visitors"
            )
            sub.add_argument("--approved-public", action="store_true")
    run_async(run(parser.parse_args()))


if __name__ == "__main__":
    main()
