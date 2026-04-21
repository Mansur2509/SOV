"""
achievements.py — система достижений (бейджей) SOV.
Бейдж = карточка особого типа. Проверяется после каждого ивента/оценки.
"""
from dataclasses import dataclass
from typing import Optional
import logging

logger = logging.getLogger(__name__)

# ── Определения достижений ───────────────────────────────────────────────────

@dataclass
class Achievement:
    key:         str    # уникальный ключ
    emoji:       str    # иконка
    title_ru:    str
    title_uz:    str
    title_en:    str
    desc_ru:     str
    desc_uz:     str
    desc_en:     str


ACHIEVEMENTS: list[Achievement] = [
    Achievement("first_event",   "🌱", "Первый шаг",       "Birinchi qadam",      "First step",
                "Принял участие в первом ивенте",
                "Birinchi tadbirda ishtirok etdi",
                "Participated in the first event"),

    Achievement("events_5",      "⭐", "Опытный волонтёр", "Tajribali volontyor",  "Experienced volunteer",
                "5 ивентов за плечами",
                "5 ta tadbirda ishtirok etdi",
                "Participated in 5 events"),

    Achievement("events_10",     "🌟", "Ветеран SOV",      "SOV veterani",         "SOV Veteran",
                "10 ивентов — настоящий ветеран!",
                "10 ta tadbir — haqiqiy veteran!",
                "10 events — a true veteran!"),

    Achievement("events_25",     "💎", "Легенда SOV",      "SOV afsonasi",         "SOV Legend",
                "25 ивентов. Легендарный статус.",
                "25 ta tadbir. Afsonaviy status.",
                "25 events. Legendary status."),

    Achievement("streak_3",      "🔥", "Серийник",         "Ketma-ket",            "On a streak",
                "3 ивента подряд без пропусков",
                "Ketma-ket 3 ta tadbir",
                "3 events in a row without missing"),

    Achievement("streak_5",      "🚀", "Неудержимый",      "To'xtatib bo'lmas",    "Unstoppable",
                "5 ивентов подряд!",
                "Ketma-ket 5 ta tadbir!",
                "5 events in a row!"),

    Achievement("rating_8",      "💫", "Высокая оценка",   "Yuqori baho",          "High rating",
                "Средний рейтинг 8.0+",
                "O'rtacha reyting 8.0+",
                "Average rating 8.0+"),

    Achievement("rating_9",      "🏅", "Почти идеален",    "Deyarli mukammal",     "Nearly perfect",
                "Средний рейтинг 9.0+",
                "O'rtacha reyting 9.0+",
                "Average rating 9.0+"),

    Achievement("top3_once",     "🥉", "В тройке лидеров", "Uchlik liderlarda",    "Top 3",
                "Попал в топ-3 лучших волонтёров месяца",
                "Oyning eng yaxshi 3 ta volontyoridan biri",
                "Made it to the top 3 volunteers of the month"),

    Achievement("no_points",     "😇", "Чистая репутация", "Toza obro'",           "Clean record",
                "10 ивентов без единого поинта нарушения",
                "10 ta tadbir, birorta ham jarima yo'q",
                "10 events without a single violation point"),

    Achievement("referral_3",    "🤝", "Амбассадор",       "Ambassador",           "Ambassador",
                "Пригласил 3 и более участников",
                "3 va undan ko'p ishtirokchi taklif qildi",
                "Invited 3 or more participants"),
]

ACHIEVEMENTS_MAP = {a.key: a for a in ACHIEVEMENTS}


def get_title(ach: Achievement, lang: str) -> str:
    return {"ru": ach.title_ru, "uz": ach.title_uz, "en": ach.title_en}.get(lang, ach.title_ru)


def get_desc(ach: Achievement, lang: str) -> str:
    return {"ru": ach.desc_ru, "uz": ach.desc_uz, "en": ach.desc_en}.get(lang, ach.desc_ru)


