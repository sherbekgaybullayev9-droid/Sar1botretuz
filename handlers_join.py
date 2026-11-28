"""
Yopiq kanallar: foydalanuvchi "ariza bilan qo'shilish" havolasini bosganda
bot arizani avtomatik tasdiqlaydi (faqat ro'yxatdan o'tgan kanallar uchun).
Bot kanalda admin bo'lishi va "Havola orqali taklif qilish" huquqiga ega bo'lishi kerak.
"""
import logging

import telebot

import services
from utils import esc

log = logging.getLogger("join")


def register(bot: telebot.TeleBot) -> None:
    @bot.chat_join_request_handler()
    def on_join_request(req):
        chat_id = req.chat.id
        user_id = req.from_user.id
        try:
            if not services.is_registered_chat(str(chat_id)):
                return  # begona kanal — tegmaymiz
            bot.approve_chat_join_request(chat_id, user_id)
            log.info("Ariza tasdiqlandi: chat=%s user=%s", chat_id, user_id)
        except Exception as e:
            log.warning("Arizani tasdiqlab bo'lmadi (chat=%s user=%s): %s", chat_id, user_id, e)
            return
        target = getattr(req, "user_chat_id", None) or user_id
        try:
            bot.send_message(
                target,
                f"✅ <b>{esc(req.chat.title or 'Kanal')}</b> kanaliga arizangiz tasdiqlandi.\n"
                f"Botga qaytib davom eting.",
            )
        except Exception:
            pass  # foydalanuvchi botni boshlamagan bo'lishi mumkin
