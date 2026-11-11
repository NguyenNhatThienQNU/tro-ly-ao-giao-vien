"""Nghiệp vụ giao bài: tạo bộ đề nháp cá nhân hóa, duyệt, chỉnh sửa, hủy."""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..ai.base import AIError, AIProvider
from ..ai.schemas import QuestionGenRequest
from ..models import (
    LEVELS,
    Assignment,
    AssignmentBatch,
    AssignmentItem,
    AssignmentStatus,
    Classroom,
    Question,
    Student,
    Subject,
    Submission,
    SubmissionStatus,
    Topic,
)
from ..utils.text import round_quarter
from ..utils.timeutil import utcnow
from .mastery import mastery_for_students
from .recommender import MODE_LABELS, TARGET_SUCCESS, Recommendation, Slot, index_bank, recommend

log = logging.getLogger(__name__)

DEFAULT_MAX_SCORE: dict[int, float] = {1: 1.0, 2: 2.0, 3: 3.0, 4: 4.0}
MAX_QUESTIONS = 10
MAX_GENERATE_PER_GROUP = 6


class AssignmentError(ValueError):
    """Lỗi nghiệp vụ hiển thị được cho giáo viên."""


@dataclass
class BatchResult:
    batch: AssignmentBatch
    generated: int = 0
    unfilled: int = 0
    warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Truy vấn
# ---------------------------------------------------------------------------


def active_bank(db: Session, subject_id: int) -> list[Question]:
    return list(
        db.scalars(select(Question).where(Question.subject_id == subject_id, Question.status == "active")).all()
    )


def recent_question_ids(db: Session, student_id: int, limit: int = 5) -> set[int]:
    assignment_ids = db.scalars(
        select(Assignment.id)
        .where(Assignment.student_id == student_id, Assignment.status != AssignmentStatus.CANCELLED)
        .order_by(Assignment.created_at.desc())
        .limit(limit)
    ).all()
    if not assignment_ids:
        return set()
    return set(
        db.scalars(select(AssignmentItem.question_id).where(AssignmentItem.assignment_id.in_(assignment_ids))).all()
    )


def open_assignments(db: Session, student: Student) -> list[Assignment]:
    """Bộ đề đã giao, học sinh chưa nộp."""
    rows = db.scalars(
        select(Assignment)
        .where(Assignment.student_id == student.id, Assignment.status == AssignmentStatus.ASSIGNED)
        .order_by(Assignment.id)
    ).all()
    return sorted(rows, key=lambda a: (a.due_at is None, a.due_at or datetime.max, a.id))


def batch_stats(batch: AssignmentBatch, now: datetime | None = None) -> dict[str, int]:
    now = now or utcnow()
    stats = dict.fromkeys(("total", "draft", "assigned", "sent", "submitted", "graded", "cancelled", "overdue"), 0)
    for a in batch.assignments:
        if a.status == AssignmentStatus.CANCELLED:
            stats["cancelled"] += 1
            continue
        stats["total"] += 1
        stats[a.status] = stats.get(a.status, 0) + 1
        if a.sent_at:
            stats["sent"] += 1
        if a.status == AssignmentStatus.ASSIGNED and a.due_at and a.due_at < now:
            stats["overdue"] += 1
    active = stats["total"] - stats["draft"]
    stats["active"] = active
    stats["done"] = stats["submitted"] + stats["graded"]
    stats["done_pct"] = round(100 * stats["done"] / active) if active else 0
    return stats


# ---------------------------------------------------------------------------
# Sinh câu hỏi bằng AI
# ---------------------------------------------------------------------------


def normalize_rubric(rubric: list[dict], max_score: float) -> list[dict]:
    """Đảm bảo rubric có ít nhất một tiêu chí và tổng điểm đúng bằng max_score."""
    items = [
        {"criterion": str(r.get("criterion", "")).strip(), "points": float(r.get("points") or 0)}
        for r in rubric or []
        if str(r.get("criterion", "")).strip()
    ]
    if not items:
        return [{"criterion": "Lời giải đúng, đầy đủ, trình bày rõ ràng", "points": max_score}]
    total = sum(max(0.0, i["points"]) for i in items)
    if total <= 0:
        share = round_quarter(max_score / len(items))
        for i in items:
            i["points"] = share
    else:
        for i in items:
            i["points"] = round_quarter(max(0.0, i["points"]) * max_score / total)
    diff = round(max_score - sum(i["points"] for i in items), 2)
    items[-1]["points"] = round(max(0.0, items[-1]["points"] + diff), 2)
    return items


