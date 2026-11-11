"""Lưu trữ ảnh bài làm của học sinh."""

from __future__ import annotations

import shutil
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

from ..config import Settings

MAX_SIDE = 2200
JPEG_QUALITY = 88


class InvalidUpload(ValueError):
    pass


def submission_folder(settings: Settings, submission_id: int) -> Path:
    return settings.upload_dir / f"sub_{submission_id}"


def save_submission_file(
    settings: Settings, submission_id: int, position: int, data: bytes, mime_type: str
) -> tuple[str, str]:
    """Lưu ảnh (chuẩn hóa xoay/kích thước) hoặc PDF. Trả về (đường dẫn tương đối, mime)."""
    folder = submission_folder(settings, submission_id)
    folder.mkdir(parents=True, exist_ok=True)

    if mime_type == "application/pdf":
        if not data.startswith(b"%PDF"):
            raise InvalidUpload("Tệp PDF không hợp lệ.")
        path = folder / f"{position:02d}.pdf"
        path.write_bytes(data)
        return path.relative_to(settings.upload_dir).as_posix(), "application/pdf"

    try:
        image = Image.open(BytesIO(data))
        image = ImageOps.exif_transpose(image)
        image = image.convert("RGB")
    except (UnidentifiedImageError, OSError) as exc:
        raise InvalidUpload("Không đọc được ảnh. Em hãy gửi ảnh JPG/PNG.") from exc
    image.thumbnail((MAX_SIDE, MAX_SIDE))
    path = folder / f"{position:02d}.jpg"
    image.save(path, format="JPEG", quality=JPEG_QUALITY, optimize=True)
    return path.relative_to(settings.upload_dir).as_posix(), "image/jpeg"


def resolve_upload(settings: Settings, relative_path: str) -> Path:
    """Đường dẫn tuyệt đối an toàn (không cho thoát ra ngoài thư mục uploads)."""
    base = settings.upload_dir.resolve()
    path = (base / relative_path).resolve()
    if base not in path.parents:
        raise InvalidUpload("Đường dẫn không hợp lệ.")
    return path


def delete_submission_files(settings: Settings, submission_id: int) -> None:
    shutil.rmtree(submission_folder(settings, submission_id), ignore_errors=True)
