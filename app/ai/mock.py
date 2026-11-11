"""Chế độ DEMO: chạy toàn bộ quy trình khi chưa có khóa API.

- Chấm bài: sinh điểm mô phỏng ổn định (cùng ảnh -> cùng điểm), có ghi chú rõ là demo.
- Sinh câu hỏi: tạo câu hỏi mẫu theo khuôn.
- Trợ lý: nhận diện vài câu lệnh thường gặp (tạo bộ đề cho cả lớp / nâng cao cho một học sinh,
  xem tổng quan lớp, bài chờ chấm) rồi gọi đúng các công cụ như mô hình thật.
"""

from __future__ import annotations

import hashlib
import re

from ..utils.text import fmt_score, norm, round_quarter
from ..utils.timeutil import now_local
from ..utils.vndate import parse_vn_deadline
from .base import AIProvider, ChatSession
from .schemas import (
    CriterionResult,
    ErrorItem,
    GeneratedQuestion,
    GeneratedRubricItem,
    GradingRequest,
    GradingResult,
    ModelTurn,
    QuestionGenRequest,
    QuestionResult,
    ToolCall,
    ToolResult,
)

DEMO_NOTE = "(Chế độ demo – chưa cấu hình GEMINI_API_KEY nên kết quả chỉ mang tính minh họa.)"

DEMO_HELP = (
    "Em đang chạy ở **chế độ demo** (chưa có GEMINI_API_KEY), nên chỉ hiểu một số câu lệnh mẫu:\n"
    "- «Tạo bộ đề cá nhân hóa cho từng bạn lớp 10 TOÁN, 4 câu, hạn 10h ngày mai»\n"
    "- «Bạn Minh Anh là học sinh giỏi, tạo bộ đề nâng cao cho bạn ấy, hạn tối thứ 6»\n"
    "- «Tổng quan tình hình lớp 10 TOÁN»\n"
    "- «Có bài nào chờ chấm không?»\n"
    "Thêm khóa Gemini vào tệp .env để trò chuyện tự do, dán bảng điểm, nhờ tư vấn soạn bài..."
)


class MockProvider(AIProvider):
    name = "mock"
    is_real = False

    def grade(self, request: GradingRequest) -> GradingResult:
        digest = hashlib.sha256(b"".join(img.data[:4096] for img in request.images)).digest()
        results = []
        for q in request.questions:
            frac = 0.45 + digest[q.number % len(digest)] / 255 * 0.55
            criteria = [
                CriterionResult(
                    criterion=r.criterion,
                    max_points=r.points,
                    awarded=round_quarter(r.points * frac),
                    comment="Ước lượng mô phỏng.",
                )
                for r in q.rubric
            ]
            score = sum(c.awarded for c in criteria) if criteria else round_quarter(q.max_score * frac)
            errors = []
            if frac < 0.85:
                errors.append(
                    ErrorItem(
                        description="Lời giải còn thiếu hoặc sai ở một bước (mô phỏng).",
                        explanation="Dữ liệu minh họa vì AI chưa được kết nối.",
                        fix="Cấu hình GEMINI_API_KEY để AI đọc bài viết tay thật.",
                    )
                )
            results.append(
                QuestionResult(
                    question_number=q.number,
                    found=True,
                    transcription="[Chế độ demo: chưa đọc chữ viết tay]",
                    criteria=criteria,
                    score=score,
                    comment=f"Em đạt khoảng {frac:.0%} yêu cầu của câu này. {DEMO_NOTE}",
                    errors=errors,
                    confidence=0.5,
                )
            )
        return GradingResult(
            questions=results,
            overall_feedback=f"Em đã hoàn thành bài, cố gắng trình bày rõ từng bước nhé! {DEMO_NOTE}",
            image_quality="trung bình",
        )

    def generate_questions(self, request: QuestionGenRequest) -> list[GeneratedQuestion]:
        half = round_quarter(request.max_score / 2)
        out = []
        for i in range(1, request.count + 1):
            out.append(
                GeneratedQuestion(
                    content=(
                        f"[Câu mẫu do AI-demo soạn #{i}] Mức {request.level_name.lower()} – chủ đề «{request.topic_name}». "
                        "Thầy/cô hãy sửa nội dung trước khi duyệt."
                    ),
                    rubric=[
                        GeneratedRubricItem(criterion="Nêu đúng ý chính / viết đúng cú pháp", points=half),
                        GeneratedRubricItem(criterion="Lời giải đầy đủ, trình bày rõ", points=request.max_score - half),
                    ],
                    reference_answer="(Chế độ demo – chưa có đáp án)",
                )
            )
        return out

    def start_chat(self, system, history, tools, context=None) -> ChatSession:
        return DemoChatSession(context or {})


