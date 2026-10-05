"""Admin panel: bosh sahifadagi aylanib turadigan bannerlar (yangiliklar, chegirmalar)."""
from __future__ import annotations

from html import escape

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from .. import access
from ..config import Config
from ..core import localized
from ..db import Database
from .admin import BACK_MAIN, CANCEL_KB, _edit, _guard_message, kb

router = Router(name="banners")

MAX_BANNERS = 6
THEMES = {"yellow": "🟡 Sariq", "red": "🔴 Qizil", "dark": "⚫ Qora"}
FIELDS = {"tag": "🏷 Belgi", "title": "📝 Sarlavha", "text": "💬 Matn"}
FIELD_HINTS = {
    "tag": "Kichik belgi, masalan: <code>CHEGIRMA</code>, <code>YANGI</code>, <code>HIT</code>.",
    "title": "Katta sarlavha, masalan: <code>Ikkinchi lavash -20%</code>.",
    "text": "Qisqa matn. <code>{price}</code> — ulangan taom narxi, <code>{min}</code> — minimal summa.",
}


class BannerInput(StatesGroup):
    text = State()
    photo = State()


@router.callback_query.outer_middleware()
async def _only_admins(handler, call: CallbackQuery, data: dict):
    if not (call.data or "").startswith("b:"):
        return await handler(call, data)  # boshqa tugmalar (buyurtma, til) — o'z routerlariga o'tadi
    if not await access.is_admin(data["bot"], data["db"], data["cfg"], call.from_user.id):
        await call.answer("⛔ Ruxsat yo'q", show_alert=True)
        return None
    return await handler(call, data)


async def list_view(db: Database) -> tuple[str, object]:
    banners = await db.banners()
    rows = [[(f"{'✅' if b['is_active'] else '🙈'} {b['title_uz'] or 'Nomsiz'}", f"b:v:{b['id']}")] for b in banners]
    if len(banners) < MAX_BANNERS:
        rows.append([("➕ Yangi banner", "b:new")])
    rows.append([("⬅️ Orqaga", BACK_MAIN)])
    text = ("🖼 <b>Bannerlar</b>\n\nBosh sahifada o'zi aylanib turadi (mijoz qo'lda ham surishi mumkin). "
            "Yangiliklar, chegirmalar va aksiyalar uchun.\n✅ ko'rinadi · 🙈 yashirilgan")
    return text, kb(*rows)


async def banner_view(db: Database, bid: int) -> tuple[str, object] | None:
    b = await db.banner(bid)
    if b is None:
        return None
    product = await db.product(b["product_id"]) if b["product_id"] else None
    img = "o'zingiz yuklagan rasm" if b["img"].startswith("tg:") else ("taom rasmi" if product and not b["img"] else "standart rasm")
    text = (
        f"🖼 <b>Banner</b> ({'✅ ko‘rinadi' if b['is_active'] else '🙈 yashirilgan'})\n\n"
        f"🏷 Belgi: {escape(b['tag_uz'] or '—')}\n"
        f"📝 Sarlavha: <b>{escape(b['title_uz'] or '—')}</b>\n"
        f"💬 Matn: {escape(b['text_uz'] or '—')}\n"
        f"🎨 Rang: {THEMES.get(b['theme'], b['theme'])}\n"
        f"🍔 Taom: {escape(product['name_uz']) if product else 'ulanmagan'}\n"
        f"🖼 Rasm: {img}\n\n"
        "Taom ulangan bo'lsa, mijoz bannerni bosganda o'sha taom ochiladi."
    )
    markup = kb(
        [("🏷 Belgi", f"b:f:tag:{bid}"), ("📝 Sarlavha", f"b:f:title:{bid}"), ("💬 Matn", f"b:f:text:{bid}")],
        [("🎨 Rang", f"b:th:{bid}"), ("🖼 Rasm", f"b:img:{bid}"), ("🍔 Taom", f"b:pc:{bid}")],
        [("🙈 Yashirish" if b["is_active"] else "👁 Ko'rsatish", f"b:t:{bid}"), ("⬆️ Yuqoriga", f"b:up:{bid}")],
        [("🗑 O'chirish", f"b:del:{bid}")],
        [("⬅️ Bannerlar", "b:list")],
    )
    return text, markup


