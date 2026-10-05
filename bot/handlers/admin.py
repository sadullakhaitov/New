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
    BufferedInputFile, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message,
)

from .. import access
from ..config import TASHKENT_TZ, Config
from ..core import CLOSED_FOREVER, format_sum, parse_close_until, parse_price, shop_status
from ..db import Database
from ..translit import latin_to_cyrillic

log = logging.getLogger(__name__)
router = Router(name="admin")

BACK_MAIN = "a:main"


class Input(StatesGroup):
    value = State()   # matn kutilmoqda (narx, nom, karta, ...)
    photo = State()   # taom rasmi kutilmoqda


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


async def main_panel(db: Database) -> tuple[str, InlineKeyboardMarkup]:
    s = await db.all_settings()
    status = shop_status(s.get("closed_until", ""))
    state = "🟢 Ochiq" if status.is_open else (
        f"🔴 Yopiq ({status.until_text()} gacha)" if status.until else "🔴 Yopiq (noma'lum muddatga)"
    )
    group = "✅ ulangan" if s.get("group_chat_id") else "⚠️ ulanmagan — guruhda /setgroup yozing"
    text = (
        "🛠 <b>Emir Food — admin panel</b>\n\n"
        f"Do'kon: {state}\n"
        f"Buyurtmalar guruhi: {group}\n"
        f"Karta: <code>{escape(s.get('card_number', ''))}</code>\n"
        f"Minimal summa (yetkazish): {format_sum(int(s.get('min_order') or 0))} so'm"
    )
    markup = kb(
        [("🍔 Menyu va narxlar", "a:menu"), ("➕ Taom qo'shish", "a:add")],
        [("🔒 Do'kon holati", "a:shop"), ("💳 Karta", "a:card")],
        [("📦 Buyurtmalar", "a:orders"), ("🖼 Bannerlar", "b:list")],
        [("💰 Minimal summa", "a:min"), ("💾 Zaxira nusxa", "a:backup")],
    )
    return text, markup


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


# ---------- menyu ----------
@admin_calls.callback_query(F.data == "a:menu")
async def cb_menu(call: CallbackQuery, db: Database) -> None:
    rows = [[(f"{c['name_uz']}", f"a:cat:{c['id']}")] for c in await db.categories()]
    rows.append([("⬅️ Orqaga", BACK_MAIN)])
    await _edit(call, "🍔 <b>Bo'limni tanlang</b>", kb(*rows))
    await call.answer()


async def category_view(db: Database, cid: int) -> tuple[str, InlineKeyboardMarkup]:
    cat = await db.category(cid)
    products = await db.products(cid)
    rows = []
    for p in products:
        mark = "⛔" if not p["is_active"] else ("🕓" if p["price"] is None else "✅")
        price = format_sum(p["price"]) if p["price"] is not None else "—"
        rows.append([(f"{mark} {p['name_uz']} · {price}", f"a:p:{p['id']}")])
    rows.append([("➕ Shu bo'limga taom qo'shish", f"a:addc:{cid}")])
    rows.append([("⬅️ Bo'limlar", "a:menu")])
    text = (f"📂 <b>{escape(cat['name_uz'] if cat else '')}</b>\n\n"
            "✅ sotuvda · 🕓 narx kiritilmagan · ⛔ yashirilgan")
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
    status = "ko'rinadi" if p["is_active"] else "yashirilgan"
    text = (
        f"🍽 <b>{escape(p['name_uz'])}</b>\n"
        f"Kirill: {escape(p['name_cyr'] or latin_to_cyrillic(p['name_uz']))}\n"
        f"Rus: {escape(p['name_ru'] or '—')}\n\n"
        f"💰 {price_text(p)}\n"
        f"👁 Menyuda: {status}\n"
        f"⭐ Hit: {'ha' if p['is_hit'] else 'yo‘q'}"
    )
    markup = kb(
        [("💰 Narx", f"a:pp:{pid}"), ("✏️ Nomi", f"a:pn:{pid}"), ("🖼 Rasm", f"a:pi:{pid}")],
        [("🙈 Yashirish" if p["is_active"] else "👁 Ko'rsatish", f"a:pt:{pid}"),
         ("⭐ Hitni olib tashlash" if p["is_hit"] else "⭐ Hit qilish", f"a:ph:{pid}")],
        [("🗑 O'chirish", f"a:pd:{pid}")],
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
    "pp": "💰 Yangi narxni yozing (so'mda).\nMasalan: <code>35000</code> yoki <code>35</code>.\n"
          "<code>-</code> — narxni olib tashlash (menyuda «Tez orada» bo'ladi).",
    "pn": "✏️ Yangi nomni yozing (lotinda).\nKirill avtomatik yoziladi.\n"
          "Uch tilda yozish uchun: <code>Lotin | Кирилл | Русский</code>",
    "card": "💳 Yangi karta raqamini yozing (16 xonali).",
    "owner": "👤 Karta egasining ism-familiyasini yozing.\n<code>-</code> — ko'rsatmaslik.",
    "min": "💰 Yetkazib berish uchun minimal summani yozing (so'mda).\n<code>0</code> — cheklov yo'q.",
    "close": "🕐 Qachongacha yopiq bo'lishini yozing.\nMasalan: <code>10:00</code>, "
             "<code>07.10 09:00</code> yoki <code>07.10.2026 09:00</code>",
}


