"""SQLite ma'lumotlar bazasi: menyu, sozlamalar, foydalanuvchilar va buyurtmalar."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import aiosqlite

from .config import TASHKENT_TZ

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS categories (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    slug     TEXT UNIQUE NOT NULL,
    name_uz  TEXT NOT NULL,
    name_cyr TEXT NOT NULL,
    name_ru  TEXT NOT NULL,
    img      TEXT NOT NULL DEFAULT '',
    sort     INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS products (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
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
    id         INTEGER PRIMARY KEY,
    first_name TEXT NOT NULL DEFAULT '',
    username   TEXT NOT NULL DEFAULT '',
    lang       TEXT,
    name       TEXT NOT NULL DEFAULT '',
    phone      TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS orders (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL,
    kind       TEXT NOT NULL,
    name       TEXT NOT NULL,
    phone      TEXT NOT NULL,
    address    TEXT NOT NULL DEFAULT '',
    lat        REAL,
    lon        REAL,
    comment    TEXT NOT NULL DEFAULT '',
    payment    TEXT NOT NULL,
    items      TEXT NOT NULL,
    total      INTEGER NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS orders_user ON orders(user_id, id);
"""

PRODUCT_FIELDS = {
    "category_id", "name_uz", "name_cyr", "name_ru", "desc_uz", "desc_cyr", "desc_ru",
    "img", "price", "price_large", "is_active", "is_hit", "sort",
}

FIRST_ORDER_ID = 1001


def now_iso() -> str:
    return datetime.now(TASHKENT_TZ).isoformat(timespec="seconds")


