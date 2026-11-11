"""Cấu hình chung cho kiểm thử: CSDL SQLite tạm, AI chế độ demo, không bật chatbot."""

from __future__ import annotations

import re
from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.config import Settings
from app.db import Base, SessionLocal, get_engine
from app.main import create_app
from app.models import Teacher
from app.security import hash_password
from app.seed import seed_sample_data


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        _env_file=None,
        data_dir=tmp_path,
        secret_key="khoa-kiem-thu",
        ai_provider="mock",
        telegram_bot_token="",
        zalo_bot_token="",
        auto_migrate=False,
        worker_enabled=False,
    )


@pytest.fixture
def app(settings):
    application = create_app(settings, start_background=False)
    Base.metadata.create_all(get_engine())
    return application


@pytest.fixture
def db(app):
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture
def teacher(db) -> Teacher:
    t = Teacher(full_name="Cô Lan", email="lan@truong.vn", password_hash=hash_password("matkhau1"))
    db.add(t)
    db.commit()
    return t


@pytest.fixture
def sample(db, teacher, settings, app):
    """Lớp mẫu 10 học sinh, môn Tin học 10, có lịch sử 3 tuần."""
    classroom = seed_sample_data(db, teacher, settings, app.state.ai)
    db.commit()
    return classroom


def csrf_of(html: str) -> str:
    match = re.search(r'name="csrf-token" content="([^"]+)"', html) or re.search(
        r'name="csrf_token" value="([^"]+)"', html
    )
    assert match, "Không thấy CSRF token trong trang"
    return match.group(1)


def login(client: TestClient, email: str, password: str) -> None:
    token = csrf_of(client.get("/login").text)
    r = client.post("/login", data={"email": email, "password": password, "csrf_token": token}, follow_redirects=False)
    assert r.status_code == 303, r.text


@pytest.fixture
def client(app, teacher):
    with TestClient(app) as c:
        login(c, "lan@truong.vn", "matkhau1")
        c.csrf = csrf_of(c.get("/settings").text)
        yield c


def make_image(text: str = "bai lam") -> bytes:
    img = Image.new("RGB", (400, 300), "white")
    buf = BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()
