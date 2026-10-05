"""Buyurtma xabarlarini tayyorlash (xodimlar guruhi va mijoz uchun)."""
from __future__ import annotations

from datetime import datetime
from html import escape
from typing import Any

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
        f"• {escape(_line_name(line, lang))} × {line['qty']} = {format_sum(line['sum'])} {cur}"
        for line in order["items"]
    )


def group_order_text(order: dict[str, Any], username: str = "") -> str:
    """Xodimlar guruhiga boradigan xabar (doim o'zbek lotin)."""
    created = datetime.fromisoformat(order["created_at"]).strftime("%d.%m %H:%M")
    who = f'<a href="tg://user?id={order["user_id"]}">{escape(order["name"])}</a>'
    if username:
        who += f" (@{escape(username)})"
    parts = [
        f"🆕 <b>Yangi buyurtma №{order['id']}</b>  ·  {created}",
        "",
        f"👤 {who}",
        f"📞 {escape(order['phone'])}",
    ]
    if order["kind"] == "delivery":
        parts.append("🚚 <b>Yetkazib berish</b>")
        if order.get("address"):
            parts.append(f"📍 {escape(order['address'])}")
        if order.get("lat") is not None:
            parts.append("🗺 Lokatsiya pastda 👇")
    else:
        parts.append("🏃 <b>Olib ketadi</b>")
    parts.append("💵 Naqd" if order["payment"] == "cash" else "💳 Kartaga o'tkazma (chekni kuting)")
    parts += ["", order_lines_text(order, "uz"), "", f"💰 <b>Jami: {format_sum(order['total'])} so'm</b>"]
    if order.get("comment"):
        parts.append(f"💬 {escape(order['comment'])}")
    return "\n".join(parts)


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
        blocks.append(
            f"\n<b>№{order['id']}</b> · {created}\n{escape(items)}\n💰 {format_sum(order['total'])} {cur}"
        )
    return "\n".join(blocks)
