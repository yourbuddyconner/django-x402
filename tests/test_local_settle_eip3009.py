from typing import Any, Dict

import pytest


def _requirements() -> Dict[str, Any]:
    return {
        "scheme": "exact",
        "network": "base-sepolia",
        "asset": "0x0000000000000000000000000000000000000001",
        "maxAmountRequired": "10000",
        "resource": "https://testserver/api/premium/data",
        "description": "Premium API call",
        "mimeType": "application/json",
        "payTo": "0x0000000000000000000000000000000000beefca",
        "maxTimeoutSeconds": 60,
        "extra": {
            "name": "USD Coin",
            "version": "2",
            "chainId": 84532,
            "verifyingContract": "0x0000000000000000000000000000000000000001",
        },
    }


def _payment() -> Dict[str, Any]:
    return {
        "x402Version": 1,
        "scheme": "exact",
        "network": "base-sepolia",
        "payload": {
            "signature": "0x" + ("aa" * 65),
            "authorization": {
                "from": "0x1111111111111111111111111111111111111111",
                "to": "0x0000000000000000000000000000000000beefca",
                "value": "10000",
                "validAfter": "0",
                "validBefore": "9999999999",
                "nonce": "0x" + ("11" * 32),
            },
        },
    }


def test_local_settle_builds_and_sends_tx(monkeypatch):
    # Provide env config names, though we will fake Web3 so no real RPC
    from django_x402.facilitators import LocalFacilitator
    import django_x402.facilitators as fac_mod

    sent = {"count": 0}

    class FakeAcct:
        def __init__(self, address: str):
            self.address = address

    class FakeEth:
        def __init__(self):
            self.account = self
            self.gas_price = 1000000000  # 1 gwei in wei

        def from_key(self, key: str):
            return FakeAcct("0xfeed000000000000000000000000000000000000")
            
        def sign_transaction(self, tx, private_key):
            class FakeSignedTx:
                raw_transaction = b"signed_tx_bytes"
            return FakeSignedTx()

        def get_transaction_count(self, addr: str):
            return 7
        
        def call(self, tx):
            # Simulate successful transaction for testing
            return b"\x00" * 32

        def send_raw_transaction(self, raw: bytes):
            sent["count"] += 1
            class H:
                def hex(self_inner):
                    return "0xabc"

            return H()

    class FakeWeb3:
        def __init__(self, provider):
            self.eth = FakeEth()

        class HTTPProvider:
            def __init__(self, url: str):
                self.url = url

        @staticmethod
        def keccak(text: str) -> bytes:
            # 4-byte selector dummy
            return b"\x12\x34\x56\x78" + b"\x00" * 28

    monkeypatch.setattr(fac_mod, "Web3", FakeWeb3)

    fac = LocalFacilitator(config={"private_key_env": "X402_SIGNER_KEY", "rpc_url_env": "X402_RPC_URL"})
    res = fac.settle(_payment(), _requirements())
    assert res.get("success") is True
    assert res.get("transaction") == "0xabc"
    assert sent["count"] == 1


