"""Sinh mã QR liên kết học sinh với chatbot."""

from __future__ import annotations

import segno


def qr_svg(data: str, scale: int = 4) -> str:
    """Trả về chuỗi SVG nhúng thẳng vào HTML."""
    return segno.make(data, error="m").svg_inline(scale=scale, border=2)


def telegram_deep_link(bot_username: str | None, link_code: str) -> str | None:
    """Đường dẫn mở bot Telegram và tự gửi /start <mã> – quét là liên kết ngay."""
    if not bot_username:
        return None
    return f"https://t.me/{bot_username}?start={link_code}"
