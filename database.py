"""
database.py — SOV Bot
Поддерживает PostgreSQL (через DATABASE_URL) и SQLite (локально).
Переключение автоматическое по наличию переменной окружения DATABASE_URL.
"""

import os
import hashlib
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

DATABASE_URL = os.environ.get("DATABASE_URL", "")

# ─── Адаптер: один интерфейс для SQLite и PostgreSQL ─────────────────────────

if DATABASE_URL:
    import psycopg2
    import psycopg2.extras

    def get_conn():
        conn = psycopg2.connect(DATABASE_URL)
        conn.autocommit = False
        return conn

    def _q(sql: str) -> str:
        """Конвертирует SQLite-плейсхолдеры ? -> %s для psycopg2."""
        return sql.replace("?", "%s")

    PH = "%s"   # placeholder
    BACKEND = "pg"

else:
    import sqlite3

    def get_conn():
        conn = sqlite3.connect("sov.db")
        conn.row_factory = sqlite3.Row
        return conn

    def _q(sql: str) -> str:
        return sql

    PH = "?"
    BACKEND = "sqlite"


def _rows(cursor) -> list:
    """Универсальный fetchall -> list of dict."""
    if BACKEND == "pg":
        cols = [d[0] for d in cursor.description]
        return [dict(zip(cols, row)) for row in cursor.fetchall()]
    else:
        return [dict(r) for r in cursor.fetchall()]


def _row(cursor):
    """Универсальный fetchone -> dict or None."""
    if BACKEND == "pg":
        row = cursor.fetchone()
        if row is None:
            return None
        cols = [d[0] for d in cursor.description]
        return dict(zip(cols, row))
    else:
        row = cursor.fetchone()
        return dict(row) if row else None


# ─── ИНИЦИАЛИЗАЦИЯ БД ────────────────────────────────────────────────────────

