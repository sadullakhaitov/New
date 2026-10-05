"""Mijozlarga yuboriladigan bot xabarlari: o'zbek (lotin), o'zbek (kirill), rus."""
from __future__ import annotations

from .core import norm_lang

LANG_NAMES = {"uz": "🇺🇿 O'zbekcha", "cyr": "🇺🇿 Ўзбекча", "ru": "🇷🇺 Русский"}

TEXTS: dict[str, dict[str, str]] = {
    "choose_lang": {
        "uz": "Tilni tanlang 👇",
        "cyr": "Тилни танланг 👇",
        "ru": "Выберите язык 👇",
    },
    "welcome": {
        "uz": "Assalomu alaykum, {name}! 🍔\n<b>Emir Food</b>ga xush kelibsiz.\n\n"
              "Menyuni oching va bir necha bosishda buyurtma bering.\n"
              "🚚 {min} so'mdan yetkazib berish — <b>bepul</b>!",
        "cyr": "Ассалому алайкум, {name}! 🍔\n<b>Emir Food</b>га хуш келибсиз.\n\n"
               "Менюни очинг ва бир неча босишда буюртма беринг.\n"
               "🚚 {min} сўмдан етказиб бериш — <b>бепул</b>!",
        "ru": "Здравствуйте, {name}! 🍔\nДобро пожаловать в <b>Emir Food</b>.\n\n"
              "Откройте меню и закажите в пару касаний.\n"
              "🚚 Доставка от {min} сум — <b>бесплатно</b>!",
    },
    "closed_note": {
        "uz": "\n\n⏸ Hozir yopiqmiz{until}. Menyuni ko'rishingiz mumkin.",
        "cyr": "\n\n⏸ Ҳозир ёпиқмиз{until}. Менюни кўришингиз мумкин.",
        "ru": "\n\n⏸ Сейчас мы закрыты{until}. Меню можно посмотреть.",
    },
    "closed_until": {
        "uz": " ({until} gacha)",
        "cyr": " ({until} гача)",
        "ru": " (до {until})",
    },
    "btn_open_app": {"uz": "🍔 Buyurtma berish", "cyr": "🍔 Буюртма бериш", "ru": "🍔 Заказать"},
    "btn_menu": {"uz": "🍔 Menyu", "cyr": "🍔 Меню", "ru": "🍔 Меню"},
    "btn_orders": {"uz": "📦 Buyurtmalarim", "cyr": "📦 Буюртмаларим", "ru": "📦 Мои заказы"},
    "btn_contact": {"uz": "📞 Aloqa", "cyr": "📞 Алоқа", "ru": "📞 Контакты"},
    "btn_lang": {"uz": "🌐 Til", "cyr": "🌐 Тил", "ru": "🌐 Язык"},
    "menu_button": {"uz": "Menyu", "cyr": "Меню", "ru": "Меню"},
    "open_menu": {
        "uz": "Menyuni ochish uchun tugmani bosing 👇",
        "cyr": "Менюни очиш учун тугмани босинг 👇",
        "ru": "Нажмите кнопку, чтобы открыть меню 👇",
    },
    "no_webapp": {
        "uz": "Menyu hali sozlanmagan. Iltimos, keyinroq urinib ko'ring yoki {phone} ga qo'ng'iroq qiling.",
        "cyr": "Меню ҳали созланмаган. Илтимос, кейинроқ уриниб кўринг ёки {phone} га қўнғироқ қилинг.",
        "ru": "Меню ещё не настроено. Попробуйте позже или позвоните по номеру {phone}.",
    },
    "lang_set": {"uz": "✅ Til o'zgartirildi", "cyr": "✅ Тил ўзгартирилди", "ru": "✅ Язык изменён"},
    "no_orders": {
        "uz": "Sizda hali buyurtmalar yo'q. Menyudan birinchi buyurtmangizni bering! 🍔",
        "cyr": "Сизда ҳали буюртмалар йўқ. Менюдан биринчи буюртмангизни беринг! 🍔",
        "ru": "У вас пока нет заказов. Сделайте первый заказ из меню! 🍔",
    },
    "orders_title": {
        "uz": "📦 <b>Oxirgi buyurtmalaringiz</b>",
        "cyr": "📦 <b>Охирги буюртмаларингиз</b>",
        "ru": "📦 <b>Ваши последние заказы</b>",
    },
    "contact": {
        "uz": "📞 {phone}\n📍 {address}\n🕒 Har kuni, 24/7\n🚚 Yetkazib berish bepul — {zone}, {min} so'mdan",
        "cyr": "📞 {phone}\n📍 {address}\n🕒 Ҳар куни, 24/7\n🚚 Етказиб бериш бепул — {zone}, {min} сўмдан",
        "ru": "📞 {phone}\n📍 {address}\n🕒 Ежедневно, 24/7\n🚚 Доставка бесплатно — {zone}, от {min} сум",
    },
    "order_confirm": {
        "uz": "📨 <b>Buyurtmangiz yuborildi!</b>  №{id}\n➖➖➖➖➖➖➖➖\n{lines}\n\n💰 <b>Jami: {total} so'm</b>\n"
              "➖➖➖➖➖➖➖➖\n{kind}\n{payment}\n\n⏳ Xodimlarimiz tasdiqlashi bilan shu yerga xabar keladi.",
        "cyr": "📨 <b>Буюртмангиз юборилди!</b>  №{id}\n➖➖➖➖➖➖➖➖\n{lines}\n\n💰 <b>Жами: {total} сўм</b>\n"
               "➖➖➖➖➖➖➖➖\n{kind}\n{payment}\n\n⏳ Ходимларимиз тасдиқлаши билан шу ерга хабар келади.",
        "ru": "📨 <b>Ваш заказ отправлен!</b>  №{id}\n➖➖➖➖➖➖➖➖\n{lines}\n\n💰 <b>Итого: {total} сум</b>\n"
              "➖➖➖➖➖➖➖➖\n{kind}\n{payment}\n\n⏳ Как только сотрудники подтвердят заказ, здесь придёт сообщение.",
    },
    "order_accepted": {
        "uz": "✅ <b>Buyurtmangiz №{id} qabul qilindi!</b>\nTayyorlashni boshladik. Yoqimli ishtaha! 😋",
        "cyr": "✅ <b>Буюртмангиз №{id} қабул қилинди!</b>\nТайёрлашни бошладик. Ёқимли иштаҳа! 😋",
        "ru": "✅ <b>Ваш заказ №{id} принят!</b>\nУже готовим. Приятного аппетита! 😋",
    },
    "order_canceled": {
        "uz": "❌ <b>Buyurtmangiz №{id} bekor qilindi.</b>\nSavollar bo'lsa, qo'ng'iroq qiling: {phone}",
        "cyr": "❌ <b>Буюртмангиз №{id} бекор қилинди.</b>\nСаволлар бўлса, қўнғироқ қилинг: {phone}",
        "ru": "❌ <b>Ваш заказ №{id} отменён.</b>\nЕсли есть вопросы, позвоните: {phone}",
    },
    "kind_delivery": {
        "uz": "🚚 Yetkazib berish (bepul)",
        "cyr": "🚚 Етказиб бериш (бепул)",
        "ru": "🚚 Доставка (бесплатно)",
    },
    "kind_pickup": {
        "uz": "🏃 Olib ketish: {address}",
        "cyr": "🏃 Олиб кетиш: {address}",
        "ru": "🏃 Самовывоз: {address}",
    },
    "pay_cash": {"uz": "💵 To'lov: naqd", "cyr": "💵 Тўлов: нақд", "ru": "💵 Оплата: наличными"},
    "pay_card": {
        "uz": "💳 To'lov: kartaga o'tkazma (Click / Payme)\nKarta: <code>{card}</code>{owner}\n"
              "📸 To'lovdan so'ng chek rasmini shu chatga yuboring.",
        "cyr": "💳 Тўлов: картага ўтказма (Click / Payme)\nКарта: <code>{card}</code>{owner}\n"
               "📸 Тўловдан сўнг чек расмини шу чатга юборинг.",
        "ru": "💳 Оплата: перевод на карту (Click / Payme)\nКарта: <code>{card}</code>{owner}\n"
              "📸 После оплаты отправьте фото чека в этот чат.",
    },
    "pay_later": {
        "uz": "🤝 To'lov: buyurtmani olgandan keyin — naqd yoki kartaga\nKarta: <code>{card}</code>{owner}\n"
              "📸 Kartaga o'tkazsangiz, chek rasmini shu chatga yuboring.",
        "cyr": "🤝 Тўлов: буюртмани олгандан кейин — нақд ёки картага\nКарта: <code>{card}</code>{owner}\n"
               "📸 Картага ўтказсангиз, чек расмини шу чатга юборинг.",
        "ru": "🤝 Оплата: после получения заказа — наличными или на карту\nКарта: <code>{card}</code>{owner}\n"
              "📸 Если переводите на карту, отправьте фото чека в этот чат.",
    },
    "receipt_ok": {
        "uz": "🧾 <b>Chek qabul qilindi!</b>\nU buyurtma №{id} bilan birga xodimlarga yuborildi. Rahmat!",
        "cyr": "🧾 <b>Чек қабул қилинди!</b>\nУ буюртма №{id} билан бирга ходимларга юборилди. Раҳмат!",
        "ru": "🧾 <b>Чек получен!</b>\nОн отправлен сотрудникам вместе с заказом №{id}. Спасибо!",
    },
    "receipt_no_order": {
        "uz": "Avval buyurtma bering, so'ng chekni yuboring 🙂",
        "cyr": "Аввал буюртма беринг, сўнг чекни юборинг 🙂",
        "ru": "Сначала оформите заказ, затем отправьте чек 🙂",
    },
    "phone_saved": {
        "uz": "✅ Raqamingiz saqlandi: {phone}",
        "cyr": "✅ Рақамингиз сақланди: {phone}",
        "ru": "✅ Номер сохранён: {phone}",
    },
    "btn_cancel_order": {"uz": "❌ №{id} ni bekor qilish", "cyr": "❌ №{id} ни бекор қилиш", "ru": "❌ Отменить №{id}"},
    "cancel_q": {
        "uz": "Buyurtma №{id} bekor qilinsinmi?",
        "cyr": "Буюртма №{id} бекор қилинсинми?",
        "ru": "Отменить заказ №{id}?",
    },
    "cancel_yes": {"uz": "Ha, bekor qilinsin", "cyr": "Ҳа, бекор қилинсин", "ru": "Да, отменить"},
    "cancel_no": {"uz": "Yo'q", "cyr": "Йўқ", "ru": "Нет"},
    "canceled_by_you": {
        "uz": "❌ Buyurtma №{id} bekor qilindi.",
        "cyr": "❌ Буюртма №{id} бекор қилинди.",
        "ru": "❌ Заказ №{id} отменён.",
    },
    "cannot_cancel": {
        "uz": "Buyurtma №{id} allaqachon qabul qilingan, endi bekor qilib bo'lmaydi. Savollar bo'lsa: {phone}",
        "cyr": "Буюртма №{id} аллақачон қабул қилинган, энди бекор қилиб бўлмайди. Саволлар бўлса: {phone}",
        "ru": "Заказ №{id} уже принят, отменить его нельзя. Если есть вопросы: {phone}",
    },
    "size_small": {"uz": "kichik", "cyr": "кичик", "ru": "маленький"},
    "size_large": {"uz": "katta", "cyr": "катта", "ru": "большой"},
    "currency": {"uz": "so'm", "cyr": "сўм", "ru": "сум"},
}


def t(key: str, lang: str | None, **kwargs) -> str:
    text = TEXTS[key][norm_lang(lang)]
    return text.format(**kwargs) if kwargs else text
