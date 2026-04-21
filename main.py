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
from utils.achievements import _save_achievements  # noqa — triggers table creation on import

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s — %(message)s",
    datefmt="%H:%M:%S"
)

# Отдельный тихий логгер для audit
audit_log = logging.getLogger("sov.audit")
audit_handler = logging.FileHandler("audit.log", encoding="utf-8")
audit_handler.setFormatter(logging.Formatter("%(message)s"))
audit_log.addHandler(audit_handler)
audit_log.setLevel(logging.INFO)

logger = logging.getLogger(__name__)

# ── Конфигурация webhook ──────────────────────────────────────────────────────
WEBHOOK_HOST = os.environ.get("WEBHOOK_HOST", "")   # например https://sov-bot.onrender.com
WEBHOOK_PATH = "/webhook"
WEBHOOK_URL  = f"{WEBHOOK_HOST}{WEBHOOK_PATH}" if WEBHOOK_HOST else ""
WEB_PORT     = int(os.environ.get("PORT", 8080))


async def on_startup(bot: Bot):
    init_db()
    logger.info("База данных инициализирована ✓")

    # Дополнительные таблицы
    try:
        init_audit_table()
        from database import init_roles_table, init_templates_table
        init_roles_table()
        init_templates_table()
        logger.info("Вспомогательные таблицы готовы ✓")
    except Exception as e:
        logger.warning(f"Таблицы (не критично): {e}")

    # Webhook или polling — определяем по наличию WEBHOOK_HOST
    if WEBHOOK_URL:
        await bot.set_webhook(WEBHOOK_URL)
        logger.info(f"Webhook установлен: {WEBHOOK_URL} ✓")
    else:
        await bot.delete_webhook(drop_pending_updates=True)
        logger.info("Режим polling ✓")


async def on_shutdown(bot: Bot):
    if WEBHOOK_URL:
        await bot.delete_webhook()
    logger.info("Бот остановлен.")


async def main():
    bot = Bot(token=BOT_TOKEN)
    dp  = Dispatcher(storage=MemoryStorage())

    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

    # Роутеры — порядок важен (более специфичные раньше)
    dp.include_router(admin.router)
    dp.include_router(organizer_router)
    dp.include_router(user.router)

    # Фоновые задачи
    async def background(bot: Bot):
        await asyncio.gather(
            monthly_scheduler(bot),
            reminder_scheduler(bot),
            deadline_scheduler(bot),
            cleanup_loop(),
        )

    if WEBHOOK_URL:
        # ── Webhook режим (Render) ──────────────────────────────────────────
        app = web.Application()
        handler = SimpleRequestHandler(dispatcher=dp, bot=bot)
        handler.register(app, path=WEBHOOK_PATH)
        setup_application(app, dp, bot=bot)

        async def start_bg(_app):
            asyncio.create_task(background(bot))
        app.on_startup.append(start_bg)

        logger.info(f"🚀 Запуск webhook на порту {WEB_PORT}")
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "0.0.0.0", WEB_PORT)
        await site.start()
        # Держим сервер живым
        await asyncio.Event().wait()

    else:
        # ── Polling режим (локальная разработка) ───────────────────────────
        logger.info("🚀 Запуск в режиме polling (локально)")
        asyncio.create_task(background(bot))
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())


if __name__ == "__main__":
    asyncio.run(main())
