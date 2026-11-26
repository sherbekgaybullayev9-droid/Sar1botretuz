"""
Barcha ma'lumotlar bazasi amallari (psycopg2, sinxron).
"""
import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

import config
from database import get_cur

log = logging.getLogger("services")


# =====================================================================
# SOZLAMALAR
# =====================================================================

def get_setting(key: str, default: str) -> str:
    with get_cur() as cur:
        cur.execute("SELECT value FROM settings WHERE key = %s", (key,))
        row = cur.fetchone()
    return row["value"] if row else default


def set_setting(key: str, value: str) -> None:
    with get_cur() as cur:
        cur.execute("""
            INSERT INTO settings (key, value) VALUES (%s, %s)
            ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
        """, (key, value))


def get_default_reward() -> Decimal:
    return Decimal(get_setting("default_reward", str(config.DEFAULT_REWARD)))


def get_min_withdraw() -> Decimal:
    return Decimal(get_setting("min_withdraw", str(config.MIN_WITHDRAW)))


def get_daily_bonus() -> Decimal:
    return Decimal(get_setting("daily_bonus", str(config.DAILY_BONUS)))


def get_referral_reward() -> Decimal:
    return Decimal(get_setting("referral_reward", str(config.REFERRAL_REWARD)))


# =====================================================================
# FOYDALANUVCHILAR
# =====================================================================

def upsert_user(user_id: int, username: Optional[str], full_name: str) -> None:
    with get_cur() as cur:
        cur.execute("""
            INSERT INTO users (id, username, full_name)
            VALUES (%s, %s, %s)
            ON CONFLICT (id) DO UPDATE
                SET username  = EXCLUDED.username,
                    full_name = EXCLUDED.full_name
        """, (user_id, username, full_name))


def get_user(user_id: int) -> Optional[dict]:
    with get_cur() as cur:
        cur.execute("SELECT * FROM users WHERE id = %s", (user_id,))
        return cur.fetchone()


def adjust_balance(user_id: int, delta: Decimal) -> Decimal:
    """Balansni o'zgartiradi. Yetarli bo'lmasa ValueError ko'taradi."""
    with get_cur() as cur:
        cur.execute("SELECT balance FROM users WHERE id = %s FOR UPDATE", (user_id,))
        row = cur.fetchone()
        if row is None:
            raise ValueError("no_user")
        new_bal = Decimal(str(row["balance"])) + delta
        if new_bal < 0:
            raise ValueError("insufficient")
        cur.execute("UPDATE users SET balance = %s WHERE id = %s", (new_bal, user_id))
    return new_bal


# =====================================================================
# MAJBURIY KANALLAR
# =====================================================================

def list_required() -> list:
    with get_cur() as cur:
        cur.execute("SELECT * FROM required_channels ORDER BY id")
        return cur.fetchall()


def add_required(chat: str, title: str, url: str) -> None:
    with get_cur() as cur:
        cur.execute(
            "INSERT INTO required_channels (chat, title, url) VALUES (%s, %s, %s)",
            (chat, title, url),
        )


def delete_required(rid: int) -> None:
    with get_cur() as cur:
        cur.execute("DELETE FROM required_channels WHERE id = %s", (rid,))


# =====================================================================
# VAZIFALAR
# =====================================================================

def add_task(kind: str, title: str, target: str, url: str,
             reward: Optional[Decimal] = None) -> dict:
    if reward is None:
        reward = get_default_reward()
    with get_cur() as cur:
        cur.execute("""
            INSERT INTO tasks (kind, title, target, url, reward)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING *
        """, (kind, title[:250], target, url, reward))
        return cur.fetchone()


def list_tasks() -> list:
    with get_cur() as cur:
        cur.execute("SELECT * FROM tasks ORDER BY id")
        return cur.fetchall()


def get_task(task_id: int) -> Optional[dict]:
    with get_cur() as cur:
        cur.execute("SELECT * FROM tasks WHERE id = %s", (task_id,))
        return cur.fetchone()


def available_tasks(user_id: int) -> list:
    with get_cur() as cur:
        cur.execute("""
            SELECT t.* FROM tasks t
            WHERE t.active = TRUE
              AND t.id NOT IN (
                  SELECT task_id FROM completions WHERE user_id = %s
              )
            ORDER BY t.id
        """, (user_id,))
        return cur.fetchall()


def is_completed(user_id: int, task_id: int) -> bool:
    with get_cur() as cur:
        cur.execute(
            "SELECT 1 FROM completions WHERE user_id = %s AND task_id = %s",
            (user_id, task_id),
        )
        return cur.fetchone() is not None


def completed_count(user_id: int) -> int:
    with get_cur() as cur:
        cur.execute("SELECT COUNT(*) AS cnt FROM completions WHERE user_id = %s", (user_id,))
        return cur.fetchone()["cnt"]


