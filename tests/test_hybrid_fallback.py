import base64
import json
from typing import Any, Dict

import pytest
import respx
import httpx
from django.test import Client


def _encode(obj: Dict[str, Any]) -> str:
    return base64.b64encode(json.dumps(obj).encode("utf-8")).decode("ascii")


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
                "to": "0xTEST",
                "value": "1",
                "validAfter": "0",
                "validBefore": "9999999999",
                "nonce": "0x1",
            },
        },
    }


@respx.mock
def test_hybrid_falls_back_to_remote_on_local_sig_error(client: Client, settings, monkeypatch):
    settings.X402 = {
        **settings.X402,
        "mode": "hybrid",
        "facilitator_config": {"url": "https://fac.remote"},
        "local": {
            "private_key_env": "X402_SIGNER_KEY",
            "rpc_url_env": "X402_RPC_URL",
        },
    }

    # Force LocalFacilitator.verify to raise, simulating signature parsing/verification failure
    import django_x402.facilitators as fac_mod

    class Boom(Exception):
        pass

    def bad_verify(*args, **kwargs):
        raise Boom("sig error")

    monkeypatch.setattr(fac_mod.LocalFacilitator, "verify", bad_verify)

    respx.post("https://fac.remote/verify").mock(return_value=httpx.Response(200, json={"isValid": True}))
    respx.post("https://fac.remote/settle").mock(return_value=httpx.Response(200, json={"success": True, "transaction": "0xabc"}))

    resp = client.get("/api/premium/data", HTTP_X_PAYMENT=_encode(_payment()))
    assert resp.status_code == 200
    assert resp["X-PAYMENT-RESPONSE"]


