"""Tác vụ nền chạy song song với web:
1. Chấm sơ bộ các bài học sinh vừa nộp (hàng đợi trong CSDL – khởi động lại không mất việc).
2. Gửi bộ đề đã duyệt, kết quả đã xác nhận, yêu cầu nộp lại, nhắc hạn – qua kênh chat.

Mọi việc gửi tin đều dựa vào trạng thái trong CSDL (sent_at, result_sent_at...), nên nếu
mất mạng hoặc học sinh chưa liên kết, hệ thống tự gửi bù khi có thể.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import select, update

from .ai.base import AIProvider
from .channels.base import ChannelHub, ChannelSendError, OutgoingMessage
from .channels.bot_logic import public_assignment_url
from .config import Settings
from .db import session_scope
from .models import Assignment, AssignmentStatus, Student, Submission, SubmissionStatus
from .services import messages
from .services.grading import grade_submission
from .utils.timeutil import utcnow

log = logging.getLogger(__name__)

GRADE_BATCH = 3
DELIVERY_BATCH = 50


@dataclass
class Delivery:
    kind: str  # assignment | result | reminder
    record_id: int
    channel: str
    chat_id: str
    message: OutgoingMessage


class BackgroundWorker:
    def __init__(self, settings: Settings, ai: AIProvider, hub: ChannelHub):
        self.settings = settings
        self.ai = ai
        self.hub = hub

    async def run(self) -> None:
        await asyncio.to_thread(self.recover)
        log.info("Tác vụ nền đã chạy (chu kỳ %.0fs)", self.settings.worker_interval_seconds)
        while True:
            try:
                await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("Lỗi tác vụ nền")
            await asyncio.sleep(self.settings.worker_interval_seconds)

    async def tick(self) -> None:
        await asyncio.to_thread(self.grade_pending)
        await self.deliver()

    # ------------------------------------------------------------------
    def recover(self) -> None:
        """Bài đang chấm dở khi máy chủ tắt -> đưa lại vào hàng đợi."""
        with session_scope() as db:
            db.execute(
                update(Submission)
                .where(Submission.status == SubmissionStatus.GRADING)
                .values(status=SubmissionStatus.SUBMITTED)
            )

    def grade_pending(self, limit: int = GRADE_BATCH) -> int:
        with session_scope() as db:
            ids = db.scalars(
                select(Submission.id)
                .where(Submission.status == SubmissionStatus.SUBMITTED)
                .order_by(Submission.submitted_at)
                .limit(limit)
            ).all()
        done = 0
        for sub_id in ids:
            with session_scope() as db:
                sub = db.get(Submission, sub_id)
                if sub is None or sub.status != SubmissionStatus.SUBMITTED:
                    continue
                sub.status = SubmissionStatus.GRADING  # hiển thị "AI đang chấm" trên web
            with session_scope() as db:
                sub = db.get(Submission, sub_id)
                if grade_submission(db, sub, self.ai, self.settings):
                    done += 1
                    log.info("AI đã chấm sơ bộ bài #%s", sub_id)
        return done

    # ------------------------------------------------------------------
    def collect_deliveries(self) -> list[Delivery]:
        channels = list(self.hub.adapters)
        if not channels:
            return []
        now = utcnow()
        out: list[Delivery] = []
        with session_scope() as db:
            linked = (Student.chat_id.is_not(None), Student.channel.in_(channels))

            assignments = db.scalars(
                select(Assignment)
                .join(Student, Assignment.student_id == Student.id)
                .where(Assignment.status == AssignmentStatus.ASSIGNED, Assignment.sent_at.is_(None), *linked)
                .order_by(Assignment.assigned_at)
                .limit(DELIVERY_BATCH)
            ).all()
            for a in assignments:
                text = messages.assignment_text(a, public_assignment_url(self.settings, a))
                out.append(Delivery("assignment", a.id, a.student.channel, a.student.chat_id, OutgoingMessage(text)))

            subs = db.scalars(
                select(Submission)
                .join(Student, Submission.student_id == Student.id)
                .where(
                    Submission.status.in_([SubmissionStatus.CONFIRMED, SubmissionStatus.RETURNED]),
                    Submission.result_sent_at.is_(None),
                    *linked,
                )
                .order_by(Submission.confirmed_at)
                .limit(DELIVERY_BATCH)
            ).all()
            for s in subs:
                text = messages.result_text(s) if s.status == SubmissionStatus.CONFIRMED else messages.returned_text(s)
                out.append(Delivery("result", s.id, s.student.channel, s.student.chat_id, OutgoingMessage(text)))

            window = timedelta(hours=self.settings.reminder_hours_before)
            candidates = db.scalars(
                select(Assignment)
                .join(Student, Assignment.student_id == Student.id)
                .where(
                    Assignment.status == AssignmentStatus.ASSIGNED,
                    Assignment.sent_at.is_not(None),
                    Assignment.reminder_sent_at.is_(None),
                    Assignment.due_at.is_not(None),
                    Assignment.due_at > now,
                    Assignment.due_at <= now + window,
                    *linked,
                )
                .limit(DELIVERY_BATCH)
            ).all()
            for a in candidates:
                # bài vừa gửi đã nằm sẵn trong khung nhắc thì không nhắc ngay (tránh làm phiền)
                if a.sent_at and a.sent_at > a.due_at - window:
                    continue
                out.append(
                    Delivery(
                        "reminder",
                        a.id,
                        a.student.channel,
                        a.student.chat_id,
                        OutgoingMessage(messages.reminder_text(a)),
                    )
                )
        return out

    def mark_delivered(self, delivery: Delivery) -> None:
        now = utcnow()
        with session_scope() as db:
            if delivery.kind == "assignment":
                a = db.get(Assignment, delivery.record_id)
                if a:
                    a.sent_at = now
            elif delivery.kind == "reminder":
                a = db.get(Assignment, delivery.record_id)
                if a:
                    a.reminder_sent_at = now
            elif delivery.kind == "result":
                s = db.get(Submission, delivery.record_id)
                if s:
                    s.result_sent_at = now

    async def deliver(self) -> int:
        deliveries = await asyncio.to_thread(self.collect_deliveries)
        sent = 0
        for d in deliveries:
            try:
                await self.hub.send(d.channel, d.chat_id, d.message)
                ok = True
            except ChannelSendError as exc:
                ok = exc.permanent  # lỗi vĩnh viễn (bị chặn...) -> đánh dấu để không gửi lại mãi
                log.warning("Không gửi được %s #%s: %s", d.kind, d.record_id, exc)
            except Exception:
                ok = False
                log.exception("Lỗi gửi %s #%s", d.kind, d.record_id)
            if ok:
                await asyncio.to_thread(self.mark_delivered, d)
                sent += 1
        return sent
