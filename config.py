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


def _base_url() -> str:
    """
    Webhook uchun Render manzili. Tartib:
    WEBHOOK_URL -> RENDER_URL -> RENDER_EXTERNAL_URL (Render o'zi beradi).
    To'liq webhook manzili kiritilgan bo'lsa ham, faqat asosiy qismi olinadi.
    """
    for name in ("WEBHOOK_URL", "RENDER_URL", "RENDER_EXTERNAL_URL"):
        v = os.getenv(name, "").strip().rstrip("/")
        if not v:
            continue
        if not v.startswith(("http://", "https://")):
            v = "https://" + v
        return v.split("/webhook")[0].rstrip("/")
    return ""


BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_ID = _int("ADMIN_ID")
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
PORT = _int("PORT", 10000)
START_WAIT_SECONDS = _int("START_WAIT_SECONDS", 15)
BASE_URL = _base_url()
KEEPALIVE = os.getenv("KEEPALIVE", "1").strip() != "0"
AUTO_BACKUP = os.getenv("AUTO_BACKUP", "1").strip() != "0"

# Telegram secret_token: faqat A-Z a-z 0-9 _ - (1..256 belgi)
_secret = re.sub(r"[^A-Za-z0-9_-]", "", os.getenv("WEBHOOK_SECRET", "").strip())
if not _secret and BOT_TOKEN:
    _secret = hashlib.sha256(("wh:" + BOT_TOKEN).encode()).hexdigest()[:48]
WEBHOOK_SECRET = _secret[:256]
WEBHOOK_PATH = f"/webhook/{WEBHOOK_SECRET}"

DEFAULT_REWARD = Decimal("0.5")
MIN_WITHDRAW = Decimal("15")
DAILY_BONUS = Decimal("0.3")
REFERRAL_REWARD = Decimal("0.3")


def validate() -> None:
    problems = []
    if not BOT_TOKEN:
        problems.append("BOT_TOKEN kiritilmagan")
    if not ADMIN_ID:
        problems.append("ADMIN_ID kiritilmagan yoki noto'g'ri")
    if not DATABASE_URL:
        problems.append("DATABASE_URL kiritilmagan")
    if problems:
        raise RuntimeError("Sozlama xatosi: " + "; ".join(problems))
