"""WSGI entry point for production hosting (Render / gunicorn / any PaaS).

The hosting platform serves `application` from this file, e.g. on Render:
    gunicorn wsgi:application --bind 0.0.0.0:$PORT
Set SECRET_KEY, HTTPS=1, and DATABASE_URL in the environment before this
module is imported (see render.yaml and DEPLOY.md).
"""
from app import app as application  # noqa: F401
