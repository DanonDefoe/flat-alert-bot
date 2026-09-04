"""
Точка входа бота. Собирает всё написанное на предыдущих шагах:
  - config.py / logger.py — конфигурация и логирование
  - db.py — подключение к БД, инициализация схемы
  - start.py, menu.py, listing.py, errors.py — роутеры с handlers

Порядок dp.include_router() важен: errors.router — ПОСЛЕДНИЙ (см. докстринг
errors.py — это его собственное требование к порядку подключения, не наша
прихоть).

Про db_conn: передаётся в dp.start_polling(bot, db_conn=db_conn) — это
стандартный механизм aiogram 3.x, extra kwargs в start_polling становятся
доступны как параметры в любом handler, где объявлены с таким же именем
(так это используется в start.py/menu.py/listing.py — там db_conn просто
берётся как параметр функции, aiogram сам его туда подставляет).

ВАЖНО про структуру импортов: сейчас все модули (start.py, menu.py и т.д.)
лежат рядом друг с другом, плоско — так же, как в /mnt/user-data/outputs при
разработке. Когда переносишь в структуру PyCharm-проекта из
PROJECT_STRUCTURE.md (src/bot/handlers/start.py и т.д.) — импорты ниже нужно
поправить на путь до пакета (например, from bot.handlers import start),
иначе будет ModuleNotFoundError. Сам код handlers при этом не меняется.

ВАЖНО про MemoryStorage: FSM-состояния (на каком шаге онбординга находится
пользователь и т.п.) хранятся в памяти процесса — при перезапуске бота все
незавершённые сценарии (кто-то на середине ввода ссылки) сбрасываются.
Для 3-10 пользователей и коротких сценариев это приемлемо для MVP; если
станет проблемой — meняется на RedisStorage/SQLiteStorage без изменений в
самих handlers (FSMContext API одинаковый).
"""

from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand

from db import db
from bot.handlers import commands
from bot.handlers import start
from bot.handlers import menu
from bot.handlers import listing
from bot.handlers import errors
from scheduler import jobs
from config import settings
from logger import setup_logging
from parsers.base import make_session

logger = logging.getLogger(__name__)


def create_dispatcher() -> Dispatcher:
    """Вынесено отдельной функцией от main() — чтобы можно было проверить
    порядок и полноту подключённых роутеров в тестах, не запуская реальный
    polling (который требует живого токена и сети)."""
    dp = Dispatcher(storage=MemoryStorage())

    # commands.router — ПЕРВЫМ: команда /menu и кнопка "☰ Меню" должны
    # перехватываться раньше любых FSM-состояний, привязанных к конкретному
    # тексту (см. докстринг commands.py — иначе "/menu", отправленный посреди
    # ввода ссылки/заметки/времени, был бы съеден тем обработчиком).
    dp.include_router(commands.router)
    dp.include_router(start.router)
    dp.include_router(menu.router)
    dp.include_router(listing.router)
    dp.include_router(errors.router)  # ПОСЛЕДНИМ — см. докстринг файла и errors.py

    return dp


async def main() -> None:
    setup_logging()
    logger.info("Запуск бота...")

    db_conn = db.get_connection(settings.database_path)
    db.init_db(db_conn)
    logger.info("БД инициализирована: %s", settings.database_path)

    bot = Bot(token=settings.telegram_bot_token)
    dp = create_dispatcher()

    # Общая HTTP-сессия для планировщика — та же, что использует link_common.py
    # для валидации ссылок (make_session из parsers_poc.py), с одинаковыми
    # заголовками. Отдельная от той, что создана внутри start.py/menu.py как
    # module-level объект — это два независимых экземпляра requests.Session
    # с одинаковыми настройками; не критично для 3-10 пользователей, но при
    # желании унифицировать — переносится в общий workflow_data по той же
    # схеме, что и db_conn (см. докстринг файла).
    http_session = make_session()
    scheduler = jobs.setup_scheduler(bot, db_conn, http_session)

    try:
        # drop_pending_updates=True — не разгребаем накопившиеся апдейты за
        # время, пока бот не работал (например, ты его перезапускаешь во время
        # разработки в PyCharm) — иначе после каждого запуска бот "вспомнит"
        # и обработает всё, что пользователи прислали, пока он был выключен.
        await bot.delete_webhook(drop_pending_updates=True)
        await bot.set_my_commands([
            BotCommand(command="start", description="Начать / приветствие"),
            BotCommand(command="menu", description="Открыть меню"),
        ])
        scheduler.start()
        logger.info("Планировщик запущен, тик каждые %d сек", jobs.TICK_INTERVAL_SEC)
        await dp.start_polling(bot, db_conn=db_conn)
    finally:
        logger.info("Остановка бота, закрываю соединения...")
        scheduler.shutdown(wait=False)
        await bot.session.close()
        db_conn.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Бот остановлен вручную (Ctrl+C).")