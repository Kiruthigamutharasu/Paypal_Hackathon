"""Disputes API (F5)."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.deps import get_ai_provider_factory, get_db, get_paypal_client, settings_dep
from app.errors import AppError
from app.models import Dispute, EvidencePack, EvidenceSubmission, Order
from app.services.paypal.client import PayPalClient
from app.workflows import disputes as dw

router = APIRouter(tags=["disputes"])


class NoteIn(BaseModel):
    note: str = Field(min_length=1, max_length=2000)


class SubmitIn(BaseModel):
    pack_id: str
    confirm: bool = False


class SandboxIn(BaseModel):
    action: str = Field(pattern="^(SELLER_FAVOR|BUYER_FAVOR|SELLER_EVIDENCE|BUYER_EVIDENCE)$")


def _dispute(db: Session, dispute_id: str) -> Dispute:
    d = db.get(Dispute, dispute_id)
    if d is None:
        raise AppError("DISPUTE_NOT_FOUND", "Dispute not found.", 404)
    return d


def _detail(db: Session, d: Dispute) -> dict:
    pack = dw.latest_pack(db, d.id)
    subs = list(db.scalars(select(EvidenceSubmission).where(EvidenceSubmission.pack_id == pack.id).order_by(EvidenceSubmission.submitted_at))) if pack else []
    order = db.get(Order, d.order_id) if d.order_id else None
    return {
        **dw.dispute_json(d),
        "order": {"id": order.id, "item": order.item_description, "buyer_name": order.buyer_name, "amount": str(order.amount),
                  "shipment_state": order.shipment_state} if order else None,
        "pack": dw.pack_json(pack, subs),
        "pack_versions": db.query(EvidencePack).filter(EvidencePack.dispute_id == d.id).count(),
    }


@router.get("/api/disputes")
def list_disputes(db: Session = Depends(get_db)):
    rows = db.scalars(select(Dispute).order_by(Dispute.created_at.desc())).all()
    out = []
    for d in rows:
        order = db.get(Order, d.order_id) if d.order_id else None
        pack = dw.latest_pack(db, d.id)
        out.append({**dw.dispute_json(d), "item": order.item_description if order else None,
                    "buyer_name": order.buyer_name if order else None, "pack_status": pack.status if pack else None})
    return out


@router.post("/api/disputes/sync")
def sync(db: Session = Depends(get_db), client: PayPalClient = Depends(get_paypal_client)):
    """Pull disputes from PayPal (covers missed webhooks)."""
    return {"synced": [d.paypal_dispute_id for d in dw.sync_all(db, client)]}


@router.get("/api/disputes/{dispute_id}")
def get_dispute(dispute_id: str, db: Session = Depends(get_db)):
    return _detail(db, _dispute(db, dispute_id))


@router.post("/api/disputes/{dispute_id}/refresh")
def refresh(dispute_id: str, db: Session = Depends(get_db), client: PayPalClient = Depends(get_paypal_client)):
    d = _dispute(db, dispute_id)
    return _detail(db, dw.sync_dispute(db, client, d.paypal_dispute_id))


@router.post("/api/disputes/{dispute_id}/plan")
def plan(dispute_id: str, db: Session = Depends(get_db), settings: Settings = Depends(settings_dep),
         provider_factory=Depends(get_ai_provider_factory)):
    d = _dispute(db, dispute_id)
    try:
        provider = provider_factory()
    except Exception:
        provider = None
    dw.build_pack(db, settings, provider, d)
    return _detail(db, d)


@router.put("/api/disputes/{dispute_id}/note")
def edit_note(dispute_id: str, body: NoteIn, db: Session = Depends(get_db)):
    d = _dispute(db, dispute_id)
    dw.update_note(db, d, body.note)
    return _detail(db, d)


@router.post("/api/disputes/{dispute_id}/submit")
def submit(dispute_id: str, body: SubmitIn, db: Session = Depends(get_db), settings: Settings = Depends(settings_dep),
           client: PayPalClient = Depends(get_paypal_client)):
    """AUTO_SUBMIT_EVIDENCE is intentionally ignored in the MVP: the seller always confirms."""
    d = _dispute(db, dispute_id)
    dw.submit(db, settings, client, d, pack_id=body.pack_id, confirm=body.confirm)
    return _detail(db, d)


@router.get("/api/disputes/{dispute_id}/files/{file_id}")
def evidence_file(dispute_id: str, file_id: str, db: Session = Depends(get_db), settings: Settings = Depends(settings_dep)):
    from fastapi.responses import Response

    from app.models import EvidenceFile
    from app.services.storage import storage_root

    f = db.get(EvidenceFile, file_id)
    if f is None or f.pack.dispute_id != dispute_id:
        raise AppError("FILE_NOT_FOUND", "File not found.", 404)
    data = (storage_root(settings) / f.path).read_bytes()
    return Response(data, media_type=f.mime, headers={"X-Content-Type-Options": "nosniff",
                                                      "Content-Disposition": f'inline; filename="{f.filename}"'})


@router.post("/api/sandbox/disputes/{dispute_id}/action")
def sandbox_action(dispute_id: str, body: SandboxIn, db: Session = Depends(get_db), settings: Settings = Depends(settings_dep),
                   client: PayPalClient = Depends(get_paypal_client)):
    """Sandbox-only demo tools: settle (adjudicate) or move the dispute to 'waiting for evidence'."""
    d = _dispute(db, dispute_id)
    return _detail(db, dw.sandbox_action(db, client, settings, d, body.action))
