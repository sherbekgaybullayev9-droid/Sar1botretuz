"""
Admin handlerlari (telebot, sinxron).
"""
import logging
import math
import re
import threading
import time
from decimal import Decimal

import telebot
from telebot import types
from telebot.apihelper import ApiTelegramException

import config
import middleware as mw
import services
import states
from handlers_user import wd_card, wd_confirm_kb
from utils import (channel_url, chat_ref, esc, normalize_channel_input, parse_amount,
                   safe_edit as _safe_edit, stars)

log = logging.getLogger("admin")


# =====================================================================
# KLAVIATURALAR
# =====================================================================

def admin_menu_kb() -> types.InlineKeyboardMarkup:
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("➕ Kanal vazifasi",   callback_data="adm:addch"),
        types.InlineKeyboardButton("➕ START vazifasi",   callback_data="adm:addstart"),
    )
    kb.add(types.InlineKeyboardButton("📋 Vazifalar",          callback_data="adm:tasks"))
    kb.add(types.InlineKeyboardButton("📢 Majburiy kanallar",  callback_data="adm:req"))
    kb.add(
        types.InlineKeyboardButton("👥 Foydalanuvchilar", callback_data="adm:users:0"),
        types.InlineKeyboardButton("📣 Xabar yuborish",   callback_data="adm:bc"),
    )
    kb.add(
        types.InlineKeyboardButton("👤 Balans boshqaruvi",     callback_data="adm:bal"),
        types.InlineKeyboardButton("💸 Pul yechish arizalari", callback_data="adm:wd"),
    )
    kb.add(
        types.InlineKeyboardButton("⚙️ Sozlamalar",  callback_data="adm:set"),
        types.InlineKeyboardButton("📊 Statistika",  callback_data="adm:stats"),
    )
    return kb


def back_kb(target: str = "adm:menu", label: str = "⬅️ Admin menyu") -> types.InlineKeyboardMarkup:
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton(label, callback_data=target))
    return kb


# =====================================================================
# HANDLERLARNI ROʻYXATDAN OʻTKAZISH
# =====================================================================

