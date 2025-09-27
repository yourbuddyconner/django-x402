from __future__ import annotations

from typing import Callable, Dict, Any, List, Optional, cast

from django.http import HttpRequest, HttpResponse, JsonResponse, HttpResponse as DjangoHttpResponse
from django.conf import settings
import base64
import json
from asgiref.sync import async_to_sync
import logging

from x402.common import (
    process_price_to_atomic_amount,
    x402_VERSION,
    find_matching_payment_requirements,
)
from x402.encoding import safe_base64_decode
from x402.facilitator import FacilitatorClient, FacilitatorConfig
from x402.path import path_is_match
from x402.paywall import is_browser_request, get_paywall_html
from x402.types import (
    PaymentPayload,
    PaymentRequirements,
    HTTPInputSchema,
    x402PaymentRequiredResponse,
)


class X402Middleware:
    """Django middleware implementing the x402 "Payment Required" protocol.

    Behavior:
    - Matches incoming requests against configured protected paths.
    - If missing/invalid payment, returns HTTP 402 with JSON or an HTML paywall.
    - If a payment is present, verifies with the x402 Facilitator.
    - After a successful view (2xx), settles and adds the `X-PAYMENT-RESPONSE` header.

    Configuration is read from `settings.X402`. This implementation is sync
    (`async_capable = False`) and adapts async facilitator calls via asgiref.
    """

    async_capable = False

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]):
        """Initialize middleware and load configuration from Django settings.

        Reads `settings.X402` for path protection and payment requirement
        defaults (network, price, pay_to_address, etc.).
        """
        self.get_response = get_response
        self.config = getattr(settings, "X402", None) or {}
        self.protected_paths = self.config.get("paths", "*")

    def __call__(self, request: HttpRequest) -> HttpResponse:
        """Apply x402 gating for protected paths and orchestrate verify/settle.

        - Unprotected requests pass through unchanged.
        - Protected requests without a valid `X-PAYMENT` receive a 402 response.
        - With a valid payment, the view executes; on 2xx, we settle and attach
          a base64-encoded `X-PAYMENT-RESPONSE` header.
        """
        if not path_is_match(self.protected_paths, request.path):
            return self.get_response(request)

        payment_header = request.META.get("HTTP_X_PAYMENT", "")
        payment_requirements_models = self._build_payment_requirements(request)

        if payment_header == "":
            return self._payment_required_response(request, payment_requirements_models, "No X-PAYMENT header provided")

        try:
            payment_dict = json.loads(safe_base64_decode(payment_header))
            payment = PaymentPayload(**payment_dict)
        except Exception:
            return self._payment_required_response(request, payment_requirements_models, "Invalid payment header format")

        selected_payment_requirements = find_matching_payment_requirements(
            payment_requirements_models, payment
        )

        if not selected_payment_requirements:
            return self._payment_required_response(request, payment_requirements_models, "No matching payment requirements found")

        try:
            verify_result = verify_payment(payment_header, selected_payment_requirements.model_dump(by_alias=True))
            # Back-compat: if dict response from our function mimics VerifyResponse
            is_valid = False
            invalid_reason = None
            if isinstance(verify_result, dict):
                is_valid = verify_result.get("is_valid") or verify_result.get("ok") or verify_result.get("isValid")
                invalid_reason = verify_result.get("invalid_reason") or verify_result.get("invalidReason")
            else:
                is_valid = bool(verify_result)
            if not is_valid:
                return self._payment_required_response(request, payment_requirements_models, f"Invalid payment: {invalid_reason or 'Unknown error'}")
        except Exception:
            return self._payment_required_response(request, payment_requirements_models, "payment verification error")

        response = self.get_response(request)

        if 200 <= response.status_code < 300:
            # Use dynamic settle policy, default to block-on-failure for parity
            cfg_now = getattr(settings, "X402", {}) or {}
            settle_policy = cast(str, cfg_now.get("settle_policy", self.config.get("settle_policy", "block-on-failure")))
            use_cache = bool(cfg_now.get("replay_cache_backend") or self.config.get("replay_cache_backend"))

            # Replay/idempotency: reuse cached settle result for the same payment header
            if use_cache:
                cached = _get_cached_payment_response(payment_header)
                if cached is not None:
                    response["X-PAYMENT-RESPONSE"] = cached
                    return response

            try:
                settle_result = settle_payment(payment_header, selected_payment_requirements.model_dump(by_alias=True))
                # If a dict/model with success flag, enforce 402 on failure like FastAPI middleware
                success = True
                model_json = None
                if hasattr(settle_result, "success"):
                    success = bool(getattr(settle_result, "success"))
                    model_json = settle_result.model_dump_json(by_alias=True) if hasattr(settle_result, "model_dump_json") else None
                elif isinstance(settle_result, dict):
                    success = bool(settle_result.get("success", True))
                if not success:
                    if settle_policy == "log-and-continue":
                        logging.warning("x402: settlement failed; continuing without header")
                        return response
                    logging.error("x402: settlement failed; policy=block-on-failure")
                    return self._payment_required_response(request, payment_requirements_models, "Settle failed")

                if model_json is not None:
                    encoded = base64.b64encode(model_json.encode("utf-8")).decode("ascii")
                else:
                    encoded = base64.b64encode(
                        json.dumps(settle_result).encode("utf-8")
                    ).decode("ascii")
                response["X-PAYMENT-RESPONSE"] = encoded
                if use_cache:
                    _cache_payment_response(payment_header, encoded)
            except Exception as e:
                if settle_policy == "log-and-continue":
                    logging.warning("x402: settlement error; continuing without header", exc_info=True)
                    return response
                logging.error(f"x402: settlement error; policy=block-on-failure. Error: {str(e)}", exc_info=True)
                return self._payment_required_response(request, payment_requirements_models, f"Settle failed: {str(e)}")

        return response

    def _build_payment_requirements(self, request: HttpRequest) -> List[PaymentRequirements]:
        """Construct `PaymentRequirements` for the incoming request.

        Derives atomic amount, asset, and EIP-712 domain from configured price
        and network, and populates `output_schema` with HTTP input/output hints.
        The `resource` is the absolute URL of the current request.
        """
        network = cast(str, self.config.get("network", "base-sepolia"))
        price = cast(Any, self.config.get("price", "$0.01"))
        pay_to_address = cast(str, self.config.get("pay_to_address", ""))
        description = cast(str, self.config.get("description", ""))
        mime_type = cast(str, self.config.get("mime_type", ""))
        max_deadline_seconds = cast(int, self.config.get("max_deadline_seconds", 60))
        discoverable = cast(bool, self.config.get("discoverable", True))
        input_schema_dict = cast(Optional[Dict[str, Any]], self.config.get("input_schema"))
        output_schema = self.config.get("output_schema")

        max_amount_required, asset_address, eip712_domain = process_price_to_atomic_amount(price, network)

        # Build input schema model if provided
        input_schema: Optional[HTTPInputSchema] = None
        if isinstance(input_schema_dict, dict):
            input_schema = HTTPInputSchema(**input_schema_dict)

        resource_url = request.build_absolute_uri()

        return [
            PaymentRequirements(
                scheme="exact",
                network=network,  # type: ignore[arg-type]
                asset=asset_address,
                max_amount_required=max_amount_required,
                resource=resource_url,
                description=description,
                mime_type=mime_type,
                pay_to=pay_to_address,
                max_timeout_seconds=max_deadline_seconds,
                output_schema={
                    "input": {
                        "type": "http",
                        "method": request.method.upper(),
                        "discoverable": discoverable,
                        **(input_schema.model_dump(by_alias=True) if input_schema else {}),
                    },
                    "output": output_schema,
                },
                extra=eip712_domain,
            )
        ]

    def _payment_required_response(
        self, request: HttpRequest, payment_requirements: List[PaymentRequirements], error: str
    ) -> DjangoHttpResponse:
        """Return a 402 response in HTML (browser) or JSON (API) form.

        Browser detection uses `Accept` and `User-Agent` headers via the x402
        paywall helper. API clients receive a JSON body matching the x402
        Payment Required Response schema.
        """
        # Browser paywall or JSON
        headers = {k: v for k, v in request.headers.items()}
        if is_browser_request(headers):
            html_content = get_paywall_html(error, payment_requirements, None)
            return DjangoHttpResponse(html_content, status=402, content_type="text/html; charset=utf-8")

        response_data = x402PaymentRequiredResponse(
            x402_version=x402_VERSION,
            accepts=payment_requirements,
            error=error,
        ).model_dump(by_alias=True)
        return JsonResponse(response_data, status=402)


