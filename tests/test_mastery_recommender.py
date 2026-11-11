"""Mô hình mức nắm vững (Elo) và thuật toán chọn câu hỏi."""

import itertools
from datetime import datetime, timedelta

from app.models import Question, Topic
from app.services.mastery import (
    Observation,
    TopicMastery,
    compute_mastery,
    mastery_label,
)
from app.services.recommender import choose_level, recommend

T0 = datetime(2026, 9, 1)


def obs(perf, level_difficulty=0.0, day=0, topic=1, weight=1.0):
    return Observation(1, topic, perf, level_difficulty, T0 + timedelta(days=day), weight)


def test_good_results_raise_mastery_and_poor_results_lower_it():
    good = compute_mastery([obs(1.0, day=i) for i in range(6)])[1][1]
    poor = compute_mastery([obs(0.2, day=i) for i in range(6)])[1][1]
    assert good.pct > 85
    assert poor.pct < 35
    # hội tụ dần: mỗi lần tăng ít hơn lần trước
    deltas = [b - a for (_, a), (_, b) in zip(good.history, good.history[1:], strict=False)]
    assert all(d1 >= d2 for d1, d2 in itertools.pairwise(deltas))


def test_same_score_on_harder_question_counts_more():
    easy = compute_mastery([obs(0.7, -1.0)])[1][1]
    hard = compute_mastery([obs(0.7, 2.0)])[1][1]
    assert hard.pct > easy.pct


def test_weight_reduces_influence():
    strong = compute_mastery([obs(1.0, weight=1.0)])[1][1]
    weak = compute_mastery([obs(1.0, weight=0.4)])[1][1]
    assert 50 < weak.pct < strong.pct


def test_labels():
    assert mastery_label(None) == "Chưa có dữ liệu"
    assert mastery_label(30) == "Cần củng cố"
    assert mastery_label(60) == "Đang tiến bộ"
    assert mastery_label(80) == "Khá vững"
    assert mastery_label(92) == "Thành thạo"


def test_choose_level_follows_mode_target():
    assert choose_level(-2.0, 0.7) == 1
    assert choose_level(2.0, 0.7) == 3
    assert choose_level(2.0, 0.45) == 4  # nâng cao: khó hơn
    assert choose_level(2.0, 0.85) <= 2  # ôn tập: dễ hơn


def _bank():
    topics = [Topic(id=i, name=f"Chủ đề {i}", position=i) for i in (1, 2, 3)]
    questions = []
    qid = 1
    for t in topics:
        for level in (1, 2, 3, 4):
            for _ in range(2):
                questions.append(
                    Question(id=qid, topic_id=t.id, level=level, status="active", content=f"q{qid}", max_score=2)
                )
                qid += 1
    return topics, questions


def test_recommend_targets_weakest_topics():
    topics, bank = _bank()
    states = {1: TopicMastery(theta=2.0, n=3), 2: TopicMastery(theta=-1.5, n=3), 3: TopicMastery(theta=0.2, n=3)}
    rec = recommend(topics, states, bank, num_questions=4, mode="auto")
    assert [t.id for t, _ in rec.focus] == [2, 3]
    assert len(rec.slots) == 4 and rec.missing == 0
    # chủ đề yếu (θ=-1.5) bắt đầu từ Nhận biết, câu thứ hai tăng một bậc
    weak_levels = [s.level for s in rec.slots if s.topic.id == 2]
    assert weak_levels == [1, 2]
    assert "Ưu tiên chủ đề" in rec.rationale()


def test_recommend_avoids_recent_then_repeats_when_bank_runs_out():
    topics, bank = _bank()
    topic1 = [q for q in bank if q.topic_id == 1]
    rec = recommend(topics[:1], {}, topic1, num_questions=3, mode="auto", recent_ids={q.id for q in topic1})
    assert rec.missing == 3  # mọi câu đều vừa giao
    from app.services.recommender import index_bank

    rec.fill_with_repeats(index_bank(topic1))
    assert rec.missing == 0 and rec.repeated == 3
    assert len({s.question.id for s in rec.slots}) == 3  # không trùng trong cùng bộ đề


def test_recommend_only_requested_topics():
    topics, bank = _bank()
    rec = recommend(topics, {}, bank, num_questions=4, topic_ids=[3])
    assert {s.topic.id for s in rec.slots} == {3}