def register(bot: telebot.TeleBot) -> None:

    def _is_admin(uid: int) -> bool:
        return uid == config.ADMIN_ID

    # ---- /admin ----
    @bot.message_handler(commands=["admin"])
    def cmd_admin(message: types.Message):
        if not _is_admin(message.from_user.id):
            bot.reply_to(message, "⛔ Sizda admin huquqlari mavjud emas.")
            return
        states.clear("a", message.from_user.id)
        bot.send_message(message.chat.id, "🛠 <b>Admin panel</b>", reply_markup=admin_menu_kb())

    # ---- /cancel (admin) ----
    @bot.message_handler(commands=["cancel"],
                         func=lambda m: _is_admin(m.from_user.id))
    def cmd_cancel(message: types.Message):
        states.clear("a", message.from_user.id)
        bot.send_message(message.chat.id, "Bekor qilindi.", reply_markup=admin_menu_kb())

    # ---- Admin matn holatlari ----
    @bot.message_handler(
        func=lambda m: (_is_admin(m.from_user.id)
                        and not (m.text or "").startswith("/")
                        and states.get("a", m.from_user.id) is not None),
        content_types=["text", "photo", "video", "document", "animation", "audio", "voice"],
    )
    def handle_admin_text(message: types.Message):
        uid   = message.from_user.id
        st    = states.get("a", uid) or {}
        state = st.get("state", "")
        data  = st.get("data", {})

        # Xabar yuborish (broadcast): istalgan turdagi xabar
        if state == "adm:bc_msg":
            states.set("a", uid, "adm:bc_confirm",
                       {"chat_id": message.chat.id, "message_id": message.message_id})
            total = services.count_users()
            kb = types.InlineKeyboardMarkup(row_width=2)
            kb.add(
                types.InlineKeyboardButton("✅ Yuborish", callback_data="adm:bcgo"),
                types.InlineKeyboardButton("❌ Bekor",    callback_data="adm:bcno"),
            )
            bot.send_message(
                message.chat.id,
                f"📣 Yuqoridagi xabar <b>{total}</b> ta foydalanuvchiga yuboriladi. Tasdiqlaysizmi?",
                reply_markup=kb,
                reply_to_message_id=message.message_id,
            )
            return

        if message.content_type != "text":
            bot.send_message(message.chat.id, "Matn yuboring. Bekor qilish: /cancel")
            return

        if state == "adm:bc_confirm":
            bot.send_message(message.chat.id, "Tugmalardan foydalaning yoki /cancel.")
            return

        # Vazifa mukofoti (yangi vazifa qo'shishda)
        if state == "adm:task_amount":
            v = parse_amount(message.text)
            if v is None:
                bot.send_message(message.chat.id, "❌ Musbat son kiriting (masalan 0.5 yoki 2).")
                return
            _finish_task(bot, message.chat.id, uid, data, v)
            return

        # Kunlik bonus miqdori
        if state == "adm:setbonus":
            v = parse_amount(message.text)
            if v is None:
                bot.send_message(message.chat.id, "❌ Musbat son kiriting.")
                return
            services.set_setting("daily_bonus", str(v))
            states.clear("a", uid)
            bot.send_message(message.chat.id, f"✅ Kunlik bonus: {stars(v)}", reply_markup=admin_menu_kb())
            return

        # Kanal vazifasi qo'shish
        if state == "adm:addch":
            _add_channel_task(bot, message, uid)
            return

        # START vazifasi qo'shish
        if state == "adm:addstart":
            _add_start_task(bot, message, uid)
            return

        # Majburiy kanal qo'shish
        if state == "adm:reqadd":
            _add_req_channel(bot, message, uid)
            return

        # Balans — foydalanuvchi ID
        if state == "adm:bal_user":
            _bal_user_step(bot, message, uid)
            return

        # Balans — miqdor
        if state == "adm:bal_amount":
            _bal_amount_step(bot, message, uid, data)
            return

        # Vazifa mukofoti
        if state == "adm:task_reward":
            _task_reward_step(bot, message, uid, data)
            return

        # Standart mukofot
        if state == "adm:setreward":
            v = parse_amount(message.text)
            if v is None:
                bot.send_message(message.chat.id, "❌ Musbat son kiriting.")
                return
            services.set_setting("default_reward", str(v))
            states.clear("a", uid)
            bot.send_message(message.chat.id, f"✅ Standart mukofot: {stars(v)}", reply_markup=admin_menu_kb())
            return

        # Minimal yechish
        if state == "adm:setmin":
            v = parse_amount(message.text)
            if v is None:
                bot.send_message(message.chat.id, "❌ Musbat son kiriting.")
                return
            services.set_setting("min_withdraw", str(v))
            states.clear("a", uid)
            bot.send_message(message.chat.id, f"✅ Minimal yechish: {stars(v)}", reply_markup=admin_menu_kb())
            return

    # ---- Admin callback querylar ----
    @bot.callback_query_handler(func=lambda c: _is_admin(c.from_user.id) and c.data.startswith("adm:"))
    def handle_admin_cb(call: types.CallbackQuery):
        uid  = call.from_user.id
        data = call.data

        if data == "adm:menu":
            states.clear("a", uid)
            bot.answer_callback_query(call.id)
            _safe_edit(bot, call, "🛠 <b>Admin panel</b>", admin_menu_kb())
            return

        if data == "adm:stats":
            bot.answer_callback_query(call.id)
            s = services.stats()
            _safe_edit(bot, call, (
                "📊 <b>Statistika</b>\n\n"
                f"👥 Foydalanuvchilar: {s['users']}\n"
                f"📋 Vazifalar: {s['tasks_active']} faol / {s['tasks_all']} jami\n"
                f"✅ Bajarilgan vazifalar: {s['done']}\n"
                f"💰 Jami balanslar: {stars(s['balances'])}\n"
                f"⏳ Kutilayotgan arizalar: {s['pending_count']} ({stars(s['pending_sum'])})\n"
                f"💸 To'langan: {stars(s['paid'])}"
            ), back_kb())
            return

        if data == "adm:addch":
            states.set("a", uid, "adm:addch", {})
            bot.answer_callback_query(call.id)
            _safe_edit(bot, call,
                       "📢 Kanal @username, t.me havolasi yoki ID (-100...) yuboring.\n"
                       "⚠️ Bot kanalda <b>admin</b> bo'lishi shart.\nBekor qilish: /cancel")
            return

        if data == "adm:addstart":
            states.set("a", uid, "adm:addstart", {})
            bot.answer_callback_query(call.id)
            _safe_edit(bot, call,
                       "🤖 Bot @username yoki havolasini yuboring.\nBekor qilish: /cancel")
            return

        if data == "adm:tasks":
            bot.answer_callback_query(call.id)
            items = services.list_tasks()
            if not items:
                _safe_edit(bot, call, "Vazifalar yo'q.", back_kb())
                return
            kb = types.InlineKeyboardMarkup(row_width=1)
            for t in items:
                icon   = "📢" if t["kind"] == "channel" else "🤖"
                status = "🟢" if t["active"] else "⏸"
                kb.add(types.InlineKeyboardButton(
                    f"{status} {icon} {t['title']} · {stars(t['reward'])}",
                    callback_data=f"adm:t:{t['id']}",
                ))
            kb.add(types.InlineKeyboardButton("⬅️ Admin menyu", callback_data="adm:menu"))
            _safe_edit(bot, call, "📋 <b>Vazifalar</b>", kb)
            return

        if data.startswith("adm:t:") and not any(
            data.startswith(p) for p in ("adm:tt:", "adm:tr:", "adm:td:", "adm:tdy:")
        ):
            tid = int(data.split(":")[2])
            bot.answer_callback_query(call.id)
            _show_task_detail(bot, call, tid)
            return

        if data.startswith("adm:tt:"):
            tid = int(data.split(":")[2])
            services.toggle_task(tid)
            bot.answer_callback_query(call.id, "Holat o'zgartirildi")
            _show_task_detail(bot, call, tid)
            return

        if data.startswith("adm:tr:"):
            tid = int(data.split(":")[2])
            states.set("a", uid, "adm:task_reward", {"task_id": tid})
            bot.answer_callback_query(call.id)
            _safe_edit(bot, call, f"💰 #{tid} vazifa uchun yangi mukofotni yuboring (masalan 0.5). /cancel")
            return

        if data.startswith("adm:td:"):
            tid = int(data.split(":")[2])
            kb  = types.InlineKeyboardMarkup(row_width=2)
            kb.add(
                types.InlineKeyboardButton("✅ Ha, o'chirish", callback_data=f"adm:tdy:{tid}"),
                types.InlineKeyboardButton("❌ Yo'q",          callback_data=f"adm:t:{tid}"),
            )
            bot.answer_callback_query(call.id)
            _safe_edit(bot, call, f"🗑 #{tid} vazifani o'chirishni tasdiqlaysizmi?", kb)
            return

        if data.startswith("adm:tdy:"):
            tid = int(data.split(":")[2])
            services.delete_task(tid)
            bot.answer_callback_query(call.id, "O'chirildi")
            _safe_edit(bot, call, "🗑 Vazifa o'chirildi.", back_kb("adm:tasks", "⬅️ Ro'yxat"))
            return

        if data == "adm:req":
            bot.answer_callback_query(call.id)
            _show_req_channels(bot, call)
            return

        if data.startswith("adm:reqdel:"):
            rid = int(data.split(":")[2])
            services.delete_required(rid)
            mw.invalidate_all()
            bot.answer_callback_query(call.id, "O'chirildi")
            _show_req_channels(bot, call)
            return

        if data == "adm:reqadd":
            states.set("a", uid, "adm:reqadd", {})
            bot.answer_callback_query(call.id)
            _safe_edit(bot, call,
                       "📢 Majburiy kanal @username yoki ID yuboring. Bot kanalda admin bo'lsin.\nBekor qilish: /cancel")
            return

        if data == "adm:bal":
            states.set("a", uid, "adm:bal_user", {})
            bot.answer_callback_query(call.id)
            _safe_edit(bot, call, "👤 Foydalanuvchi Telegram ID raqamini yuboring. Bekor qilish: /cancel")
            return

        if data == "adm:wd":
            bot.answer_callback_query(call.id)
            items = services.list_pending_withdrawals()
            if not items:
                _safe_edit(bot, call, "💸 Kutilayotgan arizalar yo'q.", back_kb())
                return
            _safe_edit(bot, call, f"💸 Kutilayotgan arizalar: {len(items)}", back_kb())
            for wd in items:
                user = services.get_user(wd["user_id"])
                name = esc(user["full_name"]) if user else "—"
                bot.send_message(
                    call.message.chat.id,
                    wd_card(wd, name),
                    reply_markup=wd_confirm_kb(wd["id"]),
                )
            return

        if data == "adm:set":
            bot.answer_callback_query(call.id)
            reward = services.get_default_reward()
            min_w  = services.get_min_withdraw()
            bonus  = services.get_daily_bonus()
            kb = types.InlineKeyboardMarkup(row_width=1)
            kb.add(types.InlineKeyboardButton("🎁 Yangi vazifa mukofoti", callback_data="adm:setreward"))
            kb.add(types.InlineKeyboardButton("🎁 Kunlik bonus",          callback_data="adm:setbonus"))
            kb.add(types.InlineKeyboardButton("💸 Minimal yechish",       callback_data="adm:setmin"))
            kb.add(types.InlineKeyboardButton("⬅️ Admin menyu",           callback_data="adm:menu"))
            _safe_edit(bot, call, (
                f"⚙️ <b>Sozlamalar</b>\n\n"
                f"Yangi vazifalar uchun standart mukofot: {stars(reward)}\n"
                f"Kunlik bonus: {stars(bonus)}\n"
                f"Minimal yechish (eng arzon sovg'a chegarasi): {stars(min_w)}"
            ), kb)
            return

        if data == "adm:setreward":
            states.set("a", uid, "adm:setreward", {})
            bot.answer_callback_query(call.id)
            _safe_edit(bot, call,
                       "🎁 Yangi vazifalar uchun standart mukofotni yuboring (masalan 0.5). /cancel")
            return

        if data == "adm:setmin":
            states.set("a", uid, "adm:setmin", {})
            bot.answer_callback_query(call.id)
            _safe_edit(bot, call, "💸 Minimal yechish miqdorini yuboring (masalan 15). /cancel")
            return

        # ---- Vazifa mukofoti: standart ----
        if data == "adm:amtdef":
            st = states.get("a", uid)
            if not st or st["state"] != "adm:task_amount":
                bot.answer_callback_query(call.id, "Eskirgan. Qaytadan boshlang.", show_alert=True)
                return
            bot.answer_callback_query(call.id)
            _finish_task(bot, call.message.chat.id, uid, st["data"], services.get_default_reward())
            return

        # ---- Foydalanuvchilar ro'yxati ----
        if data.startswith("adm:users:"):
            try:
                page = int(data.split(":")[2])
            except (IndexError, ValueError):
                page = 0
            bot.answer_callback_query(call.id)
            text, kb = _users_page(page)
            _safe_edit(bot, call, text, kb)
            return

        # ---- Broadcast ----
        if data == "adm:bc":
            states.set("a", uid, "adm:bc_msg", {})
            bot.answer_callback_query(call.id)
            _safe_edit(bot, call,
                       "📣 Barcha foydalanuvchilarga yuboriladigan xabarni yuboring "
                       "(matn, rasm, video — istalgani).\nBekor qilish: /cancel",
                       back_kb())
            return

        if data == "adm:bcno":
            states.clear("a", uid)
            bot.answer_callback_query(call.id, "Bekor qilindi")
            _safe_edit(bot, call, "❌ Yuborish bekor qilindi.", back_kb())
            return

        if data == "adm:bcgo":
            st = states.get("a", uid)
            if not st or st["state"] != "adm:bc_confirm":
                bot.answer_callback_query(call.id, "Eskirgan. Qaytadan boshlang.", show_alert=True)
                return
            if not _bc_lock.acquire(blocking=False):
                bot.answer_callback_query(call.id, "Boshqa xabar hozir yuborilmoqda. Kuting.", show_alert=True)
                return
            states.clear("a", uid)
            bot.answer_callback_query(call.id, "Yuborish boshlandi")
            _safe_edit(bot, call, "⏳ Yuborilmoqda... Tugagach hisobot keladi.")
            threading.Thread(
                target=_broadcast_worker,
                args=(bot, call.message.chat.id, st["data"]["chat_id"], st["data"]["message_id"]),
                daemon=True, name="broadcast",
            ).start()
            return

        # ---- Kunlik bonus sozlamasi ----
        if data == "adm:setbonus":
            states.set("a", uid, "adm:setbonus", {})
            bot.answer_callback_query(call.id)
            _safe_edit(bot, call, "🎁 Kunlik bonus miqdorini yuboring (masalan 0.3). /cancel")
            return

        bot.answer_callback_query(call.id)


