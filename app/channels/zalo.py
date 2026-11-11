"""Kênh Zalo Bot (Zalo Bot Platform – THỬ NGHIỆM).

API của Zalo Bot Platform tương tự Telegram Bot API:
    https://bot-api.zaloplatforms.com/bot<TOKEN>/<method>
Khác biệt chính: getUpdates trả về MỘT sự kiện mỗi lần gọi; không có nút bấm (inline keyboard),
nên học sinh dùng lệnh gõ chữ (NOP, HUY, BAITAP...); tin nhắn tối đa 2000 ký tự.
Ảnh gửi tới bot có dạng sự kiện "message.image.received" kèm đường dẫn ảnh (photo_url).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging

import httpx

from ..utils.text import split_text
from .base import ChannelAdapter, ChannelSendError, OutgoingMessage
from .bot_logic import StudentBot

log = logging.getLogger(__name__)

API_BASE = "https://bot-api.zaloplatforms.com"
TEXT_LIMIT = 1900


class ZaloError(RuntimeError):
    def __init__(self, description: str, code: int | None = None):
        super().__init__(description)
        self.code = code


class ZaloAdapter(ChannelAdapter):
    name = "zalo"
    supports_buttons = False

    def __init__(
        self,
        token: str,
        bot: StudentBot,
        *,
        mode: str = "polling",
        public_base_url: str = "",
        webhook_secret: str = "",
        bot_link: str = "",
        client: httpx.AsyncClient | None = None,
        api_base: str = API_BASE,
        ack_delay: float = 3.0,
    ):
        self.token = token
        self.bot = bot
        self.mode = mode
        self.public_base_url = public_base_url.rstrip("/")
        self.webhook_secret = webhook_secret
        self.bot_link = bot_link
        self.api_base = api_base.rstrip("/")
        self.client = client or httpx.AsyncClient(timeout=httpx.Timeout(50.0, connect=10.0))
        self.ack_delay = ack_delay
        self.account_name: str | None = None
        self._poll_task: asyncio.Task | None = None
        self._ack_tasks: dict[str, asyncio.Task] = {}

    async def call(self, method: str, **params):
        try:
            response = await self.client.post(f"{self.api_base}/bot{self.token}/{method}", json=params)
            data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise ZaloError(f"Lỗi kết nối Zalo: {exc}") from exc
        if not data.get("ok"):
            raise ZaloError(data.get("description", "Lỗi không rõ"), data.get("error_code"))
        return data.get("result")

    async def start(self) -> None:
        me = await self.call("getMe")
        self.account_name = (me or {}).get("account_name")
        if self.mode == "webhook":
            if not self.public_base_url.startswith("https://"):
                raise ZaloError("Chế độ webhook cần PUBLIC_BASE_URL dạng https://")
            await self.call("setWebhook", url=f"{self.public_base_url}/webhooks/zalo", secret_token=self.webhook_secret)
        else:
            with contextlib.suppress(ZaloError):
                await self.call("deleteWebhook")
            self._poll_task = asyncio.create_task(self._poll_loop(), name="zalo-polling")
        log.info("Zalo bot %s đang chạy (%s)", self.account_name, self.mode)

    async def stop(self) -> None:
        if self._poll_task:
            self._poll_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._poll_task
        for task in self._ack_tasks.values():
            task.cancel()
        await self.client.aclose()

    def link_url(self, link_code: str) -> str | None:
        return self.bot_link or None  # Zalo chưa hỗ trợ tham số /start: học sinh gõ mã sau khi mở bot

    async def _poll_loop(self) -> None:
        while True:
            try:
                result = await self.call("getUpdates", timeout=30)
                updates = result if isinstance(result, list) else ([result] if result else [])
                for update in updates:
                    try:
                        await self.process_update(update)
                    except Exception:
                        log.exception("Lỗi xử lý tin Zalo")
            except asyncio.CancelledError:
                raise
            except ZaloError as exc:
                if exc.code == 408:  # hết thời gian chờ, không có tin mới
                    continue
                log.warning("Zalo getUpdates lỗi: %s", exc)
                await asyncio.sleep(5)
            except Exception:
                log.exception("Lỗi vòng polling Zalo")
                await asyncio.sleep(5)

    async def process_update(self, update: dict) -> None:
        if "result" in update and "event_name" not in update:
            update = update["result"] or {}
        event = update.get("event_name", "")
        message = update.get("message") or {}
        chat_id = str((message.get("chat") or {}).get("id") or (message.get("from") or {}).get("id") or "")
        if not chat_id:
            return
        display_name = (message.get("from") or {}).get("display_name", "")

        if event == "message.text.received":
            replies = await asyncio.to_thread(
                self.bot.handle_text, self.name, chat_id, display_name, message.get("text", "")
            )
            await self._send_all(chat_id, replies)
        elif event == "message.image.received":
            url = message.get("photo_url") or message.get("photo") or message.get("url")
            if isinstance(url, list):
                url = url[-1].get("url") if url and isinstance(url[-1], dict) else None
            if not url:
                await self.send(chat_id, OutgoingMessage("⚠️ Bot chưa đọc được ảnh, em gửi lại giúp nhé."))
                return
            try:
                response = await self.client.get(url)
                response.raise_for_status()
            except httpx.HTTPError as exc:
                log.warning("Không tải được ảnh Zalo: %s", exc)
                await self.send(chat_id, OutgoingMessage("⚠️ Bot chưa tải được ảnh, em gửi lại giúp nhé."))
                return
            mime = response.headers.get("content-type", "image/jpeg").split(";")[0]
            result = await asyncio.to_thread(
                self.bot.handle_image, self.name, chat_id, display_name, response.content, mime
            )
            await self._send_all(chat_id, result.messages)
            if result.schedule_ack:
                self._schedule_ack(chat_id)
        elif event.startswith("message."):
            await self.send(chat_id, OutgoingMessage("Bot chỉ nhận tin nhắn chữ và ảnh bài làm."))

    def _schedule_ack(self, chat_id: str) -> None:
        if task := self._ack_tasks.get(chat_id):
            task.cancel()
        self._ack_tasks[chat_id] = asyncio.create_task(self._ack_later(chat_id))

    async def _ack_later(self, chat_id: str) -> None:
        try:
            await asyncio.sleep(self.ack_delay)
            replies = await asyncio.to_thread(self.bot.collecting_status, self.name, chat_id)
            await self._send_all(chat_id, replies)
        except asyncio.CancelledError:
            pass
        finally:
            if self._ack_tasks.get(chat_id) is asyncio.current_task():
                self._ack_tasks.pop(chat_id, None)

    async def _send_all(self, chat_id: str, replies: list[OutgoingMessage]) -> None:
        for reply in replies:
            try:
                await self.send(chat_id, reply)
            except ChannelSendError as exc:
                log.warning("Không gửi được tin Zalo tới %s: %s", chat_id, exc)

    async def send(self, chat_id: str, message: OutgoingMessage) -> None:
        # Zalo không có nút bấm: nội dung tin đã kèm hướng dẫn gõ lệnh.
        for chunk in split_text(message.text, TEXT_LIMIT):
            try:
                await self.call("sendMessage", chat_id=chat_id, text=chunk)
            except ZaloError as exc:
                raise ChannelSendError(str(exc), permanent=exc.code in (400, 403, 404)) from exc
