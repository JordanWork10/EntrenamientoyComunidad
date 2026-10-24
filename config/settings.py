"""
Configuracion principal de EntrenamientoyComunidadV2.
Django 6.1.1, PostgreSQL, Espanol y America/Santiago.
V129: seguridad de cuentas, correo SMTP y django-axes.
"""

from datetime import timedelta
from pathlib import Path
import os

from dotenv import load_dotenv
from django.core.exceptions import ImproperlyConfigured


# =====================================================
# RUTAS DEL PROYECTO
# =====================================================

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / '.env')


# =====================================================
# SEGURIDAD
# =====================================================

SECRET_KEY = os.getenv('DJANGO_SECRET_KEY')

if not SECRET_KEY:
    raise ImproperlyConfigured(
        'Falta DJANGO_SECRET_KEY en el archivo .env.'
    )

DEBUG = os.getenv('DJANGO_DEBUG', 'True').strip().lower() in (
    'true', '1', 'yes', 'on',
)

ALLOWED_HOSTS = [
    host.strip()
    for host in os.getenv('DJANGO_ALLOWED_HOSTS', '').split(',')
    if host.strip()
]


# =====================================================
# APLICACIONES
# =====================================================

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',

    # V129 - Registro y seguimiento de intentos fallidos.
    'axes',

    'apps.accounts',
    'apps.locations',
    'apps.core',
    'apps.professionals',
    'apps.bookings',
    'apps.spaces.apps.SpacesConfig',
    'apps.activities.apps.ActivitiesConfig',
    'apps.subscriptions.apps.SubscriptionsConfig',
    'apps.payments.apps.PaymentsConfig',
]


# =====================================================
# MIDDLEWARE
# =====================================================

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',

    # Django-Axes debe ir al final de la lista.
    'axes.middleware.AxesMiddleware',
]

ROOT_URLCONF = 'config.urls'


# =====================================================
# PLANTILLAS
# =====================================================

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'


# =====================================================
# BASE DE DATOS - POSTGRESQL
# =====================================================

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': os.getenv('DB_NAME'),
        'USER': os.getenv('DB_USER'),
        'PASSWORD': os.getenv('DB_PASSWORD'),
        'HOST': os.getenv('DB_HOST'),
        'PORT': os.getenv('DB_PORT', '5432'),
    }
}


# =====================================================
# VALIDACION DE CONTRASENAS
# =====================================================

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': (
            'django.contrib.auth.password_validation.'
            'UserAttributeSimilarityValidator'
        ),
    },
    {
        'NAME': (
            'django.contrib.auth.password_validation.'
            'MinimumLengthValidator'
        ),
    },
    {
        'NAME': (
            'django.contrib.auth.password_validation.'
            'CommonPasswordValidator'
        ),
    },
    {
        'NAME': (
            'django.contrib.auth.password_validation.'
            'NumericPasswordValidator'
        ),
    },
]


# =====================================================
# IDIOMA Y ZONA HORARIA
# =====================================================

LANGUAGE_CODE = 'es'
TIME_ZONE = 'America/Santiago'
USE_I18N = True
USE_TZ = True


# =====================================================
# ARCHIVOS ESTATICOS Y MULTIMEDIA
# =====================================================

STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / 'static']

MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'


# =====================================================
# CUENTA UNICA UNIVERSAL
# =====================================================

AUTH_USER_MODEL = 'accounts.User'


# =====================================================
# V129 - PROTECCION DE INICIO DE SESION CON DJANGO-AXES
# =====================================================

AUTHENTICATION_BACKENDS = [
    'axes.backends.AxesStandaloneBackend',
    'django.contrib.auth.backends.ModelBackend',
]

# Cinco contrasenas incorrectas dentro de una ventana de 15 minutos.
AXES_FAILURE_LIMIT = 5
AXES_COOLOFF_TIME = timedelta(minutes=15)
AXES_USE_ATTEMPT_EXPIRATION = True

# Se rastrea el par identificador/IP; no se bloquea toda una red
# compartida por errores cometidos desde otro identificador.
# La vista de inicio de sesion debe pasar el username canonico
# al autenticar con correo o RUT para no duplicar contadores.
AXES_LOCKOUT_PARAMETERS = [['username', 'ip_address']]

AXES_RESET_ON_SUCCESS = True
AXES_HTTP_RESPONSE_CODE = 429
AXES_ENABLE_RETRY_AFTER_HEADER = True

# V129 - Pantalla de bloqueo accesible y coherente con la plataforma.
AXES_LOCKOUT_TEMPLATE = 'accounts/login_locked.html'

# Configuracion conservadora para uso local. Al desplegar con
# proxy inverso, revisar los encabezados y el IP real del cliente.
AXES_IPWARE_META_PRECEDENCE_ORDER = ('REMOTE_ADDR',)


# =====================================================
# V129 - CORREOS
# =====================================================

EMAIL_DELIVERY_MODE = os.getenv(
    'EMAIL_DELIVERY_MODE', 'console'
).strip().lower()

DEFAULT_FROM_EMAIL = os.getenv(
    'DEFAULT_FROM_EMAIL', 'webmaster@localhost'
)

if EMAIL_DELIVERY_MODE == 'console':
    MAILERS = {
        'default': {
            'BACKEND': 'django.core.mail.backends.console.EmailBackend',
        },
    }

elif EMAIL_DELIVERY_MODE == 'smtp':
    smtp_host = os.getenv('SMTP_HOST', '').strip()
    smtp_username = os.getenv('SMTP_USERNAME', '').strip()
    smtp_password = os.getenv('SMTP_PASSWORD', '')
    smtp_port = int(os.getenv('SMTP_PORT', '587'))

    smtp_use_tls = os.getenv('SMTP_USE_TLS', 'true').strip().lower() in (
        'true', '1', 'yes', 'on',
    )
    smtp_use_ssl = os.getenv('SMTP_USE_SSL', 'false').strip().lower() in (
        'true', '1', 'yes', 'on',
    )

    if smtp_use_tls and smtp_use_ssl:
        raise ImproperlyConfigured(
            'SMTP_USE_TLS y SMTP_USE_SSL no pueden estar activos simultaneamente.'
        )

    if not all([smtp_host, smtp_username, smtp_password]):
        raise ImproperlyConfigured(
            'Faltan las credenciales SMTP en el archivo .env.'
        )

    MAILERS = {
        'default': {
            'BACKEND': 'django.core.mail.backends.smtp.EmailBackend',
            'OPTIONS': {
                'host': smtp_host,
                'port': smtp_port,
                'username': smtp_username,
                'password': smtp_password,
                'use_tls': smtp_use_tls,
                'use_ssl': smtp_use_ssl,
                'timeout': 15,
            },
        },
    }

else:
    raise ImproperlyConfigured(
        'EMAIL_DELIVERY_MODE debe ser console o smtp.'
    )


# =====================================================
# V129 - RECUPERACION DE CONTRASENAS
# =====================================================

PASSWORD_RESET_TIMEOUT = 60 * 60


# =====================================================
# PAGOS - ENTORNO DE DESARROLLO
# =====================================================

PAYMENTS_SANDBOX = DEBUG
