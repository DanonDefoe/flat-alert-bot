"""
Handlers меню (см. architecture_and_plan.md, раздел 8, "Меню").
Доступно в любой момент через кнопки main_menu_keyboard() — не привязано
к какому-то одному FSM-состоянию, в отличие от онбординга.

Про db_conn / session — см. докстринг start.py, тот же принцип: db_conn
передаётся через workflow_data, session — общая HTTP-сессия модуля.
"""

from __future__ import annotations

import logging

from aiogram import Router, F, Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery

from src.db import db
from src.bot.handlers import link_common
from utils import time_utils
from bot import keyboards
from bot import message_tracker
from bot import messages
from config import settings
from fetcher import FetchError
from bot.states import EditLinkStates, AddNoteStates, WorkHoursStates, OnboardingStates
from parsers.base import make_session
from utils import map_utils

logger = logging.getLogger(__name__)

router = Router(name="menu")

_session = make_session()


async def _show_menu(message: Message, db_conn) -> None:
    """Общий хелпер — показать меню с актуальным состоянием паузы.
    Переиспользуется после завершения любого из сценариев меню (редактирование
    ссылки, заметка, рабочее окно) — везде возвращаемся к одному и тому же
    экрану, а не изобретаем разные "конечные" сообщения."""
    user = db.get_user(db_conn, message.chat.id)
    is_paused = bool(user["is_paused"]) if user else False
    sent = await message.answer(messages.MENU_TITLE, reply_markup=keyboards.main_menu_keyboard(is_paused=is_paused))
    message_tracker.track(db_conn, sent)


# ---------------------------------------------------------------------------
# Добавить ещё один сайт — переиспользует ГОТОВЫЙ флоу онбординга
# (handlers/start.py: OnboardingStates.awaiting_link -> ... -> ask_add_more).
# Единственное отличие от первого запуска — точка входа: там это происходит
# после "onb:ready" или "addmore:yes", здесь — по кнопке из меню. Дальше по
# состояниям код полностью общий, включая тестовое объявление, выбор
# интервала и петлю "добавить ещё?" — ничего не задвоено.
# ---------------------------------------------------------------------------
@router.callback_query(F.data == "menu:add_site")
async def add_site_start(callback: CallbackQuery, state: FSMContext, db_conn) -> None:
    await state.set_state(OnboardingStates.awaiting_link)
    sent = await callback.message.answer(messages.ASK_FOR_LINK_TEXT)
    message_tracker.track(db_conn, sent)
    await callback.answer()


# ---------------------------------------------------------------------------
# Пауза
# ---------------------------------------------------------------------------
@router.callback_query(F.data == "menu:toggle_pause")
async def toggle_pause(callback: CallbackQuery, db_conn) -> None:
    user = db.get_user(db_conn, callback.from_user.id)
    currently_paused = bool(user["is_paused"]) if user else False
    new_paused = not currently_paused

    db.set_paused(db_conn, callback.from_user.id, new_paused)

    text = messages.MENU_PAUSED if new_paused else messages.MENU_RESUMED
    sent1 = await callback.message.answer(text)
    message_tracker.track(db_conn, sent1)
    sent2 = await callback.message.answer(
        messages.MENU_TITLE,
        reply_markup=keyboards.main_menu_keyboard(is_paused=new_paused),
    )
    message_tracker.track(db_conn, sent2)
    await callback.answer()


# ---------------------------------------------------------------------------
# Редактирование ссылки
# ---------------------------------------------------------------------------
@router.callback_query(F.data == "menu:edit_link")
async def edit_link_start(callback: CallbackQuery, state: FSMContext, db_conn) -> None:
    subscriptions = db.get_subscriptions_for_user(db_conn, callback.from_user.id)

    if not subscriptions:
        sent = await callback.message.answer(messages.MENU_NO_SUBSCRIPTIONS)
        message_tracker.track(db_conn, sent)
        await callback.answer()
        return

    if len(subscriptions) == 1:
        # Единственная подписка — не заставляем выбирать из списка на одну кнопку,
        # сразу переходим к вводу новой ссылки (см. комментарий в keyboards.py).
        sub = subscriptions[0]
        await state.update_data(editing_subscription_id=sub["id"])
        await state.set_state(EditLinkStates.awaiting_new_link)
        sent = await callback.message.answer(messages.MENU_ASK_NEW_LINK,
                                             reply_markup=keyboards.edit_link_cancel_keyboard())
        message_tracker.track(db_conn, sent)
        await callback.answer()
        return

    rows = [(s["id"], s["site"], s["filter_url"]) for s in subscriptions]
    sent = await callback.message.answer(
        messages.MENU_CHOOSE_SUBSCRIPTION_TO_EDIT,
        reply_markup=keyboards.choose_subscription_keyboard(rows),
    )
    message_tracker.track(db_conn, sent)
    await callback.answer()


