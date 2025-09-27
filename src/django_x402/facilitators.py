from __future__ import annotations

import time
from typing import Any, Dict, Optional, Union, cast
import logging

import httpx
from django.conf import settings
from eth_account import Account
from eth_account.messages import encode_typed_data
from web3 import Web3


Payment = Dict[str, Any]
Requirements = Dict[str, Any]


class BaseFacilitator:
    def verify(self, payment: Union[Payment, Any], requirements: Union[Requirements, Any]) -> Dict[str, Any]:
        raise NotImplementedError

    def settle(self, payment: Union[Payment, Any], requirements: Union[Requirements, Any]) -> Dict[str, Any]:
        raise NotImplementedError


class RemoteFacilitator(BaseFacilitator):
    def __init__(self, url: str, headers: Optional[Dict[str, str]] = None):
        self.url = url.rstrip("/")
        self.headers = headers or {}

    def verify(self, payment: Union[Payment, Any], requirements: Union[Requirements, Any]) -> Dict[str, Any]:
        resp = httpx.post(
            f"{self.url}/verify",
            json={"payment": payment, "requirements": requirements},
            headers=self.headers,
            timeout=20,
        )
        resp.raise_for_status()
        return cast(Dict[str, Any], resp.json())

    def settle(self, payment: Union[Payment, Any], requirements: Union[Requirements, Any]) -> Dict[str, Any]:
        resp = httpx.post(
            f"{self.url}/settle",
            json={"payment": payment, "requirements": requirements},
            headers=self.headers,
            timeout=20,
        )
        resp.raise_for_status()
        return cast(Dict[str, Any], resp.json())