def generate_questions_for_topic(
    db: Session,
    ai: AIProvider,
    subject: Subject,
    topic: Topic,
    level: int,
    count: int,
    instruction: str = "",
    status: str = "draft",
) -> list[Question]:
    max_score = DEFAULT_MAX_SCORE.get(level, 2.0)
    existing = db.scalars(
        select(Question.content).where(Question.topic_id == topic.id).order_by(Question.id.desc()).limit(15)
    ).all()
    request = QuestionGenRequest(
        subject_name=subject.name,
        topic_name=topic.name,
        level=level,
        level_name=LEVELS[level],
        count=count,
        max_score=max_score,
        instruction=instruction,
        avoid=list(existing),
    )
    created: list[Question] = []
    for generated in ai.generate_questions(request)[:count]:
        content = generated.content.strip()
        if not content:
            continue
        rubric = normalize_rubric([r.model_dump() for r in generated.rubric], max_score)
        question = Question(
            subject_id=subject.id,
            topic_id=topic.id,
            content=content,
            level=level,
            max_score=max_score,
            rubric=rubric,
            reference_answer=generated.reference_answer.strip(),
            source="ai",
            status=status,
        )
        db.add(question)
        created.append(question)
    db.flush()
    return created


# ---------------------------------------------------------------------------
# Tạo đợt giao bài
# ---------------------------------------------------------------------------


def create_batch(
    db: Session,
    classroom: Classroom,
    *,
    title: str,
    due_at: datetime | None,
    num_questions: int = 4,
    mode: str = "auto",
    student_ids: list[int] | None = None,
    topic_ids: list[int] | None = None,
    instruction: str = "",
    created_by: str = "teacher",
    ai: AIProvider | None = None,
    generate_missing: bool = True,
) -> BatchResult:
    """Tạo bộ đề NHÁP cho từng học sinh. Giáo viên phải duyệt trước khi gửi."""
    if mode not in TARGET_SUCCESS:
        raise AssignmentError("Chế độ giao bài không hợp lệ.")
    num_questions = max(1, min(MAX_QUESTIONS, int(num_questions)))
    students = [s for s in classroom.students if not student_ids or s.id in set(student_ids)]
    if not students:
        raise AssignmentError("Không có học sinh nào để giao bài.")
    subject = classroom.subject
    topics = list(subject.topics)
    if not topics:
        raise AssignmentError("Môn học chưa có chủ đề. Hãy thêm chủ đề trước.")
    if topic_ids:
        valid = {t.id for t in topics}
        topic_ids = [t for t in topic_ids if t in valid]
        if not topic_ids:
            raise AssignmentError("Chủ đề được chọn không thuộc môn của lớp.")

    title = (title or "").strip() or f"Bài luyện tập – {MODE_LABELS[mode]}"
    batch = AssignmentBatch(
        classroom_id=classroom.id,
        title=title[:200],
        mode=mode,
        num_questions=num_questions,
        due_at=due_at,
        instruction=(instruction or "").strip(),
        created_by=created_by,
    )
    db.add(batch)
    db.flush()
    result = BatchResult(batch=batch)

    table = mastery_for_students(db, students, [t.id for t in topics])
    bank = active_bank(db, subject.id)
    recs: dict[int, Recommendation] = {}
    for student in students:
        recs[student.id] = recommend(
            topics,
            table.get(student.id, {}),
            bank,
            num_questions=num_questions,
            mode=mode,
            topic_ids=topic_ids,
            recent_ids=recent_question_ids(db, student.id),
        )

    # Vị trí còn thiếu câu: (1) AI thật soạn câu mới; (2) dùng lại câu cũ; (3) AI demo soạn câu mẫu
    can_generate = generate_missing and ai is not None
    if can_generate and ai.is_real:
        _generate_for_missing(db, ai, subject, topics, recs, batch.instruction, result)
    index = index_bank(bank)
    for rec in recs.values():
        rec.fill_with_repeats(index)
    if can_generate and not ai.is_real:
        _generate_for_missing(db, ai, subject, topics, recs, batch.instruction, result)

    for student in students:
        rec = recs[student.id]
        rationale = rec.rationale()
        if batch.instruction:
            rationale = f"Yêu cầu của giáo viên: {batch.instruction}. {rationale}"
        assignment = Assignment(
            batch_id=batch.id,
            classroom_id=classroom.id,
            student_id=student.id,
            title=batch.title,
            status=AssignmentStatus.DRAFT,
            due_at=due_at,
            rationale=rationale,
        )
        seen: set[int] = set()
        for slot in rec.slots:
            if slot.question is None:
                result.unfilled += 1
                continue
            if slot.question.id in seen:
                continue
            seen.add(slot.question.id)
            assignment.items.append(AssignmentItem(question=slot.question, position=len(assignment.items)))
        db.add(assignment)
    db.flush()
    if result.unfilled:
        result.warnings.append(
            f"Còn {result.unfilled} vị trí chưa có câu hỏi phù hợp. Hãy bổ sung ngân hàng câu hỏi hoặc thêm câu thủ công."
        )
    return result


