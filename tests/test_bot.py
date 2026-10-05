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
from bot.handlers import admin, banners, orders, user

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
        _DP.include_router(banners.router)
        _DP.include_router(orders.router)
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


def cb(data: str, user_id: int, chat_id: int | None = None) -> Update:
    chat = Chat(id=chat_id, type="supergroup") if chat_id else Chat(id=user_id, type="private")
    m = Message(message_id=1, date=datetime.now(), chat=chat, text="x")
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


async def test_admin_price_list(env):
    bot, dp, db, session = env
    await db.set_setting("group_chat_id", str(GROUP_ID))
    from aiogram.methods import EditMessageText
    await dp.feed_update(bot, cb("a:prices", ADMIN_ID))
    edit = next(c for c in reversed(session.calls) if isinstance(c, EditMessageText))
    buttons = [b.text for row in edit.reply_markup.inline_keyboard for b in row]
    assert "Lavash — 40 000" in buttons and "Emir burger — narx yo'q ❗" in buttons
    pid = next(p["id"] for p in await db.products() if p["name_uz"] == "Emir burger")
    await dp.feed_update(bot, cb(f"a:pr:{pid}", ADMIN_ID))
    assert "Emir burger" in session.texts()[-1]
    await dp.feed_update(bot, msg("42", ADMIN_ID))
    assert (await db.product(pid))["price"] == 42000
    assert session.texts()[-1].startswith("✅ Emir burger — 42 000 so'm") and "Narxlar" in session.texts()[-1]

    # Sozlamalar: minimal summa saqlangach sozlamalarga qaytadi
    await dp.feed_update(bot, cb("a:set", ADMIN_ID))
    await dp.feed_update(bot, cb("a:min", ADMIN_ID))
    await dp.feed_update(bot, msg("60000", ADMIN_ID))
    assert await db.get_setting("min_order") == "60000" and "Sozlamalar" in session.texts()[-1]


async def test_add_product(env):
    bot, dp, db, session = env
    await db.set_setting("group_chat_id", str(GROUP_ID))
    cat = (await db.categories())[1]
    await dp.feed_update(bot, cb(f"a:addc:{cat['id']}", ADMIN_ID))
    await dp.feed_update(bot, msg("Tovuq lavash", ADMIN_ID))
    await dp.feed_update(bot, msg("38", ADMIN_ID))
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


async def _new_order(db):
    await db.upsert_user(CLIENT_ID, "Ali")
    await db.set_user_lang(CLIENT_ID, "ru")
    return await db.create_order(
        user_id=CLIENT_ID, kind="pickup", name="Ali", phone="+998901234567", payment="cash",
        items=[{"id": 1, "name": "Fri", "size": "", "qty": 1, "price": 15000, "sum": 15000}], total=15000)


async def test_order_accept_from_group(env):
    bot, dp, db, session = env
    await db.set_setting("group_chat_id", str(GROUP_ID))
    oid = await _new_order(db)
    await dp.feed_update(bot, cb(f"o:acc:{oid}", CLIENT_ID + 5, GROUP_ID))
    order = await db.order(oid)
    assert order["status"] == "accepted" and order["status_by"] == "Ali"
    from aiogram.methods import EditMessageText
    edit = next(c for c in reversed(session.calls) if isinstance(c, EditMessageText))
    assert "QABUL QILINDI" in edit.text and edit.reply_markup.inline_keyboard[0][0].callback_data == f"o:rej:{oid}"
    assert any("принят" in t for t in session.texts())  # mijozga o'z tilida

    # Ikkinchi marta bosilsa — holat o'zgarmaydi, mijozga qayta xabar bormaydi
    n = len(session.texts())
    await dp.feed_update(bot, cb(f"o:acc:{oid}", CLIENT_ID + 6, GROUP_ID))
    assert len(session.texts()) == n


async def test_order_cancel_needs_confirmation(env):
    bot, dp, db, session = env
    await db.set_setting("group_chat_id", str(GROUP_ID))
    oid = await _new_order(db)
    await dp.feed_update(bot, cb(f"o:rej:{oid}", CLIENT_ID + 5, GROUP_ID))
    assert (await db.order(oid))["status"] == "new"  # hali tasdiqlanmagan
    await dp.feed_update(bot, cb(f"o:rejy:{oid}", CLIENT_ID + 5, GROUP_ID))
    assert (await db.order(oid))["status"] == "canceled"
    assert any("отменён" in t and "+998 95 289 85 55" in t for t in session.texts())


async def test_order_buttons_only_in_staff_group(env):
    bot, dp, db, session = env
    await db.set_setting("group_chat_id", str(GROUP_ID))
    oid = await _new_order(db)
    await dp.feed_update(bot, cb(f"o:acc:{oid}", CLIENT_ID, -999))
    assert (await db.order(oid))["status"] == "new"


