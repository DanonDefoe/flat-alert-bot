"""
Модуль дедупликации.

Логика (см. architecture_and_plan.md, раздел 4):
  - ss.ge: первичный сигнал — поле `duplicate_group_id` (это Listing.duplicate_group_id,
    заполняется из similarityGroup в parsers_poc.py). Если у нового объявления есть
    duplicate_group_id, и среди УЖЕ ПОКАЗАННЫХ в рамках этой же подписки есть объявление
    с тем же duplicate_group_id — новое помечается дублем того объявления.
  - Фоллбэк (используется всегда для myhome, и для ss.ge когда duplicate_group_id пуст):
    эвристика — улица (сырой текст, точное совпадение) + площадь (±6 м) + этаж (точное
    совпадение) + кровати/комнаты (точное совпадение, ТОЛЬКО если поле есть у обеих
    сторон — отсутствие поля не блокирует совпадение).
  - Цена НЕ участвует ни в одном из сравнений — сознательное решение (см. architecture doc).
  - Кросс-сайтовый дедуп (ss.ge <-> myhome.ge) НЕ делается вообще.

Важно: дедуп всегда идёт в рамках ОДНОЙ подписки (subscription_id), не глобально —
у разных пользователей с похожими фильтрами независимые списки "уже показанного".
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Optional

from src.db import db
from parsers.base import Listing

AREA_TOLERANCE_SQM = 6


@dataclass
class DedupResult:
    listing: Listing
    is_duplicate: bool
    duplicate_of_native_id: Optional[str]  # native_id объявления-оригинала, если is_duplicate=True


def is_already_seen(conn: sqlite3.Connection, subscription_id: int, native_id: str) -> bool:
    """True, если это объявление уже показывали в рамках этой подписки раньше —
    такие полностью пропускаем, это не про дубли, это про "уже отправляли"."""
    cur = conn.execute(
        "SELECT 1 FROM seen_listings WHERE subscription_id = ? AND native_id = ?",
        (subscription_id, native_id),
    )
    return cur.fetchone() is not None


def _find_duplicate_by_group(
    conn: sqlite3.Connection, subscription_id: int, listing: Listing
) -> Optional[str]:
    """ss.ge: поиск среди уже показанных объявлений с тем же duplicate_group_id."""
    if not listing.duplicate_group_id:
        return None
    cur = conn.execute(
        """
        SELECT native_id FROM seen_listings
        WHERE subscription_id = ? AND duplicate_group_id = ? AND native_id != ?
        ORDER BY first_seen_at ASC
        LIMIT 1
        """,
        (subscription_id, listing.duplicate_group_id, listing.native_id),
    )
    row = cur.fetchone()
    return row["native_id"] if row else None


def _find_duplicate_by_heuristic(
    conn: sqlite3.Connection, subscription_id: int, listing: Listing
) -> Optional[str]:
    """Эвристика: улица (точный текст) + этаж (точное совпадение) в SQL,
    площадь (±6м) и кровати/комнаты (если есть с обеих сторон) — уже в Python,
    т.к. это не сводится к простому равенству в SQL-запросе."""
    if not listing.street_raw or listing.area_sqm is None:
        return None

    cur = conn.execute(
        """
        SELECT native_id, area_sqm, rooms_or_beds FROM seen_listings
        WHERE subscription_id = ? AND street_raw = ? AND floor = ? AND native_id != ?
        """,
        (subscription_id, listing.street_raw, listing.floor, listing.native_id),
    )
    for row in cur.fetchall():
        if row["area_sqm"] is None:
            continue
        if abs(row["area_sqm"] - listing.area_sqm) > AREA_TOLERANCE_SQM:
            continue
        # Кровати/комнаты сравниваем, только если поле известно с ОБЕИХ сторон.
        # Если хотя бы с одной стороны None — не блокируем совпадение этим полем.
        if listing.rooms_or_beds is not None and row["rooms_or_beds"] is not None:
            if listing.rooms_or_beds != row["rooms_or_beds"]:
                continue
        return row["native_id"]
    return None


def find_duplicate(conn: sqlite3.Connection, subscription_id: int, listing: Listing) -> Optional[str]:
    """Главная точка входа: пробует native-сигнал (ss.ge), потом эвристику."""
    if listing.site == "ss_ge":
        native_match = _find_duplicate_by_group(conn, subscription_id, listing)
        if native_match:
            return native_match
        # duplicate_group_id может отсутствовать у самого объявления (similarityGroup=null),
        # но эвристика всё равно может найти совпадение — используем как фоллбэк.
        return _find_duplicate_by_heuristic(conn, subscription_id, listing)

    # myhome.ge — только эвристика
    return _find_duplicate_by_heuristic(conn, subscription_id, listing)


def record_seen(conn: sqlite3.Connection, subscription_id: int, listing: Listing) -> None:
    conn.execute(
        """
        INSERT OR IGNORE INTO seen_listings
            (subscription_id, native_id, street_id, street_raw, area_sqm, floor,
             rooms_or_beds, duplicate_group_id, url, price_usd, price_gel)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            subscription_id,
            listing.native_id,
            listing.street_id,
            listing.street_raw,
            listing.area_sqm,
            listing.floor,
            listing.rooms_or_beds,
            listing.duplicate_group_id,
            listing.url,
            listing.price_usd,
            listing.price_gel,
        ),
    )
    conn.commit()


def process_new_listings(
    conn: sqlite3.Connection, subscription_id: int, listings: list[Listing]
) -> list[DedupResult]:
    """
    Главная функция, которую вызывает планировщик после парсинга.

    Возвращает только ГЕНУИННО новые объявления (которых раньше не было в
    seen_listings для этой подписки) — уже с проставленным флагом дубля.
    Уже показанные (native_id повторно встретился) полностью отбрасываются,
    их не нужно ни возвращать, ни повторно записывать.

    Побочный эффект: каждое новое объявление сразу записывается в seen_listings —
    чтобы дубли внутри одного и того же батча (если два новых объявления в одном
    цикле — дубли друг друга) тоже ловились корректно.
    """
    results: list[DedupResult] = []
    for listing in listings:
        if is_already_seen(conn, subscription_id, listing.native_id):
            continue

        duplicate_of = find_duplicate(conn, subscription_id, listing)
        record_seen(conn, subscription_id, listing)

        results.append(DedupResult(
            listing=listing,
            is_duplicate=duplicate_of is not None,
            duplicate_of_native_id=duplicate_of,
        ))
    return results


def filter_excluded_groups(
    conn: sqlite3.Connection, subscription_id: int, results: list[DedupResult]
) -> list[DedupResult]:
    """
    Фича "Убрать из выдачи": вызывается ПОСЛЕ process_new_listings, ПЕРЕД
    отправкой в Telegram. Убирает из списка все объявления, чей
    duplicate_group_id пользователь ранее исключил кнопкой под сообщением.

    Важно: process_new_listings() уже записал эти объявления в seen_listings
    (иначе при следующей проверке они снова считались бы "новыми" и опять
    попадали бы в этот фильтр — лишняя, но не критичная работа). Здесь мы
    только решаем, ЧТО реально уйдёт пользователю в Telegram.

    Действует независимо от флага is_duplicate — если группа исключена, то и
    самое первое новое объявление этой группы (ещё не помеченное дублем)
    тоже не отправляется, а не только последующие копии.
    """
    return [
        r for r in results
        if not db.is_group_excluded(conn, subscription_id, r.listing.duplicate_group_id)
    ]