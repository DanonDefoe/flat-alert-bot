"""
Доставка объявлений пользователю + handler кнопки "Убрать из выдачи".

Используется планировщиком (scheduler/jobs.py, ещё не написан): после
parse -> dedup.process_new_listings -> dedup.filter_excluded_groups планировщик
вызывает deliver_new_listings() для каждой подписки, чтобы отправить то, что
реально дошло до отправки.

ВАЖНЫЙ НЮАНС TELEGRAM BOT API: инлайн-клавиатуру нельзя прикрепить к
sendMediaGroup (альбому фото) — Telegram API этого не поддерживает вообще,
ни через aiogram, ни напрямую. Поэтому кнопка "Убрать из выдачи" уходит
ОТДЕЛЬНЫМ сообщением сразу после фото/текста объявления, а не как часть
одного и того же сообщения.
"""

from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Router, F
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, InputMediaPhoto

from db import db
from bot import keyboards
from bot import messages
from dedup.dedup import DedupResult
from bot import message_tracker
from utils import map_utils

logger = logging.getLogger(__name__)

router = Router(name="listing")

# Пауза между отправкой отдельных объявлений одному пользователю — чтобы не
# упереться в лимиты Telegram при массовой рассылке (много новых объявлений
# за один цикл проверки). Значение с запасом, не тонкая настройка под лимит.
SEND_DELAY_SEC = 0.5


