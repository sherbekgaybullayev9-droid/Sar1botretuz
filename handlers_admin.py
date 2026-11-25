import logging
import re
from decimal import Decimal

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

import config
import services
from utils import (channel_url, chat_ref, esc, normalize_channel_input, parse_amount, safe_edit, stars)

log = logging.getLogger("admin")
router = Router(name="admin")
router.message.filter(F.from_user.id == config.ADMIN_ID)
router.callback_query.filter(F.from_user.id == config.ADMIN_ID)


class A(StatesGroup):
    ch_task = State()
    start_task = State()
    req_channel = State()
    task_reward = State()
    bal_user = State()
    bal_amount = State()
    set_reward = State()
    set_min = State()


def admin_menu():
    kb = InlineKeyboardBuilder()
    kb.button(text="➕ Kanal vazifasi", callback_data="adm:addch")
    kb.button(text="➕ START vazifasi", callback_data="adm:addstart")
    kb.button(text="📋 Vazifalar", callback_data="adm:tasks")
    kb.button(text="📢 Majburiy kanallar", callback_data="adm:req")
    kb.button(text="👤 Balansni boshqarish", callback_data="adm:bal")
    kb.button(text="💸 Pul yechish arizalari", callback_data="adm:wd")
    kb.button(text="⚙️ Sozlamalar", callback_data="adm:set")
    kb.button(text="📊 Statistika", callback_data="adm:stats")
    kb.adjust(2)
    return kb.as_markup()


def back_kb(target: str = "adm:menu", label: str = "⬅️ Admin menyu"):
    kb = InlineKeyboardBuilder()
    kb.button(text=label, callback_data=target)
    return kb.as_markup()


@router.message(Command("admin"))
async def cmd_admin(m: Message, state: FSMContext):
    await state.clear()
    await m.answer("🛠 <b>Admin panel</b>", reply_markup=admin_menu())


@router.message(Command("cancel"))
async def cmd_cancel(m: Message, state: FSMContext):
    await state.clear()
    await m.answer("Bekor qilindi.", reply_markup=admin_menu())


