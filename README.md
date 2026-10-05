# Emir Food — Telegram buyurtma boti

Peshku tumanidagi **Emir Food** fastfudi uchun Telegram bot va Mini App.

- **Mijoz** botda «Menyu» tugmasini bosadi. Mini App ochiladi: rasmli menyu, kichik/katta o'lcham, savat va rasmiylashtirish. Ilova uch tilda ishlaydi: o'zbek lotin, o'zbek kirill, rus.
- **Buyurtma** xodimlar Telegram guruhiga keladi: taomlar, summa, telefon, manzil va lokatsiya. Mijozga botda tasdiq xabari boradi.
- **Admin panel** bot ichida ishlaydi (`/admin`). Undan taom qo'shish, narx, rasm va nomni o'zgartirish, taomni yashirish, karta raqami, minimal summa, do'konni «ertagacha» yoki aniq vaqtgacha yopish boshqariladi. Ma'lumotlar bazasining zaxira nusxasini ham shu yerdan olasiz.

## Tuzilishi

```
bot/            Python (aiogram 3 + aiohttp + SQLite)
  __main__.py   ishga tushirish: python -m bot
  handlers/     user.py — mijoz, admin.py — admin panel va /setgroup
  web.py        Mini App fayllari va API (/api/menu, /api/order, ...)
  seed.py       boshlang'ich menyu va narxlar
webapp/         Mini App (HTML/CSS/JS, Font Awesome ikonkalari, taom rasmlari)
tests/          avtomatik testlar
```

## 1. Tayyorgarlik

1. **Tokenni yangilang.** @BotFather → `/revoke` → botni tanlang → yangi tokenni oling. Eski token chatda ochiq yozilgan edi, shuning uchun uni bekor qilish shart.
2. Python 3.11 yoki undan yangi versiya kerak.
3. Kerakli paketlarni o'rnating:
   ```bash
   python -m venv .venv
   source .venv/bin/activate        # Windows: .venv\Scripts\activate
   pip install -r requirements.txt
   ```
4. `.env.example` faylidan nusxa olib, `.env` yarating va to'ldiring:
   ```
   BOT_TOKEN=yangi_token
   BASE_URL=https://sizning-manzilingiz
   MODE=polling
   ```
   `.env` GitHub'ga yuklanmaydi (`.gitignore` da turibdi).

## 2. Ishga tushirish

```bash
python -m bot
```

Telegram Mini App faqat **HTTPS** manzilda ochiladi. Shuning uchun `BASE_URL` ommaviy HTTPS manzil bo'lishi kerak.

**O'z kompyuteringizda sinash (bepul).** [cloudflared](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/) dasturini o'rnating va ishga tushiring:
```bash
cloudflared tunnel --url http://localhost:8080
```
Dastur `https://....trycloudflare.com` ko'rinishidagi manzil beradi. Uni `.env` dagi `BASE_URL` ga yozing va botni qayta ishga tushiring. Bu manzil har safar o'zgaradi, shuning uchun faqat sinash uchun mos keladi.

**Hostingda.** Serverni keyin birga tanlaymiz. Ikki rejim bor:
- `MODE=polling`: doim yoqiq turadigan server yoki kompyuter uchun.
- `MODE=webhook`: kirilmaganda «uxlab qoladigan» bepul hostinglar uchun (masalan Render). Bunda Telegram xabari kelganda server o'zi uyg'onadi.

Ishga tushirish buyrug'i ikkala rejimda ham bir xil: `python -m bot`. Port `PORT` o'zgaruvchisidan olinadi.

> ⚠️ Ba'zi bepul hostinglarda server qayta ishga tushganda fayllar o'chib ketadi, `data/` papkasi ham. Shunday hostingda menyudagi o'zgarishlar va buyurtmalar tarixi yo'qolishi mumkin. Admin paneldagi **💾 Zaxira nusxa** tugmasi bazani faylga saqlab beradi.

## 3. Xodimlar guruhini ulash

1. Telegram'da guruh yarating va xodimlarni qo'shing.
2. Botni guruhga qo'shing.
3. Guruhda (guruh admini sifatida) `/setgroup` deb yozing. Shundan keyin barcha buyurtmalar shu guruhga keladi.
4. Guruh adminlari botga **shaxsiy chatda** `/admin` deb yozib, admin panelni ochadi.

Agar biror odam guruh admini bo'lmasa ham panelga kirishi kerak bo'lsa, uning Telegram ID raqamini `.env` dagi `SUPERADMIN_IDS` ga yozing.

## 4. Font Awesome

Ikonkalar sizning Font Awesome kit'ingizdan olinadi (`webapp/index.html`). Kit sozlamalarida domenlar ro'yxati cheklangan bo'lsa, `BASE_URL` domenini u yerga qo'shing. Ikonkalar yuklanmasa ham ilova ishlayveradi, ularning o'rnida oddiy belgilar (+, −, ✓) chiqadi.

## 5. Testlar

```bash
pip install -r requirements-dev.txt
python -m pytest
```
