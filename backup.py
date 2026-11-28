"""
Zaxira nusxa (backup) va tiklash.
Backup — JSON (to'liq) + CSV (foydalanuvchilar, Excel uchun), adminga Telegram orqali yuboriladi.
Tiklash faqat YETISHMAYOTGAN foydalanuvchilarni qo'shadi (mavjudlarni o'zgartirmaydi).
"""
import csv
import io
import json
import logging
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from database import get_cur

log = logging.getLogger("backup")

TABLES = ["users", "tasks", "completions", "withdrawals", "required_channels", "settings"]


def build_backup() -> dict:
    data = {
        "version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "tables": {},
    }
    with get_cur() as cur:
        for t in TABLES:  # jadval nomlari doimiy ro'yxatdan
            cur.execute(f"SELECT * FROM {t} ORDER BY 1")
            data["tables"][t] = [dict(r) for r in cur.fetchall()]
    return data


def to_json_bytes(data: dict) -> bytes:
    return json.dumps(data, ensure_ascii=False, default=str, indent=1).encode("utf-8")


def _safe_cell(v) -> str:
    s = "" if v is None else str(v)
    return "'" + s if s[:1] in ("=", "+", "-", "@") else s


def users_csv_bytes(data: dict) -> bytes:
    cols = ["id", "username", "full_name", "balance", "created_at",
            "last_bonus_date", "referrer_id", "ref_rewarded", "ref_paid"]
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(cols)
    for u in data["tables"]["users"]:
        w.writerow([_safe_cell(u.get(c)) for c in cols])
    return buf.getvalue().encode("utf-8-sig")


def _named(data: bytes, name: str) -> io.BytesIO:
    f = io.BytesIO(data)
    f.name = name
    return f


def send_backup(bot, chat_id: int, auto: bool = False) -> int:
    data = build_backup()
    n = len(data["tables"]["users"])
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")
    bot.send_document(
        chat_id, _named(to_json_bytes(data), f"backup_{ts}.json"),
        caption=f"💾 {'Avtomatik b' if auto else 'B'}ackup · foydalanuvchilar: {n}",
    )
    bot.send_document(chat_id, _named(users_csv_bytes(data), f"users_{ts}.csv"))
    return n


def parse_users(raw: bytes) -> list:
    """Backup JSON'dan to'g'ri foydalanuvchi qatorlarini ajratadi."""
    payload = json.loads(raw.decode("utf-8-sig"))
    rows = (payload.get("tables") or {}).get("users") if isinstance(payload, dict) else None
    if rows is None and isinstance(payload, dict):
        rows = payload.get("users")
    if not isinstance(rows, list):
        raise ValueError("Faylda foydalanuvchilar topilmadi")
    out = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        try:
            uid = int(r["id"])
            balance = Decimal(str(r.get("balance") or 0))
            paid = Decimal(str(r.get("ref_paid") or 0))
            ref = r.get("referrer_id")
            ref = int(ref) if ref not in (None, "", "None") else None
        except (KeyError, ValueError, TypeError, InvalidOperation):
            continue
        if balance < 0:
            continue
        def _n(v):
            return None if v in (None, "", "None") else str(v)
        out.append((
            uid, _n(r.get("username")), str(r.get("full_name") or "")[:256], balance,
            _n(r.get("created_at")), _n(r.get("last_bonus_date")),
            ref, bool(r.get("ref_rewarded")), paid,
        ))
    return out


def restore_users(raw: bytes):
    """(qo'shildi, mavjud edi, noto'g'ri) sonlarini qaytaradi."""
    rows = parse_users(raw)
    total_in_file = len(rows)
    added = 0
    with get_cur() as cur:
        for row in rows:
            cur.execute("""
                INSERT INTO users (id, username, full_name, balance, created_at,
                                   last_bonus_date, referrer_id, ref_rewarded, ref_paid)
                VALUES (%s, %s, %s, %s, COALESCE(%s::timestamptz, NOW()), %s::date, %s, %s, %s)
                ON CONFLICT (id) DO NOTHING
            """, row)
            added += cur.rowcount
    return added, total_in_file - added
