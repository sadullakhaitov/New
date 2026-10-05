from datetime import datetime

import pytest

from bot.config import TASHKENT_TZ
from bot.core import (
    CLOSED_FOREVER, OrderError, build_order_lines, localized, normalize_phone,
    parse_close_until, parse_price, shop_status,
)
from bot.translit import latin_to_cyrillic

NOW = datetime(2026, 10, 5, 22, 30, tzinfo=TASHKENT_TZ)


@pytest.mark.parametrize("text,expected", [
    ("35000", 35000), ("35 000", 35000), ("35", 35000), ("35.000", 35000), ("-", None), ("0", None),
])
def test_parse_price(text, expected):
    assert parse_price(text) == expected


@pytest.mark.parametrize("text", ["abc", "99999999"])
def test_parse_price_invalid(text):
    with pytest.raises(ValueError):
        parse_price(text)


@pytest.mark.parametrize("raw,expected", [
    ("+998 95 289 85 55", "+998952898555"), ("952898555", "+998952898555"), ("12", None), ("", None),
])
def test_normalize_phone(raw, expected):
    assert normalize_phone(raw) == expected


def test_shop_status():
    assert shop_status("", NOW).is_open
    assert not shop_status(CLOSED_FOREVER, NOW).is_open
    closed = shop_status("2026-10-06T10:00", NOW)
    assert not closed.is_open and closed.until_text() == "06.10.2026 10:00"
    assert shop_status("2026-10-05T10:00", NOW).is_open  # muddat o'tgan — avtomatik ochiladi


def test_parse_close_until():
    assert parse_close_until("10:00", NOW) == datetime(2026, 10, 6, 10, 0, tzinfo=TASHKENT_TZ)
    assert parse_close_until("23:00", NOW) == datetime(2026, 10, 5, 23, 0, tzinfo=TASHKENT_TZ)
    assert parse_close_until("07.10 09:30", NOW) == datetime(2026, 10, 7, 9, 30, tzinfo=TASHKENT_TZ)
    assert parse_close_until("07.10.2026 09:30", NOW) == datetime(2026, 10, 7, 9, 30, tzinfo=TASHKENT_TZ)
    assert parse_close_until("01.10.2026 09:30", NOW) is None  # o'tmish
    assert parse_close_until("ertaga", NOW) is None


PRODUCTS = {
    1: {"id": 1, "name_uz": "Qazi xot-dog", "name_cyr": "Қази хот-дог", "name_ru": "Хот-дог с казы",
        "price": 28000, "price_large": 38000, "is_active": 1},
    2: {"id": 2, "name_uz": "Fri", "name_cyr": "", "name_ru": "", "price": 15000, "price_large": None, "is_active": 1},
    3: {"id": 3, "name_uz": "Emir burger", "name_cyr": "", "name_ru": "", "price": None, "price_large": None, "is_active": 1},
    4: {"id": 4, "name_uz": "Lavash", "name_cyr": "", "name_ru": "", "price": 40000, "price_large": None, "is_active": 0},
}


def test_build_order_lines_recomputes_prices():
    lines, total = build_order_lines(
        [{"id": 1, "size": "large", "qty": 1, "price": 1}, {"id": 2, "qty": 2}, {"id": 2, "qty": 1}], PRODUCTS
    )
    assert total == 38000 + 15000 * 3
    assert lines[0]["size"] == "large" and lines[0]["names"]["ru"] == "Хот-дог с казы"
    assert lines[1]["qty"] == 3 and lines[1]["size"] == ""


@pytest.mark.parametrize("items,code", [
    ([], "empty_cart"),
    ([{"id": 3}], "unavailable"),          # narx yo'q
    ([{"id": 4}], "unavailable"),          # yashirilgan
    ([{"id": 2, "size": "large"}], "unavailable"),  # katta o'lcham yo'q
    ([{"id": 99}], "unavailable"),
    ([{"id": 2, "qty": 0}], "bad_request"),
    ([{"id": "x"}], "bad_request"),
])
def test_build_order_lines_errors(items, code):
    with pytest.raises(OrderError) as exc:
        build_order_lines(items, PRODUCTS)
    assert exc.value.code == code


def test_translit():
    assert latin_to_cyrillic("Go'shtli xot-dog") == "Гўштли хот-дог"
    assert latin_to_cyrillic("Choy va Shirinlik") == "Чой ва Ширинлик"
    assert latin_to_cyrillic("Emir yog'li") == "Эмир ёғли"
    assert latin_to_cyrillic("KFC tovuq") == "KFC товуқ"


def test_localized_fallback():
    row = {"name_uz": "Tovuq lavash", "name_cyr": "", "name_ru": ""}
    assert localized(row, "name", "cyr") == "Товуқ лаваш"
    assert localized(row, "name", "ru") == "Tovuq lavash"
