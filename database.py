"""
PostgreSQL ulanishi va jadval ta'riflari.
psycopg2 (sinxron) ishlatiladi — aiogram o'rniga telebot bo'lgani uchun
async shart emas.
"""
import logging
import threading
from contextlib import contextmanager

import psycopg2
import psycopg2.extras
from psycopg2 import pool as pg_pool

import config

log = logging.getLogger("database")

# Ulanish havzasi (thread-safe)
_pool: pg_pool.ThreadedConnectionPool | None = None
_pool_lock = threading.Lock()


def _dsn() -> str:
    """postgres:// sxemasini psycopg2 uchun moslashtiradi."""
    url = config.DATABASE_URL
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    return url


def init_pool() -> None:
    global _pool
    with _pool_lock:
        if _pool is None:
            _pool = pg_pool.ThreadedConnectionPool(1, 10, dsn=_dsn())
            log.info("PostgreSQL ulanish havzasi yaratildi.")


def get_pool() -> pg_pool.ThreadedConnectionPool:
    if _pool is None:
        init_pool()
    return _pool  # type: ignore[return-value]


@contextmanager
def get_conn():
    """Havzadan ulanish oladi, ishlatib bo'lgach qaytaradi."""
    p = get_pool()
    conn = p.getconn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        p.putconn(conn)


@contextmanager
def get_cur(row_factory=psycopg2.extras.RealDictCursor):
    """Havzadan cursor oladi."""
    with get_conn() as conn:
        with conn.cursor(cursor_factory=row_factory) as cur:
            yield cur


def db_ping() -> bool:
    try:
        with get_cur() as cur:
            cur.execute("SELECT 1")
        return True
    except Exception as e:
        log.error("DB ping xatosi: %s", e)
        return False
