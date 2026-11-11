"""Cấu trúc dữ liệu vào/ra của các tác vụ AI (độc lập với nhà cung cấp mô hình)."""

from __future__ import annotations

from dataclasses import dataclass, field

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Chấm bài qua ảnh
# ---------------------------------------------------------------------------


@dataclass
class RubricItem:
    criterion: str
    points: float


@dataclass
class GradingQuestion:
    number: int  # số thứ tự câu trong bộ đề (1, 2, ...)
    content: str
    max_score: float
    level_name: str
    rubric: list[RubricItem] = field(default_factory=list)
    reference_answer: str = ""


@dataclass
class ImageInput:
    data: bytes
    mime_type: str = "image/jpeg"


@dataclass
class GradingRequest:
    subject_name: str
    questions: list[GradingQuestion]
    images: list[ImageInput]


class CriterionResult(BaseModel):
    criterion: str = Field(description="Tên tiêu chí, giữ nguyên như rubric")
    max_points: float = Field(description="Điểm tối đa của tiêu chí")
    awarded: float = Field(description="Điểm học sinh đạt được ở tiêu chí này")
    comment: str = Field(description="Nhận xét ngắn cho tiêu chí")


class ErrorItem(BaseModel):
    description: str = Field(description="Lỗi sai cụ thể học sinh mắc phải")
    explanation: str = Field(description="Vì sao đó là lỗi")
    fix: str = Field(description="Cách sửa đúng")


class QuestionResult(BaseModel):
    question_number: int = Field(description="Số thứ tự câu (1, 2, ...)")
    found: bool = Field(description="Có tìm thấy bài làm của câu này trong ảnh không")
    transcription: str = Field(description="Chép lại nguyên văn phần bài làm của học sinh cho câu này")
    criteria: list[CriterionResult] = Field(description="Điểm theo từng tiêu chí của rubric")
    score: float = Field(description="Tổng điểm của câu")
    comment: str = Field(description="Nhận xét cho học sinh, xưng 'em'")
    errors: list[ErrorItem] = Field(description="Danh sách lỗi sai (rỗng nếu làm đúng)")
    confidence: float = Field(description="Mức tin cậy 0-1 về việc đọc ảnh và chấm câu này")


class GradingResult(BaseModel):
    questions: list[QuestionResult]
    overall_feedback: str = Field(description="Nhận xét chung gửi học sinh, khích lệ và cụ thể")
    image_quality: str = Field(description="Chất lượng ảnh: tốt | trung bình | kém")


# ---------------------------------------------------------------------------
# Sinh câu hỏi
# ---------------------------------------------------------------------------


@dataclass
class QuestionGenRequest:
    subject_name: str
    topic_name: str
    level: int
    level_name: str
    count: int
    max_score: float
    instruction: str = ""
    avoid: list[str] = field(default_factory=list)  # nội dung các câu đã có, tránh trùng


class GeneratedRubricItem(BaseModel):
    criterion: str
    points: float


class GeneratedQuestion(BaseModel):
    content: str = Field(description="Nội dung câu hỏi tự luận, học sinh làm trên giấy")
    rubric: list[GeneratedRubricItem] = Field(description="Các tiêu chí chấm, tổng điểm bằng điểm tối đa")
    reference_answer: str = Field(description="Đáp án / lời giải tham khảo")


class GeneratedQuestions(BaseModel):
    questions: list[GeneratedQuestion]


# ---------------------------------------------------------------------------
# Hội thoại có gọi công cụ (trợ lý giáo viên)
# ---------------------------------------------------------------------------


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: dict  # JSON Schema của tham số


@dataclass
class ToolCall:
    id: str
    name: str
    args: dict


@dataclass
class ToolResult:
    call_id: str
    name: str
    result: dict


@dataclass
class ModelTurn:
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
