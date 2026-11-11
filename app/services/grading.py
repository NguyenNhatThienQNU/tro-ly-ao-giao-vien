"""Chấm bài qua ảnh: gọi AI, chuẩn hóa kết quả, giáo viên xác nhận/sửa điểm."""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from ..ai.base import AIError, AIProvider
from ..ai.schemas import CriterionResult, GradingQuestion, GradingRequest, GradingResult, ImageInput, RubricItem
from ..config import Settings
from ..models import AssignmentStatus, ItemGrade, Submission, SubmissionStatus
from ..utils.text import norm, round_quarter
from ..utils.timeutil import utcnow
from .storage import resolve_upload

log = logging.getLogger(__name__)


class GradingError(ValueError):
    pass


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def build_request(settings: Settings, sub: Submission) -> GradingRequest:
    assignment = sub.assignment
    if assignment is None:
        raise GradingError("Bài nộp chưa gắn với bộ đề.")
    if not sub.images:
        raise GradingError("Bài nộp không có ảnh.")
    questions = [
        GradingQuestion(
            number=pos,
            content=item.question.content,
            max_score=item.question.max_score,
            level_name=item.question.level_name,
            rubric=[RubricItem(r["criterion"], float(r["points"])) for r in item.question.rubric or []],
            reference_answer=item.question.reference_answer or "",
        )
        for pos, item in enumerate(assignment.items, start=1)
    ]
    images = [
        ImageInput(data=resolve_upload(settings, img.file_path).read_bytes(), mime_type=img.mime_type)
        for img in sub.images
    ]
    return GradingRequest(subject_name=assignment.student.classroom.subject.name, questions=questions, images=images)


def normalize_criteria(ai_criteria: list[CriterionResult], rubric: list[dict]) -> list[dict]:
    """Ghép điểm AI vào rubric gốc (rubric trong CSDL là chuẩn), chặn điểm vượt mức."""
    if not rubric:
        return [
            {
                "criterion": c.criterion,
                "max_points": max(0.0, c.max_points),
                "awarded": _clamp(round_quarter(c.awarded), 0.0, max(0.0, c.max_points)),
                "comment": c.comment.strip(),
            }
            for c in ai_criteria
        ]
    by_name = {norm(c.criterion): c for c in ai_criteria}
    result = []
    for i, r in enumerate(rubric):
        points = float(r["points"])
        match = by_name.get(norm(r["criterion"])) or (ai_criteria[i] if i < len(ai_criteria) else None)
        awarded = _clamp(round_quarter(match.awarded), 0.0, points) if match else 0.0
        result.append(
            {
                "criterion": r["criterion"],
                "max_points": points,
                "awarded": awarded,
                "comment": match.comment.strip() if match else "",
            }
        )
    return result


def apply_result(db: Session, sub: Submission, result: GradingResult) -> None:
    assignment = sub.assignment
    by_number = {q.question_number: q for q in result.questions}
    for old in list(sub.grades):
        sub.grades.remove(old)
    db.flush()

    total = max_total = 0.0
    for pos, item in enumerate(assignment.items, start=1):
        question = item.question
        qr = by_number.get(pos)
        grade = ItemGrade(
            assignment_item_id=item.id,
            question_id=question.id,
            position=pos,
            max_score=question.max_score,
        )
        if qr is None:
            grade.found = False
            grade.ai_score = 0.0
            grade.ai_comment = "AI không tìm thấy bài làm cho câu này trong ảnh."
            grade.confidence = 0.3
        else:
            criteria = normalize_criteria(qr.criteria, question.rubric or [])
            score = sum(c["awarded"] for c in criteria) if criteria else qr.score
            score = _clamp(round_quarter(score), 0.0, question.max_score)
            grade.found = qr.found
            grade.transcription = qr.transcription.strip()
            grade.criteria = criteria
            grade.ai_score = score
            grade.ai_comment = qr.comment.strip()
            grade.errors = [e.model_dump() for e in qr.errors]
            grade.confidence = _clamp(qr.confidence, 0.0, 1.0)
        sub.grades.append(grade)
        total += grade.ai_score or 0.0
        max_total += question.max_score

    sub.ai_total = round(total, 2)
    sub.max_total = max_total
    sub.ai_summary = result.overall_feedback.strip()
    sub.ai_image_quality = result.image_quality.strip()[:30]
    sub.status = SubmissionStatus.AI_GRADED
    sub.graded_at = utcnow()
    sub.error_message = ""
    db.flush()


