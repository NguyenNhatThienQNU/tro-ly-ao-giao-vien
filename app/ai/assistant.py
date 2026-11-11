"""Trợ lý ảo của giáo viên: hiểu câu lệnh tiếng Việt và thao tác dữ liệu qua "công cụ".

Mô hình AI chỉ được gọi các công cụ khai báo dưới đây. Công cụ tạo nội dung (bộ đề, câu hỏi)
luôn tạo bản NHÁP; giáo viên duyệt trên web rồi hệ thống mới gửi cho học sinh.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import Settings
from ..models import (
    LEVELS,
    AssistantMessage,
    Classroom,
    ScoreRecord,
    Student,
    Submission,
    SubmissionStatus,
    Teacher,
)
from ..services import assignments as assignment_service
from ..services.alerts import class_alerts, submission_series
from ..services.mastery import class_mastery, mastery_for_students, student_average, topic_average
from ..services.recommender import MODE_LABELS
from ..services.students import StudentLookupError, resolve_student
from ..utils.text import fmt_score, norm, to_ten, truncate
from ..utils.timeutil import fmt_local, now_local, parse_datetime
from . import prompts
from .base import AIError, AIProvider
from .schemas import ToolCall, ToolResult, ToolSpec

log = logging.getLogger(__name__)

MAX_STEPS = 6
HISTORY_LIMIT = 12
WEEKDAYS_VN = ["Thứ Hai", "Thứ Ba", "Thứ Tư", "Thứ Năm", "Thứ Sáu", "Thứ Bảy", "Chủ Nhật"]

_CLASS = {"type": "integer", "description": "id của lớp"}
_STUDENT = {"type": "string", "description": "Họ tên (hoặc tên gọi, mã học sinh)"}

TOOLS: list[ToolSpec] = [
    ToolSpec("list_classes", "Liệt kê các lớp giáo viên đang dạy: id, tên, môn, sĩ số, số em đã liên kết chatbot.", {}),
    ToolSpec(
        "list_students",
        "Danh sách học sinh của một lớp kèm mức nắm vững trung bình, chủ đề yếu nhất và ghi chú.",
        {"type": "object", "properties": {"class_id": _CLASS}, "required": ["class_id"]},
    ),
    ToolSpec(
        "get_student_profile",
        "Hồ sơ học tập của một học sinh: mức nắm vững từng chủ đề, kết quả các bài gần đây, ghi chú.",
        {"type": "object", "properties": {"student": _STUDENT, "class_id": _CLASS}, "required": ["student"]},
    ),
    ToolSpec(
        "get_class_overview",
        "Tổng quan một lớp: mức nắm vững trung bình theo chủ đề, tiến độ các đợt giao bài gần đây, cảnh báo.",
        {"type": "object", "properties": {"class_id": _CLASS}, "required": ["class_id"]},
    ),
    ToolSpec(
        "record_scores",
        "Lưu bảng điểm giáo viên cung cấp (vd điểm kiểm tra trên lớp) để cập nhật mức nắm vững. "
        "Dùng khi giáo viên dán danh sách điểm.",
        {
            "type": "object",
            "properties": {
                "class_id": _CLASS,
                "label": {"type": "string", "description": "Tên đầu điểm, vd 'Kiểm tra 15 phút lần 2'"},
                "max_score": {"type": "number", "description": "Thang điểm, mặc định 10"},
                "entries": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "student": _STUDENT,
                            "score": {"type": "number"},
                            "topic": {"type": "string", "description": "Tên chủ đề nếu điểm chỉ thuộc một chủ đề"},
                        },
                        "required": ["student", "score"],
                    },
                },
            },
            "required": ["class_id", "entries"],
        },
    ),
    ToolSpec(
        "create_personalized_assignments",
        "Tạo bộ đề NHÁP cá nhân hóa cho từng học sinh (cả lớp hoặc một số em) dựa trên mức nắm vững từng chủ đề. "
        "Giáo viên duyệt trên web trước khi gửi.",
        {
            "type": "object",
            "properties": {
                "class_id": _CLASS,
                "title": {"type": "string", "description": "Tên bài, vd 'Luyện tập vòng lặp'"},
                "due_at": {
                    "type": "string",
                    "description": "Hạn nộp ISO 8601 có múi giờ, vd 2026-11-12T10:00:00+07:00",
                },
                "num_questions": {"type": "integer", "description": "Số câu mỗi bộ đề (1–10), mặc định 4"},
                "mode": {
                    "type": "string",
                    "enum": ["auto", "advanced", "review"],
                    "description": "auto: theo điểm yếu; advanced: nâng cao cho học sinh khá giỏi; review: ôn tập dễ hơn",
                },
                "students": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Tên các học sinh cần giao; bỏ trống = cả lớp",
                },
                "topics": {"type": "array", "items": {"type": "string"}, "description": "Chỉ lấy các chủ đề này"},
                "instruction": {"type": "string", "description": "Yêu cầu thêm khi AI soạn câu hỏi mới"},
            },
            "required": ["class_id"],
        },
    ),
    ToolSpec(
        "generate_questions",
        "Nhờ AI soạn câu hỏi mới (dạng nháp, chờ duyệt) bổ sung vào ngân hàng câu hỏi.",
        {
            "type": "object",
            "properties": {
                "class_id": _CLASS,
                "topic": {"type": "string", "description": "Tên chủ đề"},
                "level": {"type": "integer", "description": "1 Nhận biết, 2 Thông hiểu, 3 Vận dụng, 4 Vận dụng cao"},
                "count": {"type": "integer", "description": "Số câu (1–6)"},
                "instruction": {"type": "string"},
            },
            "required": ["class_id", "topic", "level"],
        },
    ),
    ToolSpec(
        "update_student_note",
        "Lưu ghi chú về một học sinh, vd 'học sinh giỏi, thích bài thử thách'.",
        {
            "type": "object",
            "properties": {"student": _STUDENT, "note": {"type": "string"}, "class_id": _CLASS},
            "required": ["student", "note"],
        },
    ),
    ToolSpec(
        "list_pending_grading",
        "Các bài nộp AI đã chấm sơ bộ, đang chờ giáo viên xác nhận điểm.",
        {"type": "object", "properties": {"class_id": _CLASS}},
    ),
]


class ToolError(Exception):
    def __init__(self, message: str, **extra):
        super().__init__(message)
        self.extra = extra


@dataclass
class AssistantReply:
    text: str
    actions: list[dict] = field(default_factory=list)


class AssistantService:
    def __init__(self, db: Session, teacher: Teacher, ai: AIProvider, settings: Settings):
        self.db = db
        self.teacher = teacher
        self.ai = ai
        self.settings = settings
        self.actions: list[dict] = []

    # ------------------------------------------------------------------
    # Ngữ cảnh
    # ------------------------------------------------------------------
    def classes(self) -> list[Classroom]:
        return list(
            self.db.scalars(
                select(Classroom).where(Classroom.teacher_id == self.teacher.id).order_by(Classroom.name)
            ).all()
        )

    def system_prompt(self) -> str:
        lines = [
            f"- id={c.id}: {c.name} (môn {c.subject.name}, {len(c.students)} học sinh)" for c in self.classes()
        ] or ["(chưa có lớp nào)"]
        now = now_local()
        return prompts.ASSISTANT_SYSTEM.format(
            teacher=self.teacher.full_name,
            now=f"{WEEKDAYS_VN[now.weekday()]} {now:%d/%m/%Y %H:%M}",
            classes="\n".join(lines),
        )

    def context(self) -> dict:
        return {
            "classes": [
                {"id": c.id, "name": c.name, "students": [s.full_name for s in c.students]} for c in self.classes()
            ]
        }

    def history(self) -> list[tuple[str, str]]:
        rows = self.db.scalars(
            select(AssistantMessage)
            .where(AssistantMessage.teacher_id == self.teacher.id)
            .order_by(AssistantMessage.id.desc())
            .limit(HISTORY_LIMIT)
        ).all()
        items = [(m.role, m.content) for m in reversed(rows)]
        while items and items[0][0] != "user":
            items.pop(0)
        return items

    # ------------------------------------------------------------------
    # Vòng hội thoại
    # ------------------------------------------------------------------
    def chat(self, message: str) -> AssistantReply:
        message = message.strip()
        self.actions = []
        try:
            session = self.ai.start_chat(self.system_prompt(), self.history(), TOOLS, self.context())
            turn = session.send_user(message)
            steps = 0
            while turn.tool_calls and steps < MAX_STEPS:
                steps += 1
                results = [self.execute(call) for call in turn.tool_calls]
                self.db.commit()
                turn = session.send_tool_results(results)
            text = turn.text.strip() or "Đã thực hiện xong."
        except AIError as exc:
            self.db.rollback()
            text = f"⚠️ {exc}"
        self.db.add(AssistantMessage(teacher_id=self.teacher.id, role="user", content=message))
        self.db.add(AssistantMessage(teacher_id=self.teacher.id, role="assistant", content=text, actions=self.actions))
        self.db.commit()
        return AssistantReply(text=text, actions=self.actions)

    def execute(self, call: ToolCall) -> ToolResult:
        handler = getattr(self, f"tool_{call.name}", None)
        if handler is None:
            return ToolResult(call.id, call.name, {"error": f"Không có công cụ {call.name}"})
        try:
            result = handler(**(call.args or {}))
        except ToolError as exc:
            self.db.rollback()
            result = {"error": str(exc), **exc.extra}
        except (assignment_service.AssignmentError, StudentLookupError, ValueError, TypeError) as exc:
            self.db.rollback()
            result = {"error": str(exc)}
            if isinstance(exc, StudentLookupError) and exc.candidates:
                result["candidates"] = [f"{s.full_name} ({s.classroom.name})" for s in exc.candidates[:10]]
        except Exception:  # không để lỗi bất ngờ làm sập hội thoại
            log.exception("Lỗi công cụ %s", call.name)
            self.db.rollback()
            result = {"error": "Lỗi hệ thống khi thực hiện thao tác."}
        log.info("Trợ lý gọi %s(%s) -> %s", call.name, call.args, truncate(str(result), 200))
        return ToolResult(call.id, call.name, result)

    # ------------------------------------------------------------------
    # Tiện ích
    # ------------------------------------------------------------------
    def _class(self, class_id) -> Classroom:
        classes = self.classes()
        if class_id in (None, "", 0) and len(classes) == 1:
            return classes[0]
        for c in classes:
            if str(c.id) == str(class_id):
                return c
        raise ToolError(
            "Không tìm thấy lớp. Hãy chọn một trong các lớp:",
            classes=[f"id={c.id}: {c.name}" for c in classes],
        )

    def _topic(self, classroom: Classroom, name: str):
        topics = classroom.subject.topics
        key = norm(name)
        for t in topics:
            if norm(t.name) == key:
                return t
        partial = [t for t in topics if key and (key in norm(t.name) or norm(t.name) in key)]
        if len(partial) == 1:
            return partial[0]
        raise ToolError(f"Không xác định được chủ đề «{name}».", topics=[t.name for t in topics])

    # ------------------------------------------------------------------
    # Các công cụ
    # ------------------------------------------------------------------
    def tool_list_classes(self) -> dict:
        return {
            "classes": [
                {
                    "id": c.id,
                    "name": c.name,
                    "subject": c.subject.name,
                    "students": len(c.students),
                    "linked": sum(1 for s in c.students if s.is_linked),
                }
                for c in self.classes()
            ]
        }

    def tool_list_students(self, class_id=None) -> dict:
        classroom = self._class(class_id)
        table = class_mastery(self.db, classroom)
        topics = classroom.subject.topics
        out = []
        for s in classroom.students:
            states = table.get(s.id, {})
            weak = sorted(
                ((t.name, states[t.id].pct) for t in topics if t.id in states and states[t.id].has_data),
                key=lambda x: x[1],
            )[:2]
            out.append(
                {
                    "id": s.id,
                    "name": s.full_name,
                    "code": s.student_code,
                    "linked_chatbot": s.is_linked,
                    "mastery_avg_pct": student_average(table, s.id),
                    "weakest_topics": [f"{n} ({p:.0f}%)" for n, p in weak],
                    "note": s.note,
                }
            )
        return {"class": classroom.name, "students": out}

    def tool_get_student_profile(self, student, class_id=None) -> dict:
        s = resolve_student(self.db, self.teacher, student, class_id)
        topics = s.classroom.subject.topics
        table = mastery_for_students(self.db, [s], [t.id for t in topics])
        states = table.get(s.id, {})
        series = submission_series(self.db, [s.id]).get(s.id, [])
        recent = self.db.scalars(
            select(Submission)
            .where(Submission.student_id == s.id, Submission.status == SubmissionStatus.CONFIRMED)
            .order_by(Submission.confirmed_at.desc())
            .limit(5)
        ).all()
        records = self.db.scalars(
            select(ScoreRecord).where(ScoreRecord.student_id == s.id).order_by(ScoreRecord.recorded_at.desc()).limit(5)
        ).all()
        return {
            "id": s.id,
            "name": s.full_name,
            "class": s.classroom.name,
            "note": s.note,
            "linked_chatbot": s.is_linked,
            "topics": [
                {
                    "topic": t.name,
                    "mastery_pct": states[t.id].pct if t.id in states and states[t.id].has_data else None,
                    "observations": states[t.id].n if t.id in states else 0,
                }
                for t in topics
            ],
            "recent_results": [
                {
                    "title": sub.assignment.title if sub.assignment else "",
                    "score_10": to_ten(sub.final_total, sub.max_total),
                    "date": fmt_local(sub.confirmed_at, "%d/%m"),
                }
                for sub in recent
            ],
            "score_records": [
                {"label": r.label, "score": r.score, "max": r.max_score, "topic": r.topic.name if r.topic else None}
                for r in records
            ],
            "trend_pct": [round(p, 1) for _, p in series[-6:]],
            "profile_url": f"/students/{s.id}",
        }

    def tool_get_class_overview(self, class_id=None) -> dict:
        classroom = self._class(class_id)
        table = class_mastery(self.db, classroom)
        alerts = class_alerts(self.db, classroom, table)
        batches = []
        for b in classroom.batches[:5]:
            stats = assignment_service.batch_stats(b)
            batches.append(
                {
                    "title": b.title,
                    "due": fmt_local(b.due_at),
                    "assigned": stats["active"],
                    "submitted_or_graded": stats["done"],
                    "waiting_approval": stats["draft"],
                    "overdue": stats["overdue"],
                }
            )
        self.actions.append(
            {"label": f"Mở tổng quan lớp {classroom.name}", "url": f"/dashboard?class_id={classroom.id}"}
        )
        return {
            "class_name": classroom.name,
            "subject": classroom.subject.name,
            "students": len(classroom.students),
            "linked": sum(1 for s in classroom.students if s.is_linked),
            "topics": [{"topic": t.name, "avg_pct": topic_average(table, t.id)} for t in classroom.subject.topics],
            "recent_batches": batches,
            "alerts": [f"{a.student_name + ': ' if a.student_name else ''}{a.message}" for a in alerts[:15]],
        }

    def tool_record_scores(self, class_id=None, entries=None, label="", max_score=10) -> dict:
        classroom = self._class(class_id)
        entries = entries or []
        if not entries:
            raise ToolError("Không có dòng điểm nào.")
        max_score = float(max_score or 10)
        saved, unmatched, ambiguous = [], [], []
        for entry in entries:
            name = str(entry.get("student", "")).strip()
            try:
                score = float(str(entry.get("score")).replace(",", "."))
            except (TypeError, ValueError):
                unmatched.append(f"{name} (điểm không hợp lệ)")
                continue
            try:
                student = resolve_student(self.db, self.teacher, name, classroom.id)
            except StudentLookupError as exc:
                (ambiguous if exc.candidates else unmatched).append(name)
                continue
            topic = self._topic(classroom, entry["topic"]) if entry.get("topic") else None
            self.db.add(
                ScoreRecord(
                    student_id=student.id,
                    topic_id=topic.id if topic else None,
                    label=(label or "Điểm nhập qua trợ lý")[:120],
                    score=max(0.0, min(score, max_score)),
                    max_score=max_score,
                    source="assistant",
                )
            )
            saved.append(student.full_name)
        self.db.flush()
        return {
            "saved": len(saved),
            "unmatched": unmatched,
            "ambiguous": ambiguous,
            "note": "Điểm đã được dùng để cập nhật mức nắm vững.",
        }

    def tool_create_personalized_assignments(
        self,
        class_id=None,
        title="",
        due_at=None,
        num_questions=4,
        mode="auto",
        students=None,
        topics=None,
        instruction="",
    ) -> dict:
        classroom = self._class(class_id)
        student_ids = None
        if students:
            student_ids = []
            for name in students:
                student_ids.append(resolve_student(self.db, self.teacher, name, classroom.id).id)
        topic_ids = [self._topic(classroom, t).id for t in topics] if topics else None
        try:
            due = parse_datetime(due_at) if due_at else None
        except ValueError as exc:
            raise ToolError(f"Hạn nộp không đúng định dạng ISO 8601: {due_at}") from exc
        if not title:
            title = (
                "Bài nâng cao"
                if mode == "advanced"
                else ("Bài ôn tập" if mode == "review" else "Bài luyện tập cá nhân hóa")
            )
            if due:
                title += f" (hạn {fmt_local(due, '%d/%m')})"
        result = assignment_service.create_batch(
            self.db,
            classroom,
            title=title,
            due_at=due,
            num_questions=int(num_questions or 4),
            mode=mode or "auto",
            student_ids=student_ids,
            topic_ids=topic_ids,
            instruction=instruction or "",
            created_by="assistant",
            ai=self.ai,
        )
        batch = result.batch
        url = f"/assignments/batches/{batch.id}"
        self.actions.append({"label": f"Duyệt {len(batch.assignments)} bộ đề", "url": url})
        summary = []
        for a in batch.assignments[:40]:
            topics_text = ", ".join(sorted({f"{i.question.topic.name} ({LEVELS[i.question.level]})" for i in a.items}))
            summary.append({"name": a.student.full_name, "questions": len(a.items), "focus": topics_text})
        return {
            "batch_id": batch.id,
            "class_name": classroom.name,
            "created": len(batch.assignments),
            "mode": batch.mode,
            "mode_label": MODE_LABELS[batch.mode],
            "due": fmt_local(due) if due else None,
            "generated": result.generated,
            "unfilled": result.unfilled,
            "warnings": result.warnings,
            "status": "draft – chờ giáo viên duyệt trên web",
            "review_url": url,
            "students": summary,
        }

    def tool_generate_questions(self, class_id=None, topic="", level=2, count=3, instruction="") -> dict:
        classroom = self._class(class_id)
        t = self._topic(classroom, topic)
        level = int(level)
        if level not in LEVELS:
            raise ToolError("Mức độ phải từ 1 đến 4.")
        count = max(1, min(6, int(count or 3)))
        questions = assignment_service.generate_questions_for_topic(
            self.db, self.ai, classroom.subject, t, level, count, instruction or ""
        )
        url = f"/bank?subject_id={classroom.subject_id}&status=draft"
        self.actions.append({"label": f"Duyệt {len(questions)} câu hỏi mới", "url": url})
        return {
            "created": len(questions),
            "status": "draft – chờ giáo viên duyệt",
            "questions": [truncate(q.content, 160) for q in questions],
            "review_url": url,
        }

    def tool_update_student_note(self, student="", note="", class_id=None) -> dict:
        s = resolve_student(self.db, self.teacher, student, class_id)
        s.note = note.strip()[:1000]
        self.db.flush()
        return {"student": s.full_name, "note": s.note, "saved": True}

    def tool_list_pending_grading(self, class_id=None) -> dict:
        stmt = (
            select(Submission)
            .join(Student, Submission.student_id == Student.id)
            .join(Classroom, Student.classroom_id == Classroom.id)
            .where(Classroom.teacher_id == self.teacher.id, Submission.status == SubmissionStatus.AI_GRADED)
            .order_by(Submission.submitted_at)
        )
        if class_id:
            stmt = stmt.where(Classroom.id == self._class(class_id).id)
        subs = self.db.scalars(stmt).all()
        if subs:
            self.actions.append({"label": f"Xác nhận {len(subs)} bài", "url": "/grading"})
        return {
            "count": len(subs),
            "url": "/grading",
            "items": [
                {
                    "student": s.student.full_name,
                    "title": s.assignment.title if s.assignment else "",
                    "ai_score": f"{fmt_score(s.ai_total)}/{fmt_score(s.max_total)}",
                }
                for s in subs[:15]
            ],
        }
