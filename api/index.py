# Punto de entrada para despliegue en Vercel Serverless
import sys
import os
import traceback

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

_init_error = None
flask_app = None

try:
    from run import app as raw_app
    from core.database import init_db
    from core.migrations import apply_pending_migrations

    # Inicializa base de datos en /tmp de forma segura
    try:
        init_db()
        apply_pending_migrations()
    except Exception as db_err:
        print(f"[VERCEL] Aviso BD: {db_err}")

    flask_app = raw_app
except Exception as e:
    _init_error = traceback.format_exc()
    print(f"[VERCEL CRITICAL ERROR]:\n{_init_error}")

def app(environ, start_response):
    if _init_error:
        status = '200 OK'
        headers = [('Content-Type', 'text/plain; charset=utf-8')]
        start_response(status, headers)
        return [f"=== VERCEL INITIALIZATION ERROR ===\n\n{_init_error}".encode('utf-8')]

    try:
        return flask_app(environ, start_response)
    except Exception as req_err:
        status = '200 OK'
        headers = [('Content-Type', 'text/plain; charset=utf-8')]
        start_response(status, headers)
        err_trace = traceback.format_exc()
        return [f"=== VERCEL RUNTIME ERROR ===\n\n{err_trace}".encode('utf-8')]

handler = app
