"""Dispute workflow (F5): sync from PayPal, evidence packs, seller-approved submission.

Sync: always re-fetch GET /v1/customer/disputes/{id}; link to the order via the disputed capture ID.
Packs: versioned; any new plan creates a new version (old ones stay for history).
Submit preconditions: pack READY (claim check passed), supported reason, deadline not passed, the PayPal
"provide-evidence" action available, explicit seller confirmation. One submission per pack version (stable
request id). On a network timeout we re-fetch the dispute before ever retrying.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ai.agents import dispute_defense as dd
from app.ai.provider import Provider
from app.config import Settings
from app.db import utcnow
from app.errors import AppError
from app.models import (
    Actor,
    Capture,
    Dispute,
    EvidenceFile,
    EvidencePack,
    EvidenceSubmission,
    Upload,
)
from app.rules.claims import verify
from app.services.audit import audit
from app.services.evidence_pdf import build_summary_pdf
from app.services.paypal import disputes as pd
from app.services.paypal.client import PayPalClient
from app.services.paypal.errors import PayPalError
from app.services.storage import storage_root

MAX_FILE = 10 * 1024 * 1024
MAX_TOTAL = 50 * 1024 * 1024
PAYPAL_FILE_TYPES = {"image/jpeg", "image/png", "image/gif", "application/pdf"}
DEADLINE_SOON = timedelta(hours=48)


def _dt(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def deadline_flag(d: Dispute, now: datetime | None = None) -> str | None:
    """DIS-11 when the response window passed, DIS-10 when less than 48 h remain."""
    due = d.seller_response_due_date
    if due is None:
        return None
    if due.tzinfo is None:
        due = due.replace(tzinfo=timezone.utc)
    now = now or datetime.now(timezone.utc)
    if due <= now:
        return "DIS-11"
    if due - now <= DEADLINE_SOON:
        return "DIS-10"
    return None


def upsert_from_paypal(db: Session, data: dict[str, Any]) -> Dispute:
    did = data["dispute_id"]
    d = db.scalar(select(Dispute).where(Dispute.paypal_dispute_id == did))
    created = d is None
    if d is None:
        d = Dispute(paypal_dispute_id=did)
        db.add(d)
    txs = data.get("disputed_transactions") or []
    cap_id = next((t.get("seller_transaction_id") for t in txs if t.get("seller_transaction_id")), None)
    amount = data.get("dispute_amount") or {}
    before = (d.status, d.stage, d.outcome)
    d.disputed_capture_id = cap_id or d.disputed_capture_id
    d.reason = data.get("reason")
    d.stage = data.get("dispute_life_cycle_stage")
    d.status = data.get("status")
    try:
        d.amount = Decimal(str(amount.get("value"))) if amount.get("value") is not None else d.amount
    except InvalidOperation:
        pass
    d.currency = amount.get("currency_code") or d.currency
    d.seller_response_due_date = _dt(data.get("seller_response_due_date")) or d.seller_response_due_date
    d.allowed_actions = pd.allowed_actions(data)
    d.requested_evidence = [e for e in data.get("evidences") or [] if e.get("source") == "REQUESTED_FROM_SELLER"] or d.requested_evidence
    d.outcome = (data.get("dispute_outcome") or {}).get("outcome_code") or d.outcome
    d.paypal_create_time = data.get("create_time") or d.paypal_create_time
    d.raw = data
    d.synced_at = utcnow()
    if cap_id and not d.order_id:
        cap = db.scalar(select(Capture).where(Capture.paypal_capture_id == cap_id))
        if cap is not None:
            d.order_id = cap.order_id
    db.flush()
    if created:
        audit(db, d.order_id, Actor.PAYPAL, "DISPUTE_OPENED", {"dispute_id": did, "reason": d.reason, "stage": d.stage,
                                                              "due": data.get("seller_response_due_date")})
    elif before != (d.status, d.stage, d.outcome):
        audit(db, d.order_id, Actor.PAYPAL, "DISPUTE_UPDATED", {"dispute_id": did, "status": d.status, "stage": d.stage, "outcome": d.outcome})
    return d


def sync_dispute(db: Session, client: PayPalClient, paypal_dispute_id: str) -> Dispute:
    d = upsert_from_paypal(db, pd.get_dispute(client, paypal_dispute_id))
    db.commit()
    db.refresh(d)
    return d


def sync_all(db: Session, client: PayPalClient) -> list[Dispute]:
    out = []
    for item in pd.list_disputes(client):
        if item.get("dispute_id"):
            out.append(sync_dispute(db, client, item["dispute_id"]))  # list items are partial -> re-fetch details
    return out


def latest_pack(db: Session, dispute_id: str) -> EvidencePack | None:
    return db.scalar(select(EvidencePack).where(EvidencePack.dispute_id == dispute_id).order_by(EvidencePack.version.desc()))


def _store_generated(settings: Settings, order_id: str, name: str, data: bytes) -> str:
    rel = f"{order_id}/evidence/{name}"
    dest = storage_root(settings) / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    return rel


def build_pack(db: Session, settings: Settings, provider: Provider | None, dispute: Dispute) -> EvidencePack:
    facts = dd.gather_facts(db, dispute)
    p = dd.plan(dispute, facts)
    version = (db.scalar(select(func.max(EvidencePack.version)).where(EvidencePack.dispute_id == dispute.id)) or 0) + 1
    pack = EvidencePack(dispute_id=dispute.id, version=version, supported=p.supported, plan=p.as_dict(), status="DRAFT")
    db.add(pack)
    db.flush()
    if p.supported and facts.get("order_found"):
        note, source = dd.write_note(provider, facts)
        pack.note, pack.note_source = note, source
        pos = 0
        total = 0
        for uid in p.file_upload_ids:
            up = db.get(Upload, uid)
            if up is None or up.mime not in PAYPAL_FILE_TYPES or up.size > MAX_FILE or not (storage_root(settings) / up.path).exists():
                p.missing.append("Label file missing, or its type/size is not accepted by PayPal; it was left out.")
                continue
            ext = {"image/jpeg": "jpg", "image/png": "png", "image/gif": "gif", "application/pdf": "pdf"}[up.mime]
            pack.files.append(EvidenceFile(position=pos, kind="UPLOAD", upload_id=up.id, path=up.path,
                                           filename=f"shipping-label.{ext}", mime=up.mime, size=up.size,
                                           sha256=up.sha256, description="Shipping label photo (original upload)"))
            total += up.size
            pos += 1
        pdf_facts = {**facts, "payment_date": str(facts.get("payment_date") or "-")}
        pdf = build_summary_pdf(pdf_facts)
        if total + len(pdf) <= MAX_TOTAL:
            rel = _store_generated(settings, facts["order_id"], f"summary-{pack.id}.pdf", pdf)
            pack.files.append(EvidenceFile(position=pos, kind="GENERATED", path=rel, filename="evidence-summary.pdf",
                                           mime="application/pdf", size=len(pdf), sha256=hashlib.sha256(pdf).hexdigest(),
                                           description="One-page summary of PayPal facts, label check, tracking and timeline"))
        pack.plan = p.as_dict()
        _recheck(pack, facts, dispute)
    audit(db, dispute.order_id, Actor.AI, "EVIDENCE_PLANNED", {
        "dispute_id": dispute.paypal_dispute_id, "version": version, "supported": p.supported, "evidence_type": p.evidence_type,
        "missing": len(p.missing), "note_source": pack.note_source, "claim_check": (pack.claim_check or {}).get("passed"),
    })
    db.commit()
    db.refresh(pack)
    return pack


def _recheck(pack: EvidencePack, facts: dict[str, Any], dispute: Dispute) -> None:
    check = verify(pack.note or "", dd.facts_for_verifier(facts, dispute))
    pack.claim_check = check.as_dict()
    blocking_missing = any("tracking" in m.lower() for m in (pack.plan or {}).get("missing", []))
    pack.status = "READY" if (check.passed and pack.supported and not blocking_missing) else "DRAFT"


def update_note(db: Session, dispute: Dispute, note: str) -> EvidencePack:
    pack = latest_pack(db, dispute.id)
    if pack is None:
        raise AppError("NO_PACK", "Prepare the evidence first.", 409)
    if pack.status == "SUBMITTED":
        raise AppError("PACK_SUBMITTED", "This evidence was already submitted. Prepare a new version to change it.", 409)
    text = (note or "").strip()
    if not 20 <= len(text) <= dd.NOTE_MAX:
        raise AppError("NOTE_LENGTH", f"The note must be 20–{dd.NOTE_MAX} characters.", 422)
    pack.note, pack.note_source = text, "SELLER"
    _recheck(pack, dd.gather_facts(db, dispute), dispute)
    audit(db, dispute.order_id, Actor.SELLER, "EVIDENCE_NOTE_EDITED", {"dispute_id": dispute.paypal_dispute_id, "version": pack.version,
                                                                      "claim_check": pack.claim_check["passed"]})
    db.commit()
    db.refresh(pack)
    return pack


def submit(db: Session, settings: Settings, client: PayPalClient, dispute: Dispute, *, pack_id: str, confirm: bool) -> EvidenceSubmission:
    pack = latest_pack(db, dispute.id)
    if pack is None or pack.id != pack_id:
        raise AppError("STALE_PACK", "The evidence changed. Review the latest version before submitting.", 409)
    request_id = f"evidence-{pack.id}-v{pack.version}"
    done = db.scalar(select(EvidenceSubmission).where(EvidenceSubmission.request_id == request_id))
    if done is not None and done.status == "SUCCEEDED":
        return done  # once per pack version
    if not confirm:
        raise AppError("CONFIRMATION_REQUIRED", "Confirm the submission in the dialog.", 422)
    if not pack.supported:
        raise AppError("UNSUPPORTED_REASON", "This dispute reason needs a manual response in PayPal.", 409)
    if pack.status != "READY":
        raise AppError("EVD-08", "The note contains a claim we can't back with evidence (or tracking is missing). Fix it first.", 409,
                       {"claim_check": pack.claim_check})
    if deadline_flag(dispute) == "DIS-11":
        raise AppError("DIS-11", "The response window has passed.", 409)

    sync_dispute(db, client, dispute.paypal_dispute_id)  # fresh state + allowed actions before acting
    db.refresh(dispute)
    if "provide-evidence" not in (dispute.allowed_actions or []):
        raise AppError("ACTION_NOT_AVAILABLE", "PayPal does not allow providing evidence on this dispute right now.", 409,
                       {"status": dispute.status, "allowed_actions": dispute.allowed_actions})

    plan = pack.plan or {}
    evidence = {"evidence_type": plan.get("evidence_type") or "PROOF_OF_FULFILLMENT", "notes": pack.note}
    if plan.get("tracking_info"):
        evidence["evidence_info"] = {"tracking_info": plan["tracking_info"]}
    files = []
    for f in pack.files:
        path = storage_root(settings) / f.path
        if not path.exists():
            raise AppError("EVIDENCE_FILE_MISSING", f"Evidence file {f.filename} is missing on the server. Prepare the evidence again.", 409)
        files.append((f.filename, path.read_bytes(), f.mime))

    sub = done or EvidenceSubmission(pack_id=pack.id, request_id=request_id, status="UNKNOWN")
    if done is None:
        db.add(sub)
    try:
        resp = pd.provide_evidence(client, dispute.paypal_dispute_id, evidences=[evidence], files=files,
                                   request_id=request_id, order_id=dispute.order_id)
        sub.status, sub.http_status, sub.response = "SUCCEEDED", 200, resp
        pack.status = "SUBMITTED"
        audit(db, dispute.order_id, Actor.SELLER, "EVIDENCE_SUBMITTED", {"dispute_id": dispute.paypal_dispute_id, "version": pack.version,
                                                                         "files": len(files), "evidence_type": evidence["evidence_type"]})
    except PayPalError as exc:
        sub.http_status, sub.paypal_debug_id = exc.status_code, exc.debug_id
        sub.response = {"name": exc.name, "message": exc.message, "issues": exc.issues}
        if exc.retryable:
            # timeout/5xx: re-fetch before any retry — PayPal may have accepted it
            try:
                fresh = sync_dispute(db, client, dispute.paypal_dispute_id)
                accepted = "provide-evidence" not in (fresh.allowed_actions or [])
            except PayPalError:
                accepted = False
            sub.status = "SUCCEEDED" if accepted else "UNKNOWN"
            if accepted:
                pack.status = "SUBMITTED"
        else:
            sub.status = "FAILED"
        audit(db, dispute.order_id, Actor.PAYPAL, "EVIDENCE_SUBMIT_FAILED" if sub.status != "SUCCEEDED" else "EVIDENCE_SUBMITTED",
              {"dispute_id": dispute.paypal_dispute_id, "debug_id": exc.debug_id, "issues": exc.issues, "status": sub.status})
        db.commit()
        if sub.status != "SUCCEEDED":
            if not exc.retryable:
                sub.request_id = f"{request_id}-failed-{uuid.uuid4().hex[:8]}"  # free the id for a corrected retry
                db.commit()
            raise AppError("EVIDENCE_REJECTED" if not exc.retryable else "PAYPAL_TIMEOUT",
                           f"PayPal did not accept the evidence: {exc.human_message()}" if not exc.retryable else
                           "PayPal did not answer in time. We checked the dispute; please try again.", 502, exc.public_details()) from exc
    db.commit()
    try:
        sync_dispute(db, client, dispute.paypal_dispute_id)
    except PayPalError:
        pass
    db.refresh(sub)
    return sub


def sandbox_action(db: Session, client: PayPalClient, settings: Settings, dispute: Dispute, action: str) -> Dispute:
    if settings.PAYPAL_ENVIRONMENT.lower() != "sandbox":
        raise AppError("NOT_FOUND", "Not found.", 404)
    try:
        if action in ("SELLER_FAVOR", "BUYER_FAVOR"):
            pd.adjudicate(client, dispute.paypal_dispute_id, action)
        elif action in ("SELLER_EVIDENCE", "BUYER_EVIDENCE"):
            pd.require_evidence(client, dispute.paypal_dispute_id, action)
        else:
            raise AppError("BAD_ACTION", "Unknown sandbox action.", 422)
    except PayPalError as exc:
        raise AppError("SANDBOX_ACTION_FAILED", f"PayPal sandbox refused: {exc.human_message()} (needs status UNDER_REVIEW)", 409,
                       exc.public_details()) from exc
    audit(db, dispute.order_id, Actor.SELLER, "SANDBOX_DISPUTE_ACTION", {"dispute_id": dispute.paypal_dispute_id, "action": action})
    db.commit()
    return sync_dispute(db, client, dispute.paypal_dispute_id)


def _hours_left(d: Dispute) -> int | None:
    due = d.seller_response_due_date
    if due is None:
        return None
    if due.tzinfo is None:
        due = due.replace(tzinfo=timezone.utc)
    return int((due - datetime.now(timezone.utc)).total_seconds() // 3600)


def dispute_json(d: Dispute) -> dict[str, Any]:
    return {
        "id": d.id, "paypal_dispute_id": d.paypal_dispute_id, "order_id": d.order_id, "reason": d.reason, "stage": d.stage,
        "status": d.status, "amount": str(d.amount) if d.amount is not None else None, "currency": d.currency,
        "seller_response_due_date": d.seller_response_due_date.isoformat() if d.seller_response_due_date else None,
        "deadline_flag": deadline_flag(d), "hours_left": _hours_left(d), "allowed_actions": d.allowed_actions or [], "outcome": d.outcome,
        "requested_evidence": d.requested_evidence or [], "synced_at": d.synced_at.isoformat() if d.synced_at else None,
        "buyer_message": next((m.get("content") for m in (d.raw or {}).get("messages", []) if m.get("posted_by") == "BUYER"), None),
        "create_time": d.paypal_create_time,
    }


def pack_json(p: EvidencePack | None, subs: list[EvidenceSubmission]) -> dict[str, Any] | None:
    if p is None:
        return None
    return {
        "id": p.id, "version": p.version, "status": p.status, "supported": p.supported, "plan": p.plan, "note": p.note,
        "note_source": p.note_source, "claim_check": p.claim_check,
        "files": [{"id": f.id, "filename": f.filename, "mime": f.mime, "size": f.size, "kind": f.kind, "description": f.description,
                   "upload_id": f.upload_id} for f in p.files],
        "submissions": [{"id": s.id, "status": s.status, "http_status": s.http_status, "paypal_debug_id": s.paypal_debug_id,
                         "submitted_at": s.submitted_at.isoformat()} for s in subs],
        "evidence_preview": json.dumps({"evidences": [{"evidence_type": (p.plan or {}).get("evidence_type"),
                                                         "evidence_info": {"tracking_info": (p.plan or {}).get("tracking_info")},
                                                         "notes": p.note}]}, indent=1),
    }
