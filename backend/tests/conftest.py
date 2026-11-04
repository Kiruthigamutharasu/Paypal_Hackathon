"""Test setup: isolated SQLite DB, fake sandbox credentials, PayPal mocked with respx."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

# Must be set before any `app` import: env vars override the root .env file.
_TMP = Path(tempfile.mkdtemp(prefix="staycovered-tests-"))
os.environ.update(
    {
        "PAYPAL_ENVIRONMENT": "sandbox",
        "PAYPAL_BASE_URL": "https://api-m.sandbox.paypal.com",
        "PAYPAL_CLIENT_ID": "test-client-id",
        "PAYPAL_CLIENT_SECRET": "test-client-secret",
        "PAYPAL_WEBHOOK_ID": "WH-TEST-123",
        "DATABASE_URL": f"sqlite:///{(_TMP / 'test.db').as_posix()}",
        "FRONTEND_ORIGIN": "http://localhost:3000",
    }
)

import pytest  # noqa: E402
import respx  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import db as dbm  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.db import Base  # noqa: E402
from app.deps import get_paypal_client  # noqa: E402
from app.services.paypal.client import PayPalClient  # noqa: E402

BASE = "https://api-m.sandbox.paypal.com"


@pytest.fixture(autouse=True)
def fresh_db():
    Base.metadata.drop_all(dbm.engine)
    Base.metadata.create_all(dbm.engine)
    yield


@pytest.fixture
def db():
    with dbm.SessionLocal() as session:
        yield session


@pytest.fixture
def paypal_mock():
    with respx.mock(base_url=BASE, assert_all_called=False) as mock:
        mock.post("/v1/oauth2/token").respond(
            200, json={"access_token": "A21-test-token", "expires_in": 32400, "token_type": "Bearer"}
        )
        yield mock


@pytest.fixture
def client_pp(paypal_mock) -> PayPalClient:
    return PayPalClient(get_settings(), sleep=lambda _s: None)


@pytest.fixture
def api(client_pp):
    from app.main import app

    app.dependency_overrides[get_paypal_client] = lambda: client_pp
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
