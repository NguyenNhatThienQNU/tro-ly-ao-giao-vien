"""Giao bài: tạo đợt giao bài cá nhân hóa, duyệt bộ đề nháp, theo dõi tiến độ nộp."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import AssignmentBatch, AssignmentStatus, Classroom, Question, Teacher
from ..services import assignments as service
from ..services.mastery import class_mastery
from ..utils.timeutil import parse_datetime
from .deps import (
    current_teacher,
    flash,
    get_db,
    owned_assignment,
    owned_batch,
    owned_classroom,
    owned_question,
    redirect,
    render,
    teacher_classes,
    verify_csrf,
)

router = APIRouter(dependencies=[Depends(verify_csrf)])


@router.get("/assignments")
def list_batches(
    request: Request,
    class_id: int | None = None,
    db: Session = Depends(get_db),
    teacher: Teacher = Depends(current_teacher),
):
    classes = teacher_classes(db, teacher)
    stmt = (
        select(AssignmentBatch)
        .join(Classroom, AssignmentBatch.classroom_id == Classroom.id)
        .where(Classroom.teacher_id == teacher.id)
        .order_by(AssignmentBatch.created_at.desc())
    )
    if class_id:
        stmt = stmt.where(Classroom.id == class_id)
    batches = [(b, service.batch_stats(b)) for b in db.scalars(stmt.limit(100)).all()]
    return render(
        request,
        "assignments/list.html",
        db=db,
        teacher=teacher,
        active="assignments",
        classes=classes,
        class_id=class_id,
        batches=batches,
    )


@router.get("/assignments/new")
def new_batch(
    request: Request,
    class_id: int | None = None,
    student_id: int | None = None,
    mode: str = "auto",
    db: Session = Depends(get_db),
    teacher: Teacher = Depends(current_teacher),
):
    classes = teacher_classes(db, teacher)
    if not classes:
        flash(request, "Hãy tạo lớp học trước khi giao bài.", "info")
        return redirect("/classes")
    classroom = next((c for c in classes if c.id == class_id), classes[0])
    table = class_mastery(db, classroom)
    return render(
        request,
        "assignments/new.html",
        db=db,
        teacher=teacher,
        active="assignments",
        classes=classes,
        classroom=classroom,
        table=table,
        selected_student=student_id,
        mode=mode if mode in service.TARGET_SUCCESS else "auto",
    )


@router.post("/assignments/new")
def create_batch(
    request: Request,
    class_id: int = Form(...),
    title: str = Form(""),
    due_at: str = Form(""),
    num_questions: int = Form(4),
    mode: str = Form("auto"),
    student_ids: list[int] = Form([]),
    topic_ids: list[int] = Form([]),
    instruction: str = Form(""),
    db: Session = Depends(get_db),
    teacher: Teacher = Depends(current_teacher),
):
    classroom = owned_classroom(db, teacher, class_id)
    try:
        due = parse_datetime(due_at) if due_at else None
    except ValueError:
        flash(request, "Hạn nộp không hợp lệ.", "danger")
        return redirect(f"/assignments/new?class_id={class_id}")
    try:
        result = service.create_batch(
            db,
            classroom,
            title=title,
            due_at=due,
            num_questions=num_questions,
            mode=mode,
            student_ids=student_ids or None,
            topic_ids=topic_ids or None,
            instruction=instruction,
            ai=request.app.state.ai,
        )
        db.commit()
    except service.AssignmentError as exc:
        db.rollback()
        flash(request, str(exc), "danger")
        return redirect(f"/assignments/new?class_id={class_id}")
    msg = f"Đã tạo {len(result.batch.assignments)} bộ đề nháp. Kiểm tra rồi bấm «Duyệt & gửi»."
    if result.generated:
        msg += f" AI đã soạn thêm {result.generated} câu mới."
    flash(request, msg)
    for warning in result.warnings:
        flash(request, warning, "warning")
    return redirect(f"/assignments/batches/{result.batch.id}")


@router.get("/assignments/batches/{batch_id}")
def batch_detail(
    request: Request, batch_id: int, db: Session = Depends(get_db), teacher: Teacher = Depends(current_teacher)
):
    batch = owned_batch(db, teacher, batch_id)
    classroom = batch.classroom
    table = class_mastery(db, classroom)
    bank = db.scalars(
        select(Question)
        .where(Question.subject_id == classroom.subject_id, Question.status.in_(["active", "draft"]))
        .order_by(Question.topic_id, Question.level, Question.id)
    ).all()
    return render(
        request,
        "assignments/batch.html",
        db=db,
        teacher=teacher,
        active="assignments",
        batch=batch,
        classroom=classroom,
        stats=service.batch_stats(batch),
        table=table,
        bank=bank,
        hub_channels=list(request.app.state.hub.adapters),
    )


@router.post("/assignments/batches/{batch_id}/approve")
def approve_batch(
    request: Request, batch_id: int, db: Session = Depends(get_db), teacher: Teacher = Depends(current_teacher)
):
    batch = owned_batch(db, teacher, batch_id)
    approved, skipped = service.approve_batch(db, batch)
    db.commit()
    msg = f"Đã duyệt {approved} bộ đề. Hệ thống sẽ gửi qua chatbot cho học sinh đã liên kết."
    flash(request, msg)
    if skipped:
        flash(request, f"Chưa duyệt (bộ đề trống): {', '.join(skipped)}.", "warning")
    return redirect(f"/assignments/batches/{batch_id}")


@router.post("/assignments/batches/{batch_id}/due")
def update_due(
    request: Request,
    batch_id: int,
    due_at: str = Form(""),
    db: Session = Depends(get_db),
    teacher: Teacher = Depends(current_teacher),
):
    batch = owned_batch(db, teacher, batch_id)
    try:
        service.update_batch_due(db, batch, parse_datetime(due_at) if due_at else None)
        db.commit()
        flash(request, "Đã cập nhật hạn nộp.")
    except ValueError:
        flash(request, "Hạn nộp không hợp lệ.", "danger")
    return redirect(f"/assignments/batches/{batch_id}")


@router.post("/assignments/batches/{batch_id}/delete")
def delete_batch(
    request: Request, batch_id: int, db: Session = Depends(get_db), teacher: Teacher = Depends(current_teacher)
):
    batch = owned_batch(db, teacher, batch_id)
    if any(a.status != AssignmentStatus.DRAFT for a in batch.assignments):
        flash(request, "Đợt giao bài đã có bộ đề được gửi, chỉ có thể hủy từng bộ đề.", "danger")
        return redirect(f"/assignments/batches/{batch_id}")
    db.delete(batch)
    db.commit()
    flash(request, "Đã xóa đợt giao bài nháp.", "warning")
    return redirect("/assignments")


def _back(assignment) -> str:
    return f"/assignments/batches/{assignment.batch_id}#a{assignment.id}" if assignment.batch_id else "/assignments"


@router.post("/assignments/{assignment_id}/approve")
def approve_one(
    request: Request, assignment_id: int, db: Session = Depends(get_db), teacher: Teacher = Depends(current_teacher)
):
    assignment = owned_assignment(db, teacher, assignment_id)
    try:
        service.approve_assignment(db, assignment)
        db.commit()
        flash(request, f"Đã duyệt bộ đề của {assignment.student.full_name}.")
    except service.AssignmentError as exc:
        db.rollback()
        flash(request, str(exc), "danger")
    return redirect(_back(assignment))


@router.post("/assignments/{assignment_id}/cancel")
def cancel_one(
    request: Request, assignment_id: int, db: Session = Depends(get_db), teacher: Teacher = Depends(current_teacher)
):
    assignment = owned_assignment(db, teacher, assignment_id)
    try:
        service.cancel_assignment(db, assignment)
        db.commit()
        flash(request, f"Đã hủy bộ đề của {assignment.student.full_name}.", "warning")
    except service.AssignmentError as exc:
        db.rollback()
        flash(request, str(exc), "danger")
    return redirect(_back(assignment))


@router.post("/assignments/{assignment_id}/note")
def save_note(
    request: Request,
    assignment_id: int,
    note: str = Form(""),
    db: Session = Depends(get_db),
    teacher: Teacher = Depends(current_teacher),
):
    assignment = owned_assignment(db, teacher, assignment_id)
    assignment.note = note.strip()[:1000]
    db.commit()
    flash(request, "Đã lưu lời nhắn cho học sinh.")
    return redirect(_back(assignment))


@router.post("/assignments/{assignment_id}/items/{item_id}/remove")
def remove_item(
    request: Request,
    assignment_id: int,
    item_id: int,
    db: Session = Depends(get_db),
    teacher: Teacher = Depends(current_teacher),
):
    assignment = owned_assignment(db, teacher, assignment_id)
    try:
        service.remove_item(db, assignment, item_id)
        db.commit()
    except service.AssignmentError as exc:
        db.rollback()
        flash(request, str(exc), "danger")
    return redirect(_back(assignment))


@router.post("/assignments/{assignment_id}/items/add")
def add_item(
    request: Request,
    assignment_id: int,
    question_id: int = Form(...),
    db: Session = Depends(get_db),
    teacher: Teacher = Depends(current_teacher),
):
    assignment = owned_assignment(db, teacher, assignment_id)
    question = owned_question(db, teacher, question_id)
    try:
        service.add_item(db, assignment, question)
        db.commit()
    except service.AssignmentError as exc:
        db.rollback()
        flash(request, str(exc), "danger")
    return redirect(_back(assignment))
