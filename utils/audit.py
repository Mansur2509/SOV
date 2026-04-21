"""
audit.py — логирование действий администраторов/организаторов SOV.
Пишет в таблицу audit_log + в файл logs/audit.log.
"""
import logging
import os
from datetime import datetime

logger = logging.getLogger("sov.audit")


def _get_conn():
    """Импортируем get_conn из database, чтобы избежать циклических импортов."""
    from database import get_conn, _q, BACKEND
    return get_conn(), _q, BACKEND


def init_audit_table():
    conn, _q, backend = _get_conn()
    c = conn.cursor()
    if backend == "pg":
        c.execute("""
            CREATE TABLE IF NOT EXISTS audit_log (
                id         SERIAL PRIMARY KEY,
                admin_id   BIGINT NOT NULL,
                admin_name TEXT NOT NULL,
                action     TEXT NOT NULL,
                details    TEXT DEFAULT '',
                created_at TEXT DEFAULT (to_char(now(), 'YYYY-MM-DD HH24:MI:SS'))
            )
        """)
    else:
        c.execute("""
            CREATE TABLE IF NOT EXISTS audit_log (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                admin_id   INTEGER NOT NULL,
                admin_name TEXT NOT NULL,
                action     TEXT NOT NULL,
                details    TEXT DEFAULT '',
                created_at TEXT DEFAULT (datetime('now'))
            )
        """)
    conn.commit()
    conn.close()


def log_action(admin_id: int, admin_name: str, action: str, details: str = ""):
    """Записать действие администратора/организатора."""
    # В БД
    try:
        conn, _q, backend = _get_conn()
        c = conn.cursor()
        c.execute(_q("INSERT INTO audit_log (admin_id, admin_name, action, details) VALUES (?,?,?,?)"),
                  (admin_id, admin_name, action, details))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"Audit DB write failed: {e}")

    # В лог-файл
    ts = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
    logger.info(f"[{ts}] {admin_name}({admin_id}) | {action} | {details}")


def get_audit_log(limit: int = 50, admin_id: int = None):
    conn, _q, _ = _get_conn()
    c = conn.cursor()
    if admin_id:
        c.execute(_q("SELECT * FROM audit_log WHERE admin_id=? ORDER BY created_at DESC LIMIT ?"),
                  (admin_id, limit))
    else:
        c.execute(_q("SELECT * FROM audit_log ORDER BY created_at DESC LIMIT ?"), (limit,))
    from database import _rows
    rows = _rows(c)
    conn.close()
    return rows