def init_db():
    conn = get_conn()
    c    = conn.cursor()

    if BACKEND == "pg":
        # PostgreSQL — используем SERIAL вместо AUTOINCREMENT
        c.execute("""
            CREATE TABLE IF NOT EXISTS users (
                tg_id         BIGINT PRIMARY KEY,
                full_name     TEXT NOT NULL,
                group_name    TEXT NOT NULL,
                gender        TEXT NOT NULL,
                lang          TEXT DEFAULT 'ru',
                rating        REAL DEFAULT 0,
                experience    INTEGER DEFAULT 0,
                streak        INTEGER DEFAULT 0,
                notes         TEXT DEFAULT '',
                points        INTEGER DEFAULT 0,
                ban_type      TEXT DEFAULT 'none',
                ban_until     TEXT DEFAULT NULL,
                agreed        INTEGER DEFAULT 0,
                last_seen_ann INTEGER DEFAULT 0,
                photo_file_id TEXT DEFAULT NULL,
                referred_by   BIGINT DEFAULT NULL,
                referral_count INTEGER DEFAULT 0,
                registered_at TEXT DEFAULT (to_char(now(), 'YYYY-MM-DD HH24:MI:SS'))
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS events (
                id             SERIAL PRIMARY KEY,
                title          TEXT NOT NULL,
                description    TEXT DEFAULT '',
                event_date     TEXT NOT NULL,
                event_time     TEXT DEFAULT '',
                location       TEXT DEFAULT '',
                duration       TEXT DEFAULT '',
                meeting_point  TEXT DEFAULT '',
                total_slots    INTEGER NOT NULL,
                male_slots     INTEGER DEFAULT 0,
                female_slots   INTEGER DEFAULT 0,
                gender_strict  INTEGER DEFAULT 0,
                photo_file_id  TEXT DEFAULT NULL,
                is_active      INTEGER DEFAULT 1,
                created_at     TEXT DEFAULT (to_char(now(), 'YYYY-MM-DD HH24:MI:SS'))
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS applications (
                id         SERIAL PRIMARY KEY,
                event_id   INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
                tg_id      BIGINT NOT NULL REFERENCES users(tg_id) ON DELETE CASCADE,
                status     TEXT DEFAULT 'pending',
                attended   INTEGER DEFAULT 0,
                applied_at TEXT DEFAULT (to_char(now(), 'YYYY-MM-DD HH24:MI:SS')),
                UNIQUE(event_id, tg_id)
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS ratings (
                id       SERIAL PRIMARY KEY,
                event_id INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
                tg_id    BIGINT NOT NULL REFERENCES users(tg_id) ON DELETE CASCADE,
                score    REAL NOT NULL,
                comment  TEXT DEFAULT '',
                rated_at TEXT DEFAULT (to_char(now(), 'YYYY-MM-DD HH24:MI:SS')),
                UNIQUE(event_id, tg_id)
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS point_history (
                id       SERIAL PRIMARY KEY,
                tg_id    BIGINT NOT NULL REFERENCES users(tg_id) ON DELETE CASCADE,
                delta    INTEGER NOT NULL,
                reason   TEXT DEFAULT '',
                given_at TEXT DEFAULT (to_char(now(), 'YYYY-MM-DD HH24:MI:SS'))
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS announcements (
                id         SERIAL PRIMARY KEY,
                text       TEXT NOT NULL,
                created_at TEXT DEFAULT (to_char(now(), 'YYYY-MM-DD HH24:MI:SS'))
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS event_proposals (
                id             SERIAL PRIMARY KEY,
                tg_id          BIGINT NOT NULL REFERENCES users(tg_id) ON DELETE CASCADE,
                vol_count      TEXT NOT NULL,
                location       TEXT NOT NULL,
                event_date     TEXT NOT NULL,
                duration       TEXT NOT NULL,
                tasks          TEXT NOT NULL,
                gender_need    TEXT NOT NULL,
                organizer      TEXT NOT NULL,
                admin_approved TEXT NOT NULL,
                comment        TEXT DEFAULT '',
                status         TEXT DEFAULT 'pending',
                created_at     TEXT DEFAULT (to_char(now(), 'YYYY-MM-DD HH24:MI:SS'))
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS cards (
                id        SERIAL PRIMARY KEY,
                tg_id     BIGINT NOT NULL REFERENCES users(tg_id) ON DELETE CASCADE,
                event_id  INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
                issued_at TEXT DEFAULT (to_char(now(), 'YYYY-MM-DD HH24:MI:SS')),
                UNIQUE(tg_id, event_id)
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS qr_tokens (
                token      TEXT PRIMARY KEY,
                event_id   INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
                created_at TEXT DEFAULT (to_char(now(), 'YYYY-MM-DD HH24:MI:SS'))
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS rate_limit (
                tg_id  BIGINT NOT NULL,
                action TEXT NOT NULL,
                ts     TEXT NOT NULL,
                PRIMARY KEY (tg_id, action, ts)
            )
        """)

    else:
        # SQLite
        c.execute("""
            CREATE TABLE IF NOT EXISTS users (
                tg_id         INTEGER PRIMARY KEY,
                full_name     TEXT NOT NULL,
                group_name    TEXT NOT NULL,
                gender        TEXT NOT NULL CHECK(gender IN ('М','Ж')),
                lang          TEXT DEFAULT 'ru',
                rating        REAL DEFAULT 0,
                experience    INTEGER DEFAULT 0,
                streak        INTEGER DEFAULT 0,
                notes         TEXT DEFAULT '',
                points        INTEGER DEFAULT 0,
                ban_type      TEXT DEFAULT 'none',
                ban_until     TEXT DEFAULT NULL,
                agreed        INTEGER DEFAULT 0,
                last_seen_ann INTEGER DEFAULT 0,
                photo_file_id TEXT DEFAULT NULL,
                referred_by   INTEGER DEFAULT NULL,
                referral_count INTEGER DEFAULT 0,
                registered_at TEXT DEFAULT (datetime('now'))
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS events (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                title          TEXT NOT NULL,
                description    TEXT DEFAULT '',
                event_date     TEXT NOT NULL,
                event_time     TEXT DEFAULT '',
                location       TEXT DEFAULT '',
                duration       TEXT DEFAULT '',
                meeting_point  TEXT DEFAULT '',
                total_slots    INTEGER NOT NULL,
                male_slots     INTEGER DEFAULT 0,
                female_slots   INTEGER DEFAULT 0,
                gender_strict  INTEGER DEFAULT 0,
                photo_file_id  TEXT DEFAULT NULL,
                is_active      INTEGER DEFAULT 1,
                created_at     TEXT DEFAULT (datetime('now'))
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS applications (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id   INTEGER NOT NULL REFERENCES events(id),
                tg_id      INTEGER NOT NULL REFERENCES users(tg_id),
                status     TEXT DEFAULT 'pending',
                attended   INTEGER DEFAULT 0,
                applied_at TEXT DEFAULT (datetime('now')),
                UNIQUE(event_id, tg_id)
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS ratings (
                id       INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id INTEGER NOT NULL REFERENCES events(id),
                tg_id    INTEGER NOT NULL REFERENCES users(tg_id),
                score    REAL NOT NULL,
                comment  TEXT DEFAULT '',
                rated_at TEXT DEFAULT (datetime('now')),
                UNIQUE(event_id, tg_id)
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS point_history (
                id       INTEGER PRIMARY KEY AUTOINCREMENT,
                tg_id    INTEGER NOT NULL,
                delta    INTEGER NOT NULL,
                reason   TEXT DEFAULT '',
                given_at TEXT DEFAULT (datetime('now'))
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS announcements (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                text       TEXT NOT NULL,
                created_at TEXT DEFAULT (datetime('now'))
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS event_proposals (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                tg_id          INTEGER NOT NULL,
                vol_count      TEXT NOT NULL,
                location       TEXT NOT NULL,
                event_date     TEXT NOT NULL,
                duration       TEXT NOT NULL,
                tasks          TEXT NOT NULL,
                gender_need    TEXT NOT NULL,
                organizer      TEXT NOT NULL,
                admin_approved TEXT NOT NULL,
                comment        TEXT DEFAULT '',
                status         TEXT DEFAULT 'pending',
                created_at     TEXT DEFAULT (datetime('now'))
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS cards (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                tg_id     INTEGER NOT NULL,
                event_id  INTEGER NOT NULL,
                issued_at TEXT DEFAULT (datetime('now')),
                UNIQUE(tg_id, event_id)
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS qr_tokens (
                token      TEXT PRIMARY KEY,
                event_id   INTEGER NOT NULL,
                created_at TEXT DEFAULT (datetime('now'))
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS rate_limit (
                tg_id  INTEGER NOT NULL,
                action TEXT NOT NULL,
                ts     TEXT NOT NULL,
                PRIMARY KEY (tg_id, action, ts)
            )
        """)

        # Безопасная миграция для существующих SQLite баз
        migrations = [
            ("users","lang","TEXT DEFAULT 'ru'"),
            ("users","streak","INTEGER DEFAULT 0"),
            ("users","photo_file_id","TEXT DEFAULT NULL"),
            ("users","referred_by","INTEGER DEFAULT NULL"),
            ("users","referral_count","INTEGER DEFAULT 0"),
            ("users","agreed","INTEGER DEFAULT 0"),
            ("users","last_seen_ann","INTEGER DEFAULT 0"),
            ("users","points","INTEGER DEFAULT 0"),
            ("users","ban_type","TEXT DEFAULT 'none'"),
            ("users","ban_until","TEXT DEFAULT NULL"),
            ("events","event_time","TEXT DEFAULT ''"),
            ("events","location","TEXT DEFAULT ''"),
            ("events","duration","TEXT DEFAULT ''"),
            ("events","meeting_point","TEXT DEFAULT ''"),
            ("events","gender_strict","INTEGER DEFAULT 0"),
            ("events","photo_file_id","TEXT DEFAULT NULL"),
            ("applications","attended","INTEGER DEFAULT 0"),
        ]
        for table, col, definition in migrations:
            try:
                c.execute(f"ALTER TABLE {table} ADD COLUMN {col} {definition}")
            except Exception:
                pass

    conn.commit()
    conn.close()
    logger.info(f"DB init OK ({BACKEND})")


