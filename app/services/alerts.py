"""Cảnh báo sớm cho giáo viên: tụt điểm, hổng kiến thức, quá hạn, chưa liên kết chatbot."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from statistics import mean

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Assignment, AssignmentStatus, Classroom, Submission, SubmissionStatus
from ..utils.timeutil import utcnow
from .mastery import MasteryTable, Residual, collect_observations, compute_mastery

DROP_GAP = 0.2  # 2 bài gần nhất kém hơn các bài trước ≥ 20 điểm % (so với kỳ vọng)
DROP_RECENT_MAX = -0.1  # và thực sự thấp hơn kỳ vọng ≥ 10 điểm %
WEAK_THRESHOLD = 45.0
WEAK_MIN_OBSERVATIONS = 2
SEVERITY_ORDER = {"danger": 0, "warning": 1, "info": 2}


@dataclass
class Alert:
    kind: str  # drop | weak | overdue | unlinked
    severity: str  # danger | warning | info
    student_id: int | None
    student_name: str
    message: str

    @property
    def icon(self) -> str:
        return {"drop": "graph-down-arrow", "weak": "exclamation-triangle", "overdue": "clock-history"}.get(
            self.kind, "info-circle"
        )


def submission_series(db: Session, student_ids: list[int]) -> dict[int, list[tuple[datetime, float]]]:
    """Tỉ lệ điểm (%) các bài đã xác nhận của từng học sinh, theo thời gian nộp."""
    if not student_ids:
        return {}
    rows = db.execute(
        select(Submission.student_id, Submission.submitted_at, Submission.final_total, Submission.max_total)
        .where(
            Submission.student_id.in_(student_ids),
            Submission.status == SubmissionStatus.CONFIRMED,
            Submission.final_total.is_not(None),
        )
        .order_by(Submission.submitted_at)
    ).all()
    series: dict[int, list[tuple[datetime, float]]] = defaultdict(list)
    for sid, at, total, max_total in rows:
        if max_total:
            series[sid].append((at, 100.0 * total / max_total))
    return series


def submission_residuals(residuals: list[Residual]) -> dict[int, list[float]]:
    """Gom chênh lệch (thực tế − kỳ vọng) theo từng bài nộp, theo thứ tự thời gian, cho mỗi học sinh."""
    grouped: dict[int, dict[int | None, list[float]]] = defaultdict(dict)
    for r in sorted(residuals, key=lambda r: r.at):
        grouped[r.student_id].setdefault(r.submission_id, []).append(r.value)
    return {sid: [mean(values) for values in subs.values()] for sid, subs in grouped.items()}


def detect_drop(per_submission: list[float]) -> bool:
    """Tụt điểm = 2 bài gần nhất kém hơn hẳn kỳ vọng so với các bài trước.

    Dùng chênh lệch so với kỳ vọng của mô hình Elo (đã tính đến độ khó của câu hỏi),
    nên không báo nhầm khi điểm thô giảm chỉ vì hệ thống giao câu khó hơn.
    """
    if len(per_submission) < 3:
        return False
    recent = mean(per_submission[-2:])
    before = mean(per_submission[-5:-2])
    return before - recent >= DROP_GAP and recent <= DROP_RECENT_MAX


def class_alerts(db: Session, classroom: Classroom, table: MasteryTable, now: datetime | None = None) -> list[Alert]:
    now = now or utcnow()
    students = list(classroom.students)
    topics = list(classroom.subject.topics)
    alerts: list[Alert] = []
    student_ids = [s.id for s in students]
    series = submission_series(db, student_ids)
    residuals: list[Residual] = []
    compute_mastery(collect_observations(db, student_ids, [t.id for t in topics]), residuals)
    per_submission = submission_residuals(residuals)

    for student in students:
        if detect_drop(per_submission.get(student.id, [])):
            raw = [pct for _, pct in series.get(student.id, [])]
            detail = ""
            if len(raw) >= 3:
                detail = f" (trung bình {mean(raw[-5:-2]):.0f}% → {mean(raw[-2:]):.0f}%)"
            alerts.append(
                Alert(
                    "drop",
                    "danger",
                    student.id,
                    student.full_name,
                    f"Điểm giảm bất thường ở 2 bài gần nhất{detail}, thấp hơn hẳn năng lực em đã thể hiện.",
                )
            )
        weak = []
        for topic in topics:
            state = table.get(student.id, {}).get(topic.id)
            if state and state.n >= WEAK_MIN_OBSERVATIONS and state.pct < WEAK_THRESHOLD:
                weak.append(f"{topic.name} ({state.pct:.0f}%)")
        if weak:
            alerts.append(
                Alert("weak", "warning", student.id, student.full_name, "Hổng kiến thức: " + "; ".join(weak) + ".")
            )

    overdue_rows = db.scalars(
        select(Assignment).where(
            Assignment.classroom_id == classroom.id,
            Assignment.status == AssignmentStatus.ASSIGNED,
            Assignment.due_at.is_not(None),
            Assignment.due_at < now,
        )
    ).all()
    overdue_by_student: dict[int, list[Assignment]] = defaultdict(list)
    for a in overdue_rows:
        overdue_by_student[a.student_id].append(a)
    for items in overdue_by_student.values():
        student = items[0].student
        titles = ", ".join(f"«{a.title}»" for a in items[:3])
        alerts.append(Alert("overdue", "warning", student.id, student.full_name, f"Quá hạn chưa nộp: {titles}."))

    unlinked = [s for s in students if not s.is_linked]
    if unlinked:
        names = ", ".join(s.full_name for s in unlinked[:5])
        more = f" và {len(unlinked) - 5} em khác" if len(unlinked) > 5 else ""
        alerts.append(
            Alert(
                "unlinked",
                "info",
                None,
                "",
                f"{len(unlinked)} học sinh chưa liên kết chatbot: {names}{more}. In phiếu QR để các em quét.",
            )
        )
    alerts.sort(key=lambda a: (SEVERITY_ORDER.get(a.severity, 9), a.student_name))
    return alerts
