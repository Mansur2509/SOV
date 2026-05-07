import re
import io
import asyncio
import qrcode
from datetime import datetime

from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, BufferedInputFile, PhotoSize
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardButton

from config import PAIRS_SCHEDULE
from database import (
    get_all_users, get_user, update_user_notes, delete_user,
    get_all_events, get_event, create_event, close_event, delete_event,
    set_event_photo, set_event_card_photo,
    get_applications, auto_select, get_selected_for_event,
    get_selected_users_detail, set_application_status,
    manually_add_to_event, manually_remove_from_event,
    add_rating, get_top_users,
    add_points, get_point_history,
    ban_user, unban_user,
    create_announcement, get_announcements, get_announcements_count, delete_announcement,
    get_proposals, update_proposal_status, get_proposal,
    issue_card, issue_cards_bulk, generate_qr_token,
    close_event_work, complete_event, get_event_work_status,
    bulk_ban, bulk_unban, bulk_add_points, bulk_add_rating_score,
    adjust_rating, get_users_page, get_channel_id,
    is_banned, run_migrations,
)
from keyboards import (
    admin_menu_kb, admin_events_kb, admin_event_detail_kb,
    admin_users_kb, admin_user_detail_kb,
    rate_select_user_kb, rate_multi_kb, edit_selected_kb,
    give_card_events_kb, multi_select_users_kb,
    main_menu_kb, confirm_ban_kb, confirm_delete_kb,
    proposals_kb, proposal_action_kb,
    announcements_nav_kb,
)
from utils.tg_helpers import safe_edit_text

router = Router()


def is_admin(tg_id: int) -> bool:
    from config import ADMIN_IDS
    return tg_id in ADMIN_IDS


# ─── Пары по расписанию ──────────────────────────────────────────────────────

def get_pair_info(time_str: str) -> str:
    if not time_str:
        return ""
    try:
        t = datetime.strptime(time_str.strip(), "%H:%M").time()
    except ValueError:
        return ""
    for start, end, label in PAIRS_SCHEDULE:
        ts = datetime.strptime(start, "%H:%M").time()
        te = datetime.strptime(end,   "%H:%M").time()
        if ts <= t <= te:
            return f"({label})"
    return ""


# ─── FSM ─────────────────────────────────────────────────────────────────────

class CreateEventState(StatesGroup):
    title         = State()
    description   = State()
    event_date    = State()
    event_time    = State()
    location      = State()
    duration      = State()
    meeting_point = State()
    total_slots   = State()
    male_slots    = State()
    female_slots  = State()
    gender_strict = State()


class QuickEventState(StatesGroup):
    raw_text = State()
    confirm  = State()


class RateState(StatesGroup):
    score   = State()
    comment = State()


class NoteState(StatesGroup):
    note = State()


class PointReasonState(StatesGroup):
    reason = State()


class AnnouncementState(StatesGroup):
    text = State()


class ManualAddState(StatesGroup):
    tg_id = State()


class UploadImgState(StatesGroup):
    photo = State()


# ─── Вход/выход ──────────────────────────────────────────────────────────────

@router.message(Command("admin"))
async def cmd_admin(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("⛔ Нет доступа."); return
    await message.answer("🔧 <b>Панель администратора SOV</b>",
                         parse_mode="HTML", reply_markup=admin_menu_kb())


@router.message(F.text == "🔙 Выйти из админки")
async def exit_admin(message: Message):
    await message.answer("Вышел.", reply_markup=main_menu_kb())


# ─── Быстрое создание ивента из текста ──────────────────────────────────────

def parse_event_text(raw: str) -> dict:
    """Извлекает дату, время, место, название из произвольного текста анонса."""
    result = {}

    # Заголовок — первая непустая строка
    lines = [l.strip() for l in raw.strip().split("\n") if l.strip()]
    if lines:
        result["title"] = lines[0][:100]

    # Дата: ищем "9 April", "April 9", "9.04", "09/04" и т.д.
    date_patterns = [
        r'\b(\d{1,2})\s+(January|February|March|April|May|June|July|August|September|October|November|December)\b',
        r'\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2})\b',
        r'\b(\d{1,2})[./](\d{1,2})(?:[./](\d{2,4}))?\b',
    ]
    months_en = {"january":"01","february":"02","march":"03","april":"04","may":"05","june":"06",
                 "july":"07","august":"08","september":"09","october":"10","november":"11","december":"12"}
    for pat in date_patterns:
        m = re.search(pat, raw, re.IGNORECASE)
        if m:
            groups = m.groups()
            if groups[0].lower() in months_en:
                result["event_date"] = f"{groups[1]}.{months_en[groups[0].lower()]}"
            elif len(groups) > 1 and isinstance(groups[1], str) and groups[1].lower() in months_en:
                result["event_date"] = f"{groups[0]}.{months_en[groups[1].lower()]}"
            else:
                result["event_date"] = f"{groups[0]}.{groups[1] if len(groups)>1 else '??'}"
            break

    # Время: "11:30", "11.30", "at 10:00"
    time_m = re.search(r'\b(\d{1,2})[:\.](\d{2})\b', raw)
    if time_m:
        result["event_time"] = f"{time_m.group(1).zfill(2)}:{time_m.group(2)}"

    # Место: строка после "Venue:", "Location:", "Place:", "📍"
    venue_m = re.search(r'(?:Venue|Location|Place|📍)[:\s]+(.+)', raw, re.IGNORECASE)
    if venue_m:
        result["location"] = venue_m.group(1).strip()[:100]

    # Описание — весь текст
    result["description"] = raw[:800]
    return result


@router.message(F.text == "⚡ Быстрый ивент из текста")
async def quick_event_start(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id): return
    await state.set_state(QuickEventState.raw_text)
    await message.answer(
        "⚡ <b>Быстрое создание ивента</b>\n\n"
        "Скопируй и вставь текст объявления (с датой, временем, местом).\n"
        "Бот автоматически распознает данные:",
        parse_mode="HTML"
    )


@router.message(QuickEventState.raw_text)
async def quick_event_parse(message: Message, state: FSMContext):
    raw    = message.text.strip()
    parsed = parse_event_text(raw)
    await state.update_data(parsed=parsed, raw=raw)
    await state.set_state(QuickEventState.confirm)

    preview = (
        f"🔍 <b>Распознано:</b>\n\n"
        f"📌 Название: {parsed.get('title','—')}\n"
        f"📅 Дата: {parsed.get('event_date','—')}\n"
        f"🕐 Время: {parsed.get('event_time','—')}\n"
        f"📍 Место: {parsed.get('location','—')}\n\n"
        f"Создать ивент с этими данными?\n"
        f"<i>(потом можно отредактировать в базе через DB Browser)</i>"
    )
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="✅ Создать", callback_data="quick_confirm"),
        InlineKeyboardButton(text="❌ Отмена",  callback_data="quick_cancel"),
    )
    await message.answer(preview, parse_mode="HTML", reply_markup=builder.as_markup())


@router.callback_query(F.data == "quick_confirm")
async def quick_event_create(call: CallbackQuery, state: FSMContext):
    data   = await state.get_data()
    parsed = data.get("parsed", {})
    await state.clear()

    eid = create_event(
        title=parsed.get("title", "Новый ивент"),
        description=parsed.get("description", ""),
        event_date=parsed.get("event_date", "—"),
        event_time=parsed.get("event_time", ""),
        location=parsed.get("location", ""),
        duration="",
        meeting_point="",
        total_slots=10,
        male_slots=0,
        female_slots=0,
        gender_strict=0
    )
    await call.message.edit_text(
        f"✅ Ивент создан (ID: {eid})!\n\n"
        f"Уточни детали через <b>📂 Все ивенты</b> или отредактируй в DB Browser.",
        parse_mode="HTML"
    )
    await call.message.answer("⚙️", reply_markup=admin_menu_kb())
    await call.answer()