# ─── RATE LIMITING ───────────────────────────────────────────────────────────

def check_rate_limit(tg_id: int, action: str, max_calls: int, window_seconds: int) -> bool:
    conn   = get_conn()
    c      = conn.cursor()
    cutoff = (datetime.now() - timedelta(seconds=window_seconds)).isoformat()
    c.execute(_q("DELETE FROM rate_limit WHERE tg_id=? AND action=? AND ts<?"), (tg_id, action, cutoff))
    c.execute(_q("SELECT COUNT(*) FROM rate_limit WHERE tg_id=? AND action=?"), (tg_id, action))
    count = c.fetchone()[0]
    if count >= max_calls:
        conn.commit(); conn.close()
        return False
    c.execute(_q("INSERT INTO rate_limit (tg_id, action, ts) VALUES (?,?,?)"),
              (tg_id, action, datetime.now().isoformat()))
    conn.commit(); conn.close()
    return True


# ─── ПОЛЬЗОВАТЕЛИ ────────────────────────────────────────────────────────────

def user_exists(tg_id: int) -> bool:
    conn = get_conn(); c = conn.cursor()
    c.execute(_q("SELECT 1 FROM users WHERE tg_id=?"), (tg_id,))
    row = c.fetchone(); conn.close()
    return row is not None


def register_user(tg_id: int, full_name: str, group_name: str, gender: str,
                  lang: str = "ru", referred_by: int = None):
    conn = get_conn(); c = conn.cursor()
    if BACKEND == "pg":
        c.execute("""INSERT INTO users (tg_id, full_name, group_name, gender, lang, referred_by)
                     VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT (tg_id) DO NOTHING""",
                  (tg_id, full_name, group_name, gender, lang, referred_by))
    else:
        c.execute("INSERT OR IGNORE INTO users (tg_id, full_name, group_name, gender, lang, referred_by) VALUES (?,?,?,?,?,?)",
                  (tg_id, full_name, group_name, gender, lang, referred_by))
    if referred_by:
        c.execute(_q("UPDATE users SET referral_count = referral_count + 1 WHERE tg_id=?"), (referred_by,))
    conn.commit(); conn.close()


def set_agreed(tg_id: int):
    conn = get_conn(); c = conn.cursor()
    c.execute(_q("UPDATE users SET agreed=1 WHERE tg_id=?"), (tg_id,))
    conn.commit(); conn.close()


def set_lang(tg_id: int, lang: str):
    conn = get_conn(); c = conn.cursor()
    c.execute(_q("UPDATE users SET lang=? WHERE tg_id=?"), (lang, tg_id))
    conn.commit(); conn.close()


def get_user_lang(tg_id: int) -> str:
    conn = get_conn(); c = conn.cursor()
    c.execute(_q("SELECT lang FROM users WHERE tg_id=?"), (tg_id,))
    row = c.fetchone(); conn.close()
    if row is None: return "ru"
    return (row[0] if BACKEND == "pg" else row["lang"]) or "ru"


def get_user(tg_id: int):
    conn = get_conn(); c = conn.cursor()
    c.execute(_q("SELECT * FROM users WHERE tg_id=?"), (tg_id,))
    row = _row(c); conn.close()
    return row


def get_all_users():
    conn = get_conn(); c = conn.cursor()
    c.execute("SELECT * FROM users ORDER BY rating DESC, experience DESC")
    rows = _rows(c); conn.close()
    return rows


def update_user_notes(tg_id: int, notes: str):
    conn = get_conn(); c = conn.cursor()
    c.execute(_q("UPDATE users SET notes=? WHERE tg_id=?"), (notes, tg_id))
    conn.commit(); conn.close()


def set_user_photo(tg_id: int, file_id: str):
    conn = get_conn(); c = conn.cursor()
    c.execute(_q("UPDATE users SET photo_file_id=? WHERE tg_id=?"), (file_id, tg_id))
    conn.commit(); conn.close()


def delete_user(tg_id: int):
    conn = get_conn(); c = conn.cursor()
    for tbl in ["applications","point_history","ratings","cards"]:
        c.execute(_q(f"DELETE FROM {tbl} WHERE tg_id=?"), (tg_id,))
    c.execute(_q("DELETE FROM users WHERE tg_id=?"), (tg_id,))
    conn.commit(); conn.close()


def get_top_users(limit=3):
    conn = get_conn(); c = conn.cursor()
    c.execute(_q("SELECT * FROM users WHERE ban_type='none' ORDER BY rating DESC, experience DESC LIMIT ?"), (limit,))
    rows = _rows(c); conn.close()
    return rows


def is_banned(tg_id: int) -> tuple:
    user = get_user(tg_id)
    if not user: return False, ""
    if user["ban_type"] == "full": return True, "full"
    if user["ban_type"] == "temp" and user.get("ban_until"):
        try:
            ban_until = datetime.fromisoformat(user["ban_until"])
            if datetime.now() < ban_until:
                return True, ban_until.strftime("%d.%m.%Y")
        except Exception:
            pass
        conn = get_conn(); c = conn.cursor()
        c.execute(_q("UPDATE users SET ban_type='none', ban_until=NULL WHERE tg_id=?"), (tg_id,))
        conn.commit(); conn.close()
    return False, ""


