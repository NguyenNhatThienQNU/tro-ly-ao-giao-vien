"""Kịch bản hội thoại với học sinh – dùng chung cho mọi kênh chat.

Lớp này không biết gì về Telegram/Zalo: nhận (kênh, chat_id, nội dung) và trả về danh sách
tin nhắn cần gửi. Nhờ vậy dễ kiểm thử và dễ thêm kênh mới.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import Settings
from ..db import session_scope
from ..models import (
    Assignment,
    AssignmentStatus,
    Student,
    Submission,
    SubmissionImage,
    SubmissionStatus,
)
from ..services import messages
from ..services.assignments import collecting_submission, open_assignments
from ..services.mastery import mastery_for_students
from ..services.storage import InvalidUpload, delete_submission_files, save_submission_file
from ..utils.text import clean_code, looks_like_link_code, norm, truncate
from ..utils.timeutil import utcnow
from .base import Button, OutgoingMessage

log = logging.getLogger(__name__)

MAX_IMAGES_PER_SUBMISSION = 10
COLLECTING_TTL = timedelta(hours=24)

CMD_LIST = {"baitap", "bt", "bai", "de", "xembai"}
CMD_RESULTS = {"ketqua", "kq", "diem", "xemdiem"}
CMD_PROGRESS = {"tiendo", "td", "nangluc"}
CMD_SUBMIT = {"nop", "nopbai", "submit"}
CMD_CANCEL = {"huy", "huybai", "huyanh", "cancel"}
CMD_HELP = {"huongdan", "help", "trogiup", "menu", "hd", "start"}


@dataclass
class ImageResult:
    messages: list[OutgoingMessage] = field(default_factory=list)
    schedule_ack: bool = False  # True: kênh nên gửi tin xác nhận sau vài giây (gom nhiều ảnh)


def public_assignment_url(settings: Settings, assignment: Assignment) -> str | None:
    base = settings.public_base_url.rstrip("/")
    if not base or "localhost" in base or "127.0.0.1" in base:
        return None  # học sinh không mở được địa chỉ nội bộ
    return f"{base}/bai/{assignment.access_token}"


class StudentBot:
    def __init__(self, settings: Settings):
        self.settings = settings

    # ------------------------------------------------------------------
    @staticmethod
    def find_student(db: Session, channel: str, chat_id: str) -> Student | None:
        return db.scalar(select(Student).where(Student.channel == channel, Student.chat_id == str(chat_id)))

    # ------------------------------------------------------------------
    # Văn bản
    # ------------------------------------------------------------------
    def handle_text(self, channel: str, chat_id: str, display_name: str, text: str) -> list[OutgoingMessage]:
        text = (text or "").strip()
        with session_scope() as db:
            if text.lower().startswith("/start"):
                payload = text[6:].strip()
                if payload:
                    return self._link(db, channel, chat_id, display_name, payload)
                student = self.find_student(db, channel, chat_id)
                return [OutgoingMessage(messages.welcome_text(student) if student else messages.NOT_LINKED_TEXT)]

            student = self.find_student(db, channel, chat_id)
            if looks_like_link_code(text) and (student is None or clean_code(text) != student.link_code):
                return self._link(db, channel, chat_id, display_name, text)
            if student is None:
                return [OutgoingMessage(messages.NOT_LINKED_TEXT)]

            cmd = norm(text).lstrip("/").replace(" ", "")
            if cmd in CMD_LIST:
                return [OutgoingMessage(messages.assignment_list_text(open_assignments(db, student)))]
            if cmd in CMD_RESULTS:
                return [self._results(db, student)]
            if cmd in CMD_PROGRESS:
                return [self._progress(db, student)]
            if cmd in CMD_SUBMIT:
                return self._submit(db, student)
            if cmd in CMD_CANCEL:
                return self._cancel(db, student)
            if cmd in CMD_HELP:
                return [OutgoingMessage(messages.HELP_TEXT)]
            if cmd.isdigit():
                return self._pick_by_number(db, student, int(cmd))
            return [
                OutgoingMessage(
                    "Em gửi ảnh bài làm vào đây để nộp, hoặc gõ HUONGDAN để xem các lệnh nhé. "
                    "Câu hỏi về bài học em hỏi trực tiếp thầy/cô."
                )
            ]

    def handle_action(self, channel: str, chat_id: str, action: str) -> list[OutgoingMessage]:
        """Xử lý khi học sinh bấm nút (kênh có hỗ trợ nút bấm)."""
        with session_scope() as db:
            student = self.find_student(db, channel, chat_id)
            if student is None:
                return [OutgoingMessage(messages.NOT_LINKED_TEXT)]
            if action == "submit":
                return self._submit(db, student)
            if action == "cancel":
                return self._cancel(db, student)
            if action == "list":
                return [OutgoingMessage(messages.assignment_list_text(open_assignments(db, student)))]
            if action.startswith("pick:"):
                try:
                    return self._pick(db, student, int(action.split(":", 1)[1]))
                except ValueError:
                    pass
            return []

    # ------------------------------------------------------------------
    # Ảnh bài làm
    # ------------------------------------------------------------------
    def handle_image(self, channel: str, chat_id: str, display_name: str, data: bytes, mime_type: str) -> ImageResult:
        with session_scope() as db:
            student = self.find_student(db, channel, chat_id)
            if student is None:
                return ImageResult([OutgoingMessage(messages.NOT_LINKED_TEXT)])
            sub = collecting_submission(db, student)
            if sub is not None and utcnow() - sub.created_at > COLLECTING_TTL:
                delete_submission_files(self.settings, sub.id)
                db.delete(sub)
                db.flush()
                sub = None
            if sub is None:
                opens = open_assignments(db, student)
                if not opens:
                    return ImageResult([OutgoingMessage("Hiện em không có bài nào cần nộp nên bot chưa nhận ảnh này.")])
                sub = Submission(
                    student_id=student.id,
                    assignment_id=opens[0].id if len(opens) == 1 else None,
                    status=SubmissionStatus.COLLECTING,
                )
                db.add(sub)
                db.flush()
            if len(sub.images) >= MAX_IMAGES_PER_SUBMISSION:
                return ImageResult(
                    [OutgoingMessage(f"Mỗi bài nộp tối đa {MAX_IMAGES_PER_SUBMISSION} ảnh. Em gõ NOP để nộp nhé.")]
                )
            position = len(sub.images) + 1
            try:
                rel_path, mime = save_submission_file(self.settings, sub.id, position, data, mime_type)
            except InvalidUpload as exc:
                return ImageResult([OutgoingMessage(f"⚠️ {exc}")])
            sub.images.append(SubmissionImage(file_path=rel_path, mime_type=mime, position=position))
            return ImageResult(schedule_ack=True)

    def collecting_status(self, channel: str, chat_id: str) -> list[OutgoingMessage]:
        """Tin xác nhận đã nhận ảnh (gửi sau khi học sinh ngừng gửi ảnh vài giây)."""
        with session_scope() as db:
            student = self.find_student(db, channel, chat_id)
            if student is None:
                return []
            sub = collecting_submission(db, student)
            if sub is None or not sub.images:
                return []
            if sub.assignment is None:
                return [self._pick_prompt(db, student, sub)]
            return [
                OutgoingMessage(
                    f"📥 Đã nhận {len(sub.images)} ảnh cho bài «{sub.assignment.title}».\n"
                    "Nếu bài còn trang khác, em gửi tiếp ảnh. Xong thì gõ NOP để nộp bài, hoặc HUY để làm lại.",
                    [[Button("✅ Nộp bài", "submit"), Button("🗑 Hủy", "cancel")]],
                )
            ]

    # ------------------------------------------------------------------
    # Nội bộ
    # ------------------------------------------------------------------
    def _link(self, db: Session, channel: str, chat_id: str, display_name: str, raw: str) -> list[OutgoingMessage]:
        code = clean_code(raw)
        student = db.scalar(select(Student).where(Student.link_code == code))
        if student is None:
            return [OutgoingMessage("❌ Mã liên kết không đúng. Em kiểm tra lại mã 8 ký tự trên phiếu nhé.")]
        if student.chat_id == str(chat_id) and student.channel == channel:
            return [OutgoingMessage(f"Em đã liên kết rồi, {student.full_name} 😊\n\n{messages.HELP_TEXT}")]
        if student.chat_id:
            return [
                OutgoingMessage(
                    "⚠️ Mã này đã được liên kết với một tài khoản khác. Nếu em đổi tài khoản, "
                    "nhờ thầy/cô bấm «Cấp lại mã» rồi quét mã mới."
                )
            ]
        for other in db.scalars(select(Student).where(Student.channel == channel, Student.chat_id == str(chat_id))):
            other.channel = other.chat_id = other.chat_display_name = None
            other.linked_at = None
        db.flush()
        student.channel = channel
        student.chat_id = str(chat_id)
        student.chat_display_name = (display_name or "")[:120] or None
        student.linked_at = utcnow()
        db.flush()
        log.info("Học sinh #%s liên kết %s:%s", student.id, channel, chat_id)
        return [OutgoingMessage(messages.welcome_text(student))]

    def _pick_prompt(self, db: Session, student: Student, sub: Submission) -> OutgoingMessage:
        opens = open_assignments(db, student)
        lines = [f"📥 Đã nhận {len(sub.images)} ảnh. Bài làm này thuộc bài nào? Em gõ số tương ứng:"]
        lines += [f"{i}. {a.title}" for i, a in enumerate(opens, start=1)]
        buttons = [[Button(f"{i}. {truncate(a.title, 40)}", f"pick:{a.id}")] for i, a in enumerate(opens, start=1)]
        return OutgoingMessage("\n".join(lines), buttons)

    def _pick_by_number(self, db: Session, student: Student, number: int) -> list[OutgoingMessage]:
        opens = open_assignments(db, student)
        if not 1 <= number <= len(opens):
            return [OutgoingMessage("Số không hợp lệ. Em gõ BAITAP để xem danh sách bài.")]
        return self._pick(db, student, opens[number - 1].id)

    def _pick(self, db: Session, student: Student, assignment_id: int) -> list[OutgoingMessage]:
        sub = collecting_submission(db, student)
        if sub is None:
            return [OutgoingMessage("Em gửi ảnh bài làm trước, rồi chọn bài sau nhé.")]
        assignment = db.get(Assignment, assignment_id)
        if assignment is None or assignment.student_id != student.id or assignment.status != AssignmentStatus.ASSIGNED:
            return [OutgoingMessage("Bài này không còn nhận nộp. Em gõ BAITAP để xem bài đang mở.")]
        sub.assignment_id = assignment.id
        db.flush()
        db.refresh(sub)
        return [
            OutgoingMessage(
                f"📌 Đã gắn {len(sub.images)} ảnh vào bài «{assignment.title}». "
                "Gửi tiếp ảnh nếu còn trang, xong thì gõ NOP để nộp.",
                [[Button("✅ Nộp bài", "submit"), Button("🗑 Hủy", "cancel")]],
            )
        ]

    def _submit(self, db: Session, student: Student) -> list[OutgoingMessage]:
        sub = collecting_submission(db, student)
        if sub is None or not sub.images:
            return [OutgoingMessage("Em chưa gửi ảnh nào. Hãy chụp ảnh bài làm và gửi vào đây trước nhé.")]
        if sub.assignment is None:
            return [self._pick_prompt(db, student, sub)]
        assignment = sub.assignment
        if assignment.status != AssignmentStatus.ASSIGNED:
            delete_submission_files(self.settings, sub.id)
            db.delete(sub)
            return [OutgoingMessage("Bài này không còn nhận nộp (đã nộp hoặc đã hủy). Em gõ BAITAP để kiểm tra.")]
        now = utcnow()
        sub.status = SubmissionStatus.SUBMITTED
        sub.submitted_at = now
        sub.is_late = bool(assignment.due_at and now > assignment.due_at)
        sub.max_total = assignment.max_total
        assignment.status = AssignmentStatus.SUBMITTED
        db.flush()
        late = " (nộp muộn)" if sub.is_late else ""
        return [
            OutgoingMessage(
                f"✅ Đã nộp bài «{assignment.title}» với {len(sub.images)} ảnh{late}.\n"
                "Hệ thống đang chấm sơ bộ; thầy/cô sẽ xem lại và gửi kết quả cho em."
            )
        ]

    def _cancel(self, db: Session, student: Student) -> list[OutgoingMessage]:
        sub = collecting_submission(db, student)
        if sub is None:
            return [OutgoingMessage("Không có ảnh nào đang chờ nộp.")]
        count = len(sub.images)
        delete_submission_files(self.settings, sub.id)
        db.delete(sub)
        return [OutgoingMessage(f"🗑 Đã hủy {count} ảnh. Em có thể gửi lại ảnh mới.")]

    def _results(self, db: Session, student: Student) -> OutgoingMessage:
        subs = db.scalars(
            select(Submission)
            .where(Submission.student_id == student.id, Submission.status == SubmissionStatus.CONFIRMED)
            .order_by(Submission.confirmed_at.desc())
            .limit(5)
        ).all()
        return OutgoingMessage(messages.results_list_text(list(subs)))

    def _progress(self, db: Session, student: Student) -> OutgoingMessage:
        topics = list(student.classroom.subject.topics)
        table = mastery_for_students(db, [student], [t.id for t in topics])
        return OutgoingMessage(messages.progress_text(student, topics, table.get(student.id, {})))
