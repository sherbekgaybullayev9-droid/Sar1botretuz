"""
Admin handlerlari (telebot, sinxron).
"""
import logging
import re
from decimal import Decimal

import telebot
from telebot import types

import config
import services
from utils import channel_url, chat_ref, esc, normalize_channel_input, parse_amount, stars

log = logging.getLogger("admin")

# Admin holatlari: user_id -> {"state": str, "data": dict}
admin_states: dict[int, dict] = {}


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
        admin_states.pop(message.from_user.id, None)
        bot.send_message(message.chat.id, "🛠 <b>Admin panel</b>", reply_markup=admin_menu_kb())

    # ---- /cancel (admin) ----
    @bot.message_handler(commands=["cancel"],
                         func=lambda m: _is_admin(m.from_user.id))
    def cmd_cancel(message: types.Message):
        admin_states.pop(message.from_user.id, None)
        bot.send_message(message.chat.id, "Bekor qilindi.", reply_markup=admin_menu_kb())

    # ---- Admin matn holatlari ----
    @bot.message_handler(func=lambda m: _is_admin(m.from_user.id) and m.from_user.id in admin_states,
                         content_types=["text"])
    def handle_admin_text(message: types.Message):
        uid   = message.from_user.id
        st    = admin_states.get(uid, {})
        state = st.get("state", "")
        data  = st.get("data", {})

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
            admin_states.pop(uid, None)
            bot.send_message(message.chat.id, f"✅ Standart mukofot: {stars(v)}", reply_markup=admin_menu_kb())
            return

        # Minimal yechish
        if state == "adm:setmin":
            v = parse_amount(message.text)
            if v is None:
                bot.send_message(message.chat.id, "❌ Musbat son kiriting.")
                return
            services.set_setting("min_withdraw", str(v))
            admin_states.pop(uid, None)
            bot.send_message(message.chat.id, f"✅ Minimal yechish: {stars(v)}", reply_markup=admin_menu_kb())
            return

    # ---- Admin callback querylar ----
    @bot.callback_query_handler(func=lambda c: _is_admin(c.from_user.id) and c.data.startswith("adm:"))
    def handle_admin_cb(call: types.CallbackQuery):
        uid  = call.from_user.id
        data = call.data

        if data == "adm:menu":
            admin_states.pop(uid, None)
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
            admin_states[uid] = {"state": "adm:addch", "data": {}}
            bot.answer_callback_query(call.id)
            _safe_edit(bot, call,
                       "📢 Kanal @username, t.me havolasi yoki ID (-100...) yuboring.\n"
                       "⚠️ Bot kanalda <b>admin</b> bo'lishi shart.\nBekor qilish: /cancel")
            return

        if data == "adm:addstart":
            admin_states[uid] = {"state": "adm:addstart", "data": {}}
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
            admin_states[uid] = {"state": "adm:task_reward", "data": {"task_id": tid}}
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
            from middleware import invalidate_cache as _ic
            # Hamma keshni tozalaymiz (kanallar o'zgardi)
            import middleware as mw
            mw._sub_cache.clear()
            bot.answer_callback_query(call.id, "O'chirildi")
            _show_req_channels(bot, call)
            return

        if data == "adm:reqadd":
            admin_states[uid] = {"state": "adm:reqadd", "data": {}}
            bot.answer_callback_query(call.id)
            _safe_edit(bot, call,
                       "📢 Majburiy kanal @username yoki ID yuboring. Bot kanalda admin bo'lsin.\nBekor qilish: /cancel")
            return

        if data == "adm:bal":
            admin_states[uid] = {"state": "adm:bal_user", "data": {}}
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
                from handlers_user import wd_confirm_kb
                bot.send_message(
                    call.message.chat.id,
                    f"💸 <b>Ariza #{wd['id']}</b>\n"
                    f"👤 {name}\n"
                    f"🆔 <code>{wd['user_id']}</code>\n"
                    f"💰 {stars(wd['amount'])}\n"
                    f"📝 {esc(wd['details'])}",
                    reply_markup=wd_confirm_kb(wd["id"]),
                )
            return

        if data == "adm:set":
            bot.answer_callback_query(call.id)
            reward = services.get_default_reward()
            min_w  = services.get_min_withdraw()
            kb = types.InlineKeyboardMarkup(row_width=1)
            kb.add(types.InlineKeyboardButton("🎁 Yangi vazifa mukofoti", callback_data="adm:setreward"))
            kb.add(types.InlineKeyboardButton("💸 Minimal yechish",       callback_data="adm:setmin"))
            kb.add(types.InlineKeyboardButton("⬅️ Admin menyu",           callback_data="adm:menu"))
            _safe_edit(bot, call, (
                f"⚙️ <b>Sozlamalar</b>\n\n"
                f"Yangi vazifalar uchun standart mukofot: {stars(reward)}\n"
                f"Minimal yechish: {stars(min_w)}"
            ), kb)
            return

        if data == "adm:setreward":
            admin_states[uid] = {"state": "adm:setreward", "data": {}}
            bot.answer_callback_query(call.id)
            _safe_edit(bot, call,
                       "🎁 Yangi vazifalar uchun standart mukofotni yuboring (masalan 0.5). /cancel")
            return

        if data == "adm:setmin":
            admin_states[uid] = {"state": "adm:setmin", "data": {}}
            bot.answer_callback_query(call.id)
            _safe_edit(bot, call, "💸 Minimal yechish miqdorini yuboring (masalan 15). /cancel")
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
    task = services.add_task("channel", chat_obj.title or str(chat_obj.id), str(chat_obj.id), url)
    admin_states.pop(uid, None)
    bot.send_message(message.chat.id,
                     f"✅ Kanal vazifasi #{task['id']} qo'shildi: {esc(task['title'])} ({stars(task['reward'])})",
                     reply_markup=admin_menu_kb())


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
    task = services.add_task("start", f"@{name}", name, url)
    admin_states.pop(uid, None)
    bot.send_message(message.chat.id,
                     f"✅ START vazifasi #{task['id']} qo'shildi: @{esc(name)} ({stars(task['reward'])})",
                     reply_markup=admin_menu_kb())


def _add_req_channel(bot: telebot.TeleBot, message: types.Message, uid: int) -> None:
    res = _resolve_channel(bot, message)
    if res is None:
        return
    chat_obj, url = res
    services.add_required(str(chat_obj.id), chat_obj.title or str(chat_obj.id), url)
    import middleware as mw
    mw._sub_cache.clear()
    admin_states.pop(uid, None)
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
    admin_states[uid] = {"state": "adm:bal_amount", "data": {"target_uid": target_uid}}
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
    admin_states.pop(uid, None)
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
    admin_states.pop(uid, None)
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


def _safe_edit(bot: telebot.TeleBot, call: types.CallbackQuery,
               text: str, kb=None) -> None:
    try:
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=kb)
    except Exception:
        try:
            bot.send_message(call.message.chat.id, text, reply_markup=kb)
        except Exception:
            pass