def grade_submission(db: Session, sub: Submission, ai: AIProvider, settings: Settings) -> bool:
    """Chấm một bài. Trả về True nếu thành công. Lỗi thì tăng số lần thử."""
    try:
        request = build_request(settings, sub)
        result = ai.grade(request)
        apply_result(db, sub, result)
        return True
    except (AIError, GradingError, OSError, ValueError) as exc:
        log.warning("Chấm bài #%s lỗi: %s", sub.id, exc)
        sub.attempts += 1
        sub.error_message = str(exc)[:1000]
        sub.status = (
            SubmissionStatus.FAILED if sub.attempts >= settings.max_grading_attempts else SubmissionStatus.SUBMITTED
        )
        db.flush()
        return False


def init_manual_grades(db: Session, sub: Submission) -> None:
    """Tạo khung điểm trống để giáo viên chấm tay (khi AI lỗi)."""
    if sub.grades or sub.assignment is None:
        return
    for pos, item in enumerate(sub.assignment.items, start=1):
        sub.grades.append(
            ItemGrade(
                assignment_item_id=item.id,
                question_id=item.question_id,
                position=pos,
                max_score=item.question.max_score,
            )
        )
    sub.max_total = sum(item.question.max_score for item in sub.assignment.items)
    db.flush()


def confirm_submission(
    db: Session,
    sub: Submission,
    scores: dict[int, float | None],
    item_comments: dict[int, str] | None = None,
    teacher_comment: str = "",
) -> None:
    """Giáo viên chốt điểm. Chỉ sau bước này điểm mới tính vào mức nắm vững và gửi học sinh."""
    if sub.status not in (SubmissionStatus.AI_GRADED, SubmissionStatus.FAILED, SubmissionStatus.CONFIRMED):
        raise GradingError("Bài này chưa sẵn sàng để xác nhận.")
    init_manual_grades(db, sub)
    item_comments = item_comments or {}
    total = 0.0
    for grade in sub.grades:
        value = scores.get(grade.id)
        if value is None:
            value = grade.ai_score
        if value is None:
            raise GradingError(f"Chưa nhập điểm câu {grade.position}.")
        grade.final_score = _clamp(round_quarter(float(value)), 0.0, grade.max_score)
        if grade.id in item_comments:
            grade.teacher_comment = item_comments[grade.id].strip()
        total += grade.final_score
    sub.final_total = round(total, 2)
    sub.max_total = sum(g.max_score for g in sub.grades)
    sub.teacher_comment = (teacher_comment or "").strip()
    sub.status = SubmissionStatus.CONFIRMED
    sub.confirmed_at = utcnow()
    sub.result_sent_at = None  # (gửi lại nếu giáo viên sửa điểm sau khi đã gửi)
    if sub.assignment is not None:
        sub.assignment.status = AssignmentStatus.GRADED
    db.flush()


def request_regrade(db: Session, sub: Submission) -> None:
    if sub.status not in (SubmissionStatus.AI_GRADED, SubmissionStatus.FAILED):
        raise GradingError("Chỉ chấm lại được bài đang chờ xác nhận hoặc bị lỗi.")
    for old in list(sub.grades):
        sub.grades.remove(old)
    sub.status = SubmissionStatus.SUBMITTED
    sub.attempts = 0
    sub.error_message = ""
    db.flush()


def return_submission(db: Session, sub: Submission, reason: str) -> None:
    """Trả bài, yêu cầu học sinh chụp/nộp lại (vd ảnh mờ, thiếu trang)."""
    if sub.status not in (SubmissionStatus.AI_GRADED, SubmissionStatus.FAILED, SubmissionStatus.SUBMITTED):
        raise GradingError("Không thể trả bài ở trạng thái hiện tại.")
    sub.status = SubmissionStatus.RETURNED
    sub.teacher_comment = (reason or "").strip() or "Ảnh chưa rõ hoặc thiếu trang, em chụp và nộp lại nhé."
    sub.result_sent_at = None
    if sub.assignment is not None:
        sub.assignment.status = AssignmentStatus.ASSIGNED
    db.flush()


def needs_attention(sub: Submission, settings: Settings) -> bool:
    """Bài cần giáo viên xem kỹ: độ tin cậy thấp hoặc có câu không tìm thấy."""
    conf = sub.min_confidence
    return (conf is not None and conf < settings.low_confidence_threshold) or any(not g.found for g in sub.grades)
