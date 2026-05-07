from aiogram.types import KeyboardButton, InlineKeyboardButton
from aiogram.utils.keyboard import ReplyKeyboardBuilder, InlineKeyboardBuilder
from i18n import t

from aiogram.types import ReplyKeyboardMarkup, KeyboardButton

gender_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="Мужской"), KeyboardButton(text="Женский")]
    ],
    resize_keyboard=True
)
# ─── Согласие ─────────────────────────────────────────────────────────────────

def agreement_kb(lang: str = "ru"):
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text=t("agree_btn", lang), callback_data="agree_yes"))
    return builder.as_markup()


# ─── Список ивентов ───────────────────────────────────────────────────────────

def events_kb(events: list, user_applications: set, lang: str = "ru"):
    builder = InlineKeyboardBuilder()
    for ev in events:
        applied = ev["id"] in user_applications
        label   = f"{'✅ ' if applied else ''}📌 {ev['title']} ({ev['event_date']})"
        builder.row(InlineKeyboardButton(text=label, callback_data=f"event_{ev['id']}"))
    return builder.as_markup()


def event_detail_kb(event_id: int, already_applied: bool, can_apply: bool = True,
                    app_status: str = None, lang: str = "ru"):
    builder = InlineKeyboardBuilder()
    if can_apply and not already_applied:
        builder.row(InlineKeyboardButton(text=t("apply_btn", lang), callback_data=f"apply_{event_id}"))
    if already_applied and app_status == "pending":
        builder.row(InlineKeyboardButton(text=t("cancel_btn", lang), callback_data=f"cancel_apply_{event_id}"))
    builder.row(InlineKeyboardButton(text=t("back_btn", lang), callback_data="back_events"))
    return builder.as_markup()


# ─── Карточки ─────────────────────────────────────────────────────────────────

def cards_nav_kb(offset: int, total: int):
    builder = InlineKeyboardBuilder()
    row = []
    if offset + 1 < total:
        row.append(InlineKeyboardButton(text="▶️", callback_data=f"card_next_{offset+1}"))
    if offset > 0:
        row.append(InlineKeyboardButton(text="◀️", callback_data=f"card_prev_{offset-1}"))
    if row:
        builder.row(*row)
    builder.row(InlineKeyboardButton(text="❌", callback_data="card_close"))
    return builder.as_markup()


# ─── Объявления ──────────────────────────────────────────────────────────────

def announcements_nav_kb(offset: int, total: int):
    builder = InlineKeyboardBuilder()
    row = []
    if offset + 3 < total:
        row.append(InlineKeyboardButton(text="⏫ +3", callback_data=f"ann_skip_{offset+3}"))
    if offset + 1 < total:
        row.append(InlineKeyboardButton(text="▶️", callback_data=f"ann_next_{offset+1}"))
    if offset > 0:
        row.append(InlineKeyboardButton(text="◀️", callback_data=f"ann_prev_{offset-1}"))
    if row:
        builder.row(*row)
    builder.row(InlineKeyboardButton(text="❌", callback_data="ann_close"))
    return builder.as_markup()


# ─── Главное меню (fallback, без локализации) ────────────────────────────────

def main_menu_kb():
    builder = ReplyKeyboardBuilder()
    builder.row(KeyboardButton(text="📋 Активные ивенты"))
    builder.row(KeyboardButton(text="👤 Мой профиль"), KeyboardButton(text="🏆 Рейтинг"))
    builder.row(KeyboardButton(text="🎴 Мои карточки"), KeyboardButton(text="📢 Объявления"))
    builder.row(KeyboardButton(text="💡 Предложить ивент"), KeyboardButton(text="🆘 Поддержка"))
    builder.row(KeyboardButton(text="🔗 Реферальная ссылка"), KeyboardButton(text="📖 Как это работает?"))
    builder.row(KeyboardButton(text="🌐 Язык / Til / Language"), KeyboardButton(text="🏠 Главное меню"))
    return builder.as_markup(resize_keyboard=True)