@router.callback_query(F.data.startswith("editlink:sub:"))
async def edit_link_subscription_chosen(callback: CallbackQuery, state: FSMContext, db_conn) -> None:
    subscription_id = int(callback.data.split(":")[2])
    await state.update_data(editing_subscription_id=subscription_id)
    await state.set_state(EditLinkStates.awaiting_new_link)
    sent = await callback.message.answer(messages.MENU_ASK_NEW_LINK, reply_markup=keyboards.edit_link_cancel_keyboard())
    message_tracker.track(db_conn, sent)
    await callback.answer()


@router.callback_query(F.data == "editlink:cancel")
async def edit_link_cancel(callback: CallbackQuery, state: FSMContext, db_conn) -> None:
    # Безопасно вызывать независимо от текущего состояния — на шаге выбора
    # подписки FSM-состояние ещё не установлено (см. edit_link_start), а на
    # шаге ввода ссылки уже установлено EditLinkStates.awaiting_new_link.
    # state.clear() корректно отрабатывает в обоих случаях.
    await state.clear()
    sent = await callback.message.answer(messages.MENU_EDIT_LINK_CANCELLED)
    message_tracker.track(db_conn, sent)
    await _show_menu(callback.message, db_conn)
    await callback.answer()


@router.message(EditLinkStates.awaiting_new_link)
async def edit_link_process_new_url(message: Message, state: FSMContext, db_conn) -> None:
    url = (message.text or "").strip()

    try:
        site, listings = await link_common.validate_link(_session, url)

    except link_common.UnsupportedSiteError:
        sent = await message.answer(messages.ERROR_UNSUPPORTED_SITE,
                                    reply_markup=keyboards.retry_link_keyboard(cancel_callback_data="editlink:cancel"))
        message_tracker.track(db_conn, sent)
        return
    except FetchError as e:
        logger.warning("Не удалось загрузить ссылку при редактировании: %s", e)
        sent = await message.answer(messages.ERROR_FETCH_FAILED,
                                    reply_markup=keyboards.retry_link_keyboard(cancel_callback_data="editlink:cancel"))
        message_tracker.track(db_conn, sent)
        return
    except ValueError as e:
        logger.error("Не удалось распарсить страницу при редактировании: %s", e)
        sent = await message.answer(messages.ERROR_PARSE_FAILED,
                                    reply_markup=keyboards.retry_link_keyboard(cancel_callback_data="editlink:cancel"))
        message_tracker.track(db_conn, sent)
        return
    except link_common.NoListingsFoundError:
        sent = await message.answer(messages.ERROR_NO_LISTINGS,
                                    reply_markup=keyboards.retry_link_keyboard(cancel_callback_data="editlink:cancel"))
        message_tracker.track(db_conn, sent)
        return

    data = await state.get_data()
    subscription_id = data["editing_subscription_id"]

    # Используем subscription['site'] (уже сохранённый), а не свежеопределённый
    # site из validate_link — потому что сохраняемое ниже update_subscription_url
    # не меняет site (см. комментарий в исходной версии этой функции), значит и
    # проверка на дубль должна идти по тому значению, которое реально попадёт в БД.
    subscription = db.get_subscription(db_conn, subscription_id)
    if db.subscription_exists(db_conn, message.from_user.id, subscription["site"], url,
                              exclude_subscription_id=subscription_id):
        sent = await message.answer(
            messages.ERROR_DUPLICATE_SUBSCRIPTION,
            reply_markup=keyboards.retry_link_keyboard(cancel_callback_data="editlink:cancel"),
        )
        message_tracker.track(db_conn, sent)
        return

    # Примечание: сайт (ss_ge/myhome_ge) у подписки не меняем даже если новая
    # ссылка вдруг оказалась с другого домена — это осознанное упрощение,
    # такой кейс ("поменял ссылку ss.ge на ссылку myhome.ge при редактировании")
    # не описан в UX и выглядит как маловероятная ошибка пользователя, а не
    # осознанное действие. При необходимости — уточнить и доработать отдельно.
    db.update_subscription_url(db_conn, subscription_id, url)
    # Старая история seen_listings относится к прошлому фильтру — бесполезна
    # (а местами вредна: случайные совпадения по эвристике) как база сравнения
    # для нового. Сброс расписания заставит планировщик обработать следующую
    # проверку этой подписки как "первый запуск" (см. jobs.py:process_subscription)
    # — текущие объявления по НОВОМУ фильтру молча запомнятся, но не придут
    # пачкой, как реально новая подписка.
    db.clear_seen_listings(db_conn, subscription_id)
    db.reset_subscription_schedule(db_conn, subscription_id)

    test_listing = listings[0]
    sent1 = await message.answer(messages.MENU_LINK_UPDATED_TEXT)
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

    await state.clear()
    await _show_menu(message, db_conn)


