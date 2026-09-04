"""
Автоудаление сообщений бота старше 3 суток (кроме сообщений из списка
"⭐ Избранное" — см. message_tracker.py, db_schema.sql: is_favorite=1
исключены из выборки в db.get_stale_messages()).

Отдельный периодический job (см. jobs.py:setup_scheduler), не совмещён с
основным tick() планировщика — разная частота имеет смысл: проверять due-
подписки нужно часто (раз в минуту), а искать сообщения старше 3 суток
достаточно раз в час, гранулярность в минуты тут значения не имеет.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError

from db import db

logger = logging.getLogger(__name__)

MESSAGE_TTL_DAYS = 2
CLEANUP_INTERVAL_SEC = 3600  # Можно уменьшить, если удалять нужно быстрее, чем раз в час.

_DATETIME_FORMAT = "%Y-%m-%d %H:%M:%S"  # совместим с SQLite datetime('now')


async def cleanup_old_messages(bot: Bot, db_conn) -> None:
    cutoff = (datetime.utcnow() - timedelta(days=MESSAGE_TTL_DAYS)).strftime(_DATETIME_FORMAT)
    stale = db.get_stale_messages(db_conn, cutoff)

    if not stale:
        return

    logger.info("Автоудаление: %d сообщений старше %d суток", len(stale), MESSAGE_TTL_DAYS)

    for record in stale:
        try:
            await bot.delete_message(chat_id=record["chat_id"], message_id=record["message_id"])
        except TelegramForbiddenError:
            # Бот заблокирован/удалён из чата — сообщение всё равно недостижимо,
            # снимаем с учёта ниже как обычно, отдельно ничего не делаем.
            pass
        except TelegramBadRequest as e:
            # Частые легитимные причины: юзер уже удалил сообщение вручную,
            # либо Telegram отказывает в удалении слишком старых сообщений
            # (у некоторых типов чатов есть отдельный лимит ~48ч на удаление
            # чужих/старых сообщений даже для ботов) — не ошибка НАШЕЙ логики.
            logger.debug(
                "Не удалось удалить сообщение %s в чате %s: %s",
                record["message_id"], record["chat_id"], e,
            )
        finally:
            # Снимаем с учёта в любом случае — не ретраим бесконечно одно и то
            # же сообщение, если Telegram стабильно отказывается его удалять
            # (иначе один такой случай засорял бы каждый следующий cleanup-тик).
            db.delete_sent_message_record(db_conn, record["id"])