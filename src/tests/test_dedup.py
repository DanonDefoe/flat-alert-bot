"""
Регрессионные тесты dedup.py. Запуск: python3 test_dedup.py
Использует in-memory SQLite — сеть/файлы не нужны.
"""

import sys
sys.path.insert(0, ".")

from db import db
from src.dedup import dedup
from parsers.base import Listing


def make_listing(native_id, site="ss_ge", street="ул. Политковская", area=50,
                  floor=4, beds=1, dup_group=None):
    return Listing(
        native_id=native_id, site=site, url=f"https://example.com/{native_id}",
        price_usd=550, price_gel=1440, area_sqm=area, floor=floor, total_floors=10,
        rooms_or_beds=beds, street_id=157, street_raw=street, photo_urls=[],
        duplicate_group_id=dup_group,
    )


def fresh_conn():
    conn = db.get_connection(":memory:")
    db.init_db(conn)
    db.upsert_user(conn, telegram_id=123)
    sub_id = db.add_subscription(
        conn, user_id=123, site="ss_ge", filter_url="x",
        interval_min_sec=1200, interval_max_sec=1800,
    )
    return conn, sub_id


def test_two_distinct_listings_are_not_duplicates():
    conn, sub_id = fresh_conn()
    r = dedup.process_new_listings(conn, sub_id, [
        make_listing("AAA", area=50, floor=4, beds=1),
        make_listing("BBB", area=80, floor=7, beds=2),
    ])
    assert len(r) == 2
    assert all(not x.is_duplicate for x in r)


def test_already_seen_listing_is_dropped_entirely():
    conn, sub_id = fresh_conn()
    dedup.process_new_listings(conn, sub_id, [make_listing("AAA")])
    r = dedup.process_new_listings(conn, sub_id, [make_listing("AAA")])
    assert len(r) == 0


def test_similarity_group_catches_duplicate_heuristic_would_miss():
    conn, sub_id = fresh_conn()
    dedup.process_new_listings(conn, sub_id, [
        make_listing("DDD", street="ул. Тестовая", area=60, floor=2, beds=1, dup_group="G1"),
    ])
    r = dedup.process_new_listings(conn, sub_id, [
        make_listing("EEE", street="ул. Тестовая", area=95, floor=9, beds=3, dup_group="G1"),
    ])
    assert r[0].is_duplicate
    assert r[0].duplicate_of_native_id == "DDD"


def test_myhome_heuristic_matches_within_area_tolerance():
    conn, sub_id = fresh_conn()
    dedup.process_new_listings(conn, sub_id, [
        make_listing("MY_1", site="myhome_ge", street="S1", area=40, floor=8, beds=2),
    ])
    r = dedup.process_new_listings(conn, sub_id, [
        make_listing("MY_2", site="myhome_ge", street="S1", area=44, floor=8, beds=2),
    ])
    assert r[0].is_duplicate


def test_myhome_heuristic_rejects_beyond_area_tolerance():
    conn, sub_id = fresh_conn()
    dedup.process_new_listings(conn, sub_id, [
        make_listing("ISO_1", site="myhome_ge", street="S_ISOLATED", area=40, floor=8, beds=2),
    ])
    r = dedup.process_new_listings(conn, sub_id, [
        make_listing("ISO_2", site="myhome_ge", street="S_ISOLATED", area=48, floor=8, beds=2),
    ])
    assert not r[0].is_duplicate


def test_myhome_heuristic_rejects_when_room_count_differs():
    conn, sub_id = fresh_conn()
    dedup.process_new_listings(conn, sub_id, [
        make_listing("RM_1", site="myhome_ge", street="S2", area=41, floor=8, beds=2),
    ])
    r = dedup.process_new_listings(conn, sub_id, [
        make_listing("RM_2", site="myhome_ge", street="S2", area=41, floor=8, beds=3),
    ])
    assert not r[0].is_duplicate


def test_area_tolerance_drift_across_chain():
    """ВАЖНО: документирует сознательное поведение, не баг.
    Сравнение идёт с КАЖДЫМ уже увиденным объявлением, а не только с первым
    в цепочке — поэтому допуск может "накапливаться" на цепочке близких
    значений площади (40 -> 44 -> 48), хотя 40 и 48 сами по себе вне допуска.
    Если это нежелательно — нужно менять find_duplicate_by_heuristic на
    сравнение только с "корневым" (первым) объявлением цепочки."""
    conn, sub_id = fresh_conn()
    dedup.process_new_listings(conn, sub_id, [
        make_listing("X1", site="myhome_ge", street="Drift", area=40, floor=8, beds=2),
    ])
    r2 = dedup.process_new_listings(conn, sub_id, [
        make_listing("X2", site="myhome_ge", street="Drift", area=44, floor=8, beds=2),
    ])
    r3 = dedup.process_new_listings(conn, sub_id, [
        make_listing("X3", site="myhome_ge", street="Drift", area=48, floor=8, beds=2),
    ])
    assert r2[0].is_duplicate and r2[0].duplicate_of_native_id == "X1"
    assert r3[0].is_duplicate and r3[0].duplicate_of_native_id == "X2"  # не X1!


if __name__ == "__main__":
    tests = [v for k, v in list(globals().items()) if k.startswith("test_")]
    passed = 0
    for t in tests:
        t()
        print(f"  OK  {t.__name__}")
        passed += 1
    print(f"\n{passed}/{len(tests)} тестов прошли")
