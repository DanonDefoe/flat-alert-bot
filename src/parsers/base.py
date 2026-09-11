from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
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
    posted_at: Optional[datetime] = None  # UTC, для фичи "последние N часов"


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


def extract_next_data(html: str) -> dict:
    """Общая логика для обоих сайтов: найти <script id="__NEXT_DATA__"> и распарсить JSON."""
    soup = BeautifulSoup(html, "html.parser")
    script = soup.find("script", id="__NEXT_DATA__")
    if script is None or not script.string:
        raise ValueError("__NEXT_DATA__ не найден на странице — верстка могла измениться")
    return json.loads(script.string)
