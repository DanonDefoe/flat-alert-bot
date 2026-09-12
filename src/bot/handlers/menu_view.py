from __future__ import annotations

import logging

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import InlineKeyboardMarkup

from db import db
from bot import keyboards
from bot import messages
from bot import message_tracker

logger = logging.getLogger(__name__)


async def show_screen(
        bot: Bot, db_conn, chat_id: int, text: str, reply_markup: InlineKeyboardMarkup,
) -> None:
    """Показать произвольный "экран навигации" (текст + клавиатура), удалив
    перед этим предыдущий такой же отслеживаемый экран для этого чата, если
    он ещё жив. Это и есть тот самый общий механизм, которым пользуется
    show_menu() ниже — просто с произвольными text/reply_markup вместо
    зафиксированных MENU_TITLE/main_menu_keyboard()."""
    user = db.get_user(db_conn, chat_id)

    if user and user["last_menu_message_id"]:
        try:
            await bot.delete_message(chat_id=chat_id, message_id=user["last_menu_message_id"])
        except TelegramBadRequest as e:
            # Юзер мог уже сам удалить старый экран вручную, или он старше
            # 48ч (лимит Telegram на удаление) — не страшно, просто логируем.
            logger.debug("Не удалось удалить предыдущий экран навигации (chat_id=%s): %s", chat_id, e)

    sent = await bot.send_message(chat_id=chat_id, text=text, reply_markup=reply_markup)
    message_tracker.track(db_conn, sent)
    db.set_last_menu_message_id(db_conn, chat_id, sent.message_id)


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
    await show_screen(bot, db_conn, chat_id, text, keyboards.main_menu_keyboard(is_paused=is_paused))
