
"""
Django settings for Chama Link.
"""

import os
from importlib.util import find_spec
from pathlib import Path

from dotenv import load_dotenv
from django.core.exceptions import ImproperlyConfigured


# ==================================================
# BASE DIRECTORY AND ENVIRONMENT VARIABLES
# ==================================================

BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR / ".env")


# ==================================================
# SECURITY AND DEVELOPMENT
# ==================================================

DEBUG = os.getenv(
    "DJANGO_DEBUG", "false" if os.getenv("RENDER") else "true"
).strip().lower() in {"1", "true", "yes", "on"}

DEVELOPMENT_SECRET_KEY = (
    "django-insecure-35(6n%2v8b)#by=i^s=a3-+y8n+zdmoqne6bk2fyc3eqh8wxn%"
)
SECRET_KEY = os.getenv("DJANGO_SECRET_KEY") or os.getenv("SECRET_KEY")
if DEBUG:
    SECRET_KEY = SECRET_KEY or DEVELOPMENT_SECRET_KEY
elif not SECRET_KEY or SECRET_KEY == DEVELOPMENT_SECRET_KEY:
    raise ImproperlyConfigured(
        "Set DJANGO_SECRET_KEY to a unique secret before starting in production."
    )

RENDER_EXTERNAL_HOSTNAME = os.getenv("RENDER_EXTERNAL_HOSTNAME", "").strip()
CHAMALINK_ALLOWED_HOSTS = [
    host.strip()
    for host in os.getenv("CHAMALINK_ALLOWED_HOSTS", "").split(",")
    if host.strip()
]
if DEBUG:
    ALLOWED_HOSTS = ["localhost", "127.0.0.1", "list-obtuse-entangled.ngrok-free.dev"]
    if RENDER_EXTERNAL_HOSTNAME:
        ALLOWED_HOSTS.append(RENDER_EXTERNAL_HOSTNAME)
    ALLOWED_HOSTS.extend(CHAMALINK_ALLOWED_HOSTS)
else:
    ALLOWED_HOSTS = CHAMALINK_ALLOWED_HOSTS.copy()
    if RENDER_EXTERNAL_HOSTNAME:
        ALLOWED_HOSTS.append(RENDER_EXTERNAL_HOSTNAME)
    if not ALLOWED_HOSTS:
        raise ImproperlyConfigured(
            "Set RENDER_EXTERNAL_HOSTNAME or CHAMALINK_ALLOWED_HOSTS in production."
        )

# Optional, exact host for viewing the development app from another device on
# the same private network (for example a phone). Keep this opt-in and local.
CHAMALINK_PREVIEW_HOST = os.getenv("CHAMALINK_PREVIEW_HOST", "").strip()
if DEBUG and CHAMALINK_PREVIEW_HOST:
    ALLOWED_HOSTS.append(CHAMALINK_PREVIEW_HOST)
    CSRF_TRUSTED_ORIGINS = [f"http://{CHAMALINK_PREVIEW_HOST}:8000"]
else:
    CSRF_TRUSTED_ORIGINS = [
        f"https://{host}" for host in ALLOWED_HOSTS
        if host not in {"localhost", "127.0.0.1"}
    ] if not DEBUG else []


# ==================================================
# INSTALLED APPLICATIONS
# ==================================================

INSTALLED_APPS = [
    # Django applications
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.sites",

    # Django Allauth and Google authentication
    "allauth",
    "allauth.account",
    "allauth.socialaccount",
    "allauth.socialaccount.providers.google",

    # Chama Link applications
    "groups",
    "payments",
    "accounts",
]


# Required by Django Allauth Sites integration
SITE_ID = 1


# ==================================================
# MIDDLEWARE
# ==================================================

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "allauth.account.middleware.AccountMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]
if find_spec("whitenoise"):
    MIDDLEWARE.insert(1, "whitenoise.middleware.WhiteNoiseMiddleware")
elif not DEBUG:
    raise ImproperlyConfigured(
        "Install WhiteNoise before starting in production."
    )

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
if not DEBUG:
    SECURE_SSL_REDIRECT = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 3600
    SECURE_CONTENT_TYPE_NOSNIFF = True
    X_FRAME_OPTIONS = "DENY"


# ==================================================
# URLS AND TEMPLATES
# ==================================================

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",

                # Chama Link Google OAuth context processor
                "accounts.context_processors.google_oauth",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"


