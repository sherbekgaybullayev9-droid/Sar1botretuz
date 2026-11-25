import html
import logging
import re
from decimal import Decimal, InvalidOperation
from typing import Optional

from aiogram.exceptions import TelegramAPIError, TelegramBadRequest

log = logging.getLogger("utils")

esc = html.escape


def stars(value) -> str:
    s = f"{Decimal(value):.2f}".rstrip("0").rstrip(".")
    return f"{s} ⭐"


def parse_amount(text: str, allow_negative: bool = False) -> Optional[Decimal]:
    try:
        d = Decimal((text or "").strip().replace(",", "."))
    except InvalidOperation:
        return None
    if not d.is_finite() or d == 0 or (d < 0 and not allow_negative) or abs(d) > Decimal("1000000"):
        return None
    return d.quantize(Decimal("0.01"))


def chat_ref(value: str):
    v = str(value).strip()
    return int(v) if v.lstrip("-").isdigit() else v


def normalize_channel_input(text: str) -> Optional[str]:
    t = (text or "").strip()
    if not t:
        return None
    m = re.match(r"^(?:https?://)?t\.me/(.+)$", t)
    if m:
        name = m.group(1).split("?")[0].strip("/")
        if name.startswith("+") or name.startswith("joinchat"):
            return None  # yopiq havola orqali kanalni aniqlab bo'lmaydi
        return "@" + name
    if t.lstrip("-").isdigit() or t.startswith("@"):
        return t
    return "@" + t


async def is_member(bot, chat, user_id: int, *, on_error: bool) -> bool:
    """Foydalanuvchi kanal/guruh a'zosimi? API xatosida on_error qaytariladi."""
    try:
        m = await bot.get_chat_member(chat_ref(chat), user_id)
    except TelegramAPIError as e:
        log.warning("get_chat_member(%s, %s) xato: %s", chat, user_id, e)
        return on_error
    status = getattr(m.status, "value", m.status)
    return status in {"creator", "administrator", "member"} or (
        status == "restricted" and bool(getattr(m, "is_member", False))
    )


async def channel_url(bot, chat) -> Optional[str]:
    if chat.username:
        return f"https://t.me/{chat.username}"
    if getattr(chat, "invite_link", None):
        return chat.invite_link
    try:
        return await bot.export_chat_invite_link(chat.id)
    except TelegramAPIError:
        return None


async def safe_edit(cb, text: str, kb=None) -> None:
    try:
        await cb.message.edit_text(text, reply_markup=kb)
    except TelegramBadRequest as e:
        if "not modified" not in str(e).lower():
            await cb.message.answer(text, reply_markup=kb)
