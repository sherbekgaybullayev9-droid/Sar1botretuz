"""
Obuna tekshirish va flood-control yordamchi funksiyalari.
telebot middleware o'rniga handler ichida chaqiriladigan funksiyalar.
"""
import logging
import time
from typing import Optional

import telebot
from telebot import types

import config
import services
from utils import is_member, esc

log = logging.getLogger("middleware")

# Obuna keshi: user_id -> monotonic vaqt
_sub_cache: dict[int, float] = {}
CACHE_SECONDS = 60
MAX_CACHE = 10_000

# Flood control: user_id -> [timestamp, ...]
_flood: dict[int, list] = {}


def flood_check(uid: int) -> bool:
    """1 soniyada 2 martadan ko'p → True (bloklash kerak)."""
    now = time.time()
    arr = _flood.setdefault(uid, [])
    arr[:] = [t for t in arr if now - t < 1]
    arr.append(now)
    return len(arr) > 2


def missing_channels(bot: telebot.TeleBot, user_id: int) -> list:
    missing = []
    for ch in services.list_required():
        if not is_member(bot, ch["chat"], user_id, on_error=True):
            missing.append(ch)
    return missing


def check_subscription(bot: telebot.TeleBot, uid: int) -> bool:
    if uid == config.ADMIN_ID:
        return True
    now = time.monotonic()
    if _sub_cache.get(uid, 0) > now:
        return True
    if missing_channels(bot, uid):
        _sub_cache.pop(uid, None)
        return False
    if len(_sub_cache) >= MAX_CACHE:
        expired = [k for k, v in _sub_cache.items() if v < now]
        for k in expired:
            del _sub_cache[k]
    _sub_cache[uid] = now + CACHE_SECONDS
    return True


def invalidate_cache(uid: int) -> None:
    _sub_cache.pop(uid, None)


def subscribe_markup(channels: list) -> types.InlineKeyboardMarkup:
    kb = types.InlineKeyboardMarkup(row_width=1)
    for ch in channels:
        kb.add(types.InlineKeyboardButton(f"📢 {ch['title']}", url=ch["url"]))
    kb.add(types.InlineKeyboardButton("✅ Tekshirish", callback_data="sub:check"))
    return kb


def send_subscription_required(bot: telebot.TeleBot, chat_id: int, uid: int) -> None:
    missing = missing_channels(bot, uid)
    if not missing:
        return
    bot.send_message(
        chat_id,
        "🔒 Botdan foydalanish uchun quyidagi kanallarga obuna bo'ling, "
        "so'ng «✅ Tekshirish» tugmasini bosing:",
        reply_markup=subscribe_markup(missing),
    )
