"""Veb-server: Mini App fayllari va JSON API."""
from __future__ import annotations

import hashlib
import io
import logging
import time
from collections import OrderedDict
from datetime import datetime, timedelta, timezone
from typing import Any

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.utils.web_app import WebAppInitData, safe_parse_webapp_init_data
from aiohttp import web

from .config import WEBAPP_DIR, Config
from .core import (
    LANGS, OrderError, build_order_lines, delivery_zone, format_sum, guess_lang, is_available, localized,
    norm_lang, normalize_phone, shop_status,
)
from .db import Database
from .notify import user_order_text
from .staff import cancel_by_customer, notify_staff

log = logging.getLogger(__name__)

INIT_DATA_MAX_AGE = timedelta(hours=24)
ORDER_COOLDOWN = 15.0

CFG = web.AppKey("cfg", Config)
DB = web.AppKey("db", Database)
BOT = web.AppKey("bot", Bot)
LAST_ORDER = web.AppKey("last_order", dict)
IMG_CACHE = web.AppKey("img_cache", OrderedDict)
IMG_CACHE_SIZE = 60


def _error(code: str, status: int = 400, **extra: Any) -> web.Response:
    return web.json_response({"ok": False, "error": code, **extra}, status=status)


def _auth(request: web.Request) -> WebAppInitData:
    header = request.headers.get("Authorization", "")
    if not header.startswith("tma "):
        raise web.HTTPUnauthorized(text='{"ok":false,"error":"auth"}', content_type="application/json")
    try:
        data = safe_parse_webapp_init_data(request.app[CFG].bot_token, header[4:])
    except ValueError:
        raise web.HTTPUnauthorized(text='{"ok":false,"error":"auth"}', content_type="application/json") from None
    auth_date = data.auth_date
    if auth_date.tzinfo is None:
        auth_date = auth_date.replace(tzinfo=timezone.utc)
    if data.user is None or datetime.now(timezone.utc) - auth_date > INIT_DATA_MAX_AGE:
        raise web.HTTPUnauthorized(text='{"ok":false,"error":"auth"}', content_type="application/json")
    return data


async def _json(request: web.Request) -> dict[str, Any]:
    try:
        body = await request.json()
    except ValueError:
        body = None
    if not isinstance(body, dict):
        raise web.HTTPBadRequest(text='{"ok":false,"error":"bad_request"}', content_type="application/json")
    return body


BANNER_THEMES = ("yellow", "red", "dark")
CURRENCY = {"uz": "so'm", "cyr": "сўм", "ru": "сум"}


def _fill(text: str, values: dict[str, str]) -> str:
    for key, value in values.items():
        text = text.replace("{" + key + "}", value)
    return text


