# Entrypoint oficial para despliegue en Vercel (Zero-configuration Flask)
import sys
import os

# Agrega la ruta raiz del proyecto al path de Python
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

# Importa la aplicacion Flask configurada
from run import app
from core.database import init_db
from core.migrations import apply_pending_migrations

# Inicializa la base de datos y migraciones de manera segura
try:
    init_db()
    apply_pending_migrations()
except Exception as e:
    print(f"[VERCEL] Aviso al inicializar base de datos: {e}")

if __name__ == '__main__':
    app.run()
