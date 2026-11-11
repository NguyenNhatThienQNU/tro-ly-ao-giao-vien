"""Môn học, chủ đề và ngân hàng câu hỏi (kèm AI soạn câu hỏi nháp)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..ai.base import AIError
from ..models import LEVELS, AssignmentItem, Question, Subject, Teacher, Topic
from ..services.assignments import DEFAULT_MAX_SCORE, generate_questions_for_topic, normalize_rubric
from ..utils.text import norm
from .deps import (
    current_teacher,
    flash,
    get_db,
    owned_question,
    owned_subject,
    owned_topic,
    redirect,
    render,
    teacher_subjects,
    verify_csrf,
)

router = APIRouter(dependencies=[Depends(verify_csrf)])


# ---------------------------------------------------------------------------
# Môn học & chủ đề
# ---------------------------------------------------------------------------


@router.get("/subjects")
def list_subjects(request: Request, db: Session = Depends(get_db), teacher: Teacher = Depends(current_teacher)):
    subjects = teacher_subjects(db, teacher)
    counts = dict(
        db.execute(
            select(Question.topic_id, func.count(Question.id))
            .join(Subject, Question.subject_id == Subject.id)
            .where(Subject.teacher_id == teacher.id, Question.status != "archived")
            .group_by(Question.topic_id)
        ).all()
    )
    return render(
        request, "subjects/list.html", db=db, teacher=teacher, active="bank", subjects=subjects, counts=counts
    )


@router.post("/subjects")
def create_subject(
    request: Request,
    name: str = Form(...),
    description: str = Form(""),
    db: Session = Depends(get_db),
    teacher: Teacher = Depends(current_teacher),
):
    name = " ".join(name.split())
    if not name:
        flash(request, "Vui lòng nhập tên môn.", "danger")
        return redirect("/subjects")
    db.add(Subject(teacher_id=teacher.id, name=name[:120], description=description.strip()))
    db.commit()
    flash(request, f"Đã tạo môn {name}. Hãy thêm các chủ đề kiến thức.")
    return redirect("/subjects")


@router.post("/subjects/{subject_id}/topics")
def create_topic(
    request: Request,
    subject_id: int,
    name: str = Form(...),
    db: Session = Depends(get_db),
    teacher: Teacher = Depends(current_teacher),
):
    subject = owned_subject(db, teacher, subject_id)
    names = [" ".join(n.split()) for n in name.replace(";", "\n").split("\n")]
    names = [n for n in names if n]
    if not names:
        flash(request, "Vui lòng nhập tên chủ đề.", "danger")
        return redirect("/subjects")
    position = max((t.position for t in subject.topics), default=-1) + 1
    for n in names:
        db.add(Topic(subject_id=subject.id, name=n[:160], position=position))
        position += 1
    db.commit()
    flash(request, f"Đã thêm {len(names)} chủ đề vào môn {subject.name}.")
    return redirect("/subjects")


@router.post("/topics/{topic_id}/update")
def update_topic(
    request: Request,
    topic_id: int,
    name: str = Form(...),
    position: int = Form(0),
    db: Session = Depends(get_db),
    teacher: Teacher = Depends(current_teacher),
):
    topic = owned_topic(db, teacher, topic_id)
    if name.strip():
        topic.name = " ".join(name.split())[:160]
    topic.position = position
    db.commit()
    flash(request, "Đã cập nhật chủ đề.")
    return redirect("/subjects")


@router.post("/topics/{topic_id}/delete")
def delete_topic(
    request: Request, topic_id: int, db: Session = Depends(get_db), teacher: Teacher = Depends(current_teacher)
):
    topic = owned_topic(db, teacher, topic_id)
    if db.scalar(select(func.count(Question.id)).where(Question.topic_id == topic.id)):
        flash(request, "Chủ đề đã có câu hỏi nên không thể xóa (có thể đổi tên).", "danger")
        return redirect("/subjects")
    db.delete(topic)
    db.commit()
    flash(request, "Đã xóa chủ đề.", "warning")
    return redirect("/subjects")


# ---------------------------------------------------------------------------
# Ngân hàng câu hỏi
# ---------------------------------------------------------------------------


@router.get("/bank")
def bank(
    request: Request,
    subject_id: int | None = None,
    topic_id: int | None = None,
    level: int | None = None,
    status: str = "active",
    q: str = "",
    db: Session = Depends(get_db),
    teacher: Teacher = Depends(current_teacher),
):
    subjects = teacher_subjects(db, teacher)
    if not subjects:
        flash(request, "Hãy tạo môn học trước khi thêm câu hỏi.", "info")
        return redirect("/subjects")
    subject = next((s for s in subjects if s.id == subject_id), subjects[0])
    stmt = select(Question).where(Question.subject_id == subject.id)
    if topic_id:
        stmt = stmt.where(Question.topic_id == topic_id)
    if level:
        stmt = stmt.where(Question.level == level)
    if status in ("active", "draft", "archived"):
        stmt = stmt.where(Question.status == status)
    questions = list(db.scalars(stmt.order_by(Question.topic_id, Question.level, Question.id)).all())
    if q.strip():
        key = norm(q)
        questions = [x for x in questions if key in norm(x.content)]
    draft_count = db.scalar(
        select(func.count(Question.id)).where(Question.subject_id == subject.id, Question.status == "draft")
    )
    return render(
        request,
        "bank/list.html",
        db=db,
        teacher=teacher,
        active="bank",
        subjects=subjects,
        subject=subject,
        questions=questions,
        filters={"topic_id": topic_id, "level": level, "status": status, "q": q},
        draft_count=draft_count or 0,
    )


def _rubric_from_form(criteria: list[str], points: list[str], max_score: float) -> list[dict]:
    rows = []
    for c, p in zip(criteria, points, strict=False):
        if c.strip():
            try:
                value = float(str(p).replace(",", "."))
            except ValueError:
                value = 0.0
            rows.append({"criterion": c.strip(), "points": value})
    return normalize_rubric(rows, max_score)


@router.get("/bank/new")
def new_question(
    request: Request,
    subject_id: int,
    topic_id: int | None = None,
    db: Session = Depends(get_db),
    teacher: Teacher = Depends(current_teacher),
):
    subject = owned_subject(db, teacher, subject_id)
    if not subject.topics:
        flash(request, "Môn học chưa có chủ đề.", "warning")
        return redirect("/subjects")
    question = Question(
        subject_id=subject.id, topic_id=topic_id or subject.topics[0].id, level=2, max_score=2.0, rubric=[]
    )
    return render(
        request,
        "bank/form.html",
        db=db,
        teacher=teacher,
        active="bank",
        subject=subject,
        question=question,
        is_new=True,
    )


@router.post("/bank/new")
def create_question(
    request: Request,
    subject_id: int = Form(...),
    topic_id: int = Form(...),
    level: int = Form(2),
    max_score: float = Form(2.0),
    content: str = Form(...),
    reference_answer: str = Form(""),
    rubric_criterion: list[str] = Form([]),
    rubric_points: list[str] = Form([]),
    db: Session = Depends(get_db),
    teacher: Teacher = Depends(current_teacher),
):
    subject = owned_subject(db, teacher, subject_id)
    topic = owned_topic(db, teacher, topic_id)
    if topic.subject_id != subject.id or not content.strip():
        flash(request, "Dữ liệu câu hỏi không hợp lệ.", "danger")
        return redirect(f"/bank/new?subject_id={subject.id}")
    max_score = max(0.25, max_score)
    question = Question(
        subject_id=subject.id,
        topic_id=topic.id,
        level=level if level in LEVELS else 2,
        max_score=max_score,
        content=content.strip(),
        reference_answer=reference_answer.strip(),
        rubric=_rubric_from_form(rubric_criterion, rubric_points, max_score),
        source="bank",
        status="active",
    )
    db.add(question)
    db.commit()
    flash(request, "Đã thêm câu hỏi vào ngân hàng.")
    return redirect(f"/bank?subject_id={subject.id}&topic_id={topic.id}")


@router.get("/bank/{question_id}/edit")
def edit_question(
    request: Request, question_id: int, db: Session = Depends(get_db), teacher: Teacher = Depends(current_teacher)
):
    question = owned_question(db, teacher, question_id)
    usage = db.scalar(select(func.count(AssignmentItem.id)).where(AssignmentItem.question_id == question.id)) or 0
    return render(
        request,
        "bank/form.html",
        db=db,
        teacher=teacher,
        active="bank",
        subject=question.subject,
        question=question,
        is_new=False,
        usage=usage,
    )


@router.post("/bank/{question_id}/edit")
def save_question(
    request: Request,
    question_id: int,
    topic_id: int = Form(...),
    level: int = Form(2),
    max_score: float = Form(2.0),
    content: str = Form(...),
    reference_answer: str = Form(""),
    rubric_criterion: list[str] = Form([]),
    rubric_points: list[str] = Form([]),
    approve: str = Form(""),
    db: Session = Depends(get_db),
    teacher: Teacher = Depends(current_teacher),
):
    question = owned_question(db, teacher, question_id)
    topic = owned_topic(db, teacher, topic_id)
    if topic.subject_id != question.subject_id or not content.strip():
        flash(request, "Dữ liệu câu hỏi không hợp lệ.", "danger")
        return redirect(f"/bank/{question_id}/edit")
    max_score = max(0.25, max_score)
    question.topic_id = topic.id
    question.level = level if level in LEVELS else question.level
    question.max_score = max_score
    question.content = content.strip()
    question.reference_answer = reference_answer.strip()
    question.rubric = _rubric_from_form(rubric_criterion, rubric_points, max_score)
    if approve and question.status == "draft":
        question.status = "active"
    db.commit()
    flash(request, "Đã lưu câu hỏi." + (" Câu hỏi đã được duyệt vào ngân hàng." if approve else ""))
    return redirect(f"/bank?subject_id={question.subject_id}&topic_id={question.topic_id}&status={question.status}")


@router.post("/bank/{question_id}/status")
def set_status(
    request: Request,
    question_id: int,
    status: str = Form(...),
    db: Session = Depends(get_db),
    teacher: Teacher = Depends(current_teacher),
):
    question = owned_question(db, teacher, question_id)
    if status not in ("active", "archived"):
        flash(request, "Trạng thái không hợp lệ.", "danger")
    else:
        question.status = status
        db.commit()
        flash(
            request, "Đã duyệt câu hỏi." if status == "active" else "Đã lưu trữ câu hỏi (không dùng để giao bài nữa)."
        )
    return redirect(request.headers.get("referer") or f"/bank?subject_id={question.subject_id}")


@router.post("/bank/generate")
def generate(
    request: Request,
    topic_id: int = Form(...),
    level: int = Form(2),
    count: int = Form(3),
    instruction: str = Form(""),
    db: Session = Depends(get_db),
    teacher: Teacher = Depends(current_teacher),
):
    topic = owned_topic(db, teacher, topic_id)
    level = level if level in LEVELS else 2
    count = max(1, min(6, count))
    try:
        questions = generate_questions_for_topic(
            db, request.app.state.ai, topic.subject, topic, level, count, instruction.strip()
        )
        db.commit()
    except AIError as exc:
        db.rollback()
        flash(request, f"AI chưa soạn được câu hỏi: {exc}", "danger")
        return redirect(f"/bank?subject_id={topic.subject_id}")
    flash(
        request,
        f"AI đã soạn {len(questions)} câu hỏi mức {LEVELS[level]} (tối đa {DEFAULT_MAX_SCORE[level]:g} điểm). "
        "Hãy kiểm tra, sửa nếu cần rồi bấm Duyệt.",
    )
    return redirect(f"/bank?subject_id={topic.subject_id}&topic_id={topic.id}&status=draft")
