"""Công cụ dòng lệnh quản trị.

python -m app.cli init-db                      Tạo/cập nhật CSDL
python -m app.cli create-teacher --name "Nguyễn Văn A" --email a@truong.edu.vn --password matkhau
python -m app.cli reset-password --email a@truong.edu.vn --password matkhaumoi
python -m app.cli seed-demo                    Tạo tài khoản demo + dữ liệu mẫu Tin học 10
"""

from __future__ import annotations

import argparse
import sys

from sqlalchemy import func, select

from .ai import build_provider
from .config import get_settings
from .db import init_engine, session_scope
from .migrate import upgrade_database
from .models import Teacher
from .security import hash_password
from .utils.timeutil import set_default_timezone


def _find_teacher(db, email: str) -> Teacher | None:
    return db.scalar(select(Teacher).where(func.lower(Teacher.email) == email.strip().lower()))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli", description="Quản trị Trợ lý ảo Giáo viên")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init-db", help="Tạo/cập nhật cấu trúc CSDL")
    p = sub.add_parser("create-teacher", help="Tạo tài khoản giáo viên")
    p.add_argument("--name", required=True)
    p.add_argument("--email", required=True)
    p.add_argument("--password", required=True)
    p = sub.add_parser("reset-password", help="Đặt lại mật khẩu")
    p.add_argument("--email", required=True)
    p.add_argument("--password", required=True)
    p = sub.add_parser("seed-demo", help="Tạo tài khoản demo kèm dữ liệu mẫu")
    p.add_argument("--email", default="demo@truonghoc.vn")
    p.add_argument("--password", default="demo1234")
    p.add_argument("--name", default="Giáo viên Demo")
    p.add_argument("--grade", type=int, default=10, choices=[10, 11], help="Khối lớp (10 hoặc 11)")
    args = parser.parse_args(argv)

    settings = get_settings()
    settings.ensure_dirs()
    set_default_timezone(settings.timezone)
    upgrade_database(settings)
    init_engine(settings.resolved_database_url)

    if args.command == "init-db":
        print("✔ Đã cập nhật cấu trúc CSDL:", settings.resolved_database_url.split("://")[0])
        return 0

    with session_scope() as db:
        if args.command == "create-teacher":
            if len(args.password) < 6:
                print("✘ Mật khẩu tối thiểu 6 ký tự.")
                return 1
            if _find_teacher(db, args.email):
                print("✘ Email đã tồn tại.")
                return 1
            db.add(
                Teacher(
                    full_name=args.name, email=args.email.strip().lower(), password_hash=hash_password(args.password)
                )
            )
            print(f"✔ Đã tạo tài khoản {args.email}")
            return 0

        if args.command == "reset-password":
            teacher = _find_teacher(db, args.email)
            if teacher is None:
                print("✘ Không tìm thấy tài khoản.")
                return 1
            teacher.password_hash = hash_password(args.password)
            print("✔ Đã đặt lại mật khẩu.")
            return 0

        if args.command == "seed-demo":
            from .seed import seed_sample_data

            teacher = _find_teacher(db, args.email)
            if teacher is not None:
                print(f"• Tài khoản {args.email} đã có – bỏ qua (xóa tệp data/app.db nếu muốn tạo lại từ đầu).")
                return 0
            teacher = Teacher(full_name=args.name, email=args.email.lower(), password_hash=hash_password(args.password))
            db.add(teacher)
            db.flush()
            classroom = seed_sample_data(db, teacher, settings, build_provider(settings), grade=args.grade)
            print(f"✔ Đã tạo dữ liệu mẫu (lớp {classroom.name}).")
            print(f"  Đăng nhập: {args.email} / {args.password}")
            return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
