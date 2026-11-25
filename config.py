import hashlib
import os
import re
from decimal import Decimal

from dotenv import load_dotenv

load_dotenv()


def _int(name: str, default: int = 0) -> int:
    try:
        return int(os.getenv(name, str(default)) or default)
    except ValueError:
        return default


BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_ID = _int("ADMIN_ID")
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
PORT = _int("PORT", 10000)
START_WAIT_SECONDS = _int("START_WAIT_SECONDS", 15)

_RAW_SECRET = os.getenv("WEBHOOK_SECRET", "").strip()
# Telegram secret_token faqat A-Z a-z 0-9 _ - (1..256) belgilarini qabul qiladi.
# Boshqa belgilar bo'lsa (masalan Render generateValue), SHA-256 hex'ga o'giramiz.
if _RAW_SECRET and re.fullmatch(r"[A-Za-z0-9_-]{1,256}", _RAW_SECRET):
    WEBHOOK_SECRET_TOKEN = _RAW_SECRET
elif _RAW_SECRET:
    WEBHOOK_SECRET_TOKEN = hashlib.sha256(_RAW_SECRET.encode()).hexdigest()
else:
    # Bo'sh secret bilan webhook ochiq qoladi — validate() buni xato sifatida qaytaradi
    WEBHOOK_SECRET_TOKEN = ""

_BASE = (os.getenv("WEBHOOK_URL") or os.getenv("RENDER_EXTERNAL_URL") or "").strip().rstrip("/")

DEFAULT_REWARD = Decimal("0.5")
MIN_WITHDRAW = Decimal("15")


def webhook_url() -> str:
    return _BASE if _BASE.endswith("/webhook") else _BASE + "/webhook"


def validate() -> None:
    problems = []
    if not BOT_TOKEN:
        problems.append("BOT_TOKEN kiritilmagan")
    if not ADMIN_ID:
        problems.append("ADMIN_ID kiritilmagan yoki noto'g'ri")
    if not WEBHOOK_SECRET_TOKEN:
        problems.append("WEBHOOK_SECRET kiritilmagan")
    if not DATABASE_URL:
        problems.append("DATABASE_URL kiritilmagan")
    if not _BASE.startswith("https://"):
        problems.append("WEBHOOK_URL (yoki RENDER_EXTERNAL_URL) https:// bilan boshlanishi kerak")
    if problems:
        raise RuntimeError("Sozlama xatosi: " + "; ".join(problems))
