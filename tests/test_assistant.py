"""Trợ lý AI của giáo viên: vòng gọi công cụ, chế độ demo, xử lý tên trùng."""

from datetime import datetime

from app.ai.assistant import AssistantService
from app.ai.base import AIProvider, ChatSession
from app.ai.mock import MockProvider
from app.ai.schemas import ModelTurn, ToolCall
from app.models import AssignmentBatch, AssistantMessage, ScoreRecord
from app.utils.timeutil import to_local
from app.utils.vndate import parse_vn_deadline


class ScriptedSession(ChatSession):
    """Giả lập mô hình: lần lượt trả về các bước đã định sẵn, ghi lại kết quả công cụ."""

    def __init__(self, steps, seen):
        self.steps = list(steps)
        self.seen = seen

    def send_user(self, text):
        self.seen.append(("user", text))
        return self.steps.pop(0)

    def send_tool_results(self, results):
        self.seen.append(("tools", results))
        return self.steps.pop(0)


class ScriptedProvider(MockProvider):
    is_real = True

    def __init__(self, steps):
        self.steps = steps
        self.seen = []
        self.system = ""

    def start_chat(self, system, history, tools, context=None):
        self.system = system
        return ScriptedSession(self.steps, self.seen)


def test_tool_loop_creates_drafts_with_deadline(db, sample, teacher, settings):
    provider = ScriptedProvider(
        [
            ModelTurn(tool_calls=[ToolCall("c1", "list_classes", {})]),
            ModelTurn(
                tool_calls=[
                    ToolCall(
                        "c2",
                        "create_personalized_assignments",
                        {"class_id": sample.id, "due_at": "2026-11-12T10:00:00+07:00", "num_questions": 3},
                    )
                ]
            ),
            ModelTurn(text="Đã tạo bộ đề nháp, thầy/cô duyệt tại /assignments/batches/…"),
        ]
    )
    reply = AssistantService(db, teacher, provider, settings).chat("Tạo đề cho từng bạn, hạn 10h mai")
    assert "nháp" in reply.text
    assert "10A1" in provider.system and "giờ Việt Nam" in provider.system
    result = provider.seen[-1][1][0].result
    assert result["created"] == 10 and result["status"].startswith("draft")
    batch = db.get(AssignmentBatch, result["batch_id"])
    assert to_local(batch.due_at).strftime("%H:%M %d/%m") == "10:00 12/11"
    assert reply.actions and reply.actions[0]["url"] == f"/assignments/batches/{batch.id}"
    assert db.query(AssistantMessage).count() == 2


def test_ambiguous_or_unknown_student_returns_error_for_model(db, sample, teacher, settings):
    provider = ScriptedProvider(
        [
            ModelTurn(tool_calls=[ToolCall("c1", "get_student_profile", {"student": "Không Có Ai"})]),
            ModelTurn(text="Không tìm thấy."),
        ]
    )
    AssistantService(db, teacher, provider, settings).chat("Hồ sơ em Không Có Ai")
    result = provider.seen[-1][1][0].result
    assert "error" in result


def test_record_scores_and_note(db, sample, teacher, settings):
    provider = ScriptedProvider(
        [
            ModelTurn(
                tool_calls=[
                    ToolCall(
                        "c1",
                        "record_scores",
                        {
                            "class_id": sample.id,
                            "label": "15 phút",
                            "entries": [
                                {"student": "Minh Anh", "score": 9.5},
                                {"student": "Phát", "score": "4,5", "topic": "Xâu kí tự"},
                                {"student": "Người Lạ", "score": 7},
                            ],
                        },
                    ),
                    ToolCall("c2", "update_student_note", {"student": "Minh Anh", "note": "Học sinh giỏi"}),
                ]
            ),
            ModelTurn(text="Đã lưu."),
        ]
    )
    AssistantService(db, teacher, provider, settings).chat("Lưu điểm 15 phút")
    scores, note = provider.seen[-1][1]
    assert scores.result["saved"] == 2 and scores.result["unmatched"] == ["Người Lạ"]
    assert db.query(ScoreRecord).filter_by(label="15 phút").count() == 2
    assert note.result["saved"]


def test_demo_mode_understands_teacher_examples(db, sample, teacher, settings):
    service = AssistantService(db, teacher, MockProvider(), settings)
    reply = service.chat("Tạo bộ đề cá nhân hóa cho từng bạn lớp 10A1, 4 câu, hạn 10h ngày mai")
    assert "10 bộ đề nháp" in reply.text and reply.actions
    reply = service.chat("Bạn Minh Anh là học sinh giỏi, tạo bộ đề nâng cao cho bạn ấy, hạn tối thứ 6")
    assert "1 bộ đề nháp" in reply.text and "nâng cao" in reply.text
    batch = db.query(AssignmentBatch).order_by(AssignmentBatch.id.desc()).first()
    assert batch.mode == "advanced" and batch.assignments[0].student.full_name == "Nguyễn Minh Anh"
    assert "chế độ demo" in service.chat("Xin chào").text


def test_vietnamese_deadlines():
    now = datetime(2026, 11, 11, 10, 44)  # thứ Tư
    assert parse_vn_deadline("hạn 10h ngày mai", now) == datetime(2026, 11, 12, 10, 0)
    assert parse_vn_deadline("tối thứ 6", now) == datetime(2026, 11, 13, 22, 0)
    assert parse_vn_deadline("3h chiều nay", now) == datetime(2026, 11, 11, 15, 0)
    assert parse_vn_deadline("14:30 ngày 20/11", now) == datetime(2026, 11, 20, 14, 30)
    assert parse_vn_deadline("giao 4 câu", now) is None


class _Unused(AIProvider):  # đảm bảo giao diện trừu tượng không đổi ngoài ý muốn
    def grade(self, request): ...
    def generate_questions(self, request): ...
    def start_chat(self, system, history, tools, context=None): ...


def test_provider_interface_is_implementable():
    assert _Unused() is not None