# =====================================================================
# YORDAMCHI FUNKSIYALAR
# =====================================================================

def _resolve_channel(bot: telebot.TeleBot, message: types.Message):
    ref = normalize_channel_input(message.text)
    if not ref:
        bot.send_message(message.chat.id,
                         "❌ Yopiq havola bo'yicha kanalni aniqlab bo'lmaydi. @username yoki ID yuboring.")
        return None
    try:
        chat_obj = bot.get_chat(chat_ref(ref))
    except Exception:
        bot.send_message(message.chat.id,
                         "❌ Kanal topilmadi yoki bot unda yo'q. Qayta yuboring yoki /cancel.")
        return None
    try:
        me = bot.get_me()
        cm = bot.get_chat_member(chat_obj.id, me.id)
        if cm.status not in ("administrator", "creator"):
            bot.send_message(message.chat.id, "❌ Bot kanalda admin emas. Avval botni admin qiling.")
            return None
    except Exception:
        bot.send_message(message.chat.id, "❌ Bot kanalda admin ekanini tekshirib bo'lmadi.")
        return None
    url = channel_url(bot, chat_obj)
    if not url:
        bot.send_message(message.chat.id,
                         "❌ Kanal havolasini olib bo'lmadi. Botga havola yaratish huquqini bering.")
        return None
    return chat_obj, url


