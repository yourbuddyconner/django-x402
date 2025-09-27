import base64
import json
from typing import Dict, Any

import pytest
from django.test import Client


@pytest.fixture
def client() -> Client:
    return Client()


def _encode_payment_header(payload: Dict[str, Any]) -> str:
    return base64.b64encode(json.dumps(payload).encode("utf-8")).decode("ascii")


def test_missing_payment_header_returns_402_json(client: Client):
    response = client.get("/api/premium/data")
    assert response.status_code == 402
    body = response.json()
    assert "x402Version" in body
    assert "accepts" in body
    assert isinstance(body["accepts"], list)


def test_bad_payment_header_returns_402_with_error(client: Client):
    response = client.get("/api/premium/data", HTTP_X_PAYMENT="not-base64!!")
    assert response.status_code == 402
    body = response.json()
    assert body.get("error")


def test_valid_payment_header_allows_request_and_sets_response_header(client: Client, monkeypatch):
    def fake_verify(payment_header: str, payment_requirements: Dict[str, Any]):
        return {"isValid": True}

    def fake_settle(payment_header: str, payment_requirements: Dict[str, Any]):
        return {"success": True, "transaction": "0x123"}

    import django_x402.middleware as mw

    monkeypatch.setattr(mw, "verify_payment", fake_verify)
    monkeypatch.setattr(mw, "settle_payment", fake_settle)

    payment_payload = {
        "x402Version": 1,
        "scheme": "exact",
        "network": "base-sepolia",
        "payload": {
            "signature": "0x",  # not validated by our test stubs
            "authorization": {
                "from": "0xfrom",
                "to": "0xto",
                "value": "1",
                "validAfter": "0",
                "validBefore": "9999999999",
                "nonce": "0x1",
            },
        },
    }
    encoded = _encode_payment_header(payment_payload)

    response = client.get("/api/premium/data", HTTP_X_PAYMENT=encoded)
    assert response.status_code == 200
    assert response["X-PAYMENT-RESPONSE"]


