import os
from typing import Any, Dict

import pytest


def _base_x402() -> Dict[str, Any]:
    return {
        "paths": ["/api/premium/*"],
        "network": "base-sepolia",
        "price": "$0.01",
        "pay_to_address": "0xTEST",
        "mime_type": "application/json",
        "description": "Premium API call",
        "max_deadline_seconds": 60,
        "discoverable": True,
        "output_schema": {"type": "json"},
    }


def test_get_facilitator_remote_by_default(settings):
    settings.X402 = {
        **_base_x402(),
        "facilitator_config": {"url": "https://fac.remote"},
    }

    from django_x402.facilitators import (
        get_facilitator_from_settings,
        RemoteFacilitator,
    )

    fac = get_facilitator_from_settings()
    assert isinstance(fac, RemoteFacilitator)


def test_get_facilitator_local_mode(settings, monkeypatch):
    monkeypatch.setenv("X402_SIGNER_KEY", "0x" + "11" * 32)
    monkeypatch.setenv("X402_RPC_URL", "https://rpc.local")

    settings.X402 = {
        **_base_x402(),
        "mode": "local",
        "local": {
            "private_key_env": "X402_SIGNER_KEY",
            "rpc_url_env": "X402_RPC_URL",
        },
    }

    from django_x402.facilitators import (
        get_facilitator_from_settings,
        LocalFacilitator,
    )

    fac = get_facilitator_from_settings()
    assert isinstance(fac, LocalFacilitator)


def test_get_facilitator_hybrid_mode(settings, monkeypatch):
    monkeypatch.setenv("X402_SIGNER_KEY", "0x" + "22" * 32)
    monkeypatch.setenv("X402_RPC_URL", "https://rpc.local")

    settings.X402 = {
        **_base_x402(),
        "mode": "hybrid",
        "facilitator_config": {"url": "https://fac.remote"},
        "local": {
            "private_key_env": "X402_SIGNER_KEY",
            "rpc_url_env": "X402_RPC_URL",
        },
    }

    from django_x402.facilitators import (
        get_facilitator_from_settings,
        HybridFacilitator,
    )

    fac = get_facilitator_from_settings()
    assert isinstance(fac, HybridFacilitator)