def _add_channel_task(bot: telebot.TeleBot, message: types.Message, uid: int) -> None:
    res = _resolve_channel(bot, message)
    if res is None:
        return
    chat_obj, url = res
    _ask_task_amount(bot, message.chat.id, uid, "channel",
                     chat_obj.title or str(chat_obj.id), str(chat_obj.id), url)


def _add_start_task(bot: telebot.TeleBot, message: types.Message, uid: int) -> None:
    t = (message.text or "").strip()
    if "t.me/" in t:
        url  = t if t.startswith("http") else "https://" + t
        name = t.split("t.me/")[1].split("?")[0].strip("/")
    else:
        name = t.lstrip("@")
        url  = f"https://t.me/{name}"
    if not re.fullmatch(r"[A-Za-z0-9_]{4,64}", name):
        bot.send_message(message.chat.id, "❌ Noto'g'ri bot nomi. Qayta yuboring yoki /cancel.")
        return
    _ask_task_amount(bot, message.chat.id, uid, "start", f"@{name}", name, url)


def _add_req_channel(bot: telebot.TeleBot, message: types.Message, uid: int) -> None:
    res = _resolve_channel(bot, message)
    if res is None:
        return
    chat_obj, url = res
    services.add_required(str(chat_obj.id), chat_obj.title or str(chat_obj.id), url)
    mw.invalidate_all()
    states.clear("a", uid)
    bot.send_message(message.chat.id,
                     f"✅ Majburiy kanal qo'shildi: {esc(chat_obj.title or str(chat_obj.id))}",
                     reply_markup=admin_menu_kb())


