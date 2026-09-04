"""
Модуль сетевых запросов с retry и backoff.

Отдельный слой между планировщиком и парсерами — парсеры работают
только с html-строкой и не знают про сеть. Это упрощает тестирование:
парсеры гоняются на фикстурах, fetcher — отдельно.

Поведение при ошибках:
  - Таймаут / сеть недоступна: retry с экспоненциальным backoff
    (2 → 4 → 8 секунд), после MAX_RETRIES — бросаем FetchError.
  - 403 / 429 (антибот): не ретраим агрессивно — бросаем сразу,
    планировщик сам перенесёт следующую проверку.
  - 5xx: ретраим так же, как таймаут.

Глобальный троттлинг (минимальный зазор между запросами к одному домену)
реализован через словарь _last_request_time. Защищает от случайного
одновременного срабатывания нескольких подписок на один сайт.
"""

from __future__ import annotations

import time
import logging
from urllib.parse import urlparse
from typing import Optional

import requests
from requests.exceptions import Timeout, ConnectionError as ReqConnectionError

logger = logging.getLogger(__name__)

# Минимальная пауза между двумя любыми запросами к одному домену (секунды).
MIN_DOMAIN_INTERVAL_SEC = 3.0

MAX_RETRIES = 3
BACKOFF_BASE_SEC = 2  # задержки: 2 → 4 → 8 секунд

# Хранит время последнего запроса к каждому домену (domain -> timestamp).
_last_request_time: dict[str, float] = {}


class FetchError(Exception):
    """Поднимается когда после всех попыток получить ответ не удалось."""
    def __init__(self, url: str, reason: str):
        super().__init__(f"Не удалось получить {url}: {reason}")
        self.url = url
        self.reason = reason


def _throttle(domain: str) -> None:
    """Ждём, если к этому домену обращались слишком недавно."""
    last = _last_request_time.get(domain)
    if last:
        elapsed = time.monotonic() - last
        wait = MIN_DOMAIN_INTERVAL_SEC - elapsed
        if wait > 0:
            logger.debug("Throttle: ждём %.1f сек перед запросом к %s", wait, domain)
            time.sleep(wait)


def fetch_html(session: requests.Session, url: str, timeout: int = 15) -> str:
    """
    Загрузить HTML по URL с retry и глобальным троттлингом по домену.
    Возвращает resp.text или бросает FetchError.
    """
    domain = urlparse(url).netloc

    for attempt in range(1, MAX_RETRIES + 1):
        _throttle(domain)
        try:
            resp = session.get(url, timeout=timeout)
            _last_request_time[domain] = time.monotonic()

            if resp.status_code == 200:
                return resp.text

            if resp.status_code in (403, 429):
                # Антибот — не ретраим, сразу сообщаем.
                raise FetchError(url, f"HTTP {resp.status_code} — вероятно антибот-защита")

            if resp.status_code >= 500:
                logger.warning("Попытка %d/%d: HTTP %d для %s", attempt, MAX_RETRIES, resp.status_code, url)
                # Идём в retry ниже.
            else:
                # 4xx кроме 403/429 — проблема в URL, не в сети, ретраить бессмысленно.
                raise FetchError(url, f"HTTP {resp.status_code}")

        except (Timeout, ReqConnectionError) as e:
            logger.warning("Попытка %d/%d: %s для %s", attempt, MAX_RETRIES, type(e).__name__, url)
            _last_request_time[domain] = time.monotonic()

        # Ждём перед следующей попыткой (exponential backoff).
        if attempt < MAX_RETRIES:
            wait = BACKOFF_BASE_SEC * (2 ** (attempt - 1))
            logger.debug("Backoff: ждём %d сек", wait)
            time.sleep(wait)

    raise FetchError(url, f"Превышено число попыток ({MAX_RETRIES})")