class Database:
    def __init__(self, path: Path | str):
        self.path = Path(path) if str(path) != ":memory:" else path
        self._conn: aiosqlite.Connection | None = None

    @property
    def conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("Database.connect() chaqirilmagan")
        return self._conn

    async def connect(self) -> None:
        if isinstance(self.path, Path):
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(str(self.path))
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA foreign_keys = ON")
        await self._conn.execute("PRAGMA journal_mode = WAL")
        await self._conn.executescript(SCHEMA)
        await self._conn.commit()

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    # ---------- sozlamalar ----------
    async def get_setting(self, key: str, default: str = "") -> str:
        async with self.conn.execute("SELECT value FROM settings WHERE key = ?", (key,)) as cur:
            row = await cur.fetchone()
        return row["value"] if row else default

    async def set_setting(self, key: str, value: str) -> None:
        await self.conn.execute(
            "INSERT INTO settings(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, str(value)),
        )
        await self.conn.commit()

    async def all_settings(self) -> dict[str, str]:
        async with self.conn.execute("SELECT key, value FROM settings") as cur:
            return {r["key"]: r["value"] async for r in cur}

    # ---------- menyu ----------
    async def categories(self) -> list[dict[str, Any]]:
        async with self.conn.execute("SELECT * FROM categories ORDER BY sort, id") as cur:
            return [dict(r) async for r in cur]

    async def category(self, category_id: int) -> dict[str, Any] | None:
        async with self.conn.execute("SELECT * FROM categories WHERE id = ?", (category_id,)) as cur:
            row = await cur.fetchone()
        return dict(row) if row else None

    async def products(self, category_id: int | None = None) -> list[dict[str, Any]]:
        sql = "SELECT * FROM products"
        args: tuple = ()
        if category_id is not None:
            sql += " WHERE category_id = ?"
            args = (category_id,)
        async with self.conn.execute(sql + " ORDER BY sort, id", args) as cur:
            return [dict(r) async for r in cur]

    async def product(self, product_id: int) -> dict[str, Any] | None:
        async with self.conn.execute("SELECT * FROM products WHERE id = ?", (product_id,)) as cur:
            row = await cur.fetchone()
        return dict(row) if row else None

    async def products_by_ids(self, ids: list[int]) -> dict[int, dict[str, Any]]:
        if not ids:
            return {}
        marks = ",".join("?" * len(ids))
        async with self.conn.execute(f"SELECT * FROM products WHERE id IN ({marks})", tuple(ids)) as cur:
            return {r["id"]: dict(r) async for r in cur}

    async def add_category(self, **fields: Any) -> int:
        cols = ", ".join(fields)
        marks = ", ".join("?" * len(fields))
        cur = await self.conn.execute(f"INSERT INTO categories({cols}) VALUES({marks})", tuple(fields.values()))
        await self.conn.commit()
        return cur.lastrowid

    async def add_product(self, **fields: Any) -> int:
        unknown = set(fields) - PRODUCT_FIELDS
        if unknown:
            raise ValueError(f"Noma'lum maydonlar: {unknown}")
        if "sort" not in fields:
            async with self.conn.execute(
                "SELECT COALESCE(MAX(sort), 0) + 10 AS s FROM products WHERE category_id = ?",
                (fields["category_id"],),
            ) as cur:
                fields["sort"] = (await cur.fetchone())["s"]
        cols = ", ".join(fields)
        marks = ", ".join("?" * len(fields))
        cur = await self.conn.execute(f"INSERT INTO products({cols}) VALUES({marks})", tuple(fields.values()))
        await self.conn.commit()
        return cur.lastrowid

    async def update_product(self, product_id: int, **fields: Any) -> None:
        unknown = set(fields) - PRODUCT_FIELDS
        if unknown:
            raise ValueError(f"Noma'lum maydonlar: {unknown}")
        if not fields:
            return
        sets = ", ".join(f"{k} = ?" for k in fields)
        await self.conn.execute(f"UPDATE products SET {sets} WHERE id = ?", (*fields.values(), product_id))
        await self.conn.commit()

    async def delete_product(self, product_id: int) -> None:
        await self.conn.execute("DELETE FROM products WHERE id = ?", (product_id,))
        await self.conn.commit()

    # ---------- foydalanuvchilar ----------
    async def upsert_user(self, user_id: int, first_name: str = "", username: str = "") -> dict[str, Any]:
        await self.conn.execute(
            "INSERT INTO users(id, first_name, username, created_at) VALUES(?, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET first_name = excluded.first_name, username = excluded.username",
            (user_id, first_name or "", username or "", now_iso()),
        )
        await self.conn.commit()
        return await self.user(user_id)  # type: ignore[return-value]

    async def user(self, user_id: int) -> dict[str, Any] | None:
        async with self.conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)) as cur:
            row = await cur.fetchone()
        return dict(row) if row else None

    async def set_user_lang(self, user_id: int, lang: str) -> None:
        await self.conn.execute("UPDATE users SET lang = ? WHERE id = ?", (lang, user_id))
        await self.conn.commit()

    async def set_user_contact(self, user_id: int, name: str, phone: str) -> None:
        await self.conn.execute("UPDATE users SET name = ?, phone = ? WHERE id = ?", (name, phone, user_id))
        await self.conn.commit()

    # ---------- buyurtmalar ----------
    async def create_order(self, **fields: Any) -> int:
        fields = dict(fields)
        fields["items"] = json.dumps(fields["items"], ensure_ascii=False)
        fields.setdefault("created_at", now_iso())
        async with self.conn.execute("SELECT seq FROM sqlite_sequence WHERE name = 'orders'") as cur:
            seeded = await cur.fetchone()
        if seeded is None:
            await self.conn.execute(
                "INSERT INTO sqlite_sequence(name, seq) VALUES('orders', ?)", (FIRST_ORDER_ID - 1,)
            )
        cols = ", ".join(fields)
        marks = ", ".join("?" * len(fields))
        cur = await self.conn.execute(f"INSERT INTO orders({cols}) VALUES({marks})", tuple(fields.values()))
        await self.conn.commit()
        return cur.lastrowid

    @staticmethod
    def _order_row(row: aiosqlite.Row) -> dict[str, Any]:
        order = dict(row)
        order["items"] = json.loads(order["items"])
        return order

    async def order(self, order_id: int) -> dict[str, Any] | None:
        async with self.conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)) as cur:
            row = await cur.fetchone()
        return self._order_row(row) if row else None

    async def user_orders(self, user_id: int, limit: int = 10) -> list[dict[str, Any]]:
        async with self.conn.execute(
            "SELECT * FROM orders WHERE user_id = ? ORDER BY id DESC LIMIT ?", (user_id, limit)
        ) as cur:
            return [self._order_row(r) async for r in cur]

    async def backup_to(self, target: Path) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(str(target)) as dst:
            await self.conn.backup(dst)
