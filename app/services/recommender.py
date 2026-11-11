"""Đề xuất bộ câu hỏi cá nhân hóa theo điểm yếu của từng học sinh.

Thuật toán (giải thích được, chạy không cần AI):
1. Xếp chủ đề theo mức nắm vững tăng dần (chủ đề chưa có dữ liệu coi như 55%).
2. Lấy ⌈n/2⌉ chủ đề yếu nhất (hoặc các chủ đề giáo viên chỉ định), chia đều n câu.
3. Với mỗi chủ đề, chọn mức độ có xác suất làm đúng kỳ vọng gần "mức mục tiêu" nhất:
   - Cá nhân hóa (auto): ≈ 70%  – vùng thử thách vừa sức
   - Nâng cao (advanced): ≈ 45% – dành cho học sinh khá giỏi
   - Ôn tập (review):    ≈ 85% – củng cố, lấy lại tự tin
   Câu thứ hai trong cùng chủ đề tăng một bậc (trừ chế độ ôn tập) để tạo "bậc thang".
4. Lấy câu trong ngân hàng đúng chủ đề/mức độ, tránh câu đã giao gần đây.
   Thiếu câu thì để trống để AI soạn câu mới (giáo viên duyệt trước khi gửi).
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field

from ..models import LEVELS, Question, Topic
from .mastery import TopicMastery, difficulty_of, expected_success

TARGET_SUCCESS: dict[str, float] = {"auto": 0.70, "advanced": 0.45, "review": 0.85}
MODE_LABELS: dict[str, str] = {
    "auto": "Cá nhân hóa theo điểm yếu",
    "advanced": "Nâng cao (học sinh khá giỏi)",
    "review": "Ôn tập, củng cố",
}
UNKNOWN_PCT = 55.0


@dataclass
class Slot:
    topic: Topic
    level: int
    question: Question | None = None


@dataclass
class Recommendation:
    mode: str
    slots: list[Slot]
    focus: list[tuple[Topic, float | None]] = field(default_factory=list)
    generated: int = 0  # số câu AI soạn mới
    repeated: int = 0  # số câu lặp lại từ bài trước

    @property
    def missing(self) -> int:
        return sum(1 for s in self.slots if s.question is None)

    def fill_with_repeats(self, index: dict[tuple[int, int], list[Question]]) -> None:
        """Khi không còn câu mới (và không có AI soạn): dùng lại câu đã giao, gần mức độ nhất."""
        used = {s.question.id for s in self.slots if s.question is not None}
        for slot in self.slots:
            if slot.question is not None:
                continue
            question = fallback_question(index, slot.topic.id, slot.level, used)
            if question is not None:
                slot.question = question
                slot.level = question.level
                used.add(question.id)
                self.repeated += 1

    def rationale(self) -> str:
        parts = []
        focus_text = "; ".join(
            f"{t.name} ({'chưa có dữ liệu' if pct is None else f'{pct:.0f}%'})" for t, pct in self.focus
        )
        parts.append(f"Chế độ: {MODE_LABELS.get(self.mode, self.mode)}.")
        if focus_text:
            parts.append(f"Ưu tiên chủ đề: {focus_text}.")
        target = TARGET_SUCCESS.get(self.mode, 0.7)
        levels = ", ".join(LEVELS[s.level] for s in self.slots)
        parts.append(f"Độ khó nhắm tới xác suất làm đúng ≈ {target:.0%}; mức độ các câu: {levels}.")
        if self.generated:
            parts.append(f"{self.generated} câu do AI soạn mới (duyệt cùng bộ đề).")
        if self.repeated:
            parts.append(f"{self.repeated} câu lặp lại từ bài trước vì ngân hàng chưa đủ câu mới.")
        if self.missing:
            parts.append(f"{self.missing} vị trí chưa có câu phù hợp.")
        return " ".join(parts)


def choose_level(theta: float, target: float) -> int:
    """Mức độ (1–4) có xác suất làm đúng gần mục tiêu nhất; hòa thì chọn mức cao hơn."""
    return min(LEVELS, key=lambda lv: (abs(expected_success(theta, difficulty_of(lv)) - target), -lv))


def prioritize_topics(topics: Iterable[Topic], states: dict[int, TopicMastery]) -> list[Topic]:
    def key(topic: Topic) -> tuple[float, int, int]:
        state = states.get(topic.id)
        pct = state.pct if state and state.has_data else UNKNOWN_PCT
        return (pct, topic.position, topic.id)

    return sorted(topics, key=key)


def index_bank(bank: Iterable[Question]) -> dict[tuple[int, int], list[Question]]:
    index: dict[tuple[int, int], list[Question]] = defaultdict(list)
    for q in sorted(bank, key=lambda q: q.id):
        if q.status == "active":
            index[(q.topic_id, q.level)].append(q)
    return index


def _level_order(level: int, mode: str) -> list[int]:
    if mode == "advanced":
        order = [level, level + 1, level - 1]
    else:
        order = [level, level - 1, level + 1]
    return [lv for lv in order if lv in LEVELS]


def pick_question(
    index: dict[tuple[int, int], list[Question]],
    topic_id: int,
    level: int,
    mode: str,
    used: set[int],
    recent: set[int],
) -> Question | None:
    for lv in _level_order(level, mode):
        for q in index.get((topic_id, lv), []):
            if q.id not in used and q.id not in recent:
                return q
    return None


def fallback_question(
    index: dict[tuple[int, int], list[Question]], topic_id: int, level: int, used: set[int]
) -> Question | None:
    for lv in sorted(LEVELS, key=lambda lv: (abs(lv - level), -lv)):
        for q in index.get((topic_id, lv), []):
            if q.id not in used:
                return q
    return None


def recommend(
    topics: list[Topic],
    states: dict[int, TopicMastery],
    bank: Iterable[Question],
    *,
    num_questions: int = 4,
    mode: str = "auto",
    topic_ids: Iterable[int] | None = None,
    recent_ids: Iterable[int] = (),
) -> Recommendation:
    if mode not in TARGET_SUCCESS:
        raise ValueError(f"Chế độ không hợp lệ: {mode}")
    wanted = set(topic_ids or [])
    pool = [t for t in topics if not wanted or t.id in wanted]
    if not pool:
        raise ValueError("Môn học chưa có chủ đề phù hợp.")
    num_questions = max(1, num_questions)

    ordered = prioritize_topics(pool, states)
    k = len(ordered) if wanted else min(len(ordered), max(1, math.ceil(num_questions / 2)))
    chosen = ordered[:k]
    counts = dict.fromkeys((t.id for t in chosen), 0)
    for i in range(num_questions):
        counts[chosen[i % k].id] += 1

    index = index_bank(bank)
    target = TARGET_SUCCESS[mode]
    used: set[int] = set()
    recent = set(recent_ids)
    slots: list[Slot] = []
    focus: list[tuple[Topic, float | None]] = []

    for topic in chosen:
        state = states.get(topic.id) or TopicMastery()
        focus.append((topic, state.pct if state.has_data else None))
        base = choose_level(state.theta, target)
        for j in range(counts[topic.id]):
            level = min(4, base + (0 if mode == "review" else j))
            question = pick_question(index, topic.id, level, mode, used, recent)
            if question is not None:
                used.add(question.id)
                level = question.level
            slots.append(Slot(topic=topic, level=level, question=question))

    return Recommendation(mode=mode, slots=slots, focus=focus)