def _bal_user_step(bot: telebot.TeleBot, message: types.Message, uid: int) -> None:
    if not (message.text or "").strip().isdigit():
        bot.send_message(message.chat.id, "❌ ID faqat raqamlardan iborat bo'lishi kerak.")
        return
    target_uid = int(message.text.strip())
    user = services.get_user(target_uid)
    if user is None:
        bot.send_message(message.chat.id, "❌ Bunday foydalanuvchi topilmadi. Boshqa ID yuboring yoki /cancel.")
        return
    bal = Decimal(str(user["balance"]))
    states.set("a", uid, "adm:bal_amount", {"target_uid": target_uid})
    bot.send_message(
        message.chat.id,
        f"👤 {esc(user['full_name'])} — balans: {stars(bal)}\n"
        "Miqdorni yuboring: <code>+5</code> qo'shadi, <code>-2</code> ayiradi. Bekor qilish: /cancel",
    )


def _bal_amount_step(bot: telebot.TeleBot, message: types.Message, uid: int, data: dict) -> None:
    delta = parse_amount(message.text, allow_negative=True)
    if delta is None:
        bot.send_message(message.chat.id, "❌ Noto'g'ri son. Masalan: +5 yoki -2")
        return
    target_uid = data["target_uid"]
    try:
        new_bal = services.adjust_balance(target_uid, delta)
    except ValueError as e:
        msg = "❌ Balans manfiy bo'lib qoladi." if str(e) == "insufficient" else "❌ Foydalanuvchi topilmadi."
        bot.send_message(message.chat.id, msg)
        return
    states.clear("a", uid)
    bot.send_message(message.chat.id, f"✅ Yangi balans: {stars(new_bal)}", reply_markup=admin_menu_kb())
    try:
        sign = "+" if delta > 0 else ""
        bot.send_message(
            target_uid,
            f"ℹ️ Balansingiz admin tomonidan o'zgartirildi: {sign}{stars(delta)}.\n"
            f"Joriy balans: {stars(new_bal)}",
        )
    except Exception:
        pass


