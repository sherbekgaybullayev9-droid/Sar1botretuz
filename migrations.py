"""
Oddiy migratsiya tizimi — alembic shart emas.
Versiya `schema_version` jadvalida saqlanadi.
"""
import logging

from database import get_conn

log = logging.getLogger("migrations")


def _m0001(cur) -> None:
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id          BIGINT PRIMARY KEY,
            username    VARCHAR(64),
            full_name   VARCHAR(256) NOT NULL DEFAULT '',
            balance     NUMERIC(12,2) NOT NULL DEFAULT 0,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            id          SERIAL PRIMARY KEY,
            kind        VARCHAR(16) NOT NULL,
            title       VARCHAR(256) NOT NULL,
            target      VARCHAR(256) NOT NULL,
            url         VARCHAR(512) NOT NULL,
            reward      NUMERIC(8,2) NOT NULL,
            active      BOOLEAN NOT NULL DEFAULT TRUE,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS completions (
            id          SERIAL PRIMARY KEY,
            user_id     BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            task_id     INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
            reward      NUMERIC(8,2) NOT NULL,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (user_id, task_id)
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS ix_completions_user_id ON completions(user_id)")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS withdrawals (
            id           SERIAL PRIMARY KEY,
            user_id      BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            amount       NUMERIC(12,2) NOT NULL,
            details      TEXT NOT NULL DEFAULT '',
            status       VARCHAR(16) NOT NULL DEFAULT 'pending',
            created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            processed_at TIMESTAMPTZ
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS ix_withdrawals_user_id ON withdrawals(user_id)")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS required_channels (
            id    SERIAL PRIMARY KEY,
            chat  VARCHAR(64) NOT NULL,
            title VARCHAR(256) NOT NULL,
            url   VARCHAR(512) NOT NULL
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key   VARCHAR(64) PRIMARY KEY,
            value VARCHAR(256) NOT NULL
        )
    """)


MIGRATIONS = [("0001", _m0001)]


def upgrade() -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS schema_version (
                    version VARCHAR(32) PRIMARY KEY
                )
            """)
            cur.execute("SELECT version FROM schema_version ORDER BY version DESC LIMIT 1")
            row = cur.fetchone()
            current = row[0] if row else None
            revisions = [r for r, _ in MIGRATIONS]
            start = revisions.index(current) + 1 if current in revisions else 0
            for rev, fn in MIGRATIONS[start:]:
                log.info("Migratsiya qo'llanmoqda: %s", rev)
                fn(cur)
                cur.execute(
                    "INSERT INTO schema_version (version) VALUES (%s) ON CONFLICT DO NOTHING",
                    (rev,),
                )
        conn.commit()
    log.info("Migratsiyalar tugadi.")
