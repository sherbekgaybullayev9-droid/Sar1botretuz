"""
Foydalanuvchi handlerlari (telebot, sinxron).
"""
import logging
import time
from decimal import Decimal

import telebot
from telebot import types

import config
import services
from middleware import (check_subscription, flood_check, invalidate_cache,
                        missing_channels, send_subscription_required, subscribe_markup)
from utils import esc, is_member, parse_amount, stars

log = logging.getLogger("user")

BTN_TASKS = "📋 Vazifalar"
BTN_BAL   = "💰 Balans"
BTN_WD    = "💸 Pul yechish"
BTN_HELP  = "ℹ️ Yordam"

# START vazifasi: (user_id, task_id) -> monotonic vaqt
_opened: dict[tuple, float] = {}

# Foydalanuvchi holatlari: user_id -> {"state": str, "data": dict}
user_states: dict[int, dict] = {}


# =====================================================================
# KLAVIATURALAR
# =====================================================================

def main_menu_kb() -> types.ReplyKeyboardMarkup:
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row(BTN_TASKS, BTN_BAL)
    kb.row(BTN_WD, BTN_HELP)
    return kb


def tasks_kb(task_list: list) -> types.InlineKeyboardMarkup:
    kb = types.InlineKeyboardMarkup(row_width=1)
    for t in task_list:
        icon = "📢" if t["kind"] == "channel" else "🤖"
        kb.add(types.InlineKeyboardButton(
            f"{icon} {t['title']} · +{stars(t['reward'])}",
            callback_data=f"task:{t['id']}",
        ))
    return kb


def task_detail_kb(task_id: int, task_url: str) -> types.InlineKeyboardMarkup:
    kb = types.InlineKeyboardMarkup(row_width=1)
    kb.add(types.InlineKeyboardButton("🔗 Ochish", url=task_url))
    kb.add(types.InlineKeyboardButton("✅ Tekshirish", callback_data=f"chk:{task_id}"))
    kb.add(types.InlineKeyboardButton("⬅️ Orqaga", callback_data="tasks:list"))
    return kb


def wd_confirm_kb(wid: int) -> types.InlineKeyboardMarkup:
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("✅ Tasdiqlash", callback_data=f"wd:ok:{wid}"),
        types.InlineKeyboardButton("❌ Rad etish",  callback_data=f"wd:no:{wid}"),
    )
    return kb


# =====================================================================
# HANDLERLARNI ROʻYXATDAN OʻTKAZISH
# =====================================================================

