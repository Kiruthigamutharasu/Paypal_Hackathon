from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import Settings
from app.deps import get_db, settings_dep

router = APIRouter(tags=["health"])


@router.get("/api/health")
def health(db: Session = Depends(get_db), settings: Settings = Depends(settings_dep)):
    """Config sanity without secrets."""
    try:
        db.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        db_ok = False
    return {
        "status": "ok" if db_ok else "degraded",
        "paypal_environment": settings.PAYPAL_ENVIRONMENT,
        "paypal_credentials_configured": settings.paypal_configured,
        "webhook_id_configured": bool(settings.PAYPAL_WEBHOOK_ID),
        "database": "ok" if db_ok else "error",
        "database_backend": settings.database_url.split(":", 1)[0],
        "ai_provider": settings.AI_PROVIDER,
    }
