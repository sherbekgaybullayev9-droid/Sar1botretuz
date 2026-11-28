"""
Foydalanuvchi handlerlari (telebot, sinxron).
"""
import logging
import re
from decimal import Decimal
from urllib.parse import quote

import telebot
from telebot import types

import config
import services
import states
from gifts import BY_KEY, GIFTS
from middleware import (check_subscription, flood_check, invalidate_cache,
                        missing_channels, send_subscription_required, subscribe_markup)
from utils import esc, is_member, parse_amount, safe_edit as _safe_edit, stars

log = logging.getLogger("user")

BTN_TASKS = "📋 Vazifalar"
BTN_BAL   = "💰 Balans"
BTN_WD    = "💸 Pul yechish"
BTN_HELP  = "ℹ️ Yordam"
BTN_BONUS = "🎁 Kunlik bonus"
BTN_ID    = "🆔 Mening ID"
BTN_REF   = "👥 Referal"



def _int_arg(data: str, idx: int) -> int:
    try:
        return int(data.split(":")[idx])
    except (IndexError, ValueError):
        return 0


# =====================================================================
# KLAVIATURALAR
# =====================================================================

def main_menu_kb() -> types.ReplyKeyboardMarkup:
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row(BTN_TASKS, BTN_BAL)
    kb.row(BTN_BONUS, BTN_REF)
    kb.row(BTN_WD, BTN_ID)
    kb.row(BTN_HELP)
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


def gifts_kb(balance: Decimal, min_w: Decimal) -> types.InlineKeyboardMarkup:
    kb = types.InlineKeyboardMarkup(row_width=2)
    buttons = []
    for g in GIFTS:
        if g.cost < min_w:
            continue
        lock = "" if balance >= g.cost else "🔒 "
        buttons.append(types.InlineKeyboardButton(
            f"{lock}{g.emoji} {g.cost} ⭐", callback_data=f"gift:{g.key}"))
    kb.add(*buttons)
    kb.add(types.InlineKeyboardButton("✖️ Bekor qilish", callback_data="gift:cancel"))
    return kb


def wd_card(wd: dict, who: str) -> str:
    """Admin uchun ariza kartochkasi (HTML)."""
    g = BY_KEY.get(wd.get("gift") or "")
    gift_txt = f"{g.emoji} {g.name}" if g else "—"
    return (
        f"💸 <b>Ariza #{wd['id']}</b>\n"
        f"👤 {who}\n"
        f"🆔 <code>{wd['user_id']}</code>\n"
        f"🎁 Sovg'a: {gift_txt}\n"
        f"📬 Qabul qiluvchi: {esc(wd.get('recipient') or '—')}\n"
        f"💰 {stars(wd['amount'])}\n"
        f"📝 {esc(wd['details'])}"
    )


def _norm_username(text: str):
    t = (text or "").strip()
    m = re.match(r"^(?:https?://)?t\.me/([A-Za-z0-9_]+)/?$", t)
    if m:
        t = m.group(1)
    t = t.lstrip("@")
    if re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{4,31}", t):
        return "@" + t
    return None


_bot_username: str = ""


def _get_bot_username(bot: telebot.TeleBot) -> str:
    global _bot_username
    if not _bot_username:
        _bot_username = bot.get_me().username
    return _bot_username


def _reward_referrer(bot: telebot.TeleBot, uid: int) -> None:
    """Do'st majburiy obunadan o'tdi — taklif qilganga mukofot (bir marta)."""
    try:
        res = services.reward_referral(uid)
    except Exception:
        log.exception("Referal mukofotini berishda xato")
        return
    if res is None:
        return
    referrer_id, amount = res
    friend = services.get_user(uid)
    name = esc((friend["full_name"] if friend else "") or "Do'stingiz")
    try:
        bot.send_message(
            referrer_id,
            f"🎉 Taklif qilgan do'stingiz <b>{name}</b> obunadan o'tdi!\n"
            f"+{stars(amount)} balansingizga qo'shildi.",
        )
    except Exception:
        pass


