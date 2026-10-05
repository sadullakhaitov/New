import hashlib
import hmac
import json
import time
from types import SimpleNamespace
from urllib.parse import urlencode

import pytest
from aiohttp.test_utils import TestClient, TestServer

from bot.config import Config
from bot.web import create_app

TOKEN = "123456:TEST-token"


def sign(user: dict, token: str = TOKEN, auth_date: int | None = None) -> str:
    fields = {"auth_date": str(auth_date or int(time.time())), "query_id": "AAE",
              "user": json.dumps(user, separators=(",", ":"))}
    dcs = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    fields["hash"] = hmac.new(secret, dcs.encode(), hashlib.sha256).hexdigest()
    return urlencode(fields)


class FakeBot:
    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text, **kw):
        self.sent.append(("message", chat_id, text))
        return SimpleNamespace(message_id=len(self.sent))

    async def send_location(self, chat_id, lat, lon, **kw):
        self.sent.append(("location", chat_id, (lat, lon)))

    async def edit_message_text(self, text, chat_id=None, message_id=None, **kw):
        self.sent.append(("edit", chat_id, text))

    async def edit_message_caption(self, chat_id=None, message_id=None, caption=None, **kw):
        self.sent.append(("edit_caption", chat_id, caption))

    async def send_photo(self, chat_id, photo, caption=None, **kw):
        self.sent.append(("photo", chat_id, caption))
        return SimpleNamespace(message_id=len(self.sent))

    async def delete_message(self, chat_id, message_id):
        self.sent.append(("delete", chat_id, message_id))

    async def get_file(self, file_id):
        return SimpleNamespace(file_path=f"photos/{file_id}.jpg")

    async def download_file(self, path, destination):
        self.sent.append(("download", path, None))
        destination.write(b"\xff\xd8JPEG")


USER = {"id": 777, "first_name": "Sardor", "language_code": "uz"}


@pytest.fixture
async def ctx(tmp_path, fresh_db):
    cfg = Config(bot_token=TOKEN, base_url="https://example.com", mode="polling", host="127.0.0.1",
                 port=0, data_dir=tmp_path, superadmins=frozenset())
    db = fresh_db
    await db.set_setting("group_chat_id", "-100500")
    bot = FakeBot()
    client = TestClient(TestServer(create_app(cfg, db, bot)))
    await client.start_server()
    yield SimpleNamespace(client=client, db=db, bot=bot)
    await client.close()


def auth(user=USER, **kw):
    return {"Authorization": "tma " + sign(user, **kw)}


async def product_id(db, name):
    return next(p["id"] for p in await db.products() if p["name_uz"] == name)


async def test_menu(ctx):
    resp = await ctx.client.get("/api/menu?lang=ru")
    data = await resp.json()
    assert data["ok"] and data["shop"]["open"] and data["shop"]["min_order"] == 50000
    names = [p["name"] for c in data["categories"] for p in c["products"]]
    assert "Хот-дог с казы (маленький)" in names and "Хот-дог с казы (большой)" in names
    soon = [p for c in data["categories"] for p in c["products"] if p["name"] == "Эмир бургер"][0]
    assert soon["available"] is False


async def test_index_and_static(ctx):
    assert (await ctx.client.get("/")).status == 200
    assert (await ctx.client.get("/static/app.js")).status == 200
    assert (await ctx.client.get("/static/img/burger.svg")).status == 200


async def test_auth_required(ctx):
    resp = await ctx.client.post("/api/order", json={})
    assert resp.status == 401
    bad = {"Authorization": "tma " + sign(USER, token="999:other")}
    assert (await ctx.client.post("/api/me", headers=bad)).status == 401
    old = auth(auth_date=int(time.time()) - 3 * 86400)
    assert (await ctx.client.post("/api/me", headers=old)).status == 401


async def verify(db, phone="+998952898555", user_id=777):
    await db.upsert_user(user_id, "Sardor")
    await db.set_verified_phone(user_id, phone)


