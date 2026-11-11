"""Quản lý học sinh: thêm, tìm theo tên, cấp lại mã liên kết."""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Classroom, Student, Teacher
from ..utils.text import new_link_code, norm


class StudentLookupError(LookupError):
    def __init__(self, message: str, candidates: list[Student] | None = None):
        super().__init__(message)
        self.candidates = candidates or []


@dataclass
class MatchReport:
    matched: list[tuple[str, Student]] = field(default_factory=list)
    unmatched: list[str] = field(default_factory=list)
    ambiguous: list[tuple[str, list[Student]]] = field(default_factory=list)


def unique_link_code(db: Session) -> str:
    while True:
        code = new_link_code()
        if db.scalar(select(Student.id).where(Student.link_code == code)) is None:
            return code


def add_student(db: Session, classroom: Classroom, full_name: str, student_code: str = "", note: str = "") -> Student:
    full_name = " ".join((full_name or "").split())
    if not full_name:
        raise ValueError("Họ tên học sinh không được để trống.")
    student = Student(
        classroom_id=classroom.id,
        full_name=full_name[:120],
        student_code=(student_code or "").strip()[:40],
        note=(note or "").strip(),
        link_code=unique_link_code(db),
    )
    db.add(student)
    db.flush()
    return student


def reset_link(db: Session, student: Student) -> None:
    """Hủy liên kết chat hiện tại và cấp mã mới (khi học sinh đổi tài khoản hoặc lộ mã)."""
    student.channel = None
    student.chat_id = None
    student.chat_display_name = None
    student.linked_at = None
    student.link_code = unique_link_code(db)
    db.flush()


def match_students(students: list[Student], query: str) -> list[Student]:
    """Tìm học sinh theo mã HS, họ tên đầy đủ, hoặc phần cuối của tên (không phân biệt dấu)."""
    q = norm(query)
    if not q:
        return []
    by_code = [s for s in students if s.student_code and norm(s.student_code) == q]
    if by_code:
        return by_code
    exact = [s for s in students if norm(s.full_name) == q]
    if exact:
        return exact
    suffix = [s for s in students if norm(s.full_name).endswith(" " + q) or norm(s.given_name) == q]
    if suffix:
        return suffix
    return [s for s in students if q in norm(s.full_name)]


def teacher_students(db: Session, teacher: Teacher, class_id: int | None = None) -> list[Student]:
    stmt = select(Student).join(Classroom).where(Classroom.teacher_id == teacher.id)
    if class_id:
        stmt = stmt.where(Classroom.id == class_id)
    return list(db.scalars(stmt).all())


def resolve_student(db: Session, teacher: Teacher, query: str | int, class_id: int | None = None) -> Student:
    students = teacher_students(db, teacher, class_id)
    text = str(query).strip()
    if text.isdigit():
        found = next((s for s in students if s.id == int(text)), None)
        if found:
            return found
    matches = match_students(students, text)
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise StudentLookupError(f"Không tìm thấy học sinh «{text}».")
    raise StudentLookupError(f"Có {len(matches)} học sinh khớp «{text}», cần nói rõ hơn.", matches)


def match_names(students: list[Student], names: list[str]) -> MatchReport:
    report = MatchReport()
    for name in names:
        found = match_students(students, name)
        if len(found) == 1:
            report.matched.append((name, found[0]))
        elif not found:
            report.unmatched.append(name)
        else:
            report.ambiguous.append((name, found))
    return report
