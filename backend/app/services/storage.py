"""Evidence file storage (PRD §6.5, F2 task 1).

- Type check by magic bytes AND extension allow-list (per upload kind)
- Max 10 MB per file, max 5 chat images per batch
- Stored as FILE_STORAGE_PATH/{order_id}/{uuid}.{ext}; never overwritten; SHA-256 recorded
- A new label supersedes the previous active label (`superseded_by`); originals are kept
"""
from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import ROOT_DIR, Settings
from app.errors import AppError
from app.models import Actor, Order, Upload, UploadKind
from app.services.audit import audit

MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_CHAT_IMAGES_PER_BATCH = 5
MAX_CHAT_TEXT_CHARS = 20_000

# mime -> (magic-byte check, canonical extension)
_SIGNATURES: dict[str, tuple[tuple[bytes, ...], str]] = {
    "image/png": ((b"\x89PNG\r\n\x1a\n",), "png"),
    "image/jpeg": ((b"\xff\xd8\xff",), "jpg"),
    "image/gif": ((b"GIF87a", b"GIF89a"), "gif"),
    "application/pdf": ((b"%PDF-",), "pdf"),
}
_EXT_TO_MIME = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "gif": "image/gif", "pdf": "application/pdf"}

ALLOWED: dict[UploadKind, set[str]] = {
    UploadKind.CHAT_IMAGE: {"image/png", "image/jpeg"},
    UploadKind.LABEL_IMAGE: {"image/png", "image/jpeg", "image/gif", "application/pdf"},
}


@dataclass
class IncomingFile:
    filename: str | None
    data: bytes


def storage_root(settings: Settings) -> Path:
    p = Path(settings.FILE_STORAGE_PATH)
    if not p.is_absolute():
        p = ROOT_DIR / p
    return p


def sniff_mime(data: bytes) -> str | None:
    for mime, (magics, _) in _SIGNATURES.items():
        if any(data.startswith(m) for m in magics):
            return mime
    return None


def validate_file(kind: UploadKind, f: IncomingFile) -> str:
    """Return the verified mime type or raise AppError(UPLOAD_REJECTED)."""
    name = f.filename or "file"
    if len(f.data) == 0:
        raise AppError("UPLOAD_REJECTED", f"'{name}' is empty.", 400)
    if len(f.data) > MAX_FILE_BYTES:
        raise AppError("UPLOAD_REJECTED", f"'{name}' is larger than 10 MB. Please upload a smaller photo.", 413)
    ext = Path(name).suffix.lower().lstrip(".")
    allowed = ALLOWED[kind]
    allowed_exts = sorted({e for e, m in _EXT_TO_MIME.items() if m in allowed})
    if _EXT_TO_MIME.get(ext) not in allowed:
        raise AppError(
            "UPLOAD_REJECTED",
            f"'{name}' is not an allowed file type. Allowed: {', '.join(allowed_exts)}.",
            415,
        )
    sniffed = sniff_mime(f.data)
    if sniffed is None or sniffed != _EXT_TO_MIME[ext]:
        raise AppError(
            "UPLOAD_REJECTED",
            f"'{name}' does not look like a real {ext.upper()} file.",
            415,
        )
    return sniffed


def _write(root: Path, order_id: str, data: bytes, ext: str) -> str:
    rel = Path(order_id) / f"{uuid.uuid4()}.{ext}"
    dest = root / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    with open(dest, "xb") as fh:  # 'x' = never overwrite
        fh.write(data)
    return rel.as_posix()


def read_bytes(settings: Settings, upload: Upload) -> bytes:
    path = (storage_root(settings) / upload.path).resolve()
    root = storage_root(settings).resolve()
    if root not in path.parents:
        raise AppError("FILE_NOT_FOUND", "File not found.", 404)
    return path.read_bytes()


def _next_sequence(db: Session, order_id: str) -> int:
    rows = db.scalars(
        select(Upload.sequence).where(Upload.order_id == order_id, Upload.kind != UploadKind.LABEL_IMAGE)
    ).all()
    return (max(rows) + 1) if rows else 1


def save_uploads(
    db: Session,
    settings: Settings,
    order: Order,
    kind: UploadKind,
    files: list[IncomingFile],
    text: str | None = None,
) -> list[Upload]:
    """Validate everything first, then write. Commits."""
    root = storage_root(settings)
    batch_id = str(uuid.uuid4())
    to_write: list[tuple[bytes, str, str, str | None]] = []  # data, mime, ext, original name

    if kind == UploadKind.CHAT_TEXT:
        clean = (text or "").strip()
        if not clean:
            raise AppError("UPLOAD_REJECTED", "Paste the chat text first.", 400)
        if len(clean) > MAX_CHAT_TEXT_CHARS:
            raise AppError("UPLOAD_REJECTED", "Pasted chat is too long (max 20,000 characters).", 413)
        to_write.append((clean.encode("utf-8"), "text/plain", "txt", None))
    else:
        if not files:
            raise AppError("UPLOAD_REJECTED", "Choose at least one file.", 400)
        if kind == UploadKind.CHAT_IMAGE and len(files) > MAX_CHAT_IMAGES_PER_BATCH:
            raise AppError("UPLOAD_REJECTED", "Upload at most 5 chat screenshots at a time.", 400)
        if kind == UploadKind.LABEL_IMAGE and len(files) != 1:
            raise AppError("UPLOAD_REJECTED", "Upload exactly one shipping label photo.", 400)
        for f in files:
            mime = validate_file(kind, f)
            to_write.append((f.data, mime, _SIGNATURES[mime][1], f.filename))

    created: list[Upload] = []
    seq = _next_sequence(db, order.id)
    if kind == UploadKind.LABEL_IMAGE:
        previous = db.scalars(
            select(Upload).where(
                Upload.order_id == order.id,
                Upload.kind == UploadKind.LABEL_IMAGE,
                Upload.superseded_by.is_(None),
            )
        ).all()
    else:
        previous = []

    for data, mime, ext, original in to_write:
        rel = _write(root, order.id, data, ext)
        up = Upload(
            order_id=order.id,
            kind=kind,
            path=rel,
            original_filename=(original or "")[:255] or None,
            mime=mime,
            size=len(data),
            sha256=hashlib.sha256(data).hexdigest(),
            sequence=0 if kind == UploadKind.LABEL_IMAGE else seq,
            batch_id=batch_id,
        )
        seq += 1
        db.add(up)
        db.flush()
        created.append(up)

    for old in previous:
        old.superseded_by = created[0].id

    audit(
        db,
        order.id,
        Actor.SELLER,
        "EVIDENCE_UPLOADED",
        {
            "kind": kind,
            "count": len(created),
            "upload_ids": [u.id for u in created],
            "sha256": [u.sha256[:12] for u in created],
            "superseded": [o.id for o in previous],
        },
    )
    db.commit()
    return created


def active_uploads(db: Session, order_id: str) -> list[Upload]:
    return list(
        db.scalars(
            select(Upload)
            .where(Upload.order_id == order_id, Upload.superseded_by.is_(None))
            .order_by(Upload.sequence, Upload.created_at)
        )
    )