def register(bot: telebot.TeleBot) -> None:

    # ---- /start ----
    @bot.message_handler(commands=["start"])
    def cmd_start(message: types.Message):
        uid = message.from_user.id
        services.upsert_user(
            uid,
            message.from_user.username,
            (message.from_user.first_name or "") + " " + (message.from_user.last_name or ""),
        )
        user_states.pop(uid, None)
        if uid != config.ADMIN_ID and not check_subscription(bot, uid):
            send_subscription_required(bot, message.chat.id, uid)
            return
        reward = services.get_default_reward()
        min_w  = services.get_min_withdraw()
        bot.send_message(
            message.chat.id,
            f"👋 Salom, <b>{esc(message.from_user.first_name)}</b>!\n\n"
            f"Vazifalarni bajaring va ⭐ to'plang. Har bir vazifa uchun odatda {stars(reward)} beriladi.\n"
            f"Minimal yechish: {stars(min_w)}.",
            reply_markup=main_menu_kb(),
        )

    # ---- /cancel ----
    @bot.message_handler(commands=["cancel"])
    def cmd_cancel(message: types.Message):
        uid = message.from_user.id
        user_states.pop(uid, None)
        bot.send_message(message.chat.id, "Bekor qilindi.", reply_markup=main_menu_kb())

    # ---- Vazifalar ----
    @bot.message_handler(func=lambda m: m.text == BTN_TASKS)
    def show_tasks(message: types.Message):
        uid = message.from_user.id
        user_states.pop(uid, None)
        if not check_subscription(bot, uid):
            send_subscription_required(bot, message.chat.id, uid)
            return
        task_list = services.available_tasks(uid)
        if not task_list:
            bot.send_message(message.chat.id, "🎉 Hozircha yangi vazifa yo'q. Keyinroq qaytib keling!")
            return
        bot.send_message(
            message.chat.id,
            "📋 <b>Mavjud vazifalar</b>\nBittasini tanlang:",
            reply_markup=tasks_kb(task_list),
        )

    # ---- Balans ----
    @bot.message_handler(func=lambda m: m.text == BTN_BAL)
    def show_balance(message: types.Message):
        uid = message.from_user.id
        user_states.pop(uid, None)
        user  = services.get_user(uid)
        done  = services.completed_count(uid)
        min_w = services.get_min_withdraw()
        bal   = Decimal(str(user["balance"])) if user else Decimal("0")
        bot.send_message(
            message.chat.id,
            f"💰 <b>Balansingiz:</b> {stars(bal)}\n"
            f"✅ Bajarilgan vazifalar: {done}\n"
            f"💸 Minimal yechish: {stars(min_w)}",
        )

    # ---- Yordam ----
    @bot.message_handler(func=lambda m: m.text == BTN_HELP)
    def show_help(message: types.Message):
        user_states.pop(message.from_user.id, None)
        min_w = services.get_min_withdraw()
        bot.send_message(
            message.chat.id,
            f"ℹ️ <b>Yordam</b>\n\n"
            f"📋 Vazifalar — kanalga obuna bo'ling yoki botga START bosing.\n"
            f"💰 Balans — to'plangan ⭐.\n"
            f"💸 Pul yechish — {stars(min_w)} dan boshlab ariza yuboring.\n"
            f"/cancel — joriy amalni bekor qilish.",
        )

    # ---- Pul yechish ----
    @bot.message_handler(func=lambda m: m.text == BTN_WD)
    def wd_start(message: types.Message):
        uid = message.from_user.id
        user_states.pop(uid, None)
        if not check_subscription(bot, uid):
            send_subscription_required(bot, message.chat.id, uid)
            return
        user  = services.get_user(uid)
        min_w = services.get_min_withdraw()
        bal   = Decimal(str(user["balance"])) if user else Decimal("0")
        if bal < min_w:
            bot.send_message(
                message.chat.id,
                f"❌ Minimal yechish miqdori {stars(min_w)}. Sizning balansingiz: {stars(bal)}.",
            )
            return
        user_states[uid] = {"state": "wd_amount", "data": {}}
        bot.send_message(
            message.chat.id,
            f"💸 Qancha yechmoqchisiz? ({stars(min_w)} – {stars(bal)})\nBekor qilish: /cancel",
        )

    # ---- Umumiy matn (holat mashina) ----
    @bot.message_handler(func=lambda m: True, content_types=["text"])
    def handle_text(message: types.Message):
        uid = message.from_user.id
        if flood_check(uid):
            return
        st = user_states.get(uid)
        if st is None:
            return
        state = st["state"]
        data  = st["data"]

        # Pul yechish: miqdor
        if state == "wd_amount":
            amount = parse_amount(message.text)
            user   = services.get_user(uid)
            min_w  = services.get_min_withdraw()
            bal    = Decimal(str(user["balance"])) if user else Decimal("0")
            if amount is None or amount < min_w or amount > bal:
                bot.send_message(
                    message.chat.id,
                    f"❌ Noto'g'ri miqdor. {stars(min_w)} dan {stars(bal)} gacha son kiriting.",
                )
                return
            user_states[uid] = {"state": "wd_details", "data": {"amount": str(amount)}}
            bot.send_message(message.chat.id,
                             "✍️ Pul qabul qilish uchun ma'lumot yuboring (Telegram @username yoki rekvizit):")
            return

        # Pul yechish: rekvizit
        if state == "wd_details":
            amount  = Decimal(data["amount"])
            details = message.text.strip()[:500]
            wd = services.create_withdrawal(uid, amount, details)
            user_states.pop(uid, None)
            if wd is None:
                bot.send_message(message.chat.id, "❌ Balansingiz yetarli emas.", reply_markup=main_menu_kb())
                return
            wid = wd["id"]
            bot.send_message(
                message.chat.id,
                f"✅ Ariza #{wid} qabul qilindi: {stars(amount)}.\n"
                f"Admin ko'rib chiqadi, natija haqida xabar beramiz.",
                reply_markup=main_menu_kb(),
            )
            uname = f"@{message.from_user.username}" if message.from_user.username else "—"
            try:
                bot.send_message(
                    config.ADMIN_ID,
                    f"💸 <b>Yangi ariza #{wid}</b>\n"
                    f"👤 {esc(message.from_user.first_name)} ({uname})\n"
                    f"🆔 <code>{uid}</code>\n"
                    f"💰 Miqdor: {stars(amount)}\n"
                    f"📝 Ma'lumot: {esc(details)}",
                    reply_markup=wd_confirm_kb(wid),
                )
            except Exception:
                pass
            return

    # ---- Callback querylar ----
    @bot.callback_query_handler(func=lambda c: c.data == "sub:check")
    def cb_sub_check(call: types.CallbackQuery):
        uid = call.from_user.id
        missing = missing_channels(bot, uid)
        if missing:
            bot.answer_callback_query(call.id, "❌ Hali hamma kanallarga obuna bo'lmadingiz", show_alert=True)
            return
        invalidate_cache(uid)
        bot.answer_callback_query(call.id, "✅ Rahmat!")
        try:
            bot.delete_message(call.message.chat.id, call.message.message_id)
        except Exception:
            pass
        bot.send_message(call.message.chat.id,
                         "✅ Obuna tasdiqlandi. Marhamat, davom eting!",
                         reply_markup=main_menu_kb())

    @bot.callback_query_handler(func=lambda c: c.data == "tasks:list")
    def cb_tasks_list(call: types.CallbackQuery):
        bot.answer_callback_query(call.id)
        task_list = services.available_tasks(call.from_user.id)
        if not task_list:
            _safe_edit(bot, call, "🎉 Hozircha yangi vazifa yo'q. Keyinroq qaytib keling!")
            return
        _safe_edit(bot, call, "📋 <b>Mavjud vazifalar</b>\nBittasini tanlang:", tasks_kb(task_list))

    @bot.callback_query_handler(func=lambda c: c.data.startswith("task:"))
    def cb_task_open(call: types.CallbackQuery):
        uid     = call.from_user.id
        task_id = int(call.data.split(":")[1])
        task    = services.get_task(task_id)
        if task is None or not task["active"]:
            bot.answer_callback_query(call.id, "Bu vazifa mavjud emas yoki to'xtatilgan", show_alert=True)
            return
        if services.is_completed(uid, task_id):
            bot.answer_callback_query(call.id, "Bu vazifa allaqachon bajarilgan", show_alert=True)
            return
        bot.answer_callback_query(call.id)
        if task["kind"] == "channel":
            text = (f"📢 <b>{esc(task['title'])}</b>\n\n"
                    f"Kanalga obuna bo'ling, so'ng «✅ Tekshirish» tugmasini bosing.\n"
                    f"🎁 Mukofot: {stars(task['reward'])}")
        else:
            if len(_opened) > 5000:
                now = time.monotonic()
                for k in [k for k, v in _opened.items() if now - v > 300]:
                    del _opened[k]
            _opened[(uid, task_id)] = time.monotonic()
            text = (f"🤖 <b>{esc(task['title'])}</b>\n\n"
                    f"Botga o'ting va <b>START</b> bosing, so'ng bu yerga qaytib "
                    f"«✅ Tekshirish» tugmasini bosing "
                    f"(kamida {config.START_WAIT_SECONDS} soniyadan keyin).\n"
                    f"🎁 Mukofot: {stars(task['reward'])}")
        _safe_edit(bot, call, text, task_detail_kb(task_id, task["url"]))

    @bot.callback_query_handler(func=lambda c: c.data.startswith("chk:"))
    def cb_task_check(call: types.CallbackQuery):
        uid     = call.from_user.id
        task_id = int(call.data.split(":")[1])
        task    = services.get_task(task_id)
        if task is None or not task["active"]:
            bot.answer_callback_query(call.id, "Bu vazifa mavjud emas yoki to'xtatilgan", show_alert=True)
            return
        if services.is_completed(uid, task_id):
            bot.answer_callback_query(call.id, "Bu vazifa allaqachon bajarilgan", show_alert=True)
            return
        if task["kind"] == "channel":
            if not is_member(bot, task["target"], uid, on_error=False):
                bot.answer_callback_query(call.id, "❌ Siz hali kanalga obuna bo'lmagansiz", show_alert=True)
                return
        else:
            key = (uid, task_id)
            t0  = _opened.get(key)
            if t0 is None:
                _opened[key] = time.monotonic()
                bot.answer_callback_query(call.id,
                                          "Avval «🔗 Ochish» orqali botga o'tib START bosing.",
                                          show_alert=True)
                return
            left = config.START_WAIT_SECONDS - (time.monotonic() - t0)
            if left > 0:
                bot.answer_callback_query(
                    call.id,
                    f"⏳ Botga START bosganingizdan so'ng {int(left)+1} soniya kuting va qayta tekshiring.",
                    show_alert=True,
                )
                return
        reward = services.complete_task(uid, task_id)
        if reward is None:
            bot.answer_callback_query(call.id, "Bu vazifa allaqachon bajarilgan", show_alert=True)
            return
        _opened.pop((uid, task_id), None)
        bot.answer_callback_query(call.id, f"✅ +{stars(reward)} balansingizga qo'shildi!", show_alert=True)
        task_list = services.available_tasks(uid)
        if not task_list:
            _safe_edit(bot, call, "🎉 Barcha vazifalarni bajardingiz! Keyinroq yangilari qo'shiladi.")
            return
        _safe_edit(bot, call, "📋 <b>Mavjud vazifalar</b>\nBittasini tanlang:", tasks_kb(task_list))

    @bot.callback_query_handler(func=lambda c: c.data.startswith("wd:"))
    def cb_wd_resolve(call: types.CallbackQuery):
        if call.from_user.id != config.ADMIN_ID:
            bot.answer_callback_query(call.id, "⛔ Ruxsat yo'q", show_alert=True)
            return
        _, act, wid = call.data.split(":")
        approve = (act == "ok")
        wd = services.resolve_withdrawal(int(wid), approve)
        if wd is None:
            bot.answer_callback_query(call.id, "Bu ariza allaqachon ko'rib chiqilgan", show_alert=True)
            return
        bot.answer_callback_query(call.id, "Bajarildi")
        verdict = "✅ Tasdiqlandi" if approve else "❌ Rad etildi (balans qaytarildi)"
        try:
            bot.edit_message_text(
                (call.message.text or "") + f"\n\n<b>{verdict}</b>",
                call.message.chat.id, call.message.message_id,
                reply_markup=None,
            )
        except Exception:
            pass
        try:
            if approve:
                bot.send_message(wd["user_id"],
                                 f"✅ Ariza #{wd['id']} tasdiqlandi: {stars(wd['amount'])} to'lanadi.")
            else:
                bot.send_message(wd["user_id"],
                                 f"❌ Ariza #{wd['id']} rad etildi. {stars(wd['amount'])} balansingizga qaytarildi.")
        except Exception:
            pass


# =====================================================================
# YORDAMCHI
# =====================================================================

def _safe_edit(bot: telebot.TeleBot, call: types.CallbackQuery,
               text: str, kb=None) -> None:
    try:
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=kb)
    except Exception:
        try:
            bot.send_message(call.message.chat.id, text, reply_markup=kb)
        except Exception:
            pass
