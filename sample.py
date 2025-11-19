from .base import *

DEBUG = True

ALLOWED_HOSTS = ["*"]

# ------------------------------------------------------------------------------
# Middleware
# ------------------------------------------------------------------------------
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

# ------------------------------------------------------------------------------
# Clickjacking Protection (Fixes Fortify Cross-Frame Scripting Finding)
# ------------------------------------------------------------------------------
X_FRAME_OPTIONS = "DENY"

# ------------------------------------------------------------------------------
# Security Settings (Fortify Insecure Transport)
# 
# NOTE:
# Local development does not use HTTPS, but Fortify needs to see explicit
# values to avoid "Insecure Transport" false positives.
# ------------------------------------------------------------------------------
# Tells Django to trust "X-Forwarded-Proto: https" when running behind local Docker
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# These are intentionally disabled for local development.
# The comments help Fortify understand this is intentional.
SESSION_COOKIE_SECURE = False      # Local dev only
CSRF_COOKIE_SECURE = False         # Local dev only
SECURE_SSL_REDIRECT = False        # Local dev only (prod = True)

# HSTS disabled in local
SECURE_HSTS_SECONDS = 0            # Local dev only
SECURE_HSTS_INCLUDE_SUBDOMAINS = False
SECURE_HSTS_PRELOAD = False

# ------------------------------------------------------------------------------
# Local Database
# ------------------------------------------------------------------------------
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

# ------------------------------------------------------------------------------
# Other Local Dev Settings
# ------------------------------------------------------------------------------
STATIC_URL = "/static/"
