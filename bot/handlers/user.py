"""Mijoz tomoni: /start, til, menyu tugmasi, buyurtmalar tarixi, aloqa, to'lov cheki."""
from __future__ import annotations

import logging
from html import escape

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import CommandStart
from aiogram.types import (
    CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton,
    MenuButtonWebApp, Message, ReplyKeyboardMarkup, WebAppInfo,
)

from ..config import Config
from ..core import LANGS, format_sum, norm_lang, normalize_phone, shop_status
from ..db import Database
from ..notify import history_text
from ..staff import attach_receipt, cancel_by_customer
from ..texts import LANG_NAMES, TEXTS, t

log = logging.getLogger(__name__)
router = Router(name="user")
router.message.filter(F.chat.type == "private")


def _all(key: str) -> set[str]:
    return set(TEXTS[key].values())


def lang_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=LANG_NAMES[code], callback_data=f"lang:{code}")] for code in LANGS
    ])


def main_keyboard(lang: str) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=t("btn_menu", lang))],
            [KeyboardButton(text=t("btn_orders", lang)), KeyboardButton(text=t("btn_contact", lang))],
            [KeyboardButton(text=t("btn_lang", lang))],
        ],
        resize_keyboard=True,
    )


def app_button(cfg: Config, lang: str) -> InlineKeyboardMarkup | None:
    if not cfg.webapp_url:
        return None
    url = f"{cfg.webapp_url}?lang={lang}"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t("btn_open_app", lang), web_app=WebAppInfo(url=url))]
    ])


async def set_menu_button(bot: Bot, cfg: Config, chat_id: int, lang: str) -> None:
    if not cfg.webapp_url:
        return
    try:
        await bot.set_chat_menu_button(
            chat_id=chat_id,
            menu_button=MenuButtonWebApp(
                text=t("menu_button", lang), web_app=WebAppInfo(url=f"{cfg.webapp_url}?lang={lang}")
            ),
        )
    except TelegramAPIError as exc:
        log.warning("Menyu tugmasi o'rnatilmadi: %s", exc)


async def send_welcome(message: Message, db: Database, cfg: Config, lang: str) -> None:
    settings = await db.all_settings()
    text = t("welcome", lang, name=escape(message.chat.first_name or ""),
             min=format_sum(int(settings.get("min_order") or 0)))
    status = shop_status(settings.get("closed_until", ""))
    if not status.is_open:
        until = t("closed_until", lang, until=status.until_text()) if status.until else ""
        text += t("closed_note", lang, until=until)
    await message.answer(text, reply_markup=main_keyboard(lang))
    markup = app_button(cfg, lang)
    if markup:
        await message.answer(t("open_menu", lang), reply_markup=markup)
    else:
        await message.answer(t("no_webapp", lang, phone=settings.get("phone", "")))


@router.message(CommandStart())
async def start(message: Message, db: Database, cfg: Config, bot: Bot) -> None:
    user = await db.upsert_user(message.from_user.id, message.from_user.first_name or "",
                                message.from_user.username or "")
    if not user["lang"]:
        await message.answer(" / ".join(TEXTS["choose_lang"].values()), reply_markup=lang_keyboard())
        return
    await set_menu_button(bot, cfg, message.chat.id, user["lang"])
    await send_welcome(message, db, cfg, user["lang"])


@router.callback_query(F.data.startswith("lang:"))
async def choose_lang(call: CallbackQuery, db: Database, cfg: Config, bot: Bot) -> None:
    lang = call.data.split(":", 1)[1]
    if lang not in LANGS:
        await call.answer()
        return
    await db.upsert_user(call.from_user.id, call.from_user.first_name or "", call.from_user.username or "")
    await db.set_user_lang(call.from_user.id, lang)
    await call.answer(t("lang_set", lang))
    try:
        await call.message.delete()
    except TelegramAPIError:
        pass
    await set_menu_button(bot, cfg, call.message.chat.id, lang)
    await send_welcome(call.message, db, cfg, lang)


async def _lang(db: Database, message: Message) -> str:
    user = await db.user(message.from_user.id)
    return norm_lang(user["lang"] if user else None)


@router.message(F.text.in_(_all("btn_lang")))
async def change_lang(message: Message) -> None:
    await message.answer(" / ".join(TEXTS["choose_lang"].values()), reply_markup=lang_keyboard())


@router.message(F.text.in_(_all("btn_menu")))
async def open_menu(message: Message, db: Database, cfg: Config) -> None:
    lang = await _lang(db, message)
    markup = app_button(cfg, lang)
    if markup:
        await message.answer(t("open_menu", lang), reply_markup=markup)
    else:
        await message.answer(t("no_webapp", lang, phone=await db.get_setting("phone")))


