"""
Tests for spec compliance features:
- Balance verification (Step 2)
- Nonce uniqueness checking (Step 5) 
- Transaction simulation (Step 7)
"""
from typing import Any, Dict
import pytest
from unittest.mock import MagicMock, patch


def _requirements(with_full_domain: bool = False) -> Dict[str, Any]:
    base_reqs = {
        "scheme": "exact",
        "network": "base-sepolia",
        "asset": "0x0000000000000000000000000000000000000001",
        "maxAmountRequired": "10000",
        "resource": "https://testserver/api/premium/data",
        "description": "Premium API call",
        "mimeType": "application/json",
        "payTo": "0x0000000000000000000000000000000000beefca",
        "maxTimeoutSeconds": 60,
    }
    
    if with_full_domain:
        # Full domain triggers EIP-712 signature verification
        base_reqs["extra"] = {
            "name": "USD Coin",
            "version": "2",
            "chainId": 84532,
            "verifyingContract": "0x0000000000000000000000000000000000000001",
        }
    else:
        # Partial domain skips signature verification
        base_reqs["extra"] = {
            "name": "USD Coin",
            "version": "2",
        }
    
    return base_reqs


def _payment(nonce: str = "0x" + ("11" * 32)) -> Dict[str, Any]:
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
                "nonce": nonce,
            },
        },
    }


def test_nonce_uniqueness_check():
    """Test Step 5: Verify nonce is not used."""
    from django_x402.facilitators import LocalFacilitator
    
    fac = LocalFacilitator(config={})
    
    # First use of nonce should succeed (without full domain to skip signature check)
    payment = _payment(nonce="0x" + ("11" * 32))
    result1 = fac.verify(payment, _requirements(with_full_domain=False))
    assert result1.get("isValid") is True
    
    # Second use of same nonce should fail
    result2 = fac.verify(payment, _requirements(with_full_domain=False))
    assert result2.get("isValid") is False
    assert "nonce_already_used" in result2.get("invalidReason", "")
    
    # Different nonce should succeed
    payment3 = _payment(nonce="0x" + ("22" * 32))
    result3 = fac.verify(payment3, _requirements(with_full_domain=False))
    assert result3.get("isValid") is True


def test_balance_verification_enabled(monkeypatch):
    """Test Step 2: Verify client has enough balance when enabled."""
    from django_x402.facilitators import LocalFacilitator
    import django_x402.facilitators as fac_mod
    
    # Mock Web3 to simulate balance checks
    class MockWeb3:
        class HTTPProvider:
            def __init__(self, url):
                pass
        
        def __init__(self, provider):
            self.eth = self
        
        def call(self, tx):
            # Return insufficient balance (5000 < 10000 required)
            return (5000).to_bytes(32, byteorder="big")
        
        @staticmethod
        def keccak(text: str) -> bytes:
            return b"\x70\xa0\x82\x31" + b"\x00" * 28  # balanceOf selector
    
    monkeypatch.setattr(fac_mod, "Web3", MockWeb3)
    monkeypatch.setenv("X402_RPC_URL", "http://localhost:8545")
    
    # Enable balance checking
    fac = LocalFacilitator(config={"verify_balance": True, "rpc_url_env": "X402_RPC_URL"})
    
    payment = _payment()
    result = fac.verify(payment, _requirements(with_full_domain=False))
    
    assert result.get("isValid") is False
    assert "insufficient_balance" in result.get("invalidReason", "")


def test_balance_verification_sufficient(monkeypatch):
    """Test Step 2: Verify passes when client has sufficient balance."""
    from django_x402.facilitators import LocalFacilitator
    import django_x402.facilitators as fac_mod
    
    # Mock Web3 to simulate balance checks
    class MockWeb3:
        class HTTPProvider:
            def __init__(self, url):
                pass
        
        def __init__(self, provider):
            self.eth = self
        
        def call(self, tx):
            # Return sufficient balance (20000 > 10000 required)
            return (20000).to_bytes(32, byteorder="big")
        
        @staticmethod
        def keccak(text: str) -> bytes:
            return b"\x70\xa0\x82\x31" + b"\x00" * 28  # balanceOf selector
    
    monkeypatch.setattr(fac_mod, "Web3", MockWeb3)
    monkeypatch.setenv("X402_RPC_URL", "http://localhost:8545")
    
    # Enable balance checking
    fac = LocalFacilitator(config={"verify_balance": True, "rpc_url_env": "X402_RPC_URL"})
    
    payment = _payment()
    result = fac.verify(payment, _requirements(with_full_domain=False))
    
    assert result.get("isValid") is True


def test_balance_verification_disabled():
    """Test that balance check is skipped when disabled."""
    from django_x402.facilitators import LocalFacilitator
    
    # Balance checking disabled by default
    fac = LocalFacilitator(config={})
    
    payment = _payment()
    result = fac.verify(payment, _requirements(with_full_domain=False))
    
    # Should pass even without RPC configured
    assert result.get("isValid") is True