def check_and_award(tg_id: int) -> list[Achievement]:
    """
    Проверяет все достижения для пользователя.
    Возвращает список НОВЫХ (только что полученных) достижений.
    """
    from database import get_user, get_user_events, get_conn, _q, _rows

    user = get_user(tg_id)
    if not user:
        return []

    exp        = user.get("experience", 0)
    streak     = user.get("streak", 0)
    rating     = float(user.get("rating", 0))
    points     = user.get("points", 0)
    referrals  = user.get("referral_count", 0)

    # Считаем сколько раз был в топ-3 (через карточки достижений)
    conn = get_conn()
    c    = conn.cursor()
    c.execute(_q("SELECT key FROM achievement_cards WHERE tg_id=?"), (tg_id,))
    from database import _rows as db_rows
    already_rows = db_rows(c)
    conn.close()
    already_keys = {r["key"] for r in already_rows}

    earned = []

    def _check(key: str, condition: bool):
        if condition and key not in already_keys:
            earned.append(ACHIEVEMENTS_MAP[key])

    _check("first_event",  exp >= 1)
    _check("events_5",     exp >= 5)
    _check("events_10",    exp >= 10)
    _check("events_25",    exp >= 25)
    _check("streak_3",     streak >= 3)
    _check("streak_5",     streak >= 5)
    _check("rating_8",     rating >= 8.0 and exp >= 3)
    _check("rating_9",     rating >= 9.0 and exp >= 5)
    _check("no_points",    exp >= 10 and points == 0)
    _check("referral_3",   referrals >= 3)
    # top3_once — выдаётся вручную через scheduler

    if earned:
        _save_achievements(tg_id, earned)

    return earned


def _save_achievements(tg_id: int, achievements: list[Achievement]):
    from database import get_conn, _q, BACKEND
    conn = get_conn()
    c    = conn.cursor()

    # Создаём таблицу если нет
    if BACKEND == "pg":
        c.execute("""CREATE TABLE IF NOT EXISTS achievement_cards (
            id        SERIAL PRIMARY KEY,
            tg_id     BIGINT NOT NULL,
            key       TEXT NOT NULL,
            issued_at TEXT DEFAULT (to_char(now(), 'YYYY-MM-DD HH24:MI:SS')),
            UNIQUE(tg_id, key)
        )""")
    else:
        c.execute("""CREATE TABLE IF NOT EXISTS achievement_cards (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            tg_id     INTEGER NOT NULL,
            key       TEXT NOT NULL,
            issued_at TEXT DEFAULT (datetime('now')),
            UNIQUE(tg_id, key)
        )""")

    for ach in achievements:
        try:
            if BACKEND == "pg":
                c.execute("INSERT INTO achievement_cards (tg_id, key) VALUES (%s,%s) ON CONFLICT DO NOTHING",
                          (tg_id, ach.key))
            else:
                c.execute("INSERT OR IGNORE INTO achievement_cards (tg_id, key) VALUES (?,?)",
                          (tg_id, ach.key))
        except Exception as e:
            logger.warning(f"Achievement save error: {e}")

    conn.commit()
    conn.close()


def get_user_achievements(tg_id: int) -> list[dict]:
    """Возвращает список полученных достижений пользователя."""
    from database import get_conn, _q, _rows, BACKEND

    conn = get_conn()
    c    = conn.cursor()
    try:
        c.execute(_q("SELECT * FROM achievement_cards WHERE tg_id=? ORDER BY issued_at DESC"), (tg_id,))
        rows = _rows(c)
    except Exception:
        rows = []
    conn.close()

    result = []
    for r in rows:
        ach = ACHIEVEMENTS_MAP.get(r["key"])
        if ach:
            result.append({
                "key":       ach.key,
                "emoji":     ach.emoji,
                "title_ru":  ach.title_ru,
                "title_uz":  ach.title_uz,
                "title_en":  ach.title_en,
                "desc_ru":   ach.desc_ru,
                "desc_uz":   ach.desc_uz,
                "desc_en":   ach.desc_en,
                "issued_at": r.get("issued_at",""),
            })
    return result


def award_top3(tg_id: int):
    """Выдать бейдж top3_once вручную (из scheduler)."""
    ach = ACHIEVEMENTS_MAP.get("top3_once")
    if ach:
        _save_achievements(tg_id, [ach])