def _facilitator_from_settings():
    """Return facilitator adapter based on `settings.X402`.

    Uses our internal adapter that can route to local/remote/hybrid.
    """
    # Import locally to avoid circulars
    from .facilitators import get_facilitator_from_settings as _get

    return _get()


def verify_payment(payment_header: str, payment_requirements: Dict[str, Any]):
    """Verify a base64-encoded x402 payment using the configured Facilitator.

    Parameters
    ----------
    payment_header: str
        Base64-encoded JSON of the x402 Payment Payload (client-provided).
    payment_requirements: Dict[str, Any]
        Dict (with alias keys) representing `PaymentRequirements`.

    Returns
    -------
    Any
        Facilitator verification result (boolean or dict-like with validity fields).
    """
    payment_dict = json.loads(safe_base64_decode(payment_header))
    # Pass raw dicts to facilitator adapters (remote/local expect plain dicts)
    facilitator = _facilitator_from_settings()
    return facilitator.verify(payment_dict, payment_requirements)


def settle_payment(payment_header: str, payment_requirements: Dict[str, Any]):
    """Settle a verified x402 payment using the configured Facilitator.

    Returns the facilitator's settlement result (model or dict). The caller is
    expected to encode the result into the `X-PAYMENT-RESPONSE` header.
    """
    payment_dict = json.loads(safe_base64_decode(payment_header))
    facilitator = _facilitator_from_settings()
    return facilitator.settle(payment_dict, payment_requirements)


# Simple in-process cache for idempotent settlement header by payment header
_PAYMENT_RESPONSE_CACHE: Dict[str, str] = {}


def _get_cached_payment_response(payment_header: str) -> Optional[str]:
    return _PAYMENT_RESPONSE_CACHE.get(payment_header)


def _cache_payment_response(payment_header: str, encoded_response: str) -> None:
    _PAYMENT_RESPONSE_CACHE[payment_header] = encoded_response