async def test_order_flow(ctx):
    await verify(ctx.db)
    qazi = await product_id(ctx.db, "Qazi xot-dog (katta)")
    lavash = await product_id(ctx.db, "Emir lavash")
    body = {
        "lang": "uz", "kind": "delivery", "payment": "card", "name": "Sardor", "phone": "95 289 85 55",
        "address": "Maktab yonida", "lat": 39.98, "lon": 64.5, "comment": "achchiq bo'lmasin",
        "items": [{"id": qazi, "qty": 1}, {"id": lavash, "size": "small", "qty": 1}],
    }
    resp = await ctx.client.post("/api/order", json=body, headers=auth())
    data = await resp.json()
    assert resp.status == 200, data
    order = data["order"]
    assert order["id"] == 1001 and order["total"] == 88000

    kinds = [(k, chat) for k, chat, _ in ctx.bot.sent]
    # Lokatsiya alohida xabar emas — xarita havolasi buyurtma ichida
    assert kinds.count(("message", -100500)) == 1 and ("message", 777) in kinds
    assert all(k != "location" for k, _ in kinds)
    group_text = next(t for k, c, t in ctx.bot.sent if k == "message" and c == -100500)
    assert "№1001" in group_text and "88 000" in group_text and "kartaga" in group_text
    assert "chek hali yuborilmagan" in group_text and "maps.google.com/?q=39.98,64.5" in group_text
    user_text = next(t for k, c, t in ctx.bot.sent if k == "message" and c == 777)
    assert "1234 5678 8910 1112" in user_text

    me = await (await ctx.client.post("/api/me", headers=auth())).json()
    assert me["user"]["phone"] == "+998952898555"
    orders = await (await ctx.client.get("/api/orders?lang=ru", headers=auth())).json()
    assert orders["orders"][0]["items"][0]["name"] == "Хот-дог с казы (большой)"

    again = await ctx.client.post("/api/order", json=body, headers=auth())
    assert (await again.json())["error"] == "too_fast"


async def test_min_order_and_pickup(ctx):
    await verify(ctx.db, "+998901234567")
    fri = await product_id(ctx.db, "Fri")
    base = {"lang": "uz", "payment": "cash", "name": "Ali", "phone": "+998901234567",
            "items": [{"id": fri, "qty": 1}]}
    resp = await ctx.client.post("/api/order", json={**base, "kind": "delivery", "address": "x"}, headers=auth())
    assert (await resp.json())["error"] == "min_order"
    resp = await ctx.client.post("/api/order", json={**base, "kind": "pickup"}, headers=auth())
    assert (await resp.json())["ok"]


async def test_closed_shop(ctx):
    await ctx.db.set_setting("closed_until", "forever")
    fri = await product_id(ctx.db, "Fri")
    body = {"lang": "uz", "kind": "pickup", "payment": "cash", "name": "Ali", "phone": "+998901234567",
            "items": [{"id": fri, "qty": 1}]}
    resp = await ctx.client.post("/api/order", json=body, headers=auth())
    assert resp.status == 409 and (await resp.json())["error"] == "closed"


async def test_uploaded_photo_served_from_telegram(ctx):
    pid = await product_id(ctx.db, "Burger (katta)")
    await ctx.db.update_product(pid, img="tg:AgACAgIAAx")
    data = await (await ctx.client.get("/api/menu")).json()
    img = next(p["img"] for c in data["categories"] for p in c["products"] if p["id"] == pid)
    assert img.startswith(f"img/p/{pid}?v=")
    for _ in range(2):
        resp = await ctx.client.get("/" + img)
        assert resp.status == 200 and await resp.read() == b"\xff\xd8JPEG"
    assert [k for k, *_ in ctx.bot.sent].count("download") == 1  # ikkinchi marta keshdan
    assert (await ctx.client.get("/img/p/1")).status == 404


async def test_sizes_split_into_separate_items(ctx):
    from bot.seed import split_sizes

    products = {p["name_uz"]: p for p in await ctx.db.products()}
    assert all(p["price_large"] is None for p in products.values())
    assert products["Xot-dog Klassika (kichik)"]["price"] == 15000
    assert products["Xot-dog Klassika (katta)"]["price"] == 18000
    assert products["Burger (katta)"]["name_cyr"] == "Бургер (катта)"
    assert products["Go'shtli xot-dog"]["price"] == 25000  # bitta o'lchamli taom o'zgarmaydi
    assert len(products) == 20 + 7
    assert await split_sizes(ctx.db) == 0  # qayta ishga tushganda hech narsa qilmaydi


async def test_menu_banners(ctx):
    data = await (await ctx.client.get("/api/menu?lang=uz")).json()
    banners = data["banners"]
    assert [b["theme"] for b in banners] == ["yellow", "red", "dark"]
    assert banners[0]["text"].startswith("50 000 so'm")
    assert banners[1]["text"].startswith("50 000 so'm") and banners[1]["product_id"]
    assert banners[0]["img"] == "static/img/photos/burger.webp"
    assert banners[1]["img"] == "static/img/photos/lavash.webp"
    assert banners[2]["img"] == "static/img/photos/hotdog-qazi.webp"
    # Ulangan taom yashirilsa — banner ham chiqmaydi
    await ctx.db.update_product(banners[1]["product_id"], is_active=0)
    data = await (await ctx.client.get("/api/menu?lang=ru")).json()
    assert len(data["banners"]) == 2 and data["banners"][1]["text"] == "Большой размер — 38 000 сум"