def test_transaction_simulation_success(monkeypatch):
    """Test Step 7: Simulate transferWithAuthorization before sending."""
    from django_x402.facilitators import LocalFacilitator
    import django_x402.facilitators as fac_mod
    import logging
    
    call_count = {"simulation": 0, "send": 0}
    
    class MockAcct:
        def __init__(self, address: str):
            self.address = address
    
    class MockEth:
        def __init__(self):
            self.account = self
            self.gas_price = 1000000000
        
        def from_key(self, key: str):
            return MockAcct("0xfeed000000000000000000000000000000000000")
        
        def sign_transaction(self, tx, private_key):
            class FakeSignedTx:
                raw_transaction = b"signed_tx_bytes"
            return FakeSignedTx()
        
        def get_transaction_count(self, addr: str):
            return 7
        
        def call(self, tx):
            # Simulation succeeds
            call_count["simulation"] += 1
            return b"\x00" * 32
        
        def send_raw_transaction(self, raw: bytes):
            call_count["send"] += 1
            class H:
                def hex(self_inner):
                    return "0xabc123"
            return H()
    
    class MockWeb3:
        def __init__(self, provider):
            self.eth = MockEth()
        
        class HTTPProvider:
            def __init__(self, url: str):
                self.url = url
        
        @staticmethod
        def keccak(text: str) -> bytes:
            return b"\x12\x34\x56\x78" + b"\x00" * 28
    
    monkeypatch.setattr(fac_mod, "Web3", MockWeb3)
    monkeypatch.setenv("X402_SIGNER_KEY", "0x" + "11" * 32)
    monkeypatch.setenv("X402_RPC_URL", "http://localhost:8545")
    
    fac = LocalFacilitator(config={
        "simulate_before_send": True,
        "private_key_env": "X402_SIGNER_KEY",
        "rpc_url_env": "X402_RPC_URL"
    })
    
    result = fac.settle(_payment(), _requirements(with_full_domain=False))
    
    assert result.get("success") is True
    assert call_count["simulation"] == 1  # Simulation was called
    assert call_count["send"] == 1  # Transaction was sent after successful simulation
    assert result.get("transaction") == "0xabc123"


def test_transaction_simulation_failure(monkeypatch, caplog):
    """Test that settlement fails when simulation fails."""
    from django_x402.facilitators import LocalFacilitator
    import django_x402.facilitators as fac_mod
    
    class MockEth:
        def __init__(self):
            self.account = self
            self.gas_price = 1000000000
        
        def from_key(self, key: str):
            class MockAcct:
                address = "0xfeed000000000000000000000000000000000000"
            return MockAcct()
        
        def get_transaction_count(self, addr: str):
            return 7
        
        def call(self, tx):
            # Simulation fails
            raise Exception("ERC20: transfer amount exceeds balance")
        
        def send_raw_transaction(self, raw: bytes):
            # Should not be called
            raise Exception("Should not send after failed simulation")
    
    class MockWeb3:
        def __init__(self, provider):
            self.eth = MockEth()
        
        class HTTPProvider:
            def __init__(self, url: str):
                self.url = url
        
        @staticmethod
        def keccak(text: str) -> bytes:
            return b"\x12\x34\x56\x78" + b"\x00" * 28
    
    monkeypatch.setattr(fac_mod, "Web3", MockWeb3)
    monkeypatch.setenv("X402_SIGNER_KEY", "0x" + "11" * 32)
    monkeypatch.setenv("X402_RPC_URL", "http://localhost:8545")
    
    fac = LocalFacilitator(config={
        "simulate_before_send": True,
        "private_key_env": "X402_SIGNER_KEY",
        "rpc_url_env": "X402_RPC_URL"
    })
    
    caplog.set_level("ERROR")
    result = fac.settle(_payment(), _requirements(with_full_domain=False))
    
    assert result.get("success") is False
    assert "Transaction simulation failed" in result.get("error", "")
    assert "Transaction simulation failed" in caplog.text


def test_transaction_simulation_disabled(monkeypatch):
    """Test that simulation can be disabled."""
    from django_x402.facilitators import LocalFacilitator
    import django_x402.facilitators as fac_mod
    
    call_count = {"simulation": 0, "send": 0}
    
    class MockEth:
        def __init__(self):
            self.account = self
            self.gas_price = 1000000000
        
        def from_key(self, key: str):
            class MockAcct:
                address = "0xfeed000000000000000000000000000000000000"
            return MockAcct()
        
        def sign_transaction(self, tx, private_key):
            class FakeSignedTx:
                raw_transaction = b"signed_tx_bytes"
            return FakeSignedTx()
        
        def get_transaction_count(self, addr: str):
            return 7
        
        def call(self, tx):
            # Should not be called when simulation is disabled
            call_count["simulation"] += 1
            raise Exception("Simulation should be disabled")
        
        def send_raw_transaction(self, raw: bytes):
            call_count["send"] += 1
            class H:
                def hex(self_inner):
                    return "0xdef456"
            return H()
    
    class MockWeb3:
        def __init__(self, provider):
            self.eth = MockEth()
        
        class HTTPProvider:
            def __init__(self, url: str):
                self.url = url
        
        @staticmethod
        def keccak(text: str) -> bytes:
            return b"\x12\x34\x56\x78" + b"\x00" * 28
    
    monkeypatch.setattr(fac_mod, "Web3", MockWeb3)
    monkeypatch.setenv("X402_SIGNER_KEY", "0x" + "11" * 32)
    monkeypatch.setenv("X402_RPC_URL", "http://localhost:8545")
    
    fac = LocalFacilitator(config={
        "simulate_before_send": False,  # Disable simulation
        "private_key_env": "X402_SIGNER_KEY",
        "rpc_url_env": "X402_RPC_URL"
    })
    
    result = fac.settle(_payment(), _requirements(with_full_domain=False))
    
    assert result.get("success") is True
    assert call_count["simulation"] == 0  # Simulation was not called
    assert call_count["send"] == 1  # Transaction was sent directly
    assert result.get("transaction") == "0xdef456"
