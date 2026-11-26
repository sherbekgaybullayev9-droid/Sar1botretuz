"""
Flask keep-alive + telebot polling.
Flask alohida daemon thread'da ishlaydi; bot polling asosiy threadda.

Render.com uchun: startCommand = gunicorn app:flask_app -c gunicorn.conf.py
Lekin gunicorn + polling birga ishlamaydi, shu sababli to'g'ridan-to'g'ri:
  python app.py
yoki Procfile: web: python app.py
"""
import logging
import threading
import time

import telebot
from flask import Flask, jsonify

import config
import migrations
from database import db_ping, init_pool

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
log = logging.getLogger("app")

# ---- Sozlamalar tekshiruvi ----
config.validate()

# ---- DB ulanish havzasi va migratsiyalar ----
init_pool()
migrations.upgrade()

# ---- Bot ----
bot = telebot.TeleBot(config.BOT_TOKEN, parse_mode="HTML")

# ---- Handlerlarni ro'yxatdan o'tkazish ----
import handlers_admin as admin_handlers  # noqa: E402
import handlers_user  as user_handlers   # noqa: E402

admin_handlers.register(bot)   # admin birinchi (filtr ustunligi)
user_handlers.register(bot)

# ---- Flask ----
flask_app = Flask(__name__)


@flask_app.get("/")
def index():
    return jsonify(status="ok", service="Telegram Stars topshiriqlar boti")


@flask_app.get("/health")
def health():
    ok = db_ping()
    return jsonify(status="ok" if ok else "degraded", db="ok" if ok else "error"), 200 if ok else 503


# ---- Ishga tushirish ----
def run_flask() -> None:
    flask_app.run(host="0.0.0.0", port=config.PORT)


if __name__ == "__main__":
    flask_thread = threading.Thread(target=run_flask, daemon=True, name="flask")
    flask_thread.start()
    log.info("Flask server %s-portda ishga tushdi.", config.PORT)
    log.info("Bot polling boshlandi...")

    while True:
        try:
            bot.infinity_polling(timeout=10, long_polling_timeout=5)
        except Exception as e:
            log.error("Polling xatosi, 5 soniyadan keyin qayta urinish: %s", e)
            time.sleep(5)
