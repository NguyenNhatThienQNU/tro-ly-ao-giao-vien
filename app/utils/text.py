"""Tiện ích xử lý chuỗi tiếng Việt, điểm số và mã."""

from __future__ import annotations

import re
import secrets
import unicodedata

LINK_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # bỏ 0/O, 1/I để HS khỏi nhầm
LINK_CODE_LENGTH = 8


def strip_accents(text: str) -> str:
    text = (text or "").replace("đ", "d").replace("Đ", "D")
    decomposed = unicodedata.normalize("NFD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def norm(text: str | None) -> str:
    """Chuẩn hóa để so khớp: bỏ dấu, chữ thường, gộp khoảng trắng."""
    return re.sub(r"\s+", " ", strip_accents(text or "").lower()).strip()


def norm_key(text: str | None) -> str:
    """Chuẩn hóa mạnh (chỉ giữ chữ và số), dùng cho tên cột bảng tính."""
    return re.sub(r"[^a-z0-9]+", "", norm(text))


def new_link_code() -> str:
    return "".join(secrets.choice(LINK_ALPHABET) for _ in range(LINK_CODE_LENGTH))


def new_token() -> str:
    return secrets.token_urlsafe(18)


def clean_code(text: str | None) -> str:
    return re.sub(r"[^A-Za-z0-9]", "", text or "").upper()


def looks_like_link_code(text: str | None) -> bool:
    code = clean_code(text)
    return len(code) == LINK_CODE_LENGTH and all(ch in LINK_ALPHABET for ch in code)


def round_quarter(value: float) -> float:
    return round(value * 4) / 4


def fmt_score(value: float | None) -> str:
    """Hiển thị điểm kiểu Việt Nam: 7.5 -> '7,5'; 8.0 -> '8'."""
    if value is None:
        return "–"
    text = f"{value:.2f}".rstrip("0").rstrip(".")
    return text.replace(".", ",")


def to_ten(score: float | None, max_total: float | None) -> float | None:
    """Quy đổi về thang điểm 10."""
    if score is None or not max_total:
        return None
    return round(score / max_total * 10, 2)


def split_text(text: str, limit: int) -> list[str]:
    """Chia tin nhắn dài theo dòng để không vượt giới hạn ký tự của kênh chat."""
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    current = ""
    for line in text.split("\n"):
        while len(line) > limit:
            if current:
                chunks.append(current)
                current = ""
            chunks.append(line[:limit])
            line = line[limit:]
        candidate = f"{current}\n{line}" if current else line
        if len(candidate) > limit:
            chunks.append(current)
            current = line
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


def truncate(text: str | None, length: int = 80) -> str:
    text = (text or "").strip().replace("\n", " ")
    return text if len(text) <= length else text[: length - 1].rstrip() + "…"
