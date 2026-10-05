"""Ma'lumotlar bazasi: menyu, sozlamalar, foydalanuvchilar va buyurtmalar.

Ikki xil baza ishlaydi:
- SQLite (fayl) — kompyuterda sinash va doimiy diskli server uchun;
- PostgreSQL (DATABASE_URL=postgresql://...) — Render kabi fayllari o'chib ketadigan hosting uchun (masalan Neon).
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import aiosqlite

from .config import TASHKENT_TZ

_TABLES = """
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS categories (
    id       {pk},
    slug     TEXT UNIQUE NOT NULL,
    name_uz  TEXT NOT NULL,
    name_cyr TEXT NOT NULL,
    name_ru  TEXT NOT NULL,
    img      TEXT NOT NULL DEFAULT '',
    sort     INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS products (
    id          {pk},
    category_id INTEGER NOT NULL REFERENCES categories(id),
    name_uz     TEXT NOT NULL,
    name_cyr    TEXT NOT NULL DEFAULT '',
    name_ru     TEXT NOT NULL DEFAULT '',
    desc_uz     TEXT NOT NULL DEFAULT '',
    desc_cyr    TEXT NOT NULL DEFAULT '',
    desc_ru     TEXT NOT NULL DEFAULT '',
    img         TEXT NOT NULL DEFAULT '',
    price       INTEGER,
    price_large INTEGER,
    is_active   INTEGER NOT NULL DEFAULT 1,
    is_hit      INTEGER NOT NULL DEFAULT 0,
    sort        INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS users (
    id         BIGINT PRIMARY KEY,
    first_name TEXT NOT NULL DEFAULT '',
    username   TEXT NOT NULL DEFAULT '',
    lang       TEXT,
    name       TEXT NOT NULL DEFAULT '',
    phone      TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS orders (
    id         {pk},
    user_id    BIGINT NOT NULL,
    kind       TEXT NOT NULL,
    name       TEXT NOT NULL,
    phone      TEXT NOT NULL,
    address    TEXT NOT NULL DEFAULT '',
    lat        {real},
    lon        {real},
    comment    TEXT NOT NULL DEFAULT '',
    payment    TEXT NOT NULL,
    items      TEXT NOT NULL,
    total      INTEGER NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS orders_user ON orders(user_id, id);
"""
SQLITE_SCHEMA = _TABLES.format(pk="INTEGER PRIMARY KEY AUTOINCREMENT", real="REAL")
POSTGRES_SCHEMA = _TABLES.format(pk="SERIAL PRIMARY KEY", real="DOUBLE PRECISION")

PRODUCT_FIELDS = {
    "category_id", "name_uz", "name_cyr", "name_ru", "desc_uz", "desc_cyr", "desc_ru",
    "img", "price", "price_large", "is_active", "is_hit", "sort",
}
CATEGORY_FIELDS = {"slug", "name_uz", "name_cyr", "name_ru", "img", "sort"}
BACKUP_TABLES = ("settings", "categories", "products", "users", "orders")

FIRST_ORDER_ID = 1001


def now_iso() -> str:
    return datetime.now(TASHKENT_TZ).isoformat(timespec="seconds")


def is_postgres_url(url: str) -> bool:
    return url.startswith(("postgres://", "postgresql://"))


def asyncpg_dsn(url: str) -> str:
    """Neon bergan manzildan asyncpg tushunmaydigan parametrlarni olib tashlaydi (channel_binding)."""
    from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

    parts = urlsplit(url)
    query = [(k, v) for k, v in parse_qsl(parts.query) if k not in {"channel_binding"}]
    return urlunsplit(parts._replace(query=urlencode(query)))


def _pg_placeholders(sql: str) -> str:
    counter = iter(range(1, 1000))
    return re.sub(r"\?", lambda _: f"${next(counter)}", sql)


class Database:
    def __init__(self, target: Path | str):
        """target — SQLite fayl yo'li, ":memory:" yoki postgresql:// manzil."""
        self.target = str(target)
        self.is_pg = is_postgres_url(self.target)
        self._sqlite: aiosqlite.Connection | None = None
        self._pool = None

    # ---------- ulanish ----------
    async def connect(self) -> None:
        if self.is_pg:
            import asyncpg

            # statement_cache_size=0 — Neon/pgbouncer pooler bilan ishlash uchun.
            self._pool = await asyncpg.create_pool(asyncpg_dsn(self.target), min_size=1, max_size=5, statement_cache_size=0)
            async with self._pool.acquire() as conn:
                await conn.execute(POSTGRES_SCHEMA)
            return
        if self.target != ":memory:":
            Path(self.target).parent.mkdir(parents=True, exist_ok=True)
        self._sqlite = await aiosqlite.connect(self.target)
        self._sqlite.row_factory = aiosqlite.Row
        await self._sqlite.execute("PRAGMA foreign_keys = ON")
        await self._sqlite.execute("PRAGMA journal_mode = WAL")
        await self._sqlite.executescript(SQLITE_SCHEMA)
        await self._sqlite.commit()

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None
        if self._sqlite is not None:
            await self._sqlite.close()
            self._sqlite = None

    # ---------- past darajadagi so'rovlar ----------
    async def _fetchall(self, sql: str, args: tuple = ()) -> list[dict[str, Any]]:
        if self.is_pg:
            async with self._pool.acquire() as conn:
                return [dict(r) for r in await conn.fetch(_pg_placeholders(sql), *args)]
        async with self._sqlite.execute(sql, args) as cur:
            return [dict(r) async for r in cur]

    async def _fetchone(self, sql: str, args: tuple = ()) -> dict[str, Any] | None:
        rows = await self._fetchall(sql, args)
        return rows[0] if rows else None

    async def _execute(self, sql: str, args: tuple = ()) -> None:
        if self.is_pg:
            async with self._pool.acquire() as conn:
                await conn.execute(_pg_placeholders(sql), *args)
            return
        await self._sqlite.execute(sql, args)
        await self._sqlite.commit()

    async def _insert(self, table: str, fields: dict[str, Any]) -> int:
        cols = ", ".join(fields)
        marks = ", ".join("?" * len(fields))
        sql = f"INSERT INTO {table}({cols}) VALUES({marks}) RETURNING id"
        row = await self._fetchone(sql, tuple(fields.values()))
        if not self.is_pg:
            await self._sqlite.commit()
        return row["id"]

    # ---------- sozlamalar ----------
    async def get_setting(self, key: str, default: str = "") -> str:
        row = await self._fetchone("SELECT value FROM settings WHERE key = ?", (key,))
        return row["value"] if row else default

    async def set_setting(self, key: str, value: str) -> None:
        await self._execute(
            "INSERT INTO settings(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, str(value)),
        )

    async def all_settings(self) -> dict[str, str]:
        return {r["key"]: r["value"] for r in await self._fetchall("SELECT key, value FROM settings")}

    # ---------- menyu ----------
    async def categories(self) -> list[dict[str, Any]]:
        return await self._fetchall("SELECT * FROM categories ORDER BY sort, id")

    async def category(self, category_id: int) -> dict[str, Any] | None:
        return await self._fetchone("SELECT * FROM categories WHERE id = ?", (category_id,))

    async def products(self, category_id: int | None = None) -> list[dict[str, Any]]:
        if category_id is None:
            return await self._fetchall("SELECT * FROM products ORDER BY sort, id")
        return await self._fetchall(
            "SELECT * FROM products WHERE category_id = ? ORDER BY sort, id", (category_id,)
        )

    async def product(self, product_id: int) -> dict[str, Any] | None:
        return await self._fetchone("SELECT * FROM products WHERE id = ?", (product_id,))

    async def products_by_ids(self, ids: list[int]) -> dict[int, dict[str, Any]]:
        ids = sorted(set(ids))
        if not ids:
            return {}
        marks = ",".join("?" * len(ids))
        rows = await self._fetchall(f"SELECT * FROM products WHERE id IN ({marks})", tuple(ids))
        return {r["id"]: r for r in rows}

    async def add_category(self, **fields: Any) -> int:
        if set(fields) - CATEGORY_FIELDS:
            raise ValueError(f"Noma'lum maydonlar: {set(fields) - CATEGORY_FIELDS}")
        return await self._insert("categories", fields)

    async def add_product(self, **fields: Any) -> int:
        unknown = set(fields) - PRODUCT_FIELDS
        if unknown:
            raise ValueError(f"Noma'lum maydonlar: {unknown}")
        if "sort" not in fields:
            row = await self._fetchone(
                "SELECT COALESCE(MAX(sort), 0) + 10 AS s FROM products WHERE category_id = ?",
                (fields["category_id"],),
            )
            fields["sort"] = row["s"]
        return await self._insert("products", fields)

    async def update_product(self, product_id: int, **fields: Any) -> None:
        unknown = set(fields) - PRODUCT_FIELDS
        if unknown:
            raise ValueError(f"Noma'lum maydonlar: {unknown}")
        if not fields:
            return
        sets = ", ".join(f"{k} = ?" for k in fields)
        await self._execute(f"UPDATE products SET {sets} WHERE id = ?", (*fields.values(), product_id))

    async def delete_product(self, product_id: int) -> None:
        await self._execute("DELETE FROM products WHERE id = ?", (product_id,))

    # ---------- foydalanuvchilar ----------
    async def upsert_user(self, user_id: int, first_name: str = "", username: str = "") -> dict[str, Any]:
        await self._execute(
            "INSERT INTO users(id, first_name, username, created_at) VALUES(?, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET first_name = excluded.first_name, username = excluded.username",
            (user_id, first_name or "", username or "", now_iso()),
        )
        return await self.user(user_id)  # type: ignore[return-value]

    async def user(self, user_id: int) -> dict[str, Any] | None:
        return await self._fetchone("SELECT * FROM users WHERE id = ?", (user_id,))

    async def set_user_lang(self, user_id: int, lang: str) -> None:
        await self._execute("UPDATE users SET lang = ? WHERE id = ?", (lang, user_id))

    async def set_user_contact(self, user_id: int, name: str, phone: str) -> None:
        await self._execute("UPDATE users SET name = ?, phone = ? WHERE id = ?", (name, phone, user_id))

    # ---------- buyurtmalar ----------
    async def _ensure_order_numbering(self) -> None:
        """Buyurtma raqamlari 1001 dan boshlanadi."""
        if await self._fetchone("SELECT id FROM orders LIMIT 1"):
            return
        if self.is_pg:
            await self._execute(
                "SELECT setval(pg_get_serial_sequence('orders', 'id'), ?, true)", (FIRST_ORDER_ID - 1,)
            )
        elif not await self._fetchone("SELECT seq FROM sqlite_sequence WHERE name = 'orders'"):
            await self._execute("INSERT INTO sqlite_sequence(name, seq) VALUES('orders', ?)", (FIRST_ORDER_ID - 1,))

    async def create_order(self, **fields: Any) -> int:
        fields = dict(fields)
        fields["items"] = json.dumps(fields["items"], ensure_ascii=False)
        fields.setdefault("created_at", now_iso())
        await self._ensure_order_numbering()
        return await self._insert("orders", fields)

    @staticmethod
    def _order_row(row: dict[str, Any]) -> dict[str, Any]:
        row["items"] = json.loads(row["items"])
        return row

    async def order(self, order_id: int) -> dict[str, Any] | None:
        row = await self._fetchone("SELECT * FROM orders WHERE id = ?", (order_id,))
        return self._order_row(row) if row else None

    async def user_orders(self, user_id: int, limit: int = 10) -> list[dict[str, Any]]:
        rows = await self._fetchall(
            "SELECT * FROM orders WHERE user_id = ? ORDER BY id DESC LIMIT ?", (user_id, limit)
        )
        return [self._order_row(r) for r in rows]

    # ---------- zaxira ----------
    async def export_json(self) -> bytes:
        data = {"exported_at": now_iso()}
        for table in BACKUP_TABLES:
            data[table] = await self._fetchall(f"SELECT * FROM {table} ORDER BY 1")
        return json.dumps(data, ensure_ascii=False, indent=1).encode("utf-8")