class LocalFacilitator(BaseFacilitator):
    def __init__(self, config: Optional[Dict[str, Any]]):
        self.config = config or {}
        # Track used nonces to prevent replay attacks
        self._used_nonces: set[str] = set()

    def verify(self, payment: Payment, requirements: Requirements) -> Dict[str, Any]:
        try:
            # Basic structural checks
            if int(payment.get("x402Version", 0)) != 1:
                return {"isValid": False, "invalidReason": "invalid_x402_version"}
            if payment.get("scheme") != "exact" or requirements.get("scheme") != "exact":
                return {"isValid": False, "invalidReason": "invalid_scheme"}
            if payment.get("network") != requirements.get("network"):
                return {"isValid": False, "invalidReason": "invalid_network"}

            payload = cast(Dict[str, Any], payment.get("payload", {}))
            auth = cast(Dict[str, Any], payload.get("authorization", {}))
            signature = cast(str, payload.get("signature", ""))
            nonce = auth.get("nonce")

            to_addr = str(auth.get("to", "")).lower()
            value = str(auth.get("value", ""))
            now = int(time.time())
            valid_after = int(str(auth.get("validAfter", "0")) or 0)
            valid_before = int(str(auth.get("validBefore", "0")) or 0)

            if to_addr != str(requirements.get("payTo", "")).lower():
                return {"isValid": False, "invalidReason": "invalid_exact_evm_payload_recipient_mismatch"}
            if value != str(requirements.get("maxAmountRequired", "")):
                return {"isValid": False, "invalidReason": "invalid_exact_evm_payload_authorization_value"}
            if now < valid_after:
                return {"isValid": False, "invalidReason": "invalid_exact_evm_payload_authorization_valid_after"}
            if valid_before and now > valid_before:
                return {"isValid": False, "invalidReason": "invalid_exact_evm_payload_authorization_valid_before"}

            # Step 5: Verify nonce is not used (spec requirement)
            nonce_str = str(nonce) if nonce else ""
            if nonce_str in self._used_nonces:
                return {"isValid": False, "invalidReason": "nonce_already_used"}

            # EIP-712 verification for EIP-3009 TransferWithAuthorization only when full domain is present
            domain = cast(Dict[str, Any], requirements.get("extra")) or {}
            has_full_domain = all(k in domain for k in ("name", "version", "chainId", "verifyingContract"))

            if has_full_domain and signature:
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

                message = {
                    "from": auth.get("from"),
                    "to": auth.get("to"),
                    "value": int(str(auth.get("value", "0")) or 0),
                    "validAfter": int(str(auth.get("validAfter", "0")) or 0),
                    "validBefore": int(str(auth.get("validBefore", "0")) or 0),
                    "nonce": auth.get("nonce"),
                }

                full_message = {
                    "types": types,
                    "primaryType": "TransferWithAuthorization",
                    "domain": domain,
                    "message": message,
                }

                signable = encode_typed_data(full_message=full_message)
                try:
                    recovered = Account.recover_message(signable, signature=signature)
                except Exception:
                    return {"isValid": False, "invalidReason": "invalid_exact_evm_payload_signature"}

                if str(recovered).lower() != str(auth.get("from", "")).lower():
                    return {"isValid": False, "invalidReason": "invalid_exact_evm_payload_signature"}

            # Step 2: Verify the client has enough balance (spec requirement)
            # This requires RPC connection - only check if configured
            if self._should_check_balance():
                balance_check = self._check_erc20_balance(
                    auth.get("from"),
                    requirements.get("asset"),
                    int(value),
                    payment.get("network")
                )
                if not balance_check.get("sufficient", False):
                    return {"isValid": False, "invalidReason": "insufficient_balance"}

            # Mark nonce as used only after all checks pass
            if nonce_str:
                self._used_nonces.add(nonce_str)

            # If no full domain or after successful EIP-712 verification
            return {"isValid": True, "payer": auth.get("from")}
        except Exception as exc:  # pragma: no cover - surfaced in hybrid fallback test
            return {"isValid": False, "invalidReason": f"unexpected_verify_error: {exc}"}

    def _should_check_balance(self) -> bool:
        """Check if balance verification is enabled in config."""
        return bool(self.config.get("verify_balance", False))

    def _check_erc20_balance(self, from_addr: str, asset: str, required_amount: int, network: str) -> Dict[str, Any]:
        """Check if the from address has sufficient ERC20 balance.
        
        Step 2 from spec: Verify the client has enough of the asset (ERC20 token)
        to cover paymentRequirements.maxAmountRequired
        """
        try:
            local_cfg = self.config or {}
            rpc_url_env = str(local_cfg.get("rpc_url_env", "X402_RPC_URL"))
            rpc_url = cast(str, (settings and getattr(settings, rpc_url_env, None)) or "")
            if not rpc_url:
                import os
                rpc_url = os.environ.get(rpc_url_env, "")
            
            if not rpc_url:
                # Can't check balance without RPC
                return {"sufficient": True, "checked": False}
            
            w3 = Web3(Web3.HTTPProvider(rpc_url))
            
            # Standard ERC20 balanceOf ABI
            balance_selector = Web3.keccak(text="balanceOf(address)")[:4]
            
            # Encode the address parameter
            try:
                from eth_abi import encode as abi_encode  # type: ignore
            except Exception:
                from eth_abi.abi import encode as abi_encode  # type: ignore
            
            data = balance_selector + abi_encode(["address"], [from_addr])
            
            # Call balanceOf
            result = w3.eth.call({
                "to": asset,
                "data": data,
            })
            
            # Decode uint256 result
            balance = int.from_bytes(result, byteorder="big")
            
            return {
                "sufficient": balance >= required_amount,
                "balance": balance,
                "required": required_amount,
                "checked": True
            }
        except Exception as e:
            logging.warning(f"Failed to check ERC20 balance: {e}")
            # On error, don't block verification
            return {"sufficient": True, "checked": False, "error": str(e)}

    def settle(self, payment: Payment, requirements: Requirements) -> Dict[str, Any]:
        try:
            logging.info("LocalFacilitator.settle called with payment=%s, requirements=%s", payment, requirements)
            local_cfg = self.config or {}
            priv_key_env = str(local_cfg.get("private_key_env", "X402_SIGNER_KEY"))
            rpc_url_env = str(local_cfg.get("rpc_url_env", "X402_RPC_URL"))
            wait_for_receipt = bool(local_cfg.get("wait_for_receipt", False))
            private_key = cast(str, (settings and getattr(settings, priv_key_env, None)) or "")
            if not private_key:
                # Also look up in os.environ if not set on settings
                import os

                private_key = os.environ.get(priv_key_env, "")
            logging.info("Looking for private key in env var %s: found=%s", priv_key_env, bool(private_key))
            
            rpc_url = cast(str, (settings and getattr(settings, rpc_url_env, None)) or "")
            if not rpc_url:
                import os

                rpc_url = os.environ.get(rpc_url_env, "")
            logging.info("Looking for RPC URL in env var %s: found=%s, value=%s", rpc_url_env, bool(rpc_url), rpc_url if rpc_url else "none")

            # Initialize Web3 (always via local Web3 symbol so tests can monkeypatch)
            # Default to Base mainnet RPC if not provided
            w3 = Web3(Web3.HTTPProvider(rpc_url or "https://mainnet.base.org"))
            acct = w3.eth.account.from_key(private_key) if private_key else None

            # Craft call data for transferWithAuthorization per EIP-3009 (v, r, s variant)
            auth = cast(Dict[str, Any], payment.get("payload", {}).get("authorization", {}))
            from_addr = auth.get("from")
            to = auth.get("to")
            value = int(str(auth.get("value", "0")) or 0)
            valid_after = int(str(auth.get("validAfter", "0")) or 0)
            valid_before = int(str(auth.get("validBefore", "0")) or 0)
            nonce = auth.get("nonce")
            signature = cast(str, payment.get("payload", {}).get("signature", ""))

            # Parse signature r,s,v from 65-byte hex
            sig_hex = signature[2:] if signature.startswith("0x") else signature
            r = bytes.fromhex(sig_hex[0:64]) if len(sig_hex) >= 64 else b"\x00" * 32
            s = bytes.fromhex(sig_hex[64:128]) if len(sig_hex) >= 128 else b"\x00" * 32
            v = int(sig_hex[128:130], 16) if len(sig_hex) >= 130 else 27
            if v in (0, 1):
                v += 27

            # Normalize nonce to 32 bytes
            if isinstance(nonce, str) and nonce.startswith("0x"):
                nonce_bytes = bytes.fromhex(nonce[2:].zfill(64))
            elif isinstance(nonce, (bytes, bytearray)):
                nb = bytes(nonce)
                nonce_bytes = (b"\x00" * (32 - len(nb))) + nb if len(nb) < 32 else nb[:32]
            else:
                # Fallback: interpret as int
                n_int = int(nonce or 0)
                nonce_bytes = n_int.to_bytes(32, byteorder="big")

            # Function selector for v,r,s variant
            selector = Web3.keccak(
                text="transferWithAuthorization(address,address,uint256,uint256,uint256,bytes32,uint8,bytes32,bytes32)"
            )[:4]

            # ABI-encode arguments
            try:
                from eth_abi import encode as abi_encode  # type: ignore
            except Exception:
                from eth_abi.abi import encode as abi_encode  # type: ignore

            data = selector + abi_encode(
                [
                    "address",
                    "address",
                    "uint256",
                    "uint256",
                    "uint256",
                    "bytes32",
                    "uint8",
                    "bytes32",
                    "bytes32",
                ],
                [
                    from_addr,
                    to,
                    value,
                    valid_after,
                    valid_before,
                    nonce_bytes,
                    v,
                    r,
                    s,
                ],
            )

            tx = {
                "to": requirements.get("asset"),
                "from": acct.address if acct else from_addr,
                "data": data,
                "value": 0,
                "nonce": w3.eth.get_transaction_count(acct.address) if acct else 0,
                "gas": 300000,  # Reasonable gas limit for ERC-20 transfer
                "gasPrice": w3.eth.gas_price,  # Current gas price from the node
            }

            # Step 7: Simulate the transferWithAuthorization (spec requirement)
            # This ensures the transaction would succeed before broadcasting
            simulate = bool(local_cfg.get("simulate_before_send", True))
            if simulate:
                try:
                    # Use eth_call to simulate the transaction
                    simulation_tx = {
                        "to": requirements.get("asset"),
                        "from": from_addr,  # Use the actual payer address for simulation
                        "data": data,
                        "value": 0,
                    }
                    w3.eth.call(simulation_tx)
                    logging.info("x402: Transaction simulation successful")
                except Exception as sim_error:
                    logging.error(f"x402: Transaction simulation failed: {sim_error}")
                    # Return early if simulation fails
                    return {"success": False, "error": f"Transaction simulation failed: {str(sim_error)}"}

            # Sign and send
            if acct:
                signed = w3.eth.account.sign_transaction(tx, private_key)
                tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction).hex()
            else:
                # As a fallback in tests without a key, call send_raw_transaction with dummy bytes
                tx_hash = w3.eth.send_raw_transaction(b"signed").hex()

            logging.info("x402: settle broadcast tx_hash=%s", tx_hash)

            if wait_for_receipt:
                try:
                    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
                    status = getattr(receipt, "status", None) if hasattr(receipt, "status") else (receipt.get("status") if isinstance(receipt, dict) else None)
                    logging.info(
                        "x402: settle mined tx_hash=%s block=%s status=%s",
                        tx_hash,
                        getattr(receipt, "blockNumber", None) if hasattr(receipt, "blockNumber") else (receipt.get("blockNumber") if isinstance(receipt, dict) else None),
                        status,
                    )
                    # Convert receipt to a JSON-serializable dict
                    def convert_to_serializable(obj):
                        """Recursively convert Web3 objects to JSON-serializable format."""
                        if hasattr(obj, 'hex'):  # HexBytes
                            return obj.hex()
                        elif hasattr(obj, '__dict__') and not isinstance(obj, type):  # AttributeDict or similar
                            # Convert to dict and recursively process
                            return {k: convert_to_serializable(v) for k, v in dict(obj).items()}
                        elif isinstance(obj, dict):
                            return {k: convert_to_serializable(v) for k, v in obj.items()}
                        elif isinstance(obj, (list, tuple)):
                            return [convert_to_serializable(v) for v in obj]
                        else:
                            return obj
                    
                    receipt_dict = convert_to_serializable(dict(receipt))
                    
                    # Check if transaction was successful (status == 1)
                    if status == 0:
                        logging.error("x402: Transaction reverted! tx_hash=%s", tx_hash)
                        return {"success": False, "error": "Transaction reverted", "transaction": tx_hash, "receipt": receipt_dict}
                    
                    return {"success": True, "transaction": tx_hash, "receipt": receipt_dict}
                except Exception:
                    # still return the tx hash even if waiting fails
                    return {"success": True, "transaction": tx_hash}
            return {"success": True, "transaction": tx_hash}
        except Exception as exc:
            logging.error("LocalFacilitator.settle failed with exception: %s", exc, exc_info=True)
            return {"success": False, "error": str(exc)}


