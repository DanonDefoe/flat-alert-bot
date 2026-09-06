"""
Единая точка показа главного меню. Гарантирует, что в чате одновременно
открыто НЕ БОЛЕЕ ОДНОГО "окна меню" (как в stock-alert-bot, на который
ссылался пользователь): при показе нового меню предыдущее — если оно ещё
не было убрано пользователем вручную — удаляется.

Используется вместо того, чтобы каждый файл (commands.py, start.py, menu.py)
слал main_menu_keyboard() по отдельности — было 3 копии одной и той же
логики (создать/обновить), теперь одна.
"""

from __future__ import annotations

import logging

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest

from db import db
from bot import keyboards
from bot import messages
from bot import message_tracker

logger = logging.getLogger(__name__)


async def show_menu(bot: Bot, db_conn, chat_id: int, text: str = messages.MENU_TITLE) -> None:
    """
    text — заголовок сообщения с меню. По умолчанию просто "Меню:", но
    некоторые вызывающие места хотят совместить меню с коротким
    подтверждением действия (например, "Отлично, буду присылать новые
    объявления по твоим фильтрам!") в одном сообщении — тогда передают
    свой текст вместо дефолтного.
    """
    user = db.get_user(db_conn, chat_id)
    is_paused = bool(user["is_paused"]) if user else False

    if user and user["last_menu_message_id"]:
        try:
            await bot.delete_message(chat_id=chat_id, message_id=user["last_menu_message_id"])
        except TelegramBadRequest as e:
            # Юзер мог уже сам удалить старое меню вручную, или оно старше
            # 48ч (лимит Telegram на удаление) — не страшно, просто логируем.
            logger.debug("Не удалось удалить предыдущее окно меню (chat_id=%s): %s", chat_id, e)

    sent = await bot.send_message(
        chat_id=chat_id, text=text, reply_markup=keyboards.main_menu_keyboard(is_paused=is_paused),
    )
    message_tracker.track(db_conn, sent)
    db.set_last_menu_message_id(db_conn, chat_id, sent.message_id)

