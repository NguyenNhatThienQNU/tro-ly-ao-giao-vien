"""Cấu hình ứng dụng, đọc từ biến môi trường hoặc tệp .env ở thư mục gốc dự án."""

from __future__ import annotations

import secrets
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Chung ---
    app_name: str = "Trợ lý ảo Giáo viên"
    secret_key: str = ""  # để trống: tự sinh và lưu vào data/.secret_key
    data_dir: Path = BASE_DIR / "data"
    database_url: str = ""  # để trống: SQLite tại data/app.db
    timezone: str = "Asia/Ho_Chi_Minh"
    public_base_url: str = "http://localhost:8000"
    allow_registration: bool = False  # tài khoản đầu tiên luôn được phép đăng ký
    auto_migrate: bool = True  # tự chạy Alembic khi khởi động

    # --- AI ---
    ai_provider: str = "auto"  # auto | gemini | mock
    gemini_api_key: str = ""
    gemini_model: str = "gemini-flash-latest"
    ai_timeout_seconds: int = 180

    # --- Telegram ---
    telegram_bot_token: str = ""
    telegram_mode: str = "polling"  # polling | webhook | off
    telegram_webhook_secret: str = ""

    # --- Zalo Bot (thử nghiệm) ---
    zalo_bot_token: str = ""
    zalo_mode: str = "polling"  # polling | webhook | off
    zalo_webhook_secret: str = ""
    zalo_bot_link: str = ""  # đường dẫn mở bot Zalo (lấy trên Zalo Bot Platform)

    # --- Tác vụ nền ---
    worker_enabled: bool = True
    worker_interval_seconds: float = 5.0
    reminder_hours_before: int = 12
    max_grading_attempts: int = 3
    low_confidence_threshold: float = 0.6

    # ------------------------------------------------------------------
    @property
    def upload_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def resolved_database_url(self) -> str:
        if self.database_url:
            return self.database_url
        return f"sqlite:///{(self.data_dir / 'app.db').as_posix()}"

    @property
    def effective_ai_provider(self) -> str:
        provider = self.ai_provider.strip().lower()
        if provider == "auto":
            return "gemini" if self.gemini_api_key else "mock"
        return provider

    @property
    def telegram_enabled(self) -> bool:
        return bool(self.telegram_bot_token) and self.telegram_mode != "off"

    @property
    def zalo_enabled(self) -> bool:
        return bool(self.zalo_bot_token) and self.zalo_mode != "off"

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.upload_dir.mkdir(parents=True, exist_ok=True)

    def get_secret_key(self) -> str:
        """Khóa ký phiên đăng nhập. Nếu chưa cấu hình thì sinh một lần và lưu lại."""
        if self.secret_key:
            return self.secret_key
        self.ensure_dirs()
        key_file = self.data_dir / ".secret_key"
        if key_file.exists():
            return key_file.read_text(encoding="utf-8").strip()
        key = secrets.token_urlsafe(48)
        key_file.write_text(key, encoding="utf-8")
        return key


@lru_cache
def get_settings() -> Settings:
    return Settings()
