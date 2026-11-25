from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (BigInteger, Boolean, DateTime, ForeignKey, Integer, Numeric,
                        String, Text, UniqueConstraint, func, true)
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

import config


def engine_args(raw: Optional[str] = None):
    """Render'ning postgres:// / postgresql:// URL'ini SQLAlchemy asyncpg formatiga o'giradi."""
    url = make_url(raw or config.DATABASE_URL)
    query = dict(url.query)
    host = url.host or ""
    sslmode = query.get("sslmode")
    url = url.set(drivername="postgresql+asyncpg", query={})
    connect_args = {}
    if sslmode in {"require", "verify-ca", "verify-full"}:
        connect_args["ssl"] = "require"
    elif sslmode is None and "." in host and host not in {"localhost", "127.0.0.1"}:
        # Render'ning tashqi (external) hosti SSL talab qiladi; ichki host (nuqtasiz) talab qilmaydi.
        connect_args["ssl"] = "require"
    return url, connect_args


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    username: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    full_name: Mapped[str] = mapped_column(String(256), default="")
    balance: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"), server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Task(Base):
    __tablename__ = "tasks"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(16))  # "channel" | "start"
    title: Mapped[str] = mapped_column(String(256))
    target: Mapped[str] = mapped_column(String(256))
    url: Mapped[str] = mapped_column(String(512))
    reward: Mapped[Decimal] = mapped_column(Numeric(8, 2))
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Completion(Base):
    __tablename__ = "completions"
    __table_args__ = (UniqueConstraint("user_id", "task_id", name="uq_completion_user_task"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    task_id: Mapped[int] = mapped_column(Integer, ForeignKey("tasks.id", ondelete="CASCADE"))
    reward: Mapped[Decimal] = mapped_column(Numeric(8, 2))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Withdrawal(Base):
    __tablename__ = "withdrawals"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    details: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(16), default="pending", server_default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    processed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class RequiredChannel(Base):
    __tablename__ = "required_channels"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    chat: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(256))
    url: Mapped[str] = mapped_column(String(512))


class Setting(Base):
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(String(256))


_url, _connect_args = engine_args()
engine = create_async_engine(_url, connect_args=_connect_args, pool_pre_ping=True, pool_size=5, max_overflow=5)
Session = async_sessionmaker(engine, expire_on_commit=False)
