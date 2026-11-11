"""Nhập danh sách học sinh và bảng điểm từ tệp Excel (.xlsx) hoặc CSV."""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field

from openpyxl import load_workbook
from sqlalchemy.orm import Session

from ..models import Classroom, ScoreRecord, Student, Topic
from ..utils.text import norm, norm_key
from .students import add_student, match_students

HEADER_ALIASES: dict[str, set[str]] = {
    "full_name": {
        "hoten",
        "hovaten",
        "ten",
        "hotenhocsinh",
        "hovatenhocsinh",
        "hocsinh",
        "name",
        "fullname",
        "tenhocsinh",
    },
    "student_code": {"mahs", "mahocsinh", "ma", "mshs", "msv", "mssv", "code", "studentcode", "maso"},
    "score": {"diem", "diemso", "tongdiem", "diemtb", "dtb", "diemtrungbinh", "score", "diemkiemtra"},
    "note": {"ghichu", "note", "nhanxet"},
}
MAX_ROWS = 2000


class ImportFormatError(ValueError):
    pass


@dataclass
class TableData:
    headers: list[str]
    rows: list[list[str]]
    mapping: dict[int, str]  # chỉ số cột -> trường (full_name, student_code, score, note, topic:<id>)

    def records(self) -> list[dict[str, str]]:
        out = []
        for row in self.rows:
            rec = {}
            for idx, key in self.mapping.items():
                rec[key] = row[idx].strip() if idx < len(row) and row[idx] is not None else ""
            out.append(rec)
        return out

    def to_text(self, limit: int = 200) -> str:
        """Dạng văn bản (để dán vào khung chat trợ lý)."""
        lines = ["\t".join(self.headers)]
        lines += ["\t".join(cell for cell in row) for row in self.rows[:limit]]
        return "\n".join(lines)


@dataclass
class ImportReport:
    created: int = 0
    skipped: int = 0
    records: int = 0
    unmatched: list[str] = field(default_factory=list)
    ambiguous: list[str] = field(default_factory=list)


def _cell(value) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _decode(data: bytes) -> str:
    for encoding in ("utf-8-sig", "cp1258", "cp1252"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ImportFormatError("Không đọc được bảng mã của tệp CSV. Hãy lưu tệp dạng 'CSV UTF-8'.")


def read_rows(data: bytes, filename: str) -> list[list[str]]:
    name = (filename or "").lower()
    if name.endswith((".xlsx", ".xlsm")):
        try:
            wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        except Exception as exc:  # openpyxl ném nhiều loại lỗi khác nhau
            raise ImportFormatError("Không mở được tệp Excel.") from exc
        ws = wb.active
        rows = [[_cell(v) for v in row] for row in ws.iter_rows(values_only=True)]
        wb.close()
    elif name.endswith((".csv", ".txt", ".tsv")):
        text = _decode(data)
        try:
            dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
        except csv.Error:
            dialect = csv.excel
        rows = [[c.strip() for c in row] for row in csv.reader(io.StringIO(text), dialect)]
    else:
        raise ImportFormatError("Chỉ hỗ trợ tệp .xlsx hoặc .csv.")
    rows = [r for r in rows if any(c.strip() for c in r)]
    if len(rows) > MAX_ROWS:
        raise ImportFormatError(f"Tệp quá lớn (tối đa {MAX_ROWS} dòng).")
    return rows


def _match_topic(header: str, topics: list[Topic]) -> Topic | None:
    key = norm(header)
    if not key:
        return None
    for topic in topics:
        if norm(topic.name) == key:
            return topic
    for topic in topics:
        if key in norm(topic.name) or norm(topic.name) in key:
            return topic
    return None


def parse_table(data: bytes, filename: str, topics: list[Topic] | None = None) -> TableData:
    rows = read_rows(data, filename)
    if not rows:
        raise ImportFormatError("Tệp không có dữ liệu.")
    topics = topics or []
    for header_idx, header_row in enumerate(rows[:10]):
        mapping: dict[int, str] = {}
        for col, header in enumerate(header_row):
            key = norm_key(header)
            for field_name, aliases in HEADER_ALIASES.items():
                if key in aliases and field_name not in mapping.values():
                    mapping[col] = field_name
                    break
            else:
                topic = _match_topic(header, topics)
                if topic is not None:
                    mapping[col] = f"topic:{topic.id}"
        if "full_name" in mapping.values() or "student_code" in mapping.values():
            width = len(header_row)
            body = [(r + [""] * width)[:width] for r in rows[header_idx + 1 :]]
            return TableData(headers=[h for h in header_row], rows=body, mapping=mapping)
    raise ImportFormatError("Không tìm thấy cột 'Họ và tên' hoặc 'Mã HS' trong 10 dòng đầu.")


def parse_score(value: str | None) -> float | None:
    text = (value or "").strip().replace(",", ".")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def import_students(db: Session, classroom: Classroom, table: TableData) -> ImportReport:
    report = ImportReport()
    existing = {(norm(s.full_name), norm(s.student_code)) for s in classroom.students}
    for rec in table.records():
        name = rec.get("full_name", "")
        code = rec.get("student_code", "")
        if not name:
            report.skipped += 1
            continue
        key = (norm(name), norm(code))
        if key in existing:
            report.skipped += 1
            continue
        add_student(db, classroom, name, code, rec.get("note", ""))
        existing.add(key)
        report.created += 1
    db.refresh(classroom)
    return report


def import_scores(
    db: Session, classroom: Classroom, table: TableData, label: str, max_score: float = 10.0
) -> ImportReport:
    report = ImportReport()
    students: list[Student] = list(classroom.students)
    for rec in table.records():
        query = rec.get("student_code") or rec.get("full_name") or ""
        if not query:
            continue
        found = match_students(students, rec.get("student_code", "")) if rec.get("student_code") else []
        if len(found) != 1:
            found = match_students(students, rec.get("full_name", ""))
        if not found:
            report.unmatched.append(rec.get("full_name") or query)
            continue
        if len(found) > 1:
            report.ambiguous.append(rec.get("full_name") or query)
            continue
        student = found[0]
        for key, value in rec.items():
            score = parse_score(value)
            if score is None:
                continue
            if key == "score":
                topic_id = None
            elif key.startswith("topic:"):
                topic_id = int(key.split(":", 1)[1])
            else:
                continue
            db.add(
                ScoreRecord(
                    student_id=student.id,
                    topic_id=topic_id,
                    label=label,
                    score=max(0.0, min(score, max_score)),
                    max_score=max_score,
                    source="import",
                )
            )
            report.records += 1
    db.flush()
    return report
