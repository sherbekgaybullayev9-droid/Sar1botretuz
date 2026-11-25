import logging
import time
from decimal import Decimal

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (CallbackQuery, InlineKeyboardButton, KeyboardButton, Message,
                           ReplyKeyboardMarkup)
from aiogram.utils.keyboard import InlineKeyboardBuilder

import config
import services
from utils import esc, is_member, parse_amount, safe_edit, stars

log = logging.getLogger("user")
router = Router(name="user")

BTN_TASKS = "📋 Vazifalar"
BTN_BAL = "💰 Balans"
BTN_WD = "💸 Pul yechish"
BTN_HELP = "ℹ️ Yordam"

# START vazifasi: foydalanuvchi vazifani ochgan vaqt (jarayon xotirasida)
_opened = {}


def main_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=BTN_TASKS), KeyboardButton(text=BTN_BAL)],
                  [KeyboardButton(text=BTN_WD), KeyboardButton(text=BTN_HELP)]],
        resize_keyboard=True)


class WithdrawStates(StatesGroup):
    amount = State()
    details = State()


async def tasks_view(user_id: int):
    tasks = await services.available_tasks(user_id)
    if not tasks:
        return "🎉 Hozircha yangi vazifa yo'q. Keyinroq qaytib keling!", None
    kb = InlineKeyboardBuilder()
    for t in tasks:
        icon = "📢" if t.kind == "channel" else "🤖"
        kb.button(text=f"{icon} {t.title} · +{stars(t.reward)}", callback_data=f"task:{t.id}")
    kb.adjust(1)
    return "📋 <b>Mavjud vazifalar</b>\nBittasini tanlang:", kb.as_markup()


@router.message(CommandStart())
async def cmd_start(m: Message, state: FSMContext):
    await state.clear()
    await services.upsert_user(m.from_user)
    reward = await services.get_default_reward()
    min_w = await services.get_min_withdraw()
    await m.answer(
        f"👋 Salom, <b>{esc(m.from_user.full_name)}</b>!\n\n"
        f"Vazifalarni bajaring va ⭐ to'plang. Har bir vazifa uchun odatda {stars(reward)} beriladi.\n"
        f"Minimal yechish: {stars(min_w)}.",
        reply_markup=main_menu())


@router.message(Command("cancel"))
async def cmd_cancel(m: Message, state: FSMContext):
    await state.clear()
    await m.answer("Bekor qilindi.", reply_markup=main_menu())


@router.callback_query(F.data == "sub:check")
async def sub_check(cb: CallbackQuery, bot: Bot):
    missing = await services.missing_channels(bot, cb.from_user.id)
    if missing:
        await cb.answer("❌ Hali hamma kanallarga obuna bo'lmadingiz", show_alert=True)
        return
    await cb.answer("✅ Rahmat!")
    if cb.message:
        try:
            await cb.message.delete()
        except TelegramAPIError:
            pass
        await cb.message.answer("✅ Obuna tasdiqlandi. Marhamat, davom eting!", reply_markup=main_menu())


@router.message(F.text == BTN_TASKS)
async def show_tasks(m: Message, state: FSMContext):
    await state.clear()
    text, kb = await tasks_view(m.from_user.id)
    await m.answer(text, reply_markup=kb)


@router.callback_query(F.data == "tasks:list")
async def tasks_list(cb: CallbackQuery):
    text, kb = await tasks_view(cb.from_user.id)
    await cb.answer()
    await safe_edit(cb, text, kb)


@router.callback_query(F.data.startswith("task:"))
async def task_open(cb: CallbackQuery):
    task_id = int(cb.data.split(":")[1])
    task = await services.get_task(task_id)
    if task is None or not task.active:
        await cb.answer("Bu vazifa mavjud emas yoki to'xtatilgan", show_alert=True)
        return
    if await services.is_completed(cb.from_user.id, task_id):
        await cb.answer("Bu vazifa allaqachon bajarilgan", show_alert=True)
        return
    if task.kind == "channel":
        text = (f"📢 <b>{esc(task.title)}</b>\n\nKanalga obuna bo'ling, so'ng «✅ Tekshirish» tugmasini bosing.\n"
                f"🎁 Mukofot: {stars(task.reward)}")
    else:
        if len(_opened) > 5000:
            _opened.clear()
        _opened[(cb.from_user.id, task_id)] = time.monotonic()
        text = (f"🤖 <b>{esc(task.title)}</b>\n\nBotga o'ting va <b>START</b> bosing, so'ng bu yerga qaytib "
                f"«✅ Tekshirish» tugmasini bosing (kamida {config.START_WAIT_SECONDS} soniyadan keyin).\n"
                f"🎁 Mukofot: {stars(task.reward)}")
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="🔗 Ochish", url=task.url))
    kb.row(InlineKeyboardButton(text="✅ Tekshirish", callback_data=f"chk:{task_id}"))
    kb.row(InlineKeyboardButton(text="⬅️ Orqaga", callback_data="tasks:list"))
    await cb.answer()
    await safe_edit(cb, text, kb.as_markup())