@router.callback_query(F.data == "quick_cancel")
async def quick_event_cancel(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.message.edit_text("❌ Отменено.")
    await call.answer()


# ─── Создание ивента вручную ─────────────────────────────────────────────────

@router.message(F.text == "➕ Создать ивент")
async def create_ev_start(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id): return
    await state.set_state(CreateEventState.title)
    await message.answer("📌 <b>Название ивента:</b>", parse_mode="HTML")


@router.message(CreateEventState.title)
async def cev_title(message: Message, state: FSMContext):
    await state.update_data(title=message.text.strip())
    await state.set_state(CreateEventState.description)
    await message.answer("📝 <b>Описание</b> (или «-»):", parse_mode="HTML")


@router.message(CreateEventState.description)
async def cev_desc(message: Message, state: FSMContext):
    await state.update_data(description="" if message.text.strip()=="-" else message.text.strip())
    await state.set_state(CreateEventState.event_date)
    await message.answer("📅 <b>Дата</b> (например: 25.05.2025):", parse_mode="HTML")


@router.message(CreateEventState.event_date)
async def cev_date(message: Message, state: FSMContext):
    await state.update_data(event_date=message.text.strip())
    await state.set_state(CreateEventState.event_time)
    await message.answer("🕐 <b>Время начала</b> (например: 10:00, или «-»):", parse_mode="HTML")


@router.message(CreateEventState.event_time)
async def cev_time(message: Message, state: FSMContext):
    await state.update_data(event_time="" if message.text.strip()=="-" else message.text.strip())
    await state.set_state(CreateEventState.location)
    await message.answer("📍 <b>Место проведения</b> (или «-»):", parse_mode="HTML")


@router.message(CreateEventState.location)
async def cev_location(message: Message, state: FSMContext):
    await state.update_data(location="" if message.text.strip()=="-" else message.text.strip())
    await state.set_state(CreateEventState.duration)
    await message.answer("⏱ <b>Длительность</b> (или «-»):", parse_mode="HTML")


@router.message(CreateEventState.duration)
async def cev_duration(message: Message, state: FSMContext):
    await state.update_data(duration="" if message.text.strip()=="-" else message.text.strip())
    await state.set_state(CreateEventState.meeting_point)
    await message.answer("🤝 <b>Место встречи волонтёров</b> (или «-»):", parse_mode="HTML")


@router.message(CreateEventState.meeting_point)
async def cev_meeting(message: Message, state: FSMContext):
    await state.update_data(meeting_point="" if message.text.strip()=="-" else message.text.strip())
    await state.set_state(CreateEventState.total_slots)
    await message.answer("👥 Всего <b>волонтёров</b>:", parse_mode="HTML")


@router.message(CreateEventState.total_slots)
async def cev_total(message: Message, state: FSMContext):
    if not message.text.strip().isdigit():
        await message.answer("⚠️ Число."); return
    await state.update_data(total_slots=int(message.text.strip()))
    await state.set_state(CreateEventState.male_slots)
    await message.answer("♂ <b>Парней</b> (0 = без квоты):", parse_mode="HTML")


@router.message(CreateEventState.male_slots)
async def cev_male(message: Message, state: FSMContext):
    if not message.text.strip().isdigit():
        await message.answer("⚠️ Число."); return
    await state.update_data(male_slots=int(message.text.strip()))
    await state.set_state(CreateEventState.female_slots)
    await message.answer("♀ <b>Девушек</b> (0 = без квоты):", parse_mode="HTML")


@router.message(CreateEventState.female_slots)
async def cev_female(message: Message, state: FSMContext):
    if not message.text.strip().isdigit():
        await message.answer("⚠️ Число."); return
    await state.update_data(female_slots=int(message.text.strip()))
    await state.set_state(CreateEventState.gender_strict)
    await message.answer(
        "🔒 <b>Строгое ограничение по полу?</b> (Да/Нет)\n"
        "Если Да — другой пол не сможет записаться вообще.",
        parse_mode="HTML"
    )


@router.message(CreateEventState.gender_strict)
async def cev_strict(message: Message, state: FSMContext, bot: Bot):
    strict = 1 if message.text.strip().lower() in ("да","yes","д","ha") else 0
    data   = await state.get_data()
    await state.clear()
    eid = create_event(
        title=data["title"], description=data["description"],
        event_date=data["event_date"], event_time=data["event_time"],
        location=data["location"], duration=data["duration"],
        meeting_point=data["meeting_point"],
        total_slots=data["total_slots"], male_slots=data["male_slots"],
        female_slots=data["female_slots"], gender_strict=strict
    )
    slots_info = f"{data['total_slots']} чел."
    if data["male_slots"] or data["female_slots"]:
        slots_info += f" (♂{data['male_slots']} / ♀{data['female_slots']})"

    await message.answer(
        f"✅ Ивент <b>«{data['title']}»</b> создан!\n"
        f"📅 {data['event_date']} {data['event_time']}\n"
        f"📍 {data['location'] or '—'} | 👥 {slots_info}\n"
        f"🔒 Строгий пол: {'Да' if strict else 'Нет'}\n\n"
        f"Загрузи фото ивента через кнопку «🖼 Загрузить фото» в списке ивентов.",
        parse_mode="HTML", reply_markup=admin_menu_kb()
    )
    # Пост нового ивента в канал
    new_event = get_event(eid)
    if new_event:
        try:
            await post_event_to_channel(bot, new_event)
        except Exception:
            pass

    # ── Рассылка всем участникам о новом ивенте ──────────────────────────────
    await _broadcast_new_event(bot, data["title"], data["event_date"],
                                data.get("event_time",""), data.get("location",""), slots_info)


# ─── Утилита: рассылка ───────────────────────────────────────────────────────

async def _broadcast_new_event(bot: Bot, title: str, date: str,
                                time: str, location: str, slots: str):
    """Рассылает всем активным участникам уведомление о новом ивенте."""
    users = get_all_users()
    from i18n import t
    notif_ru = (
        f"🆕 <b>Новый ивент SOV!</b>\n\n"
        f"📌 <b>{title}</b>\n"
        f"📅 {date}" + (f" в {time}" if time else "") + "\n"
        + (f"📍 {location}\n" if location else "")
        + f"👥 Мест: {slots}\n\n"
        f"Запись открыта → «📋 Активные ивенты»"
    )
    notif_uz = (
        f"🆕 <b>Yangi SOV tadbiri!</b>\n\n"
        f"📌 <b>{title}</b>\n"
        f"📅 {date}" + (f" soat {time}" if time else "") + "\n"
        + (f"📍 {location}\n" if location else "")
        + f"👥 O'rinlar: {slots}\n\n"
        f"Ro'yxat ochiq → «📋 Faol tadbirlar»"
    )
    notif_en = (
        f"🆕 <b>New SOV event!</b>\n\n"
        f"📌 <b>{title}</b>\n"
        f"📅 {date}" + (f" at {time}" if time else "") + "\n"
        + (f"📍 {location}\n" if location else "")
        + f"👥 Slots: {slots}\n\n"
        f"Sign up → «📋 Active events»"
    )
    notifs = {"ru": notif_ru, "uz": notif_uz, "en": notif_en}

    sent = 0
    for user in users:
        if not user.get("agreed"): continue
        banned, _ = is_banned(user["tg_id"])
        if banned: continue
        lang = user.get("lang","ru")
        try:
            await bot.send_message(user["tg_id"], notifs.get(lang, notif_ru), parse_mode="HTML")
            sent += 1
            await asyncio.sleep(0.04)
        except Exception:
            pass
    logger.info(f"Broadcast new event sent to {sent} users")


async def _broadcast_close_event(bot: Bot, event_id: int, title: str, date: str):
    """Уведомляет всех подавших заявку о закрытии набора."""
    apps = get_applications(event_id)
    pending = [a for a in apps if a["status"] == "pending"]
    for a in pending:
        lang = get_user(a["tg_id"]).get("lang","ru") if get_user(a["tg_id"]) else "ru"
        msgs = {
            "ru": f"🔒 Набор на ивент <b>«{title}»</b> ({date}) закрыт.\n\nРезультаты придут отдельным сообщением.",
            "uz": f"🔒 <b>«{title}»</b> ({date}) tadbiri uchun ro'yxat yopildi.",
            "en": f"🔒 Registration for <b>«{title}»</b> ({date}) is closed.",
        }
        try:
            await bot.send_message(a["tg_id"], msgs.get(lang, msgs["ru"]), parse_mode="HTML")
            await asyncio.sleep(0.04)
        except Exception:
            pass


# ─── Все ивенты ──────────────────────────────────────────────────────────────

@router.message(F.text == "📂 Все ивенты")
async def all_events(message: Message):
    if not is_admin(message.from_user.id): return
    events = get_all_events()
    if not events:
        await message.answer("Ивентов нет."); return
    await message.answer("📂 <b>Все ивенты</b>:", parse_mode="HTML",
                         reply_markup=admin_events_kb(events))


@router.callback_query(F.data.regexp(r"^adm_event_(\d+)$"))
async def adm_event_detail(call: CallbackQuery):
    event_id = int(call.data.split("_")[2])
    event    = get_event(event_id)
    if not event:
        await call.answer("Не найдено."); return
    apps  = get_applications(event_id)
    sel   = sum(1 for a in apps if a["status"]=="selected")
    pend  = sum(1 for a in apps if a["status"]=="pending")
    text  = (
        f"📌 <b>{event['title']}</b>\n"
        f"📅 {event['event_date']} {event.get('event_time','')}\n"
        f"📍 {event.get('location','—')} | ⏱ {event.get('duration','—')}\n"
        f"🤝 {event.get('meeting_point','—')}\n"
        f"👥 {event['total_slots']} | 🔒 Строгий: {'Да' if event.get('gender_strict') else 'Нет'}\n"
        f"{'🟢 Открыт' if event['is_active'] else '🔴 Закрыт'} | 📨 {len(apps)} заявок (⏳{pend} ✅{sel})"
    )
    await call.message.edit_text(text, parse_mode="HTML",
                                  reply_markup=admin_event_detail_kb(event_id, bool(event["is_active"])))


@router.callback_query(F.data.regexp(r"^close_event_(\d+)$"))
async def adm_close_event(call: CallbackQuery, bot: Bot):
    event_id = int(call.data.split("_")[2])
    event    = get_event(event_id)
    close_event(event_id)
    await call.answer("🔒 Закрыт.", show_alert=True)
    await adm_event_detail(call)
    await _broadcast_close_event(bot, event_id, event["title"], event["event_date"])


@router.callback_query(F.data == "back_adm_events")
async def back_adm_events(call: CallbackQuery):
    events = get_all_events()
    await call.message.edit_text("📂 <b>Все ивенты</b>:", parse_mode="HTML",
                                  reply_markup=admin_events_kb(events))


# ─── Удаление ивента ─────────────────────────────────────────────────────────

@router.callback_query(F.data.regexp(r"^del_event_(\d+)$"))
async def del_event_confirm(call: CallbackQuery):
    event_id = int(call.data.split("_")[2])
    event    = get_event(event_id)
    await call.message.edit_text(
        f"🗑 Удалить ивент <b>«{event['title']}»</b>?\nВсе заявки и карточки будут удалены!",
        parse_mode="HTML",
        reply_markup=confirm_delete_kb("event", event_id)
    )


@router.callback_query(F.data.regexp(r"^del_confirm_event_(\d+)$"))
async def del_event_apply(call: CallbackQuery):
    event_id = int(call.data.split("_")[3])
    delete_event(event_id)
    await call.message.edit_text("🗑 Ивент удалён.")
    await call.answer()


# ─── Загрузка фото ивента ────────────────────────────────────────────────────

@router.callback_query(F.data.regexp(r"^upload_img_(\d+)$"))
async def upload_img_start(call: CallbackQuery, state: FSMContext):
    event_id = int(call.data.split("_")[2])
    await state.update_data(upload_event_id=event_id)
    await state.set_state(UploadImgState.photo)
    await call.message.answer("🖼 Отправь фото для ивента:")
    await call.answer()


@router.message(UploadImgState.photo, F.photo)
async def upload_img_save(message: Message, state: FSMContext):
    data     = await state.get_data()
    event_id = data["upload_event_id"]
    file_id  = message.photo[-1].file_id
    set_event_photo(event_id, file_id)
    await state.clear()
    await message.answer("✅ Фото ивента сохранено!", reply_markup=admin_menu_kb())


# ─── Заявки ──────────────────────────────────────────────────────────────────

@router.callback_query(F.data.regexp(r"^adm_apps_(\d+)$"))
async def adm_applications(call: CallbackQuery):
    event_id = int(call.data.split("_")[2])
    apps     = get_applications(event_id)
    if not apps:
        await call.answer("Заявок нет.", show_alert=True); return
    lines = []
    for a in apps:
        icon = {"selected":"✅","pending":"⏳","rejected":"❌"}.get(a["status"],"❓")
        gi   = "♂" if a["gender"]=="М" else "♀"
        att  = " 🎯" if a.get("attended") else ""
        lines.append(f"{icon}{gi} {a['full_name']} ({a['group_name']}) ⭐{a['rating']}{att}")
    await call.message.edit_text(
        "📨 <b>Заявки</b>\n\n" + "\n".join(lines), parse_mode="HTML",
        reply_markup=admin_event_detail_kb(event_id, True)
    )


# ─── Ручное добавление/удаление участника ────────────────────────────────────

@router.callback_query(F.data.regexp(r"^manual_add_(\d+)$"))
async def manual_add_start(call: CallbackQuery, state: FSMContext):
    event_id = int(call.data.split("_")[2])
    await state.update_data(manual_event_id=event_id)
    await state.set_state(ManualAddState.tg_id)
    await call.message.answer(
        "👤 Введи <b>Telegram ID</b> участника которого хочешь добавить:\n"
        "<i>(Узнать ID — попроси участника написать @userinfobot)</i>",
        parse_mode="HTML"
    )
    await call.answer()


@router.message(ManualAddState.tg_id)
async def manual_add_apply(message: Message, state: FSMContext, bot: Bot):
    data     = await state.get_data()
    event_id = data["manual_event_id"]
    try:
        tg_id = int(message.text.strip())
    except ValueError:
        await message.answer("⚠️ Введи числовой Telegram ID."); return
    user = get_user(tg_id)
    if not user:
        await message.answer("❌ Участник не найден в базе SOV."); return
    await state.clear()
    success = manually_add_to_event(event_id, tg_id)
    event   = get_event(event_id)
    if success:
        await message.answer(
            f"✅ <b>{user['full_name']}</b> добавлен на ивент «{event['title']}».",
            parse_mode="HTML", reply_markup=admin_menu_kb()
        )
        try:
            await bot.send_message(
                tg_id,
                f"🎉 Тебя добавили на ивент <b>«{event['title']}»</b> ({event['event_date']})!\n"
                f"📍 {event.get('location','')}\n🕐 {event.get('event_time','')}",
                parse_mode="HTML"
            )
        except Exception:
            pass
    else:
        await message.answer("❌ Не удалось добавить.")


@router.callback_query(F.data.regexp(r"^manual_remove_(\d+)_(\d+)$"))
async def manual_remove(call: CallbackQuery, bot: Bot):
    parts    = call.data.split("_")
    event_id = int(parts[2])
    tg_id    = int(parts[3])
    user     = get_user(tg_id)
    event    = get_event(event_id)
    manually_remove_from_event(event_id, tg_id)
    await call.answer(f"✅ {user['full_name']} удалён из ивента.", show_alert=True)
    try:
        await bot.send_message(
            tg_id,
            f"ℹ️ Тебя убрали из списка участников ивента «{event['title']}».",
            parse_mode="HTML"
        )
    except Exception:
        pass


# ─── Автоподбор + список для отпрашивания ────────────────────────────────────

@router.callback_query(F.data.regexp(r"^autoselect_(\d+)$"))
async def adm_autoselect(call: CallbackQuery, bot: Bot):
    event_id = int(call.data.split("_")[1])
    event    = get_event(event_id)
    result   = auto_select(event_id)
    selected = result["selected"]
    rejected = result["rejected"]
    if not selected:
        await call.answer("😔 Нет заявок.", show_alert=True); return

    pair_info = get_pair_info(event.get("event_time",""))
    time_str  = event.get("event_time","")
    pair_str  = f" {pair_info}" if pair_info else ""

    lines = [f"{i}. {s['full_name']} {s['group_name']}" for i, s in enumerate(selected, 1)]
    report = (
        f"📋 <b>Просьба отпросить волонтёров на ивент</b>\n"
        f"«<b>{event['title']}</b>»\n"
        f"📅 {event['event_date']} в {time_str}{pair_str}\n\n"
        + "\n".join(lines)
    )
    await call.message.answer(report, parse_mode="HTML")
    if rejected:
        rej_lines = [f"— {'♂' if r['gender']=='М' else '♀'} {r['full_name']}" for r in rejected]
        await call.message.answer(f"❌ <b>Не прошли:</b>\n" + "\n".join(rej_lines), parse_mode="HTML")

    # Пост в канал при создании набора
    try:
        await post_event_to_channel(bot, event)
    except Exception:
        pass

    await call.answer("✅ Готово!", show_alert=True)

    # Спрашиваем хочет ли редактировать список
    from keyboards import edit_selected_kb
    await call.message.answer(
        f"✅ Автоподбор завершён: выбрано <b>{len(selected)}</b> чел.\n\nХочешь изменить список вручную?",
        parse_mode="HTML",
        reply_markup=edit_selected_kb(event_id, selected)
    )

    for s in selected:
        try:
            await bot.send_message(
                s["tg_id"],
                f"🎉 Ты выбран волонтёром на <b>«{event['title']}»</b>!\n"
                f"📅 {event['event_date']}" + (f" в {time_str}" if time_str else "")
                + (f"\n📍 {event.get('location','')}" if event.get("location") else "")
                + (f"\n🤝 Место встречи: {event.get('meeting_point','')}" if event.get("meeting_point") else "")
                + "\n\nОжидай напоминания перед ивентом.",
                parse_mode="HTML"
            )
        except Exception:
            pass


# ─── QR генерация ────────────────────────────────────────────────────────────

@router.callback_query(F.data.regexp(r"^gen_qr_(\d+)$"))
async def gen_qr(call: CallbackQuery, bot: Bot):
    event_id = int(call.data.split("_")[2])
    event    = get_event(event_id)
    token    = generate_qr_token(event_id)

    bot_info = await bot.get_me()
    qr_url   = f"https://t.me/{bot_info.username}?start=qrcheck_{token}"

    # Генерируем QR изображение
    img = qrcode.make(qr_url)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)

    await call.message.answer_photo(
        BufferedInputFile(buf.getvalue(), filename="qr.png"),
        caption=(
            f"🔲 <b>QR-код для ивента «{event['title']}»</b>\n\n"
            f"Покажи этот QR волонтёрам на месте.\n"
            f"Они сканируют его камерой — откроется бот и подтвердит присутствие.\n\n"
            f"Или ссылка: <code>{qr_url}</code>"
        ),
        parse_mode="HTML"
    )
    await call.answer()


