"""
Конвертация времени между тбилисским (UTC+4, в Грузии нет перехода на летнее
время) и UTC. Используется в меню "Изменить рабочее окно" (см.
architecture_and_plan.md, раздел 7): пользователь вводит время по Тбилиси,
хранится в БД всегда в UTC.

Работаем только с time-of-day (часы:минуты), без дат — рабочее окно это
повторяющийся ежедневный интервал, не привязанный к конкретному дню. Поэтому
арифметика идёт по модулю 24 часов, а не через полноценный datetime/timezone.
"""

from __future__ import annotations

from datetime import time

TBILISI_UTC_OFFSET_HOURS = 4


def parse_hh_mm(text: str) -> time:
    """'09:00' -> time(9, 0). Бросает ValueError с понятным сообщением на
    любой некорректный ввод — вызывающий код (handler) ловит именно ValueError."""
    text = text.strip()
    parts = text.split(":")
    if len(parts) != 2:
        raise ValueError(f"Ожидается формат ЧЧ:ММ, получено: {text!r}")

    hours_str, minutes_str = parts
    if not (hours_str.isdigit() and minutes_str.isdigit()):
        raise ValueError(f"Часы и минуты должны быть числами: {text!r}")

    hours, minutes = int(hours_str), int(minutes_str)
    if not (0 <= hours <= 23):
        raise ValueError(f"Часы должны быть от 00 до 23: {text!r}")
    if not (0 <= minutes <= 59):
        raise ValueError(f"Минуты должны быть от 00 до 59: {text!r}")

    return time(hour=hours, minute=minutes)


def format_hh_mm(t: time) -> str:
    return f"{t.hour:02d}:{t.minute:02d}"


def _shift_time(t: time, offset_hours: int) -> time:
    """Сдвиг time-of-day на N часов с переносом через полночь (по модулю 24ч).
    Например, tbilisi 01:00 минус 4 часа -> UTC 21:00 (предыдущего дня, но нам
    дата не важна — это ежедневное повторяющееся окно)."""
    total_minutes = t.hour * 60 + t.minute
    shifted_minutes = (total_minutes + offset_hours * 60) % (24 * 60)
    return time(hour=shifted_minutes // 60, minute=shifted_minutes % 60)


def tbilisi_to_utc(t: time) -> time:
    return _shift_time(t, -TBILISI_UTC_OFFSET_HOURS)


def utc_to_tbilisi(t: time) -> time:
    return _shift_time(t, TBILISI_UTC_OFFSET_HOURS)