def _generate_for_missing(
    db: Session,
    ai: AIProvider,
    subject: Subject,
    topics: list[Topic],
    recs: dict[int, Recommendation],
    instruction: str,
    result: BatchResult,
) -> None:
    """Gom các vị trí thiếu theo (chủ đề, mức độ) để gọi AI ít lần nhất."""
    missing: dict[tuple[int, int], list[tuple[Recommendation, Slot]]] = defaultdict(list)
    for rec in recs.values():
        for slot in rec.slots:
            if slot.question is None:
                missing[(slot.topic.id, slot.level)].append((rec, slot))
    topic_by_id = {t.id: t for t in topics}
    for (topic_id, level), entries in missing.items():
        count = min(len(entries), MAX_GENERATE_PER_GROUP)
        try:
            questions = generate_questions_for_topic(db, ai, subject, topic_by_id[topic_id], level, count, instruction)
        except AIError as exc:
            log.warning("AI không sinh được câu hỏi: %s", exc)
            result.warnings.append(f"AI chưa soạn được câu cho «{topic_by_id[topic_id].name}»: {exc}")
            continue
        result.generated += len(questions)
        if not questions:
            continue
        for i, (rec, slot) in enumerate(entries):
            slot.question = questions[i % len(questions)]
            rec.generated += 1


# ---------------------------------------------------------------------------
# Duyệt / chỉnh sửa
# ---------------------------------------------------------------------------


def _require_draft(assignment: Assignment) -> None:
    if assignment.status != AssignmentStatus.DRAFT:
        raise AssignmentError("Chỉ chỉnh sửa được bộ đề đang chờ duyệt.")


def approve_assignment(db: Session, assignment: Assignment) -> None:
    _require_draft(assignment)
    if not assignment.items:
        raise AssignmentError(f"Bộ đề của {assignment.student.full_name} chưa có câu hỏi.")
    assignment.status = AssignmentStatus.ASSIGNED
    assignment.assigned_at = utcnow()
    for item in assignment.items:
        if item.question.status == "draft":
            item.question.status = "active"  # câu AI soạn được duyệt cùng bộ đề
    db.flush()


def approve_batch(db: Session, batch: AssignmentBatch) -> tuple[int, list[str]]:
    approved, skipped = 0, []
    for assignment in batch.assignments:
        if assignment.status != AssignmentStatus.DRAFT:
            continue
        if not assignment.items:
            skipped.append(assignment.student.full_name)
            continue
        approve_assignment(db, assignment)
        approved += 1
    return approved, skipped


def cancel_assignment(db: Session, assignment: Assignment) -> None:
    if assignment.status == AssignmentStatus.GRADED:
        raise AssignmentError("Bài đã chấm, không thể hủy.")
    assignment.status = AssignmentStatus.CANCELLED
    for sub in assignment.submissions:
        if sub.status == SubmissionStatus.COLLECTING:
            db.delete(sub)
    db.flush()


def remove_item(db: Session, assignment: Assignment, item_id: int) -> None:
    _require_draft(assignment)
    item = next((i for i in assignment.items if i.id == item_id), None)
    if item is None:
        raise AssignmentError("Không tìm thấy câu hỏi trong bộ đề.")
    assignment.items.remove(item)
    for pos, it in enumerate(assignment.items):
        it.position = pos
    db.flush()


def add_item(db: Session, assignment: Assignment, question: Question) -> None:
    _require_draft(assignment)
    if question.subject_id != assignment.student.classroom.subject_id:
        raise AssignmentError("Câu hỏi không thuộc môn của lớp.")
    if question.status == "archived":
        raise AssignmentError("Câu hỏi đã lưu trữ.")
    if any(i.question_id == question.id for i in assignment.items):
        raise AssignmentError("Câu hỏi đã có trong bộ đề.")
    if len(assignment.items) >= MAX_QUESTIONS:
        raise AssignmentError(f"Mỗi bộ đề tối đa {MAX_QUESTIONS} câu.")
    assignment.items.append(AssignmentItem(question=question, position=len(assignment.items)))
    db.flush()


def update_batch_due(db: Session, batch: AssignmentBatch, due_at: datetime | None) -> None:
    batch.due_at = due_at
    for a in batch.assignments:
        if a.status in (AssignmentStatus.DRAFT, AssignmentStatus.ASSIGNED):
            a.due_at = due_at
            a.reminder_sent_at = None
    db.flush()


def collecting_submission(db: Session, student: Student) -> Submission | None:
    return db.scalars(
        select(Submission)
        .where(Submission.student_id == student.id, Submission.status == SubmissionStatus.COLLECTING)
        .order_by(Submission.created_at.desc())
    ).first()
