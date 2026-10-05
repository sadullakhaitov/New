"""Boshlang'ich menyu va sozlamalar (baza bo'sh bo'lganda bir marta yoziladi).

Narxlar so'mda. price — kichik (yoki yagona) o'lcham, price_large — katta o'lcham.
None — narx hali kiritilmagan: menyuda "Tez orada" bo'lib turadi.
"""
from __future__ import annotations

from .core import localized
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


SIZE_SUFFIX = {
    "small": {"uz": " (kichik)", "cyr": " (кичик)", "ru": " (маленький)"},
    "large": {"uz": " (katta)", "cyr": " (катта)", "ru": " (большой)"},
}


async def split_sizes(db: Database) -> int:
    """Kichik/katta o'lchamli taomlarni ikkita alohida taomga ajratadi (bir marta ishlaydi).

    "Qazi xot-dog" (28 000 / 38 000) -> "Qazi xot-dog (kichik)" 28 000 va "Qazi xot-dog (katta)" 38 000.
    """
    if await db.get_setting("migr_split_sizes") == "1":
        return 0
    count = 0
    for p in await db.products():
        if p["price_large"] is None:
            continue
        names = {lang: localized(p, "name", lang) for lang in ("uz", "cyr", "ru")}
        await db.add_product(
            category_id=p["category_id"],
            name_uz=names["uz"] + SIZE_SUFFIX["large"]["uz"],
            name_cyr=names["cyr"] + SIZE_SUFFIX["large"]["cyr"],
            name_ru=names["ru"] + SIZE_SUFFIX["large"]["ru"],
            desc_uz=p["desc_uz"], desc_cyr=p["desc_cyr"], desc_ru=p["desc_ru"],
            img=p["img"], price=p["price_large"], is_active=p["is_active"], is_hit=p["is_hit"],
            sort=p["sort"] + 5,
        )
        await db.update_product(
            p["id"], price_large=None,
            name_uz=names["uz"] + SIZE_SUFFIX["small"]["uz"],
            name_cyr=names["cyr"] + SIZE_SUFFIX["small"]["cyr"],
            name_ru=names["ru"] + SIZE_SUFFIX["small"]["ru"],
        )
        count += 1
    await db.set_setting("migr_split_sizes", "1")
    return count


# Bosh sahifadagi aylanib turadigan bannerlar. {min} — minimal summa, {price} — ulangan taom narxi.
BANNERS = [
    {
        "tag": ("DOIMIY TAKLIF", "ДОИМИЙ ТАКЛИФ", "ВСЕГДА"),
        "title": ("Bepul yetkazib berish", "Бепул етказиб бериш", "Бесплатная доставка"),
        "text": ("{min} so'mdan · Peshku markazi bo'ylab", "{min} сўмдан · Пешку маркази бўйлаб", "От {min} сум · по центру Пешку"),
        "img": "static/img/photos/burger.webp", "theme": "yellow", "product": None,
    },
    {
        "tag": ("HIT", "HIT", "ХИТ"),
        "title": ("Emir lavash", "Эмир лаваш", "Эмир лаваш"),
        "text": ("{price} · bir bosishda savatga", "{price} · бир босишда саватга", "{price} · в корзину в одно касание"),
        "img": "static/img/photos/lavash.webp", "theme": "red", "product": "Emir lavash",
    },
    {
        "tag": ("KATTA PORSIYA", "КАТТА ПОРЦИЯ", "БОЛЬШАЯ ПОРЦИЯ"),
        "title": ("Qazi xot-dog", "Қази хот-дог", "Хот-дог с казы"),
        "text": ("Katta o'lchami — {price}", "Катта ўлчами — {price}", "Большой размер — {price}"),
        "img": "", "theme": "dark", "product": "Qazi xot-dog (katta)",
    },
]


async def seed_banners(db: Database) -> None:
    """Boshlang'ich bannerlar faqat bir marta yoziladi (admin o'chirsa, qaytib kelmaydi)."""
    if await db.get_setting("banners_seeded") == "1":
        return
    by_name = {p["name_uz"]: p["id"] for p in await db.products()}
    for b in BANNERS:
        fields = {}
        for key in ("tag", "title", "text"):
            fields[f"{key}_uz"], fields[f"{key}_cyr"], fields[f"{key}_ru"] = b[key]
        await db.add_banner(**fields, img=b["img"], theme=b["theme"], product_id=by_name.get(b["product"]))
    await db.set_setting("banners_seeded", "1")