async def _show(call: CallbackQuery, db: Database, bid: int, note: str = "") -> None:
    view = await banner_view(db, bid)
    if view is None:
        text, markup = await list_view(db)
        await _edit(call, text, markup)
    else:
        await _edit(call, note + view[0], view[1])
    await call.answer()


def _bid(call: CallbackQuery) -> int:
    return int(call.data.rsplit(":", 1)[1])


@router.callback_query(F.data == "b:list")
async def cb_list(call: CallbackQuery, db: Database, state: FSMContext) -> None:
    await state.clear()
    text, markup = await list_view(db)
    await _edit(call, text, markup)
    await call.answer()


@router.callback_query(F.data == "b:new")
async def cb_new(call: CallbackQuery, db: Database) -> None:
    if len(await db.banners()) >= MAX_BANNERS:
        await call.answer(f"Ko'pi bilan {MAX_BANNERS} ta banner", show_alert=True)
        return
    bid = await db.add_banner(tag_uz="YANGI", title_uz="Yangi banner", text_uz="Matnni o'zgartiring",
                              img="static/img/photos/burger.webp", theme="yellow", is_active=0)
    await _show(call, db, bid, "✅ Banner yaratildi (hozircha yashirilgan). Matnini yozib, «Ko'rsatish» ni bosing.\n\n")


@router.callback_query(F.data.startswith("b:v:"))
async def cb_view(call: CallbackQuery, db: Database) -> None:
    await _show(call, db, _bid(call))


@router.callback_query(F.data.startswith("b:t:"))
async def cb_toggle(call: CallbackQuery, db: Database) -> None:
    b = await db.banner(_bid(call))
    if b:
        await db.update_banner(b["id"], is_active=0 if b["is_active"] else 1)
    await _show(call, db, _bid(call))


@router.callback_query(F.data.startswith("b:th:"))
async def cb_theme(call: CallbackQuery, db: Database) -> None:
    b = await db.banner(_bid(call))
    if b:
        order = list(THEMES)
        nxt = order[(order.index(b["theme"]) + 1) % len(order)] if b["theme"] in order else order[0]
        await db.update_banner(b["id"], theme=nxt)
    await _show(call, db, _bid(call))


@router.callback_query(F.data.startswith("b:up:"))
async def cb_up(call: CallbackQuery, db: Database) -> None:
    banners = await db.banners()
    ids = [b["id"] for b in banners]
    bid = _bid(call)
    if bid in ids and ids.index(bid) > 0:
        i = ids.index(bid)
        ids[i - 1], ids[i] = ids[i], ids[i - 1]
        for pos, x in enumerate(ids):
            await db.update_banner(x, sort=(pos + 1) * 10)
    await _show(call, db, bid)


@router.callback_query(F.data.startswith("b:del:"))
async def cb_delete_ask(call: CallbackQuery, db: Database) -> None:
    bid = _bid(call)
    await _edit(call, "🗑 Banner butunlay o'chirilsinmi?\nVaqtincha olib qo'yish uchun «Yashirish» ni bosing.",
                kb([("✅ Ha, o'chirish", f"b:dely:{bid}"), ("❌ Yo'q", f"b:v:{bid}")]))
    await call.answer()


@router.callback_query(F.data.startswith("b:dely:"))
async def cb_delete(call: CallbackQuery, db: Database) -> None:
    await db.delete_banner(_bid(call))
    text, markup = await list_view(db)
    await _edit(call, "✅ O'chirildi.\n\n" + text, markup)
    await call.answer()


# ---------- taomga ulash ----------
@router.callback_query(F.data.startswith("b:pc:"))
async def cb_pick_category(call: CallbackQuery, db: Database) -> None:
    bid = _bid(call)
    rows = [[(c["name_uz"], f"b:pcat:{c['id']}:{bid}")] for c in await db.categories()]
    rows.append([("🚫 Taomni ajratish", f"b:pn:0:{bid}")])
    rows.append([("⬅️ Orqaga", f"b:v:{bid}")])
    await _edit(call, "🍔 Banner qaysi taomga ulansin? Bo'limni tanlang:", kb(*rows))
    await call.answer()


