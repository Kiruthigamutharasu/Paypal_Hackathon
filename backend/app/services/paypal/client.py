"""Single entry point for every PayPal REST call (CLAUDE.md coding standards).

- OAuth client-credentials token, cached in memory, refreshed ~5 min before expiry
- Retries with exponential backoff on 429 / 5xx / transport errors (max 3 retries)
- `PayPal-Request-Id` on POSTs (stable IDs supplied by callers for idempotency)
- Captures `paypal-debug-id`; reports each call to an optional hook (audit log)
- Never logs secrets or Authorization headers
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from collections.abc import Callable
from typing import Any

import httpx

from app.config import Settings
from app.services.paypal.errors import PayPalError

log = logging.getLogger("staycovered.paypal")

TOKEN_REFRESH_MARGIN_S = 300
MAX_RETRIES = 3
RETRYABLE_STATUS = {429, 500, 502, 503, 504}

CallHook = Callable[[dict[str, Any]], None]


class PayPalClient:
    def __init__(
        self,
        settings: Settings,
        http: httpx.Client | None = None,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        on_call: CallHook | None = None,
        backoff_base: float = 0.5,
    ) -> None:
        self.base_url = settings.PAYPAL_BASE_URL.rstrip("/")
        self._client_id = settings.PAYPAL_CLIENT_ID
        self._secret = settings.PAYPAL_CLIENT_SECRET
        self._http = http or httpx.Client(timeout=httpx.Timeout(30.0, connect=10.0))
        self._clock = clock
        self._sleep = sleep
        self._backoff_base = backoff_base
        self.on_call = on_call
        self._token: str | None = None
        self._token_expires_at = 0.0
        self._lock = threading.Lock()

    # ---------- auth ----------
    def _fetch_token(self) -> None:
        if not (self._client_id and self._secret):
            raise PayPalError(401, "MISSING_CREDENTIALS", "PayPal client ID/secret are not configured.")
        resp = self._http.post(
            f"{self.base_url}/v1/oauth2/token",
            data={"grant_type": "client_credentials"},
            auth=(self._client_id, self._secret),
            headers={"Accept": "application/json"},
        )
        if resp.status_code != 200:
            raise self._error_from(resp)
        body = resp.json()
        self._token = body["access_token"]
        self._token_expires_at = self._clock() + float(body.get("expires_in", 0))

    def get_token(self, *, force: bool = False) -> str:
        with self._lock:
            if force or not self._token or self._clock() >= self._token_expires_at - TOKEN_REFRESH_MARGIN_S:
                self._fetch_token()
            assert self._token
            return self._token

    def invalidate_token(self) -> None:
        with self._lock:
            self._token = None
            self._token_expires_at = 0.0

    # ---------- requests ----------
    def request(
        self,
        method: str,
        path: str,
        *,
        json: Any = None,
        params: dict[str, Any] | None = None,
        request_id: str | None = None,
        extra_headers: dict[str, str] | None = None,
        order_id: str | None = None,
    ) -> dict[str, Any]:
        method = method.upper()
        url = f"{self.base_url}{path}"
        if method == "POST" and not request_id:
            request_id = str(uuid.uuid4())
        attempt = 0
        refreshed_after_401 = False
        while True:
            headers = {
                "Authorization": f"Bearer {self.get_token()}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            }
            if request_id:
                headers["PayPal-Request-Id"] = request_id
            if extra_headers:
                headers.update(extra_headers)
            started = self._clock()
            try:
                resp = self._http.request(method, url, json=json, params=params, headers=headers)
            except httpx.TransportError as exc:
                if attempt < MAX_RETRIES:
                    self._backoff(attempt, None)
                    attempt += 1
                    continue
                self._report(method, path, None, None, request_id, order_id, started, error=type(exc).__name__)
                raise PayPalError(503, "NETWORK_ERROR", str(exc) or "Network error", retryable=True) from exc

            debug_id = resp.headers.get("paypal-debug-id")
            if resp.status_code == 401 and not refreshed_after_401:
                refreshed_after_401 = True  # token revoked/expired early -> refresh once
                self.invalidate_token()
                continue
            if resp.status_code in RETRYABLE_STATUS and attempt < MAX_RETRIES:
                self._backoff(attempt, resp.headers.get("Retry-After"))
                attempt += 1
                continue

            self._report(method, path, resp.status_code, debug_id, request_id, order_id, started)
            if resp.status_code >= 400:
                raise self._error_from(resp)
            if resp.status_code == 204 or not resp.content:
                return {}
            return resp.json()

    def _backoff(self, attempt: int, retry_after: str | None) -> None:
        delay = self._backoff_base * (2**attempt)
        if retry_after:
            try:
                delay = max(delay, float(retry_after))
            except ValueError:
                pass
        self._sleep(min(delay, 10.0))

    def _report(self, method, path, status, debug_id, request_id, order_id, started, error=None) -> None:
        record = {
            "method": method,
            "path": path,
            "status": status,
            "debug_id": debug_id,
            "request_id": request_id,
            "order_id": order_id,
            "latency_ms": int((self._clock() - started) * 1000),
        }
        if error:
            record["error"] = error
        log.info("paypal %s %s -> %s debug_id=%s", method, path, status, debug_id)
        if self.on_call:
            try:
                self.on_call(record)
            except Exception:
                log.exception("paypal on_call hook failed")

    @staticmethod
    def _error_from(resp: httpx.Response) -> PayPalError:
        debug_id = resp.headers.get("paypal-debug-id")
        name = message = None
        details: list[dict[str, Any]] = []
        try:
            body = resp.json()
            name = body.get("name") or body.get("error")
            message = body.get("message") or body.get("error_description")
            details = body.get("details") or []
            debug_id = body.get("debug_id") or debug_id
        except ValueError:
            message = resp.text[:300] if resp.text else None
        return PayPalError(
            resp.status_code,
            name,
            message,
            debug_id,
            details,
            retryable=resp.status_code in RETRYABLE_STATUS,
        )
