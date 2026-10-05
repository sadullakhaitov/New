"""Kim admin ekanini aniqlash: SUPERADMIN_IDS yoki xodimlar guruhining adminlari."""
from __future__ import annotations

import logging
import time

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError

from .config import Config
from .db import Database

log = logging.getLogger(__name__)

ADMIN_STATUSES = {"creator", "administrator"}
_CACHE_TTL = 60.0
_cache: dict[tuple[int, int], tuple[float, bool]] = {}


async def is_chat_admin(bot: Bot, chat_id: int, user_id: int) -> bool:
    key = (chat_id, user_id)
    hit = _cache.get(key)
    if hit and time.monotonic() - hit[0] < _CACHE_TTL:
        return hit[1]
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        result = member.status in ADMIN_STATUSES
    except TelegramAPIError as exc:
        log.warning("get_chat_member(%s, %s) xato: %s", chat_id, user_id, exc)
        result = False
    _cache[key] = (time.monotonic(), result)
    return result


def forget(chat_id: int | None = None) -> None:
    if chat_id is None:
        _cache.clear()
    else:
        for key in [k for k in _cache if k[0] == chat_id]:
            _cache.pop(key, None)


async def group_id(db: Database) -> int | None:
    raw = await db.get_setting("group_chat_id")
    return int(raw) if raw.lstrip("-").isdigit() else None


async def is_admin(bot: Bot, db: Database, cfg: Config, user_id: int) -> bool:
    if user_id in cfg.superadmins:
        return True
    gid = await group_id(db)
    if gid is None:
        return False
    return await is_chat_admin(bot, gid, user_id)
