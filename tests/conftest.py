import os

import pytest

from app.runtime import loop_factory


def pytest_asyncio_loop_factories():
    return {"platform": loop_factory}


@pytest.fixture
async def database(monkeypatch):
    if os.environ.get("RUN_DB_TESTS") != "1":
        pytest.skip("Set RUN_DB_TESTS=1 against an isolated PostgreSQL database to run integration tests")
    from psycopg.rows import dict_row
    from psycopg_pool import AsyncConnectionPool

    import app.db as database_module
    from app.config import settings
    from app.db import configure, migrate, transaction

    if "test" not in settings.DATABASE_URL.rsplit("/", 1)[-1]:
        pytest.fail("Integration tests require an explicitly named test database")
    await migrate()
    pool = AsyncConnectionPool(
        settings.DATABASE_URL,
        open=False,
        min_size=1,
        max_size=4,
        kwargs={"row_factory": dict_row},
        configure=configure,
    )
    monkeypatch.setattr(database_module, "pool", pool)
    await pool.open(wait=True)
    async with transaction() as db:
        await db.execute("TRUNCATE bots,rate_limits,managed_requests CASCADE")
    yield
    await pool.close()
