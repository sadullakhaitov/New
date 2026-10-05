"""Boshlang'ich menyu va sozlamalar (baza bo'sh bo'lganda bir marta yoziladi).

Narxlar so'mda. price — kichik (yoki yagona) o'lcham, price_large — katta o'lcham.
None — narx hali kiritilmagan: menyuda "Tez orada" bo'lib turadi.
"""
from __future__ import annotations

from .db import Database

DEFAULT_SETTINGS = {
    "min_order": "50000",
    "card_number": "1234 5678 8910 1112",
    "card_owner": "",
    "phone": "+998 95 289 85 55",
    "address_uz": "Peshku tumani, Vopkent yo'lida, elektr va moyka yonida",
    "address_cyr": "Пешку тумани, Вобкент йўлида, электр ва мойка ёнида",
    "address_ru": "Пешкунский район, по дороге на Вабкент, рядом с электро и автомойкой",
    "delivery_zone_uz": "Faqat Peshku tumani markazi ichida",
    "delivery_zone_cyr": "Фақат Пешку тумани маркази ичида",
    "delivery_zone_ru": "Только в пределах центра Пешкунского района",
    "closed_until": "",
    "group_chat_id": "",
    "upsell_product_id": "",
}

CATEGORIES = [
    # slug, uz, cyr, ru, img
    ("hotdog", "Xot-doglar", "Хот-доглар", "Хот-доги", "static/img/hotdog-classic.svg"),
    ("lavash", "Lavash va donerlar", "Лаваш ва донерлар", "Лаваш и донеры", "static/img/lavash.svg"),
    ("burger", "Burger va sendvichlar", "Бургер ва сендвичлар", "Бургеры и сэндвичи", "static/img/burger.svg"),
    ("kfc", "KFC va fri", "KFC ва фри", "KFC и фри", "static/img/kfc.svg"),
    ("drinks", "Ichimliklar", "Ичимликлар", "Напитки", "static/img/cola.svg"),
]

PRODUCTS = [
    # slug, uz, cyr, ru, img, price, price_large, hit
    ("hotdog", "Xot-dog Klassika", "Хот-дог Классика", "Хот-дог Классический", "hotdog-classic", 15000, 18000, False),
    ("hotdog", "Qazi xot-dog", "Қази хот-дог", "Хот-дог с казы", "hotdog-qazi", 28000, 38000, True),
    ("hotdog", "Go'shtli xot-dog", "Гўштли хот-дог", "Мясной хот-дог", "hotdog-meat", 25000, None, False),
    ("hotdog", "Kolbaski xot-dog", "Колбаски хот-дог", "Хот-дог с колбасками", "hotdog-kolbaski", None, None, False),
    ("hotdog", "Xagi", "Хаги", "Хаги", "xagi", 35000, 45000, False),
    ("hotdog", "Longer", "Лонгер", "Лонгер", "longer", 35000, None, False),
    ("lavash", "Lavash", "Лаваш", "Лаваш", "lavash", 40000, None, False),
    ("lavash", "Tandir lavash", "Тандир лаваш", "Тандыр лаваш", "lavash-tandir", 45000, None, False),
    ("lavash", "Emir lavash", "Эмир лаваш", "Эмир лаваш", "lavash-emir", 50000, None, True),
    ("lavash", "Doner", "Донер", "Донер", "doner", 35000, 45000, False),
    ("lavash", "Arab kabob", "Араб кабоб", "Арабский кебаб", "arab-kabob", 40000, 45000, False),
    ("burger", "Burger", "Бургер", "Бургер", "burger", 30000, 40000, False),
    ("burger", "Chizburger", "Чизбургер", "Чизбургер", "cheeseburger", 30000, 40000, False),
    ("burger", "Emir burger", "Эмир бургер", "Эмир бургер", "burger-emir", None, None, True),
    ("burger", "Klab sendvich", "Клаб сендвич", "Клаб-сэндвич", "club-sandwich", 40000, None, False),
    ("kfc", "KFC (qanotcha, fele)", "KFC (қанотча, филе)", "KFC (крылышки, филе)", "kfc", 80000, None, False),
    ("kfc", "Fri", "Фри", "Картофель фри", "fries", 15000, None, False),
    ("drinks", "Coca-Cola", "Coca-Cola", "Coca-Cola", "cola", None, None, False),
    ("drinks", "Fanta", "Fanta", "Fanta", "fanta", None, None, False),
    ("drinks", "Suv", "Сув", "Вода", "water", None, None, False),
]

UPSELL_NAME = "Fri"


async def seed(db: Database) -> None:
    for key, value in DEFAULT_SETTINGS.items():
        if await db.get_setting(key, default="\0") == "\0":
            await db.set_setting(key, value)

    if await db.categories():
        return

    cat_ids: dict[str, int] = {}
    for sort, (slug, uz, cyr, ru, img) in enumerate(CATEGORIES):
        cat_ids[slug] = await db.add_category(
            slug=slug, name_uz=uz, name_cyr=cyr, name_ru=ru, img=img, sort=sort * 10
        )

    for sort, (slug, uz, cyr, ru, img, price, large, hit) in enumerate(PRODUCTS):
        pid = await db.add_product(
            category_id=cat_ids[slug],
            name_uz=uz, name_cyr=cyr, name_ru=ru,
            img=f"static/img/{img}.svg",
            price=price, price_large=large,
            is_hit=int(hit), sort=sort * 10,
        )
        if uz == UPSELL_NAME:
            await db.set_setting("upsell_product_id", str(pid))