async def test_banner_admin_flow(env):
    bot, dp, db, session = env
    await db.set_setting("group_chat_id", str(GROUP_ID))
    assert len(await db.banners()) == 3
    await dp.feed_update(bot, cb("b:new", ADMIN_ID))
    new = (await db.banners())[-1]
    assert new["is_active"] == 0
    await dp.feed_update(bot, cb(f"b:f:title:{new['id']}", ADMIN_ID))
    await dp.feed_update(bot, msg("Ikkinchi lavash -20% | Иккинчи лаваш -20% | Второй лаваш -20%", ADMIN_ID))
    await dp.feed_update(bot, cb(f"b:t:{new['id']}", ADMIN_ID))
    await dp.feed_update(bot, cb(f"b:th:{new['id']}", ADMIN_ID))
    await dp.feed_update(bot, cb(f"b:up:{new['id']}", ADMIN_ID))
    b = await db.banner(new["id"])
    assert b["title_ru"] == "Второй лаваш -20%" and b["is_active"] == 1 and b["theme"] == "red"
    assert [x["id"] for x in await db.banners()][2] == new["id"]  # bir pog'ona yuqoriga

    # Oddiy foydalanuvchi banner tugmalarini bosolmaydi, lekin til tugmasi ishlayveradi
    await dp.feed_update(bot, cb(f"b:t:{new['id']}", CLIENT_ID))
    assert (await db.banner(new["id"]))["is_active"] == 1
    await dp.feed_update(bot, cb("lang:ru", CLIENT_ID))
    assert (await db.user(CLIENT_ID))["lang"] == "ru"


def contact_msg(user_id: int, owner_id: int, phone: str) -> Update:
    from aiogram.types import Contact

    m = Message(message_id=next(_uid), date=datetime.now(), chat=Chat(id=user_id, type="private"),
                from_user=User(id=user_id, is_bot=False, first_name="Ali"),
                contact=Contact(phone_number=phone, first_name="Ali", user_id=owner_id))
    return Update(update_id=next(_uid), message=m)


async def test_shared_contact_is_saved_as_verified_phone(env):
    bot, dp, db, session = env
    await dp.feed_update(bot, contact_msg(CLIENT_ID, CLIENT_ID, "998901112233"))
    assert (await db.user(CLIENT_ID))["verified_phone"] == "+998901112233"
    # Boshqa odamning kontakti hisobga olinmaydi
    await dp.feed_update(bot, contact_msg(CLIENT_ID, 12345, "998909999999"))
    assert (await db.user(CLIENT_ID))["verified_phone"] == "+998901112233"


async def test_customer_cancel_from_bot(env):
    bot, dp, db, session = env
    await db.set_setting("group_chat_id", str(GROUP_ID))
    oid = await _new_order(db)
    await dp.feed_update(bot, msg("📦 Мои заказы", CLIENT_ID))
    from aiogram.methods import SendMessage
    last = next(c for c in reversed(session.calls) if isinstance(c, SendMessage) and c.chat_id == CLIENT_ID)
    assert last.reply_markup.inline_keyboard[0][0].callback_data == f"c:can:{oid}"
    await dp.feed_update(bot, cb(f"c:yes:{oid}", CLIENT_ID))
    assert (await db.order(oid))["status"] == "canceled"
    # Qabul qilingan buyurtmani bekor qilib bo'lmaydi
    oid2 = await _new_order(db)
    await db.set_order_status(oid2, "accepted", "Oshpaz")
    await dp.feed_update(bot, cb(f"c:yes:{oid2}", CLIENT_ID))
    assert (await db.order(oid2))["status"] == "accepted"


async def test_admin_delivery_zone(env):
    bot, dp, db, session = env
    await db.set_setting("group_chat_id", str(GROUP_ID))
    from aiogram.types import Location
    await dp.feed_update(bot, cb("a:zone:loc", ADMIN_ID))
    m = Message(message_id=next(_uid), date=datetime.now(), chat=Chat(id=ADMIN_ID, type="private"),
                from_user=User(id=ADMIN_ID, is_bot=False, first_name="A"),
                location=Location(latitude=40.123456, longitude=64.654321))
    await dp.feed_update(bot, Update(update_id=next(_uid), message=m))
    await dp.feed_update(bot, cb("a:zone:r", ADMIN_ID))
    await dp.feed_update(bot, msg("2,5", ADMIN_ID))
    s = await db.all_settings()
    assert (s["shop_lat"], s["shop_lon"], s["delivery_radius_km"]) == ("40.123456", "64.654321", "2.5")
    await dp.feed_update(bot, cb("a:zone:off", ADMIN_ID))
    assert await db.get_setting("delivery_radius_km") == ""
