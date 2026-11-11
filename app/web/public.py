"""Trang công khai: xem đề (cho học sinh), webhook chatbot, kiểm tra sức khỏe máy chủ."""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Assignment, AssignmentStatus
from ..security import tokens_match
from .deps import get_db, templates

router = APIRouter()
log = logging.getLogger(__name__)
_background: set[asyncio.Task] = set()


@router.get("/healthz")
def healthz():
    return {"status": "ok"}


@router.get("/bai/{token}")
def public_assignment(request: Request, token: str, db: Session = Depends(get_db)):
    assignment = db.scalar(select(Assignment).where(Assignment.access_token == token))
    if assignment is None or assignment.status in (AssignmentStatus.DRAFT, AssignmentStatus.CANCELLED):
        raise HTTPException(status_code=404, detail="Không tìm thấy bài.")
    return templates.TemplateResponse(
        request,
        "public/assignment.html",
        {"a": assignment, "app_name": request.app.state.settings.app_name},
    )


def _spawn(coro) -> None:
    task = asyncio.create_task(coro)
    _background.add(task)
    task.add_done_callback(_background.discard)


@router.post("/webhooks/telegram")
async def telegram_webhook(request: Request):
    settings = request.app.state.settings
    adapter = request.app.state.hub.get("telegram")
    if adapter is None or settings.telegram_mode != "webhook":
        raise HTTPException(status_code=404)
    if not tokens_match(request.headers.get("x-telegram-bot-api-secret-token"), settings.telegram_webhook_secret):
        raise HTTPException(status_code=403)
    update = await request.json()
    _spawn(adapter.process_update(update))  # trả lời Telegram ngay, xử lý ở nền
    return {"ok": True}


@router.post("/webhooks/zalo")
async def zalo_webhook(request: Request):
    settings = request.app.state.settings
    adapter = request.app.state.hub.get("zalo")
    if adapter is None or settings.zalo_mode != "webhook":
        raise HTTPException(status_code=404)
    if not tokens_match(request.headers.get("x-bot-api-secret-token"), settings.zalo_webhook_secret):
        raise HTTPException(status_code=403)
    update = await request.json()
    _spawn(adapter.process_update(update))
    return {"ok": True}