def update_last_seen_ann(tg_id: int, ann_id: int):
    conn = get_conn(); c = conn.cursor()
    c.execute(_q("UPDATE users SET last_seen_ann=? WHERE tg_id=?"), (ann_id, tg_id))
    conn.commit(); conn.close()


def recalc_streak(tg_id: int):
    conn = get_conn(); c = conn.cursor()
    c.execute(_q("""SELECT a.attended FROM applications a
                    JOIN events e ON a.event_id=e.id
                    WHERE a.tg_id=? AND a.status='selected'
                    ORDER BY e.event_date DESC"""), (tg_id,))
    rows   = _rows(c)
    streak = 0
    for r in rows:
        if r["attended"]: streak += 1
        else: break
    c.execute(_q("UPDATE users SET streak=? WHERE tg_id=?"), (streak, tg_id))
    conn.commit(); conn.close()
    return streak


def get_new_announcements_for_user(tg_id: int):
    user = get_user(tg_id)
    if not user: return []
    last_seen = user.get("last_seen_ann", 0) or 0
    conn = get_conn(); c = conn.cursor()
    c.execute(_q("SELECT * FROM announcements WHERE id > ? ORDER BY id ASC"), (last_seen,))
    rows = _rows(c); conn.close()
    return rows


# ─── ПОИНТЫ ──────────────────────────────────────────────────────────────────

def add_points(tg_id: int, delta: int, reason: str = "") -> dict:
    conn = get_conn(); c = conn.cursor()
    c.execute(_q("UPDATE users SET points = points + ? WHERE tg_id=?"), (delta, tg_id))
    c.execute(_q("INSERT INTO point_history (tg_id, delta, reason) VALUES (?,?,?)"), (tg_id, delta, reason))
    conn.commit()
    c.execute(_q("SELECT * FROM users WHERE tg_id=?"), (tg_id,))
    user       = _row(c)
    new_points = user["points"]
    action     = "none"
    if new_points >= 3:
        if user["ban_type"] == "temp":
            c.execute(_q("UPDATE users SET ban_type='full', ban_until=NULL, points=0 WHERE tg_id=?"), (tg_id,))
            action = "full_ban"
        else:
            ban_until = (datetime.now() + timedelta(days=30)).isoformat()
            c.execute(_q("UPDATE users SET ban_type='temp', ban_until=?, points=0 WHERE tg_id=?"), (ban_until, tg_id))
            action = "temp_ban"
        conn.commit()
    conn.close()
    return {"points": new_points, "action": action}


def get_point_history(tg_id: int):
    conn = get_conn(); c = conn.cursor()
    c.execute(_q("SELECT * FROM point_history WHERE tg_id=? ORDER BY given_at DESC LIMIT 10"), (tg_id,))
    rows = _rows(c); conn.close()
    return rows


# ─── БАНЫ ────────────────────────────────────────────────────────────────────

def ban_user(tg_id: int, ban_type: str, days: int = 30):
    conn = get_conn(); c = conn.cursor()
    if ban_type == "full":
        c.execute(_q("UPDATE users SET ban_type='full', ban_until=NULL WHERE tg_id=?"), (tg_id,))
    else:
        bu = (datetime.now() + timedelta(days=days)).isoformat()
        c.execute(_q("UPDATE users SET ban_type='temp', ban_until=? WHERE tg_id=?"), (bu, tg_id))
    conn.commit(); conn.close()


def unban_user(tg_id: int):
    conn = get_conn(); c = conn.cursor()
    c.execute(_q("UPDATE users SET ban_type='none', ban_until=NULL, points=0 WHERE tg_id=?"), (tg_id,))
    conn.commit(); conn.close()


# ─── ОБЪЯВЛЕНИЯ ──────────────────────────────────────────────────────────────

def create_announcement(text: str) -> int:
    conn = get_conn(); c = conn.cursor()
    if BACKEND == "pg":
        c.execute("INSERT INTO announcements (text) VALUES (%s) RETURNING id", (text,))
        ann_id = c.fetchone()[0]
    else:
        c.execute("INSERT INTO announcements (text) VALUES (?)", (text,))
        ann_id = c.lastrowid
    conn.commit(); conn.close()
    return ann_id


def get_announcements(limit=10, offset=0):
    conn = get_conn(); c = conn.cursor()
    c.execute(_q("SELECT * FROM announcements ORDER BY created_at DESC LIMIT ? OFFSET ?"), (limit, offset))
    rows = _rows(c); conn.close()
    return rows


def get_announcements_count() -> int:
    conn = get_conn(); c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM announcements")
    row = c.fetchone(); conn.close()
    return row[0]


# ─── ИВЕНТЫ ──────────────────────────────────────────────────────────────────

def create_event(title, description, event_date, event_time, location, duration,
                 meeting_point, total_slots, male_slots, female_slots,
                 gender_strict=0, photo_file_id=None) -> int:
    conn = get_conn(); c = conn.cursor()
    if BACKEND == "pg":
        c.execute("""INSERT INTO events
                     (title,description,event_date,event_time,location,duration,
                      meeting_point,total_slots,male_slots,female_slots,gender_strict,photo_file_id)
                     VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
                  (title,description,event_date,event_time,location,duration,
                   meeting_point,total_slots,male_slots,female_slots,gender_strict,photo_file_id))
        eid = c.fetchone()[0]
    else:
        c.execute("""INSERT INTO events
                     (title,description,event_date,event_time,location,duration,
                      meeting_point,total_slots,male_slots,female_slots,gender_strict,photo_file_id)
                     VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                  (title,description,event_date,event_time,location,duration,
                   meeting_point,total_slots,male_slots,female_slots,gender_strict,photo_file_id))
        eid = c.lastrowid
    conn.commit(); conn.close()
    return eid


