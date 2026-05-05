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
from utils.achievements import _save_achievements  # noqa

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s — %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger(__name__)

# Конфигурация из переменных окружения
WEBHOOK_HOST = os.environ.get("WEBHOOK_HOST", "")
WEBHOOK_PATH = "/webhook"
WEBHOOK_URL  = f"{WEBHOOK_HOST}{WEBHOOK_PATH}" if WEBHOOK_HOST else ""
WEB_PORT     = int(os.environ.get("PORT", 8080))

async def on_startup(bot: Bot):
    """Действия при запуске бота."""
    init_db()
    logger.info("База данных инициализирована ✓")

    try:
        init_audit_table()
        from database import init_roles_table, init_templates_table
        init_roles_table()
        init_templates_table()
        logger.info("Вспомогательные таблицы готовы ✓")
    except Exception as e:
        logger.warning(f"Таблицы (не критично): {e}")

    if WEBHOOK_URL:
        await bot.set_webhook(WEBHOOK_URL, drop_pending_updates=True)
        logger.info(f"Webhook установлен: {WEBHOOK_URL} ✓")
    else:
        await bot.delete_webhook(drop_pending_updates=True)
        logger.info("Режим polling (webhook удален) ✓")

async def on_shutdown(bot: Bot):
    """Действия при остановке бота."""
    if WEBHOOK_URL:
        await bot.delete_webhook()
    logger.info("Бот остановлен.")

async def keepalive_loop():
    """Пингует /health каждые 10 минут — не даёт Render усыпить процесс."""
    import aiohttp
    await asyncio.sleep(90)  # Даем время серверу подняться
    while True:
        try:
            # Пингуем сами себя через локальный адрес
            url = f"http://0.0.0.0:{WEB_PORT}/health"
            async with aiohttp.ClientSession() as s:
                await s.get(url, timeout=aiohttp.ClientTimeout(total=10))
            logger.debug("keepalive ✓")
        except Exception:
            pass
        await asyncio.sleep(600)

async def background(bot: Bot):
    """Запуск фоновых задач."""
    await asyncio.gather(
        monthly_scheduler(bot),
        reminder_scheduler(bot),
        deadline_scheduler(bot),
        cleanup_loop(),
        keepalive_loop(),
        return_exceptions=True
    )

async def health(_req):
    """Хендлер для проверки работоспособности (Health Check)."""
    return web.Response(text="OK", status=200)

async def main():
    # 1. Инициализация бота и диспетчера
    bot = Bot(token=BOT_TOKEN)
    dp  = Dispatcher(storage=MemoryStorage())

    # Регистрация системных событий
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

    # Регистрация роутеров
    dp.include_router(admin.router)
    dp.include_router(organizer_router)
    dp.include_router(user.router)

    # 2. Создание веб-приложения (ВСЕГДА для Render)
    app = web.Application()
    app.router.add_get("/health", health)
    app.router.add_get("/", health)

    # 3. Настройка режима работы
    if WEBHOOK_URL:
        # Режим Webhook
        handler = SimpleRequestHandler(dispatcher=dp, bot=bot)
        handler.register(app, path=WEBHOOK_PATH)
        setup_application(app, dp, bot=bot)
        logger.info(f"🚀 Запуск в режиме Webhook на порту {WEB_PORT}")
    else:
        # Режим Polling
        logger.info(f"🚀 Запуск в режиме Polling + HTTP сервер на порту {WEB_PORT}")
        # Запускаем polling как фоновую задачу
        asyncio.create_task(dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types()))

    # 4. Запуск фоновых задач
    asyncio.create_task(background(bot))

    # 5. Запуск HTTP сервера (критично для Render Web Service)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", WEB_PORT)
    await site.start()

    # 6. Удержание процесса
    try:
        await asyncio.Event().wait()
    finally:
        await runner.cleanup()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Бот выключен пользователем.")