# ─── Выдача карточек ─────────────────────────────────────────────────────────

@router.callback_query(F.data.regexp(r"^issue_cards_(\d+)$"))
async def issue_cards(call: CallbackQuery, bot: Bot):
    event_id   = int(call.data.split("_")[2])
    volunteers = get_selected_for_event(event_id)
    event      = get_event(event_id)
    issued     = 0
    for vol in volunteers:
        if issue_card(vol["tg_id"], event_id):
            issued += 1
            try:
                await bot.send_message(
                    vol["tg_id"],
                    f"🎴 <b>Тебе выдана карточка участника!</b>\n\n"
                    f"Ивент: <b>«{event['title']}»</b> ({event['event_date']})\n\n"
                    f"Смотри карточки в разделе «🎴 Мои карточки».",
                    parse_mode="HTML"
                )
                await asyncio.sleep(0.05)
            except Exception:
                pass
    await call.answer(f"✅ Выдано карточек: {issued}", show_alert=True)
    # Уведомляем с фото карточки если есть
    card_photo = event.get("card_photo_file_id") or event.get("photo_file_id")
    for vol in volunteers:
        if issue_card(vol["tg_id"], event_id):
            try:
                caption = (
                    f"🎴 <b>Тебе выдана карточка участника!</b>\n\n"
                    f"Ивент: <b>«{event['title']}»</b> ({event['event_date']})\n"
                    f"Смотри в «🎴 Мои карточки»."
                )
                if card_photo:
                    await bot.send_photo(vol["tg_id"], card_photo, caption=caption, parse_mode="HTML")
                else:
                    await bot.send_message(vol["tg_id"], caption, parse_mode="HTML")
                import asyncio as _asyncio
                await _asyncio.sleep(0.05)
            except Exception:
                pass


# ─── Участники ───────────────────────────────────────────────────────────────

@router.message(F.text == "👥 Все участники")
async def all_users_handler(message: Message):
    if not is_admin(message.from_user.id): return
    users, total = get_users_page(page=0, per_page=30)
    if not users:
        await message.answer("Участников нет."); return
    await message.answer(
        f"👥 <b>Все участники</b> ({total} чел.):",
        parse_mode="HTML",
        reply_markup=admin_users_kb(users, page=0, total=total)
    )


@router.callback_query(F.data.regexp(r"^adm_user_(\d+)$"))
async def adm_user_detail(call: CallbackQuery):
    tg_id = int(call.data.split("_")[2])
    user  = get_user(tg_id)
    if not user:
        await call.answer("Не найден."); return
    gi  = "♂" if user["gender"]=="М" else "♀"
    pts = user.get("points",0)
    ban_status = "✅ Активен"
    if user["ban_type"] == "full":
        ban_status = "🚫 Постоянный бан"
    elif user["ban_type"] == "temp" and user["ban_until"]:
        bu = datetime.fromisoformat(user["ban_until"]).strftime("%d.%m.%Y")
        ban_status = f"⏳ Бан до {bu}"
    notes  = user["notes"] or "<i>Заметок нет</i>"
    streak = user.get("streak",0)
    lang   = user.get("lang","ru")
    ref_c  = user.get("referral_count",0)
    text = (
        f"{gi} <b>{user['full_name']}</b>\n"
        f"📚 {user['group_name']} | 🌐 {lang.upper()}\n"
        f"⭐ {user['rating']} | 🎯 {user['experience']} ив. | 🔥 Страйк: {streak}\n"
        f"⚠️ Поинты: <b>{pts}/3</b> | 🔗 Рефералов: {ref_c}\n"
        f"🔰 {ban_status}\n\n"
        f"📝 <b>Заметки:</b>\n{notes}\n\n"
        f"🆔 <code>{tg_id}</code>"
    )
    await call.message.edit_text(text, parse_mode="HTML",
                                  reply_markup=admin_user_detail_kb(tg_id, user["ban_type"]))


@router.callback_query(F.data == "back_adm_users")
async def back_adm_users(call: CallbackQuery):
    users = get_all_users()
    await call.message.edit_text("👥 <b>Все участники</b>:", parse_mode="HTML",
                                  reply_markup=admin_users_kb(users))


# ─── Удаление участника ──────────────────────────────────────────────────────

@router.callback_query(F.data.regexp(r"^del_user_(\d+)$"))
async def del_user_confirm(call: CallbackQuery):
    tg_id = int(call.data.split("_")[2])
    user  = get_user(tg_id)
    await call.message.edit_text(
        f"🗑 Удалить участника <b>{user['full_name']}</b>?\nВсе его данные будут удалены навсегда.",
        parse_mode="HTML",
        reply_markup=confirm_delete_kb("user", tg_id)
    )


@router.callback_query(F.data.regexp(r"^del_confirm_user_(\d+)$"))
async def del_user_apply(call: CallbackQuery):
    tg_id = int(call.data.split("_")[3])
    delete_user(tg_id)
    await call.message.edit_text("🗑 Участник удалён.")
    await call.answer()


@router.callback_query(F.data.regexp(r"^del_cancel_\w+_\d+$"))
async def del_cancel(call: CallbackQuery):
    await call.message.edit_text("❌ Удаление отменено.")
    await call.answer()


# ─── Поинты ──────────────────────────────────────────────────────────────────

@router.callback_query(F.data.regexp(r"^pts_add_(\d+)$"))
async def pts_add_start(call: CallbackQuery, state: FSMContext):
    tg_id = int(call.data.split("_")[2])
    await state.update_data(pts_tg_id=tg_id, pts_delta=1)
    await state.set_state(PointReasonState.reason)
    await call.message.answer("⚠️ Причина начисления поинта (или «-»):")
    await call.answer()


@router.callback_query(F.data.regexp(r"^pts_remove_(\d+)$"))
async def pts_remove_start(call: CallbackQuery, state: FSMContext):
    tg_id = int(call.data.split("_")[2])
    await state.update_data(pts_tg_id=tg_id, pts_delta=-1)
    await state.set_state(PointReasonState.reason)
    await call.message.answer("✅ Причина снятия поинта (или «-»):")
    await call.answer()


@router.message(PointReasonState.reason)
async def pts_apply(message: Message, state: FSMContext, bot: Bot):
    data   = await state.get_data()
    tg_id  = data["pts_tg_id"]
    delta  = data["pts_delta"]
    reason = "" if message.text.strip()=="-" else message.text.strip()
    await state.clear()
    result = add_points(tg_id, delta, reason)
    user   = get_user(tg_id)
    action = result["action"]
    action_text = {"temp_ban": "\n\n⏳ <b>Автоматически выдан бан на 30 дней!</b>",
                   "full_ban": "\n\n🚫 <b>Выдан постоянный бан!</b>"}.get(action, "")
    await message.answer(
        f"{'⚠️ +1' if delta>0 else '✅ -1'} поинт — <b>{user['full_name']}</b>\n"
        f"Поинтов: <b>{result['points']}/3</b>"
        + (f"\nПричина: {reason}" if reason else "") + action_text,
        parse_mode="HTML", reply_markup=admin_menu_kb()
    )
    try:
        if delta > 0:
            msg = (f"⚠️ Тебе начислен <b>предупредительный поинт</b>.\nПоинтов: <b>{result['points']}/3</b>"
                   + (f"\nПричина: {reason}" if reason else "")
                   + "\n\nПри 3 поинтах — бан на 30 дней.")
        else:
            msg = f"✅ С тебя снят поинт. Поинтов: <b>{result['points']}/3</b>"
        if action == "temp_ban": msg += "\n\n⏳ <b>Временный бан на 30 дней.</b>"
        elif action == "full_ban": msg += "\n\n🚫 <b>Постоянный бан в SOV.</b>"
        await bot.send_message(tg_id, msg, parse_mode="HTML")
    except Exception:
        pass


