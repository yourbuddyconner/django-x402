from django.http import JsonResponse
from django.urls import path, include


def premium_view(_request):
    return JsonResponse({"message": "Premium content delivered!"})


urlpatterns = [
    path("api/premium/data", premium_view),
    path("public/ok", lambda _r: JsonResponse({"ok": True})),
    path("", include("django_x402.urls")),
]


