"""
Текстовые шаблоны сообщений бота. Тексты отдельно от handlers — чтобы менять
формулировки, не трогая логику, и чтобы не плодить длинные строки внутри
хендлеров.

Формат объявлений (format_listing_message) переиспользуется и для тестового
объявления при онбординге, и позже для настоящих уведомлений о новых
объявлениях (handlers/listing.py, ещё не написан) — одна функция, один формат.
"""

from __future__ import annotations

from urllib.parse import quote

from parsers.base import Listing
from scheduler.cleanup import MESSAGE_TTL_DAYS


def _encode_url(url: str) -> str:
    """Кодирует кириллицу и прочие небезопасные для URL символы, оставляя
    структуру (схему, слэши, ?, =, & и т.д.) нетронутой. Без этого десктопный
    клиент Telegram не распознаёт ссылки на кириллических путях (например,
    https://home.ss.ge/ru/недвижимость/...) как кликабельные — мобильный
    клиент прощает, десктопный нет. Баг найден и подтверждён вручную."""
    return quote(url, safe=":/?=&#+%@!$,;~")


WELCOME_TEXT = (
    "Привет! Это бот, который отслеживает объявления на myhome.ge и home.ss.ge.\n\n"
    "Чтобы я заработал, зайди на желаемый сайт, настрой все нужные тебе фильтры "
    "(в том числе сортировку по времени добавления) и нажми кнопку поиска.\n"
    "Когда страница загрузится — скопируй полностью URL из адресной строки и пришли мне.\n\n"
)

ASK_FOR_LINK_TEXT = "Пришли ссылку с фильтрами с ss.ge или myhome.ge."

ASK_FOR_INTERVAL_TEXT = "Выбери интервал проверок и уведомлений:"

ASK_ADD_MORE_TEXT = "Готово! Добавить ещё одну ссылку для отслеживания?"

ONBOARDING_DONE_TEXT = (
    "Отлично, теперь объявления будут приходить по заданному фильтру. "
    "Некоторые дубликаты квартир можно скрыть через соответствующую кнопку — "
    "тогда следующие дублирующие объявления тоже будут скрываться (работает не для всех объявлений). "
    f"Старые сообщения удаляются через {MESSAGE_TTL_DAYS} суток, поэтому не забывай добавлять в Избранное."
)

ONBOARDING_CANCELLED_TEXT = "Хорошо, отменил. Добавить в любой момент можно через меню, вызвать внизу слева."

LINK_VALID_TEXT = "✅ Ссылка рабочая. Кстати, МЕНЮ всегда можно вызвать через кнопку внизу слева."

LISTING_DELETED_TEXT = "🗑 Удалено."

LISTING_DELETE_ERROR_TEXT = "Не получилось удалить — попробуй ещё раз."

# --- Ошибки валидации ссылки — разные тексты под разные причины (см. link_common.py) ---

ERROR_UNSUPPORTED_SITE = (
    "Вероятно, ссылка не с ss.ge или myhome.ge. Поддерживаются только эти два сайта — "
    "нужно проверить ссылку и прислать заново."
)

ERROR_FETCH_FAILED = (
    "Внимание: myhome не пускает бота на сайт, пока что этот сервис недоступен, будем разбираться. "
    "Не получилось загрузить страницу по этой ссылке — сайт не ответил или "
    "временно недоступен. Проверь, доступен ли сайт и попробуй ещё раз через минуту."
    " Если не получается — пришли проблемную ссылку через фидбек из главного меню."
)

ERROR_PARSE_FAILED = (
    "Не смог распознать список объявлений по этой ссылке — возможно, сайт "
    "изменил вёрстку. Через главное меню можно оставить фидбек разработчику."
)

ERROR_NO_LISTINGS = (
    "По этой ссылке сейчас нет объявлений. Проверь фильтр на сайте — возможно, "
    "что-то не так с фильтрами. Если по ссылке объявления есть, но бот их не видит "
    "— пришли проблемную ссылку через фидбек из главного меню."
)

ERROR_DUPLICATE_SUBSCRIPTION = (
    "Эта ссылка уже отслеживается — добавлять её ещё раз не нужно, "
    "иначе объявления будут приходить по несколько раз."
)

# --- Меню ---

MENU_TITLE = "Меню:"

MENU_PAUSED = "⏸ Бот приостановлен. Новые объявления присылать не буду, пока не возобновишь."
MENU_RESUMED = "▶️ Бот снова активен."

MENU_NO_SUBSCRIPTIONS = "У тебя пока нет ни одной подписки. Напиши /start, чтобы добавить."

MENU_CHOOSE_SUBSCRIPTION_TO_EDIT = "Какую ссылку отредактировать?"

MENU_ASK_NEW_LINK = "Теперь нужно прислать новую ссылку взамен текущей."

MENU_EDIT_LINK_CANCELLED = "Отменено, ссылка не изменена."

MENU_LINK_UPDATED_TEXT = "✅ Ссылка обновлена! Вот как теперь будут выглядеть уведомления, только с фото:"

MENU_ASK_NOTE_TEXT = (
    "Напиши текст заметки — она будет сохранена и отправлена разработчику. "
    "Если подразумевается диалог/обратная связь — приложи свой ник Телеграма"
)

