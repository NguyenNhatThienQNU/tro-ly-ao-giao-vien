"""Mô hình dữ liệu.

Sơ đồ quan hệ chính:
    Teacher 1─n Subject 1─n Topic 1─n Question            (ngân hàng câu hỏi)
    Teacher 1─n Classroom n─1 Subject; Classroom 1─n Student
    Classroom 1─n AssignmentBatch 1─n Assignment 1─n AssignmentItem n─1 Question
    Assignment 1─n Submission 1─n SubmissionImage, Submission 1─n ItemGrade
    Student 1─n ScoreRecord                                 (điểm nhập từ bảng điểm)
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base
from .utils.text import new_link_code, new_token
from .utils.timeutil import utcnow

# Bốn mức độ nhận thức theo chương trình GDPT 2018
LEVELS: dict[int, str] = {1: "Nhận biết", 2: "Thông hiểu", 3: "Vận dụng", 4: "Vận dụng cao"}


class AssignmentStatus:
    DRAFT = "draft"  # hệ thống/AI đề xuất, chờ giáo viên duyệt
    ASSIGNED = "assigned"  # đã duyệt, gửi (hoặc chờ gửi) cho học sinh
    SUBMITTED = "submitted"  # học sinh đã nộp
    GRADED = "graded"  # giáo viên đã xác nhận điểm
    CANCELLED = "cancelled"

    LABELS = {
        DRAFT: "Chờ duyệt",
        ASSIGNED: "Đã giao",
        SUBMITTED: "Đã nộp",
        GRADED: "Đã chấm",
        CANCELLED: "Đã hủy",
    }


class SubmissionStatus:
    COLLECTING = "collecting"  # học sinh đang gửi ảnh, chưa bấm nộp
    SUBMITTED = "submitted"  # chờ AI chấm
    GRADING = "grading"  # AI đang chấm
    AI_GRADED = "ai_graded"  # chờ giáo viên xác nhận
    CONFIRMED = "confirmed"  # giáo viên đã xác nhận
    RETURNED = "returned"  # giáo viên yêu cầu nộp lại
    FAILED = "failed"  # AI chấm lỗi nhiều lần, cần chấm tay

    LABELS = {
        COLLECTING: "Đang gửi ảnh",
        SUBMITTED: "Chờ AI chấm",
        GRADING: "AI đang chấm",
        AI_GRADED: "Chờ xác nhận",
        CONFIRMED: "Đã xác nhận",
        RETURNED: "Yêu cầu nộp lại",
        FAILED: "AI lỗi – chấm tay",
    }


class Teacher(Base):
    __tablename__ = "teachers"

    id: Mapped[int] = mapped_column(primary_key=True)
    full_name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    subjects: Mapped[list[Subject]] = relationship(back_populates="teacher", cascade="all, delete-orphan")
    classrooms: Mapped[list[Classroom]] = relationship(back_populates="teacher", cascade="all, delete-orphan")


class Subject(Base):
    """Môn học theo khối, ví dụ "Tin học 10"."""

    __tablename__ = "subjects"

    id: Mapped[int] = mapped_column(primary_key=True)
    teacher_id: Mapped[int] = mapped_column(ForeignKey("teachers.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    teacher: Mapped[Teacher] = relationship(back_populates="subjects")
    topics: Mapped[list[Topic]] = relationship(
        back_populates="subject", cascade="all, delete-orphan", order_by="Topic.position"
    )
    questions: Mapped[list[Question]] = relationship(back_populates="subject", cascade="all, delete-orphan")
    classrooms: Mapped[list[Classroom]] = relationship(back_populates="subject")


class Topic(Base):
    """Chủ đề kiến thức – đơn vị để tính mức độ nắm vững."""

    __tablename__ = "topics"

    id: Mapped[int] = mapped_column(primary_key=True)
    subject_id: Mapped[int] = mapped_column(ForeignKey("subjects.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(160))
    description: Mapped[str] = mapped_column(Text, default="")
    position: Mapped[int] = mapped_column(Integer, default=0)

    subject: Mapped[Subject] = relationship(back_populates="topics")
    questions: Mapped[list[Question]] = relationship(back_populates="topic")


class Classroom(Base):
    __tablename__ = "classrooms"

    id: Mapped[int] = mapped_column(primary_key=True)
    teacher_id: Mapped[int] = mapped_column(ForeignKey("teachers.id", ondelete="CASCADE"), index=True)
    subject_id: Mapped[int] = mapped_column(ForeignKey("subjects.id", ondelete="RESTRICT"), index=True)
    name: Mapped[str] = mapped_column(String(80))
    school_year: Mapped[str] = mapped_column(String(20), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    teacher: Mapped[Teacher] = relationship(back_populates="classrooms")
    subject: Mapped[Subject] = relationship(back_populates="classrooms")
    students: Mapped[list[Student]] = relationship(
        back_populates="classroom", cascade="all, delete-orphan", order_by="Student.full_name"
    )
    batches: Mapped[list[AssignmentBatch]] = relationship(
        back_populates="classroom", cascade="all, delete-orphan", order_by="AssignmentBatch.created_at.desc()"
    )


class Student(Base):
    __tablename__ = "students"
    __table_args__ = (UniqueConstraint("channel", "chat_id", name="uq_student_channel_chat"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    classroom_id: Mapped[int] = mapped_column(ForeignKey("classrooms.id", ondelete="CASCADE"), index=True)
    full_name: Mapped[str] = mapped_column(String(120))
    student_code: Mapped[str] = mapped_column(String(40), default="")
    note: Mapped[str] = mapped_column(Text, default="")
    # Liên kết chatbot: mã in trên phiếu QR, học sinh gửi mã/quét QR để gắn tài khoản chat
    link_code: Mapped[str] = mapped_column(String(16), unique=True, index=True, default=new_link_code)
    channel: Mapped[str | None] = mapped_column(String(20), nullable=True)
    chat_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    chat_display_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    linked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    classroom: Mapped[Classroom] = relationship(back_populates="students")
    assignments: Mapped[list[Assignment]] = relationship(back_populates="student", cascade="all, delete-orphan")
    submissions: Mapped[list[Submission]] = relationship(back_populates="student", cascade="all, delete-orphan")
    score_records: Mapped[list[ScoreRecord]] = relationship(back_populates="student", cascade="all, delete-orphan")

    @property
    def is_linked(self) -> bool:
        return bool(self.chat_id)

    @property
    def given_name(self) -> str:
        parts = self.full_name.split()
        return parts[-1] if parts else self.full_name


class Question(Base):
    """Câu hỏi tự luận trong ngân hàng, có rubric chấm và đáp án tham khảo."""

    __tablename__ = "questions"

    id: Mapped[int] = mapped_column(primary_key=True)
    subject_id: Mapped[int] = mapped_column(ForeignKey("subjects.id", ondelete="CASCADE"), index=True)
    topic_id: Mapped[int] = mapped_column(ForeignKey("topics.id", ondelete="CASCADE"), index=True)
    content: Mapped[str] = mapped_column(Text)
    level: Mapped[int] = mapped_column(Integer, default=2)
    max_score: Mapped[float] = mapped_column(Float, default=2.0)
    # [{"criterion": "Mô tả tiêu chí", "points": 1.0}, ...] – tổng điểm bằng max_score
    rubric: Mapped[list] = mapped_column(JSON, default=list)
    reference_answer: Mapped[str] = mapped_column(Text, default="")
    source: Mapped[str] = mapped_column(String(20), default="bank")  # bank | ai | import
    status: Mapped[str] = mapped_column(String(20), default="active", index=True)  # active | draft | archived
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    subject: Mapped[Subject] = relationship(back_populates="questions")
    topic: Mapped[Topic] = relationship(back_populates="questions")

    @property
    def level_name(self) -> str:
        return LEVELS.get(self.level, str(self.level))


class AssignmentBatch(Base):
    """Một đợt giao bài cho lớp (mỗi học sinh nhận một bộ đề riêng)."""

    __tablename__ = "assignment_batches"

    id: Mapped[int] = mapped_column(primary_key=True)
    classroom_id: Mapped[int] = mapped_column(ForeignKey("classrooms.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    mode: Mapped[str] = mapped_column(String(20), default="auto")  # auto | advanced | review
    num_questions: Mapped[int] = mapped_column(Integer, default=4)
    due_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    instruction: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[str] = mapped_column(String(20), default="teacher")  # teacher | assistant
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    classroom: Mapped[Classroom] = relationship(back_populates="batches")
    assignments: Mapped[list[Assignment]] = relationship(
        back_populates="batch", cascade="all, delete-orphan", order_by="Assignment.id"
    )


class Assignment(Base):
    """Bộ đề cá nhân của một học sinh."""

    __tablename__ = "assignments"

    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[int | None] = mapped_column(
        ForeignKey("assignment_batches.id", ondelete="CASCADE"), nullable=True, index=True
    )
    classroom_id: Mapped[int] = mapped_column(ForeignKey("classrooms.id", ondelete="CASCADE"), index=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(20), default=AssignmentStatus.DRAFT, index=True)
    due_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    rationale: Mapped[str] = mapped_column(Text, default="")  # vì sao chọn các câu này
    note: Mapped[str] = mapped_column(Text, default="")  # lời nhắn của giáo viên
    access_token: Mapped[str] = mapped_column(String(40), unique=True, index=True, default=new_token)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    assigned_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    reminder_sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    batch: Mapped[AssignmentBatch | None] = relationship(back_populates="assignments")
    student: Mapped[Student] = relationship(back_populates="assignments")
    items: Mapped[list[AssignmentItem]] = relationship(
        back_populates="assignment", cascade="all, delete-orphan", order_by="AssignmentItem.position"
    )
    submissions: Mapped[list[Submission]] = relationship(
        back_populates="assignment", cascade="all, delete-orphan", order_by="Submission.created_at"
    )

    @property
    def max_total(self) -> float:
        return sum(item.question.max_score for item in self.items)

    @property
    def status_label(self) -> str:
        return AssignmentStatus.LABELS.get(self.status, self.status)


class AssignmentItem(Base):
    __tablename__ = "assignment_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    assignment_id: Mapped[int] = mapped_column(ForeignKey("assignments.id", ondelete="CASCADE"), index=True)
    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id", ondelete="RESTRICT"), index=True)
    position: Mapped[int] = mapped_column(Integer, default=0)

    assignment: Mapped[Assignment] = relationship(back_populates="items")
    question: Mapped[Question] = relationship()


class Submission(Base):
    __tablename__ = "submissions"

    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id", ondelete="CASCADE"), index=True)
    assignment_id: Mapped[int | None] = mapped_column(
        ForeignKey("assignments.id", ondelete="CASCADE"), nullable=True, index=True
    )
    status: Mapped[str] = mapped_column(String(20), default=SubmissionStatus.COLLECTING, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    graded_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    result_sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    is_late: Mapped[bool] = mapped_column(Boolean, default=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str] = mapped_column(Text, default="")
    ai_summary: Mapped[str] = mapped_column(Text, default="")
    ai_image_quality: Mapped[str] = mapped_column(String(30), default="")
    ai_total: Mapped[float | None] = mapped_column(Float, nullable=True)
    final_total: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_total: Mapped[float] = mapped_column(Float, default=0.0)
    teacher_comment: Mapped[str] = mapped_column(Text, default="")

    student: Mapped[Student] = relationship(back_populates="submissions")
    assignment: Mapped[Assignment | None] = relationship(back_populates="submissions")
    images: Mapped[list[SubmissionImage]] = relationship(
        back_populates="submission", cascade="all, delete-orphan", order_by="SubmissionImage.position"
    )
    grades: Mapped[list[ItemGrade]] = relationship(
        back_populates="submission", cascade="all, delete-orphan", order_by="ItemGrade.position"
    )

    @property
    def status_label(self) -> str:
        return SubmissionStatus.LABELS.get(self.status, self.status)

    @property
    def min_confidence(self) -> float | None:
        values = [g.confidence for g in self.grades if g.confidence is not None]
        return min(values) if values else None


class SubmissionImage(Base):
    __tablename__ = "submission_images"

    id: Mapped[int] = mapped_column(primary_key=True)
    submission_id: Mapped[int] = mapped_column(ForeignKey("submissions.id", ondelete="CASCADE"), index=True)
    file_path: Mapped[str] = mapped_column(String(500))  # đường dẫn tương đối trong data/uploads
    mime_type: Mapped[str] = mapped_column(String(60), default="image/jpeg")
    position: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    submission: Mapped[Submission] = relationship(back_populates="images")


class ItemGrade(Base):
    """Kết quả chấm từng câu: AI đề xuất (ai_*) và giáo viên quyết định (final_score)."""

    __tablename__ = "item_grades"

    id: Mapped[int] = mapped_column(primary_key=True)
    submission_id: Mapped[int] = mapped_column(ForeignKey("submissions.id", ondelete="CASCADE"), index=True)
    assignment_item_id: Mapped[int] = mapped_column(ForeignKey("assignment_items.id", ondelete="CASCADE"))
    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id", ondelete="RESTRICT"), index=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    max_score: Mapped[float] = mapped_column(Float, default=0.0)
    found: Mapped[bool] = mapped_column(Boolean, default=True)
    transcription: Mapped[str] = mapped_column(Text, default="")
    ai_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    final_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    ai_comment: Mapped[str] = mapped_column(Text, default="")
    # [{"description":..., "explanation":..., "fix":...}]
    errors: Mapped[list] = mapped_column(JSON, default=list)
    # [{"criterion":..., "max_points":..., "awarded":..., "comment":...}]
    criteria: Mapped[list] = mapped_column(JSON, default=list)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    teacher_comment: Mapped[str] = mapped_column(Text, default="")

    submission: Mapped[Submission] = relationship(back_populates="grades")
    question: Mapped[Question] = relationship()

    @property
    def effective_score(self) -> float | None:
        return self.final_score if self.final_score is not None else self.ai_score


class ScoreRecord(Base):
    """Điểm nhập từ bảng điểm (kiểm tra trên lớp...). topic_id rỗng = điểm chung toàn môn."""

    __tablename__ = "score_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id", ondelete="CASCADE"), index=True)
    topic_id: Mapped[int | None] = mapped_column(ForeignKey("topics.id", ondelete="SET NULL"), nullable=True)
    label: Mapped[str] = mapped_column(String(120), default="")
    score: Mapped[float] = mapped_column(Float)
    max_score: Mapped[float] = mapped_column(Float, default=10.0)
    source: Mapped[str] = mapped_column(String(20), default="import")  # import | assistant | manual
    recorded_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    student: Mapped[Student] = relationship(back_populates="score_records")
    topic: Mapped[Topic | None] = relationship()


class AssistantMessage(Base):
    """Lịch sử hội thoại giữa giáo viên và trợ lý AI."""

    __tablename__ = "assistant_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    teacher_id: Mapped[int] = mapped_column(ForeignKey("teachers.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(20))  # user | assistant
    content: Mapped[str] = mapped_column(Text)
    actions: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
