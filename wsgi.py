"""WSGI entry point for production hosting (PythonAnywhere, gunicorn, etc.).

The hosting platform imports `application` from this file. Set SECRET_KEY
and HTTPS=1 in the environment (or in the platform's WSGI wrapper) before
this module is imported.
"""
from app import app as application  # noqa: F401