@router.callback_query(F.data.regexp(r"^pts_history_(\d+)$"))
async def pts_history(call: CallbackQuery):
    tg_id   = int(call.data.split("_")[2])
    user    = get_user(tg_id)
    history = get_point_history(tg_id)
    if not history:
        await call.answer("История пуста.", show_alert=True); return
    lines = []
    for h in history:
        dt   = datetime.fromisoformat(h["given_at"]).strftime("%d.%m %H:%M")
        sign = f"+{h['delta']}" if h["delta"]>0 else str(h["delta"])
        icon = "⚠️" if h["delta"]>0 else "✅"
        lines.append(f"{icon} {sign} — {dt}" + (f" ({h['reason']})" if h["reason"] else ""))
    await call.message.answer(
        f"📋 <b>История: {user['full_name']}</b>\n\n" + "\n".join(lines), parse_mode="HTML"
    )
    await call.answer()


# ─── Баны ────────────────────────────────────────────────────────────────────

@router.callback_query(F.data.regexp(r"^ban_(temp|full)_(\d+)$"))
async def ban_confirm_step(call: CallbackQuery):
    parts    = call.data.split("_")
    ban_type = parts[1]
    tg_id    = int(parts[2])
    user     = get_user(tg_id)
    label    = "временный бан (30д)" if ban_type=="temp" else "постоянный бан"
    await call.message.edit_text(
        f"⚠️ Выдать <b>{label}</b> для <b>{user['full_name']}</b>?",
        parse_mode="HTML", reply_markup=confirm_ban_kb(tg_id, ban_type)
    )


@router.callback_query(F.data.regexp(r"^ban_confirm_(temp|full)_(\d+)$"))
async def ban_apply(call: CallbackQuery, bot: Bot):
    parts    = call.data.split("_")
    ban_type = parts[2]
    tg_id    = int(parts[3])
    user     = get_user(tg_id)
    ban_user(tg_id, ban_type)
    label = "временный бан 30д" if ban_type=="temp" else "постоянный бан"
    await call.message.edit_text(f"✅ <b>{user['full_name']}</b> — {label}.", parse_mode="HTML")
    await call.answer()
    try:
        msg = "⏳ <b>Временный бан на 30 дней в SOV.</b>" if ban_type=="temp" else "🚫 <b>Постоянный бан в SOV.</b>"
        await bot.send_message(tg_id, msg, parse_mode="HTML")
    except Exception:
        pass


@router.callback_query(F.data.regexp(r"^unban_(\d+)$"))
async def unban_apply(call: CallbackQuery, bot: Bot):
    tg_id = int(call.data.split("_")[1])
    user  = get_user(tg_id)
    unban_user(tg_id)
    await call.message.edit_text(f"✅ Бан снят с <b>{user['full_name']}</b>.", parse_mode="HTML")
    await call.answer()
    try:
        await bot.send_message(tg_id, "✅ <b>Твой бан в SOV снят!</b>", parse_mode="HTML")
    except Exception:
        pass


# ─── Заметки ─────────────────────────────────────────────────────────────────

@router.callback_query(F.data.regexp(r"^edit_note_(\d+)$"))
async def edit_note_start(call: CallbackQuery, state: FSMContext):
    tg_id = int(call.data.split("_")[2])
    await state.update_data(target_tg_id=tg_id)
    await state.set_state(NoteState.note)
    await call.message.answer("📝 Новая заметка:")
    await call.answer()


@router.message(NoteState.note)
async def edit_note_save(message: Message, state: FSMContext):
    data = await state.get_data()
    update_user_notes(data["target_tg_id"], message.text.strip())
    await state.clear()
    await message.answer("✅ Заметка сохранена!", reply_markup=admin_menu_kb())


# ─── Оценки ──────────────────────────────────────────────────────────────────

@router.callback_query(F.data.regexp(r"^rate_event_(\d+)$"))
async def rate_event_start(call: CallbackQuery):
    event_id = int(call.data.split("_")[2])
    apps     = get_applications(event_id)
    if not any(a["status"]=="selected" for a in apps):
        await call.answer("Нет выбранных.", show_alert=True); return
    await call.message.edit_text("⭐ Выбери участника:",
                                  reply_markup=rate_select_user_kb(apps, event_id))


@router.callback_query(F.data.regexp(r"^rate_user_(\d+)_(\d+)$"))
async def rate_user_start(call: CallbackQuery, state: FSMContext):
    parts    = call.data.split("_")
    event_id = int(parts[2])
    tg_id    = int(parts[3])
    await state.update_data(rate_event_id=event_id, rate_tg_id=tg_id)
    await state.set_state(RateState.score)
    user = get_user(tg_id)
    await call.message.answer(f"⭐ Оцени <b>{user['full_name']}</b> (1–10):", parse_mode="HTML")
    await call.answer()


@router.message(RateState.score)
async def rate_score(message: Message, state: FSMContext):
    try:
        score = float(message.text.strip().replace(",","."))
        if not 1 <= score <= 10: raise ValueError
    except ValueError:
        await message.answer("⚠️ 1–10"); return
    await state.update_data(score=score)
    await state.set_state(RateState.comment)
    await message.answer("💬 Комментарий (или «-»):")


@router.message(RateState.comment)
async def rate_comment_save(message: Message, state: FSMContext, bot: Bot):
    data       = await state.get_data()
    comment    = "" if message.text.strip()=="-" else message.text.strip()
    old_user   = get_user(data["rate_tg_id"])
    old_rating = old_user["rating"] if old_user else 0

    add_rating(data["rate_event_id"], data["rate_tg_id"], data["score"], comment)
    await state.clear()

    user  = get_user(data["rate_tg_id"])
    event = get_event(data["rate_event_id"])
    new_rating = user["rating"]

    u_admin = get_user(message.from_user.id)
    from utils.audit import log_action
    log_action(message.from_user.id, u_admin["full_name"], "ADD_RATING",
               f"target={data['rate_tg_id']} score={data['score']} event={data['rate_event_id']}")

    await message.answer(
        f"✅ Оценка <b>{data['score']}</b> — {user['full_name']}!\n"
        f"Рейтинг: {old_rating} → <b>{new_rating}</b>",
        parse_mode="HTML", reply_markup=admin_menu_kb()
    )

    # Уведомление участнику с изменением рейтинга
    try:
        rating_change = new_rating - old_rating
        if rating_change > 0:
            change_str = f"📈 +{round(rating_change, 2)}"
        elif rating_change < 0:
            change_str = f"📉 {round(rating_change, 2)}"
        else:
            change_str = "без изменений"

        msg = (f"📊 Оценка за <b>«{event['title']}»</b>: ⭐ {data['score']}/10"
               + (f"\n💬 <i>{comment}</i>" if comment else "")
               + f"\n\n{change_str} Рейтинг: <b>{new_rating}</b>")
        await bot.send_message(data["rate_tg_id"], msg, parse_mode="HTML")
    except Exception:
        pass

    # Проверяем достижения
    try:
        from utils.achievements import check_and_award, get_title, get_desc
        new_achievements = check_and_award(data["rate_tg_id"])
        l = get_user(data["rate_tg_id"]).get("lang","ru")
        for ach in new_achievements:
            title = get_title(ach, l)
            desc  = get_desc(ach, l)
            try:
                await bot.send_message(
                    data["rate_tg_id"],
                    f"🏅 <b>Новое достижение!</b>\n\n{ach.emoji} <b>{title}</b>\n<i>{desc}</i>",
                    parse_mode="HTML"
                )
            except Exception:
                pass
    except Exception:
        pass


# ─── Объявления ──────────────────────────────────────────────────────────────

@router.message(F.text == "📢 Написать объявление")
async def ann_start(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id): return
    await state.set_state(AnnouncementState.text)
    await message.answer("📢 Текст объявления:")


@router.message(AnnouncementState.text)
async def ann_send(message: Message, state: FSMContext, bot: Bot):
    text = message.text.strip()
    await state.clear()
    create_announcement(text)
    users = get_all_users()
    sent  = 0
    for user in users:
        if not user.get("agreed"): continue
        banned, _ = is_banned(user["tg_id"])
        if banned: continue
        try:
            await bot.send_message(user["tg_id"], f"📢 <b>Объявление SOV</b>\n\n{text}", parse_mode="HTML")
            sent += 1
            await asyncio.sleep(0.05)
        except Exception:
            pass
    await message.answer(f"✅ Отправлено {sent} участникам.", reply_markup=admin_menu_kb())


# ─── Топ-3 ───────────────────────────────────────────────────────────────────

@router.message(F.text == "📊 Топ-3 сейчас")
async def top3_now(message: Message):
    if not is_admin(message.from_user.id): return
    top = get_top_users(3)
    if not top:
        await message.answer("Нет данных."); return
    medals = ["🥇","🥈","🥉"]
    lines  = [f"{medals[i]} <b>{u['full_name']}</b> ({u['group_name']})\n    ⭐{u['rating']} | 🎯{u['experience']}ив." for i,u in enumerate(top)]
    await message.answer("🏆 <b>Топ-3</b>\n\n" + "\n\n".join(lines), parse_mode="HTML")


# ─── Статистика ──────────────────────────────────────────────────────────────

@router.message(F.text == "📈 Статистика")
async def show_stats(message: Message):
    if not is_admin(message.from_user.id): return
    from utils.cache import cache, TTL_STATS
    cached = cache.get("org_stats")
    if cached:
        stats = cached
    else:
        from database import get_org_stats
        stats = get_org_stats()
        cache.set("org_stats", stats, TTL_STATS)

    monthly = stats.get("monthly_events", [])
    monthly_lines = ""
    if monthly:
        monthly_lines = "\n\n📅 <b>Ивентов по месяцам:</b>\n"
        for m in reversed(monthly):
            monthly_lines += f"  {m.get('month','?')} — {m.get('cnt',0)} ив.\n"

    text = (
        f"📈 <b>Статистика SOV</b>\n\n"
        f"👥 Участников: <b>{stats['total_users']}</b> "
        f"(🚫 {stats['banned_users']} забанены)\n"
        f"📋 Ивентов всего: <b>{stats['total_events']}</b> "
        f"(🟢 {stats['active_events']} активных)\n"
        f"🎯 Участий: <b>{stats['total_participations']}</b>\n"
        f"⭐ Средний рейтинг: <b>{stats['avg_rating']}</b>\n"
        f"📢 Объявлений: <b>{stats['total_announcements']}</b>"
        + monthly_lines
    )
    await message.answer(text, parse_mode="HTML")
    from utils.audit import log_action
    u = get_user(message.from_user.id)
    log_action(message.from_user.id, u["full_name"], "VIEW_STATS", "")


# ─── Таргетированная рассылка ────────────────────────────────────────────────