def _task_reward_step(bot: telebot.TeleBot, message: types.Message, uid: int, data: dict) -> None:
    amount = parse_amount(message.text)
    if amount is None:
        bot.send_message(message.chat.id, "❌ Musbat son kiriting (masalan 0.5).")
        return
    tid = data["task_id"]
    services.set_task_reward(tid, amount)
    states.clear("a", uid)
    bot.send_message(message.chat.id, f"✅ #{tid} vazifa mukofoti: {stars(amount)}", reply_markup=admin_menu_kb())


def _show_req_channels(bot: telebot.TeleBot, call: types.CallbackQuery) -> None:
    items = services.list_required()
    kb    = types.InlineKeyboardMarkup(row_width=1)
    for ch in items:
        kb.add(types.InlineKeyboardButton(f"🗑 {ch['title']}", callback_data=f"adm:reqdel:{ch['id']}"))
    kb.add(types.InlineKeyboardButton("➕ Kanal qo'shish", callback_data="adm:reqadd"))
    kb.add(types.InlineKeyboardButton("⬅️ Admin menyu",    callback_data="adm:menu"))
    text = "📢 <b>Majburiy kanallar</b>\n" + (
        "\n".join(f"• {esc(c['title'])}" for c in items) if items else "Hozircha yo'q."
    )
    _safe_edit(bot, call, text, kb)


def _show_task_detail(bot: telebot.TeleBot, call: types.CallbackQuery, task_id: int) -> None:
    task = services.get_task(task_id)
    if task is None:
        _safe_edit(bot, call, "Vazifa topilmadi.", back_kb("adm:tasks", "⬅️ Ro'yxat"))
        return
    done  = services.task_completions_count(task_id)
    holat = "faol" if task["active"] else "to'xtatilgan"
    icon  = "📢" if task["kind"] == "channel" else "🤖"
    kb = types.InlineKeyboardMarkup(row_width=1)
    kb.add(types.InlineKeyboardButton(
        "⏸ To'xtatish" if task["active"] else "▶️ Yoqish",
        callback_data=f"adm:tt:{task_id}",
    ))
    kb.add(types.InlineKeyboardButton("💰 Mukofotni o'zgartirish", callback_data=f"adm:tr:{task_id}"))
    kb.add(types.InlineKeyboardButton("🗑 O'chirish",              callback_data=f"adm:td:{task_id}"))
    kb.add(types.InlineKeyboardButton("⬅️ Ro'yxat",               callback_data="adm:tasks"))
    _safe_edit(bot, call, (
        f"{icon} <b>#{task_id} {esc(task['title'])}</b>\n"
        f"Holat: {holat}\n"
        f"Mukofot: {stars(task['reward'])}\n"
        f"Bajarilgan: {done}\n"
        f"{esc(task['url'])}"
    ), kb)


