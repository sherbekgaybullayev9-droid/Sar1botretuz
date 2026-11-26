"""
PostgreSQL ulanishi (psycopg2, sinxron, thread-safe havza).
Render'dagi uyqu/uzilishlarga chidamli: har olishda ulanish tekshiriladi.
"""
import logging
import threading
from contextlib import contextmanager

import psycopg2
import psycopg2.extras
from psycopg2 import pool as pg_pool

import config

log = logging.getLogger("database")

_pool: pg_pool.ThreadedConnectionPool | None = None
_pool_lock = threading.Lock()


def _dsn() -> str:
    url = config.DATABASE_URL
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    # Render'ning tashqi (external) manzili SSL talab qiladi
    if ".render.com" in url and "sslmode=" not in url:
        url += ("&" if "?" in url else "?") + "sslmode=require"
    return url


def init_pool() -> None:
    global _pool
    with _pool_lock:
        if _pool is None:
            _pool = pg_pool.ThreadedConnectionPool(
                1, 15, dsn=_dsn(),
                connect_timeout=10,
                keepalives=1, keepalives_idle=30,
                keepalives_interval=10, keepalives_count=5,
            )
            log.info("PostgreSQL ulanish havzasi yaratildi.")


def get_pool() -> pg_pool.ThreadedConnectionPool:
    if _pool is None:
        init_pool()
    return _pool  # type: ignore[return-value]


def _checkout():
    """Sog'lom ulanish qaytaradi (uzilgan bo'lsa yangisini oladi)."""
    p = get_pool()
    last = None
    for _ in range(3):
        conn = p.getconn()
        try:
            if conn.closed:
                raise psycopg2.InterfaceError("closed")
            with conn.cursor() as c:
                c.execute("SELECT 1")
            return conn
        except (psycopg2.OperationalError, psycopg2.InterfaceError) as e:
            last = e
            p.putconn(conn, close=True)
    raise last  # type: ignore[misc]


@contextmanager
def get_conn():
    p = get_pool()
    conn = _checkout()
    broken = False
    try:
        yield conn
        conn.commit()
    except (psycopg2.OperationalError, psycopg2.InterfaceError):
        broken = True
        raise
    except Exception:
        try:
            conn.rollback()
        except Exception:
            broken = True
        raise
    finally:
        p.putconn(conn, close=broken or bool(conn.closed))


@contextmanager
def get_cur(row_factory=psycopg2.extras.RealDictCursor):
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
