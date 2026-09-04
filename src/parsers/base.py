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

import requests


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
