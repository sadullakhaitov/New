"""Bot va veb-server uchun umumiy, Telegramdan mustaqil mantiq."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from .config import TASHKENT_TZ
from .translit import latin_to_cyrillic

LANGS = ("uz", "cyr", "ru")
DEFAULT_LANG = "uz"
CLOSED_FOREVER = "forever"
MAX_QTY = 50
MAX_LINES = 30


def norm_lang(lang: str | None) -> str:
    return lang if lang in LANGS else DEFAULT_LANG


def guess_lang(language_code: str | None) -> str:
    code = (language_code or "").lower()
    if code.startswith("ru"):
        return "ru"
    return DEFAULT_LANG


def localized(row: dict[str, Any], field: str, lang: str) -> str:
    """name/desc ni kerakli tilda qaytaradi; bo'sh bo'lsa lotin yoki transliteratsiya ishlatiladi."""
    lang = norm_lang(lang)
    value = (row.get(f"{field}_{lang}") or "").strip()
    if value:
        return value
    base = (row.get(f"{field}_uz") or "").strip()
    if lang == "cyr":
        return latin_to_cyrillic(base)
    return base


def format_sum(amount: int) -> str:
    return f"{amount:,}".replace(",", " ")


def is_available(product: dict[str, Any]) -> bool:
    return bool(product.get("is_active")) and product.get("price") is not None


# ---------- do'kon holati ----------
@dataclass(frozen=True)
class ShopStatus:
    is_open: bool
    until: datetime | None = None  # None + yopiq = noma'lum muddatga

    def until_text(self) -> str:
        return self.until.strftime("%d.%m.%Y %H:%M") if self.until else ""


def shop_status(closed_until: str, now: datetime | None = None) -> ShopStatus:
    now = now or datetime.now(TASHKENT_TZ)
    value = (closed_until or "").strip()
    if not value:
        return ShopStatus(True)
    if value == CLOSED_FOREVER:
        return ShopStatus(False)
    try:
        until = datetime.fromisoformat(value)
    except ValueError:
        return ShopStatus(True)
    if until.tzinfo is None:
        until = until.replace(tzinfo=TASHKENT_TZ)
    if now >= until:
        return ShopStatus(True)
    return ShopStatus(False, until)


def parse_close_until(text: str, now: datetime | None = None) -> datetime | None:
    """Admin yozgan vaqtni o'qiydi: "10:00", "06.10 10:00", "06.10.2026 10:00".

    Faqat soat yozilsa va u o'tib ketgan bo'lsa — ertangi kun olinadi.
    """
    now = now or datetime.now(TASHKENT_TZ)
    text = re.sub(r"\s+", " ", (text or "").strip())
    m = re.fullmatch(r"(?:(\d{1,2})[./-](\d{1,2})(?:[./-](\d{2,4}))? )?(\d{1,2})[:.](\d{2})", text)
    if not m:
        return None
    day, month, year, hour, minute = m.groups()
    try:
        if day is None:
            result = now.replace(hour=int(hour), minute=int(minute), second=0, microsecond=0)
            if result <= now:
                result += timedelta(days=1)
            return result
        y = int(year) if year else now.year
        if y < 100:
            y += 2000
        result = datetime(y, int(month), int(day), int(hour), int(minute), tzinfo=TASHKENT_TZ)
        if not year and result <= now:
            result = result.replace(year=y + 1)
    except ValueError:
        return None
    return result if result > now else None


# ---------- narx va telefon ----------
def parse_price(text: str) -> int | None:
    """"35000", "35 000", "35" (ming) -> so'm. "-" yoki "0" -> None (narx yo'q)."""
    raw = (text or "").strip().lower().replace("so'm", "").replace("сум", "").replace("сўм", "")
    if raw in {"-", "0", "yo'q", "yoq", "нет"}:
        return None
    digits = re.sub(r"[\s.,_']", "", raw)
    if not digits.isdigit():
        raise ValueError("raqam emas")
    value = int(digits)
    if value < 1000:
        value *= 1000
    if value > 10_000_000:
        raise ValueError("juda katta")
    return value


def normalize_phone(phone: str) -> str | None:
    digits = re.sub(r"\D", "", phone or "")
    if len(digits) == 9:
        digits = "998" + digits
    if not 9 <= len(digits) <= 15:
        return None
    return "+" + digits


# ---------- buyurtma ----------
class OrderError(Exception):
    def __init__(self, code: str, **extra: Any):
        super().__init__(code)
        self.code = code
        self.extra = extra


def build_order_lines(
    requested: list[dict[str, Any]], products: dict[int, dict[str, Any]]
) -> tuple[list[dict[str, Any]], int]:
    """Mijoz yuborgan savatni bazadagi narxlar bilan qayta hisoblaydi."""
    if not isinstance(requested, list) or not requested:
        raise OrderError("empty_cart")
    if len(requested) > MAX_LINES:
        raise OrderError("bad_request")
    merged: dict[tuple[int, str], int] = {}
    for item in requested:
        try:
            pid = int(item["id"])
            qty = int(item.get("qty", 1))
        except (KeyError, TypeError, ValueError):
            raise OrderError("bad_request") from None
        size = item.get("size") or "small"
        if size not in {"small", "large"} or not 1 <= qty <= MAX_QTY:
            raise OrderError("bad_request")
        merged[(pid, size)] = merged.get((pid, size), 0) + qty

    lines = []
    total = 0
    for (pid, size), qty in merged.items():
        product = products.get(pid)
        if product is None or not is_available(product):
            raise OrderError("unavailable", product_id=pid)
        if size == "large":
            if product.get("price_large") is None:
                raise OrderError("unavailable", product_id=pid)
            price = product["price_large"]
        else:
            price = product["price"]
        if qty > MAX_QTY:
            raise OrderError("bad_request")
        lines.append({
            "id": pid,
            "name": product["name_uz"],
            "names": {lang: localized(product, "name", lang) for lang in LANGS},
            "size": size if product.get("price_large") is not None else "",
            "qty": qty,
            "price": price,
            "sum": price * qty,
        })
        total += price * qty
    return lines, total
