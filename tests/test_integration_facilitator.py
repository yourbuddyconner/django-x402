import base64
import json
from typing import Any, Dict
import httpx

import pytest
import respx
from django.test import Client


def _encode_payment_header(payload: Dict[str, Any]) -> str:
    return base64.b64encode(json.dumps(payload).encode("utf-8")).decode("ascii")


@pytest.fixture
def client() -> Client:
    return Client()


@respx.mock
def test_verify_and_settle_via_facilitator_http(client: Client, settings):
    settings.X402 = {
        "paths": ["/api/premium/"],
        # Use glob to match nested path
        "paths": ["/api/premium/*"],
        "network": "base-sepolia",
        "price": "$0.01",
        "pay_to_address": "0xTEST",
        "mime_type": "application/json",
        "description": "Premium API call",
        "max_deadline_seconds": 60,
        "facilitator_config": {"url": "https://fac.local"},
    }

    respx.post("https://fac.local/verify").mock(return_value=httpx.Response(200, json={"isValid": True, "payer": "0xabc"}))
    respx.post("https://fac.local/settle").mock(return_value=httpx.Response(200, json={"success": True, "transaction": "0x123"}))

    payment_payload = {
        "x402Version": 1,
        "scheme": "exact",
        "network": "base-sepolia",
        "payload": {
            "signature": "0xdeadbeef",
            "authorization": {
                "from": "0xpayer",
                "to": "0xTEST",
                "value": "1",
                "validAfter": "0",
                "validBefore": "9999999999",
                "nonce": "0x1",
            },
        },
    }
    encoded = _encode_payment_header(payment_payload)

    resp = client.get("/api/premium/data", HTTP_X_PAYMENT=encoded)
    assert resp.status_code == 200
    assert resp["X-PAYMENT-RESPONSE"]


