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


def _payment(nonce: str) -> Dict[str, Any]:
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
                "nonce": nonce,
            },
        },
    }


def test_repeated_nonce_returns_cached_settle_and_avoids_second_settlement(client: Client, settings, monkeypatch):
    settings.X402 = {**settings.X402, "replay_cache_backend": "memory"}
    from django_x402 import middleware as mw

    calls = {"settle": 0}

    def fake_verify(h, r):
        return {"isValid": True}

    def fake_settle(h, r):
        calls["settle"] += 1
        return {"success": True, "transaction": "0xabc"}

    monkeypatch.setattr(mw, "verify_payment", fake_verify)
    monkeypatch.setattr(mw, "settle_payment", fake_settle)

    resp1 = client.get("/api/premium/data", HTTP_X_PAYMENT=_enc(_payment("0x01")))
    assert resp1.status_code == 200
    header1 = resp1["X-PAYMENT-RESPONSE"]

    resp2 = client.get("/api/premium/data", HTTP_X_PAYMENT=_enc(_payment("0x01")))
    assert resp2.status_code == 200
    header2 = resp2["X-PAYMENT-RESPONSE"]

    assert header1 == header2
    assert calls["settle"] == 1