@router.callback_query(F.data.startswith("chk:"))
async def task_check(cb: CallbackQuery, bot: Bot):
    uid = cb.from_user.id
    task_id = int(cb.data.split(":")[1])
    task = await services.get_task(task_id)
    if task is None or not task.active:
        await cb.answer("Bu vazifa mavjud emas yoki to'xtatilgan", show_alert=True)
        return
    if await services.is_completed(uid, task_id):
        await cb.answer("Bu vazifa allaqachon bajarilgan", show_alert=True)
        return

    if task.kind == "channel":
        if not await is_member(bot, task.target, uid, on_error=False):
            await cb.answer("❌ Siz hali kanalga obuna bo'lmagansiz", show_alert=True)
            return
    else:
        key = (uid, task_id)
        t0 = _opened.get(key)
        if t0 is None:
            _opened[key] = time.monotonic()
            await cb.answer("Avval «🔗 Ochish» orqali botga o'tib START bosing.", show_alert=True)
            return
        left = config.START_WAIT_SECONDS - (time.monotonic() - t0)
        if left > 0:
            await cb.answer(f"⏳ Botga START bosganingizdan so'ng {int(left) + 1} soniya kuting va qayta tekshiring.",
                            show_alert=True)
            return

    reward = await services.complete_task(uid, task_id)
    if reward is None:
        await cb.answer("Bu vazifa allaqachon bajarilgan", show_alert=True)
        return
    _opened.pop((uid, task_id), None)
    await cb.answer(f"✅ +{stars(reward)} balansingizga qo'shildi!", show_alert=True)
    text, kb = await tasks_view(uid)
    await safe_edit(cb, text, kb)


@router.message(F.text == BTN_BAL)
async def show_balance(m: Message, state: FSMContext):
    await state.clear()
    user = await services.get_user(m.from_user.id)
    done = await services.completed_count(m.from_user.id)
    min_w = await services.get_min_withdraw()
    bal = user.balance if user else Decimal("0")
    await m.answer(f"💰 <b>Balansingiz:</b> {stars(bal)}\n✅ Bajarilgan vazifalar: {done}\n"
                   f"💸 Minimal yechish: {stars(min_w)}")


@router.message(F.text == BTN_HELP)
async def show_help(m: Message, state: FSMContext):
    await state.clear()
    min_w = await services.get_min_withdraw()
    await m.answer("ℹ️ <b>Yordam</b>\n\n📋 Vazifalar — kanalga obuna bo'ling yoki botga START bosing.\n"
                   f"💰 Balans — to'plangan ⭐.\n💸 Pul yechish — {stars(min_w)} dan boshlab ariza yuboring.\n"
                   "/cancel — joriy amalni bekor qilish.")


@router.message(F.text == BTN_WD)
async def wd_start(m: Message, state: FSMContext):
    await state.clear()
    user = await services.get_user(m.from_user.id)
    min_w = await services.get_min_withdraw()
    bal = user.balance if user else Decimal("0")
    if bal < min_w:
        await m.answer(f"❌ Minimal yechish miqdori {stars(min_w)}. Sizning balansingiz: {stars(bal)}.")
        return
    await state.set_state(WithdrawStates.amount)
    await m.answer(f"💸 Qancha yechmoqchisiz? ({stars(min_w)} – {stars(bal)})\nBekor qilish: /cancel")


@router.message(WithdrawStates.amount, F.text)
async def wd_amount(m: Message, state: FSMContext):
    amount = parse_amount(m.text)
    user = await services.get_user(m.from_user.id)
    min_w = await services.get_min_withdraw()
    if amount is None or amount < min_w or user is None or amount > user.balance:
        await m.answer(f"❌ Noto'g'ri miqdor. {stars(min_w)} dan {stars(user.balance if user else 0)} gacha "
                       "son kiriting.")
        return
    await state.update_data(amount=str(amount))
    await state.set_state(WithdrawStates.details)
    await m.answer("✍️ Pul qabul qilish uchun ma'lumot yuboring (Telegram @username yoki rekvizit):")


@router.message(WithdrawStates.details, F.text)
async def wd_details(m: Message, state: FSMContext, bot: Bot):
    amount = Decimal((await state.get_data())["amount"])
    details = m.text.strip()[:500]
    wd = await services.create_withdrawal(m.from_user.id, amount, details)
    await state.clear()
    if wd is None:
        await m.answer("❌ Balansingiz yetarli emas.", reply_markup=main_menu())
        return
    await m.answer(f"✅ Ariza #{wd.id} qabul qilindi: {stars(amount)}.\nAdmin ko'rib chiqadi, natija haqida xabar beramiz.",
                   reply_markup=main_menu())
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Tasdiqlash", callback_data=f"wd:ok:{wd.id}")
    kb.button(text="❌ Rad etish", callback_data=f"wd:no:{wd.id}")
    uname = f"@{m.from_user.username}" if m.from_user.username else "—"
    try:
        await bot.send_message(
            config.ADMIN_ID,
            f"💸 <b>Yangi ariza #{wd.id}</b>\n👤 {esc(m.from_user.full_name)} ({uname})\n🆔 <code>{m.from_user.id}</code>\n"
            f"💰 Miqdor: {stars(amount)}\n📝 Ma'lumot: {esc(details)}",
            reply_markup=kb.as_markup())
    except TelegramAPIError:
        log.exception("Adminga xabar yuborib bo'lmadi")
