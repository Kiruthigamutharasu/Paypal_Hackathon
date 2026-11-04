from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.deps import get_db, get_paypal_client, settings_dep
from app.models import WebhookEvent
from app.services.paypal.client import PayPalClient
from app.workflows.webhooks import (
    process_event_in_background,
    receive_webhook,
    reprocess_failed,
)

router = APIRouter(tags=["webhooks"])


@router.post("/api/webhooks/paypal")
async def paypal_webhook(
    request: Request,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    client: PayPalClient = Depends(get_paypal_client),
    settings: Settings = Depends(settings_dep),
):
    raw = await request.body()
    headers = dict(request.headers)
    result = await run_in_threadpool(receive_webhook, db, client, settings, headers, raw)
    if result.outcome == "accepted" and result.event_row_id:
        background.add_task(process_event_in_background, client, result.event_row_id)
    if result.status_code != 200:
        return JSONResponse(
            {"error_code": "WEBHOOK_REJECTED", "message": "Webhook could not be verified.", "details": {}},
            status_code=result.status_code,
        )
    return {"status": result.outcome}


@router.get("/api/admin/webhooks")
def list_webhook_events(db: Session = Depends(get_db)):
    rows = db.scalars(select(WebhookEvent).order_by(WebhookEvent.received_at.desc()).limit(100)).all()
    return [
        {
            "id": r.id,
            "paypal_event_id": r.paypal_event_id,
            "event_type": r.event_type,
            "status": r.status,
            "attempts": r.attempts,
            "error": r.error,
            "order_id": r.order_id,
            "received_at": r.received_at,
            "processed_at": r.processed_at,
        }
        for r in rows
    ]


@router.post("/api/admin/webhooks/reprocess")
def reprocess(db: Session = Depends(get_db), client: PayPalClient = Depends(get_paypal_client)):
    """Re-run FAILED/RECEIVED events (each one re-fetches from PayPal)."""
    return {"reprocessed": reprocess_failed(db, client)}
