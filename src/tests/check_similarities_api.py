"""
Проверка реального ответа api-gateway.ss.ge/v1/RealEstate/similarities.

Цель: понять точную структуру JSON, прежде чем писать финальный парсер
для фичи "Показать дубликаты дешевле". Ничего не угадываем — печатаем как есть.

Запуск: python check_similarities_api.py <group_id>
Пример: python check_similarities_api.py 36497190

Если своего group_id под рукой нет — возьми любой applicationId с непустым
similarityGroup из уже собранных данных ss.ge (например, из parse_ss_ge_list()
на реальном фильтре — там есть Listing.duplicate_group_id).
"""

import sys
import json

import requests

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
    # На всякий случай — некоторые внутренние API ss.ge проверяют Referer,
    # как и статика с фото (мы это уже видели раньше в разведке).
    "Referer": "https://home.ss.ge/",
}


def main():
    if len(sys.argv) < 2:
        print("Использование: python check_similarities_api.py <group_id>")
        sys.exit(1)

    group_id = sys.argv[1]
    url = f"https://api-gateway.ss.ge/v1/RealEstate/similarities?group={group_id}"

    print(f"Запрос: {url}\n")

    try:
        resp = requests.get(url, headers=DEFAULT_HEADERS, timeout=10)
    except requests.exceptions.RequestException as e:
        print(f"✗ Ошибка запроса: {e}")
        sys.exit(1)

    print(f"Статус: {resp.status_code}")
    print(f"Content-Type: {resp.headers.get('Content-Type')}\n")

    if resp.status_code != 200:
        print("✗ Не 200 — печатаю тело ответа как есть (может быть html с ошибкой):")
        print(resp.text[:2000])
        sys.exit(1)

    try:
        data = resp.json()
    except ValueError:
        print("✗ Ответ не является валидным JSON. Сырой текст:")
        print(resp.text[:2000])
        sys.exit(1)

    print("✓ Валидный JSON. Полная структура (topLevel keys):")
    if isinstance(data, dict):
        print(list(data.keys()))
    else:
        print(f"  (не dict, а {type(data)})")

    print("\n--- Полный ответ (первые 3000 символов) ---")
    print(json.dumps(data, ensure_ascii=False, indent=2)[:3000])

    # Пробуем несколько вероятных путей до массива объявлений — печатаем что нашли,
    # ничего не выбираем "по умолчанию" молча.
    print("\n--- Попытка найти массив similarApplicationsModel ---")
    candidates = []
    if isinstance(data, dict):
        for key in data:
            if "similar" in key.lower():
                candidates.append(key)

    if not candidates:
        print("✗ Ключ с 'similar' в названии не найден на верхнем уровне.")
        print("  Открой ответ выше руками и найди, где лежит список объявлений.")
    else:
        for key in candidates:
            items = data[key]
            print(f"✓ Найден ключ '{key}', тип: {type(items)}, длина: {len(items) if hasattr(items, '__len__') else 'N/A'}")
            if isinstance(items, list) and items:
                print(f"\n  Пример первого элемента:")
                print(json.dumps(items[0], ensure_ascii=False, indent=4))
                print(f"\n  Ключи первого элемента: {list(items[0].keys()) if isinstance(items[0], dict) else 'не dict'}")

                # Пробуем найти price и applicationId внутри элемента
                first = items[0]
                if isinstance(first, dict):
                    price_related = [k for k in first if "price" in k.lower()]
                    id_related = [k for k in first if "id" in k.lower()]
                    print(f"\n  Поля, похожие на цену: {price_related}")
                    print(f"  Поля, похожие на ID: {id_related}")


if __name__ == "__main__":
    main()