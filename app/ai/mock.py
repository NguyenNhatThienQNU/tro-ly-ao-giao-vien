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


def _smart_mock_question(request: QuestionGenRequest, index: int) -> GeneratedQuestion:
    t = request.topic_name.lower()
    score = request.max_score
    c1_score = round_quarter(score * 0.4)
    c2_score = round_quarter(score * 0.4)
    c3_score = round_quarter(score - c1_score - c2_score)
    if c3_score <= 0:
        c1_score = round_quarter(score / 2)
        c2_score = score - c1_score
        criteria = [
            GeneratedRubricItem(criterion="Nêu đúng cú pháp / giải thuật chính xác", points=c1_score),
            GeneratedRubricItem(criterion="Trình bày đầy đủ, kết quả đúng", points=c2_score),
        ]
    else:
        criteria = [
            GeneratedRubricItem(criterion="Viết đúng cú pháp và khai báo biến / cấu trúc", points=c1_score),
            GeneratedRubricItem(criterion="Xử lý logic và giải thuật chính xác", points=c2_score),
            GeneratedRubricItem(criterion="In kết quả đúng định dạng yêu cầu", points=c3_score),
        ]

    # Python - Biến và kiểu dữ liệu
    if any(k in t for k in ("biến", "kiểu dữ liệu", "lệnh gán")):
        if index % 2 == 1:
            content = (
                "Viết chương trình Python nhập vào từ bàn phím chiều dài và chiều rộng của một hình chữ nhật (số thực).\n"
                "Tính và in ra chu vi, diện tích của hình chữ nhật đó, làm tròn 2 chữ số thập phân."
            )
            answer = "d = float(input())\nr = float(input())\nprint('Chu vi:', round(2 * (d + r), 2))\nprint('Dien tich:', round(d * r, 2))"
        else:
            content = (
                "Viết chương trình Python nhập vào 3 số thực là điểm kiểm tra môn Toán, Văn, Tiếng Anh.\n"
                "Tính điểm trung bình cộng 3 môn và in ra kết quả làm tròn 1 chữ số thập phân."
            )
            answer = "toan = float(input())\nvan = float(input())\nanh = float(input())\ndtb = (toan + van + anh) / 3\nprint('Diem TB:', round(dtb, 1))"

    # Python - Rẽ nhánh if
    elif any(k in t for k in ("rẽ nhánh", "if", "điều kiện")):
        if index % 2 == 1:
            content = (
                "Viết chương trình Python nhập vào một số nguyên năm N. Kiểm tra năm N có phải là năm nhuận hay không.\n"
                "Quy tắc: Năm nhuận chia hết cho 400, hoặc chia hết cho 4 nhưng không chia hết cho 100."
            )
            answer = "n = int(input())\nif (n % 400 == 0) or (n % 4 == 0 and n % 100 != 0):\n    print('Nam nhuan')\nelse:\n    print('Khong phai nam nhuan')"
        else:
            content = (
                "Viết chương trình Python nhập vào điểm trung bình (số thực từ 0 đến 10).\n"
                "In xếp loại học lực: 'Gioi' nếu điểm >= 8.0, 'Kha' nếu từ 6.5 đến dưới 8.0, 'Trung binh' nếu từ 5.0 đến dưới 6.5, còn lại là 'Yeu'."
            )
            answer = "dtb = float(input())\nif dtb >= 8.0:\n    print('Gioi')\nelif dtb >= 6.5:\n    print('Kha')\nelif dtb >= 5.0:\n    print('Trung binh')\nelse:\n    print('Yeu')"

    # Python - Vòng lặp
    elif any(k in t for k in ("vòng lặp", "for", "while")):
        if index % 2 == 1:
            content = (
                "Viết chương trình Python nhập vào một số nguyên dương n (n > 0).\n"
                "Tính và in ra tổng S = 1 + 2 + 3 + ... + n."
            )
            answer = "n = int(input())\ns = sum(range(1, n + 1))\nprint('Tong:', s)"
        else:
            content = (
                "Viết chương trình Python nhập vào số nguyên dương n. In ra tất cả các ước số nguyên dương của n."
            )
            answer = "n = int(input())\nfor i in range(1, n + 1):\n    if n % i == 0:\n        print(i, end=' ')"

    # Python - Danh sách list
    elif any(k in t for k in ("danh sách", "list")):
        content = (
            "Viết chương trình Python nhập vào một dãy số nguyên trên một dòng (cách nhau bởi dấu cách).\n"
            "Tính và in ra phần tử lớn nhất (Max) và phần tử nhỏ nhất (Min) của dãy số đó."
        )
        answer = "a = list(map(int, input().split()))\nprint('Max:', max(a))\nprint('Min:', min(a))"

    # Python - Xâu kí tự string
    elif any(k in t for k in ("xâu", "string", "kí tự")):
        content = (
            "Viết chương trình Python nhập vào một xâu ký tự s.\n"
            "Đếm và in ra số lượng chữ số (0-9) xuất hiện trong xâu s (sử dụng phương thức isdigit())."
        )
        answer = "s = input()\ndem = sum(1 for c in s if c.isdigit())\nprint('So chu so:', dem)"

    # Python - Hàm
    elif any(k in t for k in ("hàm", "function")):
        content = (
            "Viết hàm Python kiem_tra_nguyen_to(n) nhận vào số nguyên n và trả về True nếu n là số nguyên tố, ngược lại trả về False.\n"
            "Viết lời gọi hàm để kiểm tra một số nhập từ bàn phím."
        )
        answer = "def kiem_tra_nguyen_to(n):\n    if n < 2:\n        return False\n    for i in range(2, int(n**0.5) + 1):\n        if n % i == 0:\n            return False\n    return True\n\nx = int(input())\nprint('Nguyen to' if kiem_tra_nguyen_to(x) else 'Khong phai nguyen to')"

    # Python - Thuật toán tìm kiếm & sắp xếp
    elif any(k in t for k in ("tìm kiếm", "sắp xếp")):
        content = (
            "Trình bày thuật toán tìm kiếm tuần tự (Linear Search) bằng Python:\n"
            "Nhập danh sách số nguyên A và giá trị khóa k. In vị trí xuất hiện đầu tiên của k trong A, nếu không có in -1."
        )
        answer = "a = list(map(int, input().split()))\nk = int(input())\nprint(a.index(k) + 1 if k in a else -1)"

    # SQL / CSDL
    elif any(k in t for k in ("sql", "truy vấn", "select")):
        content = (
            "Cho bảng HOC_SINH gồm các trường: MaHS, HoTen, Lop, DiemTin.\n"
            "Viết câu lệnh SQL lấy ra HoTen và DiemTin của các học sinh thuộc lớp '10A1' có DiemTin >= 8.0, sắp xếp giảm dần theo DiemTin."
        )
        answer = "SELECT HoTen, DiemTin FROM HOC_SINH WHERE Lop = '10A1' AND DiemTin >= 8.0 ORDER BY DiemTin DESC;"

    # SQL - Join
    elif any(k in t for k in ("liên kết", "join")):
        content = (
            "Cho bảng LOP(MaLop, TenLop) và bảng HOC_SINH(MaHS, HoTen, MaLop).\n"
            "Viết câu lệnh SQL sử dụng INNER JOIN để hiển thị: MaHS, HoTen, TenLop của toàn bộ học sinh."
        )
        answer = "SELECT HOC_SINH.MaHS, HOC_SINH.HoTen, LOP.TenLop\nFROM HOC_SINH\nINNER JOIN LOP ON HOC_SINH.MaLop = LOP.MaLop;"

    # Mặc định
    else:
        content = (
            f"Hãy nêu khái niệm cơ bản và trình bày 2 ví dụ minh họa cụ thể về chủ đề «{request.topic_name}» trong chương trình Tin học GDPT 2018."
        )
        answer = f"Khái niệm và ứng dụng của {request.topic_name}: Nêu định nghĩa chính xác, lấy ví dụ thực tiễn minh họa và phân tích giải pháp."

    return GeneratedQuestion(content=content, rubric=criteria, reference_answer=answer)


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
        return [_smart_mock_question(request, i) for i in range(1, request.count + 1)]

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
