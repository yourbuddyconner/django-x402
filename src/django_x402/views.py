from __future__ import annotations

import json
from typing import Any, Dict, List

from django.http import JsonResponse, HttpRequest
from django.conf import settings
import time

from x402.common import process_price_to_atomic_amount, x402_VERSION

# Import module, not symbol, so tests can monkeypatch facilitators.get_facilitator_from_settings
from . import facilitators as facilitators_mod


def x402_facilitator_verify(request: HttpRequest):
    if request.method != "POST":
        return JsonResponse({"error": "method_not_allowed"}, status=405)
    try:
        body: Dict[str, Any] = json.loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse({"error": "invalid_json"}, status=400)
    payment = body.get("payment")
    requirements = body.get("requirements")
    fac = facilitators_mod.get_facilitator_from_settings()
    result = fac.verify(payment, requirements)
    return JsonResponse(result, status=200)


def x402_facilitator_settle(request: HttpRequest):
    if request.method != "POST":
        return JsonResponse({"error": "method_not_allowed"}, status=405)
    try:
        body: Dict[str, Any] = json.loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse({"error": "invalid_json"}, status=400)
    payment = body.get("payment")
    requirements = body.get("requirements")
    fac = facilitators_mod.get_facilitator_from_settings()
    result = fac.settle(payment, requirements)
    return JsonResponse(result, status=200)


def x402_discovery_resources(request: HttpRequest):
    if request.method != "GET":
        return JsonResponse({"error": "method_not_allowed"}, status=405)

    cfg = getattr(settings, "X402", {}) or {}
    network = cfg.get("network", "base-sepolia")
    price = cfg.get("price", "$0.01")
    pay_to_address = cfg.get("pay_to_address", "")
    description = cfg.get("description", "")
    mime_type = cfg.get("mime_type", "")
    max_deadline_seconds = int(cfg.get("max_deadline_seconds", 60))

    max_amount_required, asset_address, eip712_domain = process_price_to_atomic_amount(price, network)

    # Pick first path or root as resource example
    protected_paths: List[str] = cfg.get("paths", ["/"]) or ["/"]
    resource_path = protected_paths[0] if isinstance(protected_paths, list) else "/"
    resource_url = request.build_absolute_uri(resource_path)

    accepts = [
        {
            "scheme": "exact",
            "network": network,
            "asset": asset_address,
            "maxAmountRequired": max_amount_required,
            "resource": resource_url,
            "description": description,
            "mimeType": mime_type,
            "payTo": pay_to_address,
            "maxTimeoutSeconds": max_deadline_seconds,
            "extra": eip712_domain,
        }
    ]

    resp = {
        "resources": [
            {
                "resource": resource_url,
                "type": "http",
                "x402Version": x402_VERSION,
                "accepts": accepts,
                "lastUpdated": int(time.time()),
                "metadata": {},
            }
        ]
    }
    return JsonResponse(resp, status=200)


