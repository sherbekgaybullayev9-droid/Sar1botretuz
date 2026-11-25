import asyncio
import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import List, Optional

from sqlalchemy import delete, func, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError

import config
import migrations
from database import (Completion, RequiredChannel, Session, Setting, Task, User,
                      Withdrawal, engine)
from utils import is_member

log = logging.getLogger("services")
MIGRATION_LOCK_ID = 727001


# ---------- migratsiya ----------
async def run_startup_migrations() -> None:
    # advisory lock: bir nechta instansiya bir vaqtda migratsiya qilmasligi uchun
    async with engine.connect() as lock_conn:
        await lock_conn.execute(text("SELECT pg_advisory_lock(:i)"), {"i": MIGRATION_LOCK_ID})
        try:
            async with engine.begin() as conn:
                await conn.run_sync(migrations.upgrade)
        finally:
            await lock_conn.execute(text("SELECT pg_advisory_unlock(:i)"), {"i": MIGRATION_LOCK_ID})


async def db_ping() -> None:
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))


# ---------- sozlamalar ----------
async def get_setting(key: str, default: str) -> str:
    async with Session() as s:
        v = await s.scalar(select(Setting.value).where(Setting.key == key))
    return v if v is not None else default


async def set_setting(key: str, value: str) -> None:
    async with Session() as s, s.begin():
        stmt = pg_insert(Setting).values(key=key, value=value).on_conflict_do_update(
            index_elements=[Setting.key], set_={"value": value})
        await s.execute(stmt)


async def get_default_reward() -> Decimal:
    return Decimal(await get_setting("default_reward", str(config.DEFAULT_REWARD)))


async def get_min_withdraw() -> Decimal:
    return Decimal(await get_setting("min_withdraw", str(config.MIN_WITHDRAW)))


# ---------- foydalanuvchilar ----------
async def upsert_user(tg_user) -> None:
    async with Session() as s, s.begin():
        stmt = pg_insert(User).values(
            id=tg_user.id, username=tg_user.username, full_name=tg_user.full_name or ""
        ).on_conflict_do_update(
            index_elements=[User.id],
            set_={"username": tg_user.username, "full_name": tg_user.full_name or ""})
        await s.execute(stmt)


async def get_user(user_id: int) -> Optional[User]:
    async with Session() as s:
        return await s.get(User, user_id)


async def adjust_balance(user_id: int, delta: Decimal) -> Decimal:
    """Balansni o'zgartiradi. ValueError('no_user') yoki ValueError('insufficient') ko'tarishi mumkin."""
    async with Session() as s, s.begin():
        user = await s.scalar(select(User).where(User.id == user_id).with_for_update())
        if user is None:
            raise ValueError("no_user")
        new = user.balance + delta
        if new < 0:
            raise ValueError("insufficient")
        user.balance = new
    return new


# ---------- majburiy kanallar ----------
async def list_required() -> List[RequiredChannel]:
    async with Session() as s:
        return list((await s.scalars(select(RequiredChannel).order_by(RequiredChannel.id))).all())


async def add_required(chat: str, title: str, url: str) -> None:
    async with Session() as s, s.begin():
        s.add(RequiredChannel(chat=chat, title=title, url=url))


async def delete_required(rid: int) -> None:
    async with Session() as s, s.begin():
        await s.execute(delete(RequiredChannel).where(RequiredChannel.id == rid))


async def missing_channels(bot, user_id: int) -> List[RequiredChannel]:
    missing = []
    for ch in await list_required():
        # API xatosida (bot kanalda admin emas va h.k.) foydalanuvchini qulflab qo'ymaymiz
        if not await is_member(bot, ch.chat, user_id, on_error=True):
            missing.append(ch)
    return missing


# ---------- vazifalar ----------
async def add_task(kind: str, title: str, target: str, url: str) -> Task:
    reward = await get_default_reward()
    async with Session() as s, s.begin():
        task = Task(kind=kind, title=title[:250], target=target, url=url, reward=reward)
        s.add(task)
        await s.flush()
        await s.refresh(task)
    return task


async def list_tasks() -> List[Task]:
    async with Session() as s:
        return list((await s.scalars(select(Task).order_by(Task.id))).all())


async def get_task(task_id: int) -> Optional[Task]:
    async with Session() as s:
        return await s.get(Task, task_id)


