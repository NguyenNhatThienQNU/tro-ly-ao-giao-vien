"""Kịch bản chatbot học sinh, tác vụ nền gửi tin, adapter Telegram/Zalo (giả lập HTTP)."""

import asyncio
import json
from datetime import timedelta

import httpx

from app.ai.mock import MockProvider
from app.channels.base import ChannelAdapter, ChannelHub, ChannelSendError
from app.channels.bot_logic import StudentBot
from app.channels.telegram import TelegramAdapter
from app.channels.zalo import ZaloAdapter
from app.models import Assignment, AssignmentStatus, Student, Submission, SubmissionStatus
from app.services import assignments as service
from app.services import grading
from app.utils.timeutil import utcnow
from app.worker import BackgroundWorker

from .conftest import make_image


def _student(db, sample, name="Võ Thanh Hà") -> Student:
    """Học sinh trong lớp mẫu, đã hủy bài đang mở của dữ liệu mẫu để kịch bản rõ ràng."""
    student = next(s for s in sample.students if s.full_name == name)
    for a in student.assignments:
        if a.status == AssignmentStatus.ASSIGNED:
            a.status = AssignmentStatus.CANCELLED
    db.commit()
    return student


def _assign(db, sample, student, title="Bài A", due=None) -> Assignment:
    a = service.create_batch(
        db, sample, title=title, due_at=due, student_ids=[student.id], num_questions=2
    ).batch.assignments[0]
    service.approve_assignment(db, a)
    db.commit()
    return a


def test_link_flow(db, sample, settings):
    bot = StudentBot(settings)
    student = _student(db, sample)
    assert "không đúng" in bot.handle_text("telegram", "111", "Hà", "/start SAIMA123")[0].text
    reply = bot.handle_text("telegram", "111", "Hà", f"/start {student.link_code}")[0].text
    assert "liên kết thành công" in reply and student.full_name in reply
    assert "đã liên kết rồi" in bot.handle_text("telegram", "111", "Hà", f"/start {student.link_code}")[0].text
    # tài khoản khác dùng lại mã -> bị từ chối
    assert "tài khoản khác" in bot.handle_text("telegram", "222", "X", student.link_code.lower())[0].text
    # cùng tài khoản liên kết sang học sinh khác -> chuyển liên kết
    other = _student(db, sample, "Trần Gia Bảo")
    bot.handle_text("telegram", "111", "Hà", other.link_code)
    db.expire_all()
    assert db.get(Student, student.id).chat_id is None and db.get(Student, other.id).chat_id == "111"


def test_unlinked_student_gets_instructions(settings, sample):
    bot = StudentBot(settings)
    assert "chưa liên kết" in bot.handle_text("zalo", "999", "", "xin chao")[0].text
    assert "chưa liên kết" in bot.handle_image("zalo", "999", "", make_image(), "image/jpeg").messages[0].text


def test_photo_submission_flow(db, sample, settings):
    bot = StudentBot(settings)
    student = _student(db, sample)
    bot.handle_text("telegram", "111", "Hà", f"/start {student.link_code}")
    assert "không có bài" in bot.handle_image("telegram", "111", "Hà", make_image(), "image/jpeg").messages[0].text
    a = _assign(db, sample, student)
    assert bot.handle_image("telegram", "111", "Hà", make_image(), "image/jpeg").schedule_ack
    assert bot.handle_image("telegram", "111", "Hà", make_image(), "image/jpeg").schedule_ack
    status = bot.collecting_status("telegram", "111")[0]
    assert "Đã nhận 2 ảnh" in status.text and status.buttons
    reply = bot.handle_text("telegram", "111", "Hà", "nop")[0].text
    assert "Đã nộp bài" in reply
    db.expire_all()
    sub = db.query(Submission).filter_by(assignment_id=a.id).one()
    assert sub.status == SubmissionStatus.SUBMITTED and len(sub.images) == 2
    assert db.get(Assignment, a.id).status == AssignmentStatus.SUBMITTED


