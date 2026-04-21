"""
handlers/organizer.py — обработчики для роли «Организатор».

Организатор МОЖЕТ:
  • Создавать ивенты
  • Просматривать заявки на свои ивенты
  • Запускать автоподбор
  • Выдавать карточки и генерировать QR
  • Выставлять оценки

Организатор НЕ МОЖЕТ:
  • Видеть личные дела участников (поинты, заметки, баны)
  • Выдавать/снимать баны и поинты
  • Писать объявления
  • Удалять ивенты и участников
"""
import asyncio
import io
import logging
import qrcode

from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, BufferedInputFile
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from aiogram.types import InlineKeyboardButton, KeyboardButton

from database import (
    get_user, get_event, create_event, close_event,
    get_applications, auto_select, get_selected_for_event,
    issue_card, generate_qr_token, add_rating,
    get_all_events, set_event_photo, get_role,
    set_registration_deadline
)
from utils.audit import log_action
from config import PAIRS_SCHEDULE
from datetime import datetime

logger = logging.getLogger(__name__)
router = Router()


def is_organizer(tg_id: int) -> bool:
    role = get_role(tg_id)
    return role in ("organizer", "admin")


def get_pair_info(time_str: str) -> str:
    if not time_str: return ""
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


# ─── Меню организатора ───────────────────────────────────────────────────────

def org_menu_kb():
    builder = ReplyKeyboardBuilder()
    builder.row(KeyboardButton(text="➕ [ORG] Создать ивент"))
    builder.row(KeyboardButton(text="📂 [ORG] Мои ивенты"))
    builder.row(KeyboardButton(text="🔙 Выйти из меню организатора"))
    return builder.as_markup(resize_keyboard=True)


def org_event_detail_kb(event_id: int, is_active: bool):
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🤖 Автоподбор",      callback_data=f"org_autoselect_{event_id}"))
    builder.row(InlineKeyboardButton(text="👥 Заявки",          callback_data=f"org_apps_{event_id}"))
    builder.row(InlineKeyboardButton(text="⭐ Оценки",          callback_data=f"org_rate_{event_id}"))
    builder.row(InlineKeyboardButton(text="🎴 Выдать карточки", callback_data=f"org_cards_{event_id}"))
    builder.row(InlineKeyboardButton(text="🔲 QR-код",          callback_data=f"org_qr_{event_id}"))
    builder.row(InlineKeyboardButton(text="🖼 Загрузить фото",  callback_data=f"org_img_{event_id}"))
    builder.row(InlineKeyboardButton(text="⏰ Дедлайн записи",  callback_data=f"org_deadline_{event_id}"))
    if is_active:
        builder.row(InlineKeyboardButton(text="🔒 Закрыть набор", callback_data=f"org_close_{event_id}"))
    builder.row(InlineKeyboardButton(text="◀️ Назад",           callback_data="org_back_events"))
    return builder.as_markup()


# ─── FSM ─────────────────────────────────────────────────────────────────────

class OrgCreateEvent(StatesGroup):
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


class OrgRateState(StatesGroup):
    score   = State()
    comment = State()


class OrgDeadlineState(StatesGroup):
    deadline = State()


class OrgImgState(StatesGroup):
    photo = State()


# ─── /organizer ──────────────────────────────────────────────────────────────

@router.message(Command("organizer"))
async def cmd_organizer(message: Message):
    if not is_organizer(message.from_user.id):
        await message.answer("⛔ У тебя нет роли организатора.")
        return
    user = get_user(message.from_user.id)
    await message.answer(
        f"🗂 <b>Меню организатора SOV</b>\n\n"
        f"Добро пожаловать, {user['full_name']}!\n"
        f"Здесь ты можешь создавать ивенты и управлять ими.",
        parse_mode="HTML",
        reply_markup=org_menu_kb()
    )


@router.message(F.text == "🔙 Выйти из меню организатора")
async def org_exit(message: Message):
    from keyboards import main_menu_kb
    await message.answer("Вышел из меню организатора.", reply_markup=main_menu_kb())


# ─── Создание ивента ─────────────────────────────────────────────────────────