@router.callback_query(F.data.startswith("b:pcat:"))
async def cb_pick_product(call: CallbackQuery, db: Database) -> None:
    _, _, cid, bid = call.data.split(":")
    rows = [[(p["name_uz"], f"b:pn:{p['id']}:{bid}")] for p in await db.products(int(cid)) if p["is_active"]]
    rows.append([("⬅️ Orqaga", f"b:pc:{bid}")])
    await _edit(call, "🍔 Taomni tanlang:", kb(*rows))
    await call.answer()


@router.callback_query(F.data.startswith("b:pn:"))
async def cb_set_product(call: CallbackQuery, db: Database) -> None:
    _, _, pid, bid = call.data.split(":")
    await db.update_banner(int(bid), product_id=int(pid) or None)
    await _show(call, db, int(bid), "✅ Saqlandi.\n\n")


# ---------- matn va rasm ----------
@router.callback_query(F.data.startswith("b:f:"))
async def cb_ask_field(call: CallbackQuery, db: Database, state: FSMContext) -> None:
    _, _, field, bid = call.data.split(":")
    b = await db.banner(int(bid))
    if b is None:
        await call.answer()
        return
    current = " | ".join(x for x in (b[f"{field}_uz"], localized(b, field, "cyr"), b[f"{field}_ru"]) if x)
    await state.set_state(BannerInput.text)
    await state.update_data(field=field, bid=int(bid))
    await call.message.answer(
        f"{FIELDS[field]} — yangi matnni yozing.\n{FIELD_HINTS[field]}\n\n"
        "Uch tilda yozish: <code>Lotin | Кирилл | Русский</code> (kirill yozilmasa, avtomatik o'giriladi).\n"
        "<code>-</code> — bo'sh qoldirish.\n\n"
        f"Hozirgi: <code>{escape(current or '—')}</code>",
        reply_markup=CANCEL_KB,
    )
    await call.answer()


@router.message(BannerInput.text, F.text)
async def on_text(message: Message, state: FSMContext, db: Database, cfg: Config, bot: Bot) -> None:
    if not await _guard_message(message, db, cfg, bot):
        await state.clear()
        return
    data = await state.get_data()
    field, bid = data["field"], data["bid"]
    raw = message.text.strip()
    parts = ["", "", ""] if raw == "-" else ([x.strip()[:80] for x in raw.split("|")] + ["", ""])[:3]
    await db.update_banner(bid, **{f"{field}_uz": parts[0], f"{field}_cyr": parts[1], f"{field}_ru": parts[2]})
    await state.clear()
    view = await banner_view(db, bid)
    if view:
        await message.answer("✅ Saqlandi.\n\n" + view[0], reply_markup=view[1])


@router.callback_query(F.data.startswith("b:img:"))
async def cb_ask_photo(call: CallbackQuery, state: FSMContext) -> None:
    bid = _bid(call)
    await state.set_state(BannerInput.photo)
    await state.update_data(bid=bid)
    await call.message.answer(
        "🖼 Banner uchun rasm yuboring (oddiy rasm sifatida). Eng yaxshisi — orqa foni yo'q yoki oddiy taom surati.",
        reply_markup=kb([("♻️ Taom rasmini ishlatish", f"b:imgr:{bid}")], [("❌ Bekor qilish", "a:cancel")]),
    )
    await call.answer()


@router.callback_query(F.data.startswith("b:imgr:"))
async def cb_reset_photo(call: CallbackQuery, db: Database, state: FSMContext) -> None:
    await state.clear()
    bid = _bid(call)
    b = await db.banner(bid)
    if b:
        await db.update_banner(bid, img="" if b["product_id"] else "static/img/photos/burger.webp")
    await _show(call, db, bid, "✅ Saqlandi.\n\n")


@router.message(BannerInput.photo, F.photo)
async def on_photo(message: Message, state: FSMContext, db: Database, cfg: Config, bot: Bot) -> None:
    if not await _guard_message(message, db, cfg, bot):
        await state.clear()
        return
    bid = (await state.get_data()).get("bid")
    await state.clear()
    await db.update_banner(bid, img="tg:" + message.photo[-1].file_id)
    view = await banner_view(db, bid)
    if view:
        await message.answer("✅ Rasm yangilandi.\n\n" + view[0], reply_markup=view[1])


@router.message(BannerInput.photo)
async def on_not_photo(message: Message) -> None:
    await message.answer("Iltimos, rasm yuboring yoki bekor qiling.", reply_markup=CANCEL_KB)