MENU_NOTE_SAVED = "Заметка сохранена, спасибо!"


def format_dev_note_notification(user_id: int, username: str | None, full_name: str, text: str) -> str:
    who = f"@{username}" if username else full_name
    return (
        f"📝 <b>Новая заметка от пользователя</b>\n"
        f"От: {who} (id: {user_id})\n\n"
        f"{text}"
    )


MENU_ASK_WORK_HOURS_START = (
    "Во сколько бот должен начинать присылать уведомления? "
    "Введи время по Тбилиси в формате ЧЧ:ММ, например 09:00."
)

MENU_ASK_WORK_HOURS_END = (
    "А во сколько заканчивать уведомлять? Формат ЧЧ:ММ, например 01:00."
)

MENU_WORK_HOURS_INVALID = (
    "Не удалось распознать время. Формат часы:минуты, например 23:30. "
    "Попробуй ещё раз, если не получается — опиши проблему через фидбек из главного меню."
)


def format_work_hours_saved(start_tbilisi: str, end_tbilisi: str) -> str:
    return (
        f"✅ Рабочее окно сохранено: {start_tbilisi}–{end_tbilisi} по Тбилиси.\n"
        f"В это время буду проверять объявления и присылать уведомления."
    )


# --- "Убрать из выдачи" ---

GROUP_EXCLUDED_TEXT = "🚫 Скрыто. Больше не буду присылать объявления из этой группы дублей (срабатывает не всегда)."

GROUP_EXCLUDE_ERROR_TEXT = "Не получилось скрыть — попробуй ещё раз или напиши разработчику через меню."


# --- Избранное ---

FAVORITE_ADDED_ANSWER = "⭐ Добавлено в избранное"
FAVORITE_ALREADY_ADDED_ANSWER = "Уже в избранном"
FAVORITE_ADD_ERROR_ANSWER = "Не получилось добавить — попробуй ещё раз или напиши разработчику через меню."

FAVORITES_EMPTY_TEXT = "Пока пусто. Добавить объявления можно кнопкой «⭐ В избранное» под ними."
FAVORITES_LIST_HEADER = "Твои избранные объявления:"

FAVORITE_REMOVED_TEXT = "Удалено из избранного."


def format_favorite_entry(
    street_raw: str | None,
    price_usd: float | None,
    price_gel: float | None,
    area_sqm: float | None,
    url: str,
) -> str:
    """Одна строка избранного: 'ул. А.Размадзе, $650, 47 м²', целиком —
    кликабельная ссылка на объявление (см. запрос пользователя — клик на
    текст, а не отдельная кнопка со ссылкой)."""
    parts: list[str] = []
    if street_raw:
        parts.append(street_raw)
    if price_usd:
        parts.append(f"${price_usd:.0f}")
    elif price_gel:
        parts.append(f"{price_gel:.0f}₾")
    if area_sqm:
        parts.append(f"{area_sqm:.0f} м²")

    label = ", ".join(parts) if parts else "Объявление"
    return f'<a href="{_encode_url(url)}">{label}</a>'


def format_listing_message(
    listing: Listing,
    is_test: bool = False,
    is_duplicate: bool = False,
    duplicate_of_url: str | None = None,
    fallback_map_url: str | None = None,
) -> str:
    """
    HTML-разметка (parse_mode="HTML" на стороне handler). Единый формат для
    тестового объявления при онбординге и для настоящих уведомлений.

    fallback_map_url — ссылка на Google Maps Search (см. map_utils.get_fallback_map_url()),
    передаётся ТОЛЬКО когда точных координат нет и нативная карта (send_location)
    не отправляется отдельным сообщением — тогда адрес в тексте становится
    кликабельной ссылкой как компенсация. Если координаты есть — вызывающий
    код передаёт None (карта уже показана нативно, дублировать ссылкой в
    тексте не нужно — см. map_utils.py).
    """
    lines: list[str] = []

    if is_test:
        lines.append("<b>Это тестовое объявление</b>, далее они будут приходить с дополнительными артефактами.\n")

    if is_duplicate and duplicate_of_url:
        lines.append(f'⚠️ Похоже на уже показанное: <a href="{_encode_url(duplicate_of_url)}">ссылка</a>\n')

    if listing.price_usd:
        price_line = f"${listing.price_usd:.0f}"
    elif listing.price_gel:
        price_line = f"{listing.price_gel:.0f}₾"
    else:
        price_line = "цена не указана"
    lines.append(f"<b>{price_line}</b>")

    if listing.area_sqm:
        lines.append(f"Площадь: {listing.area_sqm:.0f} м²")

    if listing.floor:
        floor_line = str(listing.floor)
        if listing.total_floors:
            floor_line += f"/{listing.total_floors:.0f}"
        lines.append(f"Этаж: {floor_line}")

    if listing.rooms_or_beds:
        lines.append(f"Комнат/спален: {listing.rooms_or_beds}")

    if listing.street_raw:
        if fallback_map_url:
            lines.append(f'📍 <a href="{_encode_url(fallback_map_url)}">{listing.street_raw}</a>')
        else:
            lines.append(f"📍 {listing.street_raw}")

    lines.append(f'\n<a href="{_encode_url(listing.url)}">Смотреть объявление</a>')

    return "\n".join(lines)