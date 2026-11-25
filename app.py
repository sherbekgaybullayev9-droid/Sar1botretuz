"""Flask + aiogram 3 (webhook). Render.com Web Service uchun.

Arxitektura: bitta Gunicorn worker (gthread). Jarayon ichida bitta fon thread'da asyncio loop
ishlaydi; Bot, Dispatcher va DB engine faqat shu loop'da ishlatiladi. Flask thread'lari
update'larni run_coroutine_threadsafe orqali shu loop'ga uzatadi.
"""
import encodings.idna  # noqa: F401  (idna codec'ni thread'lardan oldin yuklaydi)
import asyncio
import hmac
import logging
import threading

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Update
from flask import Flask, abort, jsonify, request

import config

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("app")

config.validate()

import services  # noqa: E402  (config tekshiruvidan keyin import qilinadi)
import handlers_admin as admin_handlers  # noqa: E402
import handlers_user as user_handlers  # noqa: E402
from middleware import SubscriptionMiddleware  # noqa: E402

# ---- Bot va Dispatcher: jarayonda faqat bir marta yaratiladi ----
bot = Bot(token=config.BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher(storage=MemoryStorage())
dp.message.outer_middleware(SubscriptionMiddleware())
dp.callback_query.outer_middleware(SubscriptionMiddleware())
dp.include_router(admin_handlers.router)   # admin birinchi
dp.include_router(user_handlers.router)

# ---- asyncio loop alohida thread'da ----
loop = asyncio.new_event_loop()


def _run_loop() -> None:
    asyncio.set_event_loop(loop)
    loop.run_forever()


threading.Thread(target=_run_loop, name="aiogram-loop", daemon=True).start()
ready = threading.Event()
state = {"step": "boshlanmoqda", "attempt": 0, "error": None}


async def _startup() -> None:
    attempt = 0
    while True:
        attempt += 1
        state["attempt"] = attempt
        try:
            state["step"] = "migratsiya"
            await services.run_startup_migrations()
            state["step"] = "webhook"
            await bot.set_webhook(
                url=config.webhook_url(),
                secret_token=config.WEBHOOK_SECRET_TOKEN,
                allowed_updates=dp.resolve_used_update_types(),
                drop_pending_updates=False,
            )
            info = await bot.get_webhook_info()
            me = await bot.me()
            log.info("Webhook o'rnatildi: %s (bot @%s, kutilayotgan update: %s, xato: %s)",
                     info.url, me.username, info.pending_update_count, info.last_error_message)
            ready.set()
            state["step"] = "tayyor"
            state["error"] = None
            return
        except Exception as e:
            state["error"] = f"{type(e).__name__}: {e}"[:300]
            log.exception("Ishga tushirishda xato (urinish %s), qayta uriniladi", attempt)
            await asyncio.sleep(min(30, 2 * attempt))


def _startup_done(fut) -> None:
    if not fut.cancelled() and fut.exception():
        log.error("Startup to'xtadi: %s", fut.exception())


asyncio.run_coroutine_threadsafe(_startup(), loop).add_done_callback(_startup_done)


def _update_done(fut) -> None:
    if fut.cancelled():
        return
    exc = fut.exception()
    if exc:
        log.error("Update'ni qayta ishlashda xato", exc_info=exc)


# ---- Flask ----
app = Flask(__name__)


@app.get("/")
def index():
    return jsonify(status="ok", service="Telegram Stars topshiriqlar boti", webhook_ready=ready.is_set())


@app.get("/health")
def health():
    if not ready.is_set():
        return jsonify(status="starting", **state), 200
    try:
        asyncio.run_coroutine_threadsafe(services.db_ping(), loop).result(timeout=5)
    except Exception:
        log.exception("Health: bazaga ulanishda xato")
        return jsonify(status="degraded", db="error"), 503
    return jsonify(status="ok", db="ok"), 200


@app.post("/webhook")
def webhook():
    token = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    if not hmac.compare_digest(token.encode(), config.WEBHOOK_SECRET_TOKEN.encode()):
        abort(403)
    if not ready.is_set():
        return "starting", 503  # Telegram keyinroq qayta yuboradi
    data = request.get_json(silent=True, force=True)
    if not isinstance(data, dict):
        abort(400)
    try:
        update = Update.model_validate(data, context={"bot": bot})
    except Exception:
        log.exception("Noto'g'ri update")
        abort(400)
    asyncio.run_coroutine_threadsafe(dp.feed_update(bot, update), loop).add_done_callback(_update_done)
    return "ok", 200