class TargetBroadcastState(StatesGroup):
    filter_type = State()
    filter_val  = State()
    text        = State()


@router.message(F.text == "🎯 Таргет рассылка")
async def target_broadcast_start(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id): return
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="♂ Только парни",     callback_data="tgt_gender_М"))
    builder.row(InlineKeyboardButton(text="♀ Только девушки",   callback_data="tgt_gender_Ж"))
    builder.row(InlineKeyboardButton(text="📚 По группе",       callback_data="tgt_group"))
    builder.row(InlineKeyboardButton(text="🌐 По языку",        callback_data="tgt_lang"))
    builder.row(InlineKeyboardButton(text="👥 Всем активным",   callback_data="tgt_all"))
    await message.answer("🎯 <b>Таргетированная рассылка</b>\n\nВыбери фильтр:",
                         parse_mode="HTML", reply_markup=builder.as_markup())


@router.callback_query(F.data.startswith("tgt_"))
async def target_filter_select(call: CallbackQuery, state: FSMContext):
    data = call.data[4:]  # убираем "tgt_"
    if data.startswith("gender_"):
        gender = data.split("_")[1]
        await state.update_data(filter_type="gender", filter_val=gender)
        await state.set_state(TargetBroadcastState.text)
        await call.message.edit_text(
            f"✅ Фильтр: {'Парни ♂' if gender=='М' else 'Девушки ♀'}\n\nВведи текст рассылки:"
        )
    elif data == "group":
        from database import get_all_groups
        groups = get_all_groups()
        builder = InlineKeyboardBuilder()
        for g in groups:
            builder.row(InlineKeyboardButton(text=g, callback_data=f"tgt_grp_{g}"))
        await call.message.edit_text("📚 Выбери группу:", reply_markup=builder.as_markup())
        return
    elif data.startswith("grp_"):
        group = data[4:]
        await state.update_data(filter_type="group", filter_val=group)
        await state.set_state(TargetBroadcastState.text)
        await call.message.edit_text(f"✅ Фильтр: группа {group}\n\nВведи текст рассылки:")
    elif data == "lang":
        builder = InlineKeyboardBuilder()
        builder.row(
            InlineKeyboardButton(text="🇷🇺 RU", callback_data="tgt_lng_ru"),
            InlineKeyboardButton(text="🇺🇿 UZ", callback_data="tgt_lng_uz"),
            InlineKeyboardButton(text="🇬🇧 EN", callback_data="tgt_lng_en"),
        )
        await call.message.edit_text("🌐 Выбери язык:", reply_markup=builder.as_markup())
        return
    elif data.startswith("lng_"):
        lang = data[4:]
        await state.update_data(filter_type="lang", filter_val=lang)
        await state.set_state(TargetBroadcastState.text)
        await call.message.edit_text(f"✅ Фильтр: язык {lang.upper()}\n\nВведи текст рассылки:")
    elif data == "all":
        await state.update_data(filter_type=None, filter_val=None)
        await state.set_state(TargetBroadcastState.text)
        await call.message.edit_text("✅ Рассылка всем активным\n\nВведи текст:")
    await call.answer()


@router.message(TargetBroadcastState.text)
async def target_broadcast_send(message: Message, state: FSMContext, bot: Bot):
    data   = await state.get_data()
    text   = message.text.strip()
    await state.clear()

    from database import get_users_filtered
    ftype = data.get("filter_type")
    fval  = data.get("filter_val")

    if ftype == "gender":
        users = get_users_filtered(gender=fval)
    elif ftype == "group":
        users = get_users_filtered(group=fval)
    elif ftype == "lang":
        users = get_users_filtered(lang=fval)
    else:
        users = get_all_users()

    sent = 0
    for user in users:
        if not user.get("agreed"): continue
        banned, _ = is_banned(user["tg_id"])
        if banned: continue
        try:
            await bot.send_message(user["tg_id"],
                                   f"📢 <b>Сообщение от SOV</b>\n\n{text}",
                                   parse_mode="HTML")
            sent += 1
            await asyncio.sleep(0.04)
        except Exception:
            pass

    filter_label = f"фильтр: {ftype}={fval}" if ftype else "все"
    u = get_user(message.from_user.id)
    from utils.audit import log_action
    log_action(message.from_user.id, u["full_name"], "TARGET_BROADCAST",
               f"sent={sent} {filter_label}")
    await message.answer(f"✅ Отправлено <b>{sent}</b> участникам ({filter_label}).",
                         parse_mode="HTML", reply_markup=admin_menu_kb())


# ─── Шаблоны ивентов ─────────────────────────────────────────────────────────

class SaveTemplateState(StatesGroup):
    name = State()


@router.message(F.text == "📋 Шаблоны ивентов")
async def show_templates(message: Message):
    if not is_admin(message.from_user.id): return
    from database import get_templates
    templates = get_templates()
    builder = InlineKeyboardBuilder()
    for t in templates:
        builder.row(InlineKeyboardButton(
            text=f"📋 {t['name']}",
            callback_data=f"tpl_use_{t['id']}"
        ))
    builder.row(InlineKeyboardButton(text="➕ Сохранить текущий ивент как шаблон",
                                     callback_data="tpl_save_list"))
    builder.row(InlineKeyboardButton(text="❌ Закрыть", callback_data="tpl_close"))
    count = len(templates)
    await message.answer(f"📋 <b>Шаблоны ивентов</b> ({count} шт.):",
                         parse_mode="HTML", reply_markup=builder.as_markup())


@router.callback_query(F.data.regexp(r"^tpl_use_(\d+)$"))
async def tpl_use(call: CallbackQuery, bot: Bot):
    tid = int(call.data.split("_")[2])
    from database import get_template
    tpl = get_template(tid)
    if not tpl: await call.answer("Не найден."); return

    from datetime import date
    today = date.today().strftime("%d.%m.%Y")
    eid = create_event(
        title=tpl["title"], description=tpl["description"],
        event_date=today, event_time="",
        location=tpl["location"], duration=tpl["duration"],
        meeting_point=tpl["meeting_point"],
        total_slots=tpl["total_slots"], male_slots=tpl["male_slots"],
        female_slots=tpl["female_slots"], gender_strict=tpl["gender_strict"]
    )
    u = get_user(call.from_user.id)
    from utils.audit import log_action
    log_action(call.from_user.id, u["full_name"], "CREATE_FROM_TEMPLATE",
               f"tpl={tpl['name']} event_id={eid}")

    await call.message.edit_text(
        f"✅ Ивент создан из шаблона <b>«{tpl['name']}»</b> (ID: {eid})\n\n"
        f"Дата установлена на сегодня. Измени через «📂 Все ивенты».",
        parse_mode="HTML"
    )
    await call.answer()

    # Рассылка
    slots_info = f"{tpl['total_slots']} чел."
    await _broadcast_new_event(bot, tpl["title"], today, "", tpl["location"], slots_info)


@router.callback_query(F.data == "tpl_save_list")
async def tpl_save_list(call: CallbackQuery):
    events = get_all_events()
    builder = InlineKeyboardBuilder()
    for ev in events[:10]:
        builder.row(InlineKeyboardButton(
            text=f"📌 {ev['title']}", callback_data=f"tpl_save_ev_{ev['id']}"
        ))
    builder.row(InlineKeyboardButton(text="◀️ Назад", callback_data="tpl_close"))
    await call.message.edit_text("Выбери ивент для сохранения как шаблон:",
                                  reply_markup=builder.as_markup())


@router.callback_query(F.data.regexp(r"^tpl_save_ev_(\d+)$"))
async def tpl_save_ev(call: CallbackQuery, state: FSMContext):
    event_id = int(call.data.split("_")[3])
    await state.update_data(tpl_event_id=event_id)
    await state.set_state(SaveTemplateState.name)
    await call.message.edit_text("📋 Введи название для шаблона:")


@router.message(SaveTemplateState.name)
async def tpl_save_name(message: Message, state: FSMContext):
    data     = await state.get_data()
    event_id = data["tpl_event_id"]
    name     = message.text.strip()
    await state.clear()

    event = get_event(event_id)
    if not event:
        await message.answer("Ивент не найден."); return

    from database import save_template
    tid = save_template(name, event, message.from_user.id)
    u = get_user(message.from_user.id)
    from utils.audit import log_action
    log_action(message.from_user.id, u["full_name"], "SAVE_TEMPLATE", f"name={name} id={tid}")
    await message.answer(f"✅ Шаблон <b>«{name}»</b> сохранён!", parse_mode="HTML",
                         reply_markup=admin_menu_kb())


@router.callback_query(F.data == "tpl_close")
async def tpl_close(call: CallbackQuery):
    await call.message.delete()
    await call.answer()


# ─── Дедлайн (из админки) ────────────────────────────────────────────────────

class AdminDeadlineState(StatesGroup):
    deadline = State()


@router.callback_query(F.data.regexp(r"^set_deadline_(\d+)$"))
async def set_deadline_start(call: CallbackQuery, state: FSMContext):
    event_id = int(call.data.split("_")[2])
    await state.update_data(dl_event_id=event_id)
    await state.set_state(AdminDeadlineState.deadline)
    await call.message.answer(
        "⏰ Введи дедлайн в формате:\n<code>25.05.2025 18:00</code>",
        parse_mode="HTML"
    )
    await call.answer()


@router.message(AdminDeadlineState.deadline)
async def set_deadline_save(message: Message, state: FSMContext):
    data = await state.get_data()
    text = message.text.strip()
    try:
        from datetime import datetime as dt
        deadline_dt = dt.strptime(text, "%d.%m.%Y %H:%M")
        from database import set_registration_deadline
        set_registration_deadline(data["dl_event_id"], deadline_dt.isoformat())
        await state.clear()
        await message.answer(
            f"✅ Дедлайн установлен: <b>{deadline_dt.strftime('%d.%m.%Y %H:%M')}</b>",
            parse_mode="HTML", reply_markup=admin_menu_kb()
        )
    except ValueError:
        await message.answer("⚠️ Формат: 25.05.2025 18:00")


# ─── Управление ролями ────────────────────────────────────────────────────────

@router.message(F.text == "🎭 Роли")
async def manage_roles(message: Message):
    if not is_admin(message.from_user.id): return
    from database import get_users_by_role, get_role
    organizers = get_users_by_role("organizer")
    lines = [f"🗂 {u['full_name']} ({u['group_name']}) — <code>{u['tg_id']}</code>"
             for u in organizers] or ["<i>Организаторов нет</i>"]
    await message.answer(
        "🎭 <b>Управление ролями</b>\n\n"
        "<b>Организаторы:</b>\n" + "\n".join(lines) + "\n\n"
        "<b>Команды:</b>\n"
        "<code>/setrole ID organizer</code>\n"
        "<code>/setrole ID user</code>",
        parse_mode="HTML"
    )


