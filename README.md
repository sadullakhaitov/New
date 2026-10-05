# Emir Food — Telegram buyurtma boti

Peshku tumanidagi **Emir Food** fastfudi uchun Telegram bot va Mini App.

- **Mijoz** botda «Menyu» tugmasini bosadi. Mini App ochiladi: rasmli menyu, kichik/katta o'lcham, savat va rasmiylashtirish. Ilova uch tilda ishlaydi: o'zbek lotin, o'zbek kirill, rus.
- **Buyurtma** xodimlar Telegram guruhiga keladi: taomlar, summa, telefon, manzil va lokatsiya. Mijozga botda tasdiq xabari boradi.
- **Admin panel** bot ichida ishlaydi (`/admin`). Undan taom qo'shish, narx, rasm va nomni o'zgartirish, taomni yashirish, karta raqami, minimal summa, do'konni «ertagacha» yoki aniq vaqtgacha yopish boshqariladi. Zaxira nusxani (JSON fayl) ham shu yerdan olasiz.

## Tuzilishi

```
bot/            Python (aiogram 3 + aiohttp; PostgreSQL yoki SQLite)
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

## 2.1. Bepul hostingga joylash: Render + Neon

- **Neon** — bepul PostgreSQL ma'lumotlar bazasi: menyu, sozlamalar va buyurtmalar shu yerda saqlanadi. Karta talab qilmaydi.
- **Render** — bot va Mini App ishlaydigan bepul server. Karta talab qilmaydi. Bepul server 15 daqiqa ishlatilmasa «uxlab qoladi», keyingi so'rovda taxminan 1 daqiqada uyg'onadi. Render fayllarni saqlamaydi, shuning uchun ma'lumotlar Neon'da, taom rasmlari esa Telegram'da saqlanadi.

### A. Neon (ma'lumotlar bazasi)
1. https://neon.tech saytida ro'yxatdan o'ting (Google yoki GitHub orqali).
2. **Create project**: nomi `emirfood`, region — Yevropaga eng yaqini (masalan Frankfurt).
3. **Connect** tugmasini bosing va `postgresql://...` bilan boshlanadigan manzilni (connection string) nusxalang. Bu manzil parolni ham o'z ichiga oladi, uni hech kimga ko'rsatmang.

### B. Render (server)
1. https://render.com saytida GitHub orqali ro'yxatdan o'ting va `New` repozitoriyasiga ruxsat bering.
2. **New → Web Service** → `New` repozitoriyasini tanlang.
3. Sozlamalar:
   - **Branch:** kod turgan branch (`main` ga birlashtirilgan bo'lsa — `main`)
   - **Runtime:** Python 3
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `python -m bot`
   - **Instance Type:** Free
4. **Environment Variables** bo'limiga quyidagilarni qo'shing:

   | Nomi | Qiymati |
   |---|---|
   | `BOT_TOKEN` | @BotFather bergan yangi token |
   | `DATABASE_URL` | Neon'dan nusxalangan manzil |
   | `MODE` | `webhook` |
   | `PYTHON_VERSION` | `3.12.8` |
   | `SUPERADMIN_IDS` | (ixtiyoriy) sizning Telegram ID raqamingiz |

   `BASE_URL` ni yozish shart emas: Render o'z manzilini (`https://emirfood-xxxx.onrender.com`) botga o'zi beradi.
5. **Create Web Service** tugmasini bosing. 2–3 daqiqadan keyin logda `Webhook rejimi ishga tushdi` yozuvi chiqadi.
6. Telegram'da botga `/start` deb yozing.

### C. Server uxlab qolmasligi
Render bepul serverni 15 daqiqa jimlikdan keyin uxlatadi. Bot Render'da ishga tushganda buni o'zi oldini oladi: har 10 daqiqada o'zining `/healthz` manziliga so'rov yuboradi (logda `Keepalive yoqildi` yozuvi chiqadi). O'chirish kerak bo'lsa — `KEEPALIVE=0`.

Zaxira sifatida https://cron-job.org da bepul vazifa ham qo'ying: har 10 daqiqada `https://<sizning-manzil>.onrender.com/healthz`. Server biror sabab bilan qayta ishga tushsa, u darhol uyg'otadi.

Render bepul tarifda oyiga 750 soat beradi — bitta server butun oy uzluksiz ishlashiga yetadi. Shu akkauntda boshqa bepul server ham ishlasa, soatlar bo'linadi va oy oxirida yetmay qolishi mumkin.

### Yangilanishlar
GitHub'dagi branchga yangi kod push qilinsa, Render uni o'zi qayta o'rnatadi. Ma'lumotlar Neon'da bo'lgani uchun hech narsa o'chmaydi.

## 3. Xodimlar guruhini ulash

1. Telegram'da guruh yarating va xodimlarni qo'shing.
2. Botni guruhga qo'shing.
3. Guruhda (guruh admini sifatida) `/setgroup` deb yozing. Shundan keyin barcha buyurtmalar shu guruhga keladi.
4. Guruh adminlari botga **shaxsiy chatda** `/admin` deb yozib, admin panelni ochadi.

**Buyurtma qoidalari:**
- Telefon raqam Mini App'dagi «Raqamni Telegram orqali yuborish» tugmasi bilan olinadi — raqam haqiqiy bo'ladi. Juda eski Telegram ilovalarida qo'lda yoziladi va guruhda ⚠️ «tasdiqlanmagan» deb belgilanadi.
- Yetkazish hududi: `/admin` → 📍 Yetkazish hududi → do'kon joylashuvini yuboring va radiusni (km) kiriting. Shundan keyin radiusdan uzoq lokatsiyaga yetkazish qabul qilinmaydi. Lokatsiyasiz buyurtmalar guruhda ⚠️ bilan keladi.
- Mijoz buyurtmani faqat xodimlar «Qabul qilish» ni bosmaguncha bekor qila oladi (Mini App yoki botdagi «Buyurtmalarim»). Bekor qilinsa, guruhdagi xabar yangilanadi.

Agar biror odam guruh admini bo'lmasa ham panelga kirishi kerak bo'lsa, uning Telegram ID raqamini `.env` dagi `SUPERADMIN_IDS` ga yozing.

## 4. Font Awesome

Ikonkalar sizning Font Awesome kit'ingizdan olinadi (`webapp/index.html`). Kit sozlamalarida domenlar ro'yxati cheklangan bo'lsa, `BASE_URL` domenini u yerga qo'shing. Ikonkalar yuklanmasa ham ilova ishlayveradi, ularning o'rnida oddiy belgilar (+, −, ✓) chiqadi.

## 5. Testlar

```bash
pip install -r requirements-dev.txt
python -m pytest
```
