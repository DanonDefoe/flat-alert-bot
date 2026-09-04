"""
Handlers онбординга (см. architecture_and_plan.md, раздел 8):
  /start -> приветствие -> "Понятно, готов дать первую ссылку" ->
  ввод ссылки -> валидация + тестовое объявление -> выбор интервала ->
  "добавить ещё сайт?" -> (повтор) или конец онбординга.

Про db_conn в сигнатурах handlers: подключение к БД передаётся через aiogram
workflow_data, а не создаётся здесь каждый раз. main.py (ещё не написан)
должен сделать что-то вроде:
    dp["db_conn"] = db.get_connection(settings.database_path)
и тогда aiogram сам подставит db_conn как аргумент в каждый handler, где он
объявлен в сигнатуре — это стандартный механизм aiogram 3.x, не наша магия.

Про session: HTTP-сессия (requests.Session с общими заголовками) тоже должна
быть общей на весь бот, а не создаваться на каждый запрос — заведена как
module-level объект здесь для простоты; если понадобится — переносится в
workflow_data по тому же принципу, что и db_conn.
"""

from __future__ import annotations

import logging

from db import db

from aiogram import Router, F
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery
from bot import messages
from src.bot.handlers import link_common

from bot import keyboards
from fetcher import FetchError
from bot.states import OnboardingStates
from parsers.base import make_session
from bot import message_tracker
from utils import map_utils


logger = logging.getLogger(__name__)

router = Router(name="start")

# Общая HTTP-сессия для всех запросов валидации ссылок в этом модуле.
# См. докстринг файла — при необходимости переносится в workflow_data.
_session = make_session()


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, db_conn) -> None:
    await state.clear()
    db.upsert_user(db_conn, message.from_user.id)
    sent = await message.answer(
        messages.WELCOME_TEXT,
        reply_markup=keyboards.onboarding_start_keyboard(),
    )
    message_tracker.track(db_conn, sent)


@router.callback_query(F.data == "onb:ready")
async def onboarding_ready(callback: CallbackQuery, state: FSMContext, db_conn) -> None:
    await state.set_state(OnboardingStates.awaiting_link)
    sent = await callback.message.answer(messages.ASK_FOR_LINK_TEXT)
    message_tracker.track(db_conn, sent)
    await callback.answer()


@router.callback_query(F.data == "onb:cancel")
async def onboarding_cancel(callback: CallbackQuery, state: FSMContext, db_conn) -> None:
    # Этот колбэк теперь достижим из двух разных сценариев: настоящий первый
    # онбординг (кнопка "Отмена" после ошибки валидации ссылки) и добавление
    # второго/третьего сайта через menu:add_site (handlers/menu.py) — в обоих
    # случаях к этому моменту пользователь уже есть в БД (upsert_user в
    # cmd_start), так что показ меню корректен в любом случае, а не только
    # для "продолжающего" пользователя.
    await state.clear()
    sent1 = await callback.message.answer(messages.ONBOARDING_CANCELLED_TEXT)
    message_tracker.track(db_conn, sent1)

    user = db.get_user(db_conn, callback.from_user.id)
    is_paused = bool(user["is_paused"]) if user else False
    sent2 = await callback.message.answer(
        messages.MENU_TITLE,
        reply_markup=keyboards.main_menu_keyboard(is_paused=is_paused),
    )
    message_tracker.track(db_conn, sent2)
    await callback.answer()


