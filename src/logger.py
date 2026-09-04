"""
Настройка логирования для всего проекта.

Использование:
    from logger import setup_logging
    setup_logging()  # вызывается один раз в main.py, до всего остального

    # в любом другом модуле дальше — обычный стандартный logging:
    import logging
    logger = logging.getLogger(__name__)
    logger.info("что-то произошло")
"""

from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path

from config import settings

LOG_DIR = Path("logs")
LOG_FILE = LOG_DIR / "bot.log"

# Не даём стороннним библиотекам (aiogram, urllib3 и т.д.) заваливать логи своим DEBUG,
# даже если у нас самих LOG_LEVEL=DEBUG — это отдельная настройка, не общий уровень.
# apscheduler.executors.default отдельно: он пишет "Running job.../executed
# successfully" на КАЖДЫЙ тик планировщика (раз в минуту, см. jobs.py), даже
# когда тикать реально нечего — это не ошибка и не предупреждение, приглушаем
# до WARNING, иначе за час набегает 60+ строк чистого шума.
NOISY_LIBRARIES = ("urllib3", "aiogram.event", "apscheduler.executors.default", "scheduler.jobs")


def setup_logging() -> None:
    LOG_DIR.mkdir(exist_ok=True)

    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    root_logger = logging.getLogger()
    root_logger.setLevel(settings.log_level)

    # Консоль — то, что видно в PyCharm при запуске/дебаге.
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    # Файл с ротацией — чтобы не разрастался бесконечно.
    # 5 файлов по 5 МБ: старые логи не теряются сразу, но и диск не забивается.
    file_handler = logging.handlers.RotatingFileHandler(
        LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)

    for lib_name in NOISY_LIBRARIES:
        logging.getLogger(lib_name).setLevel(logging.WARNING)

    logging.getLogger(__name__).info(
        "Логирование настроено: уровень=%s, файл=%s", settings.log_level, LOG_FILE
    )