# ==================================================
# DATABASE
# ==================================================

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
if DATABASE_URL:
    try:
        import dj_database_url
    except ImportError as error:
        raise ImproperlyConfigured(
            "Install dj-database-url to use DATABASE_URL."
        ) from error
    DATABASES = {
        "default": dj_database_url.parse(
            DATABASE_URL,
            conn_max_age=600,
            ssl_require=not DEBUG,
        )
    }
elif DEBUG:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }
else:
    raise ImproperlyConfigured(
        "DATABASE_URL is required in production; SQLite is development-only."
    )


# ==================================================
# PASSWORD VALIDATION
# ==================================================

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": (
            "django.contrib.auth.password_validation."
            "UserAttributeSimilarityValidator"
        ),
    },
    {
        "NAME": (
            "django.contrib.auth.password_validation."
            "MinimumLengthValidator"
        ),
    },
    {
        "NAME": (
            "django.contrib.auth.password_validation."
            "CommonPasswordValidator"
        ),
    },
    {
        "NAME": (
            "django.contrib.auth.password_validation."
            "NumericPasswordValidator"
        ),
    },
]


# ==================================================
# LANGUAGE AND TIME
# ==================================================

LANGUAGE_CODE = "en-us"

TIME_ZONE = "Africa/Nairobi"

USE_I18N = True

USE_TZ = True


# ==================================================
# STATIC FILES
# ==================================================

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
if find_spec("whitenoise"):
    STORAGES = {
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {
            "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"
        },
    }


# ==================================================
# MEDIA FILES
# ==================================================

MEDIA_URL = "/media/"

MEDIA_ROOT = BASE_DIR / "media"
if os.getenv("MEDIA_ROOT"):
    MEDIA_ROOT = Path(os.environ["MEDIA_ROOT"])


# ==================================================
# AUTHENTICATION
# ==================================================

LOGIN_URL = "/accounts/login/"

# Your existing groups dashboard is currently at /
LOGIN_REDIRECT_URL = "/"

LOGOUT_REDIRECT_URL = "/"

AUTHENTICATION_BACKENDS = [
    "django.contrib.auth.backends.ModelBackend",
    "allauth.account.auth_backends.AuthenticationBackend",
]


# Django Allauth account settings
ACCOUNT_LOGIN_METHODS = {"email", "username"}

ACCOUNT_SIGNUP_FIELDS = [
    "username*",
    "email*",
    "password1*",
    "password2*",
]

ACCOUNT_EMAIL_VERIFICATION = "mandatory" if (not DEBUG and os.getenv("EMAIL_HOST")) else "none"


# ==================================================
# GOOGLE OAUTH
# ==================================================

GOOGLE_OAUTH_CLIENT_ID = os.getenv(
    "GOOGLE_OAUTH_CLIENT_ID",
    ""
)

GOOGLE_OAUTH_CLIENT_SECRET = os.getenv(
    "GOOGLE_OAUTH_CLIENT_SECRET",
    ""
)

if GOOGLE_OAUTH_CLIENT_ID and GOOGLE_OAUTH_CLIENT_SECRET:
    SOCIALACCOUNT_PROVIDERS = {
        "google": {
            "APPS": [
                {
                    "client_id": GOOGLE_OAUTH_CLIENT_ID,
                    "secret": GOOGLE_OAUTH_CLIENT_SECRET,
                    "key": "",
                }
            ],
            "SCOPE": [
                "profile",
                "email",
            ],
        },
    }


# ==================================================
# EMAIL
# ==================================================

EMAIL_HOST = os.getenv("EMAIL_HOST", "")
EMAIL_PORT = int(os.getenv("EMAIL_PORT", "587"))
EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = os.getenv("EMAIL_USE_TLS", "true").strip().lower() in {"1", "true", "yes", "on"}
DEFAULT_FROM_EMAIL = os.getenv("DEFAULT_FROM_EMAIL", "ChamaLink <noreply@chamalink.app>")
EMAIL_BACKEND = (
    "django.core.mail.backends.smtp.EmailBackend"
    if EMAIL_HOST
    else "django.core.mail.backends.console.EmailBackend"
)


# ==================================================
# SAFARICOM M-PESA / DARAJA
# ==================================================

MPESA_CONSUMER_KEY = os.getenv("MPESA_CONSUMER_KEY")

MPESA_CONSUMER_SECRET = os.getenv("MPESA_CONSUMER_SECRET")

MPESA_SHORTCODE = os.getenv("MPESA_SHORTCODE")

MPESA_PASSKEY = os.getenv("MPESA_PASSKEY")

MPESA_CALLBACK_URL = os.getenv("MPESA_CALLBACK_URL")


# ==================================================
# DEFAULT PRIMARY KEY
# ==================================================

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
