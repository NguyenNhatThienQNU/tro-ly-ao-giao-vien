"""Tiện ích thời gian.

Quy ước: CSDL lưu thời gian UTC dạng "naive" (không kèm múi giờ);
giao diện và tin nhắn hiển thị theo giờ Việt Nam (cấu hình được).
"""

from __future__ import annotations

try:
    from datetime import UTC, datetime
except ImportError:  # Python < 3.11
    from datetime import datetime, timezone
    UTC = timezone.utc
from functools import lru_cache
from zoneinfo import ZoneInfo

_TZ_NAME = "Asia/Ho_Chi_Minh"


def set_default_timezone(name: str) -> None:
    global _TZ_NAME
    get_tz(name)  # kiểm tra tên múi giờ hợp lệ
    _TZ_NAME = name


@lru_cache(maxsize=8)
def get_tz(name: str | None = None) -> ZoneInfo:
    return ZoneInfo(name or _TZ_NAME)


def utcnow() -> datetime:
    """Thời điểm hiện tại theo UTC (naive) để lưu CSDL."""
    return datetime.now(UTC).replace(tzinfo=None)


def now_local() -> datetime:
    return datetime.now(get_tz(_TZ_NAME))


def to_local(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(get_tz(_TZ_NAME))


def local_to_utc(dt: datetime) -> datetime:
    """Đổi thời gian địa phương (naive = giờ Việt Nam, hoặc có múi giờ) sang UTC naive."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=get_tz(_TZ_NAME))
    return dt.astimezone(UTC).replace(tzinfo=None)


def parse_datetime(value: str | None) -> datetime | None:
    """Đọc chuỗi ISO 8601 (vd '2026-11-12T10:00' hoặc '2026-11-12T10:00:00+07:00').

    Chuỗi không có múi giờ được hiểu là giờ Việt Nam. Trả về UTC naive.
    """
    if value is None:
        return None
    value = str(value).strip()
    if not value:
        return None
    return local_to_utc(datetime.fromisoformat(value))


def fmt_local(dt: datetime | None, fmt: str = "%H:%M %d/%m/%Y") -> str:
    local = to_local(dt)
    return local.strftime(fmt) if local else ""


def to_input_value(dt: datetime | None) -> str:
    """Giá trị cho ô <input type="datetime-local">."""
    return fmt_local(dt, "%Y-%m-%dT%H:%M")


def humanize_delta(target: datetime | None, now: datetime | None = None) -> str:
    """Mô tả ngắn khoảng cách tới một thời điểm UTC naive: 'còn 3 giờ', 'quá hạn 2 ngày'."""
    if target is None:
        return ""
    now = now or utcnow()
    seconds = (target - now).total_seconds()
    future = seconds >= 0
    seconds = abs(seconds)
    if seconds < 3600:
        text = f"{max(1, int(seconds // 60))} phút"
    elif seconds < 86400:
        text = f"{int(seconds // 3600)} giờ"
    else:
        text = f"{int(seconds // 86400)} ngày"
    return f"còn {text}" if future else f"quá hạn {text}"
