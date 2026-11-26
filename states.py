"""
Foydalanuvchi/admin holatlari PostgreSQL'da saqlanadi
(Render restart qilsa ham suhbat yo'qolmaydi).
scope: "u" — foydalanuvchi, "a" — admin.
"""
from typing import Optional

from psycopg2.extras import Json

from database import get_cur


def get(scope: str, uid: int) -> Optional[dict]:
    with get_cur() as cur:
        cur.execute(
            "SELECT state, data FROM user_states WHERE scope = %s AND user_id = %s",
            (scope, uid),
        )
        row = cur.fetchone()
    if row is None:
        return None
    return {"state": row["state"], "data": row["data"] or {}}


def set(scope: str, uid: int, state: str, data: Optional[dict] = None) -> None:  # noqa: A001
    with get_cur() as cur:
        cur.execute("""
            INSERT INTO user_states (scope, user_id, state, data)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (scope, user_id) DO UPDATE
                SET state = EXCLUDED.state, data = EXCLUDED.data, updated_at = NOW()
        """, (scope, uid, state, Json(data or {})))


def clear(scope: str, uid: int) -> None:
    with get_cur() as cur:
        cur.execute(
            "DELETE FROM user_states WHERE scope = %s AND user_id = %s",
            (scope, uid),
        )
