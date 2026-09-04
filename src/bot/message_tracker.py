"""
Трекер отправленных сообщений. Не оборачивает сами вызовы send/answer — просто
регистрирует уже отправленное сообщение постфактум. Это сознательный выбор:
и message.answer(), и bot.send_message(), и bot.send_media_group() уже
возвращают готовый объект(ы) Message с chat.id/message_id — простое
"зарегистрировать то, что уже отправлено" требует меньше переделок в
существующем коде, чем полная замена всех вызовов на send-обёртки.

Используется в паре с cleanup.py: там периодическая задача находит всё, что
зарегистрировано здесь и старше 3 суток (кроме is_favorite=True), и удаляет
через bot.delete_message().

is_favorite=True — сообщения из списка "⭐ Избранное" (см.
handlers/menu.py:show_favorites) — они НЕ участвуют в автоудалении, это и
есть постоянное хранилище, которое юзер сам явно попросил сохранить.
"""

from __future__ import annotations

from src.db import db


def track(db_conn, msg, is_favorite: bool = False) -> None:
    """msg — любой объект с .chat.id и .message_id (aiogram Message)."""
    db.track_sent_message(db_conn, msg.chat.id, msg.message_id, is_favorite=is_favorite)


def track_many(db_conn, msgs, is_favorite: bool = False) -> None:
    """Для bot.send_media_group() — возвращает список Message, регистрируем
    все (при удалении альбома каждое фото нужно удалять как отдельное
    сообщение — Telegram не даёт удалить альбом одним вызовом)."""
    for m in msgs:
        track(db_conn, m, is_favorite=is_favorite)