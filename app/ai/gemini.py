"""Nhà cung cấp AI: Google Gemini (thư viện google-genai, API generateContent)."""

from __future__ import annotations

import copy
import logging
import re
import time

from pydantic import BaseModel, ValidationError

from . import prompts
from .base import AIError, AIProvider, ChatSession
from .schemas import (
    GeneratedQuestion,
    GeneratedQuestions,
    GradingRequest,
    GradingResult,
    ModelTurn,
    QuestionGenRequest,
    ToolCall,
    ToolResult,
    ToolSpec,
)

log = logging.getLogger(__name__)

RETRYABLE_CODES = {429, 500, 502, 503, 504}
MAX_ATTEMPTS = 3


def inline_schema(model: type[BaseModel]) -> dict:
    """Chuyển lược đồ Pydantic sang JSON Schema phẳng (thay $ref bằng định nghĩa, bỏ 'title')."""
    schema = model.model_json_schema()
    defs = schema.pop("$defs", {})

    def resolve(node, in_properties: bool = False):
        if isinstance(node, dict):
            if "$ref" in node and not in_properties:
                return resolve(copy.deepcopy(defs[node["$ref"].split("/")[-1]]))
            out = {}
            for key, value in node.items():
                if not in_properties and key == "title" and isinstance(value, str):
                    continue
                out[key] = resolve(value, in_properties=(key == "properties" and not in_properties))
            return out
        if isinstance(node, list):
            return [resolve(item) for item in node]
        return node

    return resolve(schema)


def _strip_fences(text: str) -> str:
    text = text.strip()
    match = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.DOTALL)
    return match.group(1) if match else text


def _friendly_error(exc: Exception, model: str) -> str:
    code = getattr(exc, "code", None)
    message = getattr(exc, "message", None) or str(exc)
    if code in (400, 401, 403) and "key" in message.lower():
        return "Khóa GEMINI_API_KEY không hợp lệ hoặc chưa được cấp quyền."
    if code == 404:
        return f"Không tìm thấy mô hình '{model}'. Kiểm tra lại GEMINI_MODEL trong tệp .env."
    if code == 429:
        return "Đã vượt hạn mức gọi Gemini (quota). Hệ thống sẽ thử lại sau."
    return f"Lỗi Gemini ({code}): {message[:300]}"


def _parts_text(content) -> str:
    if content is None or not content.parts:
        return ""
    return "".join(p.text for p in content.parts if getattr(p, "text", None) and not getattr(p, "thought", False))


class GeminiProvider(AIProvider):
    name = "gemini"
    is_real = True

    def __init__(self, api_key: str, model: str, timeout_seconds: int = 180):
        from google import genai
        from google.genai import types

        if not api_key:
            raise AIError("Chưa cấu hình GEMINI_API_KEY.")
        self.types = types
        self.model = model
        self.client = genai.Client(api_key=api_key, http_options=types.HttpOptions(timeout=int(timeout_seconds * 1000)))

    # ------------------------------------------------------------------
    def generate(self, contents, config):
        """Gọi generateContent, tự thử lại khi gặp lỗi tạm thời (quá tải, hết hạn mức)."""
        from google.genai import errors

        delay = 2.0
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                return self.client.models.generate_content(model=self.model, contents=contents, config=config)
            except errors.APIError as exc:
                if getattr(exc, "code", None) in RETRYABLE_CODES and attempt < MAX_ATTEMPTS:
                    log.info("Gemini lỗi tạm thời (%s), thử lại sau %.0fs", exc.code, delay)
                    time.sleep(delay)
                    delay *= 2
                    continue
                raise AIError(_friendly_error(exc, self.model)) from exc
            except Exception as exc:  # lỗi mạng, hết thời gian chờ...
                if attempt < MAX_ATTEMPTS:
                    time.sleep(delay)
                    delay *= 2
                    continue
                raise AIError(f"Không kết nối được Gemini: {exc}") from exc
        raise AIError("Không gọi được Gemini.")

    def _json(self, parts: list, system: str, model_cls: type[BaseModel]):
        types = self.types
        config = types.GenerateContentConfig(
            system_instruction=system,
            response_mime_type="application/json",
            response_json_schema=inline_schema(model_cls),
        )
        response = self.generate([types.Content(role="user", parts=parts)], config)
        candidate = response.candidates[0] if response.candidates else None
        text = _parts_text(candidate.content if candidate else None)
        if not text:
            raise AIError("Gemini không trả về nội dung (có thể bị bộ lọc an toàn chặn hoặc ảnh không đọc được).")
        try:
            return model_cls.model_validate_json(_strip_fences(text))
        except ValidationError as exc:
            raise AIError("Phản hồi của AI không đúng định dạng JSON mong đợi.") from exc

    # ------------------------------------------------------------------
    def grade(self, request: GradingRequest) -> GradingResult:
        types = self.types
        parts = [types.Part.from_bytes(data=img.data, mime_type=img.mime_type) for img in request.images]
        parts.append(types.Part(text=prompts.grading_prompt(request)))
        return self._json(parts, prompts.grading_system(request.subject_name), GradingResult)

    def generate_questions(self, request: QuestionGenRequest) -> list[GeneratedQuestion]:
        parts = [self.types.Part(text=prompts.question_prompt(request))]
        result = self._json(parts, prompts.question_system(request.subject_name), GeneratedQuestions)
        return result.questions

    def start_chat(self, system, history, tools, context=None) -> ChatSession:
        return GeminiChatSession(self, system, history, tools)


class GeminiChatSession(ChatSession):
    """Phiên trợ lý có gọi hàm. Giữ nguyên nội dung mô hình trả về (kể cả thought signature)."""

    def __init__(self, provider: GeminiProvider, system: str, history: list[tuple[str, str]], tools: list[ToolSpec]):
        types = provider.types
        self.provider = provider
        self.types = types
        self.contents = [
            types.Content(role="user" if role == "user" else "model", parts=[types.Part(text=text)])
            for role, text in history
            if text
        ]
        declarations = [
            types.FunctionDeclaration(
                name=t.name,
                description=t.description,
                parameters_json_schema=t.parameters if t.parameters.get("properties") else None,
            )
            for t in tools
        ]
        self.config = types.GenerateContentConfig(
            system_instruction=system,
            tools=[types.Tool(function_declarations=declarations)],
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )

    def _step(self) -> ModelTurn:
        response = self.provider.generate(self.contents, self.config)
        candidate = response.candidates[0] if response.candidates else None
        if candidate is None or candidate.content is None:
            return ModelTurn(text="Xin lỗi, AI chưa phản hồi được. Thầy/cô thử lại nhé.")
        self.contents.append(candidate.content)
        calls = []
        for i, part in enumerate(candidate.content.parts or []):
            fc = getattr(part, "function_call", None)
            if fc is not None and fc.name:
                calls.append(ToolCall(id=fc.id or f"call_{i}", name=fc.name, args=dict(fc.args or {})))
        return ModelTurn(text=_parts_text(candidate.content), tool_calls=calls)

    def send_user(self, text: str) -> ModelTurn:
        self.contents.append(self.types.Content(role="user", parts=[self.types.Part(text=text)]))
        return self._step()

    def send_tool_results(self, results: list[ToolResult]) -> ModelTurn:
        types = self.types
        parts = [
            types.Part(
                function_response=types.FunctionResponse(
                    id=r.call_id if not r.call_id.startswith("call_") else None,
                    name=r.name,
                    response=r.result,
                )
            )
            for r in results
        ]
        self.contents.append(types.Content(role="user", parts=parts))
        return self._step()
