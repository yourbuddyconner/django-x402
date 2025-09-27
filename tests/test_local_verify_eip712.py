from typing import Any, Dict

import pytest
from eth_account import Account
from eth_account.messages import encode_typed_data
from hexbytes import HexBytes


def _requirements(domain: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "scheme": "exact",
        "network": "base-sepolia",
        "asset": domain.get("verifyingContract", "0x0000000000000000000000000000000000000000"),
        "maxAmountRequired": "10000",
        "resource": "https://testserver/api/premium/data",
        "description": "Premium API call",
        "mimeType": "application/json",
        "payTo": "0x0000000000000000000000000000000000beefca",  # dummy payee
        "maxTimeoutSeconds": 60,
        "extra": domain,
    }


def _typed(types: Dict[str, Any], domain: Dict[str, Any], message: Dict[str, Any]) -> Dict[str, Any]:
    return {"types": types, "primaryType": "TransferWithAuthorization", "domain": domain, "message": message}


def test_local_verify_eip712_signature_valid():
    acct = Account.create()
    domain = {
        "name": "USD Coin",
        "version": "2",
        "chainId": 84532,
        "verifyingContract": "0x0000000000000000000000000000000000000001",
    }

    message = {
        "from": acct.address,
        "to": "0x0000000000000000000000000000000000beefca",
        "value": 10000,
        "validAfter": 0,
        "validBefore": 9999999999,
        "nonce": "0x" + ("11" * 32),
    }

    types = {
        "EIP712Domain": [
            {"name": "name", "type": "string"},
            {"name": "version", "type": "string"},
            {"name": "chainId", "type": "uint256"},
            {"name": "verifyingContract", "type": "address"},
        ],
        "TransferWithAuthorization": [
            {"name": "from", "type": "address"},
            {"name": "to", "type": "address"},
            {"name": "value", "type": "uint256"},
            {"name": "validAfter", "type": "uint256"},
            {"name": "validBefore", "type": "uint256"},
            {"name": "nonce", "type": "bytes32"},
        ],
    }

    signable = encode_typed_data(full_message=_typed(types, domain, message))
    signed = Account.sign_message(signable, acct.key)

    payment = {
        "x402Version": 1,
        "scheme": "exact",
        "network": "base-sepolia",
        "payload": {
            "signature": HexBytes(signed.signature).hex(),
            "authorization": {
                "from": acct.address,
                "to": message["to"],
                "value": str(message["value"]),
                "validAfter": str(message["validAfter"]),
                "validBefore": str(message["validBefore"]),
                "nonce": message["nonce"],
            },
        },
    }

    from django_x402.facilitators import LocalFacilitator

    fac = LocalFacilitator(config={})
    res = fac.verify(payment, _requirements(domain))
    assert res.get("isValid") is True
    assert res.get("payer").lower() == acct.address.lower()


def test_local_verify_eip712_signature_invalid_wrong_domain():
    acct = Account.create()
    domain = {
        "name": "USD Coin",
        "version": "2",
        "chainId": 84532,
        "verifyingContract": "0x0000000000000000000000000000000000000001",
    }

    bad_domain = {**domain, "verifyingContract": "0x0000000000000000000000000000000000000002"}

    message = {
        "from": acct.address,
        "to": "0x0000000000000000000000000000000000beefca",
        "value": 10000,
        "validAfter": 0,
        "validBefore": 9999999999,
        "nonce": "0x" + ("22" * 32),
    }

    types = {
        "EIP712Domain": [
            {"name": "name", "type": "string"},
            {"name": "version", "type": "string"},
            {"name": "chainId", "type": "uint256"},
            {"name": "verifyingContract", "type": "address"},
        ],
        "TransferWithAuthorization": [
            {"name": "from", "type": "address"},
            {"name": "to", "type": "address"},
            {"name": "value", "type": "uint256"},
            {"name": "validAfter", "type": "uint256"},
            {"name": "validBefore", "type": "uint256"},
            {"name": "nonce", "type": "bytes32"},
        ],
    }

    signable = encode_typed_data(full_message=_typed(types, domain, message))
    signed = Account.sign_message(signable, acct.key)

    payment = {
        "x402Version": 1,
        "scheme": "exact",
        "network": "base-sepolia",
        "payload": {
            "signature": HexBytes(signed.signature).hex(),
            "authorization": {
                "from": acct.address,
                "to": message["to"],
                "value": str(message["value"]),
                "validAfter": str(message["validAfter"]),
                "validBefore": str(message["validBefore"]),
                "nonce": message["nonce"],
            },
        },
    }

    from django_x402.facilitators import LocalFacilitator

    fac = LocalFacilitator(config={})
    res = fac.verify(payment, _requirements(bad_domain))
    assert res.get("isValid") is False
    assert "signature" in (res.get("invalidReason") or "").lower()


