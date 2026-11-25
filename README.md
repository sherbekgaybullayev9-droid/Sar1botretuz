# Telegram Stars Topshiriqlar Boti (Flask + Webhook + Render.com)

aiogram 3 · Flask · Gunicorn · PostgreSQL · SQLAlchemy (async) · Alembic. **Polling yo'q — faqat Webhook.**

## Imkoniyatlar
- Majburiy kanallarga obuna (admin boshqaradi)
- Kanalga obuna vazifalari (avtomatik tekshiruv: `getChatMember`)
- Botga START vazifalari
- Har bir vazifa uchun standart 0.5 ⭐ (har bir vazifa uchun alohida o'zgartiriladi)
- Minimal yechish 15 ⭐ (admin sozlamalarida o'zgartiriladi)
- Admin panel `/admin`: vazifa qo'shish/o'chirish/to'xtatish, mukofot, balans, arizalar, statistika
- Pul yechish arizalari + adminga xabarnoma (tasdiqlash/rad etish; rad etilsa balans qaytadi)

## Fayllar
| Fayl | Vazifasi |
|---|---|
| `app.py` | Flask (`/`, `/health`, `/webhook`) + aiogram integratsiyasi |
| `gunicorn.conf.py` | 1 worker, 8 thread, timeout 120 |
| `database.py`, `services.py` | Modellar va baza amallari |
| `migrations.py` | Alembic migratsiyalari (ishga tushganda avtomatik bajariladi) |
| `handlers_user.py`, `handlers_admin.py` | Foydalanuvchi va admin handlerlari |
| `render.yaml`, `Procfile` | Render konfiguratsiyasi |

## Muhim: nega 1 worker?
Bot, Dispatcher va asyncio loop jarayon ichida bir marta ishga tushadi. Bir nechta worker bo'lsa har biri alohida
bot nusxasi va alohida FSM xotirasini yaratadi. Parallellik `threads = 8` orqali ta'minlanadi. Migratsiya
PostgreSQL advisory lock bilan himoyalangan.

## Deploy (Render.com)

### 0. Tayyorgarlik
1. @BotFather → `/newbot` → **BOT_TOKEN** oling.
2. @userinfobot orqali o'zingizning **ADMIN_ID** raqamingizni bilib oling.
3. Botni barcha majburiy/vazifa kanallariga **admin** qiling.

### 1–2. GitHub
```bash
git init
git add .
git commit -m "Telegram Stars bot"
git branch -M main
git remote add origin https://github.com/<username>/<repo>.git
git push -u origin main
```
(`.env` GitHub'ga yuklanmaydi — `.gitignore`da bor.)

### 3. PostgreSQL yaratish
Render → **New +** → **PostgreSQL** → nom bering → Create. Tayyor bo'lgach **Internal Database URL** ni nusxalang.

### 4–5. Web Service yaratish va GitHub ulash
Render → **New +** → **Web Service** → GitHub repo'ni tanlang. Runtime: **Python 3**.
(Yoki **New + → Blueprint** orqali `render.yaml` ni ishlating — baza va servis birdan yaratiladi.)

### 6. Build Command
```
pip install -r requirements.txt
```

### 7. Start Command
```
gunicorn app:app -c gunicorn.conf.py
```
Health Check Path: `/health`

### 8. Environment Variables
| Kalit | Qiymat |
|---|---|
| `BOT_TOKEN` | BotFather tokeni |
| `ADMIN_ID` | Sizning Telegram ID |
| `WEBHOOK_SECRET` | Ixtiyoriy uzun maxfiy so'z |
| `DATABASE_URL` | Internal Database URL (`postgres://...` formati ham bo'ladi, avtomatik o'giriladi) |
| `PYTHON_VERSION` | `3.11.9` |
| `WEBHOOK_URL` | Ixtiyoriy. Berilmasa Render'ning `RENDER_EXTERNAL_URL` ishlatiladi |

`PORT` ni Render o'zi beradi.

### 9. Deploy
**Create Web Service** → loglarni kuzating. Muvaffaqiyatli bo'lsa logda shunday yozuv chiqadi:
`Webhook o'rnatildi: https://<nom>.onrender.com/webhook`

### 10. Tekshirish
- `https://<nom>.onrender.com/` → `{"status":"ok",...}`
- `https://<nom>.onrender.com/health` → `{"db":"ok","status":"ok"}`
- `https://api.telegram.org/bot<TOKEN>/getWebhookInfo` → `url` to'g'ri va `last_error_message` yo'q
- Botga `/start`, keyin `/admin` yuboring.

## Admin: birinchi sozlash
1. `/admin` → **Majburiy kanallar** → kanal qo'shing.
2. **Kanal vazifasi** / **START vazifasi** qo'shing.
3. **Sozlamalar** orqali standart mukofot va minimal yechishni o'zgartiring.

## Bilish kerak
- **START vazifasi:** Telegram Bot API boshqa botga START bosilganini tekshirishga imkon bermaydi. Shuning uchun
  foydalanuvchi vazifani ochgandan keyin `START_WAIT_SECONDS` (standart 15 soniya) o'tgach mukofot beriladi. Bu
  haqiqiy tasdiq emas; to'liq tekshiruv kerak bo'lsa, nishon bot sizniki bo'lib, u sizning API'ngizga xabar berishi kerak.
- **FSM holati** (masalan, ariza yozish jarayoni) xotirada saqlanadi — qayta ishga tushganda foydalanuvchi jarayonni
  boshidan boshlaydi. Balans, vazifalar, arizalar esa PostgreSQL'da doimiy saqlanadi.
- **Free reja:** Render Free Web Service 15 daqiqa so'rovsiz qolsa uxlaydi (birinchi so'rovda uyg'onadi). Haqiqiy 24/7
  uchun pullik reja yoki `/health` ni UptimeRobot kabi xizmat bilan har 5 daqiqada chaqirib turing. Free PostgreSQL
  30 kundan keyin o'chadi — doimiy ishlash uchun pullik rejaga o'ting.
- **Lokal ishga tushirish:** `.env` yarating, `ngrok http 10000` bilan https manzil oling, `WEBHOOK_URL` ga yozing,
  `gunicorn app:app -c gunicorn.conf.py`.