async def send_listing(
        bot: Bot,
        chat_id: int,
        result: DedupResult,
        subscription_id: int,
        db_conn,
) -> None:
    """Отправить одно объявление одному пользователю. Не бросает исключения
    наружу при сбое отправки конкретного объявления — логирует и возвращается,
    чтобы одно проблемное объявление (например, битые ссылки на фото) не
    прерывало отправку остальных объявлений в батче.

    Кнопки ("⭐ В избранное" + опционально "🚫 Убрать из выдачи" + "☰ Меню" +
    "🗑 Удалить из чата") стараемся прикрепить к уже существующему сообщению,
    а не слать отдельным:
      - если есть координаты -> вешаем на send_location (Telegram это
        поддерживает — в отличие от sendMediaGroup);
      - если координат нет и фото тоже нет -> вешаем на текстовое сообщение;
      - если координат нет, но есть фото (альбом) -> ОТДЕЛЬНОЕ сообщение
        всё же неизбежно: sendMediaGroup в принципе не поддерживает
        reply_markup ни на одном элементе — это ограничение Telegram Bot
        API, не наш недосмотр.

    prior_message_ids собирает id всех сообщений, отправленных ДО того,
    что несёт кнопки (фото, и/или карта, если карта не несёт кнопки сама) —
    нужно для кнопки "Удалить из чата": она удаляет все эти сообщения плюс
    редактирует (не удаляет) само сообщение-носитель кнопок, т.к. оно не
    может знать свой собственный message_id в момент создания клавиатуры
    (см. db_schema.sql: listing_deliveries)."""
    listing = result.listing
    prior_message_ids: list[int] = []

    duplicate_of_url = None
    if result.is_duplicate and result.duplicate_of_native_id:
        original = db.get_seen_listing(db_conn, subscription_id, result.duplicate_of_native_id)
        if original is not None:
            duplicate_of_url = original["url"]

    # Приоритет — нативная карта Telegram (send_location) там, где есть точные
    # координаты; текстовая ссылка на Google Maps — только запасной вариант,
    # когда координат нет вообще (см. map_utils.py).
    coords = map_utils.get_coordinates(db_conn, listing)
    fallback_url = None if coords else map_utils.get_fallback_map_url(listing)

    text = messages.format_listing_message(
        listing,
        is_duplicate=result.is_duplicate,
        duplicate_of_url=duplicate_of_url,
        fallback_map_url=fallback_url,
    )

    photos = listing.photo_urls[:4]
    # True, если кнопки уже прикреплены к какому-то из отправленных сообщений
    # ниже — тогда финальный блок в конце функции их повторно слать не должен.
    buttons_attached = False

    try:
        if photos:
            media = [InputMediaPhoto(media=url) for url in photos]
            media[0].caption = text
            media[0].parse_mode = "HTML"
            sent = await bot.send_media_group(chat_id=chat_id, media=media)
            message_tracker.track_many(db_conn, sent)
            prior_message_ids.extend(m.message_id for m in sent)
            # Кнопки сюда прикрепить нельзя (см. докстринг) — buttons_attached
            # остаётся False, если ниже не окажется координат для карты.
        else:
            # Фото нет — если координат тоже нет, кнопки повесим прямо на
            # этот текст ниже (после того как создадим delivery-запись).
            if coords:
                sent = await bot.send_message(chat_id=chat_id, text=text, parse_mode="HTML")
                message_tracker.track(db_conn, sent)
                prior_message_ids.append(sent.message_id)

    except TelegramBadRequest as e:
        # Частая причина — не загрузилось одно из фото (битая ссылка, сайт
        # временно отдал 403 на конкретную картинку). Не теряем объявление
        # целиком — падаем на текстовое сообщение без фото.
        logger.warning("Не удалось отправить фото для %s (%s): %s", listing.native_id, listing.site, e)
        try:
            if coords:
                sent = await bot.send_message(chat_id=chat_id, text=text, parse_mode="HTML")
                message_tracker.track(db_conn, sent)
                prior_message_ids.append(sent.message_id)
            # else: без координат — этот текст станет самим носителем кнопок
            # ниже, отправим его там за один раз вместе с клавиатурой.
        except TelegramBadRequest as e2:
            logger.error("Не удалось отправить даже текст для %s: %s", listing.native_id, e2)
            return

    # Собираем группу "прошлых" сообщений в БД ДО отправки носителя кнопок —
    # чтобы включить delivery_id в саму клавиатуру (см. докстринг про
    # невозможность сослаться на ещё не отправленное сообщение на себя же).
    delivery_id = db.create_listing_delivery(db_conn, chat_id, prior_message_ids)

    show_exclude = bool(result.is_duplicate and listing.site == "ss_ge" and listing.duplicate_group_id)
    action_keyboard = keyboards.listing_action_keyboard(
        subscription_id, listing.native_id, show_exclude, listing.duplicate_group_id, delivery_id,
    )

    # Если текста без фото и без координат ещё не было отправлено (случай
    # "нет фото, нет координат") — шлём его СЕЙЧАС сразу с кнопками, одним
    # сообщением, а не двумя.
    if not photos and not coords:
        sent = await bot.send_message(
            chat_id=chat_id, text=text, parse_mode="HTML", reply_markup=action_keyboard,
        )
        message_tracker.track(db_conn, sent)
        buttons_attached = True

    # Нативная карта Telegram — ПОСЛЕ текста/фото. send_location физически не
    # может быть частью sendMediaGroup или подписи к фото — только отдельным
    # вызовом, но САМ send_location поддерживает reply_markup — вешаем кнопки
    # сюда, если они ещё не прикреплены (т.е. выше было фото ИЛИ текст+координаты).
    if coords and not buttons_attached:
        try:
            sent_loc = await bot.send_location(
                chat_id=chat_id, latitude=coords[0], longitude=coords[1],
                reply_markup=action_keyboard,
            )
            message_tracker.track(db_conn, sent_loc)
            buttons_attached = True
        except TelegramBadRequest as e:
            # Карта не критична — объявление и так уже отправлено с текстом/
            # фото. Но кнопки МЫ планировали повесить именно сюда — раз не
            # получилось, их всё же нужно отправить отдельно ниже.
            logger.warning("Не удалось отправить карту для %s (%s): %s", listing.native_id, listing.site, e)

    # Остаётся только один случай, когда кнопки ещё не пристроены никуда:
    # был альбом фото (sendMediaGroup не поддерживает reply_markup) и при
    # этом карта либо не отправлялась (нет координат), либо не отправилась
    # (сбой). Тут отдельное сообщение с кнопками действительно неизбежно.
    #
    # ВАЖНО: text здесь НЕ может быть пустой строкой или zero-width space —
    # Telegram сервер отклоняет и то, и другое как "text must be non-empty"
    # (проверено на практике: \u200b формально не пустая строка в Python,
    # но Telegram её всё равно бракует). U+2800 (BRAILLE PATTERN BLANK) —
    # не классифицируется как whitespace, Telegram его принимает и он
    # визуально не бросается в глаза.
    if not buttons_attached:
        try:
            sent_actions = await bot.send_message(
                chat_id=chat_id, text="\u2800", reply_markup=action_keyboard,
            )
            message_tracker.track(db_conn, sent_actions)
        except TelegramBadRequest as e:
            # Не даём одному сбойному сообщению с кнопками оборвать всю
            # остальную партию доставки в этом цикле (deliver_new_listings
            # шлёт объявления по очереди — исключение отсюда раньше
            # прерывало бы весь оставшийся батч, не только это объявление).
            logger.error(
                "Не удалось отправить сообщение с кнопками для %s (%s): %s",
                listing.native_id, listing.site, e,
            )


async def deliver_new_listings(
        bot: Bot,
        chat_id: int,
        subscription_id: int,
        results: list[DedupResult],
        db_conn,
) -> None:
    """Точка входа для планировщика — отправляет весь батч по одной подписке
    с паузой между сообщениями."""
    for result in results:
        await send_listing(bot, chat_id, result, subscription_id, db_conn)
        await asyncio.sleep(SEND_DELAY_SEC)