def cancel_keyboard(orders: list[dict], lang: str) -> InlineKeyboardMarkup | None:
    """Xodimlar hali qabul qilmagan buyurtmalar uchun "bekor qilish" tugmalari."""
    rows = [[InlineKeyboardButton(text=t("btn_cancel_order", lang, id=o["id"]), callback_data=f"c:can:{o['id']}")]
            for o in orders if (o.get("status") or "new") == "new"]
    return InlineKeyboardMarkup(inline_keyboard=rows[:3]) if rows else None


@router.message(F.text.in_(_all("btn_orders")))
async def my_orders(message: Message, db: Database) -> None:
    lang = await _lang(db, message)
    orders = await db.user_orders(message.from_user.id, limit=5)
    if not orders:
        await message.answer(t("no_orders", lang))
        return
    await message.answer(history_text(orders, lang), reply_markup=cancel_keyboard(orders, lang))


@router.callback_query(F.data.startswith("c:can:"))
async def ask_cancel(call: CallbackQuery, db: Database) -> None:
    user = await db.user(call.from_user.id)
    lang = norm_lang(user["lang"] if user else None)
    oid = int(call.data.split(":")[2])
    await call.message.answer(t("cancel_q", lang, id=oid), reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=t("cancel_yes", lang), callback_data=f"c:yes:{oid}"),
        InlineKeyboardButton(text=t("cancel_no", lang), callback_data="c:no"),
    ]]))
    await call.answer()


@router.callback_query(F.data == "c:no")
async def keep_order(call: CallbackQuery) -> None:
    try:
        await call.message.delete()
    except TelegramAPIError:
        pass
    await call.answer()


@router.callback_query(F.data.startswith("c:yes:"))
async def do_cancel(call: CallbackQuery, db: Database, bot: Bot) -> None:
    user = await db.user(call.from_user.id)
    lang = norm_lang(user["lang"] if user else None)
    oid = int(call.data.split(":")[2])
    result, _ = await cancel_by_customer(bot, db, oid, call.from_user.id)
    if result == "not_found":
        await call.answer()
        return
    if result == "accepted":
        text = t("cannot_cancel", lang, id=oid, phone=await db.get_setting("phone"))
    else:  # "ok" yoki allaqachon bekor qilingan
        text = t("canceled_by_you", lang, id=oid)
    try:
        await call.message.edit_text(text)
    except TelegramAPIError:
        await call.message.answer(text)
    await call.answer()


@router.message(F.contact)
async def contact_shared(message: Message, db: Database) -> None:
    """Mini App'dagi "Telegram orqali yuborish" tugmasi raqamni shu yerga yuboradi."""
    contact = message.contact
    if contact.user_id != message.from_user.id:
        return  # boshqa odamning kontakti — tasdiqlangan raqam sifatida olinmaydi
    phone = normalize_phone(contact.phone_number)
    if not phone:
        return
    await db.upsert_user(message.from_user.id, message.from_user.first_name or "", message.from_user.username or "")
    await db.set_verified_phone(message.from_user.id, phone)
    lang = await _lang(db, message)
    await message.answer(t("phone_saved", lang, phone=phone))


@router.message(F.text.in_(_all("btn_contact")))
async def contact(message: Message, db: Database) -> None:
    lang = await _lang(db, message)
    s = await db.all_settings()
    await message.answer(t(
        "contact", lang,
        phone=escape(s.get("phone", "")),
        address=escape(s.get(f"address_{lang}") or s.get("address_uz", "")),
        zone=escape(s.get(f"delivery_zone_{lang}") or s.get("delivery_zone_uz", "")),
        min=format_sum(int(s.get("min_order") or 0)),
    ))


@router.message(F.photo | F.document)
async def receipt(message: Message, db: Database, bot: Bot) -> None:
    """To'lov chekini guruhdagi buyurtma xabariga qo'shadi (bitta xabar bo'lib turadi)."""
    lang = await _lang(db, message)
    orders = await db.user_orders(message.from_user.id, limit=5)
    if not orders:
        await message.answer(t("receipt_no_order", lang))
        return
    # Avvalo kartaga to'lanadigan, bekor qilinmagan oxirgi buyurtma
    order = next((o for o in orders if o["payment"] in ("card", "later") and o.get("status") != "canceled"), orders[0])
    if message.photo:
        file_id, kind = message.photo[-1].file_id, "photo"
    else:
        file_id, kind = message.document.file_id, "document"
    await attach_receipt(bot, db, order["id"], file_id, kind)
    await message.answer(t("receipt_ok", lang, id=order["id"]))


@router.message()
async def fallback(message: Message, db: Database, cfg: Config) -> None:
    await open_menu(message, db, cfg)
