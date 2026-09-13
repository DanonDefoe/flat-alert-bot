[For 🇷🇺 Russian language click here](#русский)


## English

# 🏠 Pad Alert — Tbilisi Rental Tracker Bot

**Pad Alert** monitors new apartment rental listings on **home.ss.ge** and **myhome.ge** and sends them directly to Telegram — with photos, a map, price, and quick action buttons.

---

## Features

- Tracks multiple filters simultaneously (up to two sites)
- Shows only **new** listings — no repeats of already seen ones
- Sends an **interactive map** directly in chat (via Telegram Location)
- Detects **duplicate listings** (same apartment posted by multiple agencies) and flags them
- **Favorites** — save an interesting apartment with one button
- **Delete from chat** — remove an unwanted listing (and everything that came with it — photos, map) with one button
- **Recent listings on demand** — pull everything posted in the last 1/3/6/12/24 hours for a filter, outside the regular schedule
- Configurable working hours (when the bot is active) in Tbilisi time
- Pause and resume without losing subscriptions
- Auto-deletes messages after 3 days (except favorites)
- Auto-closes the previous menu/navigation screen when a new one opens — the chat doesn't fill up with stale "Menu:" messages
- Supports multiple users

---

## Quick Start

### 1. Requirements

- Python 3.10+
- Telegram bot token (create one at [@BotFather](https://t.me/BotFather))

### 2. Installation

```bash
git clone <repo-url>
cd rental-listings-bot
python -m venv .venv
source .venv/bin/activate   # macOS / Linux
# .venv\Scripts\activate    # Windows

pip install -r requirements.txt
```

### 3. Configuration

```bash
cp .env.example .env
```

Open `.env` and fill in:

```env
TELEGRAM_BOT_TOKEN=123456789:AAxxxxxx   # required
DEVELOPER_TELEGRAM_ID=                  # your Telegram ID (find it at @userinfobot)
DATABASE_PATH=bot.db
LOG_LEVEL=INFO
WORK_HOURS_START_UTC=05:00              # 09:00 Tbilisi time
WORK_HOURS_END_UTC=21:00               # 01:00 Tbilisi time
```

### 4. Load the street directory

```bash
python src/streets/streets_loader.py src/streets/streets.json
```

This is a one-time setup — the directory gives the bot coordinates for the map.

### 5. Run

```bash
python -m src.main
```

Or via PyCharm: Run → Run 'main' (make sure `src/` is marked as Sources Root).

---

## How to Use

1. Send `/start` to the bot
2. Go to **ss.ge** or **myhome.ge**, set up your filters, and click "Search"
3. Copy the URL from the address bar and send it to the bot
4. Choose a check interval (20–60 minutes)
5. The bot will start sending new listings

### Menu (command `/menu`)

| Button | Action |
|---|---|
| ➕ Add site | Add a second filter (ss.ge or myhome.ge) |
| ✏️ Edit link | Replace the current filter |
| ⭐ Favorites | List of saved apartments |
| 🔄 Recent listings | Pull everything posted in the last 1/3/6/12/24 hours for a chosen filter |
| ⏸ Pause | Temporarily stop the bot |
| 🕐 Change working hours | Active hours in Tbilisi time |
| 📝 Developer note | Report an issue |

### Buttons on each listing

| Button | Action |
|---|---|
| ⭐ Favorites | Save the apartment |
| ☰ Menu | Open the menu |
| 🗑 Delete from chat | Remove the listing (and its photos/map) from chat |
| 🚫 Hide from feed | Hide a duplicate group (ss.ge only) |

---

## How It Works Under the Hood

- **Parsing without a browser** — both sites are built on Next.js and embed all listing data inside the HTML page (`__NEXT_DATA__`). A plain `requests.get()` call is enough — no Selenium or Playwright needed.
- **Scheduler** — checks sites at a randomized interval within the chosen range. It "ticks" once a minute and checks which subscriptions are due for their next check.
- **Deduplication** — uses the native duplicate signal (`similarityGroup`) for ss.ge; for myhome.ge uses a heuristic based on address + area (±6 m²) + floor.
- **Map** — for myhome.ge, coordinates come directly from the site; for ss.ge, they are looked up from the street directory by `streetId`, with a text-based fallback match if the ID lookup comes up empty. The map is sent via Telegram Location — an interactive widget right in the chat. If no coordinates can be found at all, a Google Maps search link is used instead.
- **Recent listings** — filters by the listing's own posting timestamp (`orderDate` on ss.ge, `last_updated` on myhome.ge), fetched fresh at request time rather than from the regular schedule's cache.
- **Auto-delete** — all bot messages (except favorites) are deleted after 3 days by a cleanup job that runs hourly. Navigation screens (menus, multi-step prompts) are deleted immediately once superseded by the next screen.

---

## Project Structure

```
rental-listings-bot/
├── src/
│   ├── main.py               # Entry point
│   ├── config.py             # Settings from .env
│   ├── logger.py             # Logging
│   ├── fetcher.py            # HTTP with retry and throttling
│   ├── db/                   # Database (SQLite)
│   ├── parsers/              # ss.ge and myhome.ge parsers
│   ├── dedup/                # Listing deduplication
│   ├── scheduler/            # Scheduler and auto-delete
│   ├── streets/              # Tbilisi street directory
│   ├── utils/                # Utilities (time, map)
│   └── bot/                  # Telegram bot (handlers, FSM, keyboards)
├── tests/                    # Tests
├── .env.example
├── requirements.txt
└── README.md
```

---

## Dependencies

| Package | Version |
|---|---|
| Python | 3.10+ |
| aiogram | 3.4.1 |
| APScheduler | 3.10.4 |
| requests | 2.31.0 |
| beautifulsoup4 | 4.12.2 |
| python-dotenv | 1.0.0 |

---

## Backlog

- Show cheaper duplicate listings (ss.ge API requires auth — not available yet)
- Highlight the street line on the map instead of a single point
- Show the landlord's phone number
- Cross-site deduplication (ss.ge ↔ myhome.ge)





## Русский
[🇬🇧 English](#english)

**Pad Alert** отслеживает новые объявления об аренде квартир на **home.ss.ge** и **myhome.ge** и присылает их напрямую в Telegram — с фото, картой, ценой и кнопками быстрых действий.

---

## Что умеет бот

- Следит одновременно за двумя сайтами (ссылок-фильтров может быть больше одной на сайт)
- Показывает только новые объявления — уже виденные не повторяет
- Прикладывает интерактивную карту прямо в чат (через Telegram Location)
- Определяет похожие объявления (дубли от разных агентств) и помечает их
- Избранное — сохранить понравившуюся квартиру одной кнопкой
- Удалить из чата — убрать неинтересное объявление одной кнопкой, вместе со всем, что к нему прилагалось (фото, карта)
- Последние объявления по запросу — забрать всё, что опубликовано за последние 1/3/6/12/24 часа по выбранному фильтру, вне обычного расписания
- Настраиваемое рабочее окно активности бота по тбилисскому времени
- Пауза и возобновление без потери подписок
- Автоудаление сообщений через 3 суток (кроме избранного)
- Автоматическое закрытие предыдущего окна меню/навигации при открытии нового — чат не засоряется старыми "Меню:"
- Поддержка нескольких пользователей

---

## Быстрый старт

### 1. Требования

- Python 3.10+
- Токен Telegram-бота (создать у [@BotFather](https://t.me/BotFather))

### 2. Установка

```bash
git clone <repo-url>
cd rental-listings-bot
python -m venv .venv
source .venv/bin/activate   # macOS / Linux
# .venv\Scripts\activate    # Windows

pip install -r requirements.txt
```

### 3. Конфигурация

```bash
cp .env.example .env
```

Открыть `.env` и заполнить:

```env
TELEGRAM_BOT_TOKEN=123456789:AAxxxxxx   # обязательно
DEVELOPER_TELEGRAM_ID=                  # твой Telegram ID (узнать у @userinfobot)
DATABASE_PATH=bot.db
LOG_LEVEL=INFO
WORK_HOURS_START_UTC=05:00              # 09:00 по Тбилиси
WORK_HOURS_END_UTC=21:00               # 01:00 по Тбилиси
```

### 4. Загрузка справочника улиц

```bash
python src/streets/streets_loader.py src/streets/streets.json
```

Это нужно сделать один раз — справочник даёт боту координаты для карты.

### 5. Запуск

```bash
python -m src.main
```

Или через PyCharm: Run → Run 'main' (убедись, что `src/` отмечен как Sources Root).

---

## Как пользоваться

1. Напиши боту `/start`
2. Зайди на **ss.ge** или **myhome.ge**, настрой фильтры и нажми «Найти»
3. Скопируй URL из адресной строки и пришли боту
4. Выбери интервал проверки (20–60 минут)
5. Бот начнёт присылать новые объявления

### Меню (команда `/menu`)

| Кнопка | Что делает |
|---|---|
| ➕ Добавить сайт | Добавить второй фильтр (ss.ge или myhome.ge) |
| ✏️ Отредактировать ссылку | Заменить фильтр на новый |
| ⭐ Избранное | Список сохранённых квартир |
| 🔄 Последние объявления | Забрать всё, что опубликовано за последние 1/3/6/12/24 часа по выбранному фильтру |
| ⏸ Приостановить | Временно остановить бота |
| 🕐 Изменить рабочее окно | Часы активности по Тбилиси |
| 📝 Заметка разработчику | Сообщить о проблеме |

### Кнопки под каждым объявлением

| Кнопка | Что делает |
|---|---|
| ⭐ В избранное | Сохранить квартиру |
| ☰ Меню | Открыть меню |
| 🗑 Удалить из чата | Убрать объявление (вместе с фото/картой) из чата |
| 🚫 Убрать из выдачи | Скрыть группу дублей (только ss.ge) |

---

## Как работает под капотом

- **Парсинг без браузера** — оба сайта работают на Next.js и отдают все данные объявлений внутри HTML-страницы (`__NEXT_DATA__`). Для их извлечения достаточно обычного `requests.get()`, без Selenium или Playwright.
- **Планировщик** — проверяет сайты с рандомизированным интервалом внутри выбранного диапазона. Раз в минуту "тикает" и смотрит, у кого из подписок наступило время следующей проверки.
- **Дедупликация** — для ss.ge использует родной признак дублей (`similarityGroup`), для myhome.ge — эвристику по адресу + площади (±6 м²) + этажу.
- **Карта** — для myhome.ge координаты приходят прямо с сайта; для ss.ge берутся из справочника улиц по `streetId`, с текстовым фоллбэком, если лукап по ID не дал результата. Карта отправляется через Telegram Location — интерактивный виджет прямо в чате. Если координат не нашлось вообще ни одним из способов — вместо карты используется ссылка на поиск в Google Maps.
- **Последние объявления** — фильтрация идёт по собственной дате публикации объявления (`orderDate` у ss.ge, `last_updated` у myhome.ge), данные забираются заново в момент запроса, а не из кэша обычного расписания.
- **Автоудаление** — все сообщения бота (кроме избранного) удаляются через 3 суток. Это делает cleanup-задача, которая запускается раз в час. Экраны навигации (меню, промежуточные шаги сценариев) удаляются сразу же, как только на смену им приходит следующий экран.

---

## Структура проекта

```
rental-listings-bot/
├── src/
│   ├── main.py               # Точка входа
│   ├── config.py             # Настройки из .env
│   ├── logger.py             # Логирование
│   ├── fetcher.py            # HTTP с retry и throttling
│   ├── db/                   # База данных (SQLite)
│   ├── parsers/              # Парсеры ss.ge и myhome.ge
│   ├── dedup/                # Дедупликация объявлений
│   ├── scheduler/            # Планировщик и автоудаление
│   ├── streets/              # Справочник улиц Тбилиси
│   ├── utils/                # Утилиты (время, карта)
│   └── bot/                  # Telegram-бот (handlers, FSM, клавиатуры)
├── tests/                    # Тесты
├── .env.example
├── requirements.txt
└── README.md
```

---

## Требования к системе

| Зависимость | Версия |
|---|---|
| Python | 3.10+ |
| aiogram | 3.4.1 |
| APScheduler | 3.10.4 |
| requests | 2.31.0 |
| beautifulsoup4 | 4.12.2 |
| python-dotenv | 1.0.0 |

---

## Бэклог

- Показать более дешёвые дубли объявления (API ss.ge требует авторизации, пока недоступно)
- Подсветка линии улицы на карте вместо точки
- Показ номера телефона арендодателя
- Кросс-сайтовая дедупликация (ss.ge ↔ myhome.ge)