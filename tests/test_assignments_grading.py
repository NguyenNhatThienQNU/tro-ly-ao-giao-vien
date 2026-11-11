"""Giao bài, chấm bài, cảnh báo – trên dữ liệu mẫu."""

from datetime import timedelta

import pytest

from app.ai.base import AIError
from app.ai.mock import MockProvider
from app.ai.schemas import CriterionResult, GradingResult, QuestionResult
from app.models import (
    AssignmentStatus,
    Question,
    Submission,
    SubmissionImage,
    SubmissionStatus,
    Topic,
)
from app.services import assignments as service
from app.services import grading
from app.services.alerts import class_alerts
from app.services.mastery import class_mastery, student_average
from app.services.storage import save_submission_file
from app.utils.timeutil import utcnow

from .conftest import make_image


def by_name(classroom, name):
    return next(s for s in classroom.students if s.full_name == name)


def test_personalized_batch_differs_by_student(db, sample):
    result = service.create_batch(db, sample, title="Kiểm tra", due_at=utcnow() + timedelta(days=1), num_questions=4)
    batch = result.batch
    assert len(batch.assignments) == 10
    assert all(a.status == AssignmentStatus.DRAFT and len(a.items) == 4 for a in batch.assignments)
    strong = next(a for a in batch.assignments if a.student.full_name == "Nguyễn Minh Anh")
    weak = next(a for a in batch.assignments if a.student.full_name == "Đỗ Thành Phát")
    avg = lambda a: sum(i.question.level for i in a.items) / len(a.items)  # noqa: E731
    assert avg(strong) > avg(weak)
    assert "Ưu tiên chủ đề" in strong.rationale


def test_advanced_mode_is_harder(db, sample):
    student = by_name(sample, "Nguyễn Minh Anh")
    auto = service.create_batch(db, sample, title="a", due_at=None, student_ids=[student.id]).batch.assignments[0]
    adv = service.create_batch(
        db, sample, title="b", due_at=None, student_ids=[student.id], mode="advanced"
    ).batch.assignments[0]
    level = lambda a: sum(i.question.level for i in a.items)  # noqa: E731
    assert level(adv) >= level(auto)


class FakeRealAI(MockProvider):
    is_real = True  # giả lập AI thật để kiểm tra luồng sinh câu hỏi


def test_ai_generates_questions_for_empty_topic_and_approval_activates_them(db, sample):
    topic = Topic(name="Chủ đề mới chưa có câu", position=99)
    sample.subject.topics.append(topic)
    db.flush()
    student = by_name(sample, "Võ Thanh Hà")
    result = service.create_batch(
        db,
        sample,
        title="Mới",
        due_at=None,
        student_ids=[student.id],
        topic_ids=[topic.id],
        num_questions=2,
        ai=FakeRealAI(),
    )
    assignment = result.batch.assignments[0]
    assert result.generated >= 1 and len(assignment.items) == 2
    assert all(i.question.status == "draft" and i.question.source == "ai" for i in assignment.items)
    service.approve_assignment(db, assignment)
    assert assignment.status == AssignmentStatus.ASSIGNED
    assert all(i.question.status == "active" for i in assignment.items)


def test_ai_error_is_reported_as_warning(db, sample):
    class BrokenAI(FakeRealAI):
        def generate_questions(self, request):
            raise AIError("hết hạn mức")

    topic = Topic(name="Trống", position=98)
    sample.subject.topics.append(topic)
    db.flush()
    result = service.create_batch(
        db, sample, title="x", due_at=None, topic_ids=[topic.id], num_questions=1, ai=BrokenAI()
    )
    assert result.unfilled == 10 and any("hết hạn mức" in w for w in result.warnings)


def test_edit_draft_and_cancel(db, sample):
    a = service.create_batch(db, sample, title="x", due_at=None, num_questions=2).batch.assignments[0]
    first = a.items[0]
    service.remove_item(db, a, first.id)
    assert len(a.items) == 1
    q = db.query(Question).filter(Question.subject_id == sample.subject_id).first()
    if all(i.question_id != q.id for i in a.items):
        service.add_item(db, a, q)
    with pytest.raises(service.AssignmentError):
        service.add_item(db, a, a.items[0].question)  # trùng câu
    service.cancel_assignment(db, a)
    assert a.status == AssignmentStatus.CANCELLED


