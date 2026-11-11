"""Giao diện chung cho các nhà cung cấp AI (Gemini, chế độ demo...)."""

from __future__ import annotations

from abc import ABC, abstractmethod

from .schemas import (
    GeneratedQuestion,
    GradingRequest,
    GradingResult,
    ModelTurn,
    QuestionGenRequest,
    ToolResult,
    ToolSpec,
)


class AIError(RuntimeError):
    """Lỗi khi gọi mô hình AI (mạng, hết hạn mức, phản hồi sai định dạng...)."""


class ChatSession(ABC):
    """Một phiên hội thoại nhiều bước có gọi công cụ."""

    @abstractmethod
    def send_user(self, text: str) -> ModelTurn: ...

    @abstractmethod
    def send_tool_results(self, results: list[ToolResult]) -> ModelTurn: ...


class AIProvider(ABC):
    name: str = "base"
    is_real: bool = False  # False = chế độ demo, không gọi mô hình thật

    @abstractmethod
    def grade(self, request: GradingRequest) -> GradingResult:
        """Đọc ảnh bài làm và chấm theo rubric."""

    @abstractmethod
    def generate_questions(self, request: QuestionGenRequest) -> list[GeneratedQuestion]:
        """Sinh câu hỏi mới cho một chủ đề và mức độ."""

    @abstractmethod
    def start_chat(
        self,
        system: str,
        history: list[tuple[str, str]],
        tools: list[ToolSpec],
        context: dict | None = None,
    ) -> ChatSession:
        """Bắt đầu phiên trợ lý. history: [(role 'user'|'assistant', text)]."""
