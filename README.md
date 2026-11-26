# Telegram Stars Topshiriqlar Boti (Flask + Webhook)

**Texnologiyalar:** pyTelegramBotAPI (telebot) · Flask · Gunicorn · PostgreSQL (psycopg2)
Bot **webhook** orqali ishlaydi (polling yo'q) — Render.com Web Service uchun tayyor.

## Render.com'ga joylash (qadamma-qadam)

1. Loyihani GitHub'ga yuklang (`.env` yuklanmasin — `.gitignore`da bor).
2. Render → **New → Blueprint** → repozitoriyni tanlang. `render.yaml` PostgreSQL va Web Service'ni o'zi yaratadi.
   (Qo'lda yaratsangiz: Web Service, **Start Command:** `gunicorn app:flask_app -c gunicorn.conf.py`, Health Check Path: `/health`, `PYTHON_VERSION=3.11.9`, va alohida PostgreSQL → `DATABASE_URL`.)
3. **Environment** bo'limida kiriting:

| O'zgaruvchi | Tavsif |
|---|---|
| `BOT_TOKEN` | @BotFather dan token |
| `ADMIN_ID` | Sizning Telegram ID raqamingiz |
| `DATABASE_URL` | PostgreSQL manzili (Blueprint o'zi qo'yadi) |
| `WEBHOOK_URL` | Servis manzili, masalan `https://stars-tasks-bot.onrender.com` (bo'sh qoldirsangiz Render bergan `RENDER_EXTERNAL_URL` avtomatik olinadi) |
| `WEBHOOK_SECRET` | Ixtiyoriy; bo'sh bo'lsa `BOT_TOKEN`dan avtomatik yasaladi (faqat `A-Z a-z 0-9 _ -`) |
| `START_WAIT_SECONDS` | START vazifasida kutish (standart 15) |
| `KEEPALIVE` | `0` — o'zini-o'zi ping qilishni o'chiradi (standart `1`) |

4. **Deploy**. Ishga tushganda bot o'zi `setWebhook` qiladi — logda
   `Webhook o'rnatildi` yozuvi chiqadi. Qo'lda hech narsa qilish shart emas.
5. Botga `/start`, adminga `/admin` yuboring.

## Imkoniyatlar

- Vazifalar (kanal / START) — admin har bir vazifa uchun alohida mukofot belgilaydi
- 🎁 Kunlik bonus (standart 0.3 ⭐, Toshkent vaqti bilan har kuni 00:00 da yangilanadi; admin sozlamalarda o'zgartiradi)
- 💸 Pul yechish — sovg'a ro'yxatidan tanlanadi (💝🧸 15, 🎁🌹 25, 🎂💐🚀🍾 50, 🏆💍💎 100 ⭐), qabul qiluvchi @username kiritiladi; admin arizani tasdiqlab, sovg'ani qo'lda yuboradi
- 🆔 Mening ID — foydalanuvchi o'z Telegram ID sini ko'radi
- Admin: 👥 foydalanuvchilar ro'yxati (sahifalab), 📣 hammaga xabar yuborish (matn/rasm/video), statistika, balans boshqaruvi

Eslatma: yangilangandan so'ng foydalanuvchilar yangi tugmalarni ko'rishi uchun botga `/start` yuborishi kerak.

## Tekshirish

- `https://SIZNING-URL/health` → `{"status":"ok","db":"ok"}`
- Webhook holati: `https://api.telegram.org/bot<TOKEN>/getWebhookInfo` — `url` to'g'ri va `last_error_message` bo'sh bo'lishi kerak.

## Muhim eslatmalar

- **Free reja:** 15 daqiqa trafik bo'lmasa Render servisni uxlatadi. Kod har 10 daqiqada o'z `/health` manzilini ping qiladi, bu odatda uyg'oq tutadi. To'liq ishonchli 24/7 uchun pullik reja yoki tashqi monitor (UptimeRobot, `/health`) qo'shing.
- `workers = 1` o'zgartirilmasin (holat, keshlar va webhook o'rnatish bitta jarayonda).
- Suhbat holatlari va START vazifasi vaqti bazada saqlanadi — servis restart bo'lsa ham yo'qolmaydi.
- Bot majburiy kanallarda va kanal vazifalarida **admin** bo'lishi shart.

## Lokal sinov

```bash
pip install -r requirements.txt
cp .env.example .env     # to'ldiring
python app.py            # webhook'siz, faqat Flask; webhook uchun ochiq HTTPS (masalan ngrok) kerak,
                         # uni WEBHOOK_URL ga yozing
```

## Fayl tuzilmasi

```
app.py            — Flask + webhook, navbat, keep-alive
config.py         — sozlamalar (WEBHOOK_URL / RENDER_EXTERNAL_URL)
database.py       — psycopg2 havzasi (uzilishlarga chidamli)
migrations.py     — jadvallar (0001–0003)
states.py         — suhbat holatlari (DB)
gifts.py          — sovg'alar ro'yxati va narxlari
services.py       — barcha DB amallari
middleware.py     — obuna tekshirish, flood control
handlers_user.py  — foydalanuvchi handlerlari
handlers_admin.py — admin handlerlari
utils.py          — yordamchi funksiyalar
```

## Bot buyruqlari

`/start` · `/cancel` · `/admin` (faqat admin)
