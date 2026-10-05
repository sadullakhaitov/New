"""Buyurtma xabarlarini tayyorlash (xodimlar guruhi va mijoz uchun)."""
from __future__ import annotations

from datetime import datetime
from html import escape
from typing import Any

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from .core import format_sum, norm_lang
from .texts import t


def _line_name(line: dict[str, Any], lang: str) -> str:
    names = line.get("names") or {}
    name = names.get(lang) or line["name"]
    if line.get("size"):
        name += f" ({t('size_' + line['size'], lang)})"
    return name


def order_lines_text(order: dict[str, Any], lang: str) -> str:
    cur = t("currency", lang)
    return "\n".join(
        f"▫️ {line['qty']} × {escape(_line_name(line, lang))} — {format_sum(line['sum'])} {cur}"
        for line in order["items"]
    )


SEP = "➖➖➖➖➖➖➖➖"
# Telegram rasm/fayl izohi (caption) shu uzunlikdan oshmasligi kerak
CAPTION_LIMIT = 1024


def map_links(lat: float, lon: float) -> str:
    return (f'<a href="https://maps.google.com/?q={lat},{lon}">Google xarita</a>  ·  '
            f'<a href="https://yandex.uz/maps/?pt={lon},{lat}&amp;z=17&amp;l=map">Yandex xarita</a>')


def group_order_text(order: dict[str, Any], username: str = "") -> str:
    """Xodimlar guruhiga boradigan xabar (doim o'zbek lotin).

    Tartib: holat → taomlar va summa → to'lov → olib ketish/yetkazish → mijoz.
    """
    created = datetime.fromisoformat(order["created_at"]).strftime("%d.%m · %H:%M")
    status = order.get("status") or "new"
    when = datetime.fromisoformat(order["status_at"]).strftime("%H:%M") if order.get("status_at") else ""
    by = escape(order.get("status_by") or "")
    head = {
        "new": "🆕 <b>YANGI BUYURTMA</b>",
        "accepted": f"✅ <b>QABUL QILINDI</b> — {by}, {when}",
        "canceled": f"❌ <b>BEKOR QILINDI</b> — {by}, {when}",
    }.get(status, "🆕 <b>YANGI BUYURTMA</b>")
    parts = [head, f"<b>№{order['id']}</b>  ·  🕒 {created}", SEP, order_lines_text(order, "uz"), "",
             f"💰 <b>JAMI: {format_sum(order['total'])} so'm</b>"]

    if order["payment"] == "cash":
        parts.append("💵 To'lov: <b>naqd pul</b>")
    elif order.get("receipt_file_id"):
        parts.append("💳 To'lov: <b>kartaga</b> — 🧾 chek ilova qilingan ✅")
    else:
        parts.append("💳 To'lov: <b>kartaga</b> — ⏳ chek hali yuborilmagan")
    parts.append(SEP)

    if order["kind"] == "delivery":
        parts.append("🚚 <b>YETKAZIB BERISH</b>")
        if order.get("address"):
            parts.append(f"🏠 {escape(order['address'])}")
        if order.get("lat") is not None:
            dist = order.get("distance_km")
            parts.append("📍 " + map_links(order["lat"], order["lon"])
                         + (f"  ·  {dist:.1f} km" if dist is not None else ""))
        else:
            parts.append("⚠️ Lokatsiya yo'q — manzil hudud ichidaligini tekshiring")
    else:
        parts.append("🏃 <b>OLIB KETADI</b> (do'kondan)")
    parts.append(SEP)

    who = f'<a href="tg://user?id={order["user_id"]}">{escape(order["name"])}</a>'
    if username:
        who += f" · @{escape(username)}"
    parts.append(f"👤 {who}")
    parts.append(f"📞 {escape(order['phone'])}" + (
        "  ✅ tasdiqlangan" if order.get("phone_verified") else "  ⚠️ qo'lda yozilgan, tasdiqlanmagan"))
    if order.get("comment"):
        parts.append(f"💬 <i>{escape(order['comment'])}</i>")
    return "\n".join(parts)


def group_order_keyboard(order: dict[str, Any]) -> InlineKeyboardMarkup | None:
    """Guruhdagi buyurtma tagidagi tugmalar (holatga qarab)."""
    status = order.get("status") or "new"
    oid = order["id"]
    if status == "new":
        row = [InlineKeyboardButton(text="✅ Qabul qilish", callback_data=f"o:acc:{oid}"),
               InlineKeyboardButton(text="❌ Bekor qilish", callback_data=f"o:rej:{oid}")]
    elif status == "accepted":
        row = [InlineKeyboardButton(text="❌ Bekor qilish", callback_data=f"o:rej:{oid}")]
    else:
        return None
    return InlineKeyboardMarkup(inline_keyboard=[row])


def cancel_confirm_keyboard(order_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="❗ Ha, bekor qilinsin", callback_data=f"o:rejy:{order_id}"),
        InlineKeyboardButton(text="↩️ Yo'q", callback_data=f"o:back:{order_id}"),
    ]])


def user_order_text(order: dict[str, Any], lang: str, settings: dict[str, str]) -> str:
    lang = norm_lang(lang)
    if order["kind"] == "delivery":
        kind = t("kind_delivery", lang)
    else:
        kind = t("kind_pickup", lang, address=escape(settings.get(f"address_{lang}") or settings.get("address_uz", "")))
    if order["payment"] == "card":
        owner = settings.get("card_owner", "").strip()
        payment = t("pay_card", lang, card=escape(settings.get("card_number", "")),
                    owner=f" ({escape(owner)})" if owner else "")
    else:
        payment = t("pay_cash", lang)
    return t(
        "order_confirm", lang,
        id=order["id"], lines=order_lines_text(order, lang),
        total=format_sum(order["total"]), kind=kind, payment=payment,
    )


def history_text(orders: list[dict[str, Any]], lang: str) -> str:
    lang = norm_lang(lang)
    cur = t("currency", lang)
    blocks = [t("orders_title", lang)]
    for order in orders:
        created = datetime.fromisoformat(order["created_at"]).strftime("%d.%m.%Y %H:%M")
        items = ", ".join(f"{_line_name(line, lang)} ×{line['qty']}" for line in order["items"])
        mark = {"accepted": " ✅", "canceled": " ❌"}.get(order.get("status") or "", "")
        blocks.append(
            f"\n<b>№{order['id']}</b>{mark} · {created}\n{escape(items)}\n💰 {format_sum(order['total'])} {cur}"
        )
    return "\n".join(blocks)
