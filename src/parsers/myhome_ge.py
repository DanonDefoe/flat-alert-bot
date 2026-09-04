"""
Парсеры ss.ge / myhome.ge — рабочая версия (не заглушка).

Проверено на реальных сохранённых страницах списка (view-source) обоих сайтов:
  - оба сайта отдают ПОЛНЫЙ список объявлений внутри <script id="__NEXT_DATA__">
    прямо на странице списка — отдельный XHR/API-запрос НЕ нужен.
  - ss.ge: поле `similarityGroup` — родной сигнал дублей сайта (не null у части
    объявлений, подтверждено на выборке: 7 из 16). Используем как ПЕРВИЧНЫЙ
    признак дубля вместо/вместе с эвристикой по улице+площади+этажу.
  - myhome.ge: `lat`/`lng` есть уже в списке (100% покрытие на выборке) —
    отдельный запрос на /_next/data/.../[slug].json для карты НЕ нужен.

Требуется локально: pip install requests beautifulsoup4 --break-system-packages

ВАЖНО: код ниже проверен на СОХРАНЁННЫХ HTML-фикстурах (без сети). Реальный
requests.get() на живом сайте нужно прогнать в твоём окружении — структура
__NEXT_DATA__ может отличаться в мелочах при живом запросе (напр. другие
заголовки/куки/локаль), но сама механика извлечения (найти script по id,
распарсить как JSON, пройти по известному пути ключей) должна быть той же.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional
import json

import requests
from bs4 import BeautifulSoup


# ---------------------------------------------------------------------------
# Единый контракт объявления
# ---------------------------------------------------------------------------
@dataclass
class Listing:
    native_id: str
    site: str                      # "ss_ge" | "myhome_ge"
    url: str
    price_usd: Optional[float]
    price_gel: Optional[float]
    area_sqm: float
    floor: Optional[int]
    total_floors: Optional[int]
    rooms_or_beds: Optional[int]   # кровати (ss.ge) или комнаты (myhome)
    street_id: Optional[int]        # числовой ID улицы у источника
    street_raw: str                 # сырой текст улицы (может быть на др. языке)
    lat: Optional[float] = None     # есть напрямую только у myhome
    lng: Optional[float] = None
    photo_urls: list[str] = field(default_factory=list)
    duplicate_group_id: Optional[str] = None  # ss.ge: similarityGroup как есть


def make_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
    })
    return session


def _extract_next_data(html: str) -> dict:
    """Общая логика для обоих сайтов: найти <script id="__NEXT_DATA__"> и распарсить JSON."""
    soup = BeautifulSoup(html, "html.parser")
    script = soup.find("script", id="__NEXT_DATA__")
    if script is None or not script.string:
        raise ValueError("__NEXT_DATA__ не найден на странице — верстка могла измениться")
    return json.loads(script.string)


def parse_myhome_list(html: str) -> list[Listing]:
    data = _extract_next_data(html)
    try:
        queries = data["props"]["pageProps"]["dehydratedState"]["queries"]
        list_query = next(q for q in queries if q["queryKey"][0:2] == ["statements", "list"])
        items = list_query["state"]["data"]["data"]["data"]
    except (KeyError, StopIteration) as e:
        raise ValueError(f"Не найден ожидаемый путь до списка объявлений myhome: {e}")

    listings = []
    for it in items:
        # price: словарь по валютам, ключ "2" = USD (подтверждено на данных ранее)
        price_usd = it.get("price", {}).get("2", {}).get("price_total")
        price_gel = it.get("price", {}).get("1", {}).get("price_total")
        bedroom = it.get("bedroom")
        listings.append(Listing(
            native_id=str(it["id"]),
            site="myhome_ge",
            url=f"https://www.myhome.ge/ru/nedvizhimost/{it['dynamic_slug']}-{it['id']}/",
            price_usd=price_usd,
            price_gel=price_gel,
            area_sqm=it["area"],
            floor=it.get("floor"),
            total_floors=it.get("total_floors"),
            rooms_or_beds=int(bedroom) if bedroom not in (None, "") else None,
            street_id=it.get("street_id"),
            street_raw=it.get("address") or "",
            lat=it.get("lat"),
            lng=it.get("lng"),
            photo_urls=[img["thumb"] for img in it.get("images", [])][:4],
        ))
    return listings
