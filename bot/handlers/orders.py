"""Guruhdagi buyurtma tugmalari: qabul qilish / bekor qilish."""
from __future__ import annotations

import logging

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.types import CallbackQuery

from .. import access
from ..config import Config
from ..core import norm_lang
from ..db import Database
from ..notify import cancel_confirm_keyboard
from ..staff import edit_group_message
from ..texts import t

log = logging.getLogger(__name__)
router = Router(name="orders")


async def _allowed(call: CallbackQuery, db: Database, cfg: Config) -> bool:
    """Tugmalar buyurtmalar guruhida ishlaydi (u yerdagi har bir xodim bosishi mumkin).

    Guruh ulanmagan bo'lsa, buyurtmalar SUPERADMIN_IDS ga boradi — ular ham bosa oladi.
    """
    if call.message is None:
        return False
    gid = await access.group_id(db)
    if gid is not None:
        return call.message.chat.id == gid
    return call.from_user.id in cfg.superadmins


async def _refresh(call: CallbackQuery, db: Database, order: dict) -> None:
    user = await db.user(order["user_id"])
    is_media = bool(call.message.photo or call.message.document)
    await edit_group_message(call.bot, call.message.chat.id, call.message.message_id, order,
                             (user or {}).get("username", ""), is_media)


async def _notify_customer(bot: Bot, db: Database, order: dict, key: str) -> None:
    user = await db.user(order["user_id"])
    lang = norm_lang((user or {}).get("lang"))
    try:
        await bot.send_message(order["user_id"], t(key, lang, id=order["id"], phone=await db.get_setting("phone")))
    except TelegramAPIError as exc:
        log.info("Mijozga holat xabari yuborilmadi (№%s): %s", order["id"], exc)


def _staff_name(call: CallbackQuery) -> str:
    u = call.from_user
    return " ".join(filter(None, [u.first_name, u.last_name])) or (u.username or str(u.id))


async def _parse(call: CallbackQuery, db: Database, cfg: Config) -> dict | None:
    if not await _allowed(call, db, cfg):
        await call.answer("⛔ Bu tugma faqat buyurtmalar guruhida ishlaydi", show_alert=True)
        return None
    order = await db.order(int(call.data.split(":")[2]))
    if order is None:
        await call.answer("Buyurtma topilmadi", show_alert=True)
    return order


@router.callback_query(F.data.startswith("o:acc:"))
async def accept(call: CallbackQuery, db: Database, cfg: Config, bot: Bot) -> None:
    order = await _parse(call, db, cfg)
    if order is None:
        return
    updated = await db.set_order_status(order["id"], "accepted", _staff_name(call))
    if updated is None:
        await call.answer("Bu buyurtma allaqachon ko'rib chiqilgan", show_alert=True)
        await _refresh(call, db, order)
        return
    await _refresh(call, db, updated)
    await call.answer("✅ Qabul qilindi, mijozga xabar yuborildi")
    await _notify_customer(bot, db, updated, "order_accepted")


@router.callback_query(F.data.startswith("o:rej:"))
async def ask_cancel(call: CallbackQuery, db: Database, cfg: Config) -> None:
    order = await _parse(call, db, cfg)
    if order is None:
        return
    if order["status"] == "canceled":
        await call.answer("Bu buyurtma allaqachon bekor qilingan", show_alert=True)
        await _refresh(call, db, order)
        return
    try:
        await call.message.edit_reply_markup(reply_markup=cancel_confirm_keyboard(order["id"]))
    except TelegramBadRequest:
        pass
    await call.answer("Bekor qilishni tasdiqlang")


@router.callback_query(F.data.startswith("o:back:"))
async def keep(call: CallbackQuery, db: Database, cfg: Config) -> None:
    order = await _parse(call, db, cfg)
    if order is None:
        return
    await _refresh(call, db, order)
    await call.answer()


@router.callback_query(F.data.startswith("o:rejy:"))
async def cancel(call: CallbackQuery, db: Database, cfg: Config, bot: Bot) -> None:
    order = await _parse(call, db, cfg)
    if order is None:
        return
    updated = await db.set_order_status(order["id"], "canceled", _staff_name(call))
    if updated is None:
        await call.answer("Bu buyurtma allaqachon bekor qilingan", show_alert=True)
        await _refresh(call, db, order)
        return
    await _refresh(call, db, updated)
    await call.answer("❌ Bekor qilindi, mijozga xabar yuborildi")
    await _notify_customer(bot, db, updated, "order_canceled")
