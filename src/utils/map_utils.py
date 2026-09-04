"""
Модуль карты.

Правка после первого варианта (был: единая ссылка на Google Maps в тексте
адреса): теперь при наличии точных координат отправляется НАТИВНАЯ карта
Telegram (bot.send_location() / message.answer_location()) отдельным
сообщением — интерактивный виджет прямо в чате, без перехода куда-либо.
Пользователь сразу видит район/окружение объявления, не открывая ни Google
Maps, ни само объявление. Текстовая ссылка на Google Maps Search остаётся
ТОЛЬКО как fallback для случая, когда координат нет вообще (send_location
физически невозможен без lat/lng — Telegram Bot API не принимает текстовый
адрес для этого метода).

Источники координат по сайтам:
  - myhome.ge: lat/lng приходят напрямую в данных объявления (100% покрытие
    подтверждено на реальных данных, см. parsers_poc.py).
  - ss.ge: только street_id (числовой). ПОДТВЕРЖДЕНО на реальных данных:
    это тот же самый street_id, что использует справочник streets.json
    (streetId=1136 -> "Dolidze st." совпало один в один с данными реального
    объявления) — прямой lookup в таблице streets, без текстового
    сопоставления/алиасов. Точность — на уровне улицы, не дома.
    23% улиц в справочнике (415 из 1801, подтверждено на реальном файле) не
    имеют координат вообще (latitude/longitude = null у источника, это факт
    данных, не наша ошибка) — для них get_coordinates() вернёт None, и нужно
    использовать get_fallback_map_url().

Два вызова — два разных механизма доставки на стороне handlers:
  coords = get_coordinates(conn, listing)
  if coords:
      await bot.send_location(chat_id, latitude=coords[0], longitude=coords[1])
      fallback_url = None  # в текст объявления ссылка не нужна — карта уже показана
  else:
      fallback_url = get_fallback_map_url(listing)  # None, если и street_raw пуст
"""

from __future__ import annotations

import sqlite3
from urllib.parse import quote
from typing import Optional

from db import db
from parsers.base import Listing


def get_coordinates(conn: sqlite3.Connection, listing: Listing) -> Optional[tuple[float, float]]:
    """
    Точные координаты для send_location, если есть. Порядок попыток:
      1. Готовые lat/lng у самого объявления (myhome.ge — 100% покрытие).
      2. Lookup по street_id в справочнике (ss.ge — точное совпадение ID,
         подтверждено на реальных данных).
      3. Текстовый fallback по street_raw (db.get_street_by_title) — на
         случай, когда street_id отсутствует у объявления вообще, ИЛИ
         найденная по ID запись сама не имеет координат (23% улиц в
         справочнике без координат, см. докстринг модуля), но точно такое
         же название почему-то встречается под ДРУГИМ street_id с
         координатами (расхождение в самом справочнике/данных источника).
    None — координат нет ни одним из трёх путей, тогда вместо нативной карты
    нужно использовать get_fallback_map_url().
    """
    if listing.lat is not None and listing.lng is not None:
        return listing.lat, listing.lng

    if listing.street_id is not None:
        street = db.get_street(conn, listing.street_id)
        if street is not None and street["latitude"] is not None and street["longitude"] is not None:
            return street["latitude"], street["longitude"]

    if listing.street_raw:
        street = db.get_street_by_title(conn, listing.street_raw)
        if street is not None:
            return street["latitude"], street["longitude"]

    return None


def get_fallback_map_url(listing: Listing) -> Optional[str]:
    """
    Используется ТОЛЬКО когда get_coordinates() вернул None — координат нет
    вообще, нативную карту отправить нельзя (Telegram send_location требует
    lat/lng, текстовый адрес не принимает). Вместо неё адрес в тексте
    объявления становится кликабельной ссылкой на Google Maps Search по
    тексту адреса — не требует db_conn, работает по чистому тексту, включая
    грузинский/кириллицу. None, если и street_raw пуст — совсем нечего показать.
    """
    if listing.street_raw:
        query = quote(f"{listing.street_raw}, Тбилиси")
        return f"https://www.google.com/maps/search/?api=1&query={query}"
    return None
