"""
Инлайн-клавиатуры бота. Один модуль на все кнопки — handlers импортируют
готовые функции, не строят разметку сами. Это упрощает правки: если меняется
текст кнопки или формат callback_data, трогаем только этот файл.

Формат callback_data: короткие префиксы через ":", числа как есть (не JSON —
Telegram ограничивает callback_data 64 байтами, экономим место).
Разбор этих префиксов происходит в handlers через F.data.startswith(...)
или callback_data фильтры aiogram — реализуется на шаге написания handlers.
"""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


# ---------------------------------------------------------------------------
# Онбординг (см. architecture_and_plan.md, раздел 8)
# ---------------------------------------------------------------------------
def onboarding_start_keyboard() -> InlineKeyboardMarkup:
    """Единственная кнопка после приветственного текста."""
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(
        text="Понятно, готов(а) дать первую ссылку",
        callback_data="onb:ready",
    ))
    return builder.as_markup()


# Варианты интервала проверки — (подпись для юзера, min_сек, max_сек).
# Вынесено в константу, а не захардкожено внутри функции — те же три варианта
# понадобятся planner'у/scheduler'у как источник правды для валидации ввода.
INTERVAL_CHOICES: list[tuple[str, int, int]] = [
    ("20–30 минут", 20 * 60, 30 * 60),
    ("30–40 минут", 30 * 60, 40 * 60),
    ("40–60 минут", 40 * 60, 60 * 60),
]


def interval_choice_keyboard() -> InlineKeyboardMarkup:
    """Выбор интервала после успешной валидации ссылки."""
    builder = InlineKeyboardBuilder()
    for label, min_sec, max_sec in INTERVAL_CHOICES:
        builder.add(InlineKeyboardButton(
            text=label,
            callback_data=f"intv:{min_sec}:{max_sec}",
        ))
    builder.adjust(1)  # каждая кнопка на отдельной строке — удобнее тапать на телефоне
    return builder.as_markup()


def add_more_site_keyboard() -> InlineKeyboardMarkup:
    """"Хотите добавить ещё один сайт для отслеживания?" — Да/Нет."""
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="Да, добавить ещё", callback_data="addmore:yes"))
    builder.add(InlineKeyboardButton(text="Нет, продолжить", callback_data="addmore:no"))
    builder.adjust(1)
    return builder.as_markup()


def retry_link_keyboard(cancel_callback_data: str = "onb:cancel") -> InlineKeyboardMarkup:
    """После ошибки валидации ссылки — предложить попробовать ещё раз или отменить.
    Сам повторный ввод — это просто новое текстовое сообщение от юзера (FSM-состояние
    не меняется), кнопка "Отмена" выходит в IDLE.

    cancel_callback_data параметризован, потому что эта клавиатура используется
    и в онбординге ("onb:cancel" -> см. handlers/start.py), и при редактировании
    ссылки из меню ("editlink:cancel" -> см. handlers/menu.py) — это разные
    сценарии с разным "куда вернуться", один общий callback тут был бы ошибкой."""
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="Отмена", callback_data=cancel_callback_data))
    return builder.as_markup()


def edit_link_cancel_keyboard() -> InlineKeyboardMarkup:
    """Отдельная кнопка "Отмена" для сценария редактирования ссылки — вешается
    на сообщение с просьбой прислать новую ссылку (menu:edit_link -> ...
    -> MENU_ASK_NEW_LINK), чтобы можно было выйти из сценария в любой момент,
    не только после ошибки валидации."""
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="Отмена", callback_data="editlink:cancel"))
    return builder.as_markup()


# ---------------------------------------------------------------------------
# Главное меню (доступно в любой момент — см. architecture_and_plan.md, раздел 8)
# ---------------------------------------------------------------------------
def main_menu_keyboard(is_paused: bool) -> InlineKeyboardMarkup:
    """
    Текст кнопки паузы зависит от текущего состояния — так пользователю сразу
    видно, что произойдёт по нажатию, а не приходится помнить, включена ли пауза.
    """
    pause_label = "▶️ Возобновить бота" if is_paused else "⏸ Приостановить бота"

    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text=pause_label, callback_data="menu:toggle_pause"))
    builder.add(InlineKeyboardButton(text="➕ Добавить сайт", callback_data="menu:add_site"))
    builder.add(InlineKeyboardButton(text="✏️ Отредактировать ссылку", callback_data="menu:edit_link"))
    builder.add(InlineKeyboardButton(text="⭐ Избранное", callback_data="menu:favorites"))
    builder.add(InlineKeyboardButton(text="🕐 Изменить рабочее окно", callback_data="menu:work_hours"))
    builder.add(InlineKeyboardButton(text="💬 Фидбек разработчику", callback_data="menu:add_note"))
    builder.adjust(1)
    return builder.as_markup()