# ---------------------------------------------------------------------------
# Заметка для разработчика
# ---------------------------------------------------------------------------
@router.callback_query(F.data == "menu:add_note")
async def add_note_start(callback: CallbackQuery, state: FSMContext, db_conn) -> None:
    await state.set_state(AddNoteStates.awaiting_note_text)
    sent = await callback.message.answer(messages.MENU_ASK_NOTE_TEXT)
    message_tracker.track(db_conn, sent)
    await callback.answer()


@router.message(AddNoteStates.awaiting_note_text)
async def add_note_save(message: Message, state: FSMContext, db_conn, bot: Bot) -> None:
    text = (message.text or "").strip()
    db.add_dev_note(db_conn, message.from_user.id, text)

    await state.clear()
    sent = await message.answer(messages.MENU_NOTE_SAVED)
    message_tracker.track(db_conn, sent)

    await _notify_developer(bot, message.from_user, text)

    await _show_menu(message, db_conn)


async def _notify_developer(bot: Bot, from_user, text: str) -> None:
    """Дублирует заметку личным сообщением разработчику, если DEVELOPER_TELEGRAM_ID
    задан в .env. Заметка уже сохранена в БД к моменту вызова этой функции —
    сбой пересылки (например, разработчик ни разу не писал боту, и Telegram не
    даёт отправить сообщение первым) НЕ должен ломать ответ пользователю:
    заметка всё равно не потеряна, она в dev_notes.

    Не трекается через message_tracker — это сообщение уходит в чат
    РАЗРАБОТЧИКА, а не пользователя бота, и не связано с db_conn пользователя
    так же прямо; оставляем вне общего автоудаления намеренно, не как недосмотр."""
    if settings.developer_telegram_id is None:
        logger.info("DEVELOPER_TELEGRAM_ID не задан — заметка только в БД, без пересылки.")
        return

    notification_text = messages.format_dev_note_notification(
        user_id=from_user.id,
        username=from_user.username,
        full_name=from_user.full_name,
        text=text,
    )

    try:
        await bot.send_message(
            chat_id=settings.developer_telegram_id,
            text=notification_text,
            parse_mode="HTML",
        )
    except TelegramBadRequest as e:
        # Типичная причина — разработчик ни разу не писал боту (Telegram не
        # позволяет ботам писать первыми пользователям, которые не открывали
        # с ним диалог). Заметка всё равно в БД — просто логируем и идём дальше.
        logger.warning("Не удалось переслать заметку разработчику (id=%s): %s",
                       settings.developer_telegram_id, e)


# ---------------------------------------------------------------------------
# Рабочее окно (ввод в тбилисском времени, хранение в UTC — см. time_utils.py)
# ---------------------------------------------------------------------------
@router.callback_query(F.data == "menu:work_hours")
async def work_hours_start(callback: CallbackQuery, state: FSMContext, db_conn) -> None:
    await state.set_state(WorkHoursStates.awaiting_start_time)
    sent = await callback.message.answer(messages.MENU_ASK_WORK_HOURS_START)
    message_tracker.track(db_conn, sent)
    await callback.answer()