def _limit_line(task) -> str:
    mx = task.get("max_completions")
    if mx is None:
        return ""
    left = max(0, mx - services.task_completions_count(task["id"]))
    return f"\n👥 Qolgan joylar: {left}/{mx}"


def _full_name(u) -> str:
    return ((u.first_name or "") + " " + (u.last_name or "")).strip()


def _show_gift_picker(bot: telebot.TeleBot, chat_id: int, uid: int, call=None) -> None:
    user  = services.get_user(uid)
    bal   = Decimal(str(user["balance"])) if user else Decimal("0")
    min_w = services.get_min_withdraw()
    elig  = [g for g in GIFTS if g.cost >= min_w]
    kb = None
    if not elig:
        text = "❌ Hozircha pul yechish mavjud emas."
    elif bal < min(g.cost for g in elig):
        text = (f"❌ Eng arzon sovg'a {stars(min(g.cost for g in elig))}. "
                f"Sizning balansingiz: {stars(bal)}.")
    else:
        text = (f"💸 <b>Sovg'a tanlang</b>\n\n"
                f"💰 Balansingiz: {stars(bal)}\n"
                f"Sovg'a narxi balansdan yechiladi, sovg'ani admin siz ko'rsatgan @username ga yuboradi.\n"
                f"🔒 — balans yetmaydi.")
        kb = gifts_kb(bal, min_w)
    if call is not None:
        _safe_edit(bot, call, text, kb)
    else:
        bot.send_message(chat_id, text, reply_markup=kb)


def _submit_withdrawal(bot: telebot.TeleBot, chat_id: int, from_user, gift_key: str, recipient: str) -> None:
    uid = from_user.id
    g = BY_KEY.get(gift_key)
    states.clear("u", uid)
    if g is None:
        bot.send_message(chat_id, "❌ Sovg'a topilmadi. Qaytadan urinib ko'ring.", reply_markup=main_menu_kb())
        return
    details = f"{g.emoji} {g.name} ({g.cost} ⭐) → {recipient}"
    wd = services.create_withdrawal(uid, Decimal(g.cost), details, g.key, recipient)
    if wd is None:
        bot.send_message(chat_id, "❌ Balansingiz yetarli emas.", reply_markup=main_menu_kb())
        return
    bot.send_message(
        chat_id,
        f"✅ Ariza #{wd['id']} qabul qilindi:\n"
        f"{g.emoji} {g.name} ({stars(g.cost)}) → {esc(recipient)}\n"
        f"Admin ko'rib chiqadi, natija haqida xabar beramiz.",
        reply_markup=main_menu_kb(),
    )
    uname = f"@{from_user.username}" if from_user.username else "—"
    try:
        bot.send_message(
            config.ADMIN_ID,
            wd_card(wd, f"{esc(from_user.first_name or '')} ({uname})"),
            reply_markup=wd_confirm_kb(wd["id"]),
        )
    except Exception:
        log.exception("Adminga ariza yuborib bo'lmadi")


# =====================================================================
# HANDLERLARNI ROʻYXATDAN OʻTKAZISH
# =====================================================================

