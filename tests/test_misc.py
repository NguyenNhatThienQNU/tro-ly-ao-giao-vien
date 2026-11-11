"""Nhập liệu Excel/CSV, tiện ích, migration CSDL."""

import io

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from openpyxl import Workbook
from sqlalchemy import create_engine

from app.db import Base
from app.migrate import alembic_config
from app.models import Topic
from app.services.importer import parse_score, parse_table
from app.utils.text import fmt_score, norm, split_text, to_ten


def test_parse_csv_with_semicolon_and_topic_columns():
    topics = [Topic(id=7, name="Xâu kí tự (string)"), Topic(id=8, name="Hàm trong Python")]
    data = "Mã HS;Họ và tên;Điểm;Xâu kí tự;hàm trong python\nHS1;An;8,5;7;9\n".encode()
    table = parse_table(data, "diem.csv", topics)
    assert set(table.mapping.values()) == {"student_code", "full_name", "score", "topic:7", "topic:8"}
    rec = table.records()[0]
    assert rec["full_name"] == "An" and parse_score(rec["score"]) == 8.5


def test_parse_xlsx_header_not_on_first_row():
    wb = Workbook()
    ws = wb.active
    ws.append(["Trường THPT ..."])
    ws.append([])
    ws.append(["STT", "Họ tên", "Ghi chú"])
    ws.append([1, "Phạm Thị C", "lớp trưởng"])
    buf = io.BytesIO()
    wb.save(buf)
    table = parse_table(buf.getvalue(), "ds.xlsx")
    assert table.records() == [{"full_name": "Phạm Thị C", "note": "lớp trưởng"}]


def test_text_helpers():
    assert norm("  Nguyễn   ĐỨC  ") == "nguyen duc"
    assert fmt_score(7.5) == "7,5" and fmt_score(8.0) == "8" and fmt_score(None) == "–"
    assert to_ten(6, 8) == 7.5
    chunks = split_text("a" * 50 + "\n" + "b" * 50, 60)
    assert len(chunks) == 2 and all(len(c) <= 60 for c in chunks)


def test_migrations_match_models(tmp_path, settings):
    url = f"sqlite:///{(tmp_path / 'mig.db').as_posix()}"
    settings.database_url = url
    command.upgrade(alembic_config(settings), "head")
    engine = create_engine(url)
    with engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    engine.dispose()
    assert diff == [], diff
