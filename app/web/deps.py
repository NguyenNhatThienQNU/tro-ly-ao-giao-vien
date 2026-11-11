"""Phụ thuộc dùng chung cho các route web: CSDL, đăng nhập, CSRF, giao diện."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

from fastapi import Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from markupsafe import Markup, escape
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import Settings
from ..db import SessionLocal
from ..models import (
    LEVELS,
    Assignment,
    AssignmentBatch,
    AssignmentStatus,
    Classroom,
    Question,
    Student,
    Subject,
    Submission,
    SubmissionStatus,
    Teacher,
    Topic,
)
from ..security import new_csrf_token, tokens_match
from ..services.mastery import mastery_css, mastery_label
from ..services.recommender import MODE_LABELS
from ..utils.text import fmt_score, to_ten, truncate
from ..utils.timeutil import fmt_local, humanize_delta, to_input_value

TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATE_DIR))


def _nl2br(text: str | None) -> Markup:
    return Markup("<br>".join(escape(text or "").split("\n")))


templates.env.filters.update(
    localdt=fmt_local,
    score=fmt_score,
    ten=to_ten,
    truncate_text=truncate,
    nl2br=_nl2br,
    humanize=humanize_delta,
    input_dt=to_input_value,
    mcss=mastery_css,
    mlabel=mastery_label,
    tojson_vn=lambda v: Markup(json.dumps(v, ensure_ascii=False)),
)
templates.env.globals.update(
    LEVELS=LEVELS,
    MODE_LABELS=MODE_LABELS,
    AssignmentStatus=AssignmentStatus,
    SubmissionStatus=SubmissionStatus,
)


class LoginRequired(Exception):
    """Chưa đăng nhập – trình xử lý lỗi sẽ chuyển tới trang đăng nhập."""


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def current_teacher(request: Request, db: Session = Depends(get_db)) -> Teacher:
    teacher_id = request.session.get("teacher_id")
    teacher = db.get(Teacher, teacher_id) if teacher_id else None
    if teacher is None:
        raise LoginRequired()
    return teacher


def csrf_token(request: Request) -> str:
    token = request.session.get("csrf")
    if not token:
        token = new_csrf_token()
        request.session["csrf"] = token
    return token


async def verify_csrf(request: Request) -> None:
    if request.method not in ("POST", "PUT", "PATCH", "DELETE"):
        return
    sent = request.headers.get("x-csrf-token")
    if not sent:
        form = await request.form()
        sent = form.get("csrf_token")
    if not tokens_match(sent, request.session.get("csrf")):
        raise HTTPException(status_code=403, detail="Phiên làm việc đã hết hạn. Hãy tải lại trang rồi thử lại.")


def flash(request: Request, message: str, category: str = "success") -> None:
    flashes = request.session.get("_flashes", [])
    flashes.append([category, message])
    request.session["_flashes"] = flashes


def pop_flashes(request: Request) -> list:
    return request.session.pop("_flashes", [])


def redirect(url: str) -> RedirectResponse:
    return RedirectResponse(url, status_code=303)


def pending_grading_count(db: Session, teacher: Teacher) -> int:
    return (
        db.scalar(
            select(func.count(Submission.id))
            .join(Student, Submission.student_id == Student.id)
            .join(Classroom, Student.classroom_id == Classroom.id)
            .where(
                Classroom.teacher_id == teacher.id,
                Submission.status.in_([SubmissionStatus.AI_GRADED, SubmissionStatus.FAILED]),
            )
        )
        or 0
    )


def render(
    request: Request,
    name: str,
    *,
    db: Session | None = None,
    teacher: Teacher | None = None,
    status_code: int = 200,
    **context,
):
    settings: Settings = request.app.state.settings
    context.update(
        teacher=teacher,
        app_name=settings.app_name,
        ai_demo=not request.app.state.ai.is_real,
        flashes=pop_flashes(request),
        csrf_token=csrf_token(request),
        nav_pending=pending_grading_count(db, teacher) if db is not None and teacher is not None else 0,
        active=context.get("active", ""),
    )
    return templates.TemplateResponse(request, name, context, status_code=status_code)


# ---------------------------------------------------------------------------
# Lấy bản ghi kèm kiểm tra quyền sở hữu (giáo viên chỉ thấy dữ liệu của mình)
# ---------------------------------------------------------------------------


def _not_found() -> HTTPException:
    return HTTPException(status_code=404, detail="Không tìm thấy dữ liệu.")


def owned_classroom(db: Session, teacher: Teacher, class_id: int) -> Classroom:
    obj = db.get(Classroom, class_id)
    if obj is None or obj.teacher_id != teacher.id:
        raise _not_found()
    return obj


def owned_student(db: Session, teacher: Teacher, student_id: int) -> Student:
    obj = db.get(Student, student_id)
    if obj is None or obj.classroom.teacher_id != teacher.id:
        raise _not_found()
    return obj


def owned_subject(db: Session, teacher: Teacher, subject_id: int) -> Subject:
    obj = db.get(Subject, subject_id)
    if obj is None or obj.teacher_id != teacher.id:
        raise _not_found()
    return obj


def owned_topic(db: Session, teacher: Teacher, topic_id: int) -> Topic:
    obj = db.get(Topic, topic_id)
    if obj is None or obj.subject.teacher_id != teacher.id:
        raise _not_found()
    return obj


def owned_question(db: Session, teacher: Teacher, question_id: int) -> Question:
    obj = db.get(Question, question_id)
    if obj is None or obj.subject.teacher_id != teacher.id:
        raise _not_found()
    return obj


def owned_batch(db: Session, teacher: Teacher, batch_id: int) -> AssignmentBatch:
    obj = db.get(AssignmentBatch, batch_id)
    if obj is None or obj.classroom.teacher_id != teacher.id:
        raise _not_found()
    return obj


def owned_assignment(db: Session, teacher: Teacher, assignment_id: int) -> Assignment:
    obj = db.get(Assignment, assignment_id)
    if obj is None or obj.student.classroom.teacher_id != teacher.id:
        raise _not_found()
    return obj


def owned_submission(db: Session, teacher: Teacher, submission_id: int) -> Submission:
    obj = db.get(Submission, submission_id)
    if obj is None or obj.student.classroom.teacher_id != teacher.id:
        raise _not_found()
    return obj


def teacher_classes(db: Session, teacher: Teacher) -> list[Classroom]:
    return list(db.scalars(select(Classroom).where(Classroom.teacher_id == teacher.id).order_by(Classroom.name)).all())


def teacher_subjects(db: Session, teacher: Teacher) -> list[Subject]:
    return list(db.scalars(select(Subject).where(Subject.teacher_id == teacher.id).order_by(Subject.name)).all())
