from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
import re

from parsers.base import Listing, extract_next_data


def _parse_ss_ge_datetime(raw: Optional[str]) -> Optional[datetime]:
    """ss.ge отдаёт ISO8601 со смещением, напр. '2026-08-27T12:16:18.0907505+04:00'
    — обрати внимание, 7 знаков после точки у секунд, а не 6. datetime в Python
    умеет максимум 6 (микросекунды) — без обрезки fromisoformat() падает с
    ValueError на каждой такой строке. Обрезаем лишние цифры перед парсингом."""
    if not raw:
        return None
    match = re.match(r"^(.*?\.\d{1,6})\d*([+-]\d{2}:\d{2})$", raw)
    if match:
        raw = match.group(1) + match.group(2)
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    return dt.astimezone(timezone.utc)


def parse_ss_ge_list(html: str) -> list[Listing]:
    """
    Список объявлений целиком лежит в __NEXT_DATA__ прямо на странице списка —
    подтверждено на реальных данных, отдельный XHR/API-запрос не нужен.

    Известно точно:
      - streetId у объявления совпадает 1:1 с streetId в справочнике улиц
        (streets.json) — подтверждено на реальных данных.
      - similarityGroup — родной признак дублей сайта (не null у части
        объявлений).
      - orderDate (не createDate!) — используется как posted_at: это то же
        поле, по которому сайт сам сортирует выдачу и показывает "X часов
        назад" в своём интерфейсе. У поднятых повторно объявлений orderDate
        обновляется, а createDate остаётся исходной датой первой публикации.
    """
    data = extract_next_data(html)
    try:
        items = data["props"]["pageProps"]["applicationList"]["realStateItemModel"]
    except KeyError as e:
        raise ValueError(f"Не найден ожидаемый путь до списка объявлений ss.ge: {e}")

    listings = []
    for it in items:
        addr = it["address"]
        listings.append(Listing(
            native_id=str(it["applicationId"]),
            site="ss_ge",
            url=f"https://home.ss.ge/ru/недвижимость/{it['detailUrl']}",
            price_usd=it["price"].get("priceUsd"),
            price_gel=it["price"].get("priceGeo"),
            area_sqm=it["totalArea"],
            floor=int(it["floorNumber"]) if it.get("floorNumber") else None,
            total_floors=int(it["totalAmountOfFloor"]) if it.get("totalAmountOfFloor") else None,
            rooms_or_beds=it.get("numberOfBedrooms"),
            street_id=addr.get("streetId"),
            street_raw=addr.get("streetTitle") or "",
            photo_urls=[img["fileName"] for img in it.get("appImages", [])][:4],
            duplicate_group_id=str(it["similarityGroup"]) if it.get("similarityGroup") else None,
            posted_at=_parse_ss_ge_datetime(it.get("orderDate")),
        ))
    return listings
