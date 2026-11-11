"""Ước lượng mức độ nắm vững theo chủ đề bằng mô hình Elo.

Mỗi cặp (học sinh, chủ đề) có một năng lực θ. Mỗi câu hỏi có độ khó b theo mức độ
nhận thức. Xác suất làm đúng kỳ vọng: P = 1 / (1 + e^-(θ - b)).
Sau mỗi kết quả thực tế p ∈ [0, 1] (điểm câu / điểm tối đa):
    θ ← θ + K · w · (p − P),   với K = K_BASE / (1 + K_DECAY · n)
n là số quan sát đã có (K giảm dần để ước lượng ổn định hơn), w là trọng số nguồn dữ liệu.
Mức nắm vững hiển thị = P(làm đúng một câu mức "Thông hiểu") = sigmoid(θ), tính theo %.

Tham khảo: R. Pelánek (2016), "Applications of the Elo rating system in adaptive
educational systems", Computers & Education, 98, 169–179.

Chỉ điểm đã được giáo viên XÁC NHẬN mới được dùng để cập nhật (AI chỉ đề xuất).
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Classroom, ItemGrade, Question, ScoreRecord, Student, Submission, SubmissionStatus

LEVEL_DIFFICULTY: dict[int, float] = {1: -1.0, 2: 0.0, 3: 1.0, 4: 2.0}
# Hệ số học K lớn hơn mức thường dùng trong hệ thống luyện tập trực tuyến (K≈1) vì dữ liệu lớp học
# thưa: mỗi chủ đề chỉ có vài quan sát/tháng. K giảm dần theo số quan sát để ước lượng ổn định.
K_BASE = 2.0
K_DECAY = 0.25
THETA_MIN, THETA_MAX = -4.0, 5.0
WEIGHT_GRADE = 1.0
WEIGHT_SCORE_TOPIC = 1.0  # điểm nhập theo đúng chủ đề
WEIGHT_SCORE_GENERAL = 0.5  # điểm chung toàn môn, áp cho mọi chủ đề nhưng yếu hơn

# Ngưỡng phân loại (theo %)
BANDS: list[tuple[float, str, str]] = [
    (50.0, "Cần củng cố", "m-low"),
    (70.0, "Đang tiến bộ", "m-mid"),
    (85.0, "Khá vững", "m-good"),
    (101.0, "Thành thạo", "m-high"),
]


def sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def expected_success(theta: float, difficulty: float) -> float:
    return sigmoid(theta - difficulty)


def difficulty_of(level: int) -> float:
    return LEVEL_DIFFICULTY.get(level, 0.0)


@dataclass(frozen=True)
class Observation:
    student_id: int
    topic_id: int
    performance: float  # 0..1
    difficulty: float
    at: datetime
    weight: float = WEIGHT_GRADE
    source: str = "grade"
    submission_id: int | None = None


@dataclass(frozen=True)
class Residual:
    """Chênh lệch giữa kết quả thực tế và kết quả mô hình kỳ vọng tại thời điểm làm bài."""

    student_id: int
    submission_id: int | None
    at: datetime
    value: float  # > 0: làm tốt hơn kỳ vọng; < 0: kém hơn kỳ vọng


@dataclass
class TopicMastery:
    theta: float = 0.0
    n: int = 0
    history: list[tuple[datetime, float]] = field(default_factory=list)

    def update(self, obs: Observation) -> None:
        k = K_BASE / (1.0 + K_DECAY * self.n) * obs.weight
        p = min(1.0, max(0.0, obs.performance))
        self.theta += k * (p - expected_success(self.theta, obs.difficulty))
        self.theta = min(THETA_MAX, max(THETA_MIN, self.theta))
        self.n += 1
        self.history.append((obs.at, self.pct))

    @property
    def has_data(self) -> bool:
        return self.n > 0

    @property
    def pct(self) -> float:
        return round(100.0 * sigmoid(self.theta), 1)

    @property
    def label(self) -> str:
        return mastery_label(self.pct if self.has_data else None)

    @property
    def css(self) -> str:
        return mastery_css(self.pct if self.has_data else None)


MasteryTable = dict[int, dict[int, TopicMastery]]  # student_id -> topic_id -> TopicMastery


def mastery_label(pct: float | None) -> str:
    if pct is None:
        return "Chưa có dữ liệu"
    for upper, label, _ in BANDS:
        if pct < upper:
            return label
    return BANDS[-1][1]


def mastery_css(pct: float | None) -> str:
    if pct is None:
        return "m-none"
    for upper, _, css in BANDS:
        if pct < upper:
            return css
    return BANDS[-1][2]


def compute_mastery(observations: Iterable[Observation], residuals: list[Residual] | None = None) -> MasteryTable:
    """Duyệt các quan sát theo thời gian và cập nhật Elo.

    Nếu truyền `residuals`, ghi lại chênh lệch (thực tế − kỳ vọng) của từng câu đã chấm –
    dùng để phát hiện học sinh tụt điểm mà không bị ảnh hưởng bởi độ khó thay đổi của bài.
    """
    table: MasteryTable = defaultdict(dict)
    for obs in sorted(observations, key=lambda o: o.at):
        topic_state = table[obs.student_id].setdefault(obs.topic_id, TopicMastery())
        if residuals is not None and obs.source == "grade":
            expected = expected_success(topic_state.theta, obs.difficulty)
            residuals.append(Residual(obs.student_id, obs.submission_id, obs.at, obs.performance - expected))
        topic_state.update(obs)
    return dict(table)


def collect_observations(db: Session, student_ids: list[int], topic_ids: list[int]) -> list[Observation]:
    if not student_ids:
        return []
    observations: list[Observation] = []

    grade_rows = db.execute(
        select(
            Submission.student_id,
            Question.topic_id,
            Question.level,
            ItemGrade.final_score,
            ItemGrade.max_score,
            Submission.confirmed_at,
            Submission.submitted_at,
            Submission.id,
        )
        .join(Submission, ItemGrade.submission_id == Submission.id)
        .join(Question, ItemGrade.question_id == Question.id)
        .where(
            Submission.status == SubmissionStatus.CONFIRMED,
            Submission.student_id.in_(student_ids),
            ItemGrade.final_score.is_not(None),
        )
    ).all()
    for student_id, topic_id, level, score, max_score, confirmed_at, submitted_at, submission_id in grade_rows:
        if not max_score:
            continue
        observations.append(
            Observation(
                student_id=student_id,
                topic_id=topic_id,
                performance=score / max_score,
                difficulty=difficulty_of(level),
                # dùng thời điểm nộp bài để phản ánh đúng trình tự học tập
                at=submitted_at or confirmed_at,
                weight=WEIGHT_GRADE,
                submission_id=submission_id,
            )
        )

    record_rows = db.scalars(select(ScoreRecord).where(ScoreRecord.student_id.in_(student_ids))).all()
    topic_set = set(topic_ids)
    for rec in record_rows:
        if not rec.max_score:
            continue
        perf = rec.score / rec.max_score
        if rec.topic_id is not None:
            if rec.topic_id in topic_set:
                observations.append(
                    Observation(rec.student_id, rec.topic_id, perf, 0.0, rec.recorded_at, WEIGHT_SCORE_TOPIC, "score")
                )
        else:
            for topic_id in topic_ids:
                observations.append(
                    Observation(rec.student_id, topic_id, perf, 0.0, rec.recorded_at, WEIGHT_SCORE_GENERAL, "score")
                )
    return observations


def mastery_for_students(db: Session, students: list[Student], topic_ids: list[int]) -> MasteryTable:
    ids = [s.id for s in students]
    table = compute_mastery(collect_observations(db, ids, topic_ids))
    for sid in ids:
        table.setdefault(sid, {})
    return table


def class_mastery(db: Session, classroom: Classroom) -> MasteryTable:
    topic_ids = [t.id for t in classroom.subject.topics]
    return mastery_for_students(db, list(classroom.students), topic_ids)


def get_topic_state(table: MasteryTable, student_id: int, topic_id: int) -> TopicMastery:
    return table.get(student_id, {}).get(topic_id) or TopicMastery()


def average_pct(states: Iterable[TopicMastery]) -> float | None:
    values = [s.pct for s in states if s.has_data]
    return round(sum(values) / len(values), 1) if values else None


def student_average(table: MasteryTable, student_id: int) -> float | None:
    return average_pct(table.get(student_id, {}).values())


def topic_average(table: MasteryTable, topic_id: int) -> float | None:
    return average_pct(states[topic_id] for states in table.values() if topic_id in states)