@router.message(F.text == "➕ [ORG] Создать ивент")
async def org_create_start(message: Message, state: FSMContext):
    if not is_organizer(message.from_user.id): return
    await state.set_state(OrgCreateEvent.title)
    await message.answer("📌 <b>Название ивента:</b>", parse_mode="HTML")


@router.message(OrgCreateEvent.title)
async def org_cev_title(message: Message, state: FSMContext):
    await state.update_data(title=message.text.strip())
    await state.set_state(OrgCreateEvent.description)
    await message.answer("📝 Описание (или «-»):")


@router.message(OrgCreateEvent.description)
async def org_cev_desc(message: Message, state: FSMContext):
    await state.update_data(description="" if message.text.strip()=="-" else message.text.strip())
    await state.set_state(OrgCreateEvent.event_date)
    await message.answer("📅 Дата (например: 25.05.2025):")


@router.message(OrgCreateEvent.event_date)
async def org_cev_date(message: Message, state: FSMContext):
    await state.update_data(event_date=message.text.strip())
    await state.set_state(OrgCreateEvent.event_time)
    await message.answer("🕐 Время начала (например: 10:00, или «-»):")


@router.message(OrgCreateEvent.event_time)
async def org_cev_time(message: Message, state: FSMContext):
    await state.update_data(event_time="" if message.text.strip()=="-" else message.text.strip())
    await state.set_state(OrgCreateEvent.location)
    await message.answer("📍 Место проведения (или «-»):")


@router.message(OrgCreateEvent.location)
async def org_cev_location(message: Message, state: FSMContext):
    await state.update_data(location="" if message.text.strip()=="-" else message.text.strip())
    await state.set_state(OrgCreateEvent.duration)
    await message.answer("⏱ Длительность (или «-»):")


@router.message(OrgCreateEvent.duration)
async def org_cev_duration(message: Message, state: FSMContext):
    await state.update_data(duration="" if message.text.strip()=="-" else message.text.strip())
    await state.set_state(OrgCreateEvent.meeting_point)
    await message.answer("🤝 Место встречи волонтёров (или «-»):")


@router.message(OrgCreateEvent.meeting_point)
async def org_cev_meeting(message: Message, state: FSMContext):
    await state.update_data(meeting_point="" if message.text.strip()=="-" else message.text.strip())
    await state.set_state(OrgCreateEvent.total_slots)
    await message.answer("👥 Всего волонтёров:")


@router.message(OrgCreateEvent.total_slots)
async def org_cev_total(message: Message, state: FSMContext):
    if not message.text.strip().isdigit():
        await message.answer("⚠️ Введи число."); return
    await state.update_data(total_slots=int(message.text.strip()))
    await state.set_state(OrgCreateEvent.male_slots)
    await message.answer("♂ Парней (0 = без квоты):")


@router.message(OrgCreateEvent.male_slots)
async def org_cev_male(message: Message, state: FSMContext):
    if not message.text.strip().isdigit():
        await message.answer("⚠️ Число."); return
    await state.update_data(male_slots=int(message.text.strip()))
    await state.set_state(OrgCreateEvent.female_slots)
    await message.answer("♀ Девушек (0 = без квоты):")


@router.message(OrgCreateEvent.female_slots)
async def org_cev_female(message: Message, state: FSMContext):
    if not message.text.strip().isdigit():
        await message.answer("⚠️ Число."); return
    await state.update_data(female_slots=int(message.text.strip()))
    await state.set_state(OrgCreateEvent.gender_strict)
    await message.answer("🔒 Строгое ограничение по полу? (Да/Нет)")


@router.message(OrgCreateEvent.gender_strict)
async def org_cev_strict(message: Message, state: FSMContext, bot: Bot):
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

    user = get_user(message.from_user.id)
    log_action(message.from_user.id, user["full_name"],
               "CREATE_EVENT", f"id={eid} title={data['title']}")

    await message.answer(
        f"✅ Ивент <b>«{data['title']}»</b> создан (ID: {eid})!",
        parse_mode="HTML", reply_markup=org_menu_kb()
    )

    # Рассылка о новом ивенте
    from handlers.admin import _broadcast_new_event
    slots_info = f"{data['total_slots']} чел."
    await _broadcast_new_event(bot, data["title"], data["event_date"],
                                data.get("event_time",""), data.get("location",""), slots_info)


