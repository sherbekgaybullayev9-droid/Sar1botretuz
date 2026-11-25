"""Alembic (Operations/MigrationContext) asosidagi migratsiyalar — alohida papkasiz.

Joriy versiya `alembic_version` jadvalida saqlanadi. Yangi migratsiya qo'shish uchun
funksiya yozing va MIGRATIONS ro'yxatining oxiriga qo'shing.
"""
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


def _m0001(op) -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column("username", sa.String(64), nullable=True),
        sa.Column("full_name", sa.String(256), nullable=False),
        sa.Column("balance", sa.Numeric(12, 2), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "tasks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("title", sa.String(256), nullable=False),
        sa.Column("target", sa.String(256), nullable=False),
        sa.Column("url", sa.String(512), nullable=False),
        sa.Column("reward", sa.Numeric(8, 2), nullable=False),
        sa.Column("active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "completions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("reward", sa.Numeric(8, 2), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "task_id", name="uq_completion_user_task"),
    )
    op.create_index("ix_completions_user_id", "completions", ["user_id"])
    op.create_table(
        "withdrawals",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("details", sa.Text(), nullable=False),
        sa.Column("status", sa.String(16), server_default="pending", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_withdrawals_user_id", "withdrawals", ["user_id"])
    op.create_table(
        "required_channels",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("chat", sa.String(64), nullable=False),
        sa.Column("title", sa.String(256), nullable=False),
        sa.Column("url", sa.String(512), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "settings",
        sa.Column("key", sa.String(64), nullable=False),
        sa.Column("value", sa.String(256), nullable=False),
        sa.PrimaryKeyConstraint("key"),
    )


MIGRATIONS = [("0001", _m0001)]


def upgrade(connection) -> None:
    """Sinxron funksiya: `await conn.run_sync(migrations.upgrade)` orqali chaqiriladi."""
    connection.execute(sa.text(
        "CREATE TABLE IF NOT EXISTS alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY)"))
    row = connection.execute(sa.text("SELECT version_num FROM alembic_version")).first()
    current = row[0] if row else None
    revisions = [r for r, _ in MIGRATIONS]
    start = revisions.index(current) + 1 if current in revisions else 0
    ctx = MigrationContext.configure(connection)
    op = Operations(ctx)
    for rev, fn in MIGRATIONS[start:]:
        fn(op)
        connection.execute(sa.text("DELETE FROM alembic_version"))
        connection.execute(sa.text("INSERT INTO alembic_version (version_num) VALUES (:v)"), {"v": rev})