@router.message(WorkHoursStates.awaiting_start_time)
async def work_hours_process_start(message: Message, state: FSMContext, db_conn) -> None:
    try:
        time_utils.parse_hh_mm(message.text or "")
    except ValueError:
        sent = await message.answer(messages.MENU_WORK_HOURS_INVALID)
        message_tracker.track(db_conn, sent)
        return  # остаёмся в том же состоянии, ждём повторный ввод

    # Храним как строку "HH:MM" в FSM data — сам объект time не нужен здесь,
    # достаточно валидного текста, парсим по новой на финальном шаге.
    await state.update_data(work_hours_start_tbilisi=(message.text or "").strip())
    await state.set_state(WorkHoursStates.awaiting_end_time)
    sent = await message.answer(messages.MENU_ASK_WORK_HOURS_END)
    message_tracker.track(db_conn, sent)


@router.message(WorkHoursStates.awaiting_end_time)
async def work_hours_process_end(message: Message, state: FSMContext, db_conn) -> None:
    try:
        end_time = time_utils.parse_hh_mm(message.text or "")
    except ValueError:
        sent = await message.answer(messages.MENU_WORK_HOURS_INVALID)
        message_tracker.track(db_conn, sent)
        return

    data = await state.get_data()
    start_time = time_utils.parse_hh_mm(data["work_hours_start_tbilisi"])

    start_utc = time_utils.tbilisi_to_utc(start_time)
    end_utc = time_utils.tbilisi_to_utc(end_time)

    db.set_work_hours_utc(
        db_conn,
        message.from_user.id,
        time_utils.format_hh_mm(start_utc),
        time_utils.format_hh_mm(end_utc),
    )

    await state.clear()
    sent = await message.answer(
        messages.format_work_hours_saved(
            time_utils.format_hh_mm(start_time),
            time_utils.format_hh_mm(end_time),
        )
    )
    message_tracker.track(db_conn, sent)
    await _show_menu(message, db_conn)


# ---------------------------------------------------------------------------
# Избранное — просмотр и удаление (добавление — см. handlers/listing.py,
# там же кнопка "⭐ В избранное" на самом объявлении)
# ---------------------------------------------------------------------------
@router.callback_query(F.data == "menu:favorites")
async def show_favorites(callback: CallbackQuery, db_conn) -> None:
    favorites = db.get_favorites(db_conn, callback.from_user.id)

    if not favorites:
        sent = await callback.message.answer(messages.FAVORITES_EMPTY_TEXT)
        message_tracker.track(db_conn, sent)
        await callback.answer()
        return

    header = await callback.message.answer(messages.FAVORITES_LIST_HEADER)
    message_tracker.track(db_conn, header)
    # Каждое избранное — отдельным сообщением с собственной кнопкой удаления,
    # а не одним большим списком: иначе нельзя было бы удалить конкретную
    # запись адресно (Telegram callback_data должен указывать на что-то одно).
    # is_favorite=True — эти сообщения НЕ участвуют в автоудалении через 3
    # суток (см. cleanup.py) — это и есть собственно "избранное".
    for fav in favorites:
        text = messages.format_favorite_entry(
            fav["street_raw"], fav["price_usd"], fav["price_gel"], fav["area_sqm"], fav["url"],
        )
        sent = await callback.message.answer(
            text,
            parse_mode="HTML",
            reply_markup=keyboards.favorite_delete_keyboard(fav["id"]),
        )
        message_tracker.track(db_conn, sent, is_favorite=True)
    await callback.answer()


@router.callback_query(F.data.startswith("favdel:"))
async def delete_favorite(callback: CallbackQuery, db_conn) -> None:
    favorite_id = int(callback.data.split(":", 1)[1])

    fav = db.get_favorite(db_conn, favorite_id)
    if fav is None or fav["user_id"] != callback.from_user.id:
        # Та же защита от подмены callback_data, что и у exclude_group_handler
        # и add_favorite_handler в listing.py — не должно происходить в норме.
        logger.warning(
            "delete_favorite: запись %s не найдена или не принадлежит юзеру %s",
            favorite_id, callback.from_user.id,
        )
        await callback.answer(messages.GROUP_EXCLUDE_ERROR_TEXT, show_alert=True)
        return

    db.remove_favorite(db_conn, favorite_id)
    await callback.message.edit_text(messages.FAVORITE_REMOVED_TEXT, reply_markup=None)
    await callback.answer()