"""Chấm bài: hàng đợi bài nộp, xem ảnh + kết quả AI, giáo viên xác nhận/sửa điểm."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Classroom, Student, Submission, SubmissionImage, SubmissionStatus, Teacher
from ..services import grading as service
from ..services.storage import InvalidUpload, resolve_upload
from .deps import (
    current_teacher,
    flash,
    get_db,
    owned_submission,
    redirect,
    render,
    teacher_classes,
    verify_csrf,
)

router = APIRouter(dependencies=[Depends(verify_csrf)])

STATUS_FILTERS = {
    "pending": [SubmissionStatus.AI_GRADED, SubmissionStatus.FAILED],
    "processing": [SubmissionStatus.SUBMITTED, SubmissionStatus.GRADING],
    "confirmed": [SubmissionStatus.CONFIRMED],
    "returned": [SubmissionStatus.RETURNED],
    "all": [
        SubmissionStatus.SUBMITTED,
        SubmissionStatus.GRADING,
        SubmissionStatus.AI_GRADED,
        SubmissionStatus.FAILED,
        SubmissionStatus.CONFIRMED,
        SubmissionStatus.RETURNED,
    ],
}


@router.get("/grading")
def queue(
    request: Request,
    status: str = "pending",
    class_id: int | None = None,
    db: Session = Depends(get_db),
    teacher: Teacher = Depends(current_teacher),
):
    statuses = STATUS_FILTERS.get(status, STATUS_FILTERS["pending"])
    stmt = (
        select(Submission)
        .join(Student, Submission.student_id == Student.id)
        .join(Classroom, Student.classroom_id == Classroom.id)
        .where(Classroom.teacher_id == teacher.id, Submission.status.in_(statuses))
    )
    if class_id:
        stmt = stmt.where(Classroom.id == class_id)
    order = Submission.confirmed_at.desc() if status == "confirmed" else Submission.submitted_at
    submissions = db.scalars(stmt.order_by(order).limit(200)).all()
    settings = request.app.state.settings
    return render(
        request,
        "grading/list.html",
        db=db,
        teacher=teacher,
        active="grading",
        submissions=submissions,
        status=status,
        class_id=class_id,
        classes=teacher_classes(db, teacher),
        attention={s.id: service.needs_attention(s, settings) for s in submissions},
    )


@router.get("/grading/{submission_id}")
def detail(
    request: Request, submission_id: int, db: Session = Depends(get_db), teacher: Teacher = Depends(current_teacher)
):
    sub = owned_submission(db, teacher, submission_id)
    if sub.status == SubmissionStatus.FAILED and not sub.grades:
        service.init_manual_grades(db, sub)
        db.commit()
    settings = request.app.state.settings
    next_id = db.scalar(
        select(Submission.id)
        .join(Student, Submission.student_id == Student.id)
        .join(Classroom, Student.classroom_id == Classroom.id)
        .where(
            Classroom.teacher_id == teacher.id,
            Submission.status.in_([SubmissionStatus.AI_GRADED, SubmissionStatus.FAILED]),
            Submission.id != sub.id,
        )
        .order_by(Submission.submitted_at)
    )
    return render(
        request,
        "grading/detail.html",
        db=db,
        teacher=teacher,
        active="grading",
        sub=sub,
        items={item.id: item for item in (sub.assignment.items if sub.assignment else [])},
        attention=service.needs_attention(sub, settings),
        threshold=settings.low_confidence_threshold,
        next_id=next_id,
    )


@router.post("/grading/{submission_id}/confirm")
async def confirm(
    request: Request, submission_id: int, db: Session = Depends(get_db), teacher: Teacher = Depends(current_teacher)
):
    sub = owned_submission(db, teacher, submission_id)
    form = await request.form()
    scores: dict[int, float | None] = {}
    comments: dict[int, str] = {}
    for grade in sub.grades:
        raw = str(form.get(f"score_{grade.id}", "")).strip().replace(",", ".")
        if raw:
            try:
                scores[grade.id] = float(raw)
            except ValueError:
                flash(request, f"Điểm câu {grade.position} không hợp lệ.", "danger")
                return redirect(f"/grading/{submission_id}")
        if f"comment_{grade.id}" in form:
            comments[grade.id] = str(form.get(f"comment_{grade.id}", ""))
    try:
        service.confirm_submission(db, sub, scores, comments, str(form.get("teacher_comment", "")))
        db.commit()
    except service.GradingError as exc:
        db.rollback()
        flash(request, str(exc), "danger")
        return redirect(f"/grading/{submission_id}")
    flash(request, f"Đã xác nhận điểm cho {sub.student.full_name}. Kết quả sẽ được gửi qua chatbot.")
    if form.get("next_id"):
        return redirect(f"/grading/{form.get('next_id')}")
    return redirect("/grading")


@router.post("/grading/{submission_id}/regrade")
def regrade(
    request: Request, submission_id: int, db: Session = Depends(get_db), teacher: Teacher = Depends(current_teacher)
):
    sub = owned_submission(db, teacher, submission_id)
    try:
        service.request_regrade(db, sub)
        db.commit()
        flash(request, "Đã đưa bài vào hàng đợi để AI chấm lại.")
    except service.GradingError as exc:
        db.rollback()
        flash(request, str(exc), "danger")
    return redirect(f"/grading/{submission_id}")


@router.post("/grading/{submission_id}/return")
def return_submission(
    request: Request,
    submission_id: int,
    reason: str = Form(""),
    db: Session = Depends(get_db),
    teacher: Teacher = Depends(current_teacher),
):
    sub = owned_submission(db, teacher, submission_id)
    try:
        service.return_submission(db, sub, reason)
        db.commit()
        flash(request, f"Đã yêu cầu {sub.student.full_name} nộp lại.", "warning")
    except service.GradingError as exc:
        db.rollback()
        flash(request, str(exc), "danger")
    return redirect("/grading")


@router.get("/media/images/{image_id}")
def image(request: Request, image_id: int, db: Session = Depends(get_db), teacher: Teacher = Depends(current_teacher)):
    img = db.get(SubmissionImage, image_id)
    if img is None or img.submission.student.classroom.teacher_id != teacher.id:
        raise HTTPException(status_code=404)
    try:
        path = resolve_upload(request.app.state.settings, img.file_path)
    except InvalidUpload as exc:
        raise HTTPException(status_code=404) from exc
    if not path.exists():
        raise HTTPException(status_code=404)
    return FileResponse(path, media_type=img.mime_type, headers={"Cache-Control": "private, max-age=3600"})