def choose_subscription_keyboard(
    subscriptions: list[tuple[int, str, str]],
) -> InlineKeyboardMarkup:
    """
    Меню -> "Отредактировать ссылку" -> если подписок несколько, нужно выбрать какую.

    subscriptions: список (subscription_id, site, filter_url) — обычно результат
    db.get_subscriptions_for_user(). Ссылка обрезается в подписи кнопки — сама
    Telegram-кнопка не может показать длинный URL читаемо, полная ссылка не нужна
    для выбора, только чтобы отличить подписки друг от друга.
    """
    site_labels = {"ss_ge": "ss.ge", "myhome_ge": "myhome.ge"}

    builder = InlineKeyboardBuilder()
    for subscription_id, site, filter_url in subscriptions:
        site_label = site_labels.get(site, site)
        short_url = filter_url if len(filter_url) <= 40 else filter_url[:37] + "..."
        builder.add(InlineKeyboardButton(
            text=f"{site_label}: {short_url}",
            callback_data=f"editlink:sub:{subscription_id}",
        ))
    builder.add(InlineKeyboardButton(text="Отмена", callback_data="editlink:cancel"))
    builder.adjust(1)
    return builder.as_markup()


# ---------------------------------------------------------------------------
# Кнопки под сообщением с объявлением
# ---------------------------------------------------------------------------
def listing_action_keyboard(
    subscription_id: int,
    native_id: str,
    show_exclude: bool,
    duplicate_group_id: str | None,
    delivery_id: int,
) -> InlineKeyboardMarkup:
    """
    Кнопки под объявлением. "⭐ В избранное" и "☰ Меню" — ВСЕГДА, на одной
    строке (юзер попросил "Меню" именно рядом с "В избранное" — способ
    вызвать меню в любой момент, а не только через команду /menu, см.
    commands.py). "🗑 Удалить из чата" — тоже всегда, отдельной строкой.

    "🚫 Убрать из выдачи" — только когда show_exclude=True (объявление ss.ge,
    реально отмеченное дублем, с непустым duplicate_group_id — см.
    architecture_and_plan.md, раздел 4.1), отдельной строкой сверху, если есть.
    Условие проверяется на вызывающей стороне (listing.py), сюда приходит уже
    готовым флагом — эта функция не знает про DedupResult, только собирает кнопки.

    delivery_id — ссылка на listing_deliveries (см. db_schema.sql), группу
    сообщений ОДНОЙ доставки этого объявления (фото + карта, если были ДО
    этого сообщения) — по нему кнопка "Удалить" узнаёт, что ещё нужно стереть
    кроме самого сообщения с кнопками (см. handlers/listing.py).
    """
    builder = InlineKeyboardBuilder()
    if show_exclude and duplicate_group_id:
        builder.add(InlineKeyboardButton(
            text="🚫 Убрать из выдачи",
            callback_data=f"exg:{subscription_id}:{duplicate_group_id}",
        ))
    builder.add(InlineKeyboardButton(
        text="⭐ В избранное",
        callback_data=f"fav:{subscription_id}:{native_id}",
    ))
    builder.add(InlineKeyboardButton(text="☰ Меню", callback_data="menu:open"))
    builder.add(InlineKeyboardButton(text="🗑 Удалить из чата", callback_data=f"delmsg:{delivery_id}"))

    # "Убрать из выдачи" (если есть) — своей строкой; "В избранное" + "Меню" —
    # вместе на следующей строке; "Удалить из чата" — отдельной строкой внизу.
    if show_exclude and duplicate_group_id:
        builder.adjust(1, 2, 1)
    else:
        builder.adjust(2, 1)
    return builder.as_markup()


def favorite_delete_keyboard(favorite_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="🗑 Удалить", callback_data=f"favdel:{favorite_id}"))
    return builder.as_markup()