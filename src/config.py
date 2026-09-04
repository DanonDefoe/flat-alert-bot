"""
Конфигурация проекта. Загружает переменные окружения из .env (см. .env.example)
и отдаёт их как простой объект Settings — без магии, один раз читаем при импорте.

Использование в других модулях:
    from config import settings
    bot = Bot(token=settings.telegram_bot_token)
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import time
from typing import Optional

from dotenv import load_dotenv

# Ищем .env в корне проекта (на уровень выше src/, если config.py лежит в src/).
# Если структура другая — просто убедись, что .env лежит там, откуда запускаешь main.py,
# load_dotenv() без аргумента и так подхватит .env из текущей рабочей директории.
load_dotenv()


def _parse_hh_mm(value: str, field_name: str) -> time:
    """'05:00' -> time(5, 0). Падает с понятной ошибкой, а не молча берёт что попало —
    ошибка в формате времени в .env должна быть видна сразу при старте, а не через
    час непонятного поведения планировщика."""
    try:
        hours_str, minutes_str = value.split(":")
        return time(hour=int(hours_str), minute=int(minutes_str))
    except (ValueError, AttributeError) as e:
        raise ValueError(
            f"Неверный формат {field_name}: {value!r}. Ожидается 'HH:MM', например '05:00'."
        ) from e


@dataclass(frozen=True)
class Settings:
    telegram_bot_token: str
    database_path: str
    log_level: str
    debug: bool
    default_work_hours_start_utc: time
    default_work_hours_end_utc: time
    developer_telegram_id: Optional[int]


def _load_settings() -> Settings:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token or token == "your_bot_token_here":
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN не задан. Скопируй .env.example в .env и впиши "
            "реальный токен от @BotFather."
        )

    dev_id_raw = os.getenv("DEVELOPER_TELEGRAM_ID", "").strip()
    developer_telegram_id = int(dev_id_raw) if dev_id_raw else None

    return Settings(
        telegram_bot_token=token,
        database_path=os.getenv("DATABASE_PATH", "bot.db"),
        log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
        debug=os.getenv("DEBUG", "False").strip().lower() in ("true", "1", "yes"),
        default_work_hours_start_utc=_parse_hh_mm(
            os.getenv("WORK_HOURS_START_UTC", "05:00"), "WORK_HOURS_START_UTC"
        ),
        default_work_hours_end_utc=_parse_hh_mm(
            os.getenv("WORK_HOURS_END_UTC", "21:00"), "WORK_HOURS_END_UTC"
        ),
        developer_telegram_id=developer_telegram_id,
    )


# Единственная точка входа для остального кода — импортируем settings, а не
# отдельные os.getenv() по всему проекту. Читается один раз при первом импорте модуля.
settings = _load_settings()