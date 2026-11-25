import logging
import time

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

import config
import services
from utils import esc

log = logging.getLogger("middleware")

_ok_until = {}          # obuna tekshiruvi keshi: user_id -> monotonic vaqt
CACHE_SECONDS = 60
MAX_CACHE = 10_000      # kesh hajmi chegarasi


def subscribe_markup(channels):
    kb = InlineKeyboardBuilder()
    for ch in channels:
        kb.row(InlineKeyboardButton(text=f"📢 {ch.title}", url=ch.url))
    kb.row(InlineKeyboardButton(text="✅ Tekshirish", callback_data="sub:check"))
    return kb.as_markup()


class SubscriptionMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        user = data.get("event_from_user")
        if user is None or user.is_bot:
            return await handler(event, data)

        await services.upsert_user(user)

        if user.id == config.ADMIN_ID:
            return await handler(event, data)
        if isinstance(event, CallbackQuery) and event.data == "sub:check":
            return await handler(event, data)
        if _ok_until.get(user.id, 0) > time.monotonic():
            return await handler(event, data)

        missing = await services.missing_channels(data["bot"], user.id)
        if not missing:
            if len(_ok_until) >= MAX_CACHE:
                now = time.monotonic()
                expired = [k for k, v in _ok_until.items() if v < now]
                for k in expired:
                    del _ok_until[k]
            _ok_until[user.id] = time.monotonic() + CACHE_SECONDS
            return await handler(event, data)

        _ok_until.pop(user.id, None)
        text = "🔒 Botdan foydalanish uchun quyidagi kanallarga obuna bo'ling, so'ng «✅ Tekshirish» tugmasini bosing:"
        if isinstance(event, CallbackQuery):
            await event.answer("Avval kanallarga obuna bo'ling", show_alert=True)
            if event.message:
                await event.message.answer(text, reply_markup=subscribe_markup(missing))
        else:
            await event.answer(text, reply_markup=subscribe_markup(missing))
        return None
