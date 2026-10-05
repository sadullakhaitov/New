"""Admin panel (bot ichida) va xodimlar guruhini ulash."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from html import escape

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    BufferedInputFile, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, Message,
    ReplyKeyboardMarkup,
)

from .. import access
from ..config import TASHKENT_TZ, Config
from ..core import CLOSED_FOREVER, delivery_zone, format_sum, norm_lang, parse_close_until, parse_price, shop_status
from ..db import Database
from ..translit import latin_to_cyrillic
from .user import main_keyboard

log = logging.getLogger(__name__)
router = Router(name="admin")

BACK_MAIN = "a:main"


class Input(StatesGroup):
    value = State()   # matn kutilmoqda (narx, nom, karta, ...)
    photo = State()   # taom rasmi kutilmoqda
    location = State()  # do'kon joylashuvi kutilmoqda


class AddProduct(StatesGroup):
    name = State()
    price = State()


def kb(*rows: list[tuple[str, str]]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=text, callback_data=data) for text, data in row] for row in rows
    ])


CANCEL_KB = kb([("❌ Bekor qilish", "a:cancel")])


def price_text(p: dict) -> str:
    if p["price"] is None:
        return "narx yo'q (Tez orada)"
    return f"{format_sum(p['price'])} so'm"


def parse_names(text: str) -> dict[str, str]:
    """«Lotin», «Lotin | Русский» yoki «Lotin | Кирилл | Русский»."""
    parts = [x.strip() for x in text.split("|")]
    if not parts[0] or len(parts[0]) > 60:
        raise ValueError("nom")
    if len(parts) == 2:
        return {"name_uz": parts[0], "name_cyr": "", "name_ru": parts[1]}
    return {"name_uz": parts[0], "name_cyr": parts[1] if len(parts) > 1 else "",
            "name_ru": parts[2] if len(parts) > 2 else ""}


async def _edit(call: CallbackQuery, text: str, markup: InlineKeyboardMarkup) -> None:
    try:
        await call.message.edit_text(text, reply_markup=markup)
    except TelegramBadRequest as exc:
        if "message is not modified" not in str(exc):
            await call.message.answer(text, reply_markup=markup)


# ---------- guruhni ulash ----------
@router.message(Command("setgroup"), F.chat.type.in_({"group", "supergroup"}))
async def set_group(message: Message, db: Database, cfg: Config, bot: Bot) -> None:
    user_id = message.from_user.id
    current = await access.group_id(db)
    allowed = user_id in cfg.superadmins
    if not allowed and await access.is_chat_admin(bot, message.chat.id, user_id):
        # Birinchi marta — guruh admini ulay oladi; keyin faqat eski guruh admini yoki superadmin.
        allowed = current is None or current == message.chat.id or await access.is_chat_admin(bot, current, user_id)
    if not allowed:
        await message.reply("⛔ Bu buyruq faqat guruh adminlari uchun.")
        return
    await db.set_setting("group_chat_id", str(message.chat.id))
    access.forget()
    await message.reply(
        "✅ Tayyor! Endi barcha yangi buyurtmalar shu guruhga keladi.\n\n"
        "Guruh adminlari botga shaxsiy chatda /admin deb yozib, menyu, narxlar, karta va "
        "do'kon holatini boshqarishi mumkin."
    )


@router.message(F.migrate_to_chat_id)
async def group_migrated(message: Message, db: Database) -> None:
    if await access.group_id(db) == message.chat.id:
        await db.set_setting("group_chat_id", str(message.migrate_to_chat_id))
        access.forget()


# ---------- kirish ----------
async def _guard_message(message: Message, db: Database, cfg: Config, bot: Bot) -> bool:
    if message.chat.type != "private" or not await access.is_admin(bot, db, cfg, message.from_user.id):
        return False
    return True


def _shop_line(closed_until: str) -> str:
    status = shop_status(closed_until)
    if status.is_open:
        return "🟢 Do'kon ochiq"
    return f"🔴 Do'kon yopiq ({status.until_text()} gacha)" if status.until else "🔴 Do'kon yopiq"


async def main_panel(db: Database) -> tuple[str, InlineKeyboardMarkup]:
    s = await db.all_settings()
    is_open = shop_status(s.get("closed_until", "")).is_open
    no_price = sum(1 for p in await db.products() if p["is_active"] and p["price"] is None)
    lines = ["🛠 <b>Emir Food — admin panel</b>", "", _shop_line(s.get("closed_until", ""))]
    if not s.get("group_chat_id"):
        lines.append("⚠️ Buyurtmalar guruhi ulanmagan — guruhda /setgroup yozing")
    if no_price:
        lines.append(f"❗ {no_price} ta taomning narxi yo'q")
    markup = kb(
        [("💰 Narxlar", "a:prices"), ("🍔 Taomlar", "a:menu")],
        [("🔴 Do'konni yopish" if is_open else "🟢 Do'konni ochish", "a:shop"), ("📦 Buyurtmalar", "a:orders")],
        [("🖼 Bannerlar", "b:list"), ("⚙️ Sozlamalar", "a:set")],
    )
    return "\n".join(lines), markup


async def settings_view(db: Database) -> tuple[str, InlineKeyboardMarkup]:
    s = await db.all_settings()
    zone = delivery_zone(s)
    text = (
        "⚙️ <b>Sozlamalar</b>\n\n"
        f"💳 Karta: <code>{escape(s.get('card_number', ''))}</code>\n"
        f"💰 Yetkazish uchun minimal summa: {format_sum(int(s.get('min_order') or 0))} so'm\n"
        f"📍 Yetkazish hududi: {f'{zone.radius_km:g} km' if zone else 'cheklanmagan'}\n"
        f"👥 Buyurtmalar guruhi: {'ulangan ✅' if s.get('group_chat_id') else 'ulanmagan ⚠️'}"
    )
    return text, kb(
        [("💳 Karta", "a:card"), ("💰 Minimal summa", "a:min")],
        [("📍 Yetkazish hududi", "a:zone"), ("💾 Zaxira nusxa", "a:backup")],
        [("⬅️ Orqaga", BACK_MAIN)],
    )


@router.message(Command("admin"))
async def admin_cmd(message: Message, db: Database, cfg: Config, bot: Bot, state: FSMContext) -> None:
    if not await _guard_message(message, db, cfg, bot):
        return
    await state.clear()
    text, markup = await main_panel(db)
    await message.answer(text, reply_markup=markup)


@router.message(Command("cancel"))
async def cancel_cmd(message: Message, state: FSMContext, db: Database, cfg: Config, bot: Bot) -> None:
    if await state.get_state() is None:
        return
    await state.clear()
    if await _guard_message(message, db, cfg, bot):
        text, markup = await main_panel(db)
        await message.answer("Bekor qilindi.\n\n" + text, reply_markup=markup)


# Barcha "a:" tugmalari uchun admin tekshiruvi.
admin_calls = Router(name="admin_calls")
router.include_router(admin_calls)


@admin_calls.callback_query.outer_middleware()
async def _only_admins(handler, call: CallbackQuery, data: dict):
    if not (call.data or "").startswith("a:"):
        return await handler(call, data)
    if not await access.is_admin(data["bot"], data["db"], data["cfg"], call.from_user.id):
        await call.answer("⛔ Ruxsat yo'q", show_alert=True)
        return None
    return await handler(call, data)


@admin_calls.callback_query(F.data == BACK_MAIN)
async def cb_main(call: CallbackQuery, db: Database, state: FSMContext) -> None:
    await state.clear()
    text, markup = await main_panel(db)
    await _edit(call, text, markup)
    await call.answer()


@admin_calls.callback_query(F.data == "a:cancel")
async def cb_cancel(call: CallbackQuery, db: Database, state: FSMContext) -> None:
    await state.clear()
    text, markup = await main_panel(db)
    await _edit(call, text, markup)
    await call.answer("Bekor qilindi")


@admin_calls.callback_query(F.data == "a:set")
async def cb_settings(call: CallbackQuery, db: Database, state: FSMContext) -> None:
    await state.clear()
    await _edit(call, *await settings_view(db))
    await call.answer()


# ---------- narxlar: bitta ro'yxat, bosing va yozing ----------
async def prices_view(db: Database) -> tuple[str, InlineKeyboardMarkup]:
    rows = []
    for c in await db.categories():
        for p in await db.products(c["id"]):
            price = format_sum(p["price"]) if p["price"] is not None else "narx yo'q ❗"
            hidden = " 🙈" if not p["is_active"] else ""
            rows.append([(f"{p['name_uz']} — {price}{hidden}", f"a:pr:{p['id']}")])
    rows.append([("⬅️ Orqaga", BACK_MAIN)])
    text = "💰 <b>Narxlar</b>\n\nTaomni bosing va yangi narxni yozing."
    return text, kb(*rows)


@admin_calls.callback_query(F.data == "a:prices")
async def cb_prices(call: CallbackQuery, db: Database, state: FSMContext) -> None:
    await state.clear()
    await _edit(call, *await prices_view(db))
    await call.answer()


def _price_prompt(p: dict) -> str:
    return (f"💰 <b>{escape(p['name_uz'])}</b>\nHozir: {price_text(p)}\n\n"
            "Yangi narxni yozing. Masalan: <code>35000</code> yoki qisqa <code>35</code>\n"
            "Narxni olib tashlash: <code>-</code>")


@admin_calls.callback_query(F.data.regexp(r"^a:(pr|pp):\d+$"))
async def cb_ask_price(call: CallbackQuery, db: Database, state: FSMContext) -> None:
    _, kind, pid = call.data.split(":")
    p = await db.product(int(pid))
    if p is None:
        await call.answer("Taom topilmadi", show_alert=True)
        return
    await state.set_state(Input.value)
    # a:pr — narxlar ro'yxatidan, a:pp — taom kartasidan; saqlangach o'sha joyga qaytiladi
    await state.update_data(action="pp", pid=p["id"], back="prices" if kind == "pr" else "product")
    await call.message.answer(_price_prompt(p), reply_markup=CANCEL_KB)
    await call.answer()


# ---------- menyu ----------
@admin_calls.callback_query(F.data == "a:menu")
async def cb_menu(call: CallbackQuery, db: Database) -> None:
    rows = [[(f"{c['name_uz']}", f"a:cat:{c['id']}")] for c in await db.categories()]
    rows.append([("➕ Yangi taom qo'shish", "a:add")])
    rows.append([("⬅️ Orqaga", BACK_MAIN)])
    await _edit(call, "🍔 <b>Taomlar</b>\n\nBo'limni tanlang.", kb(*rows))
    await call.answer()


async def category_view(db: Database, cid: int) -> tuple[str, InlineKeyboardMarkup]:
    cat = await db.category(cid)
    products = await db.products(cid)
    rows = []
    for p in products:
        mark = "⛔" if not p["is_active"] else ("🕓" if p["price"] is None else "✅")
        price = format_sum(p["price"]) if p["price"] is not None else "—"
        rows.append([(f"{mark} {p['name_uz']} · {price}", f"a:p:{p['id']}")])
    rows.append([("➕ Yangi taom qo'shish", f"a:addc:{cid}")])
    rows.append([("⬅️ Bo'limlar", "a:menu")])
    text = (f"📂 <b>{escape(cat['name_uz'] if cat else '')}</b>\n\n"
            "Taomni bosing: narx, rasm, nom yoki yashirish.\n"
            "✅ sotuvda · 🕓 narxi yo'q · ⛔ yashirilgan")
    return text, kb(*rows)


@admin_calls.callback_query(F.data.startswith("a:cat:"))
async def cb_category(call: CallbackQuery, db: Database) -> None:
    text, markup = await category_view(db, int(call.data.split(":")[2]))
    await _edit(call, text, markup)
    await call.answer()


async def product_view(db: Database, pid: int) -> tuple[str, InlineKeyboardMarkup] | None:
    p = await db.product(pid)
    if p is None:
        return None
    names = escape(p['name_cyr'] or latin_to_cyrillic(p['name_uz']))
    if p["name_ru"]:
        names += " · " + escape(p["name_ru"])
    text = (
        f"🍽 <b>{escape(p['name_uz'])}</b>\n<i>{names}</i>\n\n"
        f"💰 {price_text(p)}\n"
        f"{'👁 Menyuda ko‘rinadi' if p['is_active'] else '🙈 Menyuda yashirilgan'}"
        f"{' · ⭐ Hit' if p['is_hit'] else ''}"
    )
    price = format_sum(p["price"]) if p["price"] is not None else "yo'q"
    markup = kb(
        [(f"💰 Narx: {price}", f"a:pp:{pid}"), ("🖼 Rasm", f"a:pi:{pid}")],
        [("✏️ Nom", f"a:pn:{pid}"), ("🙈 Yashirish" if p["is_active"] else "👁 Ko'rsatish", f"a:pt:{pid}")],
        [("⭐ Hit: ha" if p["is_hit"] else "⭐ Hit: yo'q", f"a:ph:{pid}"), ("🗑 O'chirish", f"a:pd:{pid}")],
        [("⬅️ Orqaga", f"a:cat:{p['category_id']}")],
    )
    return text, markup


async def _show_product(call: CallbackQuery, db: Database, pid: int) -> None:
    view = await product_view(db, pid)
    if view is None:
        await call.answer("Taom topilmadi", show_alert=True)
        return
    await _edit(call, *view)
    await call.answer()


@admin_calls.callback_query(F.data.startswith("a:p:"))
async def cb_product(call: CallbackQuery, db: Database) -> None:
    await _show_product(call, db, int(call.data.split(":")[2]))


@admin_calls.callback_query(F.data.startswith("a:pt:"))
async def cb_toggle(call: CallbackQuery, db: Database) -> None:
    pid = int(call.data.split(":")[2])
    p = await db.product(pid)
    if p:
        await db.update_product(pid, is_active=0 if p["is_active"] else 1)
    await _show_product(call, db, pid)


@admin_calls.callback_query(F.data.startswith("a:ph:"))
async def cb_hit(call: CallbackQuery, db: Database) -> None:
    pid = int(call.data.split(":")[2])
    p = await db.product(pid)
    if p:
        await db.update_product(pid, is_hit=0 if p["is_hit"] else 1)
    await _show_product(call, db, pid)


@admin_calls.callback_query(F.data.startswith("a:pd:"))
async def cb_delete_ask(call: CallbackQuery, db: Database) -> None:
    pid = int(call.data.split(":")[2])
    p = await db.product(pid)
    if p is None:
        await call.answer()
        return
    await _edit(call, f"🗑 <b>{escape(p['name_uz'])}</b> menyudan butunlay o'chirilsinmi?\n\n"
                      "Vaqtincha olib qo'ymoqchi bo'lsangiz, «Yashirish» ni bosing.",
                kb([("✅ Ha, o'chirish", f"a:pdy:{pid}"), ("❌ Yo'q", f"a:p:{pid}")]))
    await call.answer()


@admin_calls.callback_query(F.data.startswith("a:pdy:"))
async def cb_delete(call: CallbackQuery, db: Database) -> None:
    pid = int(call.data.split(":")[2])
    p = await db.product(pid)
    if p:
        await db.delete_product(pid)
        text, markup = await category_view(db, p["category_id"])
        await _edit(call, "✅ O'chirildi.\n\n" + text, markup)
    await call.answer()


# ---------- matn kiritish ----------
PROMPTS = {
    "pp": "💰 Yangi narxni yozing. Masalan: <code>35000</code> yoki <code>35</code>",
    "pn": "✏️ Yangi nomni yozing. Masalan: <code>Tovuq lavash</code>\n"
          "<i>Kirillchasi o'zi yoziladi. Ruschasini ham qo'shish: <code>Tovuq lavash | Лаваш с курицей</code></i>",
    "card": "💳 Karta raqamini yozing (16 ta raqam).",
    "owner": "👤 Karta egasining ismini yozing. Ko'rsatmaslik: <code>-</code>",
    "min": "💰 Yetkazish uchun minimal summani yozing. Masalan: <code>50000</code>\nCheklovsiz: <code>0</code>",
    "radius": "📏 Necha km gacha yetkazasiz? Masalan: <code>3</code> yoki <code>2.5</code>",
    "close": "🕐 Qachongacha yopiq? Masalan: <code>10:00</code> yoki <code>07.10 09:00</code>",
}


@admin_calls.callback_query(F.data.regexp(r"^a:pn:\d+$"))
async def cb_ask_product_field(call: CallbackQuery, state: FSMContext) -> None:
    _, action, pid = call.data.split(":")
    await state.set_state(Input.value)
    await state.update_data(action=action, pid=int(pid))
    await call.message.answer(PROMPTS[action], reply_markup=CANCEL_KB)
    await call.answer()


@admin_calls.callback_query(F.data.startswith("a:pi:"))
async def cb_ask_photo(call: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(Input.photo)
    await state.update_data(pid=int(call.data.split(":")[2]))
    await call.message.answer("🖼 Taom rasmini yuboring (oddiy rasm sifatida).", reply_markup=CANCEL_KB)
    await call.answer()


@router.message(Input.value, F.text)
async def on_value(message: Message, state: FSMContext, db: Database, cfg: Config, bot: Bot) -> None:
    if not await _guard_message(message, db, cfg, bot):
        await state.clear()
        return
    data = await state.get_data()
    action, pid = data.get("action"), data.get("pid")
    text = message.text.strip()

    try:
        if action == "pp":
            await db.update_product(pid, price=parse_price(text))
        elif action == "pn":
            await db.update_product(pid, **parse_names(text))
        elif action == "card":
            digits = "".join(ch for ch in text if ch.isdigit())
            if len(digits) != 16:
                raise ValueError("karta")
            await db.set_setting("card_number", " ".join(digits[i:i + 4] for i in range(0, 16, 4)))
        elif action == "owner":
            await db.set_setting("card_owner", "" if text == "-" else text[:60])
        elif action == "min":
            await db.set_setting("min_order", str(parse_price(text) or 0))
        elif action == "radius":
            radius = float(text.replace(",", ".").replace("km", "").strip())
            if not 0.3 <= radius <= 50:
                raise ValueError("radius")
            await db.set_setting("delivery_radius_km", f"{radius:g}")
        elif action == "close":
            until = parse_close_until(text)
            if until is None:
                raise ValueError("vaqt")
            await db.set_setting("closed_until", until.isoformat(timespec="minutes"))
        else:
            await state.clear()
            return
    except ValueError:
        await message.answer("❗ Tushunmadim, qaytadan yozing.\n\n" + PROMPTS[action], reply_markup=CANCEL_KB)
        return

    await state.clear()
    if action == "pp" and data.get("back") == "prices":
        p = await db.product(pid)
        text_, markup = await prices_view(db)
        await message.answer(f"✅ {escape(p['name_uz'])} — {price_text(p)}\n\n" + text_, reply_markup=markup)
        return
    if action == "radius":
        text_, markup = await zone_view(db)
        await message.answer("✅ Saqlandi.\n\n" + text_, reply_markup=markup)
        return
    if action in ("card", "owner", "min"):
        text_, markup = await settings_view(db)
        await message.answer("✅ Saqlandi.\n\n" + text_, reply_markup=markup)
        return
    if pid is not None:
        view = await product_view(db, pid)
        if view:
            await message.answer("✅ Saqlandi.\n\n" + view[0], reply_markup=view[1])
            return
    text_, markup = await main_panel(db)
    await message.answer("✅ Saqlandi.\n\n" + text_, reply_markup=markup)


@router.message(Input.photo, F.photo)
async def on_photo(message: Message, state: FSMContext, db: Database, cfg: Config, bot: Bot) -> None:
    if not await _guard_message(message, db, cfg, bot):
        await state.clear()
        return
    pid = (await state.get_data()).get("pid")
    product = await db.product(pid)
    await state.clear()
    if product is None:
        return
    # Rasm Telegram serverlarida qoladi — hosting fayllarni o'chirsa ham yo'qolmaydi.
    await db.update_product(pid, img="tg:" + message.photo[-1].file_id)
    view = await product_view(db, pid)
    await message.answer("✅ Rasm yangilandi.\n\n" + view[0], reply_markup=view[1])


@router.message(Input.photo)
async def on_not_photo(message: Message) -> None:
    await message.answer("Iltimos, rasm yuboring yoki bekor qiling.", reply_markup=CANCEL_KB)


# ---------- taom qo'shish ----------
@admin_calls.callback_query(F.data == "a:add")
async def cb_add(call: CallbackQuery, db: Database) -> None:
    rows = [[(c["name_uz"], f"a:addc:{c['id']}")] for c in await db.categories()]
    rows.append([("⬅️ Orqaga", "a:menu")])
    await _edit(call, "➕ Yangi taom qaysi bo'limga?", kb(*rows))
    await call.answer()


@admin_calls.callback_query(F.data.startswith("a:addc:"))
async def cb_add_category(call: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AddProduct.name)
    await state.update_data(cid=int(call.data.split(":")[2]))
    await call.message.answer("✏️ Yangi taom nomini yozing. Masalan: <code>Tovuq lavash (katta)</code>",
                              reply_markup=CANCEL_KB)
    await call.answer()


@router.message(AddProduct.name, F.text)
async def add_name(message: Message, state: FSMContext, db: Database, cfg: Config, bot: Bot) -> None:
    if not await _guard_message(message, db, cfg, bot):
        await state.clear()
        return
    try:
        names = parse_names(message.text)
    except ValueError:
        await message.answer("❗ Nom 1–60 belgi bo'lsin. Qaytadan yozing.", reply_markup=CANCEL_KB)
        return
    await state.update_data(**names)
    await state.set_state(AddProduct.price)
    await message.answer("💰 Narxini yozing. Masalan: <code>35000</code> yoki <code>35</code>\n"
                         "Keyinroq kiritaman: <code>-</code>", reply_markup=CANCEL_KB)


@router.message(AddProduct.price, F.text)
async def add_price(message: Message, state: FSMContext, db: Database, cfg: Config, bot: Bot) -> None:
    if not await _guard_message(message, db, cfg, bot):
        await state.clear()
        return
    try:
        price = parse_price(message.text)
    except ValueError:
        await message.answer("❗ Raqam yozing, masalan <code>35000</code>.", reply_markup=CANCEL_KB)
        return
    await state.update_data(price=price)
    await _finish_add(message, state, db)


async def _finish_add(message: Message, state: FSMContext, db: Database) -> None:
    data = await state.get_data()
    await state.clear()
    cat = await db.category(data["cid"])
    pid = await db.add_product(
        category_id=data["cid"], name_uz=data["name_uz"], name_cyr=data["name_cyr"], name_ru=data["name_ru"],
        img=cat["img"] if cat else "", price=data["price"],
    )
    view = await product_view(db, pid)
    await message.answer("✅ Taom qo'shildi! Xohlasangiz, rasmini ham yuklang.\n\n" + view[0], reply_markup=view[1])


# ---------- do'kon holati ----------
def _tomorrow(hour: int) -> datetime:
    now = datetime.now(TASHKENT_TZ)
    return (now + timedelta(days=1)).replace(hour=hour, minute=0, second=0, microsecond=0)


@admin_calls.callback_query(F.data == "a:shop")
async def cb_shop(call: CallbackQuery, db: Database) -> None:
    status = shop_status(await db.get_setting("closed_until"))
    if status.is_open:
        t8 = _tomorrow(8)
        text = ("🟢 Do'kon hozir <b>ochiq</b>.\n\nQachongacha yopamiz?\n"
                "<i>Yopiq paytda mijozlar menyuni ko'radi, lekin buyurtma bera olmaydi.</i>")
        rows = [
            [(f"🌙 Ertaga {t8:%d.%m} 08:00 gacha", "a:cl:8")],
            [("🕐 Boshqa vaqtgacha", "a:cl:custom"), ("⛔ Men ochgunimcha", "a:cl:forever")],
        ]
    else:
        text = _shop_line(await db.get_setting("closed_until")) + ".\n\nBuyurtmalar qabul qilinmayapti."
        rows = [[("🟢 Hozir ochish", "a:open")]]
    rows.append([("⬅️ Orqaga", BACK_MAIN)])
    await _edit(call, text, kb(*rows))
    await call.answer()


@admin_calls.callback_query(F.data.startswith("a:cl:"))
async def cb_close(call: CallbackQuery, db: Database, state: FSMContext) -> None:
    arg = call.data.split(":")[2]
    if arg == "custom":
        await state.set_state(Input.value)
        await state.update_data(action="close", pid=None)
        await call.message.answer(PROMPTS["close"], reply_markup=CANCEL_KB)
        await call.answer()
        return
    value = CLOSED_FOREVER if arg == "forever" else _tomorrow(int(arg)).isoformat(timespec="minutes")
    await db.set_setting("closed_until", value)
    await cb_shop(call, db)


@admin_calls.callback_query(F.data == "a:open")
async def cb_open(call: CallbackQuery, db: Database) -> None:
    await db.set_setting("closed_until", "")
    await cb_shop(call, db)


# ---------- yetkazish hududi ----------
async def zone_view(db: Database) -> tuple[str, InlineKeyboardMarkup]:
    s = await db.all_settings()
    zone = delivery_zone(s)
    has_loc = bool(s.get("shop_lat") and s.get("shop_lon"))
    radius = s.get("delivery_radius_km") or ""
    if zone:
        state = f"🟢 Yoqilgan: do'kondan <b>{zone.radius_km:g} km</b> gacha yetkaziladi."
    else:
        state = "⚪ O'chiq: manzil tekshirilmaydi."
    text = (
        "📍 <b>Yetkazish hududi</b>\n\n" + state + "\n"
        f"Do'kon joylashuvi: {'✅ kiritilgan' if has_loc else '— kiritilmagan'}\n"
        f"Radius: {radius + ' km' if radius else '— kiritilmagan'}\n\n"
        "Mijoz lokatsiya yuborsa va u radiusdan uzoq bo'lsa, yetkazib berish buyurtmasi qabul qilinmaydi "
        "(olib ketishni tanlashi mumkin). Lokatsiyasiz buyurtmalar guruhda ⚠️ bilan belgilanadi."
    )
    rows = [[("📍 Do'kon joylashuvi", "a:zone:loc"), ("📏 Radius", "a:zone:r")]]
    if has_loc or radius:
        rows.append([("🚫 Tekshiruvni o'chirish", "a:zone:off")])
    rows.append([("⬅️ Orqaga", "a:set")])
    return text, kb(*rows)


@admin_calls.callback_query(F.data == "a:zone")
async def cb_zone(call: CallbackQuery, db: Database, state: FSMContext) -> None:
    await state.clear()
    await _edit(call, *await zone_view(db))
    await call.answer()


@admin_calls.callback_query(F.data == "a:zone:r")
async def cb_zone_radius(call: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(Input.value)
    await state.update_data(action="radius", pid=None)
    await call.message.answer(PROMPTS["radius"], reply_markup=CANCEL_KB)
    await call.answer()


@admin_calls.callback_query(F.data == "a:zone:off")
async def cb_zone_off(call: CallbackQuery, db: Database) -> None:
    for key in ("shop_lat", "shop_lon", "delivery_radius_km"):
        await db.set_setting(key, "")
    await _edit(call, *await zone_view(db))
    await call.answer("Tekshiruv o'chirildi")


@admin_calls.callback_query(F.data == "a:zone:loc")
async def cb_zone_location(call: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(Input.location)
    await call.message.answer(
        "📍 Do'kon turgan joyda turib pastdagi tugmani bosing yoki 📎 → <b>Lokatsiya</b> orqali do'kon joyini yuboring.",
        reply_markup=ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text="📍 Joylashuvni yuborish", request_location=True)],
                      [KeyboardButton(text="❌ Bekor qilish")]],
            resize_keyboard=True, one_time_keyboard=True,
        ),
    )
    await call.answer()


@router.message(Input.location, F.location)
async def on_shop_location(message: Message, state: FSMContext, db: Database, cfg: Config, bot: Bot) -> None:
    if not await _guard_message(message, db, cfg, bot):
        await state.clear()
        return
    await state.clear()
    await db.set_setting("shop_lat", f"{message.location.latitude:.6f}")
    await db.set_setting("shop_lon", f"{message.location.longitude:.6f}")
    user = await db.user(message.from_user.id)
    await message.answer("✅ Do'kon joylashuvi saqlandi.", reply_markup=main_keyboard(norm_lang(user and user["lang"])))
    text, markup = await zone_view(db)
    if not await db.get_setting("delivery_radius_km"):
        text += "\n\n👉 Endi «📏 Radius» ni bosib, necha km gacha yetkazishni kiriting."
    await message.answer(text, reply_markup=markup)


@router.message(Input.location)
async def on_not_location(message: Message, state: FSMContext, db: Database) -> None:
    await state.clear()
    user = await db.user(message.from_user.id)
    await message.answer("Bekor qilindi.", reply_markup=main_keyboard(norm_lang(user and user["lang"])))


# ---------- buyurtmalar ----------
@admin_calls.callback_query(F.data == "a:orders")
async def cb_orders(call: CallbackQuery, db: Database) -> None:
    now = datetime.now(TASHKENT_TZ)
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    n_today, s_today = await db.orders_summary(today.isoformat(timespec="seconds"))
    n_week, s_week = await db.orders_summary((today - timedelta(days=6)).isoformat(timespec="seconds"))
    lines = [
        "📦 <b>Buyurtmalar</b>",
        f"Bugun: <b>{n_today}</b> ta · {format_sum(s_today)} so'm",
        f"Oxirgi 7 kun: <b>{n_week}</b> ta · {format_sum(s_week)} so'm",
        "",
    ]
    orders = await db.recent_orders(10)
    if not orders:
        lines.append("Hali buyurtmalar yo'q.")
    for o in orders:
        when = datetime.fromisoformat(o["created_at"]).strftime("%d.%m %H:%M")
        kind = "🚚" if o["kind"] == "delivery" else "🏃"
        pay = {"cash": "💵", "card": "💳"}.get(o["payment"], "🤝")
        state = {"accepted": " ✅", "canceled": " ❌"}.get(o.get("status") or "", " 🆕")
        items = ", ".join(f"{i['name']}{' (' + ('katta' if i['size'] == 'large' else 'kichik') + ')' if i.get('size') else ''} ×{i['qty']}"
                          for i in o["items"])
        lines.append(f"<b>№{o['id']}</b>{state} · {when} {kind}{pay} · <b>{format_sum(o['total'])}</b>\n"
                     f"👤 {escape(o['name'])}, {escape(o['phone'])}\n{escape(items)}\n")
    text = "\n".join(lines)
    if len(text) > 4000:
        text = text[:3990] + "…"
    await _edit(call, text, kb([("🔄 Yangilash", "a:orders")], [("⬅️ Orqaga", BACK_MAIN)]))
    await call.answer()


# ---------- karta, minimal summa, zaxira ----------
@admin_calls.callback_query(F.data == "a:card")
async def cb_card(call: CallbackQuery, db: Database) -> None:
    s = await db.all_settings()
    owner = s.get("card_owner") or "ko'rsatilmagan"
    await _edit(call, f"💳 Karta: <code>{escape(s.get('card_number', ''))}</code>\n👤 Egasi: {escape(owner)}\n\n"
                      "Mijoz «Kartaga o'tkazma» tanlasa, shu ma'lumot ko'rsatiladi.",
                kb([("✏️ Karta raqami", "a:in:card"), ("✏️ Karta egasi", "a:in:owner")],
                   [("⬅️ Orqaga", "a:set")]))
    await call.answer()


@admin_calls.callback_query(F.data == "a:min")
async def cb_min(call: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(Input.value)
    await state.update_data(action="min", pid=None)
    await call.message.answer(PROMPTS["min"], reply_markup=CANCEL_KB)
    await call.answer()


@admin_calls.callback_query(F.data.in_({"a:in:card", "a:in:owner"}))
async def cb_card_input(call: CallbackQuery, state: FSMContext) -> None:
    action = call.data.split(":")[2]
    await state.set_state(Input.value)
    await state.update_data(action=action, pid=None)
    await call.message.answer(PROMPTS[action], reply_markup=CANCEL_KB)
    await call.answer()


@admin_calls.callback_query(F.data == "a:backup")
async def cb_backup(call: CallbackQuery, db: Database) -> None:
    data = await db.export_json()
    try:
        await call.message.answer_document(
            BufferedInputFile(data, filename=f"emirfood_{datetime.now(TASHKENT_TZ):%Y%m%d_%H%M}.json"),
            caption="💾 Zaxira nusxa: menyu, sozlamalar, mijozlar va buyurtmalar.",
        )
    except TelegramAPIError as exc:
        log.error("Zaxira yuborilmadi: %s", exc)
    await call.answer()
