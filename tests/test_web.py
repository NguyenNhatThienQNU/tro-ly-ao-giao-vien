"""Kiểm thử giao diện web: đăng nhập, CSRF, quyền sở hữu, các luồng chính."""

import io
import re

from fastapi.testclient import TestClient
from openpyxl import Workbook

from app.models import Assignment, AssignmentStatus, Classroom, Student, Submission, SubmissionStatus, Teacher
from app.security import hash_password

from .conftest import csrf_of, login


def test_requires_login(app):
    with TestClient(app) as c:
        r = c.get("/dashboard", follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"] == "/login?next=/dashboard"
        assert c.get("/login", follow_redirects=False).headers["location"] == "/register"  # chưa có tài khoản nào
        assert c.post("/api/assistant/chat", json={"message": "hi"}).status_code in (401, 403)


def test_first_registration_then_closed(app):
    with TestClient(app) as c:
        token = csrf_of(c.get("/register").text)
        r = c.post(
            "/register",
            data={
                "full_name": "Thầy Thiện",
                "email": "t@x.vn",
                "password": "123456",
                "password2": "123456",
                "csrf_token": token,
            },
            follow_redirects=False,
        )
        assert r.status_code == 303
        assert "Chào" in c.get("/dashboard").text
    with TestClient(app) as c2:
        r = c2.get("/register", follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"] == "/login"


def test_csrf_is_enforced(client):
    r = client.post("/classes", data={"name": "10B", "new_subject": "Toán 10"})
    assert r.status_code == 403
    r = client.post(
        "/classes", data={"name": "10B", "new_subject": "Toán 10", "csrf_token": client.csrf}, follow_redirects=False
    )
    assert r.status_code == 303


def test_class_students_import_and_dashboard(client, db):
    r = client.post("/classes", data={"name": "10 TOÁN", "new_subject": "Tin học 10", "csrf_token": client.csrf})
    class_id = int(re.search(r"/classes/(\d+)/qr", r.text).group(1))
    client.post(f"/classes/{class_id}/students", data={"full_name": "Lê  Văn   Tám", "csrf_token": client.csrf})
    csv = "﻿STT;Họ và tên;Mã HS\n1;Nguyễn Văn An;HS01\n2;Trần Thị Bình;HS02\n".encode()
    client.post(
        f"/classes/{class_id}/import-students",
        files={"file": ("ds.csv", csv, "text/csv")},
        data={"csrf_token": client.csrf},
    )
    names = sorted(s.full_name for s in db.query(Student).filter_by(classroom_id=class_id))
    assert names == ["Lê Văn Tám", "Nguyễn Văn An", "Trần Thị Bình"]

    wb = Workbook()
    ws = wb.active
    ws.append(["BẢNG ĐIỂM KIỂM TRA"])
    ws.append(["Họ và tên", "Điểm"])
    ws.append(["Nguyễn Văn An", "8,5"])
    ws.append(["Không Tồn Tại", 7])
    buf = io.BytesIO()
    wb.save(buf)
    r = client.post(
        f"/classes/{class_id}/import-scores",
        files={"file": ("diem.xlsx", buf.getvalue())},
        data={"label": "KT 15p", "max_score": "10", "csrf_token": client.csrf},
    )
    assert "Đã lưu 1 đầu điểm" in r.text and "Không Tồn Tại" in r.text
    assert client.get(f"/dashboard?class_id={class_id}").status_code == 200
    assert client.get(f"/classes/{class_id}/qr").status_code == 200


def test_full_teacher_flow_on_sample(client, db, sample, settings):
    r = client.get("/dashboard")
    assert "Tổng quan lớp 10A1" in r.text and "Phạm Đức Duy" in r.text
    r = client.post(
        "/assignments/new",
        data={
            "class_id": sample.id,
            "title": "Ôn tập",
            "due_at": "2026-12-01T21:00",
            "num_questions": "3",
            "mode": "review",
            "csrf_token": client.csrf,
        },
    )
    assert "Đã tạo 10 bộ đề nháp" in r.text
    batch_id = int(re.search(r"/assignments/batches/(\d+)/approve", r.text).group(1))
    client.post(f"/assignments/batches/{batch_id}/approve", data={"csrf_token": client.csrf})
    approved = db.query(Assignment).filter_by(batch_id=batch_id).all()
    assert all(a.status == AssignmentStatus.ASSIGNED for a in approved)
    assert client.get(f"/bai/{approved[0].access_token}").status_code == 200

    # bài mẫu chờ AI chấm -> chấm bằng chế độ demo rồi xác nhận
    from app.worker import BackgroundWorker

    BackgroundWorker(settings, client.app.state.ai, client.app.state.hub).grade_pending()
    db.expire_all()
    sub = db.query(Submission).filter_by(status=SubmissionStatus.AI_GRADED).one()
    page = client.get(f"/grading/{sub.id}")
    assert page.status_code == 200 and "Xác nhận" in page.text
    image_id = sub.images[0].id
    assert client.get(f"/media/images/{image_id}").headers["content-type"] == "image/jpeg"
    form = {f"score_{g.id}": str(g.max_score) for g in sub.grades}
    form.update(csrf_token=client.csrf, teacher_comment="Làm tốt")
    client.post(f"/grading/{sub.id}/confirm", data=form)
    db.expire_all()
    sub = db.get(Submission, sub.id)
    assert sub.status == SubmissionStatus.CONFIRMED and sub.final_total == sub.max_total

    r = client.post(
        "/api/assistant/chat", json={"message": "Có bài nào chờ chấm không?"}, headers={"X-CSRF-Token": client.csrf}
    )
    assert r.status_code == 200 and "reply" in r.json()
    for url in (
        "/classes",
        "/subjects",
        "/bank",
        "/assignments",
        "/grading?status=all",
        "/assistant",
        "/settings",
        f"/students/{sample.students[0].id}",
    ):
        assert client.get(url).status_code == 200, url


def test_other_teacher_cannot_access(client, db, sample):
    other = Teacher(full_name="GV khác", email="khac@x.vn", password_hash=hash_password("123456"))
    db.add(other)
    db.commit()
    with TestClient(client.app) as c2:
        login(c2, "khac@x.vn", "123456")
        assert c2.get(f"/classes/{sample.id}").status_code == 404
        assert c2.get(f"/students/{sample.students[0].id}").status_code == 404
        sub_id = db.query(Submission).first().id
        assert c2.get(f"/grading/{sub_id}").status_code == 404
        assert "10A1" not in c2.get("/dashboard").text


def test_draft_assignment_not_public(client, db, sample):
    draft = Assignment(
        classroom_id=sample.id, student_id=sample.students[0].id, title="Nháp", status=AssignmentStatus.DRAFT
    )
    db.add(draft)
    db.commit()
    assert client.get(f"/bai/{draft.access_token}").status_code == 404
    assert db.query(Classroom).count() == 1


def test_qr_sheet_with_telegram_bot(client, sample):
    from app.channels.base import ChannelAdapter

    class FakeTelegram(ChannelAdapter):
        name = "telegram"
        username = "lop10a1_bot"

        async def start(self): ...

        async def stop(self): ...

        async def send(self, chat_id, message): ...

        def link_url(self, link_code):
            return f"https://t.me/{self.username}?start={link_code}"

    client.app.state.hub.register(FakeTelegram())
    page = client.get(f"/classes/{sample.id}/qr").text
    assert page.count("<svg") == len(sample.students) and "@lop10a1_bot" in page