async def test_photos_applied_to_both_sizes(ctx):
    from bot.seed import apply_photos

    products = {p["name_uz"]: p for p in await ctx.db.products()}
    assert products["Burger (kichik)"]["img"] == products["Burger (katta)"]["img"] == "static/img/photos/burger.webp"
    assert products["Doner (katta)"]["img"].endswith("doner.webp")
    assert products["Chizburger (kichik)"]["img"] == "static/img/photos/cheeseburger.webp"
    assert products["Arab kabob (katta)"]["img"] == "static/img/photos/arab-kabob2.webp"
    assert products["Qazi xot-dog (kichik)"]["img"] == "static/img/photos/hotdog-qazi.webp"
    assert products["Kolbaski xot-dog"]["img"] == "static/img/photos/hotdog-kolbaski.webp"
    assert products["Suv"]["img"] == "static/img/photos/water.webp"
    assert products["Klab sendvich"]["img"] == "static/img/photos/club-sandwich.webp"
    for name in ("burger", "doner", "xagi", "lavash", "lavash-tandir", "arab-kabob2", "cheeseburger", "longer", "club-sandwich", "kfc", "fries",
                 "hotdog-classic", "hotdog-qazi", "hotdog-meat", "hotdog-kolbaski", "cola", "fanta", "water"):
        assert (await ctx.client.get(f"/static/img/photos/{name}.webp")).status == 200
    assert await apply_photos(ctx.db) == 0  # qayta ishga tushganda tegmaydi


async def test_new_photo_applied_after_old_migration(fresh_db):
    from bot.seed import apply_photos

    db = fresh_db
    pid = next(p["id"] for p in await db.products() if p["name_uz"] == "Arab kabob (kichik)")
    # Eski holat: v1 bayrog'i qo'yilgan, arab kabob hali chizma
    await db.update_product(pid, img="static/img/arab-kabob.svg")
    await db.set_setting("photos_applied", "")
    await db.set_setting("migr_photos_v1", "1")
    assert await apply_photos(db) == 17  # arab kabob, chizburger, xot-doglar, ichimliklar, longer, klab sendvich, kfc, fri
    assert (await db.product(pid))["img"] == "static/img/photos/arab-kabob2.webp"
    assert await apply_photos(db) == 0


async def test_banner_photos_migration(fresh_db):
    from bot.seed import apply_banner_photos

    db = fresh_db
    yellow, red, dark = await db.banners()
    # Eski holat: chizma burger va bo'sh (taom chizmasiga qaytadigan) lavash
    await db.update_banner(yellow["id"], img="static/img/burger.svg")
    await db.update_banner(red["id"], img="")
    await db.update_banner(dark["id"], img="tg:admin-file")
    await db.set_setting("migr_banner_photos", "")
    assert await apply_banner_photos(db) == 2
    assert (await db.banner(yellow["id"]))["img"] == "static/img/photos/burger.webp"
    assert (await db.banner(red["id"]))["img"] == "static/img/photos/lavash.webp"
    assert (await db.banner(dark["id"]))["img"] == "tg:admin-file"
    assert await apply_banner_photos(db) == 0


def _fri_body(db_fri, **extra):
    return {"lang": "uz", "kind": "pickup", "payment": "cash", "name": "Ali", "phone": "+998901234567",
            "items": [{"id": db_fri, "qty": 4}], **extra}


async def test_phone_must_be_shared_via_telegram(ctx):
    fri = await product_id(ctx.db, "Fri")
    resp = await ctx.client.post("/api/order", json=_fri_body(fri), headers=auth())
    assert (await resp.json())["error"] == "phone_unverified"
    # Eski Telegram ilovasi (kontakt ulasha olmaydi) — qabul qilinadi, lekin guruhda belgilanadi
    resp = await ctx.client.post("/api/order", json=_fri_body(fri, contact_supported=False), headers=auth())
    assert (await resp.json())["ok"]
    group_text = next(t for k, c, t in ctx.bot.sent if k == "message" and c == -100500)
    assert "tasdiqlanmagan" in group_text


