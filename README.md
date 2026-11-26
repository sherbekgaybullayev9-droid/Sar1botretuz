# Telegram Stars Topshiriqlar Boti

**Texnologiyalar:** pyTelegramBotAPI (telebot) · Flask · PostgreSQL (psycopg2)

---

## Ishga tushirish

```bash
pip install -r requirements.txt
cp .env.example .env   # qiymatlarni to'ldiring
python app.py
```

## Muhit o'zgaruvchilari

| O'zgaruvchi | Tavsif |
|---|---|
| `BOT_TOKEN` | @BotFather dan olingan token |
| `ADMIN_ID` | Sizning Telegram ID raqamingiz |
| `DATABASE_URL` | PostgreSQL ulanish manzili (`postgres://...`) |
| `PORT` | Flask port (standart: 10000) |
| `START_WAIT_SECONDS` | START vazifasida kutish vaqti (standart: 15) |

## Render.com ga joylash

1. `render.yaml` asosida PostgreSQL va Web Service avtomatik yaratiladi.
2. `BOT_TOKEN` va `ADMIN_ID` ni Environment Variables ga qo'shing.
3. Deploy tugmasini bosing.

## Fayl tuzilmasi

```
app.py            — asosiy kirish nuqtasi (Flask + polling)
config.py         — sozlamalar
database.py       — psycopg2 ulanish havzasi
migrations.py     — jadval yaratish
services.py       — barcha DB amallari
middleware.py     — obuna tekshirish, flood control
handlers_user.py  — foydalanuvchi handlerlari
handlers_admin.py — admin handlerlari
utils.py          — yordamchi funksiyalar
```

## Bot buyruqlari

- `/start` — botni boshlash
- `/cancel` — amalni bekor qilish
- `/admin` — admin panel (faqat adminlar uchun)
