import os
from pathlib import Path
from dotenv import load_dotenv
from datetime import timedelta

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# Load environment variables from .env file
load_dotenv(BASE_DIR / '.env')

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = os.getenv('DJANGO_SECRET_KEY', 'django-insecure-s(hwac(hhq+9(q4a@gw5$hx-9i7$6$#3oo1+sjvw1^kk@us$o(')

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = os.getenv('DEBUG', 'True').lower() == 'true'

ALLOWED_HOSTS = os.getenv('ALLOWED_HOSTS', 'localhost,127.0.0.1').split(',')

# Application definition
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'accounts',
    'strategies',
    'rest_framework_simplejwt',
    'channels',
    'rest_framework',
    'strategies.brokers.tradovate.apps.TradovateConfig',
    'corsheaders',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'my_project.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'my_project.wsgi.application'
ASGI_APPLICATION = 'my_project.asgi.application'

# Database
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}

REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'rest_framework_simplejwt.authentication.JWTAuthentication',
    ),
}



# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',},
]

SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(minutes=60),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=7),
    'ROTATE_REFRESH_TOKENS': True,
    'BLACKLIST_AFTER_ROTATION': True,
    'AUTH_HEADER_TYPES': ('Bearer',),
    'AUTH_TOKEN_CLASSES': ('rest_framework_simplejwt.tokens.AccessToken',),
}

# Internationalization
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True
LOGIN_URL = '/api/auth/login/'
#APPEND_SLASH = False

# Static files (CSS, JavaScript, Images)
STATIC_URL = 'static/'

# Default primary key field type
DEFAULT_AUTO_Field = 'django.db.models.BigAutoField'

# Custom User Model
AUTH_USER_MODEL = 'accounts.CustomUser'

# CORS settings
CORS_ALLOW_ALL_ORIGINS = True
CORS_ALLOWED_ORIGINS = [
    "http://localhost:3000",
]
CORS_ALLOW_CREDENTIALS = True

CSRF_TRUSTED_ORIGINS = ['http://localhost:3000']

# Tradovate settings
TRADOVATE_CLIENT_ID = os.getenv('TRADOVATE_CLIENT_ID')
TRADOVATE_CLIENT_SECRET = os.getenv('TRADOVATE_CLIENT_SECRET')
TRADOVATE_REDIRECT_URI = os.getenv('TRADOVATE_REDIRECT_URI')
TRADOVATE_AUTH_URL = os.getenv('TRADOVATE_AUTH_URL')

# Tradovate Live environment
TRADOVATE_LIVE_EXCHANGE_URL = os.getenv('TRADOVATE_LIVE_EXCHANGE_URL')
TRADOVATE_LIVE_API_URL = os.getenv('TRADOVATE_LIVE_API_URL')

# Tradovate Demo environment
TRADOVATE_DEMO_EXCHANGE_URL = os.getenv('TRADOVATE_DEMO_EXCHANGE_URL')
TRADOVATE_DEMO_API_URL = os.getenv('TRADOVATE_DEMO_API_URL')

# Dynamic Tradovate URLs based on environment
TRADOVATE_ENVIRONMENT = os.getenv('TRADOVATE_ENVIRONMENT', 'demo')
TRADOVATE_EXCHANGE_URL = TRADOVATE_LIVE_EXCHANGE_URL if TRADOVATE_ENVIRONMENT == 'live' else TRADOVATE_DEMO_EXCHANGE_URL
TRADOVATE_API_URL = TRADOVATE_LIVE_API_URL if TRADOVATE_ENVIRONMENT == 'live' else TRADOVATE_DEMO_API_URL

TRADOVATE_LIVE_WS_URL = os.getenv('TRADOVATE_LIVE_WS_URL')
TRADOVATE_DEMO_WS_URL = os.getenv('TRADOVATE_DEMO_WS_URL')

# Frontend URL
FRONTEND_URL = os.getenv('FRONTEND_URL', 'http://localhost:3000')

# Channel layers for WebSocket
CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels.layers.InMemoryChannelLayer"
    }
}
CORS_ALLOWED_ORIGINS_REGEXES = [
    r"^http://localhost:3000$",
    r"^http://127.0.0.1:3000$",
]


# Claude AI settings
CLAUDE_API_KEY = os.getenv('CLAUDE_API_KEY')

# Logging configuration
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': 'INFO',
    },
}

CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels.layers.InMemoryChannelLayer"
    }
}

# Cache configuration
#CACHES = {
    #'default': {
        #'BACKEND': 'django_redis.cache.RedisCache',
        #'LOCATION': 'redis://127.0.0.1:6379/1',
        #'OPTIONS': {
            #'CLIENT_CLASS': 'django_redis.client.DefaultClient',
        #}
    #}
#}

# Validation of required settings
required_settings = [
    'TRADOVATE_CLIENT_ID', 'TRADOVATE_CLIENT_SECRET', 'TRADOVATE_REDIRECT_URI',
    'TRADOVATE_AUTH_URL', 'TRADOVATE_LIVE_EXCHANGE_URL', 'TRADOVATE_LIVE_API_URL',
    'TRADOVATE_DEMO_EXCHANGE_URL', 'TRADOVATE_DEMO_API_URL', 'CLAUDE_API_KEY'
]

for setting in required_settings:
    if not globals().get(setting):
        raise ValueError(f"{setting} is not set in the environment or .env file")
    
WSCONFIG = {
    'RECONNECT_INTERVAL': 1000,
    'MAX_RECONNECT_ATTEMPTS': 5
}


WEBSOCKET_MAX_CONNECTIONS = 100
WEBSOCKET_CLEANUP_INTERVAL = 300
WEBSOCKET_HEARTBEAT_INTERVAL = 15
WEBSOCKET_RATE_LIMIT = 60