async def test_delivery_zone(ctx):
    await verify(ctx.db, "+998901234567")
    await ctx.db.set_setting("shop_lat", "40.0")
    await ctx.db.set_setting("shop_lon", "64.4")
    await ctx.db.set_setting("delivery_radius_km", "3")
    menu = await (await ctx.client.get("/api/menu")).json()
    assert menu["shop"]["zone_area"] == {"lat": 40.0, "lon": 64.4, "radius_km": 3.0}
    fri = await product_id(ctx.db, "Fri")
    far = _fri_body(fri, kind="delivery", lat=40.1, lon=64.4)  # ~11 km
    data = await (await ctx.client.post("/api/order", json=far, headers=auth())).json()
    assert data["error"] == "out_of_zone" and data["distance_km"] > 10
    near = _fri_body(fri, kind="delivery", lat=40.01, lon=64.4)  # ~1.1 km
    data = await (await ctx.client.post("/api/order", json=near, headers=auth())).json()
    assert data["ok"], data
    group_text = next(t for k, c, t in ctx.bot.sent if k == "message" and c == -100500)
    assert "1.1 km" in group_text and "✅ tasdiqlangan" in group_text


async def test_customer_cancel(ctx):
    await verify(ctx.db, "+998901234567")
    fri = await product_id(ctx.db, "Fri")
    oid = (await (await ctx.client.post("/api/order", json=_fri_body(fri), headers=auth())).json())["order"]["id"]
    # Begona foydalanuvchi bekor qila olmaydi
    other = auth({"id": 888, "first_name": "X"})
    assert (await ctx.client.post(f"/api/orders/{oid}/cancel", headers=other)).status == 404
    data = await (await ctx.client.post(f"/api/orders/{oid}/cancel", headers=auth())).json()
    assert data["ok"] and data["order"]["status"] == "canceled"
    edits = [t for k, c, t in ctx.bot.sent if k == "edit" and c == -100500]
    assert edits and "BEKOR QILINDI</b> — Mijoz" in edits[-1]
    assert any("Mijoz" in t and "bekor qildi" in t for k, c, t in ctx.bot.sent if k == "message" and c == -100500)


async def test_customer_cannot_cancel_after_accept(ctx):
    await verify(ctx.db, "+998901234567")
    fri = await product_id(ctx.db, "Fri")
    oid = (await (await ctx.client.post("/api/order", json=_fri_body(fri), headers=auth())).json())["order"]["id"]
    await ctx.db.set_order_status(oid, "accepted", "Oshpaz")
    resp = await ctx.client.post(f"/api/orders/{oid}/cancel", headers=auth())
    data = await resp.json()
    assert resp.status == 409 and data["error"] == "cannot_cancel" and data["order"]["status"] == "accepted"
    assert (await ctx.db.order(oid))["status"] == "accepted"


async def test_receipt_joins_order_message(ctx):
    from bot.staff import attach_receipt, refresh_group_message

    await verify(ctx.db, "+998901234567")
    fri = await product_id(ctx.db, "Fri")
    body = _fri_body(fri, payment="card")
    oid = (await (await ctx.client.post("/api/order", json=body, headers=auth())).json())["order"]["id"]
    old_mid = (await ctx.db.order(oid))["group_message_id"]

    assert await attach_receipt(ctx.bot, ctx.db, oid, "PHOTO_ID", "photo")
    photo = next(e for e in ctx.bot.sent if e[0] == "photo")
    # Chek rasmi + buyurtmaning to'liq matni bitta xabarda, eski matnli xabar o'chiriladi
    assert photo[1] == -100500 and f"№{oid}" in photo[2] and "chek ilova qilingan" in photo[2]
    assert ("delete", -100500, old_mid) in ctx.bot.sent
    order = await ctx.db.order(oid)
    assert order["group_is_media"] == 1 and order["receipt_file_id"] == "PHOTO_ID"

    # Keyingi yangilanishlar (qabul/bekor) rasm izohini o'zgartiradi
    await ctx.db.set_order_status(oid, "accepted", "Xodim")
    await refresh_group_message(ctx.bot, ctx.db, await ctx.db.order(oid))
    assert ctx.bot.sent[-1][0] == "edit_caption" and "QABUL QILINDI" in ctx.bot.sent[-1][2]


async def test_pay_after_receiving(ctx):
    await verify(ctx.db, "+998901234567")
    fri = await product_id(ctx.db, "Fri")
    data = await (await ctx.client.post("/api/order", json=_fri_body(fri, payment="later"), headers=auth())).json()
    assert data["ok"] and data["order"]["payment"] == "later"
    group_text = next(t for k, c, t in ctx.bot.sent if k == "message" and c == -100500)
    assert "buyurtmani olgandan keyin" in group_text
    user_text = next(t for k, c, t in ctx.bot.sent if k == "message" and c == 777)
    assert "olgandan keyin" in user_text and "1234 5678 8910 1112" in user_text
    bad = await (await ctx.client.post("/api/order", json=_fri_body(fri, payment="bitcoin"), headers=auth())).json()
    assert not bad.get("ok")
