"""
Flask + Telegram webhook (telebot). Render.com Web Service uchun.

Ishga tushirish:  gunicorn app:flask_app -c gunicorn.conf.py

Oqim:
  Telegram --POST--> /webhook/<secret>  --> navbat (thread pool) --> handlerlar
Webhook so'rovi darhol 200 qaytaradi, shuning uchun Telegram qayta yubormaydi.
"""
import hmac
import logging
import threading
import time
import urllib.request
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor

import telebot
from flask import Flask, abort, jsonify, request
from telebot import types

import config
import migrations
from database import db_ping, init_pool

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
log = logging.getLogger("app")

# ---- Sozlamalar, DB, migratsiyalar ----
config.validate()
init_pool()
migrations.upgrade()

# ---- Bot (threaded=False: handlerlar o'zimizning thread pool'da ishlaydi) ----
bot = telebot.TeleBot(config.BOT_TOKEN, parse_mode="HTML", threaded=False)

import handlers_admin as admin_handlers  # noqa: E402
import handlers_join as join_handlers      # noqa: E402
import handlers_user as user_handlers    # noqa: E402

admin_handlers.register(bot)   # admin birinchi (filtr ustunligi)
user_handlers.register(bot)
join_handlers.register(bot)

ALLOWED_UPDATES = ["message", "callback_query", "chat_join_request"]

# ---- Yangilanishlarni qayta ishlash ----
_executor = ThreadPoolExecutor(max_workers=8, thread_name_prefix="upd")
_user_locks = [threading.Lock() for _ in range(32)]  # bir foydalanuvchi — ketma-ket
_seen: "OrderedDict[int, None]" = OrderedDict()      # takroriy update_id'lardan himoya
_seen_lock = threading.Lock()


def _is_duplicate(update_id: int) -> bool:
    with _seen_lock:
        if update_id in _seen:
            return True
        _seen[update_id] = None
        while len(_seen) > 2000:
            _seen.popitem(last=False)
    return False


def _update_uid(update: types.Update) -> int:
    if update.message and update.message.from_user:
        return update.message.from_user.id
    if update.callback_query and update.callback_query.from_user:
        return update.callback_query.from_user.id
    if update.chat_join_request and update.chat_join_request.from_user:
        return update.chat_join_request.from_user.id
    return 0


def _process(update: types.Update) -> None:
    uid = _update_uid(update)
    lock = _user_locks[uid % len(_user_locks)]
    try:
        with lock:
            bot.process_new_updates([update])
    except Exception:
        log.exception("Update #%s ni qayta ishlashda xato", update.update_id)


# ---- Flask ----
flask_app = Flask(__name__)


@flask_app.get("/")
def index():
    return jsonify(status="ok", service="Telegram Stars topshiriqlar boti")


@flask_app.get("/health")
def health():
    # Doim 200: DB vaqtincha uzilsa Render servisni qayta ishga tushirib yubormasin
    return jsonify(status="ok", db="ok" if db_ping() else "error")


@flask_app.post(config.WEBHOOK_PATH)
def webhook():
    token = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    if not hmac.compare_digest(token, config.WEBHOOK_SECRET):
        abort(403)
    try:
        update = types.Update.de_json(request.get_data(as_text=True))
    except Exception:
        abort(400)
    if update is None:
        abort(400)
    if not _is_duplicate(update.update_id):
        _executor.submit(_process, update)
    return "ok", 200


# ---- Webhook'ni o'rnatish va keep-alive (fon threadlarida) ----
def _setup_webhook() -> None:
    if not config.BASE_URL:
        log.error("WEBHOOK_URL / RENDER_EXTERNAL_URL topilmadi — webhook o'rnatilmadi!")
        return
    url = config.BASE_URL + config.WEBHOOK_PATH
    for attempt in range(1, 11):
        try:
            bot.set_webhook(
                url=url,
                secret_token=config.WEBHOOK_SECRET,
                allowed_updates=ALLOWED_UPDATES,
                max_connections=40,
            )
            info = bot.get_webhook_info()
            log.info("Webhook o'rnatildi: %s (pending=%s, last_error=%s)",
                     config.BASE_URL + "/webhook/***", info.pending_update_count, info.last_error_message)
            return
        except Exception as e:
            log.error("set_webhook xatosi (%s/10): %s", attempt, e)
            time.sleep(min(5 * attempt, 30))
    log.error("Webhook o'rnatib bo'lmadi. BOT_TOKEN va WEBHOOK_URL'ni tekshiring.")


def _keepalive() -> None:
    """Render free rejada 15 daqiqa trafik bo'lmasa servis uxlaydi — o'zimizni uyg'oq tutamiz."""
    url = config.BASE_URL + "/health"
    time.sleep(60)
    while True:
        try:
            urllib.request.urlopen(url, timeout=20).read()
        except Exception as e:
            log.warning("Keep-alive xatosi: %s", e)
        time.sleep(600)


def _auto_backup() -> None:
    """Har 24 soatda backup'ni adminga yuboradi (Render'ning bepul bazasi o'chib ketishidan himoya)."""
    import backup
    import services
    time.sleep(120)
    while True:
        try:
            last = float(services.get_setting("last_backup_ts", "0"))
            if time.time() - last >= 86400:
                backup.send_backup(bot, config.ADMIN_ID, auto=True)
                services.set_setting("last_backup_ts", str(int(time.time())))
        except Exception as e:
            log.warning("Avto-backup xatosi: %s", e)
        time.sleep(3600)


_started = False
_start_lock = threading.Lock()


def _start_background() -> None:
    global _started
    with _start_lock:
        if _started:
            return
        _started = True
    threading.Thread(target=_setup_webhook, daemon=True, name="webhook-setup").start()
    if config.BASE_URL and config.KEEPALIVE:
        threading.Thread(target=_keepalive, daemon=True, name="keepalive").start()
    if config.AUTO_BACKUP:
        threading.Thread(target=_auto_backup, daemon=True, name="auto-backup").start()


_start_background()

if __name__ == "__main__":
    # Lokal sinov uchun (Renderda gunicorn ishlatiladi)
    flask_app.run(host="0.0.0.0", port=config.PORT)
