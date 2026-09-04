"""
Планировщик — используется один периодический "тик" (раз в TICK_INTERVAL_SEC),
который на каждом тике спрашивает БД: db.get_due_subscriptions() какие подписки
пора проверить.

Это проще в реализации и тестировании, не требует ручного управления жизненным
циклом job'ов в APScheduler, и даёт тот же результат: каждая подписка
проверяется примерно так часто, как задано её interval_min_sec/max_sec.
Цена — гранулярность проверки "пора ли" не точнее TICK_INTERVAL_SEC (обычно
60 сек), что для интервалов в 20+ минут совершенно не критично.

Один тик обрабатывает все due-подписки последовательно (не параллельно) —
это заодно естественным образом соблюдает троттлинг из fetcher.py (там уже
есть минимальный зазор между запросами к одному домену), не даёт нескольким
подпискам на один сайт одновременно долбить его запросами.
"""

from __future__ import annotations

import asyncio
import logging
import random
import sqlite3
from datetime import datetime, time, timedelta

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from scheduler import cleanup
from db import db
from dedup import dedup
from utils import time_utils
from fetcher import fetch_html, FetchError
from parsers.ss_ge import parse_ss_ge_list
from parsers.myhome_ge import parse_myhome_list
from bot.handlers import listing

logger = logging.getLogger(__name__)

# Как часто "тикаем" и спрашиваем БД, какие подписки пора проверить.
# Не путать с интервалом самой подписки (20-60 минут) — это только
# гранулярность опроса, должна быть заметно меньше минимального интервала.
TICK_INTERVAL_SEC = 60

# Случайный сдвиг при переносе на начало следующего рабочего окна — чтобы
# все подписки, упёршиеся в закрытие окна одновременно, не проснулись
# ровно в одну и ту же секунду в момент открытия (см. architecture_and_plan.md,
# раздел 7).
WINDOW_START_JITTER_MAX_MIN = 15

_DATETIME_FORMAT = "%Y-%m-%d %H:%M:%S"  # совместим с SQLite datetime('now')


def _now_utc_str() -> str:
    return datetime.utcnow().strftime(_DATETIME_FORMAT)


# ---------------------------------------------------------------------------
# Чистая логика вычисления next_check_at — без сети и БД, легко тестируется
# ---------------------------------------------------------------------------
def _within_work_hours(t: time, start: time, end: time) -> bool:
    """Учитывает окно, переходящее через полночь (start > end, например
    18:00-02:00) — такое возможно после конвертации тбилисского времени
    в UTC (см. time_utils.py)."""
    if start <= end:
        return start <= t <= end
    return t >= start or t <= end


def _next_window_start_datetime(after: datetime, work_start: time) -> datetime:
    """Ближайший момент времени СТРОГО ПОСЛЕ `after`, когда наступает
    work_start (сегодня, если ещё не наступил, иначе завтра)."""
    candidate = datetime.combine(after.date(), work_start)
    if candidate <= after:
        candidate += timedelta(days=1)
    return candidate


def compute_next_check_at(
        interval_min_sec: int,
        interval_max_sec: int,
        work_start: time,
        work_end: time,
        now: datetime,
) -> datetime:
    """
    Основная функция расписания. Берёт случайный интервал в заданных
    границах; если результат попадает вне рабочего окна пользователя —
    переносит на начало следующего окна + случайный джиттер (см. докстринг
    WINDOW_START_JITTER_MAX_MIN и architecture_and_plan.md, раздел 7).
    """
    interval_sec = random.randint(interval_min_sec, interval_max_sec)
    candidate = now + timedelta(seconds=interval_sec)

    if _within_work_hours(candidate.time(), work_start, work_end):
        return candidate

    window_start = _next_window_start_datetime(candidate, work_start)
    jitter_sec = random.randint(0, WINDOW_START_JITTER_MAX_MIN * 60)
    return window_start + timedelta(seconds=jitter_sec)