def get_active_events():
    conn = get_conn(); c = conn.cursor()
    c.execute("SELECT * FROM events WHERE is_active=1 ORDER BY event_date")
    rows = _rows(c); conn.close()
    return rows


def get_all_events():
    conn = get_conn(); c = conn.cursor()
    c.execute("SELECT * FROM events ORDER BY created_at DESC")
    rows = _rows(c); conn.close()
    return rows


def get_event(event_id: int):
    conn = get_conn(); c = conn.cursor()
    c.execute(_q("SELECT * FROM events WHERE id=?"), (event_id,))
    row = _row(c); conn.close()
    return row


def close_event(event_id: int):
    conn = get_conn(); c = conn.cursor()
    c.execute(_q("UPDATE events SET is_active=0 WHERE id=?"), (event_id,))
    conn.commit(); conn.close()


def delete_event(event_id: int):
    conn = get_conn(); c = conn.cursor()
    for tbl in ["applications","ratings","cards","qr_tokens"]:
        c.execute(_q(f"DELETE FROM {tbl} WHERE event_id=?"), (event_id,))
    c.execute(_q("DELETE FROM events WHERE id=?"), (event_id,))
    conn.commit(); conn.close()


def set_event_photo(event_id: int, file_id: str):
    conn = get_conn(); c = conn.cursor()
    c.execute(_q("UPDATE events SET photo_file_id=? WHERE id=?"), (file_id, event_id))
    conn.commit(); conn.close()


# ─── ЗАЯВКИ ──────────────────────────────────────────────────────────────────

def apply_to_event(event_id: int, tg_id: int) -> tuple:
    event = get_event(event_id)
    if not event: return False, "not_found"
    if event.get("gender_strict"):
        user = get_user(tg_id)
        m, f = event["male_slots"], event["female_slots"]
        if m > 0 and f == 0 and user["gender"] != "М": return False, "male_only"
        if f > 0 and m == 0 and user["gender"] != "Ж": return False, "female_only"
    try:
        conn = get_conn(); c = conn.cursor()
        if BACKEND == "pg":
            c.execute("INSERT INTO applications (event_id, tg_id) VALUES (%s,%s) ON CONFLICT DO NOTHING",
                      (event_id, tg_id))
            if c.rowcount == 0:
                conn.close(); return False, "already"
        else:
            c.execute("INSERT INTO applications (event_id, tg_id) VALUES (?,?)", (event_id, tg_id))
        conn.commit(); conn.close()
        return True, ""
    except Exception:
        return False, "already"


def cancel_application(event_id: int, tg_id: int):
    conn = get_conn(); c = conn.cursor()
    c.execute(_q("DELETE FROM applications WHERE event_id=? AND tg_id=? AND status='pending'"),
              (event_id, tg_id))
    conn.commit(); conn.close()


def get_applications(event_id: int):
    conn = get_conn(); c = conn.cursor()
    c.execute(_q("""SELECT a.*, u.full_name, u.group_name, u.gender, u.rating, u.experience
                    FROM applications a JOIN users u ON a.tg_id=u.tg_id
                    WHERE a.event_id=? ORDER BY u.rating DESC, u.experience DESC"""), (event_id,))
    rows = _rows(c); conn.close()
    return rows


def has_applied(event_id: int, tg_id: int):
    conn = get_conn(); c = conn.cursor()
    c.execute(_q("SELECT status FROM applications WHERE event_id=? AND tg_id=?"), (event_id, tg_id))
    row = c.fetchone(); conn.close()
    if row is None: return None
    return row[0] if BACKEND == "pg" else row["status"]


def get_user_events(tg_id: int):
    conn = get_conn(); c = conn.cursor()
    c.execute(_q("""SELECT e.id, e.title, e.event_date, e.event_time, e.location, a.status, a.attended
                    FROM applications a JOIN events e ON a.event_id=e.id
                    WHERE a.tg_id=? ORDER BY e.event_date DESC"""), (tg_id,))
    rows = _rows(c); conn.close()
    return rows


def get_selected_for_event(event_id: int):
    conn = get_conn(); c = conn.cursor()
    c.execute(_q("""SELECT u.tg_id, u.full_name, u.group_name
                    FROM applications a JOIN users u ON a.tg_id=u.tg_id
                    WHERE a.event_id=? AND a.status='selected'"""), (event_id,))
    rows = _rows(c); conn.close()
    return rows


def manually_add_to_event(event_id: int, tg_id: int) -> bool:
    try:
        conn = get_conn(); c = conn.cursor()
        if BACKEND == "pg":
            c.execute("""INSERT INTO applications (event_id, tg_id, status)
                         VALUES (%s,%s,'selected')
                         ON CONFLICT (event_id, tg_id) DO UPDATE SET status='selected'""",
                      (event_id, tg_id))
        else:
            c.execute("INSERT OR REPLACE INTO applications (event_id, tg_id, status) VALUES (?,?,'selected')",
                      (event_id, tg_id))
        conn.commit(); conn.close()
        return True
    except Exception:
        return False


def manually_remove_from_event(event_id: int, tg_id: int):
    conn = get_conn(); c = conn.cursor()
    c.execute(_q("DELETE FROM applications WHERE event_id=? AND tg_id=?"), (event_id, tg_id))
    conn.commit(); conn.close()


# ─── ОЦЕНКИ ──────────────────────────────────────────────────────────────────

