# Punto de entrada para despliegue en Vercel Serverless
import sys
import os

# Agrega la raiz del proyecto al path de Python para resolver modulos
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

# Importa la aplicacion Flask configurada
from run import app
from core.database import init_db
from core.migrations import apply_pending_migrations

# Inicializa la base de datos y migraciones en el entorno serverless (/tmp)
try:
    init_db()
    apply_pending_migrations()
except Exception as e:
    print(f"[VERCEL] Aviso al inicializar base de datos: {e}")

# Vercel Serverless Function expone la instancia WSGI llamada 'app'