def _text(value: Any, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


# ---------- sahifalar ----------
async def index(request: web.Request) -> web.FileResponse:
    resp = web.FileResponse(WEBAPP_DIR / "index.html")
    resp.headers["Cache-Control"] = "no-cache"
    return resp


async def health(request: web.Request) -> web.Response:
    return web.Response(text="ok")


def image_url(row: dict[str, Any], fallback: str, kind: str = "p") -> str:
    """Admin yuklagan rasm Telegramda saqlanadi (img = "tg:<file_id>") va /img/<p|b>/<id> orqali beriladi."""
    img = row.get("img") or ""
    if img.startswith("tg:"):
        version = hashlib.sha1(img.encode()).hexdigest()[:8]
        return f"img/{kind}/{row['id']}?v={version}"
    return img or fallback


async def stored_image(request: web.Request) -> web.Response:
    """Taom (p) yoki banner (b) uchun Telegramda saqlangan rasm."""
    kind = request.match_info["kind"]
    try:
        pid = int(request.match_info["pid"])
    except ValueError:
        raise web.HTTPNotFound() from None
    db = request.app[DB]
    row = await (db.product(pid) if kind == "p" else db.banner(pid))
    if row is None or not (row["img"] or "").startswith("tg:"):
        raise web.HTTPNotFound()
    file_id = row["img"][3:]
    cache = request.app[IMG_CACHE]
    data = cache.get(file_id)
    if data is None:
        bot = request.app[BOT]
        try:
            file = await bot.get_file(file_id)
            buf = io.BytesIO()
            await bot.download_file(file.file_path, destination=buf)
        except TelegramAPIError as exc:
            log.warning("Rasm yuklanmadi (taom %s): %s", pid, exc)
            raise web.HTTPNotFound() from None
        data = buf.getvalue()
        cache[file_id] = data
        while len(cache) > IMG_CACHE_SIZE:
            cache.popitem(last=False)
    else:
        cache.move_to_end(file_id)
    return web.Response(body=data, content_type="image/jpeg",
                        headers={"Cache-Control": "public, max-age=604800, immutable"})


# ---------- API ----------
async def api_menu(request: web.Request) -> web.Response:
    db = request.app[DB]
    lang = norm_lang(request.query.get("lang"))
    settings = await db.all_settings()
    status = shop_status(settings.get("closed_until", ""))
    products = [p for p in await db.products() if p["is_active"]]
    categories = []
    for cat in await db.categories():
        items = [
            {
                "id": p["id"],
                "name": localized(p, "name", lang),
                "desc": localized(p, "desc", lang),
                "img": image_url(p, cat["img"]),
                "price": p["price"],
                "price_large": p["price_large"],
                "hit": bool(p["is_hit"]),
                "available": is_available(p),
            }
            for p in products if p["category_id"] == cat["id"]
        ]
        if items:
            categories.append({
                "id": cat["id"], "slug": cat["slug"],
                "name": localized(cat, "name", lang), "img": cat["img"], "products": items,
            })
    upsell = settings.get("upsell_product_id", "")
    by_id = {p["id"]: p for p in products}
    banners = []
    for b in await db.banners(active_only=True):
        linked = by_id.get(b["product_id"]) if b["product_id"] else None
        if b["product_id"] and linked is None:
            continue  # ulangan taom yashirilgan yoki o'chirilgan
        price = f"{format_sum(linked['price'])} {CURRENCY[lang]}" if linked and linked["price"] is not None else ""
        fill = {"min": format_sum(int(settings.get("min_order") or 0)), "price": price}
        banners.append({
            "id": b["id"],
            "tag": localized(b, "tag", lang),
            "title": localized(b, "title", lang),
            "text": _fill(localized(b, "text", lang), fill),
            "img": image_url(b, image_url(linked, "") if linked else "static/img/photos/burger.webp", "b"),
            "theme": b["theme"] if b["theme"] in BANNER_THEMES else "yellow",
            "product_id": linked["id"] if linked and is_available(linked) else None,
        })
    data = {
        "ok": True,
        "shop": {
            "open": status.is_open,
            "until": status.until_text(),
            "min_order": int(settings.get("min_order") or 0),
            "phone": settings.get("phone", ""),
            "address": settings.get(f"address_{lang}") or settings.get("address_uz", ""),
            "zone": settings.get(f"delivery_zone_{lang}") or settings.get("delivery_zone_uz", ""),
            "card_number": settings.get("card_number", ""),
            "card_owner": settings.get("card_owner", ""),
            "upsell_id": int(upsell) if upsell.isdigit() else None,
            "zone_area": _zone_public(settings),
        },
        "categories": categories,
        "banners": banners,
    }
    return web.json_response(data, headers={"Cache-Control": "no-store"})


async def api_me(request: web.Request) -> web.Response:
    init = _auth(request)
    db = request.app[DB]
    tg = init.user
    user = await db.upsert_user(tg.id, tg.first_name or "", tg.username or "")
    lang = user["lang"] or guess_lang(tg.language_code)
    return web.json_response({
        "ok": True,
        "user": {
            "name": user["name"] or " ".join(filter(None, [tg.first_name, tg.last_name])),
            "phone": user["phone"],
            "verified_phone": user.get("verified_phone") or "",
            "lang": lang,
        },
    })


async def api_lang(request: web.Request) -> web.Response:
    init = _auth(request)
    body = await _json(request)
    lang = body.get("lang")
    if lang not in LANGS:
        return _error("bad_request")
    db = request.app[DB]
    await db.upsert_user(init.user.id, init.user.first_name or "", init.user.username or "")
    await db.set_user_lang(init.user.id, lang)
    return web.json_response({"ok": True})


def _zone_public(settings: dict[str, str]) -> dict[str, float] | None:
    zone = delivery_zone(settings)
    return {"lat": zone.lat, "lon": zone.lon, "radius_km": zone.radius_km} if zone else None


async def api_cancel(request: web.Request) -> web.Response:
    """Mijoz o'z buyurtmasini bekor qiladi — faqat xodimlar hali qabul qilmagan bo'lsa."""
    init = _auth(request)
    try:
        order_id = int(request.match_info["oid"])
    except ValueError:
        return _error("not_found", 404)
    lang = norm_lang(request.query.get("lang"))
    result, order = await cancel_by_customer(request.app[BOT], request.app[DB], order_id, init.user.id)
    if result == "not_found":
        return _error("not_found", 404)
    if result != "ok":
        return _error("cannot_cancel", 409, order=_public_order(order, lang))
    return web.json_response({"ok": True, "order": _public_order(order, lang)})


def _public_order(order: dict[str, Any], lang: str) -> dict[str, Any]:
    return {
        "id": order["id"],
        "created_at": order["created_at"],
        "kind": order["kind"],
        "payment": order["payment"],
        "total": order["total"],
        "status": order.get("status") or "new",
        "items": [
            {
                "id": line["id"],
                "name": (line.get("names") or {}).get(lang) or line["name"],
                "size": line.get("size", ""),
                "qty": line["qty"],
                "sum": line["sum"],
            }
            for line in order["items"]
        ],
    }


async def api_orders(request: web.Request) -> web.Response:
    init = _auth(request)
    lang = norm_lang(request.query.get("lang"))
    orders = await request.app[DB].user_orders(init.user.id, limit=20)
    return web.json_response({"ok": True, "orders": [_public_order(o, lang) for o in orders]})


async def api_order(request: web.Request) -> web.Response:
    init = _auth(request)
    body = await _json(request)
    app = request.app
    db, bot = app[DB], app[BOT]
    tg = init.user
    lang = norm_lang(body.get("lang"))

    last = app[LAST_ORDER].get(tg.id, 0.0)
    if time.monotonic() - last < ORDER_COOLDOWN:
        return _error("too_fast", 429)

    settings = await db.all_settings()
    status = shop_status(settings.get("closed_until", ""))
    if not status.is_open:
        return _error("closed", 409, until=status.until_text())

    kind = body.get("kind")
    payment = body.get("payment")
    if kind not in {"delivery", "pickup"} or payment not in {"cash", "card", "later"}:
        return _error("bad_request")

    name = _text(body.get("name"), 64)
    phone = normalize_phone(str(body.get("phone") or ""))
    if not name:
        return _error("name_required")
    if not phone:
        return _error("phone_invalid")
    # Raqam Telegram "kontaktni ulashish" orqali kelgan bo'lsa — tasdiqlangan.
    # Eski Telegram ilovalarida bu imkoniyat yo'q: u holda qo'lda yozilgan raqam qabul qilinadi,
    # lekin guruhda "tasdiqlanmagan" deb belgilanadi.
    user_row = await db.user(tg.id)
    verified_phone = (user_row or {}).get("verified_phone") or ""
    phone_verified = bool(verified_phone) and phone == verified_phone
    if not phone_verified and body.get("contact_supported") is not False:
        return _error("phone_unverified")

    address = _text(body.get("address"), 300)
    lat = lon = None
    try:
        if body.get("lat") is not None and body.get("lon") is not None:
            lat, lon = float(body["lat"]), float(body["lon"])
            if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                lat = lon = None
    except (TypeError, ValueError):
        lat = lon = None
    if kind == "delivery" and not address and lat is None:
        return _error("address_required")
    if kind == "pickup":
        address, lat, lon = "", None, None

    zone = delivery_zone(settings)
    dist = None
    if kind == "delivery" and zone is not None and lat is not None:
        dist = round(zone.distance(lat, lon), 2)
        if dist > zone.radius_km:
            return _error("out_of_zone", distance_km=dist, radius_km=zone.radius_km)

    requested = body.get("items")
    try:
        ids = [int(i["id"]) for i in requested] if isinstance(requested, list) else []
    except (KeyError, TypeError, ValueError):
        return _error("bad_request")
    products = await db.products_by_ids(ids[:50])
    try:
        lines, total = build_order_lines(requested, products)
    except OrderError as exc:
        return _error(exc.code, **exc.extra)

    min_order = int(settings.get("min_order") or 0)
    if kind == "delivery" and total < min_order:
        return _error("min_order", min_order=min_order)

    app[LAST_ORDER][tg.id] = time.monotonic()
    await db.upsert_user(tg.id, tg.first_name or "", tg.username or "")
    await db.set_user_contact(tg.id, name, phone)
    order_id = await db.create_order(
        user_id=tg.id, kind=kind, name=name, phone=phone, address=address, lat=lat, lon=lon,
        comment=_text(body.get("comment"), 300), payment=payment, items=lines, total=total,
        phone_verified=int(phone_verified), distance_km=dist,
    )
    order = await db.order(order_id)
    await notify_staff(bot, db, app[CFG], order, tg.username or "")
    try:
        await bot.send_message(tg.id, user_order_text(order, lang, settings))
    except TelegramAPIError as exc:
        log.info("Mijozga tasdiq yuborilmadi (%s): %s", tg.id, exc)

    return web.json_response({"ok": True, "order": _public_order(order, lang)})


def create_app(cfg: Config, db: Database, bot: Bot) -> web.Application:
    app = web.Application(client_max_size=256 * 1024)
    app[CFG] = cfg
    app[DB] = db
    app[BOT] = bot
    app[LAST_ORDER] = {}
    app[IMG_CACHE] = OrderedDict()
    app.router.add_get("/", index)
    app.router.add_get("/healthz", health)
    app.router.add_get("/api/menu", api_menu)
    app.router.add_post("/api/me", api_me)
    app.router.add_post("/api/lang", api_lang)
    app.router.add_get("/api/orders", api_orders)
    app.router.add_post("/api/order", api_order)
    app.router.add_post("/api/orders/{oid}/cancel", api_cancel)
    app.router.add_get("/img/{kind:[pb]}/{pid}", stored_image)
    app.router.add_static("/static/", WEBAPP_DIR)
    return app