# Haqiqiy taom suratlari (fon shaffof). Kichik va katta o'lchamga bir xil surat qo'yiladi.
PHOTOS = {
    "Lavash": "lavash",
    "Tandir lavash": "lavash-tandir",
    "Xagi (kichik)": "xagi", "Xagi (katta)": "xagi",
    "Doner (kichik)": "doner", "Doner (katta)": "doner",
    "Burger (kichik)": "burger", "Burger (katta)": "burger",
    "Arab kabob (kichik)": "arab-kabob2", "Arab kabob (katta)": "arab-kabob2",
    "Chizburger (kichik)": "cheeseburger", "Chizburger (katta)": "cheeseburger",
    "Longer": "longer", "Klab sendvich": "club-sandwich",
    "KFC (qanotcha, fele)": "kfc",
    "Fri": "fries",
    "Xot-dog Klassika (kichik)": "hotdog-classic", "Xot-dog Klassika (katta)": "hotdog-classic",
    "Qazi xot-dog (kichik)": "hotdog-qazi", "Qazi xot-dog (katta)": "hotdog-qazi",
    "Go'shtli xot-dog": "hotdog-meat",
    "Kolbaski xot-dog": "hotdog-kolbaski",
    "Coca-Cola": "cola", "Fanta": "fanta", "Suv": "water",
}


async def apply_photos(db: Database) -> int:
    """Chizma rasmlarni suratlarga almashtiradi — har bir surat bir marta qo'yiladi.

    Keyin ro'yxatga yangi surat qo'shilsa, faqat o'sha yangisi qo'yiladi. Admin yuklagan rasmlarga tegilmaydi.
    """
    done = set(filter(None, (await db.get_setting("photos_applied")).split(",")))
    if await db.get_setting("migr_photos_v1") == "1":
        done |= {"lavash", "lavash-tandir", "xagi", "doner", "burger"}  # avvalgi versiyada qo'yilganlar
    todo = {name: photo for name, photo in PHOTOS.items() if photo not in done}
    if not todo:
        return 0
    count = 0
    for p in await db.products():
        photo = todo.get(p["name_uz"])
        if photo and (not p["img"] or p["img"].startswith("static/img/")):
            await db.update_product(p["id"], img=f"static/img/photos/{photo}.webp")
            count += 1
    await db.set_setting("photos_applied", ",".join(sorted(done | set(todo.values()))))
    return count


async def apply_banner_photos(db: Database) -> int:
    """Bannerlardagi chizma burger va lavashni haqiqiy suratlarga almashtiradi (bir marta).

    Admin yuklagan rasmlarga tegilmaydi.
    """
    if await db.get_setting("migr_banner_photos") == "1":
        return 0
    count = 0
    for b in await db.banners():
        img = b["img"] or ""
        photo = None
        if img == "static/img/burger.svg":
            photo = "burger"
        elif not img and b["product_id"]:
            p = await db.product(b["product_id"])
            name = (p["name_uz"] if p else "").lower()
            if p and (not p["img"] or not p["img"].startswith(("tg:", "static/img/photos/"))):
                photo = "lavash" if "lavash" in name else "burger" if "burger" in name else None
        if photo:
            await db.update_banner(b["id"], img=f"static/img/photos/{photo}.webp")
            count += 1
    await db.set_setting("migr_banner_photos", "1")
    return count


# Souslar — alohida bo'lim (KFC va fri bilan ichimliklar orasida). Bir marta qo'shiladi.
SAUCE_CATEGORY = ("sauces", "Souslar", "Соуслар", "Соусы", "static/img/sauce-tomato.svg")
SAUCES = [
    # uz, cyr, ru, rasm, narx
    ("Sarimsoqli sous", "Саримсоқли соус", "Чесночный соус", "sauce-garlic", 6000),
    ("Tomatli sous", "Томатли соус", "Томатный соус", "sauce-tomato", 6000),
    ("Pishloqli sous", "Пишлоқли соус", "Сырный соус", "sauce-cheese", 6000),
]


async def add_sauces(db: Database) -> int:
    """Souslar bo'limini va 3 ta sousni qo'shadi (admin keyin o'chirsa — qaytib qo'shilmaydi)."""
    if await db.get_setting("migr_sauces") == "1":
        return 0
    slug, uz, cyr, ru, img = SAUCE_CATEGORY
    cat = next((c for c in await db.categories() if c["slug"] == slug), None)
    cid = cat["id"] if cat else await db.add_category(slug=slug, name_uz=uz, name_cyr=cyr, name_ru=ru, img=img, sort=35)
    have = {p["name_uz"] for p in await db.products()}
    count = 0
    for sort, (name_uz, name_cyr, name_ru, pic, price) in enumerate(SAUCES):
        if name_uz in have:
            continue
        await db.add_product(category_id=cid, name_uz=name_uz, name_cyr=name_cyr, name_ru=name_ru,
                             img=f"static/img/{pic}.svg", price=price, sort=sort * 10)
        count += 1
    await db.set_setting("migr_sauces", "1")
    return count
