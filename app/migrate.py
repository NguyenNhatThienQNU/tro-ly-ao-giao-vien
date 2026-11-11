"""Chạy Alembic migration bằng mã (dùng khi khởi động và trong lệnh init-db)."""

from __future__ import annotations

from alembic import command
from alembic.config import Config

from .config import BASE_DIR, Settings


def alembic_config(settings: Settings) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(BASE_DIR / "migrations"))
    cfg.set_main_option("sqlalchemy.url", settings.resolved_database_url.replace("%", "%%"))
    return cfg


def upgrade_database(settings: Settings) -> None:
    settings.ensure_dirs()
    command.upgrade(alembic_config(settings), "head")