# ─── Список ивентов ──────────────────────────────────────────────────────────

@router.message(F.text == "📂 [ORG] Мои ивенты")
async def org_all_events(message: Message):
    if not is_organizer(message.from_user.id): return
    events = get_all_events()
    if not events:
        await message.answer("Ивентов нет."); return
    builder = InlineKeyboardBuilder()
    for ev in events[:20]:
        status = "🟢" if ev["is_active"] else "🔴"
        builder.row(InlineKeyboardButton(
            text=f"{status} {ev['title']} ({ev['event_date']})",
            callback_data=f"org_event_{ev['id']}"
        ))
    await message.answer("📂 <b>Ивенты</b>:", parse_mode="HTML", reply_markup=builder.as_markup())


@router.callback_query(F.data.regexp(r"^org_event_(\d+)$"))
async def org_event_detail(call: CallbackQuery):
    event_id = int(call.data.split("_")[2])
    event    = get_event(event_id)
    if not event: await call.answer("Не найдено."); return
    apps = get_applications(event_id)
    sel  = sum(1 for a in apps if a["status"]=="selected")
    pend = sum(1 for a in apps if a["status"]=="pending")
    text = (
        f"📌 <b>{event['title']}</b>\n"
        f"📅 {event['event_date']} {event.get('event_time','')}\n"
        f"📍 {event.get('location','—')}\n"
        f"👥 {event['total_slots']} | {'🟢' if event['is_active'] else '🔴'}\n"
        f"📨 Заявок: {len(apps)} | ⏳{pend} | ✅{sel}"
    )
    await call.message.edit_text(text, parse_mode="HTML",
                                  reply_markup=org_event_detail_kb(event_id, bool(event["is_active"])))


@router.callback_query(F.data == "org_back_events")
async def org_back_events(call: CallbackQuery):
    events = get_all_events()
    builder = InlineKeyboardBuilder()
    for ev in events[:20]:
        status = "🟢" if ev["is_active"] else "🔴"
        builder.row(InlineKeyboardButton(
            text=f"{status} {ev['title']} ({ev['event_date']})",
            callback_data=f"org_event_{ev['id']}"
        ))
    await call.message.edit_text("📂 <b>Ивенты</b>:", parse_mode="HTML", reply_markup=builder.as_markup())


# ─── Закрытие набора ─────────────────────────────────────────────────────────

@router.callback_query(F.data.regexp(r"^org_close_(\d+)$"))
async def org_close(call: CallbackQuery, bot: Bot):
    event_id = int(call.data.split("_")[2])
    event    = get_event(event_id)
    close_event(event_id)
    user = get_user(call.from_user.id)
    log_action(call.from_user.id, user["full_name"], "CLOSE_EVENT",
               f"id={event_id} title={event['title']}")
    from handlers.admin import _broadcast_close_event
    await _broadcast_close_event(bot, event_id, event["title"], event["event_date"])
    await call.answer("🔒 Закрыт.", show_alert=True)
    await org_event_detail(call)


# ─── Заявки ──────────────────────────────────────────────────────────────────

@router.callback_query(F.data.regexp(r"^org_apps_(\d+)$"))
async def org_applications(call: CallbackQuery):
    event_id = int(call.data.split("_")[2])
    apps     = get_applications(event_id)
    if not apps: await call.answer("Заявок нет.", show_alert=True); return
    lines = []
    for a in apps:
        icon = {"selected":"✅","pending":"⏳","rejected":"❌"}.get(a["status"],"❓")
        gi   = "♂" if a["gender"]=="М" else "♀"
        att  = " 🎯" if a.get("attended") else ""
        lines.append(f"{icon}{gi} {a['full_name']} ({a['group_name']}) ⭐{a['rating']}{att}")
    await call.message.edit_text(
        "📨 <b>Заявки</b>\n\n" + "\n".join(lines), parse_mode="HTML",
        reply_markup=org_event_detail_kb(event_id, True)
    )


# ─── Автоподбор ──────────────────────────────────────────────────────────────