def add_rating(event_id: int, tg_id: int, score: float, comment: str = ""):
    conn = get_conn(); c = conn.cursor()
    if BACKEND == "pg":
        c.execute("""INSERT INTO ratings (event_id,tg_id,score,comment) VALUES (%s,%s,%s,%s)
                     ON CONFLICT (event_id,tg_id) DO UPDATE SET score=%s, comment=%s""",
                  (event_id,tg_id,score,comment,score,comment))
    else:
        c.execute("INSERT OR REPLACE INTO ratings (event_id,tg_id,score,comment) VALUES (?,?,?,?)",
                  (event_id,tg_id,score,comment))
    c.execute(_q("SELECT AVG(score) as avg_r, COUNT(*) as cnt FROM ratings WHERE tg_id=?"), (tg_id,))
    row = c.fetchone()
    avg_r = row[0] if BACKEND == "pg" else row["avg_r"]
    cnt   = row[1] if BACKEND == "pg" else row["cnt"]
    c.execute(_q("UPDATE users SET rating=ROUND(CAST(? AS NUMERIC),2), experience=? WHERE tg_id=?"),
              (avg_r, cnt, tg_id))
    conn.commit(); conn.close()


# ─── АВТОПОДБОР ──────────────────────────────────────────────────────────────

def auto_select(event_id: int) -> dict:
    event = get_event(event_id)
    if not event: return {"selected": [], "rejected": []}
    apps        = get_applications(event_id)
    active_apps = [a for a in apps if not is_banned(a["tg_id"])[0]]
    males       = [a for a in active_apps if a["gender"] == "М"]
    females     = [a for a in active_apps if a["gender"] == "Ж"]
    selected    = []
    selected   += males[:event["male_slots"]]
    selected   += females[:event["female_slots"]]
    filled_ids  = {s["tg_id"] for s in selected}
    remaining   = event["total_slots"] - len(selected)
    if remaining > 0:
        rest = sorted(
            [a for a in active_apps if a["tg_id"] not in filled_ids],
            key=lambda x: (-x["rating"], -x["experience"])
        )
        selected += rest[:remaining]
    selected_ids = {s["tg_id"] for s in selected}
    rejected     = [a for a in apps if a["tg_id"] not in selected_ids]
    conn = get_conn(); c = conn.cursor()
    for s in selected:
        c.execute(_q("UPDATE applications SET status='selected' WHERE event_id=? AND tg_id=?"),
                  (event_id, s["tg_id"]))
    for r in rejected:
        c.execute(_q("UPDATE applications SET status='rejected' WHERE event_id=? AND tg_id=?"),
                  (event_id, r["tg_id"]))
    conn.commit(); conn.close()
    return {"selected": selected, "rejected": rejected}


# ─── КАРТОЧКИ ────────────────────────────────────────────────────────────────

def issue_card(tg_id: int, event_id: int) -> bool:
    try:
        conn = get_conn(); c = conn.cursor()
        if BACKEND == "pg":
            c.execute("INSERT INTO cards (tg_id, event_id) VALUES (%s,%s) ON CONFLICT DO NOTHING",
                      (tg_id, event_id))
            inserted = c.rowcount > 0
        else:
            c.execute("INSERT OR IGNORE INTO cards (tg_id, event_id) VALUES (?,?)", (tg_id, event_id))
            inserted = c.rowcount > 0
        conn.commit(); conn.close()
        return inserted
    except Exception:
        return False


def get_user_cards(tg_id: int):
    conn = get_conn(); c = conn.cursor()
    c.execute(_q("""SELECT c.*, e.title, e.event_date, e.photo_file_id
                    FROM cards c JOIN events e ON c.event_id=e.id
                    WHERE c.tg_id=? ORDER BY c.issued_at DESC"""), (tg_id,))
    rows = _rows(c); conn.close()
    return rows


# ─── QR ──────────────────────────────────────────────────────────────────────

def generate_qr_token(event_id: int) -> str:
    raw   = f"sov_event_{event_id}_{datetime.now().isoformat()}"
    token = hashlib.sha256(raw.encode()).hexdigest()[:16]
    conn  = get_conn(); c = conn.cursor()
    if BACKEND == "pg":
        c.execute("INSERT INTO qr_tokens (token, event_id) VALUES (%s,%s) ON CONFLICT (token) DO UPDATE SET event_id=%s",
                  (token, event_id, event_id))
    else:
        c.execute("INSERT OR REPLACE INTO qr_tokens (token, event_id) VALUES (?,?)", (token, event_id))
    conn.commit(); conn.close()
    return token


def get_event_by_qr_token(token: str):
    conn = get_conn(); c = conn.cursor()
    c.execute(_q("SELECT * FROM qr_tokens WHERE token=?"), (token,))
    row = _row(c); conn.close()
    return row


def confirm_attendance(event_id: int, tg_id: int) -> str:
    conn = get_conn(); c = conn.cursor()
    c.execute(_q("SELECT * FROM applications WHERE event_id=? AND tg_id=? AND status='selected'"),
              (event_id, tg_id))
    row = _row(c)
    if not row: conn.close(); return "not_selected"
    if row["attended"]: conn.close(); return "already"
    c.execute(_q("UPDATE applications SET attended=1 WHERE event_id=? AND tg_id=?"), (event_id, tg_id))
    conn.commit(); conn.close()
    recalc_streak(tg_id)
    return "ok"


# ─── ПРЕДЛОЖЕНИЯ ─────────────────────────────────────────────────────────────

