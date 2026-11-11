"""Môi trường Alembic: dùng chung cấu hình CSDL với ứng dụng."""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool

from app import models  # noqa: F401 - nạp toàn bộ bảng vào metadata
from app.config import get_settings
from app.db import Base

config = context.config

# Chỉ cấu hình logging khi chạy bằng lệnh `alembic` (có alembic.ini),
# tránh ghi đè cấu hình log của máy chủ web khi migrate tự động.
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

url = config.get_main_option("sqlalchemy.url") or get_settings().resolved_database_url
target_metadata = Base.metadata
is_sqlite = url.startswith("sqlite")


def run_migrations_offline() -> None:
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=is_sqlite,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    if is_sqlite and url.startswith("sqlite:///"):
        from pathlib import Path

        db_path = url.removeprefix("sqlite:///")
        if db_path and db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(url, poolclass=NullPool)
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=is_sqlite,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
