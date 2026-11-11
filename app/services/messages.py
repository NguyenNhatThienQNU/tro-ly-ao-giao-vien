"""Soạn nội dung tin nhắn gửi học sinh (dạng văn bản thuần, dùng chung cho mọi kênh chat)."""

from __future__ import annotations

from collections.abc import Iterable

from ..models import Assignment, Student, Submission, Topic
from ..utils.text import fmt_score, to_ten
from ..utils.timeutil import fmt_local, humanize_delta
from .mastery import TopicMastery

HELP_TEXT = (
    "📌 Hướng dẫn:\n"
    "• Khi thầy/cô giao bài, bot sẽ gửi đề cho em.\n"
    "• Nộp bài: làm ra giấy, ghi rõ số câu, chụp rõ từng trang và gửi ảnh vào đây, sau đó gõ NOP.\n"
    "• BAITAP: xem bài đang cần làm\n"
    "• KETQUA: xem kết quả gần đây\n"
    "• TIENDO: xem mức nắm vững từng chủ đề\n"
    "• HUY: hủy các ảnh vừa gửi (khi chưa nộp)"
)

NOT_LINKED_TEXT = (
    "Em chưa liên kết tài khoản với lớp học. Hãy quét mã QR trên phiếu thầy/cô phát, "
    "hoặc gửi mã liên kết 8 ký tự in trên phiếu (ví dụ: K7M2QX9P) vào đây."
)


def welcome_text(student: Student) -> str:
    classroom = student.classroom
    return (
        f"🎉 Chào {student.full_name}! Em đã liên kết thành công với lớp {classroom.name} "
        f"– môn {classroom.subject.name}.\n\n{HELP_TEXT}"
    )


def assignment_text(assignment: Assignment, view_url: str | None = None) -> str:
    lines = [f"📚 BÀI MỚI: {assignment.title}"]
    if assignment.due_at:
        lines.append(f"⏰ Hạn nộp: {fmt_local(assignment.due_at)} ({humanize_delta(assignment.due_at)})")
    if assignment.note:
        lines.append(f"💬 Lời nhắn của thầy/cô: {assignment.note}")
    lines.append("")
    for pos, item in enumerate(assignment.items, start=1):
        q = item.question
        lines.append(f"Câu {pos} ({fmt_score(q.max_score)} điểm – {q.level_name}):")
        lines.append(q.content.strip())
        lines.append("")
    if view_url:
        lines.append(f"🔗 Xem đề dạng trang web: {view_url}")
    lines.append("✍️ Làm bài ra giấy, ghi rõ số câu. Chụp ảnh rõ nét từng trang, gửi vào đây rồi gõ NOP để nộp bài.")
    return "\n".join(lines)


def assignment_list_text(assignments: list[Assignment]) -> str:
    if not assignments:
        return "✅ Hiện em không có bài nào cần nộp."
    lines = ["📋 Bài đang cần làm:"]
    for i, a in enumerate(assignments, start=1):
        due = f" – hạn {fmt_local(a.due_at)} ({humanize_delta(a.due_at)})" if a.due_at else ""
        lines.append(f"{i}. {a.title} ({len(a.items)} câu){due}")
    lines.append("\nGửi ảnh bài làm vào đây để nộp.")
    return "\n".join(lines)


def reminder_text(assignment: Assignment) -> str:
    return (
        f"⏰ Nhắc hạn: bài «{assignment.title}» hết hạn lúc {fmt_local(assignment.due_at)} "
        f"({humanize_delta(assignment.due_at)}). Em nhớ chụp ảnh bài làm và nộp nhé!"
    )


def result_text(sub: Submission) -> str:
    assignment = sub.assignment
    ten = to_ten(sub.final_total, sub.max_total)
    lines = [
        f"📝 KẾT QUẢ: {assignment.title if assignment else 'Bài nộp'}",
        f"Điểm: {fmt_score(sub.final_total)}/{fmt_score(sub.max_total)} → {fmt_score(ten)}/10",
    ]
    for g in sub.grades:
        lines.append("")
        lines.append(f"Câu {g.position}: {fmt_score(g.final_score)}/{fmt_score(g.max_score)} điểm")
        comment = g.teacher_comment or g.ai_comment
        if comment:
            lines.append(f"• Nhận xét: {comment}")
        for err in (g.errors or [])[:3]:
            desc = err.get("description", "")
            fix = err.get("fix", "")
            lines.append(f"• Lỗi: {desc}" + (f" → Cách sửa: {fix}" if fix else ""))
    if sub.ai_summary:
        lines.append(f"\n🌟 {sub.ai_summary}")
    if sub.teacher_comment:
        lines.append(f"\n👩‍🏫 Lời thầy/cô: {sub.teacher_comment}")
    return "\n".join(lines)


def returned_text(sub: Submission) -> str:
    title = sub.assignment.title if sub.assignment else "bài nộp"
    return (
        f"🔁 Thầy/cô yêu cầu em nộp lại bài «{title}».\nLý do: {sub.teacher_comment}\n"
        "Em chụp lại ảnh rõ nét, đủ trang, gửi vào đây rồi gõ NOP nhé."
    )


def results_list_text(subs: list[Submission]) -> str:
    if not subs:
        return "Em chưa có bài nào được chấm."
    lines = ["🏅 Kết quả gần đây:"]
    for s in subs:
        ten = to_ten(s.final_total, s.max_total)
        title = s.assignment.title if s.assignment else "Bài nộp"
        lines.append(f"• {title}: {fmt_score(ten)}/10 ({fmt_local(s.confirmed_at, '%d/%m')})")
    return "\n".join(lines)


def _bar(pct: float, width: int = 10) -> str:
    filled = round(pct / 100 * width)
    return "▰" * filled + "▱" * (width - filled)


def progress_text(student: Student, topics: Iterable[Topic], states: dict[int, TopicMastery]) -> str:
    lines = [f"📈 Mức nắm vững của {student.full_name}:"]
    for topic in topics:
        state = states.get(topic.id)
        if state and state.has_data:
            lines.append(f"• {topic.name}\n  {_bar(state.pct)} {state.pct:.0f}% – {state.label}")
        else:
            lines.append(f"• {topic.name}\n  (chưa có dữ liệu)")
    lines.append("\nCố lên! Mỗi bài em làm giúp hệ thống giao bài sát với em hơn. 💪")
    return "\n".join(lines)
