"""Đăng nhập, đăng ký, đăng xuất."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import Teacher
from ..security import hash_password, verify_password
from .deps import flash, get_db, redirect, render, verify_csrf

router = APIRouter(dependencies=[Depends(verify_csrf)])


def safe_next(url: str | None) -> str:
    if url and url.startswith("/") and not url.startswith("//"):
        return url
    return "/dashboard"


def _registration_open(request: Request, db: Session) -> bool:
    has_teacher = (db.scalar(select(func.count(Teacher.id))) or 0) > 0
    return not has_teacher or request.app.state.settings.allow_registration


@router.get("/login")
def login_page(request: Request, next: str = "/dashboard", db: Session = Depends(get_db)):
    if request.session.get("teacher_id"):
        return redirect(safe_next(next))
    if (db.scalar(select(func.count(Teacher.id))) or 0) == 0:
        flash(
            request,
            "Hệ thống chưa có tài khoản nào được lưu (hoặc máy chủ vừa khởi tạo lại). Vui lòng thiết lập tài khoản giáo viên quản trị.",
            "info",
        )
        return redirect("/register")
    return render(request, "login.html", next=safe_next(next), registration_open=_registration_open(request, db))


@router.post("/login")
def login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    next: str = Form("/dashboard"),
    db: Session = Depends(get_db),
):
    teacher = db.scalar(select(Teacher).where(func.lower(Teacher.email) == email.strip().lower()))
    if teacher is None or not verify_password(password, teacher.password_hash):
        return render(
            request,
            "login.html",
            error="Email hoặc mật khẩu không đúng.",
            email=email,
            next=safe_next(next),
            registration_open=_registration_open(request, db),
            status_code=400,
        )
    request.session.clear()
    request.session["teacher_id"] = teacher.id
    return redirect(safe_next(next))


@router.get("/register")
def register_page(request: Request, db: Session = Depends(get_db)):
    if not _registration_open(request, db):
        flash(request, "Hệ thống chưa mở đăng ký. Liên hệ quản trị để được cấp tài khoản.", "warning")
        return redirect("/login")
    first = (db.scalar(select(func.count(Teacher.id))) or 0) == 0
    return render(request, "register.html", first=first)


@router.post("/register")
def register(
    request: Request,
    full_name: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    password2: str = Form(...),
    db: Session = Depends(get_db),
):
    if not _registration_open(request, db):
        return redirect("/login")
    email = email.strip().lower()
    full_name = " ".join(full_name.split())
    errors = []
    if not full_name:
        errors.append("Vui lòng nhập họ tên.")
    if "@" not in email:
        errors.append("Email không hợp lệ.")
    if len(password) < 6:
        errors.append("Mật khẩu tối thiểu 6 ký tự.")
    if password != password2:
        errors.append("Mật khẩu nhập lại không khớp.")
    if db.scalar(select(Teacher.id).where(func.lower(Teacher.email) == email)):
        errors.append("Email đã được sử dụng.")
    if errors:
        first = (db.scalar(select(func.count(Teacher.id))) or 0) == 0
        return render(
            request, "register.html", errors=errors, full_name=full_name, email=email, first=first, status_code=400
        )
    teacher = Teacher(full_name=full_name, email=email, password_hash=hash_password(password))
    db.add(teacher)
    db.commit()
    request.session.clear()
    request.session["teacher_id"] = teacher.id
    flash(request, f"Chào mừng {teacher.full_name}! Hãy bắt đầu bằng cách tạo môn học và lớp.")
    return redirect("/dashboard")


@router.post("/logout")
def logout(request: Request):
    request.session.clear()
    return redirect("/login")