@router.callback_query(F.data.regexp(r"^org_autoselect_(\d+)$"))
async def org_autoselect(call: CallbackQuery, bot: Bot):
    event_id = int(call.data.split("_")[2])
    event    = get_event(event_id)
    result   = auto_select(event_id)
    selected = result["selected"]
    if not selected: await call.answer("Нет заявок.", show_alert=True); return

    pair_str = get_pair_info(event.get("event_time",""))
    time_str = event.get("event_time","")
    lines    = [f"{i}. {s['full_name']} {s['group_name']}" for i, s in enumerate(selected, 1)]

    report = (
        f"📋 <b>Просьба отпросить волонтёров на ивент</b>\n"
        f"«<b>{event['title']}</b>»\n"
        f"📅 {event['event_date']} в {time_str} {pair_str}\n\n"
        + "\n".join(lines)
    )
    await call.message.answer(report, parse_mode="HTML")
    await call.answer("✅ Готово!")

    user = get_user(call.from_user.id)
    log_action(call.from_user.id, user["full_name"], "AUTO_SELECT",
               f"event_id={event_id} selected={len(selected)}")

    for s in selected:
        try:
            await bot.send_message(
                s["tg_id"],
                f"🎉 Ты выбран волонтёром на <b>«{event['title']}»</b>!\n"
                f"📅 {event['event_date']}" + (f" в {time_str}" if time_str else "")
                + (f"\n📍 {event.get('location','')}" if event.get("location") else ""),
                parse_mode="HTML"
            )
        except Exception:
            pass


# ─── QR ──────────────────────────────────────────────────────────────────────

@router.callback_query(F.data.regexp(r"^org_qr_(\d+)$"))
async def org_qr(call: CallbackQuery, bot: Bot):
    event_id = int(call.data.split("_")[2])
    event    = get_event(event_id)
    token    = generate_qr_token(event_id)
    bot_info = await bot.get_me()
    qr_url   = f"https://t.me/{bot_info.username}?start=qrcheck_{token}"
    img = qrcode.make(qr_url)
    buf = io.BytesIO(); img.save(buf, format="PNG"); buf.seek(0)
    await call.message.answer_photo(
        BufferedInputFile(buf.getvalue(), filename="qr.png"),
        caption=f"🔲 QR для «{event['title']}»\n\n<code>{qr_url}</code>",
        parse_mode="HTML"
    )
    await call.answer()


# ─── Карточки ────────────────────────────────────────────────────────────────

@router.callback_query(F.data.regexp(r"^org_cards_(\d+)$"))
async def org_cards(call: CallbackQuery, bot: Bot):
    event_id   = int(call.data.split("_")[2])
    event      = get_event(event_id)
    volunteers = get_selected_for_event(event_id)
    issued     = 0
    for vol in volunteers:
        if issue_card(vol["tg_id"], event_id):
            issued += 1
            try:
                await bot.send_message(
                    vol["tg_id"],
                    f"🎴 <b>Тебе выдана карточка участника!</b>\n\n"
                    f"Ивент: <b>«{event['title']}»</b> ({event['event_date']})\n"
                    f"Смотри в «🎴 Мои карточки».",
                    parse_mode="HTML"
                )
                await asyncio.sleep(0.05)
            except Exception:
                pass
    await call.answer(f"✅ Карточек: {issued}", show_alert=True)


# ─── Загрузка фото ───────────────────────────────────────────────────────────

@router.callback_query(F.data.regexp(r"^org_img_(\d+)$"))
async def org_img_start(call: CallbackQuery, state: FSMContext):
    event_id = int(call.data.split("_")[2])
    await state.update_data(org_event_id=event_id)
    await state.set_state(OrgImgState.photo)
    await call.message.answer("🖼 Отправь фото для ивента:")
    await call.answer()


@router.message(OrgImgState.photo, F.photo)
async def org_img_save(message: Message, state: FSMContext):
    data = await state.get_data()
    set_event_photo(data["org_event_id"], message.photo[-1].file_id)
    await state.clear()
    await message.answer("✅ Фото сохранено!", reply_markup=org_menu_kb())


# ─── Дедлайн ─────────────────────────────────────────────────────────────────

