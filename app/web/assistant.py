"""Trợ lý AI cho giáo viên (giao diện chat)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Request, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..ai.assistant import AssistantService
from ..models import AssistantMessage, Teacher
from ..services import importer
from .deps import current_teacher, get_db, render, teacher_classes, verify_csrf

router = APIRouter(dependencies=[Depends(verify_csrf)])


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=8000)


@router.get("/assistant")
def page(request: Request, db: Session = Depends(get_db), teacher: Teacher = Depends(current_teacher)):
    history = db.scalars(
        select(AssistantMessage)
        .where(AssistantMessage.teacher_id == teacher.id)
        .order_by(AssistantMessage.id.desc())
        .limit(40)
    ).all()
    classes = teacher_classes(db, teacher)
    return render(
        request,
        "assistant.html",
        db=db,
        teacher=teacher,
        active="assistant",
        history=list(reversed(history)),
        classes=classes,
    )


@router.post("/api/assistant/chat")
def chat(request: Request, payload: ChatIn, db: Session = Depends(get_db), teacher: Teacher = Depends(current_teacher)):
    service = AssistantService(db, teacher, request.app.state.ai, request.app.state.settings)
    reply = service.chat(payload.message)
    return {"reply": reply.text, "actions": reply.actions}


@router.post("/api/assistant/upload")
async def upload(file: UploadFile = File(...), teacher: Teacher = Depends(current_teacher)):
    """Đọc bảng điểm Excel/CSV thành văn bản để dán vào khung chat."""
    data = await file.read(2 * 1024 * 1024 + 1)
    if len(data) > 2 * 1024 * 1024:
        return {"ok": False, "error": "Tệp quá lớn (tối đa 2 MB)."}
    try:
        try:
            table = importer.parse_table(data, file.filename or "")
            text = table.to_text()
        except importer.ImportFormatError:
            rows = importer.read_rows(data, file.filename or "")
            text = "\n".join("\t".join(r) for r in rows[:200])
    except importer.ImportFormatError as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "text": text, "filename": file.filename}


@router.post("/api/assistant/clear")
def clear(db: Session = Depends(get_db), teacher: Teacher = Depends(current_teacher)):
    db.execute(delete(AssistantMessage).where(AssistantMessage.teacher_id == teacher.id))
    db.commit()
    return {"ok": True}