def register(bot: telebot.TeleBot) -> None:

    # ---- /start ----
    @bot.message_handler(commands=["start"])
    def cmd_start(message: types.Message):
        uid = message.from_user.id
        is_new = services.get_user(uid) is None
        services.upsert_user(
            uid,
            message.from_user.username,
            _full_name(message.from_user),
        )
        if is_new:
            parts = (message.text or "").split(maxsplit=1)
            if len(parts) == 2 and parts[1].strip().isdigit():
                try:
                    services.set_referrer(uid, int(parts[1].strip()))
                except Exception:
                    log.exception("Referal biriktirishda xato")
        states.clear("u", uid)
        if uid != config.ADMIN_ID and not check_subscription(bot, uid):
            send_subscription_required(bot, message.chat.id, uid)
            return
        _reward_referrer(bot, uid)
        reward = services.get_default_reward()
        min_w  = services.get_min_withdraw()
        bot.send_message(
            message.chat.id,
            f"👋 Salom, <b>{esc(message.from_user.first_name)}</b>!\n\n"
            f"Vazifalarni bajaring va ⭐ to'plang. Har bir vazifa uchun odatda {stars(reward)} beriladi.\n"
            f"🎁 Har kuni kunlik bonus oling, ⭐ ni esa sovg'a ko'rinishida yechib oling.",
            reply_markup=main_menu_kb(),
        )

    # ---- /cancel ----
    @bot.message_handler(commands=["cancel"])
    def cmd_cancel(message: types.Message):
        uid = message.from_user.id
        states.clear("u", uid)
        bot.send_message(message.chat.id, "Bekor qilindi.", reply_markup=main_menu_kb())

    # ---- Vazifalar ----
    @bot.message_handler(func=lambda m: m.text == BTN_TASKS)
    def show_tasks(message: types.Message):
        uid = message.from_user.id
        states.clear("u", uid)
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
        states.clear("u", uid)
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
        states.clear("u", message.from_user.id)
        min_w = services.get_min_withdraw()
        bot.send_message(
            message.chat.id,
            f"ℹ️ <b>Yordam</b>\n\n"
            f"📋 Vazifalar — kanalga obuna bo'ling yoki botga START bosing.\n"
            f"💰 Balans — to'plangan ⭐.\n"
            f"🎁 Kunlik bonus — har kuni bepul ⭐.\n"
            f"💸 Pul yechish — {stars(min_w)} dan boshlab sovg'a tanlab ariza yuboring.\n"
            f"👥 Referal — do'stlaringizni taklif qiling, har biri uchun ⭐ oling.\n"
            f"🆔 Mening ID — Telegram ID raqamingiz.\n"
            f"/cancel — joriy amalni bekor qilish.",
        )

    # ---- Pul yechish (sovg'a tanlash) ----
    @bot.message_handler(func=lambda m: m.text == BTN_WD)
    def wd_start(message: types.Message):
        uid = message.from_user.id
        states.clear("u", uid)
        if not check_subscription(bot, uid):
            send_subscription_required(bot, message.chat.id, uid)
            return
        _show_gift_picker(bot, message.chat.id, uid)

    # ---- Kunlik bonus ----
    @bot.message_handler(func=lambda m: m.text == BTN_BONUS)
    def daily_bonus(message: types.Message):
        uid = message.from_user.id
        states.clear("u", uid)
        if not check_subscription(bot, uid):
            send_subscription_required(bot, message.chat.id, uid)
            return
        services.upsert_user(uid, message.from_user.username, _full_name(message.from_user))
        got, left = services.claim_daily_bonus(uid)
        if got is not None:
            user = services.get_user(uid)
            bal  = Decimal(str(user["balance"])) if user else got
            bot.send_message(
                message.chat.id,
                f"🎁 <b>Kunlik bonus!</b>\n+{stars(got)} balansingizga qo'shildi.\n"
                f"💰 Balans: {stars(bal)}\nErtaga yana keling!",
            )
        else:
            hours   = int(left // 3600)
            minutes = int((left % 3600) // 60)
            bot.send_message(
                message.chat.id,
                f"⏳ Bugungi bonusni allaqachon oldingiz.\n"
                f"Keyingisi: {hours} soat {minutes} daqiqadan keyin (Toshkent vaqti bilan 00:00).",
            )

    # ---- Referal ----
    @bot.message_handler(func=lambda m: m.text == BTN_REF)
    def show_ref(message: types.Message):
        uid = message.from_user.id
        states.clear("u", uid)
        if not check_subscription(bot, uid):
            send_subscription_required(bot, message.chat.id, uid)
            return
        link   = f"https://t.me/{_get_bot_username(bot)}?start={uid}"
        reward = services.get_referral_reward()
        st     = services.referral_stats(uid)
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton(
            "📤 Do'stlarga yuborish",
            url="https://t.me/share/url?url=" + quote(link, safe="")
                + "&text=" + quote("⭐ Vazifalarni bajaring va ⭐ ishlang!", safe=""),
        ))
        bot.send_message(
            message.chat.id,
            f"👥 <b>Referal tizimi</b>\n\n"
            f"Har bir taklif qilingan do'st uchun <b>{stars(reward)}</b> olasiz — "
            f"do'stingiz majburiy kanallarga obuna bo'lgandan keyin.\n\n"
            f"🔗 Sizning havolangiz:\n<code>{link}</code>\n\n"
            f"👤 Taklif qilinganlar: {st['invited']}\n"
            f"✅ Obunadan o'tganlar: {st['passed']}\n"
            f"💰 Ishlangan: {stars(st['earned'])}",
            reply_markup=kb,
        )

    # ---- Mening ID ----
    @bot.message_handler(func=lambda m: m.text == BTN_ID)
    def my_id(message: types.Message):
        u = message.from_user
        states.clear("u", u.id)
        uname = f"@{u.username}" if u.username else "—"
        bot.send_message(
            message.chat.id,
            f"🆔 <b>Sizning Telegram ID:</b> <code>{u.id}</code>\n"
            f"👤 {esc(_full_name(u))}\n"
            f"🔗 {esc(uname)}",
        )

    # ---- Umumiy matn (holat mashina) ----
    @bot.message_handler(func=lambda m: True, content_types=["text"])
    def handle_text(message: types.Message):
        uid = message.from_user.id
        if flood_check(uid):
            return
        st = states.get("u", uid)
        if st is None:
            return
        state = st["state"]
        data  = st["data"]

        # Pul yechish: qabul qiluvchi @username
        if state == "wd_recipient":
            gift_key = data.get("gift")
            if gift_key not in BY_KEY:
                states.clear("u", uid)
                bot.send_message(message.chat.id, "Qaytadan boshlang.", reply_markup=main_menu_kb())
                return
            rec = _norm_username(message.text)
            if rec is None:
                bot.send_message(
                    message.chat.id,
                    "❌ Noto'g'ri username. Masalan: @username (kamida 5 belgi). Bekor qilish: /cancel",
                )
                return
            _submit_withdrawal(bot, message.chat.id, message.from_user, gift_key, rec)
            return

        # Eskirgan/noma'lum holat
        states.clear("u", uid)

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
        _reward_referrer(bot, uid)
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
        task_id = _int_arg(call.data, 1)
        if not check_subscription(bot, uid):
            bot.answer_callback_query(call.id, "Avval majburiy kanallarga obuna bo'ling", show_alert=True)
            send_subscription_required(bot, call.message.chat.id, uid)
            return
        task    = services.get_task(task_id)
        if task is None or not task["active"]:
            bot.answer_callback_query(call.id, "Bu vazifa mavjud emas yoki to'xtatilgan", show_alert=True)
            return
        if services.is_completed(uid, task_id):
            bot.answer_callback_query(call.id, "Bu vazifa allaqachon bajarilgan", show_alert=True)
            return
        if services.task_is_full(task_id):
            bot.answer_callback_query(call.id, "😔 Bu vazifaning limiti tugagan", show_alert=True)
            return
        bot.answer_callback_query(call.id)
        if task["kind"] == "channel":
            text = (f"📢 <b>{esc(task['title'])}</b>\n\n"
                    f"Kanalga obuna bo'ling, so'ng «✅ Tekshirish» tugmasini bosing.\n"
                    f"🎁 Mukofot: {stars(task['reward'])}" + _limit_line(task))
        else:
            services.mark_opened(uid, task_id)
            text = (f"🤖 <b>{esc(task['title'])}</b>\n\n"
                    f"Botga o'ting va <b>START</b> bosing, so'ng bu yerga qaytib "
                    f"«✅ Tekshirish» tugmasini bosing "
                    f"(kamida {config.START_WAIT_SECONDS} soniyadan keyin).\n"
                    f"🎁 Mukofot: {stars(task['reward'])}" + _limit_line(task))
        _safe_edit(bot, call, text, task_detail_kb(task_id, task["url"]))

    @bot.callback_query_handler(func=lambda c: c.data.startswith("chk:"))
    def cb_task_check(call: types.CallbackQuery):
        uid     = call.from_user.id
        task_id = _int_arg(call.data, 1)
        if not check_subscription(bot, uid):
            bot.answer_callback_query(call.id, "Avval majburiy kanallarga obuna bo'ling", show_alert=True)
            send_subscription_required(bot, call.message.chat.id, uid)
            return
        task    = services.get_task(task_id)
        if task is None or not task["active"]:
            bot.answer_callback_query(call.id, "Bu vazifa mavjud emas yoki to'xtatilgan", show_alert=True)
            return
        if services.is_completed(uid, task_id):
            bot.answer_callback_query(call.id, "Bu vazifa allaqachon bajarilgan", show_alert=True)
            return
        if services.task_is_full(task_id):
            bot.answer_callback_query(call.id, "😔 Bu vazifaning limiti tugagan", show_alert=True)
            return
        if task["kind"] == "channel":
            if not is_member(bot, task["target"], uid, on_error=False):
                bot.answer_callback_query(call.id, "❌ Siz hali kanalga obuna bo'lmagansiz", show_alert=True)
                return
        else:
            elapsed = services.seconds_since_opened(uid, task_id)
            if elapsed is None:
                services.mark_opened(uid, task_id)
                bot.answer_callback_query(call.id,
                                          "Avval «🔗 Ochish» orqali botga o'tib START bosing.",
                                          show_alert=True)
                return
            left = config.START_WAIT_SECONDS - elapsed
            if left > 0:
                bot.answer_callback_query(
                    call.id,
                    f"⏳ Botga START bosganingizdan so'ng {int(left)+1} soniya kuting va qayta tekshiring.",
                    show_alert=True,
                )
                return
        if services.get_user(uid) is None:
            services.upsert_user(uid, call.from_user.username,
                                 ((call.from_user.first_name or "") + " " + (call.from_user.last_name or "")).strip())
        reward = services.complete_task(uid, task_id)
        if reward is None:
            full = services.task_is_full(task_id)
            bot.answer_callback_query(
                call.id,
                "😔 Bu vazifaning limiti tugagan" if full else "Bu vazifa allaqachon bajarilgan",
                show_alert=True)
            return
        bot.answer_callback_query(call.id, f"✅ +{stars(reward)} balansingizga qo'shildi!", show_alert=True)
        task_list = services.available_tasks(uid)
        if not task_list:
            _safe_edit(bot, call, "🎉 Barcha vazifalarni bajardingiz! Keyinroq yangilari qo'shiladi.")
            return
        _safe_edit(bot, call, "📋 <b>Mavjud vazifalar</b>\nBittasini tanlang:", tasks_kb(task_list))

    @bot.callback_query_handler(func=lambda c: c.data.startswith("gift:"))
    def cb_gift(call: types.CallbackQuery):
        uid = call.from_user.id
        arg = call.data.split(":", 1)[1]

        if arg == "cancel":
            states.clear("u", uid)
            bot.answer_callback_query(call.id)
            _safe_edit(bot, call, "Bekor qilindi.")
            return

        if not check_subscription(bot, uid):
            bot.answer_callback_query(call.id, "Avval majburiy kanallarga obuna bo'ling", show_alert=True)
            send_subscription_required(bot, call.message.chat.id, uid)
            return

        if arg == "back":
            states.clear("u", uid)
            bot.answer_callback_query(call.id)
            _show_gift_picker(bot, call.message.chat.id, uid, call=call)
            return

        if arg == "self":
            st = states.get("u", uid)
            if not st or st["state"] != "wd_recipient" or st["data"].get("gift") not in BY_KEY:
                bot.answer_callback_query(call.id, "Eskirgan. Qaytadan boshlang.", show_alert=True)
                return
            if not call.from_user.username:
                bot.answer_callback_query(call.id, "Sizda @username yo'q. Qo'lda yozib yuboring.", show_alert=True)
                return
            bot.answer_callback_query(call.id)
            rec = "@" + call.from_user.username
            _safe_edit(bot, call, f"✅ Tanlandi: {esc(rec)}")
            _submit_withdrawal(bot, call.message.chat.id, call.from_user, st["data"]["gift"], rec)
            return

        g = BY_KEY.get(arg)
        if g is None:
            bot.answer_callback_query(call.id, "Sovg'a topilmadi", show_alert=True)
            return
        user  = services.get_user(uid)
        bal   = Decimal(str(user["balance"])) if user else Decimal("0")
        min_w = services.get_min_withdraw()
        if g.cost < min_w:
            bot.answer_callback_query(call.id, "Bu sovg'a hozir mavjud emas", show_alert=True)
            return
        if bal < g.cost:
            bot.answer_callback_query(
                call.id, f"Balans yetarli emas: kerak {g.cost} ⭐, sizda {stars(bal)}", show_alert=True)
            return
        bot.answer_callback_query(call.id)
        states.set("u", uid, "wd_recipient", {"gift": g.key})
        kb = types.InlineKeyboardMarkup(row_width=1)
        if call.from_user.username:
            kb.add(types.InlineKeyboardButton(
                f"👤 O'zimga (@{call.from_user.username})", callback_data="gift:self"))
        kb.add(types.InlineKeyboardButton("⬅️ Orqaga", callback_data="gift:back"))
        _safe_edit(
            bot, call,
            f"{g.emoji} <b>{g.name}</b> — {stars(g.cost)}\n\n"
            f"📬 Sovg'a qaysi @username ga yuborilsin? Username yuboring "
            f"(masalan <code>@username</code>).\nBekor qilish: /cancel",
            kb,
        )

    @bot.callback_query_handler(func=lambda c: c.data.startswith("wd:"))
    def cb_wd_resolve(call: types.CallbackQuery):
        if call.from_user.id != config.ADMIN_ID:
            bot.answer_callback_query(call.id, "⛔ Ruxsat yo'q", show_alert=True)
            return
        parts = call.data.split(":")
        if len(parts) != 3 or not parts[2].isdigit():
            bot.answer_callback_query(call.id)
            return
        approve = (parts[1] == "ok")
        wd = services.resolve_withdrawal(int(parts[2]), approve)
        if wd is None:
            bot.answer_callback_query(call.id, "Bu ariza allaqachon ko'rib chiqilgan", show_alert=True)
            return
        bot.answer_callback_query(call.id, "Bajarildi")
        verdict = "✅ Tasdiqlandi" if approve else "❌ Rad etildi (balans qaytarildi)"
        try:
            base = getattr(call.message, "html_text", None) or call.message.text or ""
            bot.edit_message_text(
                base + f"\n\n<b>{verdict}</b>",
                call.message.chat.id, call.message.message_id,
                reply_markup=None,
            )
        except Exception:
            pass
        g = BY_KEY.get(wd.get("gift") or "")
        what = f"{g.emoji} {g.name}" if g else stars(wd["amount"])
        rec  = esc(wd.get("recipient") or "")
        try:
            if approve:
                bot.send_message(
                    wd["user_id"],
                    f"✅ Ariza #{wd['id']} tasdiqlandi: {what} sovg'asi {rec} ga yuboriladi.")
            else:
                bot.send_message(
                    wd["user_id"],
                    f"❌ Ariza #{wd['id']} rad etildi. {stars(wd['amount'])} balansingizga qaytarildi.")
        except Exception:
            pass
