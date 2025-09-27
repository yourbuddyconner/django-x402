import base64
import json
from typing import Any, Dict

import pytest
from django.test import Client


@pytest.fixture
def client() -> Client:
    return Client()


def _payment() -> Dict[str, Any]:
    return {
        "x402Version": 1,
        "scheme": "exact",
        "network": "base-sepolia",
        "payload": {
            "signature": "0xdeadbeef",
            "authorization": {
                "from": "0xPAYER",
                "to": "0xPAYEE",
                "value": "10000",
                "validAfter": "0",
                "validBefore": "9999999999",
                "nonce": "0x1",
            },
        },
    }


def _requirements() -> Dict[str, Any]:
    return {
        "scheme": "exact",
        "network": "base-sepolia",
        "asset": "0xUSDC",
        "maxAmountRequired": "10000",
        "resource": "https://testserver/api/premium/data",
        "description": "Premium API call",
        "mimeType": "application/json",
        "payTo": "0xPAYEE",
        "maxTimeoutSeconds": 60,
    }


def test_verify_endpoint_calls_facilitator(client: Client, monkeypatch):
    class FakeFac:
        def verify(self, payment, req):
            return {"isValid": True, "payer": "0xPAYER"}

    import django_x402.facilitators as fac
    monkeypatch.setattr(fac, "get_facilitator_from_settings", lambda: FakeFac())

    resp = client.post(
        "/x402/facilitator/verify",
        data=json.dumps({"payment": _payment(), "requirements": _requirements()}),
        content_type="application/json",
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body.get("isValid") is True


def test_settle_endpoint_calls_facilitator(client: Client, monkeypatch):
    class FakeFac:
        def settle(self, payment, req):
            return {"success": True, "transaction": "0xabc"}

    import django_x402.facilitators as fac
    monkeypatch.setattr(fac, "get_facilitator_from_settings", lambda: FakeFac())

    resp = client.post(
        "/x402/facilitator/settle",
        data=json.dumps({"payment": _payment(), "requirements": _requirements()}),
        content_type="application/json",
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body.get("success") is True
    assert body.get("transaction")