@router.message(OnboardingStates.awaiting_link)
async def process_link(message: Message, state: FSMContext, db_conn) -> None:
    url = (message.text or "").strip()

    try:
        site, listings = await link_common.validate_link(_session, url)

    except link_common.UnsupportedSiteError:
        sent = await message.answer(
            messages.ERROR_UNSUPPORTED_SITE,
            reply_markup=keyboards.retry_link_keyboard(),
        )
        message_tracker.track(db_conn, sent)
        return

    except FetchError as e:
        logger.warning("Не удалось загрузить ссылку при онбординге: %s", e)
        sent = await message.answer(
            messages.ERROR_FETCH_FAILED,
            reply_markup=keyboards.retry_link_keyboard(),
        )
        message_tracker.track(db_conn, sent)
        return

    except ValueError as e:
        # __NEXT_DATA__ не найден / структура не та — верстка сайта изменилась.
        # Это не пользовательская ошибка, логируем громче.
        logger.error("Не удалось распарсить страницу при онбординге: %s", e)
        sent = await message.answer(
            messages.ERROR_PARSE_FAILED,
            reply_markup=keyboards.retry_link_keyboard(),
        )
        message_tracker.track(db_conn, sent)
        return

    except link_common.NoListingsFoundError:
        sent = await message.answer(
            messages.ERROR_NO_LISTINGS,
            reply_markup=keyboards.retry_link_keyboard(),
        )
        message_tracker.track(db_conn, sent)
        return

    # Проверка на дубль — ДО показа тестового объявления и выбора интервала,
    # чтобы не тратить время пользователя на шаги, которые всё равно ничем не
    # закончатся. Причина появления этой проверки: при каждом перезапуске бота
    # в момент разработки через /start легко случайно добавить ОДНУ И ТУ ЖЕ
    # ссылку повторно — без проверки это создавало отдельную подписку на
    # каждый раз, и одно и то же объявление приходило N раз за цикл.
    if db.subscription_exists(db_conn, message.from_user.id, site, url):
        sent = await message.answer(
            messages.ERROR_DUPLICATE_SUBSCRIPTION,
            reply_markup=keyboards.retry_link_keyboard(),
        )
        message_tracker.track(db_conn, sent)
        return

    # Успех — показываем тестовое объявление и переходим к выбору интервала.
    test_listing = listings[0]
    sent1 = await message.answer(messages.LINK_VALID_TEXT)
    message_tracker.track(db_conn, sent1)

    test_coords = map_utils.get_coordinates(db_conn, test_listing)
    test_fallback_url = None if test_coords else map_utils.get_fallback_map_url(test_listing)
    sent2 = await message.answer(
        messages.format_listing_message(test_listing, is_test=True, fallback_map_url=test_fallback_url),
        parse_mode="HTML",
    )
    message_tracker.track(db_conn, sent2)

    if test_coords:
        sent_loc = await message.answer_location(latitude=test_coords[0], longitude=test_coords[1])
        message_tracker.track(db_conn, sent_loc)

    await state.update_data(pending_site=site, pending_filter_url=url)
    await state.set_state(OnboardingStates.awaiting_interval)
    sent3 = await message.answer(
        messages.ASK_FOR_INTERVAL_TEXT,
        reply_markup=keyboards.interval_choice_keyboard(),
    )
    message_tracker.track(db_conn, sent3)


@router.callback_query(OnboardingStates.awaiting_interval, F.data.startswith("intv:"))
async def process_interval_choice(callback: CallbackQuery, state: FSMContext, db_conn) -> None:
    # callback.data формата "intv:{min_sec}:{max_sec}" — см. keyboards.py
    _, min_sec_str, max_sec_str = callback.data.split(":")

    data = await state.get_data()
    site = data["pending_site"]
    filter_url = data["pending_filter_url"]

    db.add_subscription(
        db_conn,
        user_id=callback.from_user.id,
        site=site,
        filter_url=filter_url,
        interval_min_sec=int(min_sec_str),
        interval_max_sec=int(max_sec_str),
    )

    await state.set_state(OnboardingStates.ask_add_more)
    sent = await callback.message.answer(
        messages.ASK_ADD_MORE_TEXT,
        reply_markup=keyboards.add_more_site_keyboard(),
    )
    message_tracker.track(db_conn, sent)
    await callback.answer()


@router.callback_query(OnboardingStates.ask_add_more, F.data == "addmore:yes")
async def add_more_site_yes(callback: CallbackQuery, state: FSMContext, db_conn) -> None:
    await state.set_state(OnboardingStates.awaiting_link)
    sent = await callback.message.answer(messages.ASK_FOR_LINK_TEXT)
    message_tracker.track(db_conn, sent)
    await callback.answer()


@router.callback_query(OnboardingStates.ask_add_more, F.data == "addmore:no")
async def add_more_site_no(callback: CallbackQuery, state: FSMContext, db_conn) -> None:
    await state.clear()
    user = db.get_user(db_conn, callback.from_user.id)
    is_paused = bool(user["is_paused"]) if user else False
    sent = await callback.message.answer(
        messages.ONBOARDING_DONE_TEXT,
        reply_markup=keyboards.main_menu_keyboard(is_paused=is_paused),
    )
    message_tracker.track(db_conn, sent)
    await callback.answer()