@router.callback_query(F.data.regexp(r"^org_deadline_(\d+)$"))
async def org_deadline_start(call: CallbackQuery, state: FSMContext):
    event_id = int(call.data.split("_")[2])
    await state.update_data(deadline_event_id=event_id)
    await state.set_state(OrgDeadlineState.deadline)
    await call.message.answer(
        "⏰ Введи дедлайн записи в формате:\n"
        "<code>25.05.2025 18:00</code>",
        parse_mode="HTML"
    )
    await call.answer()


@router.message(OrgDeadlineState.deadline)
async def org_deadline_save(message: Message, state: FSMContext):
    data = await state.get_data()
    text = message.text.strip()
    try:
        dt = datetime.strptime(text, "%d.%m.%Y %H:%M")
        set_registration_deadline(data["deadline_event_id"], dt.isoformat())
        await state.clear()
        await message.answer(
            f"✅ Дедлайн установлен: <b>{dt.strftime('%d.%m.%Y %H:%M')}</b>\n"
            f"Набор закроется автоматически.",
            parse_mode="HTML", reply_markup=org_menu_kb()
        )
    except ValueError:
        await message.answer("⚠️ Неверный формат. Пример: 25.05.2025 18:00")


# ─── Оценки ──────────────────────────────────────────────────────────────────

@router.callback_query(F.data.regexp(r"^org_rate_(\d+)$"))
async def org_rate_start(call: CallbackQuery):
    event_id = int(call.data.split("_")[2])
    apps     = get_applications(event_id)
    if not any(a["status"]=="selected" for a in apps):
        await call.answer("Нет выбранных.", show_alert=True); return
    builder = InlineKeyboardBuilder()
    for app in apps:
        if app["status"] == "selected":
            builder.row(InlineKeyboardButton(
                text=app["full_name"],
                callback_data=f"org_rate_user_{event_id}_{app['tg_id']}"
            ))
    builder.row(InlineKeyboardButton(text="◀️ Назад", callback_data=f"org_event_{event_id}"))
    await call.message.edit_text("⭐ Выбери участника:", reply_markup=builder.as_markup())


@router.callback_query(F.data.regexp(r"^org_rate_user_(\d+)_(\d+)$"))
async def org_rate_user(call: CallbackQuery, state: FSMContext):
    parts    = call.data.split("_")
    event_id = int(parts[3])
    tg_id    = int(parts[4])
    await state.update_data(rate_event_id=event_id, rate_tg_id=tg_id)
    await state.set_state(OrgRateState.score)
    user = get_user(tg_id)
    await call.message.answer(f"⭐ Оцени <b>{user['full_name']}</b> (1–10):", parse_mode="HTML")
    await call.answer()


@router.message(OrgRateState.score)
async def org_rate_score(message: Message, state: FSMContext):
    try:
        score = float(message.text.strip().replace(",","."))
        if not 1 <= score <= 10: raise ValueError
    except ValueError:
        await message.answer("⚠️ 1–10"); return
    await state.update_data(score=score)
    await message.answer("💬 Комментарий (или «-»):")
    from aiogram.fsm.state import State
    await state.set_state(OrgRateState.comment)


@router.message(OrgRateState.comment)
async def org_rate_comment(message: Message, state: FSMContext, bot: Bot):
    data    = await state.get_data()
    comment = "" if message.text.strip()=="-" else message.text.strip()
    add_rating(data["rate_event_id"], data["rate_tg_id"], data["score"], comment)

    # Уведомление об изменении рейтинга
    from database import get_user as _gu
    user  = _gu(data["rate_tg_id"])
    event = get_event(data["rate_event_id"])
    await state.clear()
    await message.answer(
        f"✅ Оценка <b>{data['score']}</b> — {user['full_name']}!",
        parse_mode="HTML", reply_markup=org_menu_kb()
    )
    try:
        msg = (f"📊 Оценка за <b>«{event['title']}»</b>: ⭐ {data['score']}/10"
               + (f"\n💬 <i>{comment}</i>" if comment else "")
               + f"\n\n📈 Твой рейтинг: <b>{user['rating']}</b>")
        await bot.send_message(data["rate_tg_id"], msg, parse_mode="HTML")
    except Exception:
        pass