def task_completions_count(task_id: int) -> int:
    with get_cur() as cur:
        cur.execute("SELECT COUNT(*) AS cnt FROM completions WHERE task_id = %s", (task_id,))
        return cur.fetchone()["cnt"]


def complete_task(user_id: int, task_id: int) -> Optional[Decimal]:
    """Vazifani bajaradi va mukofot beradi. Takroriy/faolsiz bo'lsa None."""
    with get_cur() as cur:
        cur.execute("SELECT * FROM tasks WHERE id = %s AND active = TRUE", (task_id,))
        task = cur.fetchone()
        if task is None:
            return None
        cur.execute("""
            INSERT INTO completions (user_id, task_id, reward)
            VALUES (%s, %s, %s)
            ON CONFLICT (user_id, task_id) DO NOTHING
            RETURNING id
        """, (user_id, task_id, task["reward"]))
        if cur.fetchone() is None:
            return None  # allaqachon bajarilgan
        cur.execute(
            "UPDATE users SET balance = balance + %s WHERE id = %s",
            (task["reward"], user_id),
        )
        return Decimal(str(task["reward"]))


def mark_opened(user_id: int, task_id: int) -> None:
    with get_cur() as cur:
        cur.execute("""
            INSERT INTO task_opens (user_id, task_id) VALUES (%s, %s)
            ON CONFLICT (user_id, task_id) DO UPDATE SET opened_at = NOW()
        """, (user_id, task_id))


def seconds_since_opened(user_id: int, task_id: int) -> Optional[float]:
    with get_cur() as cur:
        cur.execute("""
            SELECT EXTRACT(EPOCH FROM (NOW() - opened_at)) AS s
            FROM task_opens WHERE user_id = %s AND task_id = %s
        """, (user_id, task_id))
        row = cur.fetchone()
    return float(row["s"]) if row else None


def toggle_task(task_id: int) -> None:
    with get_cur() as cur:
        cur.execute(
            "UPDATE tasks SET active = NOT active WHERE id = %s",
            (task_id,),
        )


def set_task_reward(task_id: int, reward: Decimal) -> None:
    with get_cur() as cur:
        cur.execute("UPDATE tasks SET reward = %s WHERE id = %s", (reward, task_id))


def delete_task(task_id: int) -> None:
    with get_cur() as cur:
        cur.execute("DELETE FROM tasks WHERE id = %s", (task_id,))


# =====================================================================
# PUL YECHISH
# =====================================================================

def create_withdrawal(user_id: int, amount: Decimal, details: str,
                      gift: Optional[str] = None,
                      recipient: Optional[str] = None) -> Optional[dict]:
    with get_cur() as cur:
        cur.execute("""
            UPDATE users SET balance = balance - %s
            WHERE id = %s AND balance >= %s
            RETURNING id
        """, (amount, user_id, amount))
        if cur.fetchone() is None:
            return None
        cur.execute("""
            INSERT INTO withdrawals (user_id, amount, details, gift, recipient)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING *
        """, (user_id, amount, details[:500], gift, recipient))
        return cur.fetchone()


def list_pending_withdrawals(limit: int = 20) -> list:
    with get_cur() as cur:
        cur.execute(
            "SELECT * FROM withdrawals WHERE status = 'pending' ORDER BY id LIMIT %s",
            (limit,),
        )
        return cur.fetchall()


def resolve_withdrawal(wid: int, approve: bool) -> Optional[dict]:
    with get_cur() as cur:
        cur.execute(
            "SELECT * FROM withdrawals WHERE id = %s FOR UPDATE",
            (wid,),
        )
        wd = cur.fetchone()
        if wd is None or wd["status"] != "pending":
            return None
        new_status = "approved" if approve else "rejected"
        cur.execute("""
            UPDATE withdrawals
            SET status = %s, processed_at = NOW()
            WHERE id = %s
        """, (new_status, wid))
        if not approve:
            cur.execute(
                "UPDATE users SET balance = balance + %s WHERE id = %s",
                (wd["amount"], wd["user_id"]),
            )
    return wd


# =====================================================================
# REFERAL
# =====================================================================

def set_referrer(user_id: int, referrer_id: int) -> bool:
    """Yangi foydalanuvchiga taklif qilgan odamni biriktiradi (o'zini o'zi emas, faqat bir marta)."""
    if user_id == referrer_id:
        return False
    with get_cur() as cur:
        cur.execute("""
            UPDATE users SET referrer_id = %s
            WHERE id = %s AND referrer_id IS NULL
              AND EXISTS (SELECT 1 FROM users WHERE id = %s)
            RETURNING id
        """, (referrer_id, user_id, referrer_id))
        return cur.fetchone() is not None


