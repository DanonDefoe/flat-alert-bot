"""
Обёртка над sqlite3 для проекта. Без ORM — простые функции, каждая делает
одну понятную вещь. Это осознанный выбор под уровень проекта: 3-10
пользователей, несложные запросы, не нужен вес SQLAlchemy.

Требуется: только стандартная библиотека (sqlite3 встроен в Python).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional


SCHEMA_PATH = Path(__file__).parent / "db_schema.sql"


def get_connection(db_path: str = "bot.db") -> sqlite3.Connection:
    """Открыть соединение с БД. row_factory=Row — доступ к полям по имени."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    """Создать таблицы, если их ещё нет. Безопасно вызывать многократно.

    Также подчищает НОВЫЕ КОЛОНКИ на уже существующих таблицах — в отличие от
    CREATE TABLE IF NOT EXISTS (который решает только новые таблицы), уже
    развёрнутая БД никак не получит колонку, добавленную в схему уже ПОСЛЕ
    первого создания таблицы (см. _ensure_column ниже). Раньше эта проблема
    закрывалась вручную (ALTER TABLE или удаление bot.db) на каждое такое
    изменение схемы — начиная с last_menu_message_id, это делается
    автоматически при каждом старте."""
    schema_sql = SCHEMA_PATH.read_text(encoding="utf-8")
    conn.executescript(schema_sql)
    conn.commit()

    _ensure_column(conn, "users", "last_menu_message_id", "INTEGER")


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, sql_type: str) -> None:
    """Добавить колонку, если её ещё нет в таблице. SQLite не поддерживает
    'ALTER TABLE ... ADD COLUMN IF NOT EXISTS' напрямую — проверяем через
    PRAGMA table_info() и добавляем только при реальном отсутствии."""
    existing_columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in existing_columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {sql_type}")
        conn.commit()


# ---------------------------------------------------------------------------
# users
# ---------------------------------------------------------------------------
def upsert_user(conn: sqlite3.Connection, telegram_id: int) -> None:
    """Создать пользователя, если его ещё нет. Ничего не делает, если уже есть."""
    conn.execute(
        "INSERT OR IGNORE INTO users (telegram_id) VALUES (?)",
        (telegram_id,),
    )
    conn.commit()


def set_paused(conn: sqlite3.Connection, telegram_id: int, is_paused: bool) -> None:
    conn.execute(
        "UPDATE users SET is_paused = ? WHERE telegram_id = ?",
        (int(is_paused), telegram_id),
    )
    conn.commit()


def get_user(conn: sqlite3.Connection, telegram_id: int) -> Optional[sqlite3.Row]:
    cur = conn.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,))
    return cur.fetchone()


def set_work_hours_utc(conn: sqlite3.Connection, telegram_id: int, start_utc: str, end_utc: str) -> None:
    """start_utc/end_utc в формате 'HH:MM'. Конвертация из тбилисского времени (UTC+4)
    делается ДО вызова этой функции, на стороне бота (см. architecture_and_plan.md)."""
    conn.execute(
        "UPDATE users SET work_hours_start_utc = ?, work_hours_end_utc = ? WHERE telegram_id = ?",
        (start_utc, end_utc, telegram_id),
    )
    conn.commit()


def set_last_menu_message_id(conn: sqlite3.Connection, telegram_id: int, message_id: int | None) -> None:
    """message_id последнего показанного окна меню — см. menu_view.py.
    None допустим (например, после удаления/сбоя), если нужно сбросить."""
    conn.execute(
        "UPDATE users SET last_menu_message_id = ? WHERE telegram_id = ?",
        (message_id, telegram_id),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# subscriptions
# ---------------------------------------------------------------------------
def add_subscription(
    conn: sqlite3.Connection,
    user_id: int,
    site: str,
    filter_url: str,
    interval_min_sec: int,
    interval_max_sec: int,
) -> int:
    cur = conn.execute(
        """
        INSERT INTO subscriptions (user_id, site, filter_url, interval_min_sec, interval_max_sec)
        VALUES (?, ?, ?, ?, ?)
        """,
        (user_id, site, filter_url, interval_min_sec, interval_max_sec),
    )
    conn.commit()
    return cur.lastrowid


def update_subscription_url(conn: sqlite3.Connection, subscription_id: int, new_url: str) -> None:
    conn.execute(
        "UPDATE subscriptions SET filter_url = ? WHERE id = ?",
        (new_url, subscription_id),
    )
    conn.commit()


def clear_seen_listings(conn: sqlite3.Connection, subscription_id: int) -> None:
    """Удалить всю историю seen_listings для подписки — вызывается при
    редактировании ссылки: старые записи относятся к прошлому фильтру и
    бесполезны (а иногда вредны) как база сравнения для нового."""
    conn.execute("DELETE FROM seen_listings WHERE subscription_id = ?", (subscription_id,))
    conn.commit()


def reset_subscription_schedule(conn: sqlite3.Connection, subscription_id: int) -> None:
    """Сбросить last_checked_at/next_check_at в NULL — заставляет планировщик
    (jobs.py:process_subscription) обработать следующую проверку этой подписки
    как 'первый запуск': текущие объявления по НОВОМУ фильтру будут молча
    записаны в seen_listings, но не отправлены (см. jobs.py) — та же логика,
    что уже применяется к реально новым подпискам."""
    conn.execute(
        "UPDATE subscriptions SET last_checked_at = NULL, next_check_at = NULL WHERE id = ?",
        (subscription_id,),
    )
    conn.commit()


def get_subscriptions_for_user(conn: sqlite3.Connection, user_id: int) -> list[sqlite3.Row]:
    cur = conn.execute(
        "SELECT * FROM subscriptions WHERE user_id = ? AND is_active = 1",
        (user_id,),
    )
    return cur.fetchall()


def subscription_exists(
    conn: sqlite3.Connection,
    user_id: int,
    site: str,
    filter_url: str,
    exclude_subscription_id: Optional[int] = None,
) -> bool:
    """True, если у пользователя уже есть активная подписка на этот же
    site+filter_url. exclude_subscription_id — исключить конкретную подписку
    из проверки (нужно при редактировании: сравнение новой ссылки с ДРУГИМИ
    подписками юзера, а не с самой собой)."""
    query = (
        "SELECT 1 FROM subscriptions "
        "WHERE user_id = ? AND site = ? AND filter_url = ? AND is_active = 1"
    )
    params: list = [user_id, site, filter_url]
    if exclude_subscription_id is not None:
        query += " AND id != ?"
        params.append(exclude_subscription_id)

    cur = conn.execute(query, params)
    return cur.fetchone() is not None


def get_subscription(conn: sqlite3.Connection, subscription_id: int) -> Optional[sqlite3.Row]:
    cur = conn.execute("SELECT * FROM subscriptions WHERE id = ?", (subscription_id,))
    return cur.fetchone()


def get_due_subscriptions(conn: sqlite3.Connection, now_iso: str) -> list[sqlite3.Row]:
    """Подписки, у которых next_check_at уже наступил (или ещё не выставлен)."""
    cur = conn.execute(
        """
        SELECT s.* FROM subscriptions s
        JOIN users u ON u.telegram_id = s.user_id
        WHERE s.is_active = 1
          AND u.is_paused = 0
          AND (s.next_check_at IS NULL OR s.next_check_at <= ?)
        """,
        (now_iso,),
    )
    return cur.fetchall()


def mark_checked(
    conn: sqlite3.Connection,
    subscription_id: int,
    checked_at_iso: str,
    next_check_at_iso: str,
) -> None:
    conn.execute(
        "UPDATE subscriptions SET last_checked_at = ?, next_check_at = ? WHERE id = ?",
        (checked_at_iso, next_check_at_iso, subscription_id),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# streets
# ---------------------------------------------------------------------------
def upsert_street(
    conn: sqlite3.Connection,
    street_id: int,
    latitude: Optional[float],
    longitude: Optional[float],
    title_rus: Optional[str],
    title_eng: Optional[str],
    title_geo: Optional[str],
) -> None:
    conn.execute(
        """
        INSERT INTO streets (street_id, latitude, longitude, title_rus, title_eng, title_geo)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(street_id) DO UPDATE SET
            latitude=excluded.latitude, longitude=excluded.longitude,
            title_rus=excluded.title_rus, title_eng=excluded.title_eng, title_geo=excluded.title_geo
        """,
        (street_id, latitude, longitude, title_rus, title_eng, title_geo),
    )
    conn.commit()


def get_street(conn: sqlite3.Connection, street_id: int) -> Optional[sqlite3.Row]:
    cur = conn.execute("SELECT * FROM streets WHERE street_id = ?", (street_id,))
    return cur.fetchone()


def get_street_by_title(conn: sqlite3.Connection, title: str) -> Optional[sqlite3.Row]:
    """Текстовый fallback-поиск улицы по названию (точное совпадение без
    учёта регистра/пробелов по краям), используется когда street_id
    отсутствует или lookup по нему не дал координат (см. map_utils.py).
    Ищет по всем трём языковым колонкам сразу — объявление может прислать
    название на любом из них. Требует непустых координат у найденной записи,
    иначе смысла в находке нет (см. вызывающий код в map_utils.py)."""
    normalized = title.strip().lower()
    cur = conn.execute(
        """
        SELECT * FROM streets
        WHERE (lower(title_rus) = ? OR lower(title_eng) = ? OR lower(title_geo) = ?)
          AND latitude IS NOT NULL AND longitude IS NOT NULL
        LIMIT 1
        """,
        (normalized, normalized, normalized),
    )
    return cur.fetchone()


# ---------------------------------------------------------------------------
# dev_notes
# ---------------------------------------------------------------------------
def add_dev_note(conn: sqlite3.Connection, user_id: int, text: str) -> None:
    conn.execute(
        "INSERT INTO dev_notes (user_id, text) VALUES (?, ?)",
        (user_id, text),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# excluded_groups — фича "Убрать из выдачи" (кнопка под дублем на ss.ge)
# ---------------------------------------------------------------------------
def exclude_group(conn: sqlite3.Connection, subscription_id: int, duplicate_group_id: str) -> None:
    """Пометить группу дублей как исключённую для этой подписки.
    Идемпотентно — повторный вызов на ту же пару ничего не ломает."""
    conn.execute(
        """
        INSERT OR IGNORE INTO excluded_groups (subscription_id, duplicate_group_id)
        VALUES (?, ?)
        """,
        (subscription_id, duplicate_group_id),
    )
    conn.commit()


def is_group_excluded(conn: sqlite3.Connection, subscription_id: int, duplicate_group_id: Optional[str]) -> bool:
    if not duplicate_group_id:
        return False
    cur = conn.execute(
        "SELECT 1 FROM excluded_groups WHERE subscription_id = ? AND duplicate_group_id = ?",
        (subscription_id, duplicate_group_id),
    )
    return cur.fetchone() is not None


def get_excluded_groups(conn: sqlite3.Connection, subscription_id: int) -> list[sqlite3.Row]:
    cur = conn.execute(
        "SELECT * FROM excluded_groups WHERE subscription_id = ? ORDER BY excluded_at DESC",
        (subscription_id,),
    )
    return cur.fetchall()


def get_seen_listing(conn: sqlite3.Connection, subscription_id: int, native_id: str) -> Optional[sqlite3.Row]:
    """Достать сохранённую карточку объявления по (subscription_id, native_id) —
    источник данных для 'Добавить в избранное' (см. favorites ниже): объявление
    уже гарантированно есть в seen_listings к моменту, когда юзер видит кнопку
    под ним (кнопка появляется только на уже отправленных объявлениях)."""
    cur = conn.execute(
        "SELECT * FROM seen_listings WHERE subscription_id = ? AND native_id = ?",
        (subscription_id, native_id),
    )
    return cur.fetchone()


# ---------------------------------------------------------------------------
# favorites — фича "Добавить в избранное"
# ---------------------------------------------------------------------------
def add_favorite(
    conn: sqlite3.Connection,
    user_id: int,
    site: str,
    native_id: str,
    street_raw: Optional[str],
    price_usd: Optional[float],
    price_gel: Optional[float],
    area_sqm: Optional[float],
    url: str,
) -> bool:
    """Возвращает True, если запись реально добавлена, False — если такое
    объявление у этого юзера уже было в избранном (UNIQUE (user_id, site,
    native_id) — тихо игнорируем повтор, а не падаем с ошибкой)."""
    cur = conn.execute(
        """
        INSERT OR IGNORE INTO favorites
            (user_id, site, native_id, street_raw, price_usd, price_gel, area_sqm, url)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (user_id, site, native_id, street_raw, price_usd, price_gel, area_sqm, url),
    )
    conn.commit()
    return cur.rowcount > 0


