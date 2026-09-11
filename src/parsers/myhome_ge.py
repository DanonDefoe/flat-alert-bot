from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Optional

from parsers.base import Listing, extract_next_data


def _parse_myhome_datetime(raw: Optional[str]) -> Optional[datetime]:
    """myhome отдаёт наивную строку без таймзоны, напр. '2026-08-27 09:00:07' —
    подтверждено на реальных данных (поле 'last_updated', единственное
    дата/время-подобное поле в объекте объявления — отдельного поля именно
    'дата создания' у myhome нет, last_updated — лучший доступный прокси, но
    учти: если объявление отредактировали, эта дата обновится, даже если сама
    квартира выставлена раньше). Сайт грузинский — предполагаем тбилисское
    время (UTC+4), без перехода на летнее."""
    if not raw:
        return None
    try:
        dt = datetime.strptime(raw, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None
    return dt.replace(tzinfo=timezone(timedelta(hours=4))).astimezone(timezone.utc)


def parse_myhome_list(html: str) -> list[Listing]:
    """
    Список объявлений целиком лежит в __NEXT_DATA__ (dehydratedState.queries
    -> ["statements","list"] -> state.data.data.data) прямо на странице
    списка — подтверждено на реальных данных, отдельный запрос не нужен.

    Известно точно:
      - lat/lng приходят напрямую в списке — 100% покрытие на реальных данных,
        отдельный запрос на детальную страницу объявления не нужен.
      - last_updated — единственное дата/время-подобное поле, используется
        как posted_at (см. _parse_myhome_datetime).
    """
    data = extract_next_data(html)
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
            posted_at=_parse_myhome_datetime(it.get("last_updated")),
        ))
    return listings
