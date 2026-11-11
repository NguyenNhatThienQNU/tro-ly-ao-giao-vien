"""Quản lý lớp học, học sinh, phiếu QR liên kết chatbot, nhập dữ liệu từ Excel."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Classroom, ScoreRecord, Subject, Submission, SubmissionStatus, Teacher
from ..services import importer
from ..services.alerts import submission_series
from ..services.mastery import class_mastery, mastery_for_students, student_average
from ..services.qr import qr_svg
from ..services.students import add_student, reset_link
from .deps import (
    current_teacher,
    flash,
    get_db,
    owned_classroom,
    owned_student,
    owned_subject,
    redirect,
    render,
    teacher_classes,
    teacher_subjects,
    verify_csrf,
)

router = APIRouter(dependencies=[Depends(verify_csrf)])
MAX_UPLOAD = 5 * 1024 * 1024


@router.get("/classes")
def list_classes(request: Request, db: Session = Depends(get_db), teacher: Teacher = Depends(current_teacher)):
    classes = teacher_classes(db, teacher)
    return render(
        request,
        "classes/list.html",
        db=db,
        teacher=teacher,
        active="classes",
        classes=classes,
        subjects=teacher_subjects(db, teacher),
    )


@router.post("/classes")
def create_class(
    request: Request,
    name: str = Form(...),
    school_year: str = Form(""),
    subject_id: int | None = Form(None),
    new_subject: str = Form(""),
    db: Session = Depends(get_db),
    teacher: Teacher = Depends(current_teacher),
):
    name = " ".join(name.split())
    if not name:
        flash(request, "Vui lòng nhập tên lớp.", "danger")
        return redirect("/classes")
    if new_subject.strip():
        subject = Subject(teacher_id=teacher.id, name=" ".join(new_subject.split())[:120])
        db.add(subject)
        db.flush()
    elif subject_id:
        subject = owned_subject(db, teacher, subject_id)
    else:
        flash(request, "Hãy chọn môn học hoặc nhập tên môn mới.", "danger")
        return redirect("/classes")
    classroom = Classroom(teacher_id=teacher.id, subject_id=subject.id, name=name[:80], school_year=school_year.strip())
    db.add(classroom)
    db.commit()
    flash(request, f"Đã tạo lớp {classroom.name}. Thêm học sinh hoặc nhập danh sách từ Excel.")
    return redirect(f"/classes/{classroom.id}")


@router.get("/classes/{class_id}")
def class_detail(
    request: Request, class_id: int, db: Session = Depends(get_db), teacher: Teacher = Depends(current_teacher)
):
    classroom = owned_classroom(db, teacher, class_id)
    table = class_mastery(db, classroom)
    averages = {s.id: student_average(table, s.id) for s in classroom.students}
    return render(
        request,
        "classes/detail.html",
        db=db,
        teacher=teacher,
        active="classes",
        classroom=classroom,
        averages=averages,
        channels=list(request.app.state.hub.adapters),
    )


@router.post("/classes/{class_id}/update")
def update_class(
    request: Request,
    class_id: int,
    name: str = Form(...),
    school_year: str = Form(""),
    db: Session = Depends(get_db),
    teacher: Teacher = Depends(current_teacher),
):
    classroom = owned_classroom(db, teacher, class_id)
    if name.strip():
        classroom.name = " ".join(name.split())[:80]
    classroom.school_year = school_year.strip()[:20]
    db.commit()
    flash(request, "Đã cập nhật thông tin lớp.")
    return redirect(f"/classes/{class_id}")


@router.post("/classes/{class_id}/delete")
def delete_class(
    request: Request, class_id: int, db: Session = Depends(get_db), teacher: Teacher = Depends(current_teacher)
):
    classroom = owned_classroom(db, teacher, class_id)
    name = classroom.name
    db.delete(classroom)
    db.commit()
    flash(request, f"Đã xóa lớp {name} cùng toàn bộ dữ liệu của lớp.", "warning")
    return redirect("/classes")


@router.post("/classes/{class_id}/students")
def create_student(
    request: Request,
    class_id: int,
    full_name: str = Form(...),
    student_code: str = Form(""),
    db: Session = Depends(get_db),
    teacher: Teacher = Depends(current_teacher),
):
    classroom = owned_classroom(db, teacher, class_id)
    try:
        student = add_student(db, classroom, full_name, student_code)
    except ValueError as exc:
        flash(request, str(exc), "danger")
        return redirect(f"/classes/{class_id}")
    db.commit()
    flash(request, f"Đã thêm {student.full_name} (mã liên kết {student.link_code}).")
    return redirect(f"/classes/{class_id}")


async def _read_upload(file: UploadFile) -> bytes:
    data = await file.read(MAX_UPLOAD + 1)
    if len(data) > MAX_UPLOAD:
        raise importer.ImportFormatError("Tệp quá lớn (tối đa 5 MB).")
    return data


@router.post("/classes/{class_id}/import-students")
async def import_students(
    request: Request,
    class_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    teacher: Teacher = Depends(current_teacher),
):
    classroom = owned_classroom(db, teacher, class_id)
    try:
        table = importer.parse_table(await _read_upload(file), file.filename or "")
        report = importer.import_students(db, classroom, table)
        db.commit()
    except importer.ImportFormatError as exc:
        db.rollback()
        flash(request, f"Không nhập được: {exc}", "danger")
        return redirect(f"/classes/{class_id}")
    flash(request, f"Đã thêm {report.created} học sinh, bỏ qua {report.skipped} dòng trùng/trống.")
    return redirect(f"/classes/{class_id}")


@router.post("/classes/{class_id}/import-scores")
async def import_scores(
    request: Request,
    class_id: int,
    label: str = Form("Bảng điểm"),
    max_score: float = Form(10.0),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    teacher: Teacher = Depends(current_teacher),
):
    classroom = owned_classroom(db, teacher, class_id)
    try:
        table = importer.parse_table(await _read_upload(file), file.filename or "", list(classroom.subject.topics))
        if not any(v == "score" or v.startswith("topic:") for v in table.mapping.values()):
            raise importer.ImportFormatError("Không thấy cột 'Điểm' hoặc cột trùng tên chủ đề.")
        report = importer.import_scores(db, classroom, table, label.strip() or "Bảng điểm", max_score or 10.0)
        db.commit()
    except importer.ImportFormatError as exc:
        db.rollback()
        flash(request, f"Không nhập được: {exc}", "danger")
        return redirect(f"/classes/{class_id}")
    message = f"Đã lưu {report.records} đầu điểm."
    if report.unmatched:
        message += f" Không khớp tên: {', '.join(report.unmatched[:8])}."
    if report.ambiguous:
        message += f" Trùng tên cần kiểm tra: {', '.join(report.ambiguous[:8])}."
    flash(request, message, "warning" if report.unmatched or report.ambiguous else "success")
    return redirect(f"/classes/{class_id}")


@router.get("/classes/{class_id}/qr")
def print_qr(
    request: Request, class_id: int, db: Session = Depends(get_db), teacher: Teacher = Depends(current_teacher)
):
    classroom = owned_classroom(db, teacher, class_id)
    hub = request.app.state.hub
    telegram = hub.get("telegram")
    zalo = hub.get("zalo")
    cards = []
    for s in classroom.students:
        url = telegram.link_url(s.link_code) if telegram else None
        cards.append(
            {
                "student": s,
                "telegram_url": url,
                "qr": qr_svg(url, scale=4) if url else None,
            }
        )
    zalo_link = zalo.link_url("") if zalo else None
    return render(
        request,
        "classes/qr.html",
        db=db,
        teacher=teacher,
        classroom=classroom,
        cards=cards,
        telegram=telegram,
        zalo_link=zalo_link,
        zalo_qr=qr_svg(zalo_link, scale=3) if zalo_link else None,
    )


@router.get("/students/{student_id}")
def student_detail(
    request: Request, student_id: int, db: Session = Depends(get_db), teacher: Teacher = Depends(current_teacher)
):
    student = owned_student(db, teacher, student_id)
    topics = list(student.classroom.subject.topics)
    table = mastery_for_students(db, [student], [t.id for t in topics])
    states = table.get(student.id, {})
    series = submission_series(db, [student.id]).get(student.id, [])
    submissions = db.scalars(
        select(Submission)
        .where(Submission.student_id == student.id, Submission.status != SubmissionStatus.COLLECTING)
        .order_by(Submission.created_at.desc())
    ).all()
    records = db.scalars(
        select(ScoreRecord).where(ScoreRecord.student_id == student.id).order_by(ScoreRecord.recorded_at.desc())
    ).all()
    assignments = sorted(student.assignments, key=lambda a: a.created_at, reverse=True)[:10]
    chart = {
        "topics": [t.name for t in topics],
        "mastery": [states[t.id].pct if t.id in states and states[t.id].has_data else None for t in topics],
        "trend_labels": [f"{at:%d/%m}" for at, _ in series],
        "trend_values": [round(v, 1) for _, v in series],
    }
    hub = request.app.state.hub
    telegram = hub.get("telegram")
    link_url = telegram.link_url(student.link_code) if telegram else None
    return render(
        request,
        "students/detail.html",
        db=db,
        teacher=teacher,
        active="classes",
        student=student,
        topics=topics,
        states=states,
        avg=student_average(table, student.id),
        submissions=submissions,
        records=records,
        assignments=assignments,
        chart=chart,
        link_qr=qr_svg(link_url, scale=3) if link_url else None,
    )


@router.post("/students/{student_id}/update")
def update_student(
    request: Request,
    student_id: int,
    full_name: str = Form(...),
    student_code: str = Form(""),
    note: str = Form(""),
    db: Session = Depends(get_db),
    teacher: Teacher = Depends(current_teacher),
):
    student = owned_student(db, teacher, student_id)
    if full_name.strip():
        student.full_name = " ".join(full_name.split())[:120]
    student.student_code = student_code.strip()[:40]
    student.note = note.strip()[:1000]
    db.commit()
    flash(request, "Đã lưu thông tin học sinh.")
    return redirect(f"/students/{student_id}")


@router.post("/students/{student_id}/reset-link")
def reset_student_link(
    request: Request, student_id: int, db: Session = Depends(get_db), teacher: Teacher = Depends(current_teacher)
):
    student = owned_student(db, teacher, student_id)
    reset_link(db, student)
    db.commit()
    flash(request, f"Đã hủy liên kết cũ và cấp mã mới {student.link_code} cho {student.full_name}.")
    return redirect(request.headers.get("referer") or f"/students/{student_id}")


@router.post("/students/{student_id}/delete")
def delete_student(
    request: Request, student_id: int, db: Session = Depends(get_db), teacher: Teacher = Depends(current_teacher)
):
    student = owned_student(db, teacher, student_id)
    class_id = student.classroom_id
    db.delete(student)
    db.commit()
    flash(request, "Đã xóa học sinh.", "warning")
    return redirect(f"/classes/{class_id}")
