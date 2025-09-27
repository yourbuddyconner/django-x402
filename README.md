# django-x402

[![Test](https://github.com/yourbuddyconner/django-x402/actions/workflows/test.yml/badge.svg)](https://github.com/yourbuddyconner/django-x402/actions/workflows/test.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)
![Django 5.2+](https://img.shields.io/badge/Django-5.2%2B-0C4B33?logo=django)
[![PyPI version](https://badge.fury.io/py/django-x402.svg)](https://badge.fury.io/py/django-x402)

Django middleware for the x402 "Payment Required" protocol.

## Spec Compliance

This implementation follows the [x402 exact scheme specification](https://github.com/coinbase/x402/blob/main/specs/schemes/exact/scheme_exact_evm.md) with full support for:

✅ **EIP-3009 TransferWithAuthorization** - Proper signature verification and transaction encoding  
✅ **EIP-712 Typed Data Signing** - Full domain separation and signature validation  
✅ **Balance Verification** (optional) - Check payer has sufficient ERC20 tokens  
✅ **Nonce Tracking** - Prevent replay attacks by tracking used nonces  
✅ **Transaction Simulation** - Pre-flight validation before broadcasting

## Requirements

- Python 3.10 or higher
- Django 5.2 or higher

## Install

```bash
pip install django-x402
```

### Install from Git (latest/main)

```bash
pip install 'django-x402 @ git+https://github.com/yourbuddyconner/django-x402.git@main'
```

Pin to a tagged release:

```bash
pip install 'django-x402 @ git+https://github.com/yourbuddyconner/django-x402.git@v0.1.0'
```

## Configure

Add to `MIDDLEWARE` after auth/session middleware:

```python
MIDDLEWARE = [
  # ...
  "django_x402.middleware.X402Middleware",
]

X402 = {
  "paths": ["/api/premium/"],
  "network": "base-sepolia",
  "price": "$0.01",
  "pay_to_address": "0xYourAddress",
  "mime_type": "application/json",
  "description": "Premium API call",
  "max_deadline_seconds": 60,
  "discoverable": True,
  "output_schema": {"type": "json"},
  # Facilitator modes: "remote" | "local" | "hybrid"
  # Default is "remote" when facilitator_config is provided, else "local"
  # "remote" configuration
  # "facilitator_config": {"url": "https://your-facilitator"},
  # "local" configuration with enhanced verification (spec compliance)
  # "mode": "local",
  # "local": {
  #   "private_key_env": "X402_SIGNER_KEY",
  #   "rpc_url_env": "X402_RPC_URL",
  #   "verify_balance": True,         # Check ERC20 balances
  #   "simulate_before_send": True,   # Simulate transactions before broadcasting
  #   "wait_for_receipt": False,      # Wait for tx confirmation
  # },
  # Settle policy: "block-on-failure" (default) or "log-and-continue"
  # "settle_policy": "block-on-failure",
  # Optional replay cache toggle (in-memory)
  # "replay_cache_backend": "memory",
}
```

## Security Features

When using local facilitator mode:

- **Nonce Tracking**: Automatically prevents replay attacks by tracking used nonces in memory
- **Balance Verification**: Optional check to ensure payer has sufficient funds before accepting payment (requires `verify_balance: True`)
- **Transaction Simulation**: Pre-flight validation using eth_call before broadcasting (enabled by default, disable with `simulate_before_send: False`)

## Development

Run tests:

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e '.[tests]'
pytest -q
```

### Optional: Integration test with Anvil (Base mainnet fork)

1. Create a `.env` with your fork URL (Base mainnet via a provider):

```bash
export ANVIL_FORK_URL="https://base-mainnet.g.alchemy.com/v2/<API_KEY>"
export FORK_URL="$ANVIL_FORK_URL"
```

2. Start Anvil via Docker Compose:

```bash
docker compose -f docker-compose.anvil.yml up -d
```

3. Run the integration test (skipped unless `ANVIL_FORK_URL` is set):

```bash
# Option 1: Use the test environment file
source test.env
pytest tests/test_integration_anvil.py -xvs

# Option 2: Use the helper script (automatically starts/stops Anvil)
./run_integration_test.sh

# Option 3: Set environment variables manually
export ANVIL_FORK_URL="https://mainnet.base.org"
export ANVIL_RPC_URL="http://localhost:8545"
export X402_SIGNER_KEY="0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"
export X402_RPC_URL="http://localhost:8545"
pytest tests/test_integration_anvil.py -xvs
```

The `test.env` file contains all necessary environment variables for running the integration tests. The `run_integration_test.sh` script provides a convenient way to run the tests with automatic Anvil lifecycle management.

## Links

- x402 protocol and reference implementation: [coinbase/x402](https://github.com/coinbase/x402)
- x402 Specification: [Protocol Specification](https://github.com/coinbase/x402/blob/main/specs/x402-specification.md)
- EIP-712: Typed structured data hashing/signing: [eips.ethereum.org/EIPS/eip-712](https://eips.ethereum.org/EIPS/eip-712)
- EIP-3009: Transfer With Authorization: [eips.ethereum.org/EIPS/eip-3009](https://eips.ethereum.org/EIPS/eip-3009)