def test_pick_assignment_when_several_open(db, sample, settings):
    bot = StudentBot(settings)
    student = _student(db, sample)
    bot.handle_text("telegram", "111", "Hà", f"/start {student.link_code}")
    _assign(db, sample, student, "Bài A", utcnow() + timedelta(days=1))
    b = _assign(db, sample, student, "Bài B", utcnow() + timedelta(days=2))
    bot.handle_image("telegram", "111", "Hà", make_image(), "image/jpeg")
    prompt = bot.collecting_status("telegram", "111")[0]
    assert "thuộc bài nào" in prompt.text and "2. Bài B" in prompt.text
    assert "Bài B" in bot.handle_text("telegram", "111", "Hà", "2")[0].text
    assert "Đã nộp bài «Bài B»" in bot.handle_action("telegram", "111", "submit")[0].text
    db.expire_all()
    assert db.get(Assignment, b.id).status == AssignmentStatus.SUBMITTED


def test_cancel_and_commands(db, sample, settings):
    bot = StudentBot(settings)
    student = _student(db, sample)
    bot.handle_text("zalo", "555", "Hà", student.link_code)
    _assign(db, sample, student)
    bot.handle_image("zalo", "555", "Hà", make_image(), "image/jpeg")
    assert "Đã hủy 1 ảnh" in bot.handle_text("zalo", "555", "Hà", "HUY")[0].text
    assert "Bài đang cần làm" in bot.handle_text("zalo", "555", "Hà", "baitap")[0].text
    assert "Kết quả gần đây" in bot.handle_text("zalo", "555", "Hà", "/ketqua")[0].text
    assert "Mức nắm vững" in bot.handle_text("zalo", "555", "Hà", "tien do")[0].text


class FakeChannel(ChannelAdapter):
    name = "telegram"

    def __init__(self, fail_permanent=False):
        self.sent: list[tuple[str, str]] = []
        self.fail_permanent = fail_permanent

    async def start(self): ...

    async def stop(self): ...

    async def send(self, chat_id, message):
        if self.fail_permanent:
            raise ChannelSendError("bot bị chặn", permanent=True)
        self.sent.append((chat_id, message.text))


def test_worker_grades_and_delivers(db, sample, settings):
    bot = StudentBot(settings)
    student = _student(db, sample)
    bot.handle_text("telegram", "111", "Hà", f"/start {student.link_code}")
    a = _assign(db, sample, student, due=utcnow() + timedelta(hours=3))
    hub = ChannelHub()
    channel = FakeChannel()
    hub.register(channel)
    worker = BackgroundWorker(settings, MockProvider(), hub)

    asyncio.run(worker.deliver())
    assert any("BÀI MỚI" in text for _, text in channel.sent)
    db.expire_all()
    assert db.get(Assignment, a.id).sent_at is not None
    channel.sent.clear()
    asyncio.run(worker.deliver())
    assert channel.sent == []  # không gửi trùng; bài vừa gửi đã trong khung nhắc nên không nhắc ngay

    bot.handle_image("telegram", "111", "Hà", make_image(), "image/jpeg")
    bot.handle_text("telegram", "111", "Hà", "NOP")
    assert worker.grade_pending() >= 1  # (kèm bài mẫu có sẵn trong dữ liệu mẫu)
    db.expire_all()
    sub = db.query(Submission).filter_by(assignment_id=a.id).one()
    assert sub.status == SubmissionStatus.AI_GRADED
    grading.confirm_submission(db, sub, {}, teacher_comment="Tốt lắm")
    db.commit()
    asyncio.run(worker.deliver())
    assert any("KẾT QUẢ" in text and "Tốt lắm" in text for _, text in channel.sent)


def test_worker_reminder_and_permanent_failure(db, sample, settings):
    bot = StudentBot(settings)
    student = _student(db, sample)
    bot.handle_text("telegram", "111", "Hà", f"/start {student.link_code}")
    a = _assign(db, sample, student, due=utcnow() + timedelta(hours=5))
    a.sent_at = utcnow() - timedelta(days=1)
    db.commit()
    hub = ChannelHub()
    channel = FakeChannel()
    hub.register(channel)
    asyncio.run(BackgroundWorker(settings, MockProvider(), hub).deliver())
    assert any("Nhắc hạn" in text for _, text in channel.sent)

    b = _assign(db, sample, student, "Bài C")
    hub2 = ChannelHub()
    hub2.register(FakeChannel(fail_permanent=True))
    asyncio.run(BackgroundWorker(settings, MockProvider(), hub2).deliver())
    db.expire_all()
    assert db.get(Assignment, b.id).sent_at is not None  # lỗi vĩnh viễn -> không thử lại mãi


