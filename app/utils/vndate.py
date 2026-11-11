"""Hiểu các mốc thời gian nói bằng tiếng Việt: "10h ngày mai", "21 giờ tối nay", "thứ 6", "20/11"...

Chỉ dùng cho chế độ demo (khi có Gemini, mô hình tự đổi thời hạn sang ISO 8601).
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta

from .text import norm

_WEEKDAYS = {
    "thu 2": 0,
    "thu hai": 0,
    "thu 3": 1,
    "thu ba": 1,
    "thu 4": 2,
    "thu tu": 2,
    "thu 5": 3,
    "thu nam": 3,
    "thu 6": 4,
    "thu sau": 4,
    "thu 7": 5,
    "thu bay": 5,
    "chu nhat": 6,
    "cn": 6,
}
DEFAULT_HOUR = 22


def parse_vn_deadline(text: str, now: datetime) -> datetime | None:
    """Trả về thời điểm (cùng múi giờ với `now`) hoặc None nếu không thấy mốc thời gian."""
    n = f" {norm(text)} "
    day: datetime | None = None

    if m := re.search(r"\b(\d{1,2})[/-](\d{1,2})(?:[/-](\d{2,4}))?\b", n):
        d, mo = int(m.group(1)), int(m.group(2))
        year = int(m.group(3)) if m.group(3) else now.year
        if year < 100:
            year += 2000
        try:
            day = now.replace(year=year, month=mo, day=d)
        except ValueError:
            day = None
    elif any(k in n for k in (" ngay kia ", " ngay mot ", " mot ")):
        day = now + timedelta(days=2)
    elif " mai " in n:
        day = now + timedelta(days=1)
    elif any(k in n for k in (" hom nay ", " toi nay ", " chieu nay ", " sang nay ", " trua nay ")):
        day = now
    elif " tuan sau " in n:
        day = now + timedelta(days=7)
    else:
        for key, weekday in _WEEKDAYS.items():
            if f" {key} " in n:
                delta = (weekday - now.weekday()) % 7 or 7
                day = now + timedelta(days=delta)
                break

    hour = minute = None
    if m := re.search(r"\b(\d{1,2}):(\d{2})\b", n):
        hour, minute = int(m.group(1)), int(m.group(2))
    elif m := re.search(r"\b(\d{1,2})\s*(?:h|gio)\s*(\d{1,2})?\b", n):
        hour, minute = int(m.group(1)), int(m.group(2) or 0)
    if hour is not None and hour < 12 and any(k in n for k in (" chieu ", " toi ")):
        hour += 12
    if hour is not None and not (0 <= hour <= 23 and 0 <= (minute or 0) <= 59):
        hour = minute = None

    if day is None and hour is None:
        return None
    if day is None:
        candidate = now.replace(hour=hour, minute=minute or 0, second=0, microsecond=0)
        return candidate if candidate > now else candidate + timedelta(days=1)
    return day.replace(
        hour=DEFAULT_HOUR if hour is None else hour,
        minute=0 if hour is None else (minute or 0),
        second=0,
        microsecond=0,
    )