# ─── Админ-меню ──────────────────────────────────────────────────────────────

def admin_menu_kb():
    builder = ReplyKeyboardBuilder()
    builder.row(KeyboardButton(text="➕ Создать ивент"), KeyboardButton(text="⚡ Быстрый ивент из текста"))
    builder.row(KeyboardButton(text="📂 Все ивенты"), KeyboardButton(text="👥 Все участники"))
    builder.row(KeyboardButton(text="📢 Написать объявление"), KeyboardButton(text="📊 Топ-3 сейчас"))
    builder.row(KeyboardButton(text="📬 Предложения ивентов"), KeyboardButton(text="📈 Статистика"))
    builder.row(KeyboardButton(text="🎯 Таргет рассылка"), KeyboardButton(text="📋 Шаблоны ивентов"))
    builder.row(KeyboardButton(text="🎭 Роли"), KeyboardButton(text="📊 Экспорт Excel"))
    builder.row(KeyboardButton(text="🔙 Выйти из админки"))
    return builder.as_markup(resize_keyboard=True)


def admin_events_kb(events: list):
    builder = InlineKeyboardBuilder()
    for ev in events:
        status = "🟢" if ev["is_active"] else "🔴"
        builder.row(InlineKeyboardButton(
            text=f"{status} {ev['title']} ({ev['event_date']})",
            callback_data=f"adm_event_{ev['id']}"
        ))
    return builder.as_markup()


def admin_event_detail_kb(event_id: int, is_active: bool, work_closed: bool = False):
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="🤖 Автоподбор",        callback_data=f"autoselect_{event_id}"))
    b.row(InlineKeyboardButton(text="✏️ Редакт. список",    callback_data=f"edit_selected_{event_id}"))
    b.row(InlineKeyboardButton(text="👥 Все заявки",         callback_data=f"adm_apps_{event_id}"))
    b.row(
        InlineKeyboardButton(text="⭐ Оценки",   callback_data=f"rate_event_{event_id}"),
        InlineKeyboardButton(text="🎴 Карточки", callback_data=f"issue_cards_{event_id}"),
    )
    b.row(
        InlineKeyboardButton(text="🔲 QR старт", callback_data=f"gen_qr_start_{event_id}"),
        InlineKeyboardButton(text="🔲 QR финиш", callback_data=f"gen_qr_end_{event_id}"),
    )
    b.row(
        InlineKeyboardButton(text="🖼 Фото ивента",   callback_data=f"upload_img_{event_id}"),
        InlineKeyboardButton(text="🎴 Фото карточки", callback_data=f"upload_card_{event_id}"),
    )
    b.row(InlineKeyboardButton(text="➕ Добавить участника", callback_data=f"manual_add_{event_id}"))
    b.row(InlineKeyboardButton(text="⏰ Дедлайн",            callback_data=f"set_deadline_{event_id}"))
    if is_active:
        b.row(InlineKeyboardButton(text="🔒 Закрыть набор",  callback_data=f"close_event_{event_id}"))
    if not work_closed:
        b.row(InlineKeyboardButton(text="🏁 Закрыть работу", callback_data=f"close_work_{event_id}"))
    else:
        b.row(InlineKeyboardButton(text="✅ Завершить ивент", callback_data=f"finish_event_{event_id}"))
    b.row(InlineKeyboardButton(text="🗑 Удалить ивент",       callback_data=f"del_event_{event_id}"))
    b.row(InlineKeyboardButton(text="◀️ Назад",               callback_data="back_adm_events"))
    return b.as_markup()


