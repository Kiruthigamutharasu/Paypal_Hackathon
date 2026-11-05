"""StayCovered API."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import decision, disputes, evidence, fulfilment, health, orders, shop, webhooks
from app.config import assert_sandbox, get_settings
from app.errors import install_error_handlers

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def create_app() -> FastAPI:
    settings = get_settings()
    assert_sandbox(settings)  # AC1.4: refuse to start with non-sandbox config

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        assert_sandbox(get_settings())
        yield

    app = FastAPI(title="StayCovered API", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.FRONTEND_ORIGIN.rstrip("/")],
        allow_methods=["GET", "POST", "PATCH"],
        allow_headers=["Content-Type"],
    )
    install_error_handlers(app)
    for module in (health, shop, orders, webhooks, evidence, decision, fulfilment, disputes):
        app.include_router(module.router)
    return app


app = create_app()
