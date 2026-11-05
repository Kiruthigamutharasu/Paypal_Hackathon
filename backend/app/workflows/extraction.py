"""Deterministic orchestration of the extraction agents (F2 task 6). Not LLM-driven.

run_extractions(order_id):
  - collects active uploads (chat screenshots + pasted chats, current label)
  - calls Conversation Analyst (batches of <=5 images) and Label Reader
  - caches by input hash (same inputs + prompt/schema/model -> no new model call)
  - stores ai_extractions rows, audits, and resets verification_state
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import db as dbm
from app.ai.agents import conversation_analyst as ca
from app.ai.agents import label_reader as lr
from app.ai.provider import Provider, StructuredResult, hash_parts
from app.ai.schemas import SCHEMA_VERSION
from app.config import Settings
from app.models import (
    Actor,
    AIExtraction,
    ExtractionStatus,
    Order,
    Upload,
    UploadKind,
    VerificationState,
)
from app.services.audit import audit
from app.services.storage import MAX_CHAT_IMAGES_PER_BATCH, active_uploads, read_bytes

log = logging.getLogger("staycovered.extraction")


def _cached(db: Session, order_id: str, agent: str, input_hash: str) -> AIExtraction | None:
    return db.scalar(
        select(AIExtraction)
        .where(
            AIExtraction.order_id == order_id,
            AIExtraction.agent == agent,
            AIExtraction.input_hash == input_hash,
            AIExtraction.status == ExtractionStatus.SUCCEEDED,
        )
        .order_by(AIExtraction.created_at.desc())
    )


def _store(db: Session, order: Order, agent: str, prompt_version: str, upload_ids: list[str],
           input_hash: str, res: StructuredResult) -> AIExtraction:
    out = res.output.model_dump(mode="json") if res.output is not None else None
    row = AIExtraction(
        order_id=order.id,
        agent=agent,
        upload_ids=upload_ids,
        provider=res.provider,
        model=res.model,
        prompt_version=prompt_version,
        schema_version=SCHEMA_VERSION,
        input_hash=input_hash,
        raw_response_hash=res.raw_response_hash,
        output=out,
        validation_notes=res.notes or None,
        confidence=Decimal(str(round(out["confidence"], 3))) if out else None,
        status=res.status,
        error=res.error,
        attempts=res.attempts,
        latency_ms=res.latency_ms,
    )
    db.add(row)
    audit(
        db,
        order.id,
        Actor.AI,
        "AI_EXTRACTION_COMPLETED" if res.status == ExtractionStatus.SUCCEEDED else "AI_EXTRACTION_FAILED",
        {
            "agent": agent,
            "status": res.status,
            "model": res.model,
            "upload_ids": upload_ids,
            "confidence": out["confidence"] if out else None,
            "requests": [r["type"] + "/" + r["status"] for r in out.get("requests", [])] if out and "requests" in out else None,
            "dropped": len(res.notes),
            "latency_ms": res.latency_ms,
            "error": res.error,
        },
    )
    return row


def run_extractions(db: Session, settings: Settings, provider: Provider, order_id: str) -> list[AIExtraction]:
    order = db.get(Order, order_id)
    if order is None:
        raise LookupError(order_id)
    uploads = active_uploads(db, order_id)
    chats = [u for u in uploads if u.kind in (UploadKind.CHAT_IMAGE, UploadKind.CHAT_TEXT)]
    label = next((u for u in uploads if u.kind == UploadKind.LABEL_IMAGE), None)
    addr = order.active_address.fields() if order.active_address else None

    order.verification_state = VerificationState.AI_PROCESSING
    db.commit()
    results: list[AIExtraction] = []
    try:
        # Conversation Analyst: texts with the first batch, images in batches of 5
        images = [u for u in chats if u.kind == UploadKind.CHAT_IMAGE]
        texts = [u for u in chats if u.kind == UploadKind.CHAT_TEXT]
        batches: list[list[Upload]] = []
        for i in range(0, max(len(images), 1), MAX_CHAT_IMAGES_PER_BATCH):
            batches.append(images[i : i + MAX_CHAT_IMAGES_PER_BATCH])
        if texts:
            batches[0] = texts + batches[0]
        for batch in [b for b in batches if b]:
            inputs = [ca.ChatInput(u.id, u.kind, read_bytes(settings, u), u.mime) for u in batch]
            parts = ca.build_parts(inputs, addr)
            ih = hash_parts(parts, ca.PROMPT_VERSION, SCHEMA_VERSION, provider.name, provider.model)
            hit = _cached(db, order.id, ca.AGENT, ih)
            if hit:
                results.append(hit)
                continue
            res, _ = ca.analyze(provider, inputs, addr)
            results.append(_store(db, order, ca.AGENT, ca.PROMPT_VERSION, [u.id for u in batch], ih, res))
            db.commit()

        if label is not None:
            data = read_bytes(settings, label)
            parts = lr.build_parts(label.id, data, label.mime)
            ih = hash_parts(parts, lr.PROMPT_VERSION, SCHEMA_VERSION, provider.name, provider.model)
            hit = _cached(db, order.id, lr.AGENT, ih)
            if hit:
                results.append(hit)
            else:
                res, _ = lr.read_label(provider, label.id, data, label.mime)
                results.append(_store(db, order, lr.AGENT, lr.PROMPT_VERSION, [label.id], ih, res))
                db.commit()
    finally:
        order = db.get(Order, order_id)
        order.verification_state = VerificationState.AWAITING_DOCUMENTS
        db.commit()
        from app.workflows.verification import evaluate_safely  # local import: avoids a cycle

        evaluate_safely(db, settings, order_id, "AI extraction finished")
    return results


def run_extractions_in_background(settings: Settings, provider_factory: Callable[[], Provider], order_id: str) -> None:
    with dbm.SessionLocal() as db:
        try:
            run_extractions(db, settings, provider_factory(), order_id)
        except Exception as exc:
            log.exception("extraction run failed for %s", order_id)
            db.rollback()
            audit(db, order_id, Actor.SYSTEM, "AI_EXTRACTION_FAILED", {"error": type(exc).__name__, "detail": str(exc)[:300]})
            order = db.get(Order, order_id)
            if order is not None:
                order.verification_state = VerificationState.AWAITING_DOCUMENTS
            db.commit()


def latest_extractions(db: Session, order_id: str) -> dict[str, list[AIExtraction]]:
    """Latest extraction per active upload set, grouped by agent."""
    active_ids = {u.id for u in active_uploads(db, order_id)}
    rows = db.scalars(
        select(AIExtraction).where(AIExtraction.order_id == order_id).order_by(AIExtraction.created_at.desc())
    ).all()
    out: dict[str, list[AIExtraction]] = {ca.AGENT: [], lr.AGENT: []}
    covered: dict[str, set[str]] = {}
    for r in rows:  # newest first; skip rows whose inputs are already covered by a newer run
        ids = set(r.upload_ids)
        if not ids <= active_ids:
            continue
        seen = covered.setdefault(r.agent, set())
        if ids <= seen:
            continue
        seen |= ids
        out.setdefault(r.agent, []).append(r)
    return out
