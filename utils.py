import html
import logging
import re
from decimal import Decimal, InvalidOperation
from typing import Optional

import telebot

log = logging.getLogger("utils")

esc = html.escape


def stars(value) -> str:
    s = f"{Decimal(str(value)):.2f}".rstrip("0").rstrip(".")
    return f"{s} ⭐"


def parse_amount(text: str, allow_negative: bool = False) -> Optional[Decimal]:
    try:
        d = Decimal((text or "").strip().replace(",", "."))
    except InvalidOperation:
        return None
    if not d.is_finite() or d == 0 or (d < 0 and not allow_negative) or abs(d) > Decimal("1000000"):
        return None
    return d.quantize(Decimal("0.01"))


def normalize_channel_input(text: str) -> Optional[str]:
    t = (text or "").strip()
    if not t:
        return None
    m = re.match(r"^(?:https?://)?t\.me/(.+)$", t)
    if m:
        name = m.group(1).split("?")[0].strip("/")
        if name.startswith("+") or name.startswith("joinchat"):
            return None
        return "@" + name
    if t.lstrip("-").isdigit() or t.startswith("@"):
        return t
    return "@" + t


def chat_ref(value: str):
    v = str(value).strip()
    return int(v) if v.lstrip("-").isdigit() else v


def is_member(bot: telebot.TeleBot, chat, user_id: int, on_error: bool = True) -> bool:
    try:
        member = bot.get_chat_member(chat_ref(str(chat)), user_id)
        status = member.status
        return status in ("creator", "administrator", "member", "restricted")
    except Exception as e:
        log.warning("get_chat_member(%s, %s) xato: %s", chat, user_id, e)
        return on_error


def channel_url(bot: telebot.TeleBot, chat) -> Optional[str]:
    """
    Ochiq kanal: https://t.me/username.
    Yopiq kanal: "ariza bilan qo'shilish" havolasi — bot arizalarni avtomatik tasdiqlaydi.
    """
    if getattr(chat, "username", None):
        return f"https://t.me/{chat.username}"
    try:
        link = bot.create_chat_invite_link(chat.id, name="Stars bot", creates_join_request=True)
        if getattr(link, "invite_link", None):
            return link.invite_link
    except Exception as e:
        log.warning("Ariza havolasini yaratib bo'lmadi (%s): %s", chat.id, e)
    if getattr(chat, "invite_link", None):
        return chat.invite_link
    try:
        return bot.export_chat_invite_link(chat.id)
    except Exception:
        return None


def forwarded_chat(message):
    """Forward qilingan xabar kanaldan bo'lsa, o'sha kanal (chat) obyektini qaytaradi."""
    origin = getattr(message, "forward_origin", None)
    if origin is not None:
        chat = getattr(origin, "chat", None) or getattr(origin, "sender_chat", None)
        if chat is not None:
            return chat
    return getattr(message, "forward_from_chat", None)


def safe_edit(bot: telebot.TeleBot, call, text: str, kb=None) -> None:
    """Xabarni tahrirlaydi; imkoni bo'lmasa yangisini yuboradi."""
    try:
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=kb)
    except Exception as e:
        if "message is not modified" in str(e):
            return
        try:
            bot.send_message(call.message.chat.id, text, reply_markup=kb)
        except Exception:
            pass