@router.message(Command("setrole"))
async def cmd_setrole(message: Message):
    if not is_admin(message.from_user.id): return
    parts = message.text.split()
    if len(parts) != 3:
        await message.answer("Использование: /setrole <tg_id> <role>\nРоли: user, organizer"); return
    try:
        target_id = int(parts[1])
        role      = parts[2].lower()
    except ValueError:
        await message.answer("⚠️ Неверный tg_id."); return
    if role not in ("user", "organizer"):
        await message.answer("⚠️ Роли: user, organizer"); return

    target_user = get_user(target_id)
    if not target_user:
        await message.answer("❌ Участник не найден."); return

    from database import set_role
    set_role(target_id, role)

    u = get_user(message.from_user.id)
    from utils.audit import log_action
    log_action(message.from_user.id, u["full_name"], "SET_ROLE",
               f"target={target_id} role={role}")

    role_label = {"user": "👤 Обычный участник", "organizer": "🗂 Организатор"}[role]
    await message.answer(
        f"✅ Роль <b>{target_user['full_name']}</b> изменена на <b>{role_label}</b>.",
        parse_mode="HTML"
    )
    try:
        role_msg = {
            "organizer": "🗂 Тебе выдана роль <b>Организатора SOV</b>!\n\nИспользуй команду /organizer для входа в меню организатора.",
            "user":      "ℹ️ Твоя роль изменена на обычного участника."
        }[role]
        await message.bot.send_message(target_id, role_msg, parse_mode="HTML")
    except Exception:
        pass


# ─── Экспорт Excel ───────────────────────────────────────────────────────────

@router.message(F.text == "📊 Экспорт Excel")
async def export_excel(message: Message):
    if not is_admin(message.from_user.id): return
    await message.answer("⏳ Формирую Excel файл...")

    from utils.excel_export import export_users_xlsx, export_events_xlsx
    from aiogram.types import BufferedInputFile

    try:
        users  = get_all_users()
        events = get_all_events()

        # Собираем заявки для всех ивентов
        apps_map = {ev["id"]: get_applications(ev["id"]) for ev in events}

        users_bytes  = export_users_xlsx(users)
        events_bytes = export_events_xlsx(events, apps_map)

        from datetime import datetime
        ts = datetime.now().strftime("%d%m%Y_%H%M")

        await message.answer_document(
            BufferedInputFile(users_bytes, filename=f"sov_users_{ts}.xlsx"),
            caption="👥 Список участников SOV"
        )
        await message.answer_document(
            BufferedInputFile(events_bytes, filename=f"sov_events_{ts}.xlsx"),
            caption="📋 Ивенты и заявки SOV"
        )

        u = get_user(message.from_user.id)
        from utils.audit import log_action
        log_action(message.from_user.id, u["full_name"], "EXPORT_EXCEL",
                   f"users={len(users)} events={len(events)}")

    except Exception as e:
        await message.answer(f"❌ Ошибка экспорта: {e}")


# ─── Предложения ─────────────────────────────────────────────────────────────

@router.message(F.text == "📬 Предложения ивентов")
async def show_proposals(message: Message):
    if not is_admin(message.from_user.id): return
    props = get_proposals("pending")
    if not props:
        await message.answer("📬 Нет новых предложений."); return
    await message.answer(f"📬 <b>Предложения ({len(props)})</b>:", parse_mode="HTML",
                         reply_markup=proposals_kb(props))


@router.callback_query(F.data.regexp(r"^proposal_(\d+)$"))
async def proposal_detail(call: CallbackQuery):
    pid   = int(call.data.split("_")[1])
    all_p = get_proposals("pending") + get_proposals("approved") + get_proposals("rejected")
    p     = next((x for x in all_p if x["id"]==pid), None)
    if not p:
        await call.answer("Не найдено."); return
    text = (
        f"📋 <b>Предложение #{p['id']}</b> от {p['full_name']}\n\n"
        f"👥 {p['vol_count']} | 📍 {p['location']}\n📅 {p['event_date']} | ⏱ {p['duration']}\n"
        f"📋 {p['tasks']}\n🚻 {p['gender_need']}\n👤 {p['organizer']}\n"
        f"🏫 {p['admin_approved']}\n💬 {p['comment'] or '—'}"
    )
    await call.message.edit_text(text, parse_mode="HTML", reply_markup=proposal_action_kb(pid))


@router.callback_query(F.data.regexp(r"^prop_(approve|reject)_(\d+)$"))
async def proposal_action(call: CallbackQuery, bot: Bot):
    parts  = call.data.split("_")
    action = parts[1]
    pid    = int(parts[2])
    status = "approved" if action == "approve" else "rejected"
    update_proposal_status(pid, status)

    from database import get_proposal
    p = get_proposal(pid)

    label = "✅ Одобрено" if action == "approve" else "❌ Отклонено"

    if action == "approve" and p:
        # ── Авто-создание ивента из предложения ──────────────────────────────
        try:
            vol_count = int(p["vol_count"])
        except Exception:
            vol_count = 10

        # Определяем квоты пола из поля gender_need
        male_slots, female_slots = 0, 0
        gn = p.get("gender_need","").lower()
        if "парн" in gn or "erkak" in gn or "male" in gn or "boy" in gn:
            male_slots = vol_count
        elif "девуш" in gn or "ayol" in gn or "female" in gn or "girl" in gn:
            female_slots = vol_count

        eid = create_event(
            title=f"{p['organizer']}: {p['event_date']}",
            description=(
                f"📋 Задачи: {p['tasks']}\n"
                f"👤 Организатор: {p['organizer']}\n"
                f"🏫 Одобрено лицеем: {p['admin_approved']}"
                + (f"\n💬 {p['comment']}" if p.get("comment") else "")
            ),
            event_date=p["event_date"],
            event_time="",
            location=p["location"],
            duration=p["duration"],
            meeting_point="",
            total_slots=vol_count,
            male_slots=male_slots,
            female_slots=female_slots,
            gender_strict=0
        )

        slots_info = f"{vol_count} чел."
        await call.message.edit_text(
            f"✅ <b>Предложение #{pid} одобрено!</b>\n\n"
            f"📌 Ивент автоматически создан (ID: {eid})\n"
            f"📍 {p['location']} | 📅 {p['event_date']}\n"
            f"👥 {slots_info}\n\n"
            f"Ивент уже виден участникам в разделе «📋 Активные ивенты».\n"
            f"Уточни детали через <b>📂 Все ивенты</b>.",
            parse_mode="HTML"
        )
        await call.answer("✅ Одобрено, ивент создан!")

        # Рассылка о новом ивенте
        await _broadcast_new_event(
            bot,
            title=f"{p['organizer']}: {p['event_date']}",
            date=p["event_date"],
            time="",
            location=p["location"],
            slots=slots_info
        )

        # Уведомление автору предложения
        try:
            await bot.send_message(
                p["tg_id"],
                f"🎉 <b>Твоё предложение ивента одобрено!</b>\n\n"
                f"📌 Ивент создан и открыт для записи.\n"
                f"📅 {p['event_date']} | 📍 {p['location']}\n\n"
                f"Следи за обновлениями в боте SOV!",
                parse_mode="HTML"
            )
        except Exception:
            pass

    else:
        await call.message.edit_text(f"❌ Предложение #{pid} отклонено.")
        await call.answer("❌ Отклонено")
        if p:
            try:
                await bot.send_message(
                    p["tg_id"],
                    f"❌ Твоё предложение ивента было отклонено.\n\n"
                    f"Ивент: {p['event_date']}, {p['location']}\n\n"
                    f"Обратись к администратору SOV за подробностями.",
                    parse_mode="HTML"
                )
            except Exception:
                pass



@router.callback_query(F.data == "back_proposals")
async def back_proposals(call: CallbackQuery):
    props = get_proposals("pending")
    await call.message.edit_text("📬 <b>Предложения</b>:", parse_mode="HTML", reply_markup=proposals_kb(props))


@router.callback_query(F.data == "close_proposals")
async def close_proposals(call: CallbackQuery):
    await call.message.delete()
    await call.answer()


# ══════════════════════════════════════════════════════════════════════════════
# НОВЫЕ ХЕНДЛЕРЫ v5.0
# ══════════════════════════════════════════════════════════════════════════════

# ─── FSM ─────────────────────────────────────────────────────────────────────

class CardPhotoState(StatesGroup):
    photo = State()

class RatingAdjustState(StatesGroup):
    delta  = State()
    reason = State()

class MultiRateState(StatesGroup):
    event_id = State()
    score    = State()
    comment  = State()

# ─── Пагинация участников ─────────────────────────────────────────────────────

@router.callback_query(F.data.regexp(r"^users_page_(\d+)$"))
async def users_page_handler(call: CallbackQuery):
    if not is_admin(call.from_user.id): return
    page = int(call.data.split("_")[2])
    users, total = get_users_page(page=page, per_page=30)
    if not users:
        await call.answer("Нет участников.", show_alert=True); return
    await safe_edit_text(
        call.message, "👥 <b>Все участники</b>:", parse_mode="HTML",
        reply_markup=admin_users_kb(users, page=page, total=total)
    )
    await call.answer()


@router.callback_query(F.data == "noop")
async def noop_cb(call: CallbackQuery):
    await call.answer()


# ─── Удаление объявлений ──────────────────────────────────────────────────────

@router.callback_query(F.data.regexp(r"^ann_delete_offset_(\d+)$"))
async def ann_delete_by_offset(call: CallbackQuery):
    if not is_admin(call.from_user.id): return
    offset = int(call.data.split("_")[3])
    anns   = get_announcements(limit=1, offset=offset)
    if not anns:
        await call.answer("Не найдено.", show_alert=True); return
    ann_id = anns[0]["id"]
    delete_announcement(ann_id)
    await call.message.delete()
    await call.answer("🗑 Объявление удалено.", show_alert=True)


# ─── Фото карточки (отдельно) ─────────────────────────────────────────────────

@router.callback_query(F.data.regexp(r"^upload_card_(\d+)$"))
async def upload_card_photo_start(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id): return
    event_id = int(call.data.split("_")[2])
    await state.update_data(card_event_id=event_id)
    await state.set_state(CardPhotoState.photo)
    await call.message.answer(
        "🎴 Отправь фото которое будет на <b>карточке участника</b>:\n"
        "<i>Это отдельное фото — не фото самого ивента.</i>",
        parse_mode="HTML"
    )
    await call.answer()


@router.message(CardPhotoState.photo, F.photo)
async def upload_card_photo_save(message: Message, state: FSMContext):
    data = await state.get_data()
    set_event_card_photo(data["card_event_id"], message.photo[-1].file_id)
    await state.clear()
    await message.answer("✅ Фото карточки сохранено!", reply_markup=admin_menu_kb())


# ─── Редактирование списка после автоподбора ──────────────────────────────────

@router.callback_query(F.data.regexp(r"^edit_selected_(\d+)$"))
async def edit_selected_start(call: CallbackQuery):
    if not is_admin(call.from_user.id): return
    event_id = int(call.data.split("_")[2])
    selected = get_selected_users_detail(event_id)
    if not selected:
        await call.answer(
            "Нет выбранных. Сначала запусти 🤖 Автоподбор.", show_alert=True
        ); return
    await safe_edit_text(
        call.message,
        f"✏️ <b>Редактирование списка</b> ({len(selected)} чел.)\n\n"
        f"Нажми ❌ напротив участника чтобы убрать.\n"
        f"Когда закончишь — нажми ✅ Подтвердить список.",
        parse_mode="HTML",
        reply_markup=edit_selected_kb(event_id, selected)
    )


