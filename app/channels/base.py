"""Giao diện chung cho các kênh chat (Telegram, Zalo...)."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

log = logging.getLogger(__name__)


@dataclass
class Button:
    text: str
    data: str  # mã hành động: "submit", "cancel", "pick:<id>", "list"


@dataclass
class OutgoingMessage:
    """Tin nhắn gửi học sinh. `text` luôn tự đủ nghĩa (có hướng dẫn gõ lệnh) để dùng cả
    trên kênh không hỗ trợ nút bấm; `buttons` chỉ là tiện ích thêm."""

    text: str
    buttons: list[list[Button]] = field(default_factory=list)


class ChannelSendError(RuntimeError):
    def __init__(self, message: str, permanent: bool = False):
        super().__init__(message)
        self.permanent = permanent  # True: không thể gửi (bị chặn, chat không tồn tại) -> không thử lại


class ChannelAdapter(ABC):
    name: str = "base"
    supports_buttons: bool = False

    @abstractmethod
    async def start(self) -> None: ...

    @abstractmethod
    async def stop(self) -> None: ...

    @abstractmethod
    async def send(self, chat_id: str, message: OutgoingMessage) -> None: ...

    def link_url(self, link_code: str) -> str | None:
        """Đường dẫn để in thành mã QR liên kết (None nếu kênh không hỗ trợ)."""
        return None


class ChannelHub:
    """Quản lý các kênh đang hoạt động; tác vụ nền gửi tin qua đây."""

    def __init__(self) -> None:
        self.adapters: dict[str, ChannelAdapter] = {}

    def register(self, adapter: ChannelAdapter) -> None:
        self.adapters[adapter.name] = adapter

    def get(self, name: str | None) -> ChannelAdapter | None:
        return self.adapters.get(name or "")

    def is_active(self, name: str | None) -> bool:
        return (name or "") in self.adapters

    async def send(self, channel: str, chat_id: str, message: OutgoingMessage) -> None:
        adapter = self.get(channel)
        if adapter is None:
            raise ChannelSendError(f"Kênh {channel} chưa bật.")
        await adapter.send(chat_id, message)

    async def start_all(self) -> None:
        for name, adapter in list(self.adapters.items()):
            try:
                await adapter.start()
                log.info("Đã bật kênh %s", name)
            except Exception as exc:
                log.error("Không bật được kênh %s: %s", name, exc)
                self.adapters.pop(name, None)

    async def stop_all(self) -> None:
        for adapter in self.adapters.values():
            try:
                await adapter.stop()
            except Exception:  # pragma: no cover
                log.exception("Lỗi khi tắt kênh %s", adapter.name)
