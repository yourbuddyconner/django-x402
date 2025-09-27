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


def _valid_payment() -> Dict[str, Any]:
    return {
        "x402Version": 1,
        "scheme": "exact",
        "network": "base-sepolia",
        "payload": {
            "signature": "0x",
            "authorization": {
                "from": "0xfrom",
                "to": "0xTEST",
                "value": "1",
                "validAfter": "0",
                "validBefore": "9999999999",
                "nonce": "0x1",
            },
        },
    }


def test_settle_policy_log_and_continue_keeps_2xx(client: Client, settings, monkeypatch):
    settings.X402 = {**settings.X402, "settle_policy": "log-and-continue"}

    import django_x402.middleware as mw

    monkeypatch.setattr(mw, "verify_payment", lambda h, r: {"isValid": True})
    monkeypatch.setattr(mw, "settle_payment", lambda h, r: {"success": False})

    resp = client.get("/api/premium/data", HTTP_X_PAYMENT=_enc(_valid_payment()))
    assert resp.status_code == 200
    assert "X-PAYMENT-RESPONSE" not in resp


