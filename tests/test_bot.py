"""Bot handlerlarini Telegram'ga ulanmasdan sinash (so'rovlar soxta sessiya orqali ushlanadi)."""
from datetime import datetime
from typing import Any

import pytest
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.base import BaseSession
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.methods import GetChatMember, SendMessage, TelegramMethod
from aiogram.types import (
    CallbackQuery, Chat, ChatMemberAdministrator, ChatMemberMember, Message, Update, User,
)

from bot import access
from bot.config import Config
from bot.handlers import admin, user

ADMIN_ID, CLIENT_ID, GROUP_ID = 10, 20, -1001


class FakeSession(BaseSession):
    def __init__(self):
        super().__init__()
        self.calls: list[TelegramMethod] = []

    async def make_request(self, bot: Bot, method: TelegramMethod, timeout: Any = None) -> Any:
        self.calls.append(method)
        if isinstance(method, SendMessage):
            return Message(message_id=len(self.calls), date=datetime.now(),
                           chat=Chat(id=method.chat_id, type="private"), text=method.text)
        if isinstance(method, GetChatMember):
            u = User(id=method.user_id, is_bot=False, first_name="x")
            if method.user_id == ADMIN_ID:
                return ChatMemberAdministrator.model_construct(status="administrator", user=u)
            return ChatMemberMember.model_construct(status="member", user=u)
        return True

    async def close(self):
        pass

    async def stream_content(self, *a, **k):  # pragma: no cover
        yield b""

    def texts(self) -> list[str]:
        return [c.text for c in self.calls if isinstance(c, SendMessage)]


_DP: Dispatcher | None = None


def _dispatcher() -> Dispatcher:
    # Routerlar modul darajasida — ularni bitta dispatcherga faqat bir marta ulash mumkin.
    global _DP
    if _DP is None:
        _DP = Dispatcher(storage=MemoryStorage())
        _DP.include_router(admin.router)
        _DP.include_router(user.router)
    return _DP


@pytest.fixture
async def env(tmp_path, fresh_db):
    cfg = Config(bot_token="42:TEST", base_url="https://example.com", mode="polling", host="", port=0,
                 data_dir=tmp_path, superadmins=frozenset())
    db = fresh_db
    session = FakeSession()
    bot = Bot("42:TEST", session=session, default=DefaultBotProperties(parse_mode="HTML"))
    dp = _dispatcher()
    dp.workflow_data.update(db=db, cfg=cfg)
    dp.fsm.storage = MemoryStorage()
    access.forget()
    yield bot, dp, db, session


_uid = iter(range(1, 10_000))


def msg(text: str, user_id: int, chat_id: int | None = None, chat_type: str = "private") -> Update:
    chat = Chat(id=chat_id or user_id, type=chat_type, first_name="Ali")
    m = Message(message_id=next(_uid), date=datetime.now(), chat=chat,
                from_user=User(id=user_id, is_bot=False, first_name="Ali"), text=text)
    return Update(update_id=next(_uid), message=m)


def cb(data: str, user_id: int) -> Update:
    m = Message(message_id=1, date=datetime.now(), chat=Chat(id=user_id, type="private"), text="x")
    q = CallbackQuery(id=str(next(_uid)), from_user=User(id=user_id, is_bot=False, first_name="Ali"),
                      chat_instance="c", data=data, message=m)
    return Update(update_id=next(_uid), callback_query=q)


async def test_start_language_and_welcome(env):
    bot, dp, db, session = env
    await dp.feed_update(bot, msg("/start", CLIENT_ID))
    assert "Tilni tanlang" in session.texts()[-1]
    await dp.feed_update(bot, cb("lang:ru", CLIENT_ID))
    assert (await db.user(CLIENT_ID))["lang"] == "ru"
    assert any("Добро пожаловать" in t for t in session.texts())
    await dp.feed_update(bot, msg("📞 Контакты", CLIENT_ID))
    assert "+998 95 289 85 55" in session.texts()[-1]
    await dp.feed_update(bot, msg("📦 Мои заказы", CLIENT_ID))
    assert "нет заказов" in session.texts()[-1]


async def test_setgroup_and_admin_panel(env):
    bot, dp, db, session = env
    await dp.feed_update(bot, msg("/setgroup", CLIENT_ID, GROUP_ID, "supergroup"))
    assert await db.get_setting("group_chat_id") == ""
    await dp.feed_update(bot, msg("/setgroup", ADMIN_ID, GROUP_ID, "supergroup"))
    assert await db.get_setting("group_chat_id") == str(GROUP_ID)

    # Oddiy mijoz /admin yozsa — panel ochilmaydi
    n = len(session.texts())
    await dp.feed_update(bot, msg("/admin", CLIENT_ID))
    assert all("admin panel" not in t for t in session.texts()[n:])

    await dp.feed_update(bot, msg("/admin", ADMIN_ID))
    assert "admin panel" in session.texts()[-1]

    # Narxni o'zgartirish: Emir burger narxi kiritiladi
    pid = next(p["id"] for p in await db.products() if p["name_uz"] == "Emir burger")
    await dp.feed_update(bot, cb(f"a:pp:{pid}", ADMIN_ID))
    await dp.feed_update(bot, msg("55 000", ADMIN_ID))
    assert (await db.product(pid))["price"] == 55000

    # Mijoz admin tugmasini bosolmaydi
    await dp.feed_update(bot, cb(f"a:pt:{pid}", CLIENT_ID))
    assert (await db.product(pid))["is_active"] == 1

    # Do'konni yopish (aniq vaqt) va ochish
    await dp.feed_update(bot, cb("a:cl:custom", ADMIN_ID))
    await dp.feed_update(bot, msg("23.12.2099 09:00", ADMIN_ID))
    assert (await db.get_setting("closed_until")).startswith("2099-12-23T09:00")
    await dp.feed_update(bot, cb("a:open", ADMIN_ID))
    assert await db.get_setting("closed_until") == ""

    # Karta raqami
    await dp.feed_update(bot, cb("a:in:card", ADMIN_ID))
    await dp.feed_update(bot, msg("8600123412341234", ADMIN_ID))
    assert await db.get_setting("card_number") == "8600 1234 1234 1234"


async def test_add_product(env):
    bot, dp, db, session = env
    await db.set_setting("group_chat_id", str(GROUP_ID))
    cat = (await db.categories())[1]
    await dp.feed_update(bot, cb(f"a:addc:{cat['id']}", ADMIN_ID))
    await dp.feed_update(bot, msg("Tovuq lavash", ADMIN_ID))
    await dp.feed_update(bot, msg("38", ADMIN_ID))
    await dp.feed_update(bot, msg("-", ADMIN_ID))
    p = next(p for p in await db.products(cat["id"]) if p["name_uz"] == "Tovuq lavash")
    assert p["price"] == 38000 and p["price_large"] is None


async def test_admin_orders_list(env):
    bot, dp, db, session = env
    await db.set_setting("group_chat_id", str(GROUP_ID))
    await db.create_order(user_id=CLIENT_ID, kind="pickup", name="Ali", phone="+998901234567", payment="cash",
                          items=[{"id": 1, "name": "Fri", "size": "", "qty": 2, "price": 15000, "sum": 30000}],
                          total=30000)
    await dp.feed_update(bot, cb("a:orders", ADMIN_ID))
    from aiogram.methods import EditMessageText
    text = next(c.text for c in reversed(session.calls) if isinstance(c, EditMessageText))
    assert "№1001" in text and "Bugun: <b>1</b> ta · 30 000" in text and "Fri ×2" in text
