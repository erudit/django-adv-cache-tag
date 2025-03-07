import os.path
import zlib

DEBUG = False

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "default-cache",
    },
    "foo": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "foo-cache",
    },
}

ADV_CACHE_VERSIONING = False
ADV_CACHE_COMPRESS = False
ADV_CACHE_COMPRESS_LEVEL = zlib.Z_DEFAULT_COMPRESSION
ADV_CACHE_COMPRESS_SPACES = False
ADV_CACHE_INCLUDE_PK = False
ADV_CACHE_BACKEND = "default"
ADV_CACHE_VERSION = ""
ADV_CACHE_RESOLVE_NAME = False

SECRET_KEY = "m-92)2et+&&m5f&#jld7-_1qanq*n9!z90xc@+wx6y8d6y#w6t"

BASE_DIR = os.path.dirname(__file__)


def absolute_path(path):
    return os.path.normpath(os.path.join(BASE_DIR, path))


SITE_ID = 1
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": absolute_path("database.sqlite3"),
    }
}

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "adv_cache_tag",
    "adv_cache_tag.tests.testproject.adv_cache_test_app",
]

MIDDLEWARE_CLASSES = [
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "APP_DIRS": True,
        "OPTIONS": {"debug": False},
    },
]

USE_TZ = True
