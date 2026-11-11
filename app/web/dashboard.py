"""Trang tổng quan, cài đặt và nạp dữ liệu mẫu."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import __version__
from ..models import Classroom, Student, Submission, SubmissionStatus, Teacher
from ..services.alerts import class_alerts
from ..services.assignments import batch_stats
from ..services.mastery import class_mastery, student_average, topic_average
from .deps import current_teacher, flash, get_db, redirect, render, teacher_classes, verify_csrf

router = APIRouter(dependencies=[Depends(verify_csrf)])


@router.get("/")
def home():
    return redirect("/dashboard")


@router.get("/dashboard")
def dashboard(
    request: Request,
    class_id: int | None = None,
    db: Session = Depends(get_db),
    teacher: Teacher = Depends(current_teacher),
):
    classes = teacher_classes(db, teacher)
    if not classes:
        return render(request, "dashboard.html", db=db, teacher=teacher, active="dashboard", classes=[])
    classroom = next((c for c in classes if c.id == class_id), classes[0])
    topics = list(classroom.subject.topics)
    table = class_mastery(db, classroom)
    rows = [
        {
            "student": s,
            "avg": student_average(table, s.id),
            "cells": [table.get(s.id, {}).get(t.id) for t in topics],
        }
        for s in classroom.students
    ]
    rows.sort(key=lambda r: (r["avg"] is None, r["avg"] or 0))
    topic_avgs = [topic_average(table, t.id) for t in topics]
    alerts = class_alerts(db, classroom, table)
    batches = [(b, batch_stats(b)) for b in classroom.batches[:5]]
    pending = (
        db.scalar(
            select(func.count(Submission.id))
            .join(Student, Submission.student_id == Student.id)
            .where(
                Student.classroom_id == classroom.id,
                Submission.status.in_([SubmissionStatus.AI_GRADED, SubmissionStatus.FAILED]),
            )
        )
        or 0
    )
    known = [r["avg"] for r in rows if r["avg"] is not None]
    kpi = {
        "students": len(classroom.students),
        "linked": sum(1 for s in classroom.students if s.is_linked),
        "pending": pending,
        "class_avg": round(sum(known) / len(known), 1) if known else None,
        "latest_done_pct": batches[0][1]["done_pct"] if batches else None,
        "alerts": sum(1 for a in alerts if a.severity in ("danger", "warning")),
    }
    return render(
        request,
        "dashboard.html",
        db=db,
        teacher=teacher,
        active="dashboard",
        classes=classes,
        classroom=classroom,
        topics=topics,
        rows=rows,
        topic_avgs=topic_avgs,
        alerts=alerts,
        batches=batches,
        kpi=kpi,
    )


@router.post("/onboarding/sample")
def load_sample(request: Request, db: Session = Depends(get_db), teacher: Teacher = Depends(current_teacher)):
    from ..seed import seed_sample_data

    classroom = seed_sample_data(db, teacher, request.app.state.settings, request.app.state.ai)
    db.commit()
    flash(
        request, f"Đã nạp dữ liệu mẫu: môn Tin học 10, ngân hàng câu hỏi và lớp «{classroom.name}» kèm lịch sử 3 tuần."
    )
    return redirect(f"/dashboard?class_id={classroom.id}")


@router.get("/settings")
def settings_page(request: Request, db: Session = Depends(get_db), teacher: Teacher = Depends(current_teacher)):
    settings = request.app.state.settings
    hub = request.app.state.hub
    telegram = hub.get("telegram")
    zalo = hub.get("zalo")
    total_students = (
        db.scalar(select(func.count(Student.id)).join(Classroom).where(Classroom.teacher_id == teacher.id)) or 0
    )
    return render(
        request,
        "settings.html",
        db=db,
        teacher=teacher,
        active="settings",
        settings=settings,
        ai=request.app.state.ai,
        telegram=telegram,
        zalo=zalo,
        version=__version__,
        total_students=total_students,
    )