class HybridFacilitator(BaseFacilitator):
    def __init__(self, local: LocalFacilitator, remote: RemoteFacilitator, fallback_to_remote: bool = True):
        self.local = local
        self.remote = remote
        self.fallback_to_remote = fallback_to_remote

    def verify(self, payment: Payment, requirements: Requirements) -> Dict[str, Any]:
        try:
            local_res = self.local.verify(payment, requirements)
            if local_res.get("isValid") is True:
                return local_res
            if not self.fallback_to_remote:
                return local_res
        except Exception:
            # Fall through to remote on local verification error
            pass
        return self.remote.verify(payment, requirements)

    def settle(self, payment: Payment, requirements: Requirements) -> Dict[str, Any]:
        # For simplicity route settlement to remote to ensure tx visibility
        return self.remote.settle(payment, requirements)


def get_facilitator_from_settings() -> BaseFacilitator:
    cfg = cast(Dict[str, Any], getattr(settings, "X402", {}) or {})
    mode = cast(str, cfg.get("mode") or ("remote" if cfg.get("facilitator_config") else "local"))
    fac_cfg = cast(Optional[Dict[str, Any]], cfg.get("facilitator_config")) or {}
    local_cfg = cast(Optional[Dict[str, Any]], cfg.get("local")) or {}

    if mode == "local":
        return LocalFacilitator(config=local_cfg)
    if mode == "remote":
        url = cast(str, fac_cfg.get("url", ""))
        headers = cast(Optional[Dict[str, str]], fac_cfg.get("headers"))
        return RemoteFacilitator(url=url, headers=headers)

    # hybrid
    url = cast(str, fac_cfg.get("url", ""))
    headers = cast(Optional[Dict[str, str]], fac_cfg.get("headers"))
    remote = RemoteFacilitator(url=url, headers=headers)
    local = LocalFacilitator(config=local_cfg)
    return HybridFacilitator(local=local, remote=remote)


