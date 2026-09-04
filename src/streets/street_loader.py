"""
Одноразовый скрипт загрузки справочника улиц в БД. Запускать один раз при
разворачивании проекта (или повторно, если streets.json обновится — upsert
безопасен благодаря db.upsert_street()).

Источник streets.json — экспорт списка улиц Тбилиси (три языка: rus/eng/geo)
с сайта ss.ge, предоставленный пользователем. Формат подтверждён на реальных
данных: 1801 запись, streetId уникален у каждой, но у 415 записей (23%)
latitude/longitude отсутствуют (null) — это НЕ ошибка данных, а факт: не для
каждой улицы в справочнике сайта есть координаты. Карта для таких улиц будет
работать через fallback на Google Maps Search по тексту (см. map_utils.py).

Запуск: python streets_loader.py [путь_до_streets.json]
(по умолчанию ищет streets.json рядом с собой)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from db import db


def load_streets(conn, json_path: Path) -> tuple[int, int]:
    """Возвращает (всего_записей, с_координатами)."""
    data = json.loads(json_path.read_text(encoding="utf-8"))

    total = 0
    with_coords = 0
    for item in data:
        db.upsert_street(
            conn,
            street_id=item["streetId"],
            latitude=item.get("latitude"),
            longitude=item.get("longitude"),
            title_rus=item.get("streetTitleRus"),
            title_eng=item.get("streetTitleEng"),
            title_geo=item.get("streetTitleGeo"),
        )
        total += 1
        if item.get("latitude") is not None and item.get("longitude") is not None:
            with_coords += 1

    return total, with_coords


if __name__ == "__main__":
    json_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent / "streets.json"

    if not json_path.exists():
        print(f"Файл не найден: {json_path}")
        sys.exit(1)

    conn = db.get_connection("bot.db")
    db.init_db(conn)

    total, with_coords = load_streets(conn, json_path)

    print(f"Загружено улиц: {total}")
    print(f"  с координатами: {with_coords}")
    print(f"  без координат (fallback на Google Maps Search): {total - with_coords}")
