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

from .access import group_id
from .config import WEBAPP_DIR, Config
from .core import (
    LANGS, OrderError, build_order_lines, guess_lang, is_available, localized,
    norm_lang, normalize_phone, shop_status,
)
from .db import Database
from .notify import group_order_text, user_order_text

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


def _text(value: Any, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


# ---------- sahifalar ----------
async def index(request: web.Request) -> web.FileResponse:
    resp = web.FileResponse(WEBAPP_DIR / "index.html")
    resp.headers["Cache-Control"] = "no-cache"
    return resp


async def health(request: web.Request) -> web.Response:
    return web.Response(text="ok")


def image_url(product: dict[str, Any], fallback: str) -> str:
    """Admin yuklagan rasm Telegramda saqlanadi (img = "tg:<file_id>") va /img/p/<id> orqali beriladi."""
    img = product.get("img") or ""
    if img.startswith("tg:"):
        version = hashlib.sha1(img.encode()).hexdigest()[:8]
        return f"img/p/{product['id']}?v={version}"
    return img or fallback


async def product_image(request: web.Request) -> web.Response:
    try:
        pid = int(request.match_info["pid"])
    except ValueError:
        raise web.HTTPNotFound() from None
    product = await request.app[DB].product(pid)
    if product is None or not (product["img"] or "").startswith("tg:"):
        raise web.HTTPNotFound()
    file_id = product["img"][3:]
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
        },
        "categories": categories,
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


def _public_order(order: dict[str, Any], lang: str) -> dict[str, Any]:
    return {
        "id": order["id"],
        "created_at": order["created_at"],
        "kind": order["kind"],
        "payment": order["payment"],
        "total": order["total"],
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
    if kind not in {"delivery", "pickup"} or payment not in {"cash", "card"}:
        return _error("bad_request")

    name = _text(body.get("name"), 64)
    phone = normalize_phone(str(body.get("phone") or ""))
    if not name:
        return _error("name_required")
    if not phone:
        return _error("phone_invalid")

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
    )
    order = await db.order(order_id)
    await _notify_staff(app, order, tg.username or "")
    try:
        await bot.send_message(tg.id, user_order_text(order, lang, settings))
    except TelegramAPIError as exc:
        log.info("Mijozga tasdiq yuborilmadi (%s): %s", tg.id, exc)

    return web.json_response({"ok": True, "order": _public_order(order, lang)})


async def _notify_staff(app: web.Application, order: dict[str, Any], username: str) -> None:
    db, bot, cfg = app[DB], app[BOT], app[CFG]
    gid = await group_id(db)
    targets = [gid] if gid is not None else sorted(cfg.superadmins)
    if not targets:
        log.error("Buyurtma №%s: xodimlar guruhi sozlanmagan (/setgroup) va SUPERADMIN_IDS bo'sh!", order["id"])
        return
    text = group_order_text(order, username)
    for chat_id in targets:
        try:
            msg = await bot.send_message(chat_id, text)
            if order.get("lat") is not None:
                await bot.send_location(chat_id, order["lat"], order["lon"], reply_to_message_id=msg.message_id)
        except TelegramAPIError as exc:
            log.error("Buyurtma №%s guruhga yuborilmadi (%s): %s", order["id"], chat_id, exc)


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
    app.router.add_get("/img/p/{pid}", product_image)
    app.router.add_static("/static/", WEBAPP_DIR)
    return app