def _ask_task_amount(bot: telebot.TeleBot, chat_id: int, uid: int,
                     kind: str, title: str, target: str, url: str) -> None:
    states.set("a", uid, "adm:task_amount",
               {"kind": kind, "title": title, "target": target, "url": url})
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton(
        f"Standart: {stars(services.get_default_reward())}", callback_data="adm:amtdef"))
    bot.send_message(
        chat_id,
        f"💰 <b>{esc(title)}</b> uchun mukofot miqdorini yuboring (masalan 0.5 yoki 2).\n"
        f"Yoki standart qiymatni tanlang. Bekor qilish: /cancel",
        reply_markup=kb,
    )


def _finish_task(bot: telebot.TeleBot, chat_id: int, uid: int, data: dict, reward: Decimal) -> None:
    try:
        task = services.add_task(data["kind"], data["title"], data["target"], data["url"], reward)
    except KeyError:
        states.clear("a", uid)
        bot.send_message(chat_id, "❌ Ma'lumot eskirgan. Qaytadan boshlang.", reply_markup=admin_menu_kb())
        return
    states.clear("a", uid)
    label = "Kanal" if data["kind"] == "channel" else "START"
    bot.send_message(
        chat_id,
        f"✅ {label} vazifasi #{task['id']} qo'shildi: {esc(task['title'])} ({stars(task['reward'])})",
        reply_markup=admin_menu_kb(),
    )


USERS_PER_PAGE = 10


def _users_page(page: int):
    total = services.count_users()
    pages = max(1, math.ceil(total / USERS_PER_PAGE))
    page  = min(max(page, 0), pages - 1)
    rows  = services.list_users(page * USERS_PER_PAGE, USERS_PER_PAGE)
    lines = [f"👥 <b>Foydalanuvchilar:</b> {total} ta  (sahifa {page + 1}/{pages})\n"]
    for i, u in enumerate(rows, start=page * USERS_PER_PAGE + 1):
        name  = esc((u["full_name"] or "—").strip()[:40] or "—")
        uname = f"@{esc(u['username'])}" if u["username"] else "—"
        lines.append(f"{i}. {name} · {uname}\n    🆔 <code>{u['id']}</code> · {stars(u['balance'])}")
    if not rows:
        lines.append("Hozircha foydalanuvchi yo'q.")
    kb = types.InlineKeyboardMarkup(row_width=2)
    nav = []
    if page > 0:
        nav.append(types.InlineKeyboardButton("⬅️", callback_data=f"adm:users:{page - 1}"))
    if page < pages - 1:
        nav.append(types.InlineKeyboardButton("➡️", callback_data=f"adm:users:{page + 1}"))
    if nav:
        kb.add(*nav)
    kb.add(types.InlineKeyboardButton("⬅️ Admin menyu", callback_data="adm:menu"))
    return "\n".join(lines), kb


_bc_lock = threading.Lock()


def _broadcast_worker(bot: telebot.TeleBot, admin_chat: int, from_chat: int, msg_id: int) -> None:
    """Hamma foydalanuvchiga xabarni nusxalaydi (~20 xabar/soniya, 429 bo'lsa kutadi)."""
    sent = failed = 0
    try:
        ids = services.all_user_ids()
        for uid in ids:
            for _ in range(3):
                try:
                    bot.copy_message(uid, from_chat, msg_id)
                    sent += 1
                    break
                except ApiTelegramException as e:
                    if e.error_code == 429:
                        retry = 5
                        try:
                            retry = int((e.result_json.get("parameters") or {}).get("retry_after", 5))
                        except Exception:
                            pass
                        time.sleep(retry + 1)
                        continue
                    failed += 1   # bot bloklangan / chat topilmadi va h.k.
                    break
                except Exception:
                    failed += 1
                    break
            else:
                failed += 1
            time.sleep(0.05)
    except Exception:
        log.exception("Broadcast xatosi")
    finally:
        _bc_lock.release()
        try:
            bot.send_message(
                admin_chat,
                f"📣 <b>Yuborish tugadi</b>\n✅ Yetkazildi: {sent}\n❌ Yetkazilmadi: {failed}",
                reply_markup=admin_menu_kb(),
            )
        except Exception:
            pass