def _mock_transport(log, extra=None):
    def handler(request: httpx.Request):
        path = request.url.path
        body = json.loads(request.content) if request.content else {}
        log.append((path.rsplit("/", 1)[-1], body))
        if path.endswith("/getFile"):
            return httpx.Response(200, json={"ok": True, "result": {"file_path": "photos/a.jpg"}})
        if "/file/" in path or path.endswith(".jpg"):
            return httpx.Response(200, content=make_image(), headers={"content-type": "image/jpeg"})
        if extra and path.rsplit("/", 1)[-1] in extra:
            return httpx.Response(200, json=extra[path.rsplit("/", 1)[-1]])
        return httpx.Response(200, json={"ok": True, "result": {}})

    return httpx.MockTransport(handler)


def test_telegram_adapter_end_to_end(db, sample, settings):
    student = _student(db, sample)
    _assign(db, sample, student)
    log: list = []
    adapter = TelegramAdapter(
        "TOKEN", StudentBot(settings), client=httpx.AsyncClient(transport=_mock_transport(log)), ack_delay=0
    )
    adapter.username = "lop10_bot"
    assert adapter.link_url(student.link_code) == f"https://t.me/lop10_bot?start={student.link_code}"

    async def scenario():
        chat = {"id": 777, "type": "private"}
        await adapter.process_update(
            {
                "update_id": 1,
                "message": {"chat": chat, "from": {"first_name": "Hà"}, "text": f"/start {student.link_code}"},
            }
        )
        await adapter.process_update(
            {"update_id": 2, "message": {"chat": chat, "photo": [{"file_id": "small"}, {"file_id": "big"}]}}
        )
        await asyncio.sleep(0.05)
        await adapter.process_update(
            {"update_id": 3, "callback_query": {"id": "cb1", "data": "submit", "message": {"chat": chat}}}
        )

    asyncio.run(scenario())
    methods = [m for m, _ in log]
    texts = [b.get("text", "") for m, b in log if m == "sendMessage"]
    assert any("liên kết thành công" in t for t in texts)
    assert ("getFile", {"file_id": "big"}) in log
    ack = next(b for m, b in log if m == "sendMessage" and "Đã nhận 1 ảnh" in b.get("text", ""))
    assert ack["reply_markup"]["inline_keyboard"][0][0]["callback_data"] == "submit"
    assert "answerCallbackQuery" in methods and any("Đã nộp bài" in t for t in texts)


def test_zalo_adapter_text_and_image(db, sample, settings):
    student = _student(db, sample)
    _assign(db, sample, student)
    log: list = []
    adapter = ZaloAdapter(
        "TOKEN", StudentBot(settings), client=httpx.AsyncClient(transport=_mock_transport(log)), ack_delay=0
    )

    async def scenario():
        base = {"chat": {"id": "z1", "chat_type": "PRIVATE"}, "from": {"id": "z1", "display_name": "Hà"}}
        await adapter.process_update(
            {"event_name": "message.text.received", "message": {**base, "text": student.link_code}}
        )
        await adapter.process_update(
            {
                "ok": True,
                "result": {
                    "event_name": "message.image.received",
                    "message": {**base, "photo_url": "https://zalo.example/a.jpg"},
                },
            }
        )
        await asyncio.sleep(0.05)
        await adapter.process_update({"event_name": "message.text.received", "message": {**base, "text": "NOP"}})

    asyncio.run(scenario())
    texts = [b.get("text", "") for m, b in log if m == "sendMessage"]
    assert any("liên kết thành công" in t for t in texts)
    assert any("Đã nhận 1 ảnh" in t and "gõ NOP" in t for t in texts)
    assert any("Đã nộp bài" in t for t in texts)
    assert all("reply_markup" not in b for m, b in log if m == "sendMessage")  # Zalo không có nút bấm
