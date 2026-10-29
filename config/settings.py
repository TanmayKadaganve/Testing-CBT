"""
Django settings for PyForgeLabs CBT College LAN Platform.
Supports dual-mode configuration:
- Local offline development (SQLite default)
- Institutional LAN production (PostgreSQL, Nginx, Gunicorn, HTTPS)
"""

import os
from pathlib import Path
import urllib.parse as urlparse

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# Quick-start development settings - unsuitable for production
DEBUG = os.environ.get("DJANGO_DEBUG", "False").lower() in ("true", "1", "yes")
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "")
if not SECRET_KEY:
    if not DEBUG:
        raise RuntimeError("DJANGO_SECRET_KEY must be set when DJANGO_DEBUG is false.")
    SECRET_KEY = "django-insecure-local-development-only-change-me"
if not DEBUG and SECRET_KEY.lower().startswith(("replace_", "change_me", "paste_")):
    raise RuntimeError("Replace the DJANGO_SECRET_KEY placeholder with a generated secret.")

# Allowed Hosts: defaults to localhost, testserver, and RFC1918 private subnets
allowed_hosts_env = os.environ.get("DJANGO_ALLOWED_HOSTS", "")
if allowed_hosts_env:
    ALLOWED_HOSTS = [h.strip() for h in allowed_hosts_env.split(",") if h.strip()]
else:
    ALLOWED_HOSTS = [
        "127.0.0.1",
        "localhost",
        "testserver",
        ".local",
    ]
if not DEBUG and not allowed_hosts_env:
    raise RuntimeError("DJANGO_ALLOWED_HOSTS must be explicitly configured in production.")

# CSRF Trusted Origins for LAN clients
csrf_origins_env = os.environ.get("DJANGO_CSRF_TRUSTED_ORIGINS", "")
if csrf_origins_env:
    CSRF_TRUSTED_ORIGINS = [o.strip() for o in csrf_origins_env.split(",") if o.strip()]
else:
    CSRF_TRUSTED_ORIGINS = [
        "http://127.0.0.1:8000",
        "http://localhost:8000",
        "http://127.0.0.1",
        "http://localhost",
    ]
if not DEBUG and not csrf_origins_env:
    raise RuntimeError("DJANGO_CSRF_TRUSTED_ORIGINS must be explicitly configured in production.")

CSRF_FAILURE_VIEW = "portal.views.csrf_failure"

# Application definition
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "portal",
    "recruitment",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "portal.middleware.PerformanceMonitoringMiddleware",
]

LOGIN_URL = "/admin/login/"
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
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

# Database Configuration:
# - If DATABASE_URL or DB_ENGINE=postgresql is provided, use PostgreSQL with connection pooling
# - Otherwise, use local SQLite database safely
DATABASE_URL = os.environ.get("DATABASE_URL")
if not DEBUG and not ((DATABASE_URL and DATABASE_URL.startswith("postgres")) or os.environ.get("DB_ENGINE") == "postgresql"):
    raise RuntimeError("Configure DATABASE_URL or DB_ENGINE=postgresql for production.")
if DATABASE_URL and DATABASE_URL.startswith("postgres"):
    url = urlparse.urlparse(DATABASE_URL)
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": url.path[1:],
            "USER": url.username or "postgres",
            "PASSWORD": url.password or "",
            "HOST": url.hostname or "localhost",
            "PORT": url.port or "5432",
            "CONN_MAX_AGE": int(os.environ.get("DB_CONN_MAX_AGE", 60)),
            "OPTIONS": {
                "connect_timeout": 10,
            },
        }
    }
elif os.environ.get("DB_ENGINE") == "postgresql":
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.environ.get("DB_NAME", "cbt_db"),
            "USER": os.environ.get("DB_USER", "cbt_user"),
            "PASSWORD": os.environ.get("DB_PASSWORD", ""),
            "HOST": os.environ.get("DB_HOST", "localhost"),
            "PORT": os.environ.get("DB_PORT", "5432"),
            "CONN_MAX_AGE": int(os.environ.get("DB_CONN_MAX_AGE", 60)),
            "OPTIONS": {
                "connect_timeout": 10,
            },
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
            "OPTIONS": {
                "timeout": 20,
            },
        }
    }

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# Internationalization
LANGUAGE_CODE = "en-us"
TIME_ZONE = "Asia/Kolkata"
USE_I18N = True
USE_TZ = True

# Static files (CSS, JavaScript, Images)
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

# Production Security & Cookie Protection
if not DEBUG:
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SESSION_COOKIE_HTTPONLY = True
    CSRF_COOKIE_HTTPONLY = False
    SECURE_BROWSER_XSS_FILTER = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    X_FRAME_OPTIONS = "DENY"
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = os.environ.get("DJANGO_SECURE_SSL_REDIRECT", "True").lower() in ("true", "1", "yes")

# Untrusted code runs locally only in explicit development mode. Production fails closed
# through the container runner; there is no automatic fallback to host subprocesses.
CODE_EXECUTION_BACKEND = os.environ.get("CODE_EXECUTION_BACKEND", "local" if DEBUG else "container").lower()
if CODE_EXECUTION_BACKEND not in ("local", "container"):
    raise RuntimeError("CODE_EXECUTION_BACKEND must be 'container' or 'local'.")
CODE_EXECUTION_ALLOW_UNSANDBOXED = DEBUG and os.environ.get("CODE_EXECUTION_ALLOW_UNSANDBOXED", "True").lower() in ("true", "1", "yes")
CODE_EXECUTION_CONTAINER_RUNTIME = os.environ.get("CODE_EXECUTION_CONTAINER_RUNTIME", "podman")
CODE_EXECUTION_CONTAINER_IMAGE = os.environ.get("CODE_EXECUTION_CONTAINER_IMAGE", "pyforgelabs/runner:latest")
EXECUTION_WORKER_HEARTBEAT_DIR = Path(os.environ.get("EXECUTION_WORKER_HEARTBEAT_DIR", BASE_DIR / ".worker-heartbeats"))

# Structured Logging
LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "standard": {
            "format": "[%(asctime)s] %(levelname)s [%(name)s:%(lineno)s] %(message)s",
            "datefmt": "%Y-%m-%d %H:%M:%S",
        },
    },
    "handlers": {
        "console": {
            "level": "INFO",
            "class": "logging.StreamHandler",
            "formatter": "standard",
        },
        "file": {
            "level": "INFO",
            "class": "logging.handlers.RotatingFileHandler",
            "filename": str(LOG_DIR / "cbt_server.log"),
            "maxBytes": 10 * 1024 * 1024,  # 10 MB
            "backupCount": 5,
            "formatter": "standard",
            "encoding": "utf-8",
        },
    },
    "loggers": {
        "django": {
            "handlers": ["console", "file"],
            "level": "INFO",
            "propagate": True,
        },
        "portal": {
            "handlers": ["console", "file"],
            "level": "INFO",
            "propagate": True,
        },
    },
}

# Email backend (console for testing and offline operations)
MAILERS = {
    "default": {
        "BACKEND": "django.core.mail.backends.console.EmailBackend",
    },
}