@admin_calls.callback_query(F.data.regexp(r"^a:(pp|pn):\d+$"))
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
            parts = [x.strip() for x in text.split("|")]
            if not parts[0] or len(parts[0]) > 60:
                raise ValueError("nom")
            fields = {"name_uz": parts[0], "name_cyr": parts[1] if len(parts) > 1 else "",
                      "name_ru": parts[2] if len(parts) > 2 else ""}
            await db.update_product(pid, **fields)
        elif action == "card":
            digits = "".join(ch for ch in text if ch.isdigit())
            if len(digits) != 16:
                raise ValueError("karta")
            await db.set_setting("card_number", " ".join(digits[i:i + 4] for i in range(0, 16, 4)))
        elif action == "owner":
            await db.set_setting("card_owner", "" if text == "-" else text[:60])
        elif action == "min":
            await db.set_setting("min_order", str(parse_price(text) or 0))
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
    rows.append([("⬅️ Orqaga", BACK_MAIN)])
    await _edit(call, "➕ Yangi taom qaysi bo'limga qo'shilsin?", kb(*rows))
    await call.answer()


@admin_calls.callback_query(F.data.startswith("a:addc:"))
async def cb_add_category(call: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AddProduct.name)
    await state.update_data(cid=int(call.data.split(":")[2]))
    await call.message.answer(
        "✏️ Taom nomini yozing (lotinda). Masalan: <code>Tovuq lavash (katta)</code>\n"
        "Kichik va katta o'lcham — alohida taom sifatida qo'shiladi.\n"
        "Uch tilda: <code>Tovuq lavash | Товуқ лаваш | Лаваш с курицей</code>",
        reply_markup=CANCEL_KB,
    )
    await call.answer()


@router.message(AddProduct.name, F.text)
async def add_name(message: Message, state: FSMContext, db: Database, cfg: Config, bot: Bot) -> None:
    if not await _guard_message(message, db, cfg, bot):
        await state.clear()
        return
    parts = [x.strip() for x in message.text.split("|")]
    if not parts[0] or len(parts[0]) > 60:
        await message.answer("❗ Nom 1–60 belgi bo'lsin. Qaytadan yozing.", reply_markup=CANCEL_KB)
        return
    await state.update_data(name_uz=parts[0], name_cyr=parts[1] if len(parts) > 1 else "",
                            name_ru=parts[2] if len(parts) > 2 else "")
    await state.set_state(AddProduct.price)
    await message.answer("💰 Narxini yozing.\nMasalan: <code>35000</code>. "
                         "<code>-</code> — keyinroq kiritaman.", reply_markup=CANCEL_KB)


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
        head = "🟢 Do'kon hozir <b>ochiq</b>, buyurtmalar qabul qilinmoqda."
    elif status.until:
        head = f"🔴 Do'kon <b>{status.until_text()}</b> gacha yopiq."
    else:
        head = "🔴 Do'kon noma'lum muddatga yopiq."
    t8, t10 = _tomorrow(8), _tomorrow(10)
    rows = [
        [(f"🌙 Ertagacha ({t8:%d.%m} 08:00)", "a:cl:8"), (f"🌙 Ertagacha ({t10:%d.%m} 10:00)", "a:cl:10")],
        [("🕐 Sana va soatni yozish", "a:cl:custom")],
        [("⛔ Noma'lum muddatga yopish", "a:cl:forever")],
    ]
    if not status.is_open:
        rows.insert(0, [("🟢 Hozir ochish", "a:open")])
    rows.append([("⬅️ Orqaga", BACK_MAIN)])
    await _edit(call, head + "\n\nYopiq paytda mijozlar menyuni ko'radi, lekin buyurtma bera olmaydi.", kb(*rows))
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
        pay = "💵" if o["payment"] == "cash" else "💳"
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
                   [("⬅️ Orqaga", BACK_MAIN)]))
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