def admin_users_kb(users: list, page: int = 0, total: int = 0, per_page: int = 30):
    b = InlineKeyboardBuilder()
    for u in users:
        ban_icon = {"full": "🚫", "temp": "⏳"}.get(u.get("ban_type", "none"), "")
        gi  = "♂" if u["gender"] == "М" else "♀"
        pts = f" ⚠️{u['points']}" if u.get("points", 0) > 0 else ""
        b.row(InlineKeyboardButton(
            text=f"{ban_icon}{gi} {u['full_name']} ({u['group_name']}) ⭐{u['rating']}{pts}",
            callback_data=f"adm_user_{u['tg_id']}"
        ))
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️", callback_data=f"users_page_{page-1}"))
    if total > 0:
        total_pages = max(1, (total + per_page - 1) // per_page)
        nav.append(InlineKeyboardButton(text=f"{page+1}/{total_pages}", callback_data="noop"))
    if (page + 1) * per_page < total:
        nav.append(InlineKeyboardButton(text="▶️", callback_data=f"users_page_{page+1}"))
    if nav:
        b.row(*nav)
    b.row(InlineKeyboardButton(text="☑️ Мульти-выбор", callback_data="multi_select_users"))
    return b.as_markup()


def admin_user_detail_kb(tg_id: int, ban_type: str):
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="⚠️ +1 поинт", callback_data=f"pts_add_{tg_id}"),
        InlineKeyboardButton(text="✅ -1 поинт",  callback_data=f"pts_remove_{tg_id}"),
    )
    builder.row(InlineKeyboardButton(text="📋 История поинтов", callback_data=f"pts_history_{tg_id}"))
    if ban_type == "none":
        builder.row(
            InlineKeyboardButton(text="⏳ Бан 30д",  callback_data=f"ban_temp_{tg_id}"),
            InlineKeyboardButton(text="🚫 Фулл бан", callback_data=f"ban_full_{tg_id}"),
        )
    else:
        builder.row(InlineKeyboardButton(text="✅ Разбанить", callback_data=f"unban_{tg_id}"))
    builder.row(InlineKeyboardButton(text="📝 Заметка",           callback_data=f"edit_note_{tg_id}"))
    builder.row(InlineKeyboardButton(text="🗑 Удалить участника",  callback_data=f"del_user_{tg_id}"))
    builder.row(InlineKeyboardButton(text="◀️ Назад",              callback_data="back_adm_users"))
    return builder.as_markup()


def confirm_ban_kb(tg_id: int, ban_type: str):
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="✅ Подтвердить", callback_data=f"ban_confirm_{ban_type}_{tg_id}"),
        InlineKeyboardButton(text="❌ Отмена",       callback_data=f"adm_user_{tg_id}"),
    )
    return builder.as_markup()


def confirm_delete_kb(target: str, target_id: int):
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="🗑 Да, удалить", callback_data=f"del_confirm_{target}_{target_id}"),
        InlineKeyboardButton(text="❌ Отмена",       callback_data=f"del_cancel_{target}_{target_id}"),
    )
    return builder.as_markup()


def rate_select_user_kb(applications: list, event_id: int):
    builder = InlineKeyboardBuilder()
    for app in applications:
        if app["status"] == "selected":
            builder.row(InlineKeyboardButton(
                text=app["full_name"],
                callback_data=f"rate_user_{event_id}_{app['tg_id']}"
            ))
    builder.row(InlineKeyboardButton(text="◀️ Назад", callback_data=f"adm_event_{event_id}"))
    return builder.as_markup()


def proposals_kb(proposals: list):
    builder = InlineKeyboardBuilder()
    for p in proposals:
        builder.row(InlineKeyboardButton(
            text=f"📋 {p['full_name']} — {p['event_date']}",
            callback_data=f"proposal_{p['id']}"
        ))
    builder.row(InlineKeyboardButton(text="◀️ Закрыть", callback_data="close_proposals"))
    return builder.as_markup()


def proposal_action_kb(pid: int):
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="✅ Одобрить",  callback_data=f"prop_approve_{pid}"),
        InlineKeyboardButton(text="❌ Отклонить", callback_data=f"prop_reject_{pid}"),
    )
    builder.row(InlineKeyboardButton(text="◀️ Назад", callback_data="back_proposals"))
    return builder.as_markup()

from aiogram.types import ReplyKeyboardMarkup, KeyboardButton

# Клавиатура выбора пола (нужна для анкеты)
gender_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="♂️ Мужской"), KeyboardButton(text="♀️ Женский")]
    ],
    resize_keyboard=True,
    one_time_keyboard=True
)

