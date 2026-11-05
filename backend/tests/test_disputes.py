"""F5: dispute sync, evidence planning, claim verification, submission rules (PayPal mocked)."""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.deps import get_ai_provider_factory, get_paypal_client
from app.models import Dispute, EvidenceSubmission, Order, Shipment
from app.rules.claims import Facts, verify
from app.services.reconcile import reconcile_order
from app.workflows.disputes import deadline_flag
from tests import factories as f
from tests.test_fulfilment import add_evidence, mock_original

DID = "PP-D-4521"
TRACK = "9400111899223344556677"


def dispute_payload(reason="MERCHANDISE_OR_SERVICE_NOT_RECEIVED", status="WAITING_FOR_SELLER_RESPONSE", actions=True, due_days=10):
    due = (datetime.now(timezone.utc) + timedelta(days=due_days)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    links = [{"href": f"https://api-m.sandbox.paypal.com/v1/customer/disputes/{DID}", "rel": "self", "method": "GET"}]
    if actions:
        links += [{"href": f"https://api-m.sandbox.paypal.com/v1/customer/disputes/{DID}/provide-evidence", "rel": "provide_evidence", "method": "POST"},
                  {"href": f"https://api-m.sandbox.paypal.com/v1/customer/disputes/{DID}/accept-claim", "rel": "accept_claim", "method": "POST"}]
    return {"dispute_id": DID, "create_time": "2026-11-06T10:00:00.000Z", "reason": reason, "status": status,
            "dispute_life_cycle_stage": "INQUIRY", "dispute_amount": {"currency_code": "USD", "value": "300.00"},
            "seller_response_due_date": due, "disputed_transactions": [{"seller_transaction_id": f.CAPTURE_ID}],
            "messages": [{"posted_by": "BUYER", "content": "I never got it"}], "links": links}


@pytest.fixture
def api(db, client_pp):
    from app.main import app

    app.dependency_overrides[get_paypal_client] = lambda: client_pp
    app.dependency_overrides[get_ai_provider_factory] = lambda: (lambda: None)  # template note, no AI quota
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def shipped_order(db, paypal_mock, client_pp):
    mock_original(paypal_mock)
    order = reconcile_order(db, client_pp, f.ORDER_ID)
    add_evidence(db, order, chat_request=False)
    from app.config import get_settings
    from app.workflows.verification import evaluate_order

    assert evaluate_order(db, get_settings(), order.id).verdict == "GREEN"
    db.add(Shipment(order_id=order.id, paypal_order_id=f.ORDER_ID, capture_id=f.CAPTURE_ID, carrier="USPS", tracking_number=TRACK,
                    ship_date="2026-11-05", paypal_tracker_id=f"{f.CAPTURE_ID}-{TRACK}", status="SHIPPED",
                    registered_at=datetime(2026, 11, 5, 12, tzinfo=timezone.utc)))
    o = db.get(Order, order.id)
    o.shipment_state = "SHIPPED"
    db.commit()
    return order


def sync(api, paypal_mock, **kw):
    paypal_mock.get(f"/v1/customer/disputes/{DID}").respond(200, json=dispute_payload(**kw))
    paypal_mock.get("/v1/customer/disputes").respond(200, json={"items": [{"dispute_id": DID}]})
    assert api.post("/api/disputes/sync").json() == {"synced": [DID]}
    return api.get("/api/disputes").json()[0]


# ---------------- claim verifier ----------------
FACTS = Facts(tracking_numbers={TRACK}, ids={f.ORDER_ID, f.CAPTURE_ID}, amounts={Decimal("300.00")},
              dates={date(2026, 11, 4), date(2026, 11, 5)}, zips={"10001"})


@pytest.mark.parametrize("note,ok", [
    (f"I shipped it on 2026-11-05 with USPS, tracking number {TRACK}, to New York, NY 10001.", True),
    ("I sold the necklace for $300.00 through PayPal. Tracking was registered with PayPal on Nov 5, 2026.", True),
    ("Tracking 9400 1118 9922 3344 5566 77 shows it left on 2026-11-05.", True),
    ("I shipped it on 2026-11-07.", False),                         # unknown date
    ("Tracking number 1Z999AA10123456784.", False),                  # unknown tracking
    ("The buyer paid $450.00.", False),                              # wrong amount
    ("It went to ZIP 90210.", False),                                # wrong ZIP
    ("The parcel was delivered to the buyer.", False),               # no delivery confirmation
    ("The buyer signed for it with a signature.", False),            # no signature on record
    ("The parcel has not been delivered yet according to tracking.", True),
])
def test_claim_verifier(note, ok):  # AC5.2
    assert verify(note, FACTS).passed is ok


def test_claim_verifier_points_at_the_sentence():
    c = verify(f"I shipped with USPS, tracking {TRACK}. It was delivered on 2026-11-09.", FACTS)
    assert not c.passed and c.sentences[0].ok and not c.sentences[1].ok and len(c.sentences[1].problems) == 2


def test_deadline_flags():
    now = datetime(2026, 11, 10, tzinfo=timezone.utc)
    d = Dispute(paypal_dispute_id="x", seller_response_due_date=now + timedelta(hours=30))
    assert deadline_flag(d, now) == "DIS-10"
    d.seller_response_due_date = now - timedelta(minutes=1)
    assert deadline_flag(d, now) == "DIS-11"
    d.seller_response_due_date = now + timedelta(days=5)
    assert deadline_flag(d, now) is None


# ---------------- sync & planning ----------------
def test_sync_links_dispute_to_order_and_dedupes(api, db, shipped_order, paypal_mock):  # AC5.5
    row = sync(api, paypal_mock)
    assert row["order_id"] == shipped_order.id and row["reason"] == "MERCHANDISE_OR_SERVICE_NOT_RECEIVED"
    assert "provide-evidence" in row["allowed_actions"] and row["deadline_flag"] is None
    api.post("/api/disputes/sync")
    assert db.scalar(select(func.count()).select_from(Dispute)) == 1
    assert api.get("/api/orders").json()[0]["dispute_state"] == "WAITING_FOR_SELLER_RESPONSE"


def test_inr_plan_uses_proof_of_fulfillment_with_tracking(api, shipped_order, paypal_mock):  # AC5.1
    d = sync(api, paypal_mock)
    detail = api.post(f"/api/disputes/{d['id']}/plan").json()
    pack = detail["pack"]
    assert pack["supported"] and pack["plan"]["evidence_type"] == "PROOF_OF_FULFILLMENT"
    assert pack["plan"]["tracking_info"] == [{"carrier_name": "USPS", "tracking_number": TRACK}]
    assert pack["claim_check"]["passed"] and pack["status"] == "READY" and pack["note_source"] == "TEMPLATE"
    assert TRACK in pack["note"]
    assert {fl["filename"] for fl in pack["files"]} == {"shipping-label.png", "evidence-summary.pdf"}
    pdf = api.get(f"/api/disputes/{d['id']}/files/{[x for x in pack['files'] if x['kind'] == 'GENERATED'][0]['id']}")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")


def test_unsupported_reason_gives_manual_checklist(api, shipped_order, paypal_mock):
    d = sync(api, paypal_mock, reason="MERCHANDISE_OR_SERVICE_NOT_AS_DESCRIBED")
    pack = api.post(f"/api/disputes/{d['id']}/plan").json()["pack"]
    assert not pack["supported"] and pack["plan"]["manual_checklist"] and pack["status"] == "DRAFT"
    r = api.post(f"/api/disputes/{d['id']}/submit", json={"pack_id": pack["id"], "confirm": True})
    assert r.status_code == 409 and r.json()["error_code"] == "UNSUPPORTED_REASON"


def test_no_tracking_blocks_ready(api, db, shipped_order, paypal_mock):
    db.query(Shipment).delete()
    db.commit()
    d = sync(api, paypal_mock)
    pack = api.post(f"/api/disputes/{d['id']}/plan").json()["pack"]
    assert pack["status"] == "DRAFT" and any("tracking" in m.lower() for m in pack["plan"]["missing"])


def test_injected_claim_blocks_submission(api, shipped_order, paypal_mock):  # AC5.2
    d = sync(api, paypal_mock)
    pack = api.post(f"/api/disputes/{d['id']}/plan").json()["pack"]
    edited = api.put(f"/api/disputes/{d['id']}/note", json={"note": pack["note"] + " The buyer confirmed delivery on 2026-11-08."}).json()["pack"]
    assert edited["status"] == "DRAFT" and not edited["claim_check"]["passed"] and edited["note_source"] == "SELLER"
    r = api.post(f"/api/disputes/{d['id']}/submit", json={"pack_id": edited["id"], "confirm": True})
    assert r.status_code == 409 and r.json()["error_code"] == "EVD-08"


# ---------------- submission ----------------
def test_submit_sends_multipart_once_per_version(api, db, shipped_order, paypal_mock):  # AC5.3
    d = sync(api, paypal_mock)
    pack = api.post(f"/api/disputes/{d['id']}/plan").json()["pack"]
    assert api.post(f"/api/disputes/{d['id']}/submit", json={"pack_id": pack["id"], "confirm": False}).status_code == 422
    route = paypal_mock.post(f"/v1/customer/disputes/{DID}/provide-evidence").respond(200, json={"links": []})
    r = api.post(f"/api/disputes/{d['id']}/submit", json={"pack_id": pack["id"], "confirm": True})
    assert r.status_code == 200 and r.json()["pack"]["status"] == "SUBMITTED"
    req = route.calls[0].request
    assert req.headers["content-type"].startswith("multipart/form-data")
    body = req.content
    assert b'name="input"' in body and body.count(b'name="evidence-file"') == 2
    start = body.index(b'{"evidences"')
    payload = json.loads(body[start: body.index(b"\r\n", start)])
    ev = payload["evidences"][0]
    assert ev["evidence_type"] == "PROOF_OF_FULFILLMENT" and ev["evidence_info"]["tracking_info"][0]["tracking_number"] == TRACK
    assert req.headers["PayPal-Request-Id"] == f"evidence-{pack['id']}-v1"
    again = api.post(f"/api/disputes/{d['id']}/submit", json={"pack_id": pack["id"], "confirm": True})
    assert again.status_code == 200 and route.call_count == 1
    assert db.scalar(select(func.count()).select_from(EvidenceSubmission)) == 1


def test_submit_blocked_when_action_not_available(api, shipped_order, paypal_mock):
    d = sync(api, paypal_mock)
    pack = api.post(f"/api/disputes/{d['id']}/plan").json()["pack"]
    paypal_mock.get(f"/v1/customer/disputes/{DID}").respond(200, json=dispute_payload(status="UNDER_REVIEW", actions=False))
    r = api.post(f"/api/disputes/{d['id']}/submit", json={"pack_id": pack["id"], "confirm": True})
    assert r.status_code == 409 and r.json()["error_code"] == "ACTION_NOT_AVAILABLE"


def test_submit_blocked_after_deadline(api, shipped_order, paypal_mock):
    d = sync(api, paypal_mock, due_days=-1)
    assert d["deadline_flag"] == "DIS-11"
    pack = api.post(f"/api/disputes/{d['id']}/plan").json()["pack"]
    r = api.post(f"/api/disputes/{d['id']}/submit", json={"pack_id": pack["id"], "confirm": True})
    assert r.status_code == 409 and r.json()["error_code"] == "DIS-11"


def test_paypal_rejection_keeps_draft(api, shipped_order, paypal_mock):
    d = sync(api, paypal_mock)
    pack = api.post(f"/api/disputes/{d['id']}/plan").json()["pack"]
    paypal_mock.post(f"/v1/customer/disputes/{DID}/provide-evidence").respond(
        422, json={"name": "UNPROCESSABLE_ENTITY", "debug_id": "dbgE", "details": [{"issue": "INVALID_EVIDENCE_FILE"}]})
    r = api.post(f"/api/disputes/{d['id']}/submit", json={"pack_id": pack["id"], "confirm": True})
    assert r.status_code == 502 and r.json()["details"]["paypal_debug_id"] == "dbgE"
    detail = api.get(f"/api/disputes/{d['id']}").json()
    assert detail["pack"]["status"] == "READY"  # draft preserved for a corrected retry


def test_timeout_refetches_before_retry(api, shipped_order, paypal_mock):
    d = sync(api, paypal_mock)
    pack = api.post(f"/api/disputes/{d['id']}/plan").json()["pack"]
    paypal_mock.post(f"/v1/customer/disputes/{DID}/provide-evidence").mock(side_effect=httpx.ConnectTimeout("timeout"))
    # PayPal actually received it: the dispute no longer offers provide-evidence
    gets = paypal_mock.get(f"/v1/customer/disputes/{DID}")
    gets.side_effect = [httpx.Response(200, json=dispute_payload()), httpx.Response(200, json=dispute_payload(status="UNDER_REVIEW", actions=False)),
                        httpx.Response(200, json=dispute_payload(status="UNDER_REVIEW", actions=False))]
    r = api.post(f"/api/disputes/{d['id']}/submit", json={"pack_id": pack["id"], "confirm": True})
    assert r.status_code == 200 and r.json()["pack"]["status"] == "SUBMITTED"


def test_sandbox_settle_calls_adjudicate(api, shipped_order, paypal_mock):
    d = sync(api, paypal_mock, status="UNDER_REVIEW")
    adj = paypal_mock.post(f"/v1/customer/disputes/{DID}/adjudicate").respond(200, json={"links": []})
    r = api.post(f"/api/sandbox/disputes/{d['id']}/action", json={"action": "SELLER_FAVOR"})
    assert r.status_code == 200 and json.loads(adj.calls[0].request.content) == {"adjudication_outcome": "SELLER_FAVOR"}
