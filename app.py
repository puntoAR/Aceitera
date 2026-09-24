# Entrypoint principal para Vercel Serverless y entornos WSGI
import sys
import os

# Agrega la ruta raiz al path de Python
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from run import app
from core.database import init_db
from core.migrations import apply_pending_migrations

# Inicializa la base de datos de manera segura al arrancar
try:
    init_db()
    apply_pending_migrations()
except Exception as e:
    print(f"[VERCEL] Aviso al inicializar base de datos: {e}")

if __name__ == '__main__':
    app.run()