def reward_referral(user_id: int):
    """
    Taklif qilingan do'st majburiy obunadan o'tganda chaqiriladi.
    Mukofot bir marta beriladi: (referrer_id, summa) yoki None.
    """
    amount = get_referral_reward()
    with get_cur() as cur:
        cur.execute("""
            UPDATE users SET ref_rewarded = TRUE, ref_paid = %s
            WHERE id = %s AND referrer_id IS NOT NULL AND ref_rewarded = FALSE
            RETURNING referrer_id
        """, (amount, user_id))
        row = cur.fetchone()
        if row is None:
            return None
        cur.execute(
            "UPDATE users SET balance = balance + %s WHERE id = %s",
            (amount, row["referrer_id"]),
        )
        return row["referrer_id"], amount


def referral_stats(user_id: int) -> dict:
    with get_cur() as cur:
        cur.execute("""
            SELECT COUNT(*) AS invited,
                   COUNT(*) FILTER (WHERE ref_rewarded) AS passed,
                   COALESCE(SUM(ref_paid), 0) AS earned
            FROM users WHERE referrer_id = %s
        """, (user_id,))
        r = cur.fetchone()
    return {"invited": r["invited"], "passed": r["passed"], "earned": Decimal(str(r["earned"]))}


# =====================================================================
# KUNLIK BONUS (Toshkent vaqti bilan kun almashadi)
# =====================================================================

def claim_daily_bonus(user_id: int):
    """
    Bonus berilsa (Decimal, None), allaqachon olingan bo'lsa (None, qolgan_soniya).
    Bitta UPDATE — poyga holatida ham ikki marta berilmaydi.
    """
    amount = get_daily_bonus()
    with get_cur() as cur:
        cur.execute("""
            UPDATE users
            SET balance = balance + %s,
                last_bonus_date = (NOW() AT TIME ZONE 'Asia/Tashkent')::date
            WHERE id = %s
              AND (last_bonus_date IS NULL
                   OR last_bonus_date < (NOW() AT TIME ZONE 'Asia/Tashkent')::date)
            RETURNING id
        """, (amount, user_id))
        if cur.fetchone() is not None:
            return amount, None
        cur.execute("""
            SELECT EXTRACT(EPOCH FROM (
                date_trunc('day', NOW() AT TIME ZONE 'Asia/Tashkent') + INTERVAL '1 day'
                - (NOW() AT TIME ZONE 'Asia/Tashkent')
            )) AS s
        """)
        return None, float(cur.fetchone()["s"])


# =====================================================================
# FOYDALANUVCHILAR RO'YXATI / BROADCAST
# =====================================================================

def count_users() -> int:
    with get_cur() as cur:
        cur.execute("SELECT COUNT(*) AS cnt FROM users")
        return cur.fetchone()["cnt"]


def list_users(offset: int, limit: int) -> list:
    with get_cur() as cur:
        cur.execute(
            "SELECT * FROM users ORDER BY created_at DESC, id DESC OFFSET %s LIMIT %s",
            (offset, limit),
        )
        return cur.fetchall()


def all_user_ids() -> list:
    with get_cur() as cur:
        cur.execute("SELECT id FROM users ORDER BY id")
        return [r["id"] for r in cur.fetchall()]


# =====================================================================
# STATISTIKA
# =====================================================================

def stats() -> dict:
    with get_cur() as cur:
        cur.execute("SELECT COUNT(*) AS cnt FROM users")
        users = cur.fetchone()["cnt"]

        cur.execute("SELECT COUNT(*) AS cnt FROM tasks")
        tasks_all = cur.fetchone()["cnt"]

        cur.execute("SELECT COUNT(*) AS cnt FROM tasks WHERE active = TRUE")
        tasks_active = cur.fetchone()["cnt"]

        cur.execute("SELECT COUNT(*) AS cnt FROM completions")
        done = cur.fetchone()["cnt"]

        cur.execute("SELECT COALESCE(SUM(balance), 0) AS s FROM users")
        balances = Decimal(str(cur.fetchone()["s"]))

        cur.execute("""
            SELECT COUNT(*) AS cnt, COALESCE(SUM(amount), 0) AS s
            FROM withdrawals WHERE status = 'pending'
        """)
        pend = cur.fetchone()

        cur.execute("""
            SELECT COALESCE(SUM(amount), 0) AS s
            FROM withdrawals WHERE status = 'approved'
        """)
        paid = Decimal(str(cur.fetchone()["s"]))

    return {
        "users": users,
        "tasks_all": tasks_all,
        "tasks_active": tasks_active,
        "done": done,
        "balances": balances,
        "pending_count": pend["cnt"],
        "pending_sum": Decimal(str(pend["s"])),
        "paid": paid,
    }