async def available_tasks(user_id: int) -> List[Task]:
    done = select(Completion.task_id).where(Completion.user_id == user_id)
    async with Session() as s:
        q = select(Task).where(Task.active.is_(True), Task.id.not_in(done)).order_by(Task.id)
        return list((await s.scalars(q)).all())


async def is_completed(user_id: int, task_id: int) -> bool:
    async with Session() as s:
        return await s.scalar(select(Completion.id).where(
            Completion.user_id == user_id, Completion.task_id == task_id)) is not None


async def completed_count(user_id: int) -> int:
    async with Session() as s:
        return int(await s.scalar(select(func.count(Completion.id)).where(Completion.user_id == user_id)) or 0)


async def task_completions(task_id: int) -> int:
    async with Session() as s:
        return int(await s.scalar(select(func.count(Completion.id)).where(Completion.task_id == task_id)) or 0)


async def complete_task(user_id: int, task_id: int) -> Optional[Decimal]:
    """Vazifa uchun mukofot beradi. Takroriy/yaroqsiz bo'lsa None."""
    try:
        async with Session() as s, s.begin():
            task = await s.get(Task, task_id)
            if task is None or not task.active:
                return None
            exists = await s.scalar(select(Completion.id).where(
                Completion.user_id == user_id, Completion.task_id == task_id))
            if exists is not None:
                return None
            s.add(Completion(user_id=user_id, task_id=task_id, reward=task.reward))
            await s.execute(update(User).where(User.id == user_id).values(balance=User.balance + task.reward))
            reward = task.reward
        return reward
    except IntegrityError:
        return None


async def toggle_task(task_id: int) -> None:
    async with Session() as s, s.begin():
        await s.execute(update(Task).where(Task.id == task_id).values(active=~Task.active))


async def set_task_reward(task_id: int, reward: Decimal) -> None:
    async with Session() as s, s.begin():
        await s.execute(update(Task).where(Task.id == task_id).values(reward=reward))


async def delete_task(task_id: int) -> None:
    async with Session() as s, s.begin():
        await s.execute(delete(Task).where(Task.id == task_id))


# ---------- pul yechish ----------
async def create_withdrawal(user_id: int, amount: Decimal, details: str) -> Optional[Withdrawal]:
    async with Session() as s, s.begin():
        res = await s.execute(
            update(User).where(User.id == user_id, User.balance >= amount)
            .values(balance=User.balance - amount).returning(User.id))
        if res.scalar_one_or_none() is None:
            return None
        wd = Withdrawal(user_id=user_id, amount=amount, details=details)
        s.add(wd)
        await s.flush()
        await s.refresh(wd)
    return wd


async def list_pending_withdrawals(limit: int = 20) -> List[Withdrawal]:
    async with Session() as s:
        q = select(Withdrawal).where(Withdrawal.status == "pending").order_by(Withdrawal.id).limit(limit)
        return list((await s.scalars(q)).all())


async def resolve_withdrawal(wid: int, approve: bool) -> Optional[Withdrawal]:
    async with Session() as s, s.begin():
        wd = await s.scalar(select(Withdrawal).where(Withdrawal.id == wid).with_for_update())
        if wd is None or wd.status != "pending":
            return None
        wd.status = "approved" if approve else "rejected"
        wd.processed_at = datetime.now(timezone.utc)
        if not approve:  # rad etilsa balans qaytariladi
            await s.execute(update(User).where(User.id == wd.user_id).values(balance=User.balance + wd.amount))
    return wd


# ---------- statistika ----------
async def stats() -> dict:
    async with Session() as s:
        zero = Decimal("0")
        users = await s.scalar(select(func.count(User.id)))
        balances = await s.scalar(select(func.coalesce(func.sum(User.balance), 0)))
        tasks_all = await s.scalar(select(func.count(Task.id)))
        tasks_active = await s.scalar(select(func.count(Task.id)).where(Task.active.is_(True)))
        done = await s.scalar(select(func.count(Completion.id)))
        pend = (await s.execute(select(func.count(Withdrawal.id), func.coalesce(func.sum(Withdrawal.amount), 0))
                                .where(Withdrawal.status == "pending"))).one()
        paid = await s.scalar(select(func.coalesce(func.sum(Withdrawal.amount), 0))
                              .where(Withdrawal.status == "approved"))
    return {"users": users or 0, "balances": Decimal(balances or zero), "tasks_all": tasks_all or 0,
            "tasks_active": tasks_active or 0, "done": done or 0, "pending_count": pend[0],
            "pending_sum": Decimal(pend[1] or zero), "paid": Decimal(paid or zero)}
