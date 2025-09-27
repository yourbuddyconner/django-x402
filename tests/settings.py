SECRET_KEY = "test-secret"
DEBUG = True

ROOT_URLCONF = "tests.urls"

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django_x402.middleware.X402Middleware",
]

ALLOWED_HOSTS = ["testserver", "localhost"]

X402 = {
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


