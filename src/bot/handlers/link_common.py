"""
Общая логика валидации ссылки-фильтра. Вынесена отдельно от handlers, потому
что нужна в двух разных сценариях: онбординг (handlers/start.py) и
редактирование существующей подписки (handlers/link.py, ещё не написан) —
дублировать эту логику в обоих местах было бы ошибкой.

Обёртка над parsers_poc + fetcher: определяет сайт по домену, синхронно (через
поток, см. ниже) загружает HTML, парсит его, возвращает список объявлений.
Все ошибки — это конкретные исключения, а не общий Exception, чтобы handler
мог показать пользователю разное сообщение под разные причины сбоя.
"""

from __future__ import annotations

import asyncio
from urllib.parse import urlparse

from fetcher import fetch_html
from parsers.base import Listing
from src.parsers.ss_ge import parse_ss_ge_list
from src.parsers.myhome_ge import parse_myhome_list


class UnsupportedSiteError(Exception):
    """Ссылка не с ss.ge и не с myhome.ge."""


class NoListingsFoundError(Exception):
    """Ссылка распозналась и загрузилась, но объявлений в выдаче нет
    (например, слишком узкий фильтр)."""


# Домен -> внутреннее имя сайта, как везде в проекте (db_schema.sql CHECK,
# parsers_poc.Listing.site и т.д.)
_SITE_BY_DOMAIN = {
    "ss.ge": "ss_ge",
    "myhome.ge": "myhome_ge",
}


def detect_site(url: str) -> str:
    """'https://home.ss.ge/...' -> 'ss_ge'. Бросает UnsupportedSiteError,
    если домен не из двух поддерживаемых."""
    netloc = urlparse(url).netloc.lower()
    for domain, site in _SITE_BY_DOMAIN.items():
        if domain in netloc:
            return site
    raise UnsupportedSiteError(url)


async def validate_link(session, url: str) -> tuple[str, list[Listing]]:
    """
    Главная точка входа. Возвращает (site, listings) при успехе.

    Может бросить:
      - UnsupportedSiteError   — домен не ss.ge/myhome.ge
      - fetcher.FetchError     — сеть/таймаут/403/429/5xx (см. fetcher.py)
      - ValueError             — __NEXT_DATA__ не найден или структура не та
                                  (см. parsers_poc.py) — верстка сайта изменилась
      - NoListingsFoundError   — страница загрузилась, но объявлений 0

    Важно про блокировку event loop: fetch_html() внутри использует синхронный
    requests, а не aiohttp — вызываем его через asyncio.to_thread(), чтобы не
    подвешивать весь бот (все остальные пользователи) на время сетевого
    запроса к ss.ge/myhome.ge. Это относится ко всем местам, где вызывается
    validate_link() — сами не блокируем event loop, thread уже внутри.
    """
    site = detect_site(url)  # синхронно, не сеть — можно не в потоке

    html = await asyncio.to_thread(fetch_html, session, url)

    if site == "ss_ge":
        listings = parse_ss_ge_list(html)
    else:
        listings = parse_myhome_list(html)

    if not listings:
        raise NoListingsFoundError(url)

    return site, listings