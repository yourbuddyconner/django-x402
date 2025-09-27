from __future__ import annotations

from django.urls import path

from .views import x402_facilitator_verify, x402_facilitator_settle, x402_discovery_resources


urlpatterns = [
    path("x402/facilitator/verify", x402_facilitator_verify),
    path("x402/facilitator/settle", x402_facilitator_settle),
    path("x402/discovery/resources", x402_discovery_resources),
]