def _submitted(db, settings, assignment):
    sub = Submission(
        student_id=assignment.student_id,
        assignment_id=assignment.id,
        status=SubmissionStatus.SUBMITTED,
        submitted_at=utcnow(),
        max_total=assignment.max_total,
    )
    db.add(sub)
    db.flush()
    path, mime = save_submission_file(settings, sub.id, 1, make_image(), "image/jpeg")
    sub.images.append(SubmissionImage(file_path=path, mime_type=mime, position=1))
    assignment.status = AssignmentStatus.SUBMITTED
    db.flush()
    return sub


def test_apply_result_clamps_scores_and_marks_missing(db, sample, settings):
    a = service.create_batch(db, sample, title="x", due_at=None, num_questions=3).batch.assignments[0]
    service.approve_assignment(db, a)
    sub = _submitted(db, settings, a)
    q1 = a.items[0].question
    result = GradingResult(
        questions=[
            QuestionResult(
                question_number=1,
                found=True,
                transcription="print(1)",
                criteria=[
                    CriterionResult(criterion=r["criterion"], max_points=r["points"], awarded=99, comment="")
                    for r in q1.rubric
                ],
                score=99,
                comment="Tốt",
                errors=[],
                confidence=1.7,
            )
        ],
        overall_feedback="Cố gắng nhé",
        image_quality="tốt",
    )
    grading.apply_result(db, sub, result)
    assert sub.status == SubmissionStatus.AI_GRADED
    g1, g2, g3 = sub.grades
    assert g1.ai_score == q1.max_score and g1.confidence == 1.0  # chặn vượt mức
    assert not g2.found and g2.ai_score == 0 and not g3.found
    assert grading.needs_attention(sub, settings)


def test_confirm_updates_mastery_and_assignment(db, sample, settings):
    student = by_name(sample, "Ngô Thảo Vy")
    a = service.create_batch(db, sample, title="x", due_at=None, student_ids=[student.id]).batch.assignments[0]
    service.approve_assignment(db, a)
    sub = _submitted(db, settings, a)
    assert grading.grade_submission(db, sub, MockProvider(), settings)
    before = student_average(class_mastery(db, sample), student.id)
    full = {g.id: g.max_score for g in sub.grades}
    grading.confirm_submission(db, sub, full, {sub.grades[0].id: "Rất tốt"}, "Em tiến bộ nhiều")
    db.flush()
    after = student_average(class_mastery(db, sample), student.id)
    assert sub.status == SubmissionStatus.CONFIRMED and a.status == AssignmentStatus.GRADED
    assert sub.final_total == sub.max_total and after > before
    assert sub.grades[0].teacher_comment == "Rất tốt"


def test_grading_failure_retries_then_fails(db, sample, settings):
    class BrokenAI(MockProvider):
        def grade(self, request):
            raise AIError("mất mạng")

    a = service.create_batch(db, sample, title="x", due_at=None, num_questions=1).batch.assignments[0]
    service.approve_assignment(db, a)
    sub = _submitted(db, settings, a)
    for _ in range(settings.max_grading_attempts):
        assert not grading.grade_submission(db, sub, BrokenAI(), settings)
    assert sub.status == SubmissionStatus.FAILED and "mất mạng" in sub.error_message
    # giáo viên chấm tay: hệ thống mở khung điểm trống, thiếu điểm thì không cho xác nhận
    grading.init_manual_grades(db, sub)
    with pytest.raises(grading.GradingError):
        grading.confirm_submission(db, sub, {})
    grading.confirm_submission(db, sub, {g.id: 0.5 for g in sub.grades})
    assert sub.status == SubmissionStatus.CONFIRMED


def test_return_submission_reopens_assignment(db, sample, settings):
    a = service.create_batch(db, sample, title="x", due_at=None, num_questions=1).batch.assignments[0]
    service.approve_assignment(db, a)
    sub = _submitted(db, settings, a)
    grading.return_submission(db, sub, "Ảnh mờ")
    assert sub.status == SubmissionStatus.RETURNED and a.status == AssignmentStatus.ASSIGNED


def test_alerts_detect_drop_overdue_and_unlinked(db, sample):
    alerts = class_alerts(db, sample, class_mastery(db, sample))
    kinds = {(a.kind, a.student_name) for a in alerts}
    assert ("drop", "Phạm Đức Duy") in kinds  # dữ liệu mẫu mô phỏng em Duy tụt điểm
    assert ("overdue", "Đặng Quốc Huy") in kinds
    assert any(a.kind == "unlinked" for a in alerts)
    # không báo tụt điểm nhầm với học sinh khác
    assert sum(1 for a in alerts if a.kind == "drop") == 1