# ─── Редактирование списка ────────────────────────────────────────────────────

def edit_selected_kb(event_id: int, selected: list):
    b = InlineKeyboardBuilder()
    for s in selected:
        gi = "♂" if s["gender"] == "М" else "♀"
        b.row(InlineKeyboardButton(
            text=f"❌ {gi} {s['full_name']} ({s['group_name']}) ⭐{s['rating']}",
            callback_data=f"remove_selected_{event_id}_{s['tg_id']}"
        ))
    b.row(InlineKeyboardButton(text="➕ Добавить вручную", callback_data=f"manual_add_{event_id}"))
    b.row(
        InlineKeyboardButton(text="✅ Подтвердить список", callback_data=f"confirm_selected_{event_id}"),
        InlineKeyboardButton(text="◀️ Назад",              callback_data=f"adm_event_{event_id}"),
    )
    return b.as_markup()


# ─── Мульти-оценка ────────────────────────────────────────────────────────────

def rate_multi_kb(event_id: int, applications: list, selected_ids: set):
    b = InlineKeyboardBuilder()
    for app in applications:
        if app["status"] in ("done", "selected", "working"):
            tick = "☑️" if app["tg_id"] in selected_ids else "⬜"
            b.row(InlineKeyboardButton(
                text=f"{tick} {app['full_name']}",
                callback_data=f"rate_multi_toggle_{event_id}_{app['tg_id']}"
            ))
    b.row(
        InlineKeyboardButton(text="⭐ Оценить выбранных", callback_data=f"rate_multi_apply_{event_id}"),
        InlineKeyboardButton(text="❌ Отмена",            callback_data=f"rate_event_{event_id}"),
    )
    return b.as_markup()


# ─── Мульти-выбор участников ─────────────────────────────────────────────────

def multi_select_users_kb(users: list, selected: set, action: str):
    b = InlineKeyboardBuilder()
    for u in users:
        tick = "☑️" if u["tg_id"] in selected else "⬜"
        b.row(InlineKeyboardButton(
            text=f"{tick} {u['full_name']} ({u['group_name']})",
            callback_data=f"ms_toggle_{action}_{u['tg_id']}"
        ))
    b.row(
        InlineKeyboardButton(text="✅ Применить", callback_data=f"ms_apply_{action}"),
        InlineKeyboardButton(text="❌ Отмена",    callback_data="ms_cancel"),
    )
    return b.as_markup()


# ─── Выдача карточки конкретному ─────────────────────────────────────────────

def give_card_events_kb(events: list, tg_id: int):
    b = InlineKeyboardBuilder()
    for ev in events:
        b.row(InlineKeyboardButton(
            text=f"📌 {ev['title']} ({ev['event_date']})",
            callback_data=f"give_card_ev_{tg_id}_{ev['id']}"
        ))
    b.row(InlineKeyboardButton(text="◀️ Назад", callback_data=f"adm_user_{tg_id}"))
    return b.as_markup()


# ─── Объявления с кнопкой удаления ───────────────────────────────────────────

def announcements_nav_kb(offset: int, total: int, is_admin: bool = False):
    b = InlineKeyboardBuilder()
    row = []
    if offset + 3 < total:
        row.append(InlineKeyboardButton(text="⏫ +3", callback_data=f"ann_skip_{offset+3}"))
    if offset + 1 < total:
        row.append(InlineKeyboardButton(text="▶️",   callback_data=f"ann_next_{offset+1}"))
    if offset > 0:
        row.append(InlineKeyboardButton(text="◀️",   callback_data=f"ann_prev_{offset-1}"))
    if row:
        b.row(*row)
    if is_admin:
        b.row(InlineKeyboardButton(text="🗑 Удалить это объявление",
                                   callback_data=f"ann_delete_offset_{offset}"))
    b.row(InlineKeyboardButton(text="❌ Закрыть", callback_data="ann_close"))
    return b.as_markup()
