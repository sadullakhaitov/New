import os

import pytest

from bot.db import Database, asyncpg_dsn
from bot.seed import seed, seed_banners, split_sizes


@pytest.fixture
async def fresh_db():
    """Toza, boshlang'ich menyu yozilgan baza.

    TEST_DATABASE_URL berilsa — PostgreSQL'da (har test oldidan tozalanadi), aks holda xotiradagi SQLite.
    """
    url = os.environ.get("TEST_DATABASE_URL")
    if url:
        import asyncpg

        conn = await asyncpg.connect(asyncpg_dsn(url))
        await conn.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
        await conn.close()
    db = Database(url or ":memory:")
    await db.connect()
    await seed(db)
    await split_sizes(db)
    await seed_banners(db)
    yield db
    await db.close()