@router.callback_query(F.data == "adm:menu")
async def menu(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await cb.answer()
    await safe_edit(cb, "🛠 <b>Admin panel</b>", admin_menu())


# ---------- statistika ----------
@router.callback_query(F.data == "adm:stats")
async def stats(cb: CallbackQuery):
    s = await services.stats()
    await cb.answer()
    await safe_edit(cb, (
        "📊 <b>Statistika</b>\n\n"
        f"👥 Foydalanuvchilar: {s['users']}\n"
        f"📋 Vazifalar: {s['tasks_active']} faol / {s['tasks_all']} jami\n"
        f"✅ Bajarilgan vazifalar: {s['done']}\n"
        f"💰 Jami balanslar: {stars(s['balances'])}\n"
        f"⏳ Kutilayotgan arizalar: {s['pending_count']} ({stars(s['pending_sum'])})\n"
        f"💸 To'langan: {stars(s['paid'])}"), back_kb())


# ---------- vazifa qo'shish ----------
@router.callback_query(F.data == "adm:addch")
async def addch(cb: CallbackQuery, state: FSMContext):
    await state.set_state(A.ch_task)
    await cb.answer()
    await safe_edit(cb, "📢 Kanal @username, t.me havolasi yoki ID (-100...) yuboring.\n"
                        "⚠️ Bot kanalda <b>admin</b> bo'lishi shart.\nBekor qilish: /cancel")


async def _resolve_channel(m: Message, bot: Bot):
    ref = normalize_channel_input(m.text)
    if not ref:
        await m.answer("❌ Yopiq havola bo'yicha kanalni aniqlab bo'lmaydi. @username yoki ID yuboring.")
        return None
    try:
        chat = await bot.get_chat(chat_ref(ref))
    except TelegramAPIError:
        await m.answer("❌ Kanal topilmadi yoki bot unda yo'q. Qayta yuboring yoki /cancel.")
        return None
    try:
        me = await bot.me()
        cm = await bot.get_chat_member(chat.id, me.id)
        if getattr(cm.status, "value", cm.status) not in {"administrator", "creator"}:
            await m.answer("❌ Bot kanalda admin emas. Avval botni admin qiling.")
            return None
    except TelegramAPIError:
        await m.answer("❌ Bot kanalda admin ekanini tekshirib bo'lmadi.")
        return None
    url = await channel_url(bot, chat)
    if not url:
        await m.answer("❌ Kanal havolasini olib bo'lmadi. Botga havola yaratish huquqini bering.")
        return None
    return chat, url


@router.message(A.ch_task, F.text)
async def addch_msg(m: Message, state: FSMContext, bot: Bot):
    res = await _resolve_channel(m, bot)
    if res is None:
        return
    chat, url = res
    task = await services.add_task("channel", chat.title or str(chat.id), str(chat.id), url)
    await state.clear()
    await m.answer(f"✅ Kanal vazifasi #{task.id} qo'shildi: {esc(task.title)} ({stars(task.reward)})",
                   reply_markup=admin_menu())


@router.callback_query(F.data == "adm:addstart")
async def addstart(cb: CallbackQuery, state: FSMContext):
    await state.set_state(A.start_task)
    await cb.answer()
    await safe_edit(cb, "🤖 Bot @username yoki havolasini yuboring (masalan @mybot yoki https://t.me/mybot?start=ref).\n"
                        "Bekor qilish: /cancel")


@router.message(A.start_task, F.text)
async def addstart_msg(m: Message, state: FSMContext):
    t = m.text.strip()
    if "t.me/" in t:
        url = t if t.startswith("http") else "https://" + t
        name = t.split("t.me/")[1].split("?")[0].strip("/")
    else:
        name = t.lstrip("@")
        url = f"https://t.me/{name}"
    if not re.fullmatch(r"[A-Za-z0-9_]{4,64}", name):
        await m.answer("❌ Noto'g'ri bot nomi. Qayta yuboring yoki /cancel.")
        return
    task = await services.add_task("start", f"@{name}", name, url)
    await state.clear()
    await m.answer(f"✅ START vazifasi #{task.id} qo'shildi: @{esc(name)} ({stars(task.reward)})",
                   reply_markup=admin_menu())


# ---------- vazifalar ro'yxati ----------
def _task_icon(t) -> str:
    return "📢" if t.kind == "channel" else "🤖"


@router.callback_query(F.data == "adm:tasks")
async def tasks(cb: CallbackQuery):
    items = await services.list_tasks()
    await cb.answer()
    if not items:
        await safe_edit(cb, "Vazifalar yo'q.", back_kb())
        return
    kb = InlineKeyboardBuilder()
    for t in items:
        kb.button(text=f"{'🟢' if t.active else '⏸'} #{t.id} {_task_icon(t)} {t.title} · {stars(t.reward)}",
                  callback_data=f"adm:t:{t.id}")
    kb.button(text="⬅️ Admin menyu", callback_data="adm:menu")
    kb.adjust(1)
    await safe_edit(cb, "📋 <b>Vazifalar</b>", kb.as_markup())


async def _show_task(cb: CallbackQuery, task_id: int):
    t = await services.get_task(task_id)
    if t is None:
        await safe_edit(cb, "Vazifa topilmadi.", back_kb("adm:tasks", "⬅️ Ro'yxat"))
        return
    done = await services.task_completions(task_id)
    kb = InlineKeyboardBuilder()
    kb.button(text="⏸ To'xtatish" if t.active else "▶️ Yoqish", callback_data=f"adm:tt:{t.id}")
    kb.button(text="💰 Mukofotni o'zgartirish", callback_data=f"adm:tr:{t.id}")
    kb.button(text="🗑 O'chirish", callback_data=f"adm:td:{t.id}")
    kb.button(text="⬅️ Ro'yxat", callback_data="adm:tasks")
    kb.adjust(1)
    await safe_edit(cb, (f"{_task_icon(t)} <b>#{t.id} {esc(t.title)}</b>\n"
                         f"Holat: {'faol' if t.active else 'to‘xtatilgan'}\n"
                         f"Mukofot: {stars(t.reward)}\nBajarilgan: {done}\n{esc(t.url)}"), kb.as_markup())


@router.callback_query(F.data.regexp(r"^adm:t:\d+$"))
async def task_view(cb: CallbackQuery):
    await cb.answer()
    await _show_task(cb, int(cb.data.split(":")[2]))


@router.callback_query(F.data.regexp(r"^adm:tt:\d+$"))
async def task_toggle(cb: CallbackQuery):
    tid = int(cb.data.split(":")[2])
    await services.toggle_task(tid)
    await cb.answer("Holat o'zgartirildi")
    await _show_task(cb, tid)


@router.callback_query(F.data.regexp(r"^adm:td:\d+$"))
async def task_delete_ask(cb: CallbackQuery):
    tid = int(cb.data.split(":")[2])
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Ha, o'chirish", callback_data=f"adm:tdy:{tid}")
    kb.button(text="❌ Yo'q", callback_data=f"adm:t:{tid}")
    kb.adjust(2)
    await cb.answer()
    await safe_edit(cb, f"🗑 #{tid} vazifani o'chirishni tasdiqlaysizmi?", kb.as_markup())


@router.callback_query(F.data.regexp(r"^adm:tdy:\d+$"))
async def task_delete(cb: CallbackQuery):
    await services.delete_task(int(cb.data.split(":")[2]))
    await cb.answer("O'chirildi")
    await safe_edit(cb, "🗑 Vazifa o'chirildi.", back_kb("adm:tasks", "⬅️ Ro'yxat"))


@router.callback_query(F.data.regexp(r"^adm:tr:\d+$"))
async def task_reward_ask(cb: CallbackQuery, state: FSMContext):
    tid = int(cb.data.split(":")[2])
    await state.set_state(A.task_reward)
    await state.update_data(task_id=tid)
    await cb.answer()
    await safe_edit(cb, f"💰 #{tid} vazifa uchun yangi mukofotni yuboring (masalan 0.5). Bekor qilish: /cancel")


@router.message(A.task_reward, F.text)
async def task_reward_set(m: Message, state: FSMContext):
    amount = parse_amount(m.text)
    if amount is None:
        await m.answer("❌ Musbat son kiriting (masalan 0.5).")
        return
    tid = (await state.get_data())["task_id"]
    await services.set_task_reward(tid, amount)
    await state.clear()
    await m.answer(f"✅ #{tid} vazifa mukofoti: {stars(amount)}", reply_markup=admin_menu())


# ---------- majburiy kanallar ----------
@router.callback_query(F.data == "adm:req")
async def req_list(cb: CallbackQuery):
    items = await services.list_required()
    kb = InlineKeyboardBuilder()
    for ch in items:
        kb.button(text=f"🗑 {ch.title}", callback_data=f"adm:reqdel:{ch.id}")
    kb.button(text="➕ Kanal qo'shish", callback_data="adm:reqadd")
    kb.button(text="⬅️ Admin menyu", callback_data="adm:menu")
    kb.adjust(1)
    text = "📢 <b>Majburiy kanallar</b>\n" + ("\n".join(f"• {esc(c.title)}" for c in items) if items else "Hozircha yo'q.")
    await cb.answer()
    await safe_edit(cb, text, kb.as_markup())


@router.callback_query(F.data.regexp(r"^adm:reqdel:\d+$"))
async def req_delete(cb: CallbackQuery):
    await services.delete_required(int(cb.data.split(":")[2]))
    await cb.answer("O'chirildi")
    await req_list(cb)


@router.callback_query(F.data == "adm:reqadd")
async def req_add(cb: CallbackQuery, state: FSMContext):
    await state.set_state(A.req_channel)
    await cb.answer()
    await safe_edit(cb, "📢 Majburiy kanal @username yoki ID yuboring. Bot kanalda admin bo'lsin.\nBekor qilish: /cancel")


@router.message(A.req_channel, F.text)
async def req_add_msg(m: Message, state: FSMContext, bot: Bot):
    res = await _resolve_channel(m, bot)
    if res is None:
        return
    chat, url = res
    await services.add_required(str(chat.id), chat.title or str(chat.id), url)
    await state.clear()
    await m.answer(f"✅ Majburiy kanal qo'shildi: {esc(chat.title or str(chat.id))}", reply_markup=admin_menu())


# ---------- balans ----------
@router.callback_query(F.data == "adm:bal")
async def bal_ask(cb: CallbackQuery, state: FSMContext):
    await state.set_state(A.bal_user)
    await cb.answer()
    await safe_edit(cb, "👤 Foydalanuvchi Telegram ID raqamini yuboring. Bekor qilish: /cancel")


@router.message(A.bal_user, F.text)
async def bal_user(m: Message, state: FSMContext):
    if not m.text.strip().isdigit():
        await m.answer("❌ ID faqat raqamlardan iborat bo'lishi kerak.")
        return
    uid = int(m.text.strip())
    user = await services.get_user(uid)
    if user is None:
        await m.answer("❌ Bunday foydalanuvchi topilmadi. Boshqa ID yuboring yoki /cancel.")
        return
    await state.update_data(uid=uid)
    await state.set_state(A.bal_amount)
    await m.answer(f"👤 {esc(user.full_name)} — balans: {stars(user.balance)}\n"
                   "Miqdorni yuboring: <code>+5</code> qo'shadi, <code>-2</code> ayiradi. Bekor qilish: /cancel")


@router.message(A.bal_amount, F.text)
async def bal_amount(m: Message, state: FSMContext, bot: Bot):
    delta = parse_amount(m.text, allow_negative=True)
    if delta is None:
        await m.answer("❌ Noto'g'ri son. Masalan: +5 yoki -2")
        return
    uid = (await state.get_data())["uid"]
    try:
        new = await services.adjust_balance(uid, delta)
    except ValueError as e:
        await m.answer("❌ Balans manfiy bo'lib qoladi." if str(e) == "insufficient" else "❌ Foydalanuvchi topilmadi.")
        return
    await state.clear()
    await m.answer(f"✅ Yangi balans: {stars(new)}", reply_markup=admin_menu())
    try:
        await bot.send_message(uid, f"ℹ️ Balansingiz admin tomonidan o'zgartirildi: {'+' if delta > 0 else ''}{stars(delta)}.\n"
                                    f"Joriy balans: {stars(new)}")
    except TelegramAPIError:
        pass


# ---------- pul yechish arizalari ----------
def _wd_kb(wid: int):
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Tasdiqlash", callback_data=f"wd:ok:{wid}")
    kb.button(text="❌ Rad etish", callback_data=f"wd:no:{wid}")
    return kb.as_markup()


@router.callback_query(F.data == "adm:wd")
async def wd_list(cb: CallbackQuery):
    items = await services.list_pending_withdrawals()
    await cb.answer()
    await safe_edit(cb, f"💸 Kutilayotgan arizalar: {len(items)}", back_kb())
    for wd in items:
        user = await services.get_user(wd.user_id)
        name = esc(user.full_name) if user else "—"
        await cb.message.answer(f"💸 <b>Ariza #{wd.id}</b>\n👤 {name}\n🆔 <code>{wd.user_id}</code>\n"
                                f"💰 {stars(wd.amount)}\n📝 {esc(wd.details)}", reply_markup=_wd_kb(wd.id))


@router.callback_query(F.data.regexp(r"^wd:(ok|no):\d+$"))
async def wd_resolve(cb: CallbackQuery, bot: Bot):
    _, act, wid = cb.data.split(":")
    approve = act == "ok"
    wd = await services.resolve_withdrawal(int(wid), approve)
    if wd is None:
        await cb.answer("Bu ariza allaqachon ko'rib chiqilgan", show_alert=True)
        return
    await cb.answer("Bajarildi")
    verdict = "✅ Tasdiqlandi" if approve else "❌ Rad etildi (balans qaytarildi)"
    try:
        await cb.message.edit_text(f"{cb.message.html_text}\n\n<b>{verdict}</b>", reply_markup=None)
    except TelegramAPIError:
        pass
    try:
        if approve:
            await bot.send_message(wd.user_id, f"✅ Ariza #{wd.id} tasdiqlandi: {stars(wd.amount)} to'lanadi.")
        else:
            await bot.send_message(wd.user_id, f"❌ Ariza #{wd.id} rad etildi. {stars(wd.amount)} balansingizga qaytarildi.")
    except TelegramAPIError:
        pass


# ---------- sozlamalar ----------
@router.callback_query(F.data == "adm:set")
async def settings(cb: CallbackQuery):
    reward = await services.get_default_reward()
    min_w = await services.get_min_withdraw()
    kb = InlineKeyboardBuilder()
    kb.button(text="🎁 Yangi vazifa mukofoti", callback_data="adm:setreward")
    kb.button(text="💸 Minimal yechish", callback_data="adm:setmin")
    kb.button(text="⬅️ Admin menyu", callback_data="adm:menu")
    kb.adjust(1)
    await cb.answer()
    await safe_edit(cb, (f"⚙️ <b>Sozlamalar</b>\n\nYangi vazifalar uchun standart mukofot: {stars(reward)}\n"
                         f"Minimal yechish: {stars(min_w)}"), kb.as_markup())


@router.callback_query(F.data == "adm:setreward")
async def setreward_ask(cb: CallbackQuery, state: FSMContext):
    await state.set_state(A.set_reward)
    await cb.answer()
    await safe_edit(cb, "🎁 Yangi vazifalar uchun standart mukofotni yuboring (masalan 0.5). Mavjud vazifalar o'zgarmaydi. /cancel")


@router.message(A.set_reward, F.text)
async def setreward(m: Message, state: FSMContext):
    v = parse_amount(m.text)
    if v is None:
        await m.answer("❌ Musbat son kiriting.")
        return
    await services.set_setting("default_reward", str(v))
    await state.clear()
    await m.answer(f"✅ Standart mukofot: {stars(v)}", reply_markup=admin_menu())


@router.callback_query(F.data == "adm:setmin")
async def setmin_ask(cb: CallbackQuery, state: FSMContext):
    await state.set_state(A.set_min)
    await cb.answer()
    await safe_edit(cb, "💸 Minimal yechish miqdorini yuboring (masalan 15). /cancel")


@router.message(A.set_min, F.text)
async def setmin(m: Message, state: FSMContext):
    v = parse_amount(m.text)
    if v is None:
        await m.answer("❌ Musbat son kiriting.")
        return
    await services.set_setting("min_withdraw", str(v))
    await state.clear()
    await m.answer(f"✅ Minimal yechish: {stars(v)}", reply_markup=admin_menu())
