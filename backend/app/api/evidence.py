"""Evidence uploads and AI extraction results (F2)."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.deps import get_ai_provider_factory, get_db, settings_dep
from app.errors import AppError
from app.models import AIExtraction, Order, Upload, UploadKind
from app.services.storage import (
    MAX_CHAT_IMAGES_PER_BATCH,
    MAX_FILE_BYTES,
    IncomingFile,
    read_bytes,
    save_uploads,
)
from app.workflows.extraction import latest_extractions, run_extractions_in_background

router = APIRouter(tags=["evidence"])


class UploadOut(BaseModel):
    id: str
    kind: str
    mime: str
    size: int
    sha256: str
    sequence: int
    original_filename: str | None
    superseded_by: str | None
    created_at: datetime
    url: str


class ExtractionOut(BaseModel):
    id: str
    agent: str
    upload_ids: list[str]
    provider: str
    model: str
    prompt_version: str
    schema_version: str
    status: str
    output: dict[str, Any] | None
    validation_notes: list[str] | None
    confidence: float | None
    error: str | None
    attempts: int
    latency_ms: int | None
    created_at: datetime


class EvidenceOut(BaseModel):
    verification_state: str
    uploads: list[UploadOut]
    conversation: list[ExtractionOut]
    label: list[ExtractionOut]


def _upload_out(u: Upload) -> UploadOut:
    return UploadOut(
        id=u.id, kind=u.kind, mime=u.mime, size=u.size, sha256=u.sha256, sequence=u.sequence,
        original_filename=u.original_filename, superseded_by=u.superseded_by, created_at=u.created_at,
        url=f"/api/uploads/{u.id}/file",
    )


def _ex_out(r: AIExtraction) -> ExtractionOut:
    return ExtractionOut(
        id=r.id, agent=r.agent, upload_ids=r.upload_ids, provider=r.provider, model=r.model,
        prompt_version=r.prompt_version, schema_version=r.schema_version, status=r.status, output=r.output,
        validation_notes=r.validation_notes, confidence=float(r.confidence) if r.confidence is not None else None,
        error=r.error, attempts=r.attempts, latency_ms=r.latency_ms, created_at=r.created_at,
    )


def _order(db: Session, order_id: str) -> Order:
    order = db.get(Order, order_id)
    if order is None:
        raise AppError("ORDER_NOT_FOUND", "Order not found.", 404)
    return order


def _evidence(db: Session, order: Order) -> EvidenceOut:
    uploads = db.scalars(
        select(Upload).where(Upload.order_id == order.id).order_by(Upload.created_at)
    ).all()
    latest = latest_extractions(db, order.id)
    db.refresh(order)
    return EvidenceOut(
        verification_state=order.verification_state,
        uploads=[_upload_out(u) for u in uploads],
        conversation=[_ex_out(r) for r in latest.get("conversation_analyst", [])],
        label=[_ex_out(r) for r in latest.get("label_reader", [])],
    )


@router.post("/api/orders/{order_id}/uploads", response_model=EvidenceOut)
async def upload_evidence(
    order_id: str,
    background: BackgroundTasks,
    kind: UploadKind = Form(...),
    files: list[UploadFile] | None = File(default=None),
    text: str | None = Form(default=None),
    db: Session = Depends(get_db),
    settings: Settings = Depends(settings_dep),
    provider_factory=Depends(get_ai_provider_factory),
):
    order = _order(db, order_id)
    if files and len(files) > MAX_CHAT_IMAGES_PER_BATCH:
        raise AppError("UPLOAD_REJECTED", "Upload at most 5 files at a time.", 400)
    incoming: list[IncomingFile] = []
    for f in files or []:
        data = await f.read(MAX_FILE_BYTES + 1)  # never read more than the limit + 1 byte
        incoming.append(IncomingFile(f.filename, data))
    save_uploads(db, settings, order, kind, incoming, text)
    background.add_task(run_extractions_in_background, settings, provider_factory, order.id)
    return _evidence(db, order)


@router.get("/api/orders/{order_id}/evidence", response_model=EvidenceOut)
def get_evidence(order_id: str, db: Session = Depends(get_db)):
    return _evidence(db, _order(db, order_id))


@router.get("/api/orders/{order_id}/extractions", response_model=EvidenceOut)
def get_extractions(order_id: str, db: Session = Depends(get_db)):
    return _evidence(db, _order(db, order_id))


@router.post("/api/orders/{order_id}/extractions/run", response_model=EvidenceOut)
def rerun_extractions(
    order_id: str,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    settings: Settings = Depends(settings_dep),
    provider_factory=Depends(get_ai_provider_factory),
):
    """Retry (e.g. after EXTRACTION_FAILED or provider outage). Cached results are reused."""
    order = _order(db, order_id)
    background.add_task(run_extractions_in_background, settings, provider_factory, order.id)
    return _evidence(db, order)


@router.get("/api/uploads/{upload_id}/file")
def get_upload_file(upload_id: str, db: Session = Depends(get_db), settings: Settings = Depends(settings_dep)):
    up = db.get(Upload, upload_id)
    if up is None:
        raise AppError("FILE_NOT_FOUND", "File not found.", 404)
    return Response(
        read_bytes(settings, up),
        media_type=up.mime if up.mime != "text/plain" else "text/plain; charset=utf-8",
        headers={
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'none'; img-src 'self'; style-src 'unsafe-inline'",
            "Cache-Control": "private, max-age=3600",
        },
    )
