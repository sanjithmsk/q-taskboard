from pathlib import Path
from datetime import timedelta
import os

from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent

# DEBUG is resolved first because it gates the production-only safety checks
# below. It defaults to False so a deploy that configures nothing is closed by
# default, not wide open. Local dev and docker-compose set DEBUG=true explicitly.
DEBUG = os.environ.get('DEBUG', 'false').lower() == 'true'

# SECRET_KEY signs the JWTs, so a shared/default value lets anyone forge a token
# for any user. A dev placeholder is tolerated only under DEBUG; in production the
# app refuses to boot unless a real, unique secret is supplied via the environment.
_INSECURE_SECRETS = {'', 'dev-secret-change-me-in-production', 'dev-secret-change-me'}
SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY', 'dev-secret-change-me-in-production')
if not DEBUG and SECRET_KEY in _INSECURE_SECRETS:
    raise ImproperlyConfigured(
        'DJANGO_SECRET_KEY must be set to a unique, non-default value when DEBUG is False.'
    )

# Wildcard host matching is a dev convenience. In production, ALLOWED_HOSTS must
# be listed explicitly (comma-separated env var).
if DEBUG:
    ALLOWED_HOSTS = ['*']
else:
    ALLOWED_HOSTS = [h.strip() for h in os.environ.get('ALLOWED_HOSTS', '').split(',') if h.strip()]

INSTALLED_APPS = [
    'django.contrib.contenttypes',
    'django.contrib.auth',
    'rest_framework',
    'corsheaders',
    'users',
    'projects',
]

MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.common.CommonMiddleware',
]

ROOT_URLCONF = 'taskboard.urls'
WSGI_APPLICATION = 'taskboard.wsgi.application'

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': os.environ.get('POSTGRES_DB', 'taskboard'),
        'USER': os.environ.get('POSTGRES_USER', 'taskboard'),
        'PASSWORD': os.environ.get('POSTGRES_PASSWORD', 'taskboard'),
        'HOST': os.environ.get('POSTGRES_HOST', 'localhost'),
        'PORT': os.environ.get('POSTGRES_PORT', '5432'),
    }
}

AUTH_USER_MODEL = 'users.User'
APPEND_SLASH = False

REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework_simplejwt.authentication.JWTAuthentication',
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',
    ],
    # ScopedRateThrottle only limits views that declare `throttle_scope`, so this
    # is inert for every endpoint except the auth views (users/views.py). The
    # 'auth' rate is disabled under DEBUG so local dev and the test suite are not
    # affected; in production it caps login/register attempts to slow brute force.
    'DEFAULT_THROTTLE_CLASSES': [
        'rest_framework.throttling.ScopedRateThrottle',
    ],
    'DEFAULT_THROTTLE_RATES': {
        'auth': None if DEBUG else os.environ.get('LOGIN_THROTTLE_RATE', '10/min'),
    },
}

SIMPLE_JWT = {
    # Kept at 30 days by default; override via env without a code change.
    'ACCESS_TOKEN_LIFETIME': timedelta(days=int(os.environ.get('JWT_ACCESS_TOKEN_DAYS', '30'))),
    'AUTH_HEADER_TYPES': ('Bearer',),
}

# Allow any origin only in dev. In production, list trusted origins explicitly via
# CORS_ALLOWED_ORIGINS (comma-separated env var).
if DEBUG:
    CORS_ALLOW_ALL_ORIGINS = True
else:
    CORS_ALLOW_ALL_ORIGINS = False
    CORS_ALLOWED_ORIGINS = [o.strip() for o in os.environ.get('CORS_ALLOWED_ORIGINS', '').split(',') if o.strip()]

# Baseline password strength rules. NOTE: Django only applies these where
# validate_password() is called (admin, password-change forms). The API register
# flow does not call it yet, so wiring it into RegisterSerializer is a follow-up
# (tracked under issue #4) — doing so now would reject the demo password
# 'password123' used by the seed data and existing tests.
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_TZ = True
