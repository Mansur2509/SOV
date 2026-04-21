# 🤝 SOV Bot — School of Volunteers, Alwuit

Telegram-бот для управления волонтёрской организацией SOV.

---

## 🚀 Деплой на Render + Supabase (бесплатно, БД не слетает)

### Шаг 1 — Получи новый токен бота

1. Открой Telegram → @BotFather
2. Напиши `/revoke` → выбери своего бота → подтверди отзыв
3. Напиши `/newbot` или `/token` → скопируй новый токен

> ⚠️ **Никогда не публикуй токен в GitHub!** Он хранится только в переменных окружения.

---

### Шаг 2 — Создай базу данных на Supabase

1. Зайди на [supabase.com](https://supabase.com) → **Start your project**
2. Зарегистрируйся (Google или GitHub)
3. Нажми **New project** → придумай название (например `sov-bot`) → запомни пароль
4. Подожди ~2 минуты пока база создаётся
5. Перейди: **Settings → Database → Connection string → URI**
6. Скопируй строку. Она выглядит так:
   ```
   postgresql://postgres:ТВО_ПАРОЛЬ@db.abcdefgh.supabase.co:5432/postgres
   ```
7. **Замени `[YOUR-PASSWORD]`** на реальный пароль если он не подставился

---

### Шаг 3 — Загрузи код на GitHub

1. Зайди на [github.com](https://github.com) → **New repository**
2. Название: `sov_bot` → **Private** (обязательно!) → **Create**
3. На своём компьютере открой папку с ботом в терминале:
   ```bash
   git init
   git add .
   git commit -m "Initial commit"
   git branch -M main
   git remote add origin https://github.com/ТВО_ЛОГИН/sov_bot.git
   git push -u origin main
   ```

---

### Шаг 4 — Деплой на Render

1. Зайди на [render.com](https://render.com) → **Get Started for Free**
2. Войди через GitHub
3. Нажми **New +** → **Background Worker**
4. Выбери свой репозиторий `sov_bot`
5. Заполни поля:
   - **Name**: `sov-bot`
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `python main.py`
6. Перейди в **Environment** и добавь переменные:

   | Key | Value |
   |-----|-------|
   | `BOT_TOKEN` | токен от @BotFather |
   | `DATABASE_URL` | строка из Supabase |
   | `WEBHOOK_HOST` | `https://sov-bot.onrender.com` (имя твоего сервиса) |
   | `PORT` | `8080` |

7. Нажми **Create Background Worker**

> 💡 **Webhook URL** — название сервиса на Render. Если назвал `sov-bot`, то URL будет `https://sov-bot.onrender.com`. Если другое — посмотри в разделе Settings своего сервиса.

---

### Шаг 5 — Проверь что всё работает

1. В Render перейди в **Logs** своего сервиса
2. Должны появиться строки:
   ```
   База данных инициализирована ✓
   Вспомогательные таблицы готовы ✓
   Webhook установлен: https://sov-bot.onrender.com/webhook ✓
   ```
3. Напиши своему боту `/start`

---

## 💻 Локальная разработка (без сервера)

```bash
# 1. Установи зависимости
pip install -r requirements.txt

# 2. Скопируй и заполни .env
cp .env.example .env
# Открой .env и вставь BOT_TOKEN
# DATABASE_URL оставь пустым (будет SQLite)
# WEBHOOK_HOST оставь пустым (будет polling)

# 3. Запусти
python main.py
```

При локальном запуске бот автоматически использует режим **polling** и файл **sov.db** — никаких дополнительных настроек не нужно.

---

## 📁 Структура проекта

```
sov_bot/
├── main.py              — точка входа, webhook/polling автовыбор
├── config.py            — токен, ADMIN_IDS, REGLAMENT, расписание пар
├── database.py          — вся работа с БД (PostgreSQL + SQLite)
├── keyboards.py         — все кнопки и меню
├── i18n.py              — переводы (RU/UZ/EN)
├── scheduler.py         — напоминания, топ-3, дедлайны
├── render.yaml          — конфиг деплоя Render
├── .env.example         — шаблон переменных окружения
├── requirements.txt
├── handlers/
│   ├── user.py          — команды участников
│   ├── admin.py         — панель администратора
│   └── organizer.py     — панель организатора
└── utils/
    ├── cache.py         — TTL-кэш
    ├── audit.py         — лог действий администраторов
    ├── achievements.py  — система достижений (бейджи)
    └── excel_export.py  — экспорт в Excel
```

---

## 👤 Роли

| Роль | Команда | Возможности |
|------|---------|-------------|
| **user** | автоматически | Запись на ивенты, профиль, рейтинг |
| **organizer** | `/organizer` | Создание ивентов, автоподбор, оценки, QR |
| **admin** | `/admin` | Всё + баны, поинты, роли, статистика |

Назначить организатора: `/setrole 123456789 organizer`

---

## ⚙️ Переменные окружения

| Переменная | Обязательна | Описание |
|-----------|-------------|---------|
| `BOT_TOKEN` | ✅ | Токен от @BotFather |
| `DATABASE_URL` | Для продакшена | PostgreSQL URI (Supabase) |
| `WEBHOOK_HOST` | Для Render | URL сервиса без слеша в конце |
| `PORT` | Для Render | Порт (обычно 8080) |

---

## 🔧 Частые проблемы

**Бот не отвечает после деплоя**
→ Проверь Logs в Render. Обычно причина в неверном `BOT_TOKEN` или `DATABASE_URL`.

**Ошибка подключения к БД**
→ Убедись что в `DATABASE_URL` нет лишних пробелов. Пароль в URL должен быть URL-закодирован (пробелы → `%20`).

**Webhook не устанавливается**
→ `WEBHOOK_HOST` должен начинаться с `https://` и не иметь `/` в конце.

**Как обновить бота**
→ Просто сделай `git push` в GitHub. Render автоматически пересоберёт и перезапустит.
# SOV Role Bot