# ---------------------------------------------------------------------------
# Handler кнопки "Убрать из выдачи"
# ---------------------------------------------------------------------------
@router.callback_query(F.data.startswith("exg:"))
async def exclude_group_handler(callback: CallbackQuery, db_conn) -> None:
    # callback.data формата "exg:{subscription_id}:{duplicate_group_id}" — см. keyboards.py
    _, subscription_id_str, group_id = callback.data.split(":", 2)
    subscription_id = int(subscription_id_str)

    subscription = db.get_subscription(db_conn, subscription_id)
    if subscription is None or subscription["user_id"] != callback.from_user.id:
        # Защита от подмены callback_data (или устаревшей подписки, которую
        # уже удалили) — не должно происходить в норме, но не должно и падать.
        logger.warning(
            "exclude_group: подписка %s не найдена или не принадлежит юзеру %s",
            subscription_id, callback.from_user.id,
        )
        await callback.answer(messages.GROUP_EXCLUDE_ERROR_TEXT, show_alert=True)
        return

    db.exclude_group(db_conn, subscription_id, group_id)

    await callback.message.edit_text(messages.GROUP_EXCLUDED_TEXT, reply_markup=None)
    await callback.answer()


# ---------------------------------------------------------------------------
# Handler кнопки "⭐ В избранное"
# ---------------------------------------------------------------------------
@router.callback_query(F.data.startswith("fav:"))
async def add_favorite_handler(callback: CallbackQuery, db_conn) -> None:
    # callback.data формата "fav:{subscription_id}:{native_id}" — см. keyboards.py
    _, subscription_id_str, native_id = callback.data.split(":", 2)
    subscription_id = int(subscription_id_str)

    subscription = db.get_subscription(db_conn, subscription_id)
    if subscription is None or subscription["user_id"] != callback.from_user.id:
        logger.warning(
            "add_favorite: подписка %s не найдена или не принадлежит юзеру %s",
            subscription_id, callback.from_user.id,
        )
        await callback.answer(messages.FAVORITE_ADD_ERROR_ANSWER, show_alert=True)
        return

    seen = db.get_seen_listing(db_conn, subscription_id, native_id)
    if seen is None:
        # В норме не должно происходить — объявление уже должно быть в
        # seen_listings к моменту, когда юзер видит кнопку под ним (кнопка
        # прикрепляется к уже отправленному сообщению). Но БД мог почистить
        # кто-то руками, или это старое сообщение из давно удалённой подписки.
        logger.warning(
            "add_favorite: объявление %s не найдено в seen_listings для подписки %s",
            native_id, subscription_id,
        )
        await callback.answer(messages.FAVORITE_ADD_ERROR_ANSWER, show_alert=True)
        return

    added = db.add_favorite(
        db_conn,
        user_id=callback.from_user.id,
        site=subscription["site"],
        native_id=native_id,
        street_raw=seen["street_raw"],
        price_usd=seen["price_usd"],
        price_gel=seen["price_gel"],
        area_sqm=seen["area_sqm"],
        url=seen["url"],
    )

    answer_text = messages.FAVORITE_ADDED_ANSWER if added else messages.FAVORITE_ALREADY_ADDED_ANSWER
    await callback.answer(answer_text)


# ---------------------------------------------------------------------------
# Handler кнопки "🗑 Удалить из чата"
# ---------------------------------------------------------------------------
@router.callback_query(F.data.startswith("delmsg:"))
async def delete_listing_handler(callback: CallbackQuery, db_conn, bot: Bot) -> None:
    # callback.data формата "delmsg:{delivery_id}" — см. keyboards.py
    delivery_id = int(callback.data.split(":", 1)[1])

    delivery = db.get_listing_delivery(db_conn, delivery_id)
    if delivery is None or delivery["chat_id"] != callback.from_user.id:
        # Устаревшая/чужая запись — не должно происходить в норме (кнопка
        # видна только тому чату, для которого delivery создавалась), но
        # защита от подмены callback_data на всякий случай.
        logger.warning(
            "delete_listing: доставка %s не найдена или не принадлежит чату %s",
            delivery_id, callback.from_user.id,
        )
        await callback.answer(messages.LISTING_DELETE_ERROR_TEXT, show_alert=True)
        return

    message_ids = [int(mid) for mid in delivery["message_ids"].split(",") if mid]
    for message_id in message_ids:
        try:
            await bot.delete_message(chat_id=delivery["chat_id"], message_id=message_id)
        except TelegramBadRequest as e:
            # Юзер мог уже сам удалить одно из сообщений вручную — не
            # прерываем удаление остальных из-за одного такого случая.
            logger.debug("Не удалось удалить сообщение %s: %s", message_id, e)

    db.delete_listing_delivery(db_conn, delivery_id)

    # Само сообщение-носитель кнопок НЕ удаляем через delete_message — вместо
    # этого редактируем в подтверждение (см. докстринг send_listing про
    # невозможность знать свой собственный message_id заранее).
    await callback.message.edit_text(messages.LISTING_DELETED_TEXT, reply_markup=None)
    await callback.answer()
