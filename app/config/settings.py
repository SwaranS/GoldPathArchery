import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.environ["DJANGO_SECRET_KEY"]
DEBUG = os.environ.get("DJANGO_DEBUG", "0") == "1"
ALLOWED_HOSTS = ["localhost", "127.0.0.1"]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.sites",
    "allauth",
    "allauth.account",
    "allauth.socialaccount",
    "allauth.socialaccount.providers.google",
    "allauth.mfa",
    "accounts.apps.AccountsConfig",
    "scoring",
    "training",
    "clubs",
]
SITE_ID = 1

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "clubs.middleware.ClubRequestContextMiddleware",
    "allauth.account.middleware.AccountMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    # Project overrides must precede allauth's bundled account templates.
    "DIRS": [BASE_DIR / "accounts" / "templates"],
    "APP_DIRS": True,
    "OPTIONS": {
        "context_processors": [
            "django.template.context_processors.request",
            "django.contrib.auth.context_processors.auth",
            "django.contrib.messages.context_processors.messages",
            "accounts.navigation.navigation",
            "clubs.context_processors.clubs_navigation",
        ],
    },
}]

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ["POSTGRES_DB"],
        "USER": os.environ["POSTGRES_USER"],
        "PASSWORD": os.environ["POSTGRES_PASSWORD"],
        "HOST": "db",
        "PORT": "5432",
    }
}

AUTH_USER_MODEL = "accounts.User"
AUTHENTICATION_BACKENDS = [
    "django.contrib.auth.backends.ModelBackend",
    "allauth.account.auth_backends.AuthenticationBackend",
]
LOGIN_REDIRECT_URL = "/account/start/"
LOGIN_URL = "/accounts/login/"
ACCOUNT_LOGOUT_REDIRECT_URL = "/"
ACCOUNT_EMAIL_VERIFICATION = "mandatory"
ACCOUNT_LOGIN_METHODS = {"email"}
ACCOUNT_SIGNUP_FIELDS = ["email*"]
SOCIALACCOUNT_AUTO_SIGNUP = True
SOCIALACCOUNT_EMAIL_AUTHENTICATION = False
SOCIALACCOUNT_PROVIDERS = {
    "google": {
        "APP": {
            "client_id": os.environ.get("GOOGLE_CLIENT_ID", ""),
            "secret": os.environ.get("GOOGLE_CLIENT_SECRET", ""),
            "key": "",
        },
        "SCOPE": ["profile", "email"],
        "AUTH_PARAMS": {"access_type": "online"},
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation." + name}
    for name in (
        "UserAttributeSimilarityValidator",
        "MinimumLengthValidator",
        "CommonPasswordValidator",
        "NumericPasswordValidator",
    )
]

LANGUAGE_CODE = "en-gb"
TIME_ZONE = "Europe/Dublin"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

# Opt in only after the clubs verification/storage release checklist is reviewed.
CLUBS_ENABLED = os.environ.get("CLUBS_ENABLED", "0") == "1"
CLUB_EVIDENCE_BACKEND = os.environ.get("CLUB_EVIDENCE_BACKEND", "disabled")
CLUB_EVIDENCE_ROOT = os.environ.get("CLUB_EVIDENCE_ROOT", "")
CLUB_EVIDENCE_AZURE_CONNECTION_STRING = os.environ.get("CLUB_EVIDENCE_AZURE_CONNECTION_STRING", "")
CLUB_EVIDENCE_AZURE_CONTAINER = os.environ.get("CLUB_EVIDENCE_AZURE_CONTAINER", "")
CLUB_REVIEW_MFA_MAX_AGE = 300
CLUB_EVIDENCE_MAX_RETENTION_DAYS = 90
CLUB_SECURITY_RETENTION_DAYS = 30
# DatabaseCache can use the existing PostgreSQL; create its table explicitly at rollout.
if os.environ.get("DJANGO_CACHE_TABLE"):
    CACHES = {"default": {"BACKEND": "django.core.cache.backends.db.DatabaseCache",
        "LOCATION": os.environ["DJANGO_CACHE_TABLE"]}}
MFA_ADAPTER = "clubs.mfa.EncryptedMFAAdapter"
MFA_SUPPORTED_TYPES = ["totp", "recovery_codes"]
MFA_ENCRYPTION_KEYS = [key.strip() for key in os.environ.get("MFA_ENCRYPTION_KEYS", "").split(",") if key.strip()]

# Keep Firefox form origins while withholding referrers from external sites.
SECURE_REFERRER_POLICY = "same-origin"
