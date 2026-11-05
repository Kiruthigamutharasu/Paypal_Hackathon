"""Shipping verdict API (F3)."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.config import Settings
from app.deps import get_db, settings_dep
from app.errors import AppError
from app.models import Order, ShippingDecision
from app.workflows.verification import acknowledge, active_decision, evaluate_order, shipping_allowed

router = APIRouter(prefix="/api/orders/{order_id}", tags=["decision"])


class FlagOut(BaseModel):
    code: str
    name: str
    severity: str
    effect: str
    message: str
    detail: str | None
    source_ref: dict[str, Any] | None
    recommended_action: str


class DecisionOut(BaseModel):
    id: str
    verdict: str
    status: str
    resolution: str
    headline: str
    recommended_action: str
    checks: list[dict[str, Any]]
    comparison: dict[str, Any] | None
    ignored: list[str]
    flags: list[FlagOut]
    rules_version: str
    acknowledged_items: list[str] | None
    override_reason: str | None
    resolved_at: datetime | None
    created_at: datetime
    can_ship: bool
    can_ship_reason: str


class AcknowledgeIn(BaseModel):
    items: list[str] = Field(default_factory=list, description="Flag codes the seller reviewed (YELLOW)")
    reason: str | None = Field(default=None, max_length=1000, description="Required to override RED")
    confirm_void: bool = False


def decision_out(d: ShippingDecision) -> DecisionOut:
    ok, why = shipping_allowed(d)
    e = d.explanation or {}
    return DecisionOut(
        id=d.id, verdict=d.verdict, status=d.status, resolution=d.resolution, headline=e.get("headline", ""),
        recommended_action=e.get("recommended_action", ""), checks=e.get("checks", []), comparison=e.get("comparison"),
        ignored=e.get("ignored", []),
        flags=[FlagOut(code=f.code, name=f.name, severity=f.severity, effect=f.effect, message=f.message, detail=f.detail,
                       source_ref=f.source_ref, recommended_action=f.recommended_action) for f in d.flags],
        rules_version=d.rules_version, acknowledged_items=d.acknowledged_items, override_reason=d.override_reason,
        resolved_at=d.resolved_at, created_at=d.created_at, can_ship=ok, can_ship_reason=why,
    )


def _order(db: Session, order_id: str) -> Order:
    order = db.get(Order, order_id)
    if order is None:
        raise AppError("ORDER_NOT_FOUND", "Order not found.", 404)
    return order


@router.post("/evaluate", response_model=DecisionOut)
def run_evaluation(order_id: str, db: Session = Depends(get_db), settings: Settings = Depends(settings_dep)):
    _order(db, order_id)
    return decision_out(evaluate_order(db, settings, order_id, actor="SELLER", reason="manual re-check"))


@router.get("/decision", response_model=DecisionOut)
def get_decision(order_id: str, db: Session = Depends(get_db), settings: Settings = Depends(settings_dep)):
    _order(db, order_id)
    d = active_decision(db, order_id) or evaluate_order(db, settings, order_id, reason="first view")
    return decision_out(d)


@router.post("/decision/acknowledge", response_model=DecisionOut)
def acknowledge_decision(order_id: str, body: AcknowledgeIn, db: Session = Depends(get_db)):
    _order(db, order_id)
    return decision_out(acknowledge(db, order_id, items=body.items, reason=body.reason, confirm_void=body.confirm_void))
