from contextlib import asynccontextmanager
from pathlib import Path

from pgvector.psycopg import register_vector_async
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from app.config import settings


async def configure(connection):
    await register_vector_async(connection)
    await connection.commit()


pool = AsyncConnectionPool(
    settings.DATABASE_URL,
    open=False,
    min_size=1,
    max_size=12,
    kwargs={
        "row_factory": dict_row,
        "connect_timeout": 5,
        "options": "-c statement_timeout=30000 -c idle_in_transaction_session_timeout=30000",
    },
    configure=configure,
)


@asynccontextmanager
async def transaction():
    async with pool.connection() as connection:
        async with connection.transaction():
            yield connection


async def one(connection, query, params=()):
    return await (await connection.execute(query, params)).fetchone()


async def migrate():
    from psycopg import AsyncConnection

    async with await AsyncConnection.connect(settings.DATABASE_URL, connect_timeout=5) as connection:
        await connection.execute("SELECT pg_advisory_xact_lock(48261023)")
        await connection.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations (version text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())"
        )
        for path in sorted(Path("migrations").glob("*.sql")):
            found = await (
                await connection.execute("SELECT 1 FROM schema_migrations WHERE version=%s", (path.stem,))
            ).fetchone()
            if not found:
                await connection.execute(path.read_text(encoding="utf-8"))
                await connection.execute("INSERT INTO schema_migrations(version) VALUES(%s)", (path.stem,))


if __name__ == "__main__":
    from app.runtime import run

    run(migrate())