def get_favorites(conn: sqlite3.Connection, user_id: int) -> list[sqlite3.Row]:
    cur = conn.execute(
        "SELECT * FROM favorites WHERE user_id = ? ORDER BY added_at DESC",
        (user_id,),
    )
    return cur.fetchall()


def get_favorite(conn: sqlite3.Connection, favorite_id: int) -> Optional[sqlite3.Row]:
    cur = conn.execute("SELECT * FROM favorites WHERE id = ?", (favorite_id,))
    return cur.fetchone()


def remove_favorite(conn: sqlite3.Connection, favorite_id: int) -> None:
    conn.execute("DELETE FROM favorites WHERE id = ?", (favorite_id,))
    conn.commit()


# ---------------------------------------------------------------------------
# sent_messages — реестр отправленных ботом сообщений, для автоудаления
# через 3 суток (см. message_tracker.py и cleanup.py)
# ---------------------------------------------------------------------------
def track_sent_message(
    conn: sqlite3.Connection, chat_id: int, message_id: int, is_favorite: bool = False
) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO sent_messages (chat_id, message_id, is_favorite) VALUES (?, ?, ?)",
        (chat_id, message_id, int(is_favorite)),
    )
    conn.commit()


def get_stale_messages(conn: sqlite3.Connection, older_than_iso: str) -> list[sqlite3.Row]:
    """Сообщения старше указанного момента, НЕ помеченные как избранные
    (is_favorite=0 — записи из списка избранного не удаляются, см. cleanup.py)."""
    cur = conn.execute(
        "SELECT * FROM sent_messages WHERE is_favorite = 0 AND sent_at <= ?",
        (older_than_iso,),
    )
    return cur.fetchall()


def delete_sent_message_record(conn: sqlite3.Connection, record_id: int) -> None:
    conn.execute("DELETE FROM sent_messages WHERE id = ?", (record_id,))
    conn.commit()


# ---------------------------------------------------------------------------
# listing_deliveries — группировка сообщений одной доставки объявления,
# для кнопки "Удалить из чата" (см. handlers/listing.py)
# ---------------------------------------------------------------------------
def create_listing_delivery(conn: sqlite3.Connection, chat_id: int, message_ids: list[int]) -> int:
    cur = conn.execute(
        "INSERT INTO listing_deliveries (chat_id, message_ids) VALUES (?, ?)",
        (chat_id, ",".join(str(mid) for mid in message_ids)),
    )
    conn.commit()
    return cur.lastrowid


def get_listing_delivery(conn: sqlite3.Connection, delivery_id: int) -> Optional[sqlite3.Row]:
    cur = conn.execute("SELECT * FROM listing_deliveries WHERE id = ?", (delivery_id,))
    return cur.fetchone()


def delete_listing_delivery(conn: sqlite3.Connection, delivery_id: int) -> None:
    conn.execute("DELETE FROM listing_deliveries WHERE id = ?", (delivery_id,))
    conn.commit()
