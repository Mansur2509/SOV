import asyncio
import logging
from datetime import datetime, timedelta

from aiogram import Bot
from database import get_all_users, get_top_users, get_all_events, get_selected_for_event, get_event

logger = logging.getLogger(__name__)


# ─── Ежемесячный топ-3 ───────────────────────────────────────────────────────

async def send_monthly_top(bot: Bot):
    top = get_top_users(3)
    if not top: return

    medals = ["🥇", "🥈", "🥉"]
    lines  = [
        f"{medals[i]} <b>{u['full_name']}</b> ({u['group_name']})\n    ⭐ {u['rating']} | 🎯 {u['experience']} ив."
        for i, u in enumerate(top)
    ]
    month = datetime.now().strftime("%B %Y")
    text  = (
        f"🏆 <b>Лучшие волонтёры SOV за {month}!</b>\n\n"
        + "\n\n".join(lines)
        + "\n\n🎉 Поздравляем победителей!"
    )
    users = get_all_users()
    for user in users:
        try:
            await bot.send_message(user["tg_id"], text, parse_mode="HTML")
            await asyncio.sleep(0.05)
        except Exception:
            pass

    # Выдаём достижение top3_once победителям
    try:
        from utils.achievements import award_top3, get_title, get_desc
        for u in top:
            award_top3(u["tg_id"])
            l = u.get("lang", "ru")
            try:
                await bot.send_message(
                    u["tg_id"],
                    f"🏅 <b>Новое достижение!</b>\n\n🥉 <b>{'В тройке лидеров' if l=='ru' else 'Uchlik liderlarda' if l=='uz' else 'Top 3'}</b>\n"
                    f"<i>{'Попал в топ-3 лучших волонтёров месяца' if l=='ru' else 'Oyning eng yaxshi 3 ta volontyoridan biri' if l=='uz' else 'Made it to the top 3 volunteers of the month'}</i>",
                    parse_mode="HTML"
                )
            except Exception:
                pass
    except Exception as e:
        logger.warning(f"Achievement award error: {e}")


# ─── Напоминания о ивентах ───────────────────────────────────────────────────

REMINDER_OFFSETS = [
    (timedelta(hours=3),    "⏰ Напоминание: через 3 часа"),
    (timedelta(hours=1),    "⏰ Напоминание: через 1 час"),
    (timedelta(minutes=15), "🔔 Напоминание: через 15 минут"),
]

_sent_reminders: set = set()


async def send_reminders(bot: Bot):
    now    = datetime.now()
    events = get_all_events()

    for event in events:
        time_str = event.get("event_time", "")
        date_str = event.get("event_date", "")
        if not time_str or not date_str:
            continue

        event_dt = None
        for fmt in ["%d.%m.%Y %H:%M", "%Y-%m-%d %H:%M"]:
            try:
                event_dt = datetime.strptime(f"{date_str} {time_str}", fmt)
                break
            except ValueError:
                pass

        if not event_dt:
            continue

        volunteers = get_selected_for_event(event["id"])
        if not volunteers:
            continue

        loc   = event.get("location", "")
        meet  = event.get("meeting_point", "")

        for offset, label in REMINDER_OFFSETS:
            fire_at = event_dt - offset
            if abs((now - fire_at).total_seconds()) < 60:
                key = f"{event['id']}_{int(offset.total_seconds())}"
                if key in _sent_reminders:
                    continue
                _sent_reminders.add(key)

                msg = (
                    f"{label}\n"
                    f"<b>«{event['title']}»</b>\n"
                    f"🕐 {time_str}\n"
                    + (f"📍 {loc}\n" if loc else "")
                    + (f"🤝 Место встречи: {meet}\n" if meet else "")
                )
                for vol in volunteers:
                    try:
                        await bot.send_message(vol["tg_id"], msg, parse_mode="HTML")
                        await asyncio.sleep(0.03)
                    except Exception as e:
                        logger.warning(f"Напоминание не доставлено {vol['tg_id']}: {e}")

                logger.info(f"Напоминание отправлено для ивента {event['id']} ({offset})")


# ─── Главный цикл ────────────────────────────────────────────────────────────

async def monthly_scheduler(bot: Bot):
    while True:
        now = datetime.now()
        if now.day == 1 and now.hour == 10 and now.minute == 0:
            logger.info("Отправка ежемесячного топ-3...")
            await send_monthly_top(bot)
            await asyncio.sleep(70)
        else:
            await asyncio.sleep(30)


async def reminder_scheduler(bot: Bot):
    while True:
        try:
            await send_reminders(bot)
        except Exception as e:
            logger.error(f"Ошибка напоминаний: {e}")
        await asyncio.sleep(60)


# ─── Авто-закрытие по дедлайну ───────────────────────────────────────────────

async def deadline_scheduler(bot: Bot):
    """Проверяет дедлайны записи каждую минуту и закрывает набор."""
    while True:
        try:
            from database import get_events_with_expired_deadline, close_event, get_applications
            from config import ADMIN_IDS
            expired = get_events_with_expired_deadline()
            for event in expired:
                close_event(event["id"])
                logger.info(f"Авто-закрытие ивента {event['id']} по дедлайну")
                # Уведомляем участников с pending статусом
                apps = get_applications(event["id"])
                for app in apps:
                    if app["status"] == "pending":
                        try:
                            await bot.send_message(
                                app["tg_id"],
                                f"🔒 Дедлайн записи на ивент <b>«{event['title']}»</b> истёк.\n"
                                f"Набор автоматически закрыт.",
                                parse_mode="HTML"
                            )
                            await asyncio.sleep(0.04)
                        except Exception:
                            pass
                # Уведомляем админа
                for admin_id in ADMIN_IDS:
                    try:
                        await bot.send_message(
                            admin_id,
                            f"⏰ <b>Дедлайн истёк!</b>\n"
                            f"Ивент «{event['title']}» автоматически закрыт для записи.\n"
                            f"Запусти автоподбор через <b>📂 Все ивенты</b>.",
                            parse_mode="HTML"
                        )
                    except Exception:
                        pass
        except Exception as e:
            logger.error(f"Deadline scheduler error: {e}")
        await asyncio.sleep(60)
