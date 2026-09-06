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
from bot.handlers import menu_view

router = Router(name="commands")


@router.message(Command("menu"))
async def cmd_menu(message: Message, state: FSMContext, db_conn, bot: Bot) -> None:
    await state.clear()
    await menu_view.show_menu(bot, db_conn, message.from_user.id)


@router.callback_query(F.data == "menu:open")
async def callback_menu_open(callback: CallbackQuery, state: FSMContext, db_conn, bot: Bot) -> None:
    await state.clear()
    await menu_view.show_menu(bot, db_conn, callback.from_user.id)
    await callback.answer()