@router.callback_query(F.data.regexp(r"^remove_selected_(\d+)_(\d+)$"))
async def remove_from_selected(call: CallbackQuery, bot: Bot):
    parts    = call.data.split("_")
    event_id = int(parts[2])
    tg_id    = int(parts[3])
    manually_remove_from_event(event_id, tg_id)
    user  = get_user(tg_id)
    event = get_event(event_id)
    await call.answer(f"❌ {user['full_name']} убран.", show_alert=True)
    selected = get_selected_users_detail(event_id)
    if selected:
        await safe_edit_text(
            call.message,
            f"✏️ <b>Редактирование списка</b> ({len(selected)} чел.)",
            parse_mode="HTML",
            reply_markup=edit_selected_kb(event_id, selected)
        )
    else:
        await safe_edit_text(call.message, "Список пуст. Запусти автоподбор заново.")
    try:
        await bot.send_message(
            tg_id,
            f"ℹ️ Тебя убрали из списка ивента «{event['title']}»."
        )
    except Exception:
        pass


@router.callback_query(F.data.regexp(r"^confirm_selected_(\d+)$"))
async def confirm_selected(call: CallbackQuery, bot: Bot):
    event_id = int(call.data.split("_")[2])
    event    = get_event(event_id)
    selected = get_selected_users_detail(event_id)
    if not selected:
        await call.answer("Список пуст.", show_alert=True); return

    pair_str = get_pair_info(event.get("event_time", ""))
    lines    = [f"{i}. {s['full_name']} {s['group_name']}" for i, s in enumerate(selected, 1)]
    report   = (
        f"📋 <b>Просьба отпросить волонтёров</b>\n"
        f"«<b>{event['title']}</b>»\n"
        f"📅 {event['event_date']} {event.get('event_time','')} {pair_str}\n\n"
        + "\n".join(lines)
    )
    await call.message.answer(report, parse_mode="HTML")
    await call.answer("✅ Список подтверждён!")

    # Пост в канал
    channel_id = get_channel_id()
    if channel_id:
        try:
            await bot.send_message(
                channel_id,
                f"✅ <b>Набор завершён: «{event['title']}»</b>\n"
                f"Выбрано {len(selected)} из {event['total_slots']} волонтёров.",
                parse_mode="HTML"
            )
        except Exception:
            pass

    # Уведомляем выбранных
    for s in selected:
        try:
            msg = (
                f"🎉 Ты подтверждён волонтёром на <b>«{event['title']}»</b>!\n"
                f"📅 {event['event_date']}"
                + (f" в {event['event_time']}" if event.get("event_time") else "")
                + (f"\n📍 {event['location']}" if event.get("location") else "")
            )
            await bot.send_message(s["tg_id"], msg, parse_mode="HTML")
        except Exception:
            pass


# ─── QR двух типов (старт/финиш) ─────────────────────────────────────────────

@router.callback_query(F.data.regexp(r"^gen_qr_(start|end)_(\d+)$"))
async def gen_qr_typed(call: CallbackQuery, bot: Bot):
    parts    = call.data.split("_")
    qr_type  = parts[2]
    event_id = int(parts[3])
    event    = get_event(event_id)
    token    = generate_qr_token(event_id, qr_type)
    bot_info = await bot.get_me()
    qr_url   = f"https://t.me/{bot_info.username}?start=qr_{qr_type}_{token}"

    img = qrcode.make(qr_url)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)

    label = "📍 ПРИХОД НА ИВЕНТ" if qr_type == "start" else "🏁 КОНЕЦ РАБОТЫ"
    desc  = "Волонтёры сканируют при приходе → статус: Работаю" if qr_type == "start" \
        else "Волонтёры сканируют по окончании → статус: Завершил"

    await call.message.answer_photo(
        BufferedInputFile(buf.getvalue(), filename="qr.png"),
        caption=(
            f"🔲 <b>QR [{label}]</b>\n"
            f"Ивент: «{event['title']}»\n\n"
            f"{desc}\n\n"
            f"<code>{qr_url}</code>"
        ),
        parse_mode="HTML"
    )
    await call.answer()


# ─── Закрытие работы / завершение ивента ─────────────────────────────────────

@router.callback_query(F.data.regexp(r"^close_work_(\d+)$"))
async def close_work_handler(call: CallbackQuery, bot: Bot):
    if not is_admin(call.from_user.id): return
    event_id  = int(call.data.split("_")[2])
    event     = get_event(event_id)
    violators = close_event_work(event_id)

    text = f"🏁 <b>Работа закрыта: «{event['title']}»</b>\n\n"
    if violators:
        text += f"⚠️ Автоматический поинт ({len(violators)} чел.):\n"
        for v in violators:
            text += f"  • {v['full_name']}\n"
            try:
                await bot.send_message(
                    v["tg_id"],
                    f"⚠️ Ты не завершил работу на ивенте «{event['title']}» — "
                    f"начислен поинт нарушения."
                )
            except Exception:
                pass
    else:
        text += "✅ Все завершили работу."

    text += "\n\nТеперь выдай QR финиша или нажми ✅ Завершить ивент."
    await call.message.answer(text, parse_mode="HTML")
    await call.answer("🏁 Работа закрыта!", show_alert=True)


@router.callback_query(F.data.regexp(r"^finish_event_(\d+)$"))
async def finish_event_handler(call: CallbackQuery):
    if not is_admin(call.from_user.id): return
    event_id = int(call.data.split("_")[2])
    event    = get_event(event_id)
    complete_event(event_id)
    status   = get_event_work_status(event_id)
    lines    = "\n".join(f"  {k}: {v}" for k, v in status.items())
    await call.message.answer(
        f"✅ <b>Ивент «{event['title']}» полностью завершён!</b>\n\n"
        f"Статусы участников:\n{lines}\n\n"
        f"Теперь выдавай карточки и оценки через 📂 Все ивенты.",
        parse_mode="HTML"
    )
    await call.answer("✅ Ивент завершён!")


# ─── Уведомление в канал при создании ивента ─────────────────────────────────

async def post_event_to_channel(bot: Bot, event: dict):
    channel_id = get_channel_id()
    if not channel_id:
        return
    male_str   = f"{event['male_slots']} парней"   if event.get("male_slots")   else ""
    female_str = f"{event['female_slots']} девушек" if event.get("female_slots") else ""
    gender_str = ", ".join(filter(None, [male_str, female_str])) or "без ограничений"
    text = (
        f"📌 <b>Новый ивент SOV!</b>\n\n"
        f"<b>{event['title']}</b>\n\n"
        f"👥 Нужно: <b>{event['total_slots']}</b> чел.\n"
        f"🚻 {gender_str}\n"
    )
    if event.get("event_date"): text += f"📅 {event['event_date']}\n"
    if event.get("event_time"): text += f"🕐 {event['event_time']}\n"
    if event.get("location"):   text += f"📍 {event['location']}\n"
    if event.get("duration"):   text += f"⏱ {event['duration']}\n"
    if event.get("description"):text += f"\n{event['description']}\n"
    bot_info = await bot.get_me()
    text += f"\n✋ Записаться → @{bot_info.username}"
    try:
        if event.get("photo_file_id"):
            await bot.send_photo(channel_id, event["photo_file_id"], caption=text, parse_mode="HTML")
        else:
            await bot.send_message(channel_id, text, parse_mode="HTML")
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"Channel post failed: {e}")


async def notify_slots_update(bot: Bot, event_id: int):
    """Уведомляет в канал когда осталась половина мест."""
    channel_id = get_channel_id()
    if not channel_id: return
    event = get_event(event_id)
    if not event: return
    apps   = get_applications(event_id)
    count  = len([a for a in apps if a["status"] in ("pending", "selected")])
    total  = event["total_slots"]
    half   = total // 2
    free   = total - count
    if free == half:
        try:
            await bot.send_message(
                channel_id,
                f"⚡ <b>«{event['title']}»</b> — осталось <b>{free}</b> из {total} мест!",
                parse_mode="HTML"
            )
        except Exception:
            pass
    elif free == 0:
        try:
            await bot.send_message(
                channel_id,
                f"🔒 <b>«{event['title']}»</b> — все места заняты! Регистрация закрыта.",
                parse_mode="HTML"
            )
        except Exception:
            pass


# ─── Ручная корректировка рейтинга ───────────────────────────────────────────

@router.callback_query(F.data.regexp(r"^rating_(add|sub)_(\d+)$"))
async def rating_adjust_start(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id): return
    parts  = call.data.split("_")
    action = parts[1]
    tg_id  = int(parts[2])
    await state.update_data(rating_tg_id=tg_id, rating_action=action)
    await state.set_state(RatingAdjustState.delta)
    user = get_user(tg_id)
    sign = "прибавить" if action == "add" else "убрать"
    await call.message.answer(
        f"⭐ Сколько баллов {sign} у <b>{user['full_name']}</b>?\n"
        f"Текущий рейтинг: <b>{user['rating']}</b>\n"
        f"Введи число (например: 0.5 или 1):",
        parse_mode="HTML"
    )
    await call.answer()


@router.message(RatingAdjustState.delta)
async def rating_adjust_delta(message: Message, state: FSMContext):
    try:
        delta = float(message.text.strip().replace(",", "."))
        if delta <= 0 or delta > 10: raise ValueError
    except ValueError:
        await message.answer("⚠️ Введи положительное число до 10."); return
    await state.update_data(rating_delta=delta)
    await state.set_state(RatingAdjustState.reason)
    await message.answer("💬 Причина (или «-»):")


@router.message(RatingAdjustState.reason)
async def rating_adjust_apply(message: Message, state: FSMContext, bot: Bot):
    data   = await state.get_data()
    tg_id  = data["rating_tg_id"]
    delta  = data["rating_delta"]
    action = data["rating_action"]
    reason = "" if message.text.strip() == "-" else message.text.strip()
    await state.clear()

    actual = delta if action == "add" else -delta
    adjust_rating(tg_id, actual, reason)
    user = get_user(tg_id)
    sign = f"+{delta}" if action == "add" else f"-{delta}"

    await message.answer(
        f"✅ Рейтинг <b>{user['full_name']}</b>: {sign} → <b>{user['rating']}</b>",
        parse_mode="HTML", reply_markup=admin_menu_kb()
    )
    try:
        icon = "📈" if action == "add" else "📉"
        await bot.send_message(
            tg_id,
            f"{icon} Твой рейтинг изменён: {sign}\n"
            f"Текущий рейтинг: <b>{user['rating']}</b>"
            + (f"\nПричина: {reason}" if reason else ""),
            parse_mode="HTML"
        )
    except Exception:
        pass


# ─── Выдать карточку конкретному участнику ────────────────────────────────────

@router.callback_query(F.data.regexp(r"^give_card_(\d+)$"))
async def give_card_to_user(call: CallbackQuery):
    if not is_admin(call.from_user.id): return
    tg_id  = int(call.data.split("_")[2])
    events = get_all_events()[:15]
    if not events:
        await call.answer("Нет ивентов.", show_alert=True); return
    await call.message.answer(
        "🎴 Выбери ивент для выдачи карточки:",
        reply_markup=give_card_events_kb(events, tg_id)
    )
    await call.answer()


