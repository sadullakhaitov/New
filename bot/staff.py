"""Xodimlar guruhi bilan ishlash: buyurtmani yuborish, xabarni yangilash, mijoz bekor qilishi."""
from __future__ import annotations

import logging
import re
from html import unescape
from typing import Any

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest

from .access import group_id
from .config import Config
from .db import Database
from .notify import CAPTION_LIMIT, group_order_keyboard, group_order_text

log = logging.getLogger(__name__)

CUSTOMER = "Mijoz"


def _visible_len(html_text: str) -> int:
    """Telegram izoh uzunligini teglarsiz va UTF-16 birliklarida hisoblaydi."""
    plain = unescape(re.sub(r"<[^>]+>", "", html_text))
    return len(plain.encode("utf-16-le")) // 2


async def notify_staff(bot: Bot, db: Database, cfg: Config, order: dict[str, Any], username: str) -> None:
    """Yangi buyurtmani guruhga (yoki guruh ulanmagan bo'lsa — SUPERADMIN_IDS ga) yuboradi."""
    gid = await group_id(db)
    targets = [gid] if gid is not None else sorted(cfg.superadmins)
    if not targets:
        log.error("Buyurtma №%s: xodimlar guruhi sozlanmagan (/setgroup) va SUPERADMIN_IDS bo'sh!", order["id"])
        return
    text = group_order_text(order, username)
    for n, chat_id in enumerate(targets):
        try:
            msg = await bot.send_message(chat_id, text, reply_markup=group_order_keyboard(order))
            if n == 0:
                await db.set_order_group_message(order["id"], chat_id, msg.message_id)
        except TelegramAPIError as exc:
            log.error("Buyurtma №%s guruhga yuborilmadi (%s): %s", order["id"], chat_id, exc)


async def edit_group_message(bot: Bot, chat_id: int, message_id: int, order: dict[str, Any], username: str,
                             is_media: bool) -> None:
    """Guruhdagi buyurtma xabarini qayta chizadi: chek bilan bo'lsa — rasm izohini, aks holda matnni."""
    text = group_order_text(order, username)
    markup = group_order_keyboard(order)
    try:
        if is_media:
            await bot.edit_message_caption(chat_id=chat_id, message_id=message_id, caption=text, reply_markup=markup)
        else:
            await bot.edit_message_text(text, chat_id=chat_id, message_id=message_id, reply_markup=markup)
    except TelegramBadRequest as exc:
        if "message is not modified" not in str(exc):
            log.warning("Buyurtma №%s guruh xabari yangilanmadi: %s", order["id"], exc)
    except TelegramAPIError as exc:
        log.warning("Buyurtma №%s guruh xabari yangilanmadi: %s", order["id"], exc)


async def refresh_group_message(bot: Bot, db: Database, order: dict[str, Any]) -> int | None:
    """Guruhdagi buyurtma xabarini joriy holat bilan qayta chizadi. Xabar id sini qaytaradi."""
    chat_id, message_id = order.get("group_chat_id"), order.get("group_message_id")
    if not chat_id or not message_id:
        return None
    user = await db.user(order["user_id"])
    await edit_group_message(bot, chat_id, message_id, order, (user or {}).get("username", ""),
                             bool(order.get("group_is_media")))
    return message_id


async def attach_receipt(bot: Bot, db: Database, order_id: int, file_id: str, kind: str) -> bool:
    """Mijoz chekini buyurtma bilan BITTA xabarga birlashtiradi.

    Chek rasmi (yoki fayli) buyurtma matni izoh sifatida yozilgan holda guruhga yuboriladi,
    eski matnli xabar o'chiriladi. Tugmalar yangi xabarda ishlaydi.
    """
    await db.set_order_receipt(order_id, file_id, kind)
    order = await db.order(order_id)
    chat_id = order.get("group_chat_id") or await group_id(db)
    if not chat_id:
        log.error("Chek №%s: xodimlar guruhi sozlanmagan", order_id)
        return False
    old_id = order.get("group_message_id") if order.get("group_chat_id") == chat_id else None
    user = await db.user(order["user_id"])
    text = group_order_text(order, (user or {}).get("username", ""))
    send = bot.send_document if kind == "document" else bot.send_photo
    try:
        if _visible_len(text) > CAPTION_LIMIT:
            # Juda uzun buyurtma rasm izohiga sig'maydi — chek buyurtma xabariga javob sifatida boradi
            await send(chat_id, file_id, caption=f"🧾 <b>To'lov cheki — №{order_id}</b>",
                       reply_to_message_id=old_id)
            await refresh_group_message(bot, db, order)
            return True
        msg = await send(chat_id, file_id, caption=text, reply_markup=group_order_keyboard(order))
    except TelegramAPIError as exc:
        log.error("Chek №%s guruhga yuborilmadi: %s", order_id, exc)
        return False
    await db.set_order_group_message(order_id, chat_id, msg.message_id, is_media=True)
    if old_id:
        try:
            await bot.delete_message(chat_id, old_id)
        except TelegramAPIError:
            # Botda o'chirish huquqi bo'lmasa — eski xabar qisqa eslatmaga aylanadi
            try:
                text_old = f"↪️ Buyurtma <b>№{order_id}</b> chek bilan pastda qayta yuborildi."
                if order.get("group_is_media"):
                    await bot.edit_message_caption(chat_id=chat_id, message_id=old_id, caption=text_old)
                else:
                    await bot.edit_message_text(text_old, chat_id=chat_id, message_id=old_id)
            except TelegramAPIError as exc:
                log.warning("Eski buyurtma xabari (№%s) o'zgartirilmadi: %s", order_id, exc)
    return True


async def cancel_by_customer(bot: Bot, db: Database, order_id: int, user_id: int) -> tuple[str, dict[str, Any] | None]:
    """Mijoz buyurtmasini bekor qiladi — faqat xodimlar hali qabul qilmagan bo'lsa.

    Natija: ("ok" | "not_found" | "accepted" | "already_canceled", buyurtma).
    """
    order = await db.order(order_id)
    if order is None or order["user_id"] != user_id:
        return "not_found", None
    updated = await db.set_order_status(order_id, "canceled", CUSTOMER, allowed_from=("new",))
    if updated is None:
        order = await db.order(order_id)
        return ("already_canceled" if order["status"] == "canceled" else "accepted"), order

    message_id = await refresh_group_message(bot, db, updated)
    chat_id = updated.get("group_chat_id") or await group_id(db)
    if chat_id:
        try:
            await bot.send_message(
                chat_id, f"❌ Mijoz <b>№{order_id}</b> buyurtmani bekor qildi.",
                reply_to_message_id=message_id if updated.get("group_chat_id") == chat_id else None,
            )
        except TelegramAPIError as exc:
            log.warning("Bekor qilish xabari guruhga yuborilmadi (№%s): %s", order_id, exc)
    return "ok", updated
