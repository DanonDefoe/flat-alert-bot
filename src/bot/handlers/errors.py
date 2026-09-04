"""
Глобальный обработчик ошибок. Ловит всё, что не поймали локально сами
handlers (все существующие handlers уже ловят свои ожидаемые исключения —
FetchError, ValueError, link_common.*Error — это сеть на непредвиденное).

Регистрируется в main.py через dp.include_router(errors.router) — должен
быть последним подключённым роутером, чтобы не перехватывать исключения,
которые предназначены для обработки в других местах (aiogram сам следит за
порядком: @router.errors() ловит то, что "просочилось" через все handlers).

Что делает при необработанной ошибке:
  1. Логирует полный traceback.
  2. Отвечает пользователю нейтральным сообщением (best-effort — если и это
     не получится отправить, просто логирует ещё раз, не роняет бота).
  3. Если задан DEVELOPER_TELEGRAM_ID — отправляет туда traceback,
     чтобы узнать о проблеме сразу, а не искать её в логах постфактум.

Особый случай — TelegramForbiddenError (пользователь заблокировал бота или
удалил чат): это не баг бота, отвечать/уведомлять разработчика не нужно,
просто тихо логируем на уровне INFO и выходим.
"""

from __future__ import annotations

import html
import logging
import traceback

from aiogram import Router, Bot
from aiogram.exceptions import TelegramForbiddenError
from aiogram.types import ErrorEvent

from config import settings
from bot import message_tracker

logger = logging.getLogger(__name__)

router = Router(name="errors")

GENERIC_ERROR_TEXT = (
    "Что-то пошло не так на стороне бота. Попробуй ещё раз чуть позже — "
    "если повторится, напиши через меню «Фидбек разработчику»"
)

# Ограничение на длину traceback, отправляемого разработчику. Telegram режет
# сообщения на 4096 символов, а после html.escape() текст ещё немного вырастет
# (& -> &amp; и т.д.) — берём с запасом, не впритык к лимиту.
MAX_TRACEBACK_CHARS = 2500


@router.errors()
async def global_error_handler(event: ErrorEvent, bot: Bot, db_conn) -> None:
    exception = event.exception
    update = event.update

    if isinstance(exception, TelegramForbiddenError):
        # Пользователь заблокировал бота / удалил чат — не баг, ответить и
        # не получится, уведомлять разработчика не о чем.
        logger.info("Бот заблокирован или чат недоступен: %s", exception)
        return

    chat_id = _extract_chat_id(update)

    logger.error(
        "Необработанная ошибка при обработке update %s (chat_id=%s): %s",
        getattr(update, "update_id", "?"), chat_id, exception,
        exc_info=exception,
    )

    if chat_id is not None:
        try:
            sent = await bot.send_message(chat_id, GENERIC_ERROR_TEXT)
            message_tracker.track(db_conn, sent)
        except Exception as notify_err:
            # Не поднимаем дальше — мы уже в обработчике ошибок, поднимать
            # ошибку из обработчика ошибок было бы иронично и бесполезно.
            logger.warning("Не удалось уведомить пользователя об ошибке: %s", notify_err)

    await _notify_developer_about_error(bot, exception, update, chat_id)


def _extract_chat_id(update) -> int | None:
    """update — aiogram Update, может прийти от Message, CallbackQuery и
    других типов апдейтов. Пробуем достать chat_id известными путями,
    молча возвращаем None, если не получилось (например, update вообще
    без чата — такое бывает у некоторых служебных апдейтов)."""
    message = getattr(update, "message", None)
    if message is not None:
        return message.chat.id

    callback_query = getattr(update, "callback_query", None)
    if callback_query is not None and callback_query.message is not None:
        return callback_query.message.chat.id

    return None


async def _notify_developer_about_error(bot: Bot, exception: Exception, update, chat_id: int | None) -> None:
    if settings.developer_telegram_id is None:
        return

    tb_full = "".join(traceback.format_exception(type(exception), exception, exception.__traceback__))
    tb_trimmed = tb_full[-MAX_TRACEBACK_CHARS:]
    tb_escaped = html.escape(tb_trimmed)

    text = (
        f"⚠️ <b>Необработанная ошибка в боте</b>\n"
        f"chat_id: {chat_id}\n"
        f"update_id: {getattr(update, 'update_id', '?')}\n\n"
        f"<pre>{tb_escaped}</pre>"
    )

    try:
        await bot.send_message(settings.developer_telegram_id, text, parse_mode="HTML")
    except Exception as e:
        logger.warning("Не удалось отправить traceback разработчику: %s", e)