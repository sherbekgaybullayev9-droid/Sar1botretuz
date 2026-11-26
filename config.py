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

DEFAULT_REWARD = Decimal("0.5")
MIN_WITHDRAW = Decimal("15")


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
