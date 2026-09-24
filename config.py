# Importa el modulo os para interactuar con el sistema operativo y rutas de archivos
import os
# Importa Path de pathlib para manipulacion moderna y multiplataforma de rutas
from pathlib import Path

# Importa site y sys para asegurar acceso a las dependencias de .venv si se ejecuta fuera de el
import site
import sys

# Obtiene la ruta absoluta del directorio donde se encuentra este archivo de configuracion
BASE_DIR = Path(__file__).resolve().parent

# Auto-vincula el directorio site-packages del entorno virtual .venv local si existe
_venv_sp_win = os.path.join(str(BASE_DIR), '.venv', 'Lib', 'site-packages')
_venv_sp_nix = os.path.join(str(BASE_DIR), '.venv', 'lib', f'python{sys.version_info.major}.{sys.version_info.minor}', 'site-packages')
if os.path.exists(_venv_sp_win) and _venv_sp_win not in sys.path:
    site.addsitedir(_venv_sp_win)
elif os.path.exists(_venv_sp_nix) and _venv_sp_nix not in sys.path:
    site.addsitedir(_venv_sp_nix)

# Detecta si se esta ejecutando en entorno Serverless (Vercel, AWS Lambda, Cloud Run, etc.)
IS_VERCEL = bool(
    os.environ.get('VERCEL')
    or os.environ.get('VERCEL_ENV')
    or os.environ.get('VERCEL_REGION')
    or os.environ.get('AWS_LAMBDA_FUNCTION_NAME')
    or os.environ.get('LAMBDA_TASK_ROOT')
)

# Prueba si un directorio tiene permisos reales de escritura en disco
def _can_write_dir(test_path):
    try:
        os.makedirs(test_path, exist_ok=True)
        probe = os.path.join(test_path, '.perm_probe')
        with open(probe, 'w') as f:
            f.write('1')
        os.remove(probe)
        return True
    except Exception:
        return False

# Si se detecta Vercel o el sistema de archivos local es de solo lectura, usar /tmp
if IS_VERCEL or not _can_write_dir(os.path.join(str(BASE_DIR), 'data')):
    DATA_DIR = os.path.join('/tmp', 'data')
    LOGS_DIR = os.path.join('/tmp', 'logs')
    BACKUPS_DIR = os.path.join('/tmp', 'backups')
else:
    DATA_DIR = os.path.join(BASE_DIR, 'data')
    LOGS_DIR = os.path.join(BASE_DIR, 'logs')
    BACKUPS_DIR = os.path.join(BASE_DIR, 'backups')

try:
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(LOGS_DIR, exist_ok=True)
    os.makedirs(BACKUPS_DIR, exist_ok=True)
except Exception:
    # Fallback definitivo a /tmp si falla la creacion
    DATA_DIR = os.path.join('/tmp', 'data')
    LOGS_DIR = os.path.join('/tmp', 'logs')
    BACKUPS_DIR = os.path.join('/tmp', 'backups')
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        os.makedirs(LOGS_DIR, exist_ok=True)
        os.makedirs(BACKUPS_DIR, exist_ok=True)
    except Exception:
        pass

# Define la ruta del archivo de base de datos principal de SQLite
DATABASE_PATH = os.path.join(DATA_DIR, 'biobalcarce.db')

# Define la ruta del archivo de log de eventos y diagnostico de errores
LOG_FILE_PATH = os.path.join(LOGS_DIR, 'system.log')

# En entornos temporales, copia la base de datos precargada si existe y aun no esta en /tmp
if str(DATA_DIR).startswith('/tmp') or str(DATA_DIR).startswith('\\tmp'):
    seed_db = os.path.join(str(BASE_DIR), 'data', 'biobalcarce.db')
    if os.path.exists(seed_db) and not os.path.exists(DATABASE_PATH):
        try:
            import shutil
            shutil.copy2(seed_db, DATABASE_PATH)
        except Exception:
            pass

# Clave secreta para proteccion criptografica de sesiones en Flask
SECRET_KEY = os.environ.get('SECRET_KEY', 'biobalcarce-clave-segura-industrial-2026')

# Puerto de red predeterminado en el que escuchara la aplicacion web
PORT = int(os.environ.get('PORT', 5000))

# Host de red para escuchar conexiones locales y en red de la planta (0.0.0.0 permite acceso desde movil)
HOST = os.environ.get('HOST', '0.0.0.0')

# Indicador de modo depuracion para el servidor web (auto-recarga al modificar codigo o plantillas)
DEBUG = os.environ.get('DEBUG', 'True').lower() in ('true', '1', 't')

# Factor de conversion estandar: segundos en una hora
SEGUNDOS_POR_HORA = 3600

# Factor de conversion estandar: horas en un dia operativo
HORAS_POR_DIA = 24

# Factor de conversion estandar: horas en un turno estandar de trabajo
HORAS_POR_TURNO = 8

# Factor de conversion estandar: kilogramos en una tonelada metrica
KG_POR_TONELADA = 1000.0

# Factor de conversion estandar: litros contenidos en un metro cubico
LITROS_POR_M3 = 1000.0

# Factor de conversion para peso hectolitrico a densidad aparente kg/m3 (1 hl = 0.1 m3)
FACTOR_CONVERSION_PH = 10.0

# URL predeterminada del servidor o repositorio para consultar manifiestos de actualizacion
DEFAULT_UPDATE_SERVER_URL = os.environ.get(
    'UPDATE_SERVER_URL',
    'https://raw.githubusercontent.com/biobalcarce/updates/main/latest.json'
)