@router.callback_query(F.data.regexp(r"^give_card_ev_(\d+)_(\d+)$"))
async def give_card_ev_apply(call: CallbackQuery, bot: Bot):
    parts    = call.data.split("_")
    tg_id    = int(parts[3])
    event_id = int(parts[4])
    ok       = issue_card(tg_id, event_id)
    event    = get_event(event_id)
    user     = get_user(tg_id)
    if ok:
        await call.message.edit_text(
            f"✅ Карточка выдана <b>{user['full_name']}</b> — «{event['title']}»",
            parse_mode="HTML"
        )
        try:
            # Берём фото карточки если есть
            card_photo = event.get("card_photo_file_id") or event.get("photo_file_id")
            caption = (
                f"🎴 <b>Тебе выдана карточка участника!</b>\n\n"
                f"Ивент: «{event['title']}» ({event['event_date']})\n"
                f"Смотри в «🎴 Мои карточки»."
            )
            if card_photo:
                await bot.send_photo(tg_id, card_photo, caption=caption, parse_mode="HTML")
            else:
                await bot.send_message(tg_id, caption, parse_mode="HTML")
        except Exception:
            pass
    else:
        await call.answer("Карточка уже выдана.", show_alert=True)


# ─── Мульти-выбор участников ──────────────────────────────────────────────────

_multi_state: dict = {}


@router.callback_query(F.data == "multi_select_users")
async def multi_select_start(call: CallbackQuery):
    if not is_admin(call.from_user.id): return
    b = InlineKeyboardBuilder()
    actions = [
        ("⏳ Бан 30д",       "ban_temp"),
        ("🚫 Фулл бан",      "ban_full"),
        ("✅ Разбанить",      "unban"),
        ("⚠️ +1 поинт",      "pts_add"),
        ("✅ -1 поинт",      "pts_sub"),
        ("🎴 Выдать карточки","cards"),
        ("⭐ Одна оценка",   "rate"),
    ]
    for label, cb in actions:
        b.row(InlineKeyboardButton(text=label, callback_data=f"ms_action_{cb}"))
    b.row(InlineKeyboardButton(text="❌ Отмена", callback_data="ms_cancel"))
    await call.message.answer("☑️ Что сделать с несколькими участниками?",
                               reply_markup=b.as_markup())
    await call.answer()


@router.callback_query(F.data.regexp(r"^ms_action_(\w+)$"))
async def ms_action_select(call: CallbackQuery):
    action = call.data[10:]  # убираем "ms_action_"
    tg_id  = call.from_user.id
    users, total = get_users_page(page=0, per_page=30)
    _multi_state[tg_id] = {"action": action, "selected": set(), "page": 0, "total": total}
    await call.message.edit_text(
        f"☑️ Выбери участников (нажимай чтобы отмечать):\n"
        f"Страница 1 / {max(1,(total+29)//30)}",
        reply_markup=multi_select_users_kb(users, set(), action)
    )
    await call.answer()


@router.callback_query(F.data.regexp(r"^ms_toggle_(\w+)_(\d+)$"))
async def ms_toggle(call: CallbackQuery):
    parts    = call.data.split("_")
    action   = parts[2]
    user_id  = int(parts[3])
    admin_id = call.from_user.id
    st       = _multi_state.setdefault(admin_id, {"action": action, "selected": set(), "page": 0})
    if user_id in st["selected"]:
        st["selected"].discard(user_id)
    else:
        st["selected"].add(user_id)
    users, total = get_users_page(page=st.get("page", 0), per_page=30)
    try:
        await call.message.edit_reply_markup(
            reply_markup=multi_select_users_kb(users, st["selected"], action)
        )
    except Exception:
        pass
    await call.answer(f"{'✅' if user_id in st['selected'] else '❌'} {len(st['selected'])} выбрано")


@router.callback_query(F.data.regexp(r"^ms_apply_(\w+)$"))
async def ms_apply(call: CallbackQuery, bot: Bot, state: FSMContext):
    action   = call.data[9:]   # убираем "ms_apply_"
    admin_id = call.from_user.id
    ms       = _multi_state.pop(admin_id, {})
    ids      = list(ms.get("selected", set()))
    if not ids:
        await call.answer("Никого не выбрано.", show_alert=True); return

    users_info = [u for u in [get_user(i) for i in ids] if u]
    names      = ", ".join(u["full_name"] for u in users_info[:5])
    if len(users_info) > 5:
        names += f" и ещё {len(users_info)-5}"

    if action == "ban_temp":
        bulk_ban(ids, "temp")
        await call.message.edit_text(f"⏳ Бан 30д — {len(ids)} чел.: {names}")
        for uid in ids:
            try: await bot.send_message(uid, "⏳ Тебе выдан временный бан на 30 дней в SOV.")
            except Exception: pass

    elif action == "ban_full":
        bulk_ban(ids, "full")
        await call.message.edit_text(f"🚫 Фулл бан — {len(ids)} чел.: {names}")
        for uid in ids:
            try: await bot.send_message(uid, "🚫 Тебе выдан постоянный бан в SOV.")
            except Exception: pass

    elif action == "unban":
        bulk_unban(ids)
        await call.message.edit_text(f"✅ Разбанены — {len(ids)} чел.: {names}")
        for uid in ids:
            try: await bot.send_message(uid, "✅ Твой бан снят. Добро пожаловать обратно!")
            except Exception: pass

    elif action == "pts_add":
        bulk_add_points(ids, 1, "Массовое начисление")
        await call.message.edit_text(f"⚠️ +1 поинт — {len(ids)} чел.: {names}")

    elif action == "pts_sub":
        bulk_add_points(ids, -1, "Массовое снятие")
        await call.message.edit_text(f"✅ -1 поинт — {len(ids)} чел.: {names}")

    elif action == "cards":
        events = get_all_events()[:10]
        b = InlineKeyboardBuilder()
        ids_str = "_".join(str(i) for i in ids)
        for ev in events:
            b.row(InlineKeyboardButton(
                text=f"📌 {ev['title']}",
                callback_data=f"ms_cards_ev_{ev['id']}_{ids_str}"[:64]
            ))
        b.row(InlineKeyboardButton(text="❌ Отмена", callback_data="ms_cancel"))
        await call.message.edit_text(
            "Выбери ивент для выдачи карточек:",
            reply_markup=b.as_markup()
        )
        await call.answer(); return

    elif action == "rate":
        await state.update_data(ms_rate_ids=ids)
        await state.set_state(MultiRateState.score)
        await call.message.edit_text(
            f"⭐ Введи оценку (1-10) для {len(ids)} участников:"
        )
        await call.answer(); return

    await call.answer("✅ Готово!", show_alert=True)


@router.callback_query(F.data.regexp(r"^ms_cards_ev_(\d+)_(.+)$"))
async def ms_cards_ev(call: CallbackQuery, bot: Bot):
    parts    = call.data.split("_")
    event_id = int(parts[3])
    raw_ids  = parts[4] if len(parts) > 4 else ""
    ids      = [int(x) for x in raw_ids.split("_") if x.isdigit()]
    count    = issue_cards_bulk(ids, event_id)
    event    = get_event(event_id)
    card_photo = event.get("card_photo_file_id") or event.get("photo_file_id")
    await call.message.edit_text(
        f"🎴 Карточки выданы <b>{count}</b> участникам — «{event['title']}»",
        parse_mode="HTML"
    )
    for uid in ids:
        try:
            caption = (
                f"🎴 Тебе выдана карточка участника!\n"
                f"Ивент: «{event['title']}» ({event['event_date']})\n"
                f"Смотри в «🎴 Мои карточки»."
            )
            if card_photo:
                await bot.send_photo(uid, card_photo, caption=caption, parse_mode="HTML")
            else:
                await bot.send_message(uid, caption, parse_mode="HTML")
        except Exception:
            pass
    await call.answer()


@router.callback_query(F.data == "ms_cancel")
async def ms_cancel(call: CallbackQuery):
    _multi_state.pop(call.from_user.id, None)
    await call.message.delete()
    await call.answer("Отменено.")


# ─── Мульти-оценка ────────────────────────────────────────────────────────────

_rate_multi_sel: dict = {}


@router.callback_query(F.data.regexp(r"^rate_multi_(\d+)$"))
async def rate_multi_start(call: CallbackQuery):
    if not is_admin(call.from_user.id): return
    event_id = int(call.data.split("_")[2])
    apps     = get_applications(event_id)
    _rate_multi_sel[call.from_user.id] = set()
    await safe_edit_text(
        call.message,
        "☑️ Выбери участников для оценки:",
        reply_markup=rate_multi_kb(event_id, apps, set())
    )
    await call.answer()


@router.callback_query(F.data.regexp(r"^rate_multi_toggle_(\d+)_(\d+)$"))
async def rate_multi_toggle(call: CallbackQuery):
    parts    = call.data.split("_")
    event_id = int(parts[3])
    tg_id    = int(parts[4])
    sel      = _rate_multi_sel.setdefault(call.from_user.id, set())
    if tg_id in sel: sel.discard(tg_id)
    else:            sel.add(tg_id)
    apps = get_applications(event_id)
    try:
        await call.message.edit_reply_markup(
            reply_markup=rate_multi_kb(event_id, apps, sel)
        )
    except Exception:
        pass
    await call.answer(f"{len(sel)} выбрано")


@router.callback_query(F.data.regexp(r"^rate_multi_apply_(\d+)$"))
async def rate_multi_apply(call: CallbackQuery, state: FSMContext):
    event_id = int(call.data.split("_")[3])
    ids      = list(_rate_multi_sel.pop(call.from_user.id, set()))
    if not ids:
        await call.answer("Никого не выбрано.", show_alert=True); return
    await state.update_data(ms_rate_ids=ids, ms_rate_event_id=event_id)
    await state.set_state(MultiRateState.score)
    await call.message.edit_text(f"⭐ Введи оценку (1-10) для {len(ids)} участников:")
    await call.answer()


@router.message(MultiRateState.score)
async def ms_rate_score(message: Message, state: FSMContext):
    try:
        score = float(message.text.strip().replace(",", "."))
        if not 1.0 <= score <= 10.0: raise ValueError
    except ValueError:
        await message.answer("⚠️ Введи число от 1 до 10."); return
    await state.update_data(ms_score=round(score, 1))
    await state.set_state(MultiRateState.comment)
    await message.answer("💬 Комментарий (или «-»):")


@router.message(MultiRateState.comment)
async def ms_rate_comment(message: Message, state: FSMContext, bot: Bot):
    data     = await state.get_data()
    ids      = data.get("ms_rate_ids", [])
    score    = data["ms_score"]
    event_id = data.get("ms_rate_event_id")
    comment  = "" if message.text.strip() == "-" else message.text.strip()
    await state.clear()

    if not event_id:
        # Просим выбрать ивент
        events = get_all_events()[:10]
        b = InlineKeyboardBuilder()
        ids_str = "_".join(str(i) for i in ids)
        for ev in events:
            b.row(InlineKeyboardButton(
                text=f"📌 {ev['title']}",
                callback_data=f"ms_rate_final_{ev['id']}_{score}_{ids_str}"[:64]
            ))
        await message.answer("Выбери ивент для оценки:", reply_markup=b.as_markup())
        return

    event = get_event(event_id)
    bulk_add_rating_score(ids, event_id, score, comment)
    await message.answer(
        f"✅ Оценка <b>{score}</b> выставлена <b>{len(ids)}</b> участникам — «{event['title']}»",
        parse_mode="HTML", reply_markup=admin_menu_kb()
    )
    for uid in ids:
        u = get_user(uid)
        if not u: continue
        try:
            await bot.send_message(
                uid,
                f"📊 Оценка за «{event['title']}»: ⭐ {score}/10"
                + (f"\n💬 {comment}" if comment else "")
                + f"\n📈 Твой рейтинг: <b>{u['rating']}</b>",
                parse_mode="HTML"
            )
        except Exception:
            pass
