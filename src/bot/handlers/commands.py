"""
Глобальный доступ к меню — команда /menu и колбэк "menu:open" (кнопка "☰ Меню"
на объявлениях, см. keyboards.listing_action_keyboard).

ВАЖНО про порядок подключения роутеров в main.py: этот router должен быть
включён ПЕРВЫМ, раньше start.router и menu.router. Причина: часть обработчиков
там привязана к FSM-состоянию без исключения команд (например,
@router.message(OnboardingStates.awaiting_link) в start.py ловит ЛЮБОЙ текст
в этом состоянии, включая случайно набранный "/menu") — если бы commands.router
подключался позже, "/menu" перехватывался бы тем обработчиком раньше, чем
дошёл бы сюда, и воспринимался бы как невалидная ссылка вместо команды.
Aiogram проверяет роутеры в порядке подключения — этот первым получает шанс
среагировать на "/menu" независимо от того, в каком состоянии сейчас юзер.

Оба обработчика явно вызывают state.clear() — команда/кнопка "Меню" это
осознанный выход из любого текущего сценария (ввод ссылки, заметки, времени
работы и т.д.), а не просто ещё одно сообщение внутри него.
"""

from __future__ import annotations

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery

from src.db import db
from bot import keyboards
from bot import messages
from bot import message_tracker

router = Router(name="commands")


async def _open_menu(db_conn, chat_id: int, answer_fn) -> None:
    """Общая логика для команды и колбэка — оба в итоге делают одно и то же:
    показать меню с актуальным состоянием паузы. answer_fn — это либо
    message.answer, либо callback.message.answer (сигнатура одинаковая)."""
    user = db.get_user(db_conn, chat_id)
    is_paused = bool(user["is_paused"]) if user else False
    sent = await answer_fn(messages.MENU_TITLE, reply_markup=keyboards.main_menu_keyboard(is_paused=is_paused))
    message_tracker.track(db_conn, sent)


@router.message(Command("menu"))
async def cmd_menu(message: Message, state: FSMContext, db_conn) -> None:
    await state.clear()
    await _open_menu(db_conn, message.from_user.id, message.answer)


@router.callback_query(F.data == "menu:open")
async def callback_menu_open(callback: CallbackQuery, state: FSMContext, db_conn) -> None:
    await state.clear()
    await _open_menu(db_conn, callback.from_user.id, callback.message.answer)
    await callback.answer()