def create_proposal(tg_id, vol_count, location, event_date, duration,
                    tasks, gender_need, organizer, admin_approved, comment) -> int:
    conn = get_conn(); c = conn.cursor()
    if BACKEND == "pg":
        c.execute("""INSERT INTO event_proposals
                     (tg_id,vol_count,location,event_date,duration,tasks,gender_need,organizer,admin_approved,comment)
                     VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
                  (tg_id,vol_count,location,event_date,duration,tasks,gender_need,organizer,admin_approved,comment))
        pid = c.fetchone()[0]
    else:
        c.execute("""INSERT INTO event_proposals
                     (tg_id,vol_count,location,event_date,duration,tasks,gender_need,organizer,admin_approved,comment)
                     VALUES (?,?,?,?,?,?,?,?,?,?)""",
                  (tg_id,vol_count,location,event_date,duration,tasks,gender_need,organizer,admin_approved,comment))
        pid = c.lastrowid
    conn.commit(); conn.close()
    return pid


def get_proposals(status="pending"):
    conn = get_conn(); c = conn.cursor()
    c.execute(_q("""SELECT p.*, u.full_name FROM event_proposals p
                    JOIN users u ON p.tg_id=u.tg_id
                    WHERE p.status=? ORDER BY p.created_at DESC"""), (status,))
    rows = _rows(c); conn.close()
    return rows


def get_proposal(pid: int):
    conn = get_conn(); c = conn.cursor()
    c.execute(_q("""SELECT p.*, u.full_name FROM event_proposals p
                    JOIN users u ON p.tg_id=u.tg_id WHERE p.id=?"""), (pid,))
    row = _row(c); conn.close()
    return row


def update_proposal_status(pid: int, status: str):
    conn = get_conn(); c = conn.cursor()
    c.execute(_q("UPDATE event_proposals SET status=? WHERE id=?"), (status, pid))
    conn.commit(); conn.close()


# ─── РОЛИ ────────────────────────────────────────────────────────────────────
# role: 'user' | 'organizer' | 'admin'
# Хранится в отдельной таблице чтобы не ломать существующую users

def init_roles_table():
    conn = get_conn(); c = conn.cursor()
    if BACKEND == "pg":
        c.execute("""CREATE TABLE IF NOT EXISTS user_roles (
            tg_id BIGINT PRIMARY KEY REFERENCES users(tg_id) ON DELETE CASCADE,
            role  TEXT DEFAULT 'user'
        )""")
    else:
        c.execute("""CREATE TABLE IF NOT EXISTS user_roles (
            tg_id INTEGER PRIMARY KEY,
            role  TEXT DEFAULT 'user'
        )""")
    conn.commit(); conn.close()


def get_role(tg_id: int) -> str:
    from config import ADMIN_IDS
    if tg_id in ADMIN_IDS:
        return "admin"
    conn = get_conn(); c = conn.cursor()
    c.execute(_q("SELECT role FROM user_roles WHERE tg_id=?"), (tg_id,))
    row = c.fetchone(); conn.close()
    if row is None:
        return "user"
    return row[0] if BACKEND == "pg" else row["role"]


def set_role(tg_id: int, role: str):
    conn = get_conn(); c = conn.cursor()
    if BACKEND == "pg":
        c.execute("INSERT INTO user_roles (tg_id, role) VALUES (%s,%s) ON CONFLICT (tg_id) DO UPDATE SET role=%s",
                  (tg_id, role, role))
    else:
        c.execute("INSERT OR REPLACE INTO user_roles (tg_id, role) VALUES (?,?)", (tg_id, role))
    conn.commit(); conn.close()


def get_users_by_role(role: str):
    conn = get_conn(); c = conn.cursor()
    c.execute(_q("""SELECT u.* FROM users u
                    JOIN user_roles r ON u.tg_id=r.tg_id
                    WHERE r.role=?"""), (role,))
    rows = _rows(c); conn.close()
    return rows


# ─── ШАБЛОНЫ ИВЕНТОВ ─────────────────────────────────────────────────────────

def init_templates_table():
    conn = get_conn(); c = conn.cursor()
    if BACKEND == "pg":
        c.execute("""CREATE TABLE IF NOT EXISTS event_templates (
            id           SERIAL PRIMARY KEY,
            name         TEXT NOT NULL,
            title        TEXT NOT NULL,
            description  TEXT DEFAULT '',
            location     TEXT DEFAULT '',
            duration     TEXT DEFAULT '',
            meeting_point TEXT DEFAULT '',
            total_slots  INTEGER DEFAULT 10,
            male_slots   INTEGER DEFAULT 0,
            female_slots INTEGER DEFAULT 0,
            gender_strict INTEGER DEFAULT 0,
            created_by   BIGINT,
            created_at   TEXT DEFAULT (to_char(now(), 'YYYY-MM-DD HH24:MI:SS'))
        )""")
    else:
        c.execute("""CREATE TABLE IF NOT EXISTS event_templates (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            name         TEXT NOT NULL,
            title        TEXT NOT NULL,
            description  TEXT DEFAULT '',
            location     TEXT DEFAULT '',
            duration     TEXT DEFAULT '',
            meeting_point TEXT DEFAULT '',
            total_slots  INTEGER DEFAULT 10,
            male_slots   INTEGER DEFAULT 0,
            female_slots INTEGER DEFAULT 0,
            gender_strict INTEGER DEFAULT 0,
            created_by   INTEGER,
            created_at   TEXT DEFAULT (datetime('now'))
        )""")
    conn.commit(); conn.close()


def save_template(name: str, event_data: dict, created_by: int) -> int:
    conn = get_conn(); c = conn.cursor()
    fields = ("name","title","description","location","duration","meeting_point",
               "total_slots","male_slots","female_slots","gender_strict","created_by")
    vals = (name,
            event_data.get("title",""),
            event_data.get("description",""),
            event_data.get("location",""),
            event_data.get("duration",""),
            event_data.get("meeting_point",""),
            event_data.get("total_slots",10),
            event_data.get("male_slots",0),
            event_data.get("female_slots",0),
            event_data.get("gender_strict",0),
            created_by)
    if BACKEND == "pg":
        c.execute(f"INSERT INTO event_templates ({','.join(fields)}) VALUES ({','.join(['%s']*len(fields))}) RETURNING id", vals)
        tid = c.fetchone()[0]
    else:
        c.execute(f"INSERT INTO event_templates ({','.join(fields)}) VALUES ({','.join(['?']*len(fields))})", vals)
        tid = c.lastrowid
    conn.commit(); conn.close()
    return tid


def get_templates():
    conn = get_conn(); c = conn.cursor()
    c.execute("SELECT * FROM event_templates ORDER BY created_at DESC")
    rows = _rows(c); conn.close()
    return rows


def get_template(tid: int):
    conn = get_conn(); c = conn.cursor()
    c.execute(_q("SELECT * FROM event_templates WHERE id=?"), (tid,))
    row = _row(c); conn.close()
    return row


def delete_template(tid: int):
    conn = get_conn(); c = conn.cursor()
    c.execute(_q("DELETE FROM event_templates WHERE id=?"), (tid,))
    conn.commit(); conn.close()


# ─── ДЕДЛАЙНЫ ЗАПИСИ ─────────────────────────────────────────────────────────

def set_registration_deadline(event_id: int, deadline: str):
    """deadline — ISO строка datetime, например '2025-05-25T18:00:00'"""
    conn = get_conn(); c = conn.cursor()
    # Добавляем колонку если нет (миграция)
    try:
        if BACKEND == "pg":
            c.execute("ALTER TABLE events ADD COLUMN reg_deadline TEXT DEFAULT NULL")
        else:
            c.execute("ALTER TABLE events ADD COLUMN reg_deadline TEXT DEFAULT NULL")
        conn.commit()
    except Exception:
        pass
    c.execute(_q("UPDATE events SET reg_deadline=? WHERE id=?"), (deadline, event_id))
    conn.commit(); conn.close()


def get_events_with_expired_deadline():
    """Возвращает активные ивенты у которых дедлайн истёк."""
    conn = get_conn(); c = conn.cursor()
    now = datetime.now().isoformat()
    try:
        c.execute(_q("""SELECT * FROM events
                        WHERE is_active=1
                        AND reg_deadline IS NOT NULL
                        AND reg_deadline <= ?"""), (now,))
        rows = _rows(c)
    except Exception:
        rows = []
    conn.close()
    return rows


# ─── СТАТИСТИКА ──────────────────────────────────────────────────────────────

def get_org_stats() -> dict:
    """Возвращает общую статистику организации."""
    conn = get_conn(); c = conn.cursor()

    c.execute("SELECT COUNT(*) FROM users WHERE agreed=1")
    total_users = c.fetchone()[0]

    c.execute("SELECT COUNT(*) FROM users WHERE ban_type != 'none'")
    banned_users = c.fetchone()[0]

    c.execute("SELECT COUNT(*) FROM events")
    total_events = c.fetchone()[0]

    c.execute("SELECT COUNT(*) FROM events WHERE is_active=1")
    active_events = c.fetchone()[0]

    c.execute("SELECT COUNT(*) FROM applications WHERE status='selected'")
    total_participations = c.fetchone()[0]

    try:
        c.execute("SELECT AVG(score) FROM ratings")
        row = c.fetchone()
        avg_rating = round(float(row[0]), 2) if row and row[0] else 0.0
    except Exception:
        avg_rating = 0.0

    c.execute("SELECT COUNT(*) FROM announcements")
    total_announcements = c.fetchone()[0]

    # Активность по месяцам (последние 6)
    monthly = []
    try:
        if BACKEND == "pg":
            c.execute("""
                SELECT to_char(to_timestamp(created_at, 'YYYY-MM-DD HH24:MI:SS'), 'YYYY-MM') as month,
                       COUNT(*) as cnt
                FROM events
                GROUP BY month
                ORDER BY month DESC
                LIMIT 6
            """)
        else:
            c.execute("""
                SELECT strftime('%Y-%m', created_at) as month, COUNT(*) as cnt
                FROM events
                GROUP BY month
                ORDER BY month DESC
                LIMIT 6
            """)
        monthly = _rows(c)
    except Exception:
        pass

    conn.close()
    return {
        "total_users":        total_users,
        "banned_users":       banned_users,
        "total_events":       total_events,
        "active_events":      active_events,
        "total_participations": total_participations,
        "avg_rating":         avg_rating,
        "total_announcements": total_announcements,
        "monthly_events":     monthly,
    }


def get_users_filtered(gender: str = None, group: str = None,
                       lang: str = None, ban_type: str = None) -> list:
    """Фильтрованный список пользователей для таргетированной рассылки."""
    conn = get_conn(); c = conn.cursor()
    conditions = ["agreed=1"]
    params     = []

    if gender:
        conditions.append(_q("gender=?").replace("?", PH))
        params.append(gender)
    if group:
        conditions.append(_q("group_name=?").replace("?", PH))
        params.append(group)
    if lang:
        conditions.append(_q("lang=?").replace("?", PH))
        params.append(lang)
    if ban_type:
        conditions.append(_q("ban_type=?").replace("?", PH))
        params.append(ban_type)

    where = " AND ".join(conditions)
    sql   = f"SELECT * FROM users WHERE {where}"
    c.execute(sql, params)
    rows = _rows(c); conn.close()
    return rows


def get_all_groups() -> list:
    """Возвращает список уникальных групп."""
    conn = get_conn(); c = conn.cursor()
    c.execute("SELECT DISTINCT group_name FROM users ORDER BY group_name")
    rows = c.fetchall(); conn.close()
    return [r[0] for r in rows]
