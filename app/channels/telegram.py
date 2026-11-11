"""Kênh Telegram (Bot API, gọi trực tiếp bằng httpx).

Hai chế độ nhận tin:
- polling: máy chủ tự hỏi Telegram liên tục -> chạy được trên máy cá nhân, không cần tên miền.
- webhook: Telegram gọi vào /webhooks/telegram -> cần địa chỉ HTTPS công khai.
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

API_BASE = "https://api.telegram.org"
TEXT_LIMIT = 4000
MAX_FILE_BYTES = 20 * 1024 * 1024  # giới hạn tải tệp của Bot API
ALLOWED_UPDATES = ["message", "callback_query"]
BOT_COMMANDS = [
    {"command": "baitap", "description": "Xem bài đang cần làm"},
    {"command": "nop", "description": "Nộp các ảnh vừa gửi"},
    {"command": "huy", "description": "Hủy các ảnh vừa gửi"},
    {"command": "ketqua", "description": "Xem kết quả gần đây"},
    {"command": "tiendo", "description": "Xem mức nắm vững từng chủ đề"},
    {"command": "huongdan", "description": "Hướng dẫn sử dụng"},
]


class TelegramError(RuntimeError):
    def __init__(self, description: str, code: int | None = None, retry_after: int | None = None):
        super().__init__(description)
        self.code = code
        self.retry_after = retry_after


class TelegramAdapter(ChannelAdapter):
    name = "telegram"
    supports_buttons = True

    def __init__(
        self,
        token: str,
        bot: StudentBot,
        *,
        mode: str = "polling",
        public_base_url: str = "",
        webhook_secret: str = "",
        client: httpx.AsyncClient | None = None,
        api_base: str = API_BASE,
        ack_delay: float = 2.5,
    ):
        self.token = token
        self.bot = bot
        self.mode = mode
        self.public_base_url = public_base_url.rstrip("/")
        self.webhook_secret = webhook_secret
        self.api_base = api_base.rstrip("/")
        self.client = client or httpx.AsyncClient(timeout=httpx.Timeout(50.0, connect=10.0))
        self.ack_delay = ack_delay
        self.username: str | None = None
        self._poll_task: asyncio.Task | None = None
        self._ack_tasks: dict[str, asyncio.Task] = {}

    # ------------------------------------------------------------------
    async def call(self, method: str, **params):
        url = f"{self.api_base}/bot{self.token}/{method}"
        try:
            response = await self.client.post(url, json=params)
            data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise TelegramError(f"Lỗi kết nối Telegram: {exc}") from exc
        if not data.get("ok"):
            raise TelegramError(
                data.get("description", "Lỗi không rõ"),
                data.get("error_code"),
                (data.get("parameters") or {}).get("retry_after"),
            )
        return data.get("result")

    async def start(self) -> None:
        me = await self.call("getMe")
        self.username = me.get("username")
        with contextlib.suppress(TelegramError):
            await self.call("setMyCommands", commands=BOT_COMMANDS)
        if self.mode == "webhook":
            if not self.public_base_url.startswith("https://"):
                raise TelegramError("Chế độ webhook cần PUBLIC_BASE_URL dạng https://")
            await self.call(
                "setWebhook",
                url=f"{self.public_base_url}/webhooks/telegram",
                secret_token=self.webhook_secret,
                allowed_updates=ALLOWED_UPDATES,
            )
        else:
            await self.call("deleteWebhook", drop_pending_updates=False)
            self._poll_task = asyncio.create_task(self._poll_loop(), name="telegram-polling")
        log.info("Telegram bot @%s đang chạy (%s)", self.username, self.mode)

    async def stop(self) -> None:
        if self._poll_task:
            self._poll_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._poll_task
        for task in self._ack_tasks.values():
            task.cancel()
        await self.client.aclose()

    def link_url(self, link_code: str) -> str | None:
        return f"https://t.me/{self.username}?start={link_code}" if self.username else None

    # ------------------------------------------------------------------
    async def _poll_loop(self) -> None:
        offset: int | None = None
        while True:
            try:
                params = {"timeout": 30, "allowed_updates": ALLOWED_UPDATES}
                if offset is not None:
                    params["offset"] = offset
                updates = await self.call("getUpdates", **params)
                for update in updates or []:
                    offset = update["update_id"] + 1
                    try:
                        await self.process_update(update)
                    except Exception:
                        log.exception("Lỗi xử lý tin Telegram")
            except asyncio.CancelledError:
                raise
            except TelegramError as exc:
                wait = exc.retry_after or (15 if exc.code == 409 else 5)
                log.warning("Telegram getUpdates lỗi: %s – thử lại sau %ss", exc, wait)
                await asyncio.sleep(wait)
            except Exception:
                log.exception("Lỗi vòng polling Telegram")
                await asyncio.sleep(5)

    async def process_update(self, update: dict) -> None:
        if callback := update.get("callback_query"):
            await self._on_callback(callback)
            return
        message = update.get("message")
        if not message:
            return
        chat = message.get("chat") or {}
        if chat.get("type") != "private":
            return  # chỉ nhận tin nhắn riêng
        chat_id = str(chat["id"])
        sender = message.get("from") or {}
        display_name = " ".join(filter(None, [sender.get("first_name"), sender.get("last_name")]))

        if "text" in message:
            replies = await asyncio.to_thread(self.bot.handle_text, self.name, chat_id, display_name, message["text"])
            await self._send_all(chat_id, replies)
            return

        file_id = mime = None
        if message.get("photo"):
            photo = message["photo"][-1]  # bản phân giải cao nhất
            file_id, mime = photo["file_id"], "image/jpeg"
        elif document := message.get("document"):
            doc_mime = document.get("mime_type") or ""
            if doc_mime.startswith("image/") or doc_mime == "application/pdf":
                if (document.get("file_size") or 0) > MAX_FILE_BYTES:
                    await self.send(
                        chat_id, OutgoingMessage("Tệp quá lớn (tối đa 20 MB). Em chụp ảnh gửi trực tiếp nhé.")
                    )
                    return
                file_id, mime = document["file_id"], doc_mime
        if file_id is None:
            await self.send(chat_id, OutgoingMessage("Bot chỉ nhận tin nhắn chữ và ảnh bài làm (hoặc tệp PDF)."))
            return
        try:
            data = await self.download(file_id)
        except TelegramError as exc:
            log.warning("Không tải được ảnh: %s", exc)
            await self.send(chat_id, OutgoingMessage("⚠️ Bot chưa tải được ảnh, em gửi lại giúp nhé."))
            return
        result = await asyncio.to_thread(self.bot.handle_image, self.name, chat_id, display_name, data, mime)
        await self._send_all(chat_id, result.messages)
        if result.schedule_ack:
            self._schedule_ack(chat_id)

    async def _on_callback(self, callback: dict) -> None:
        with contextlib.suppress(TelegramError):
            await self.call("answerCallbackQuery", callback_query_id=callback["id"])
        message = callback.get("message") or {}
        chat_id = str((message.get("chat") or {}).get("id") or (callback.get("from") or {}).get("id"))
        replies = await asyncio.to_thread(self.bot.handle_action, self.name, chat_id, callback.get("data") or "")
        await self._send_all(chat_id, replies)

    async def download(self, file_id: str) -> bytes:
        info = await self.call("getFile", file_id=file_id)
        path = info.get("file_path")
        if not path:
            raise TelegramError("Không lấy được đường dẫn tệp.")
        try:
            response = await self.client.get(f"{self.api_base}/file/bot{self.token}/{path}")
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise TelegramError(f"Lỗi tải tệp: {exc}") from exc
        return response.content

    def _schedule_ack(self, chat_id: str) -> None:
        """Gom nhiều ảnh gửi liên tiếp (album) thành một tin xác nhận."""
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
                log.warning("Không gửi được tin Telegram tới %s: %s", chat_id, exc)

    async def send(self, chat_id: str, message: OutgoingMessage) -> None:
        chunks = split_text(message.text, TEXT_LIMIT)
        for i, chunk in enumerate(chunks):
            params: dict = {"chat_id": chat_id, "text": chunk, "link_preview_options": {"is_disabled": True}}
            if message.buttons and i == len(chunks) - 1:
                params["reply_markup"] = {
                    "inline_keyboard": [
                        [{"text": b.text, "callback_data": b.data} for b in row] for row in message.buttons
                    ]
                }
            try:
                await self.call("sendMessage", **params)
            except TelegramError as exc:
                if exc.retry_after:
                    await asyncio.sleep(exc.retry_after)
                    await self.call("sendMessage", **params)
                    continue
                raise ChannelSendError(str(exc), permanent=exc.code in (400, 403)) from exc
