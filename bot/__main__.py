"""Ishga tushirish: python -m bot"""
from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand, MenuButtonWebApp, WebAppInfo
from aiogram.webhook.aiohttp_server import SimpleRequestHandler
from aiohttp import web

from .config import load_config
from .db import Database
from .handlers import admin, banners, orders, user
from .seed import seed, seed_banners, split_sizes
from .web import create_app

log = logging.getLogger("emirfood")


async def setup_bot_ui(bot: Bot, webapp_url: str | None) -> None:
    await bot.set_my_commands([BotCommand(command="start", description="Boshlash / Начать")])
    if webapp_url:
        await bot.set_chat_menu_button(
            menu_button=MenuButtonWebApp(text="Menyu", web_app=WebAppInfo(url=webapp_url))
        )


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    cfg = load_config()

    db = Database(cfg.database)
    await db.connect()
    await seed(db)
    if (split := await split_sizes(db)):
        log.info("%s ta taom kichik/katta bo'yicha ajratildi", split)
    await seed_banners(db)

    bot = Bot(cfg.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage(), db=db, cfg=cfg)
    dp.include_router(admin.router)
    dp.include_router(banners.router)
    dp.include_router(orders.router)
    dp.include_router(user.router)

    app = create_app(cfg, db, bot)
    if cfg.mode == "webhook":
        SimpleRequestHandler(dispatcher=dp, bot=bot, secret_token=cfg.webhook_secret).register(
            app, path=cfg.webhook_path
        )

    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, cfg.host, cfg.port).start()
    log.info("Veb-server: http://%s:%s  (Mini App: %s, baza: %s)", cfg.host, cfg.port,
             cfg.webapp_url or "HTTPS yo'q", "PostgreSQL" if db.is_pg else "SQLite")
    if not cfg.webapp_url:
        log.warning("BASE_URL https:// emas — Telegram Mini App ochilmaydi. README dagi ko'rsatmaga qarang.")

    try:
        await setup_bot_ui(bot, cfg.webapp_url)
        if cfg.mode == "webhook":
            await bot.set_webhook(
                cfg.base_url + cfg.webhook_path,
                secret_token=cfg.webhook_secret,
                allowed_updates=dp.resolve_used_update_types(),
                drop_pending_updates=False,
            )
            log.info("Webhook rejimi ishga tushdi")
            await asyncio.Event().wait()
        else:
            await bot.delete_webhook(drop_pending_updates=False)
            log.info("Polling rejimi ishga tushdi")
            await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await runner.cleanup()
        await bot.session.close()
        await db.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit) as exc:
        if isinstance(exc, SystemExit) and exc.code not in (None, 0):
            raise