# ---------------------------------------------------------------------------
# Обработка одной подписки
# ---------------------------------------------------------------------------
async def process_subscription(
        bot: Bot,
        db_conn: sqlite3.Connection,
        session,
        subscription: sqlite3.Row,
) -> None:
    """
    Полный цикл для одной подписки: fetch -> parse -> dedup -> filter ->
    deliver -> mark_checked. Любая ошибка на любом шаге логируется и НЕ
    прерывает работу планировщика — next_check_at всё равно проставляется
    (иначе сломанная подписка будет запрашиваться на КАЖДОМ следующем тике,
    без всякой паузы, вместо нормального интервала — это уже было бы похоже
    на DDoS сайта нашими же руками при систематической ошибке).
    """
    subscription_id = subscription["id"]
    site = subscription["site"]
    url = subscription["filter_url"]
    user_id = subscription["user_id"]

    now = datetime.utcnow()

    user = db.get_user(db_conn, user_id)
    work_start = time_utils.parse_hh_mm(user["work_hours_start_utc"])
    work_end = time_utils.parse_hh_mm(user["work_hours_end_utc"])

    listings = None
    try:
        html = await asyncio.to_thread(fetch_html, session, url)
        listings = parse_ss_ge_list(html) if site == "ss_ge" else parse_myhome_list(html)
    except FetchError as e:
        logger.warning(
            "Подписка %s (%s): сетевая ошибка, пропускаю цикл: %s", subscription_id, site, e
        )
    except ValueError as e:
        # __NEXT_DATA__ не найден / структура не та — вёрстка сайта изменилась.
        # Громче, чем сетевая ошибка — это не временный сбой, а сигнал, что
        # парсер нужно чинить.
        logger.error(
            "Подписка %s (%s): ошибка парсинга (верстка сайта изменилась?): %s",
            subscription_id, site, e,
        )

    if listings is not None:
        is_first_run = subscription["last_checked_at"] is None

        results = dedup.process_new_listings(db_conn, subscription_id, listings)
        results = dedup.filter_excluded_groups(db_conn, subscription_id, results)

        if is_first_run:
            # Первый запуск подписки: все текущие объявления по фильтру уже
            # записаны в seen_listings через process_new_listings() выше, но
            # отправлять их не нужно — пользователь увидит только то, что
            # появится ПОСЛЕ добавления подписки. Иначе при первой проверке
            # приходил бы весь текущий список по фильтру (20-40 объявлений
            # пачкой), что неудобно и не соответствует ожиданию "новые объявления".
            logger.info(
                "Подписка %s (%s): первый запуск, %d объявлений запомнено без отправки",
                subscription_id, site, len(results),
            )
        elif results:
            logger.info(
                "Подписка %s (%s): %d новых объявлений к отправке",
                subscription_id, site, len(results),
            )
            await listing.deliver_new_listings(
                bot, chat_id=user_id, subscription_id=subscription_id, results=results, db_conn=db_conn,
            )

    next_check_at = compute_next_check_at(
        subscription["interval_min_sec"],
        subscription["interval_max_sec"],
        work_start,
        work_end,
        now,
    )

    db.mark_checked(
        db_conn,
        subscription_id,
        checked_at_iso=now.strftime(_DATETIME_FORMAT),
        next_check_at_iso=next_check_at.strftime(_DATETIME_FORMAT),
    )


# ---------------------------------------------------------------------------
# Тик планировщика
# ---------------------------------------------------------------------------
async def tick(bot: Bot, db_conn: sqlite3.Connection, session) -> None:
    now_str = _now_utc_str()
    due = db.get_due_subscriptions(db_conn, now_str)

    if not due:
        return

    logger.info("Тик планировщика: %d подписок к проверке", len(due))

    for subscription in due:
        try:
            await process_subscription(bot, db_conn, session, subscription)
        except Exception as e:
            # Одна сломанная подписка не должна останавливать обработку
            # остальных в этом же тике — логируем и идём дальше.
            logger.exception(
                "Необработанная ошибка при обработке подписки %s: %s",
                subscription["id"], e,
            )


def setup_scheduler(bot: Bot, db_conn: sqlite3.Connection, session) -> AsyncIOScheduler:
    """Вызывается из main.py. Возвращает НЕ запущенный scheduler —
    scheduler.start() вызывается в main.py, чтобы жизненный цикл (start/
    shutdown) был виден и управлялся в одном месте, а не спрятан здесь."""
    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(
        tick,
        trigger="interval",
        seconds=TICK_INTERVAL_SEC,
        args=[bot, db_conn, session],
        next_run_time=datetime.utcnow(),  # первый тик сразу при старте, не через минуту ожидания
        id="main_tick",
    )
    scheduler.add_job(
        cleanup.cleanup_old_messages,
        trigger="interval",
        seconds=cleanup.CLEANUP_INTERVAL_SEC,
        args=[bot, db_conn],
        id="cleanup_old_messages",
        # Без next_run_time=now — автоудаление не срочное, первый прогон через
        # час после старта достаточен (нечего чистить в первый час жизни бота).
    )
    return scheduler
