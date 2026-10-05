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


async def test_order_flow(ctx):
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
    assert ("message", -100500) in kinds and ("location", -100500) in kinds and ("message", 777) in kinds
    group_text = next(t for k, c, t in ctx.bot.sent if k == "message" and c == -100500)
    assert "№1001" in group_text and "88 000" in group_text and "Kartaga" in group_text
    user_text = next(t for k, c, t in ctx.bot.sent if k == "message" and c == 777)
    assert "1234 5678 8910 1112" in user_text

    me = await (await ctx.client.post("/api/me", headers=auth())).json()
    assert me["user"]["phone"] == "+998952898555"
    orders = await (await ctx.client.get("/api/orders?lang=ru", headers=auth())).json()
    assert orders["orders"][0]["items"][0]["name"] == "Хот-дог с казы (большой)"

    again = await ctx.client.post("/api/order", json=body, headers=auth())
    assert (await again.json())["error"] == "too_fast"


async def test_min_order_and_pickup(ctx):
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
    assert banners[2]["img"] == "static/img/hotdog-qazi.svg"
    # Ulangan taom yashirilsa — banner ham chiqmaydi
    await ctx.db.update_product(banners[1]["product_id"], is_active=0)
    data = await (await ctx.client.get("/api/menu?lang=ru")).json()
    assert len(data["banners"]) == 2 and data["banners"][1]["text"] == "Большой размер — 38 000 сум"


async def test_photos_applied_to_both_sizes(ctx):
    from bot.seed import apply_photos

    products = {p["name_uz"]: p for p in await ctx.db.products()}
    assert products["Burger (kichik)"]["img"] == products["Burger (katta)"]["img"] == "static/img/photos/burger.webp"
    assert products["Doner (katta)"]["img"].endswith("doner.webp")
    assert products["Chizburger (kichik)"]["img"] == "static/img/cheeseburger.svg"
    assert products["Arab kabob (katta)"]["img"] == "static/img/photos/arab-kabob.webp"
    for name in ("burger", "doner", "xagi", "lavash", "lavash-tandir", "arab-kabob"):
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
    assert await apply_photos(db) == 2
    assert (await db.product(pid))["img"] == "static/img/photos/arab-kabob.webp"
    assert await apply_photos(db) == 0
