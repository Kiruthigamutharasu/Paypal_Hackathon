import httpx
import pytest
import respx

from app.config import get_settings
from app.services.paypal.client import PayPalClient
from app.services.paypal.errors import PayPalError

BASE = "https://api-m.sandbox.paypal.com"


class FakeClock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


def token_route(mock, expires_in=3600):
    counter = {"n": 0}

    def handler(_req):
        counter["n"] += 1
        return httpx.Response(200, json={"access_token": f"tok-{counter['n']}", "expires_in": expires_in})

    mock.post("/v1/oauth2/token").mock(side_effect=handler)
    return counter


@pytest.fixture
def mock():
    with respx.mock(base_url=BASE) as m:
        yield m


def make_client(clock=None, sleeps=None, calls=None):
    return PayPalClient(
        get_settings(),
        clock=clock or FakeClock(),
        sleep=(sleeps.append if sleeps is not None else (lambda _s: None)),
        on_call=(calls.append if calls is not None else None),
    )


def test_token_is_cached_until_near_expiry(mock):  # AC1.5
    clock = FakeClock()
    counter = token_route(mock, expires_in=3600)
    route = mock.get("/v2/checkout/orders/X1").respond(200, json={"id": "X1"})
    c = make_client(clock)

    c.request("GET", "/v2/checkout/orders/X1")
    clock.t += 3000  # still > 5 min before expiry
    c.request("GET", "/v2/checkout/orders/X1")
    assert counter["n"] == 1

    clock.t += 400  # now inside the 5-minute refresh margin
    c.request("GET", "/v2/checkout/orders/X1")
    assert counter["n"] == 2
    assert route.calls[-1].request.headers["Authorization"] == "Bearer tok-2"


def test_expired_token_401_is_refreshed_transparently(mock):  # AC1.5
    counter = token_route(mock)
    mock.get("/v2/checkout/orders/X1").mock(
        side_effect=[httpx.Response(401, json={"name": "AUTHENTICATION_FAILURE"}), httpx.Response(200, json={"id": "X1"})]
    )
    c = make_client()
    assert c.request("GET", "/v2/checkout/orders/X1") == {"id": "X1"}
    assert counter["n"] == 2


def test_retries_with_backoff_on_5xx_then_succeeds(mock):
    token_route(mock)
    sleeps: list[float] = []
    mock.get("/v2/checkout/orders/X1").mock(
        side_effect=[httpx.Response(503), httpx.Response(500), httpx.Response(200, json={"id": "X1"})]
    )
    c = make_client(sleeps=sleeps)
    assert c.request("GET", "/v2/checkout/orders/X1")["id"] == "X1"
    assert sleeps == [0.5, 1.0]


def test_429_respects_retry_after(mock):
    token_route(mock)
    sleeps: list[float] = []
    mock.get("/x").mock(side_effect=[httpx.Response(429, headers={"Retry-After": "3"}), httpx.Response(200, json={})])
    make_client(sleeps=sleeps).request("GET", "/x")
    assert sleeps == [3.0]


def test_gives_up_after_max_retries(mock):
    token_route(mock)
    route = mock.get("/x").respond(503, json={"name": "SERVICE_UNAVAILABLE"}, headers={"paypal-debug-id": "dbg1"})
    with pytest.raises(PayPalError) as ei:
        make_client().request("GET", "/x")
    assert ei.value.retryable and ei.value.debug_id == "dbg1"
    assert route.call_count == 4  # 1 + 3 retries


def test_4xx_raises_with_debug_id_and_issue(mock):
    token_route(mock)
    mock.post("/v2/checkout/orders/X1/capture").respond(
        422,
        json={
            "name": "UNPROCESSABLE_ENTITY",
            "message": "The requested action could not be performed",
            "debug_id": "abc123",
            "details": [{"issue": "INSTRUMENT_DECLINED"}],
        },
    )
    with pytest.raises(PayPalError) as ei:
        make_client().request("POST", "/v2/checkout/orders/X1/capture", json={}, request_id="r1")
    err = ei.value
    assert err.status_code == 422 and err.debug_id == "abc123"
    assert err.has_issue("INSTRUMENT_DECLINED") and not err.retryable


def test_post_sends_request_id_and_reports_call_without_secrets(mock):
    token_route(mock)
    route = mock.post("/v2/checkout/orders").respond(201, json={"id": "X1"}, headers={"paypal-debug-id": "d-9"})
    calls: list[dict] = []
    make_client(calls=calls).request("POST", "/v2/checkout/orders", json={}, request_id="stable-1")
    assert route.calls[0].request.headers["PayPal-Request-Id"] == "stable-1"
    assert calls[0]["debug_id"] == "d-9" and calls[0]["status"] == 201
    flat = str(calls)
    assert "Bearer" not in flat and "tok-" not in flat and "test-client-secret" not in flat


def test_post_without_explicit_request_id_still_gets_one(mock):
    token_route(mock)
    route = mock.post("/y").respond(200, json={})
    make_client().request("POST", "/y", json={})
    assert route.calls[0].request.headers.get("PayPal-Request-Id")
