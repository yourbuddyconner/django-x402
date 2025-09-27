import base64
import json
from typing import Any, Dict

import pytest
from django.test import Client


def _enc(obj: Dict[str, Any]) -> str:
    return base64.b64encode(json.dumps(obj).encode("utf-8")).decode("ascii")


@pytest.fixture
def client() -> Client:
    return Client()


def _valid_payment(network: str = "base-sepolia") -> Dict[str, Any]:
    return {
        "x402Version": 1,
        "scheme": "exact",
        "network": network,
        "payload": {
            "signature": "0x",
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


def test_paywall_html_when_browser_accepts_html(client: Client):
    resp = client.get(
        "/api/premium/data",
        HTTP_ACCEPT="text/html",
        HTTP_USER_AGENT="Mozilla/5.0",
    )
    assert resp.status_code == 402
    assert resp["Content-Type"].startswith("text/html")


def test_no_matching_payment_requirements_returns_402(client: Client):
    payload = _valid_payment(network="base-mainnet")
    resp = client.get("/api/premium/data", HTTP_X_PAYMENT=_enc(payload))
    assert resp.status_code == 402
    body = resp.json()
    assert "No matching payment requirements" in body["error"]


def test_verification_invalid_returns_402(client: Client, monkeypatch):
    import django_x402.middleware as mw

    def fake_verify(h: str, req: Dict[str, Any]):
        return {"isValid": False, "invalidReason": "expired"}

    monkeypatch.setattr(mw, "verify_payment", fake_verify)

    resp = client.get("/api/premium/data", HTTP_X_PAYMENT=_enc(_valid_payment()))
    assert resp.status_code == 402
    assert "Invalid payment: expired" in resp.json()["error"]


def test_settle_failed_returns_402(client: Client, monkeypatch):
    import django_x402.middleware as mw

    monkeypatch.setattr(mw, "verify_payment", lambda h, r: {"isValid": True})
    monkeypatch.setattr(mw, "settle_payment", lambda h, r: {"success": False, "error_reason": "nope"})

    resp = client.get("/api/premium/data", HTTP_X_PAYMENT=_enc(_valid_payment()))
    assert resp.status_code == 402
    assert "Settle failed" in resp.json()["error"]


def test_unprotected_path_pass_through(client: Client, settings):
    settings.X402 = {**settings.X402, "paths": ["/api/other/*"]}
    resp = client.get("/public/ok")
    assert resp.status_code == 200