class DemoChatSession(ChatSession):
    def __init__(self, context: dict):
        self.context = context

    # --------------------------------------------------------------
    def _classes(self) -> list[dict]:
        return self.context.get("classes", [])

    def _find_class(self, n: str) -> dict | None:
        classes = self._classes()
        for c in sorted(classes, key=lambda c: -len(c["name"])):
            if norm(c["name"]) in n:
                return c
        return classes[0] if len(classes) == 1 else None

    def _find_student(self, n: str, classes: list[dict]) -> str | None:
        text = f" {n} "
        best: tuple[int, str] | None = None
        for c in classes:
            for name in c.get("students", []):
                parts = norm(name).split()
                for size in range(len(parts), 0, -1):
                    cand = " ".join(parts[-size:])
                    if f" {cand} " in text and (best is None or len(cand) > best[0]):
                        best = (len(cand), name)
                        break
        return best[1] if best else None

    def send_user(self, text: str) -> ModelTurn:
        n = norm(text)
        cls = self._find_class(n)
        if any(k in n for k in ("cho cham", "chua cham", "can xac nhan", "cho xac nhan")):
            return ModelTurn(tool_calls=[ToolCall("demo", "list_pending_grading", {})])
        if any(k in n for k in ("tong quan", "tinh hinh", "thong ke", "bao cao")):
            if cls is None:
                return ModelTurn(text="Thầy/cô muốn xem tổng quan lớp nào ạ?")
            return ModelTurn(tool_calls=[ToolCall("demo", "get_class_overview", {"class_id": cls["id"]})])
        if "tao" in n and any(k in n for k in (" de", "bai tap", "bo de", "bai luyen")):
            pool = [cls] if cls else self._classes()
            student = self._find_student(n, pool)
            if cls is None and student:
                cls = next((c for c in pool if student in c.get("students", [])), None)
            if cls is None:
                return ModelTurn(text="Thầy/cô muốn tạo bộ đề cho lớp nào ạ?")
            mode = "auto"
            if any(k in n for k in ("nang cao", "hoc sinh gioi", "kho hon", "thu thach")):
                mode = "advanced"
            elif any(k in n for k in ("on tap", "cung co", "de hon")):
                mode = "review"
            args: dict = {"class_id": cls["id"], "mode": mode}
            if m := re.search(r"(\d{1,2})\s*cau", n):
                args["num_questions"] = int(m.group(1))
            if due := parse_vn_deadline(text, now_local()):
                args["due_at"] = due.isoformat()
            if student and not any(k in n for k in ("tung ban", "ca lop", "moi ban", "tung hoc sinh", "moi em")):
                args["students"] = [student]
            return ModelTurn(tool_calls=[ToolCall("demo", "create_personalized_assignments", args)])
        return ModelTurn(text=DEMO_HELP)

    def send_tool_results(self, results: list[ToolResult]) -> ModelTurn:
        r = results[0]
        data = r.result
        if "error" in data:
            extra = ""
            if data.get("candidates"):
                extra = " Các học sinh khớp: " + ", ".join(data["candidates"]) + "."
            return ModelTurn(text=f"Chưa thực hiện được: {data['error']}{extra}")
        if r.name == "create_personalized_assignments":
            due = f", hạn nộp {data['due']}" if data.get("due") else ""
            lines = [
                f"Đã tạo **{data['created']} bộ đề nháp** – chế độ {data['mode_label'].lower()} – cho lớp {data['class_name']}{due}.",
            ]
            for s in data.get("students", [])[:5]:
                lines.append(f"- {s['name']}: {s['focus']}")
            if data.get("generated"):
                lines.append(f"- AI soạn thêm {data['generated']} câu mới (cần duyệt).")
            lines.append(f"Thầy/cô xem lại và bấm duyệt để gửi cho học sinh: {data['review_url']}")
            return ModelTurn(text="\n".join(lines))
        if r.name == "get_class_overview":
            lines = [
                f"**Lớp {data['class_name']}** – {data['students']} học sinh, {data['linked']} đã liên kết chatbot."
            ]
            for t in data.get("topics", []):
                pct = "chưa có dữ liệu" if t["avg_pct"] is None else f"{fmt_score(t['avg_pct'])}%"
                lines.append(f"- {t['topic']}: {pct}")
            if data.get("alerts"):
                lines.append("Cảnh báo:")
                lines += [f"- {a}" for a in data["alerts"][:5]]
            return ModelTurn(text="\n".join(lines))
        if r.name == "list_pending_grading":
            if not data.get("count"):
                return ModelTurn(text="Hiện không có bài nào chờ xác nhận điểm.")
            return ModelTurn(text=f"Có {data['count']} bài chờ xác nhận. Xem tại: {data['url']}")
        return ModelTurn(text="Đã thực hiện xong.")
