"""Lớp AI: chấm bài qua ảnh, sinh câu hỏi, trợ lý giáo viên."""

from __future__ import annotations

import logging

from ..config import Settings
from .base import AIError, AIProvider
from .mock import MockProvider

log = logging.getLogger(__name__)


def build_provider(settings: Settings) -> AIProvider:
    provider = settings.effective_ai_provider
    if provider == "gemini":
        from .gemini import GeminiProvider

        try:
            return GeminiProvider(settings.gemini_api_key, settings.gemini_model, settings.ai_timeout_seconds)
        except AIError as exc:
            log.warning("Không khởi tạo được Gemini (%s) – chuyển sang chế độ demo.", exc)
    elif provider != "mock":
        log.warning("AI_PROVIDER '%s' không hỗ trợ – dùng chế độ demo.", provider)
    return MockProvider()


__all__ = ["AIError", "AIProvider", "build_provider"]
