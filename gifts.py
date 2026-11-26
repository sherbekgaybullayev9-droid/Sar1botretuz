"""Sovg'alar ro'yxati (Telegram gift narxlari, ⭐)."""
from typing import NamedTuple


class Gift(NamedTuple):
    key: str
    emoji: str
    name: str
    cost: int


GIFTS = [
    Gift("heart",     "💝", "Yurak",     15),
    Gift("bear",      "🧸", "Ayiqcha",   15),
    Gift("box",       "🎁", "Sovg'a",    25),
    Gift("rose",      "🌹", "Atirgul",   25),
    Gift("cake",      "🎂", "Tort",      50),
    Gift("bouquet",   "💐", "Guldasta",  50),
    Gift("rocket",    "🚀", "Raketa",    50),
    Gift("champagne", "🍾", "Shampan",   50),
    Gift("cup",       "🏆", "Kubok",    100),
    Gift("ring",      "💍", "Uzuk",     100),
    Gift("diamond",   "💎", "Olmos",    100),
]
BY_KEY = {g.key: g for g in GIFTS}
