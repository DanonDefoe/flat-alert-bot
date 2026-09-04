-- Схема БД. SQLite. Все временные метки — UTC, ISO-строки (datetime('now') в SQLite уже UTC).
-- Рабочее окно пользователя тоже хранится в UTC (конвертация из тбилисского времени
-- происходит в коде бота на этапе сохранения, а не здесь — см. architecture_and_plan.md).

CREATE TABLE IF NOT EXISTS users (
    telegram_id           INTEGER PRIMARY KEY,
    is_paused             INTEGER NOT NULL DEFAULT 0,   -- 0/1
    work_hours_start_utc  TEXT    NOT NULL DEFAULT '05:00',  -- "HH:MM"
    work_hours_end_utc    TEXT    NOT NULL DEFAULT '21:00',
    created_at            TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS subscriptions (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id           INTEGER NOT NULL REFERENCES users(telegram_id) ON DELETE CASCADE,
    site              TEXT    NOT NULL CHECK (site IN ('ss_ge', 'myhome_ge')),
    filter_url        TEXT    NOT NULL,
    interval_min_sec  INTEGER NOT NULL,
    interval_max_sec  INTEGER NOT NULL,
    is_active         INTEGER NOT NULL DEFAULT 1,
    last_checked_at   TEXT,             -- факт последней проверки
    next_check_at     TEXT,             -- план следующей проверки
    created_at        TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_subscriptions_user ON subscriptions(user_id);
CREATE INDEX IF NOT EXISTS idx_subscriptions_next_check ON subscriptions(next_check_at) WHERE is_active = 1;

-- Одна строка = одно объявление, увиденное в рамках конкретной подписки.
-- Хранит достаточно полей дедупа, чтобы не нужно было повторно парсить исходный listing.
-- url/price_usd/price_gel добавлены не для дедупа (там не участвуют), а чтобы
-- по (subscription_id, native_id) можно было восстановить полную карточку
-- объявления позже — используется фичей "Добавить в избранное" (см. favorites
-- ниже) и заодно устраняет более раннее ограничение _build_original_url()
-- в listing.py (там раньше не было точного URL оригинала дубля для ss.ge).
CREATE TABLE IF NOT EXISTS seen_listings (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    subscription_id     INTEGER NOT NULL REFERENCES subscriptions(id) ON DELETE CASCADE,
    native_id           TEXT    NOT NULL,   -- id объявления у источника (applicationId / id)
    street_id           INTEGER,             -- числовой id улицы у источника, если есть
    street_raw          TEXT,                -- сырой текст улицы (для эвристики/фоллбэка)
    area_sqm            REAL,
    floor               INTEGER,
    rooms_or_beds       INTEGER,             -- кровати (ss.ge) или комнаты (myhome), если есть
    duplicate_group_id  TEXT,                -- ss.ge: significant similarityGroup, иначе NULL
    url                 TEXT,                -- полный URL объявления у источника
    price_usd           REAL,
    price_gel           REAL,
    first_seen_at       TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE (subscription_id, native_id)
);

CREATE INDEX IF NOT EXISTS idx_seen_listings_sub ON seen_listings(subscription_id);
CREATE INDEX IF NOT EXISTS idx_seen_listings_group ON seen_listings(subscription_id, duplicate_group_id);
CREATE INDEX IF NOT EXISTS idx_seen_listings_heuristic
    ON seen_listings(subscription_id, street_raw, floor);

-- Статичный справочник улиц (заполняется один раз, вручную/скриптом импорта).
CREATE TABLE IF NOT EXISTS streets (
    street_id  INTEGER PRIMARY KEY,
    latitude   REAL,
    longitude  REAL,
    title_rus  TEXT,
    title_eng  TEXT,
    title_geo  TEXT
);

CREATE TABLE IF NOT EXISTS dev_notes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL REFERENCES users(telegram_id) ON DELETE CASCADE,
    text        TEXT    NOT NULL,
    created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- Группы дублей (ss.ge similarityGroup), которые пользователь исключил из выдачи
-- кнопкой "Убрать из выдачи" под объявлением. Скоуп — на подписку, не на юзера
-- целиком: у одного юзера может быть несколько подписок на ss.ge с разными
-- фильтрами, исключение в одной не должно молча влиять на другую.
CREATE TABLE IF NOT EXISTS excluded_groups (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    subscription_id     INTEGER NOT NULL REFERENCES subscriptions(id) ON DELETE CASCADE,
    duplicate_group_id  TEXT    NOT NULL,
    excluded_at         TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE (subscription_id, duplicate_group_id)
);

CREATE INDEX IF NOT EXISTS idx_excluded_groups_sub ON excluded_groups(subscription_id, duplicate_group_id);

-- Избранное. Денормализовано намеренно (не ссылается на seen_listings/subscriptions
-- по FK для отображения) — избранное должно пережить редактирование или удаление
-- подписки, из которой объявление изначально пришло; на момент добавления в
-- избранное все нужные для отображения поля копируются как есть.
CREATE TABLE IF NOT EXISTS favorites (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL REFERENCES users(telegram_id) ON DELETE CASCADE,
    site        TEXT    NOT NULL,
    native_id   TEXT    NOT NULL,
    street_raw  TEXT,
    price_usd   REAL,
    price_gel   REAL,
    area_sqm    REAL,
    url         TEXT    NOT NULL,
    added_at    TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE (user_id, site, native_id)
);

CREATE INDEX IF NOT EXISTS idx_favorites_user ON favorites(user_id);

-- Реестр отправленных ботом сообщений — для автоудаления через 3 суток
-- (см. message_tracker.py и cleanup.py). is_favorite=1 — записи из списка
-- избранного (см. handlers/menu.py:show_favorites) — они НЕ автоудаляются,
-- в остальном это обычные сообщения бота, подлежащие очистке.
CREATE TABLE IF NOT EXISTS sent_messages (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id      INTEGER NOT NULL,
    message_id   INTEGER NOT NULL,
    is_favorite  INTEGER NOT NULL DEFAULT 0,
    sent_at      TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE (chat_id, message_id)
);

CREATE INDEX IF NOT EXISTS idx_sent_messages_cleanup ON sent_messages(sent_at) WHERE is_favorite = 0;

-- Группировка сообщений ОДНОЙ доставки объявления (фото + карта, если были
-- отправлены раньше сообщения с кнопками) — нужна кнопке "Удалить из чата"
-- (см. handlers/listing.py), чтобы одним нажатием убрать все части
-- объявления, а не только то сообщение, где сама кнопка. Сообщение-носитель
-- кнопки сюда НЕ входит — оно не удаляется, а редактируется (edit_text) в
-- подтверждение, т.к. само по себе не может ссылаться на свой ещё
-- неизвестный message_id в момент создания клавиатуры (см. listing.py).
CREATE TABLE IF NOT EXISTS listing_deliveries (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id      INTEGER NOT NULL,
    message_ids  TEXT    NOT NULL,  -- через запятую, напр. "101,102,103"
    created_at   TEXT    NOT NULL DEFAULT (datetime('now'))
);
