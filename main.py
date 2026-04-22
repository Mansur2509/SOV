import asyncio
import logging
import os

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web

from config import BOT_TOKEN
from database import init_db
from handlers import user, admin
from handlers.organizer import router as organizer_router
from scheduler import monthly_scheduler, reminder_scheduler, deadline_scheduler
from utils.cache import cleanup_loop
from utils.audit import init_audit_table

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s — %(message)s",
    datefmt="%H:%M:%S"
)

audit_log = logging.getLogger("sov.audit")
try:
    fh = logging.FileHandler("audit.log", encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(message)s"))
    audit_log.addHandler(fh)
except Exception:
    pass
audit_log.setLevel(logging.INFO)

logger = logging.getLogger(__name__)

# ── Конфигурация ──────────────────────────────────────────────────────────────
WEBHOOK_HOST = os.environ.get("WEBHOOK_HOST", "").rstrip("/")
WEBHOOK_PATH = "/webhook"
WEBHOOK_URL  = f"{WEBHOOK_HOST}{WEBHOOK_PATH}" if WEBHOOK_HOST else ""
WEB_PORT     = int(os.environ.get("PORT", 8080))
USE_WEBHOOK  = bool(WEBHOOK_HOST)


def init_all():
    init_db()
    logger.info("База данных инициализирована ✓")
    try:
        init_audit_table()
        from database import init_roles_table, init_templates_table
        init_roles_table()
        init_templates_table()
        logger.info("Вспомогательные таблицы готовы ✓")
    except Exception as e:
        logger.warning(f"Доп. таблицы: {e}")
    try:
        from utils.achievements import _save_achievements
        _save_achievements(0, [])
    except Exception:
        pass


# ── Keepalive ─────────────────────────────────────────────────────────────────
async def keepalive_loop():
    """Пингует себя каждые 10 минут чтобы Render не засыпал."""
    import aiohttp as _aiohttp
    await asyncio.sleep(90)
    while True:
        try:
            url = f"http://127.0.0.1:{WEB_PORT}/health"
            async with _aiohttp.ClientSession() as s:
                async with s.get(url, timeout=_aiohttp.ClientTimeout(total=10)) as r:
                    logger.debug(f"keepalive → {r.status}")
        except Exception:
            pass
        await asyncio.sleep(600)


# ── Фоновые задачи ────────────────────────────────────────────────────────────
async def background(bot: Bot):
    await asyncio.gather(
        monthly_scheduler(bot),
        reminder_scheduler(bot),
        deadline_scheduler(bot),
        cleanup_loop(),
        keepalive_loop(),
        return_exceptions=True
    )


# ── Health-check хендлер ──────────────────────────────────────────────────────
async def health(_req):
    return web.Response(text="SOV Bot OK", status=200)


# ── Основная функция ──────────────────────────────────────────────────────────
async def main():
    bot = Bot(token=BOT_TOKEN)
    dp  = Dispatcher(storage=MemoryStorage())

    dp.include_router(admin.router)
    dp.include_router(organizer_router)
    dp.include_router(user.router)

    # Инициализируем БД
    init_all()

    # ── ВСЕГДА строим aiohttp приложение ─────────────────────────────────────
    # Это нужно чтобы Render видел открытый порт и не убивал процесс.
    app = web.Application()
    app.router.add_get("/",       health)
    app.router.add_get("/health", health)

    if USE_WEBHOOK:
        # Регистрируем webhook-хендлер
        handler = SimpleRequestHandler(dispatcher=dp, bot=bot)
        handler.register(app, path=WEBHOOK_PATH)
        setup_application(app, dp, bot=bot)

    # Стартуем HTTP сервер
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", WEB_PORT)
    await site.start()
    logger.info(f"HTTP сервер запущен на 0.0.0.0:{WEB_PORT} ✓")

    if USE_WEBHOOK:
        # Webhook режим
        await bot.delete_webhook(drop_pending_updates=True)
        await bot.set_webhook(WEBHOOK_URL)
        logger.info(f"🚀 Webhook режим: {WEBHOOK_URL}")
        asyncio.create_task(background(bot))
        await asyncio.Event().wait()  # держим сервер живым вечно

    else:
        # Polling режим — HTTP сервер уже запущен выше, polling идёт параллельно
        await bot.delete_webhook(drop_pending_updates=True)
        logger.info(f"🚀 Polling режим | HTTP на порту {WEB_PORT}")
        asyncio.create_task(background(bot))
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())


if __name__ == "__main__":
    asyncio.run(main())
