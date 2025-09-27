import os
import base64
import json
from typing import Any, Dict

import pytest
from eth_account import Account
from eth_account.messages import encode_typed_data
from hexbytes import HexBytes
from web3 import Web3


ANVIL_URL = os.environ.get("ANVIL_RPC_URL", "http://localhost:8545")


def _enc(obj: Dict[str, Any]) -> str:
    return base64.b64encode(json.dumps(obj).encode("utf-8")).decode("ascii")




@pytest.mark.skipif(not os.environ.get("ANVIL_FORK_URL"), reason="anvil fork not configured")
def test_local_verify_and_settle_against_anvil(client, settings, monkeypatch, capsys, caplog):
    """Test happy path: successful EIP-3009 transferWithAuthorization on Anvil fork."""
    
    # Connect to Anvil first
    w3 = Web3(Web3.HTTPProvider(ANVIL_URL))
    
    # Create a new account for the payer
    payer_account = Account.create()
    payer_address = payer_account.address
    payee_address = "0x0000000000000000000000000000000000beefca"
    
    # Use Anvil default account #0 as the transaction sender
    sender_key = "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"
    sender_account = Account.from_key(sender_key)
    
    # Configure env vars for the LocalFacilitator (sender will submit the tx)
    os.environ["X402_SIGNER_KEY"] = sender_key
    os.environ["X402_RPC_URL"] = ANVIL_URL
    
    # USDC contract on Base mainnet 
    usdc_address = Web3.to_checksum_address("0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913")
    
    # Use Anvil to directly set USDC balance for the payer
    # USDC on Base uses a different storage layout - slot 9 for balances
    from eth_abi import encode as abi_encode
    
    # Calculate the storage slot for the payer's balance
    # For mappings: slot = keccak256(abi.encode(address, uint256(slot_index)))
    slot_index = 9  # USDC balance mapping is at slot 9
    encoded = abi_encode(['address', 'uint256'], [payer_address, slot_index])
    storage_slot = '0x' + Web3.keccak(encoded).hex()
    
    # Set balance to 1000 USDC (with 6 decimals)
    balance_wei = 1000 * 10**6
    balance_hex = '0x' + hex(balance_wei)[2:].zfill(64)
    
    # Set the storage
    w3.provider.make_request("anvil_setStorageAt", [
        usdc_address,
        storage_slot,
        balance_hex
    ])
    
    # Also fund the payer with ETH for gas (though they won't need it)
    w3.provider.make_request("anvil_setBalance", [
        payer_address,
        hex(10**18)  # 1 ETH
    ])
    
    # Verify the balance was set
    erc20_abi = [
        {
            "constant": True,
            "inputs": [{"name": "_owner", "type": "address"}],
            "name": "balanceOf",
            "outputs": [{"name": "", "type": "uint256"}],
            "type": "function"
        }
    ]
    
    usdc_contract = w3.eth.contract(address=usdc_address, abi=erc20_abi)
    payer_balance = usdc_contract.functions.balanceOf(payer_address).call()
    print(f"Payer USDC balance: {payer_balance / 10**6} USDC")
    
    # Configure settings for local mode
    settings.X402 = {
        **settings.X402,
        "network": "base",
        "mode": "local",
        "local": {
            "private_key_env": "X402_SIGNER_KEY",
            "rpc_url_env": "X402_RPC_URL",
            "wait_for_receipt": True,
        },
        "settle_policy": "block-on-failure",  # Block and fail on any settlement error
        "pay_to_address": payee_address,
        "asset": usdc_address  # USDC on Base
    }
    
    # Create valid EIP-3009 signature
    domain = {
        "name": "USD Coin",
        "version": "2", 
        "chainId": 8453,  # Base mainnet chain ID
        "verifyingContract": usdc_address
    }
    
    # Message for transferWithAuthorization
    message = {
        "from": payer_address,
        "to": payee_address,
        "value": 100000,  # 0.10 USDC (6 decimals)
        "validAfter": 0,
        "validBefore": 9999999999,
        "nonce": "0x" + ("44" * 32),  # Unique nonce
    }
    
    # EIP-712 types
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
    
    # Sign the message with the payer's private key
    signable = encode_typed_data(full_message={
        "types": types,
        "primaryType": "TransferWithAuthorization",
        "domain": domain,
        "message": message
    })
    signed = Account.sign_message(signable, payer_account.key)
    
    # Build payment payload
    payment_payload = {
        "x402Version": 1,
        "scheme": "exact",
        "network": "base",
        "payload": {
            "signature": HexBytes(signed.signature).hex(),
            "authorization": {
                "from": payer_address,
                "to": payee_address,
                "value": str(message["value"]),
                "validAfter": str(message["validAfter"]),
                "validBefore": str(message["validBefore"]),
                "nonce": message["nonce"],
            },
        },
    }
    
    # Stub verify to true to focus on settlement
    import django_x402.middleware as mw
    monkeypatch.setattr(mw, "verify_payment", lambda h, r: {"isValid": True})
    
    # Capture logs
    caplog.set_level("INFO")
    
    # Make the request
    resp = client.get("/api/premium/data", HTTP_X_PAYMENT=_enc(payment_payload))
    
    # Print debug info
    captured = capsys.readouterr()
    print("--- x402 integration logs begin ---")
    print(captured.out)
    print(captured.err)
    print("--- x402 integration logs end ---")
    
    print("--- Captured log records ---")
    for record in caplog.records:
        print(f"{record.levelname}: {record.message}")
    print("--- End log records ---")
    
    # Assertions for happy path
    assert resp.status_code == 200, f"Expected 200 for successful payment, got {resp.status_code}"
    
    # Verify transaction was broadcast
    assert any("x402: settle broadcast tx_hash=" in record.message for record in caplog.records), "Transaction was not broadcast"
    
    # Verify transaction succeeded (status=1)
    assert any("status=1" in record.message for record in caplog.records), "Transaction did not succeed"
    
    # Should NOT have any revert messages
    assert not any("Transaction reverted!" in record.message for record in caplog.records), "Transaction should not have reverted"
    
    # Verify response contains expected data
    assert resp.json() == {"message": "Premium content delivered!"}
    
    print("\n✓ Integration test passed: Successfully settled EIP-3009 payment on Anvil!")


