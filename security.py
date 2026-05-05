"""
security.py — защита SOV Bot.
Rate limiting, SQL-injection protection, input sanitization, transliteration.
"""
import re
import time
import logging
import html as _html
from collections import defaultdict

logger = logging.getLogger(__name__)

# ─── Rate limiting ─────────────────────────────────────────────────────────────
_call_times: dict = defaultdict(list)
_blocked:    dict = {}   # {tg_id: blocked_until}

RATE_LIMITS = {
    "message":   (25, 10),
    "callback":  (40, 10),
    "register":  (3,  60),
    "apply":     (5,  60),
    "proposal":  (2, 3600),
    "broadcast": (1,  300),
    "export":    (2,  600),
    "qr_scan":   (10,  60),
    "admin_cmd": (30,  60),
}
BLOCK_DURATION = 300   # 5 минут


def is_rate_blocked(tg_id: int) -> bool:
    until = _blocked.get(tg_id)
    if until and time.time() < until:
        return True
    _blocked.pop(tg_id, None)
    return False


def check_rate(tg_id: int, action: str) -> bool:
    """True = разрешено, False = заблокировано."""
    if is_rate_blocked(tg_id):
        return False
    max_calls, window = RATE_LIMITS.get(action, (30, 60))
    key = (tg_id, action)
    now = time.time()
    _call_times[key] = [t for t in _call_times[key] if now - t < window]
    if len(_call_times[key]) >= max_calls:
        _blocked[tg_id] = now + BLOCK_DURATION
        logger.warning(f"FLOOD uid={tg_id} action={action} blocked {BLOCK_DURATION}s")
        return False
    _call_times[key].append(now)
    return True


# ─── Транслитерация Кириллица → Латиница ─────────────────────────────────────
_CYR_LAT = {
    'а':'a','б':'b','в':'v','г':'g','д':'d','е':'e','ё':'yo','ж':'zh',
    'з':'z','и':'i','й':'y','к':'k','л':'l','м':'m','н':'n','о':'o',
    'п':'p','р':'r','с':'s','т':'t','у':'u','ф':'f','х':'kh','ц':'ts',
    'ч':'ch','ш':'sh','щ':'sch','ъ':'','ы':'y','ь':'','э':'e','ю':'yu','я':'ya',
    'А':'A','Б':'B','В':'V','Г':'G','Д':'D','Е':'E','Ё':'Yo','Ж':'Zh',
    'З':'Z','И':'I','Й':'Y','К':'K','Л':'L','М':'M','Н':'N','О':'O',
    'П':'P','Р':'R','С':'S','Т':'T','У':'U','Ф':'F','Х':'Kh','Ц':'Ts',
    'Ч':'Ch','Ш':'Sh','Щ':'Sch','Ъ':'','Ы':'Y','Ь':'','Э':'E','Ю':'Yu','Я':'Ya',
    # Узбекские буквы
    'қ':'q','Қ':'Q','ғ':"g'",'Ғ':"G'",'ҳ':'h','Ҳ':'H',
}


def transliterate(text: str) -> str:
    """Кириллица → латиница. Остальные символы без изменений."""
    return ''.join(_CYR_LAT.get(ch, ch) for ch in text)


def normalize_group(group: str) -> str:
    """
    Нормализует название группы:
    • транслитерирует кириллицу
    • верхний регистр
    • только A-Z, 0-9, -, /
    • максимум 20 символов
    """
    group = group.strip()
    group = transliterate(group)
    group = group.upper()
    group = re.sub(r"[^A-Z0-9\-/]", '', group)
    return group[:20]


def normalize_name(name: str) -> str:
    """Очищает ФИО от HTML-тегов и управляющих символов."""
    name = re.sub(r'[<>&]', '', name.strip())
    name = re.sub(r'[\x00-\x1f\x7f]', '', name)
    name = re.sub(r'\s+', ' ', name).strip()
    return name[:100]


# ─── SQL-инъекции ─────────────────────────────────────────────────────────────
_SQL_RE = re.compile(
    r"('|\")\s*(;|--|#|/\*)"
    r"|\b(DROP|DELETE|INSERT|UPDATE|ALTER|EXEC|UNION|SELECT|TRUNCATE|CAST|CONVERT)\b"
    r"|(--|;|/\*|\*/|WAITFOR|BENCHMARK|SLEEP\s*\(|0x[0-9a-f]+)",
    re.IGNORECASE
)


def is_sql_injection(text: str) -> bool:
    if not text:
        return False
    return bool(_SQL_RE.search(text))


def sanitize_text(text: str, max_len: int = 500) -> str:
    """Базовая санитизация: обрезка, убрать управляющие символы."""
    if not text:
        return ""
    text = str(text)[:max_len]
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', text)
    return text.strip()


def validate_score(value: str):
    """Возвращает float 1.0–10.0 или None."""
    try:
        score = float(str(value).replace(',', '.'))
        if 1.0 <= score <= 10.0:
            return round(score, 1)
    except (ValueError, AttributeError):
        pass
    return None


def validate_integer(value: str, min_val: int = 1, max_val: int = 500):
    """Возвращает int в диапазоне или None."""
    try:
        n = int(str(value).strip())
        if min_val <= n <= max_val:
            return n
    except (ValueError, AttributeError):
        pass
    return None


# ─── Aiogram Security Middleware ──────────────────────────────────────────────
from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery
from typing import Callable, Any, Awaitable


class SecurityMiddleware(BaseMiddleware):
    """
    Применяется к каждому update:
    - Rate limiting (флуд)
    - SQL-инъекции в тексте и callback_data
    - Огромные сообщения (DoS)
    """

    async def __call__(
        self,
        handler: Callable[[Any, dict], Awaitable[Any]],
        event: Any,
        data: dict,
    ) -> Any:
        tg_id  = None
        action = "message"

        if isinstance(event, Message):
            tg_id  = event.from_user.id
            action = "message"
            if event.text:
                if len(event.text) > 4096:
                    return  # молча дропаем огромные сообщения
                if is_sql_injection(event.text):
                    logger.warning(f"SQLi attempt uid={tg_id} text={event.text[:80]}")
                    try:
                        await event.answer("⚠️ Недопустимые символы в запросе.")
                    except Exception:
                        pass
                    return

        elif isinstance(event, CallbackQuery):
            tg_id  = event.from_user.id
            action = "callback"
            if event.data and is_sql_injection(event.data):
                logger.warning(f"SQLi in callback uid={tg_id} data={event.data[:80]}")
                try:
                    await event.answer("⚠️ Недопустимый запрос.", show_alert=True)
                except Exception:
                    pass
                return

        if tg_id and not check_rate(tg_id, action):
            if isinstance(event, Message):
                try:
                    await event.answer("⛔ Слишком много запросов. Подожди немного.")
                except Exception:
                    pass
            elif isinstance(event, CallbackQuery):
                try:
                    await event.answer("⛔ Слишком часто.", show_alert=False)
                except Exception:
                    pass
            return

        return await handler(event, data)
