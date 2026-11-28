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


def _m0002(cur) -> None:
    # Holatlar (restart bo'lsa ham yo'qolmaydi) va START vazifasi ochilish vaqti
    cur.execute("""
        CREATE TABLE IF NOT EXISTS user_states (
            scope      VARCHAR(8)  NOT NULL,
            user_id    BIGINT      NOT NULL,
            state      VARCHAR(64) NOT NULL,
            data       JSONB       NOT NULL DEFAULT '{}'::jsonb,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (scope, user_id)
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS task_opens (
            user_id   BIGINT  NOT NULL,
            task_id   INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
            opened_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (user_id, task_id)
        )
    """)


def _m0003(cur) -> None:
    # Kunlik bonus va sovg'a ko'rinishidagi pul yechish
    cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS last_bonus_date DATE")
    cur.execute("ALTER TABLE withdrawals ADD COLUMN IF NOT EXISTS gift VARCHAR(32)")
    cur.execute("ALTER TABLE withdrawals ADD COLUMN IF NOT EXISTS recipient VARCHAR(64)")


def _m0004(cur) -> None:
    # Referal tizimi
    cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS referrer_id BIGINT")
    cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS ref_rewarded BOOLEAN NOT NULL DEFAULT FALSE")
    cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS ref_paid NUMERIC(8,2) NOT NULL DEFAULT 0")
    cur.execute("CREATE INDEX IF NOT EXISTS ix_users_referrer_id ON users(referrer_id)")


def _m0005(cur) -> None:
    # Vazifani necha kishi bajara olishi (NULL = cheklovsiz)
    cur.execute("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS max_completions INTEGER")


MIGRATIONS = [("0001", _m0001), ("0002", _m0002), ("0003", _m0003), ("0004", _m0004), ("0005", _m0005)]


def upgrade() -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT pg_advisory_xact_lock(727001)")
            cur.execute("""
                CREATE TABLE IF NOT EXISTS schema_version (
                    version VARCHAR(32) PRIMARY KEY
                )
            """)
            cur.execute("SELECT version FROM schema_version")
            applied = {r[0] for r in cur.fetchall()}
            for rev, fn in MIGRATIONS:
                if rev in applied:
                    continue
                log.info("Migratsiya qo'llanmoqda: %s", rev)
                fn(cur)
                cur.execute(
                    "INSERT INTO schema_version (version) VALUES (%s) ON CONFLICT DO NOTHING",
                    (rev,),
                )
    log.info("Migratsiyalar tugadi.")
