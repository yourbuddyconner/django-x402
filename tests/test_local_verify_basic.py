from typing import Any, Dict

import pytest


def _requirements(resource: str = "https://testserver/api/premium/data") -> Dict[str, Any]:
    return {
        "scheme": "exact",
        "network": "base-sepolia",
        "asset": "0xUSDC",
        "maxAmountRequired": "10000",
        "resource": resource,
        "description": "Premium API call",
        "mimeType": "application/json",
        "payTo": "0xPAYEE",
        "maxTimeoutSeconds": 60,
        "extra": {"name": "USDC", "version": "2"},
    }


def _payment(valid_to: str = "0xPAYEE", value: str = "10000") -> Dict[str, Any]:
    return {
        "x402Version": 1,
        "scheme": "exact",
        "network": "base-sepolia",
        "payload": {
            "signature": "0xdeadbeef",  # not actually verified in unit test
            "authorization": {
                "from": "0xPAYER",
                "to": valid_to,
                "value": value,
                "validAfter": "0",
                "validBefore": "9999999999",
                "nonce": "0x01",
            },
        },
    }


def test_local_verify_valid_when_fields_match(monkeypatch):
    from django_x402.facilitators import LocalFacilitator

    fac = LocalFacilitator(config={})
    res = fac.verify(_payment(), _requirements())
    assert isinstance(res, dict)
    assert res.get("isValid") is True


def test_local_verify_invalid_on_recipient_mismatch():
    from django_x402.facilitators import LocalFacilitator

    fac = LocalFacilitator(config={})
    res = fac.verify(_payment(valid_to="0xNOTPAYEE"), _requirements())
    assert res.get("isValid") is False
    assert "recipient" in (res.get("invalidReason") or "").lower()


def test_local_verify_invalid_on_amount_mismatch():
    from django_x402.facilitators import LocalFacilitator

    fac = LocalFacilitator(config={})
    res = fac.verify(_payment(value="10001"), _requirements())
    assert res.get("isValid") is False
    assert "value" in (res.get("invalidReason") or "").lower()


