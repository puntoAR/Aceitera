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
    # Variable de entorno oficial provista por el entorno de ejecucion de Vercel
    os.environ.get('VERCEL')
    # Variable indicadora del ambiente en ejecucion dentro de Vercel
    or os.environ.get('VERCEL_ENV')
    # Region geografica asignada por la infraestructura de Vercel
    or os.environ.get('VERCEL_REGION')
    # Nombre de funcion asignado en ejecucion AWS Lambda subyacente
    or os.environ.get('AWS_LAMBDA_FUNCTION_NAME')
    # Directorio raiz de tareas asignado por contenedores serverless Lambda
    or os.environ.get('LAMBDA_TASK_ROOT')
)

# Prueba si un directorio tiene permisos reales de escritura en disco
def _can_write_dir(test_path):
    # Bloque de prueba de escritura protegida contra excepciones del SO
    try:
        # Crea la ruta de directorios si aun no existe en el sistema
        os.makedirs(test_path, exist_ok=True)
        # Define una ruta de archivo de prueba temporal en la ubicacion indicada
        probe = os.path.join(test_path, '.perm_probe')
        # Abre el archivo temporal en modo escritura para verificar permisos
        with open(probe, 'w') as f:
            # Escribe un dato minimo para confirmar operacion de escritura exitosa
            f.write('1')
        # Elimina el archivo de prueba para limpiar el directorio
        os.remove(probe)
        # Retorna verdadero indicando que el directorio admite escritura
        return True
    # Captura cualquier error de permisos o sistema de archivos de solo lectura
    except Exception:
        # Retorna falso cuando el sistema rechaza operaciones de escritura
        return False

# Si se detecta Vercel o el sistema de archivos local es de solo lectura, usar /tmp
if IS_VERCEL or not _can_write_dir(os.path.join(str(BASE_DIR), 'data')):
    # Directorio de datos en /tmp para entornos de solo lectura
    DATA_DIR = os.path.join('/tmp', 'data')
    # Directorio de logs en /tmp
    LOGS_DIR = os.path.join('/tmp', 'logs')
    # Directorio de respaldos en /tmp
    BACKUPS_DIR = os.path.join('/tmp', 'backups')
    # Directorio de fotografias de reparaciones de mantenimiento en /tmp
    MAINTENANCE_UPLOADS_DIR = os.path.join('/tmp', 'uploads', 'maintenance')
    # Directorio de paquetes de actualizacion del sistema en /tmp
    UPDATES_DIR = os.path.join('/tmp', 'updates')
    # Carpeta donde se descargan o colocan actualizaciones comprobadas pendientes de instalacion en /tmp
    PENDING_UPDATES_DIR = os.path.join(UPDATES_DIR, 'pending')
    # Carpeta historica de actualizaciones ya aplicadas en /tmp
    APPLIED_UPDATES_DIR = os.path.join(UPDATES_DIR, 'applied')
else:
    # Directorio de datos local en la carpeta data
    DATA_DIR = os.path.join(BASE_DIR, 'data')
    # Directorio de logs local en la carpeta logs
    LOGS_DIR = os.path.join(BASE_DIR, 'logs')
    # Directorio de respaldos local en backups
    BACKUPS_DIR = os.path.join(BASE_DIR, 'backups')
    # Directorio de fotografias de mantenimiento en static/uploads/maintenance
    MAINTENANCE_UPLOADS_DIR = os.path.join(str(BASE_DIR), 'static', 'uploads', 'maintenance')
    # Directorio de paquetes de actualizacion del sistema
    UPDATES_DIR = os.path.join(str(BASE_DIR), 'updates')
    # Carpeta donde se descargan o colocan actualizaciones comprobadas pendientes de instalacion
    PENDING_UPDATES_DIR = os.path.join(UPDATES_DIR, 'pending')
    # Carpeta historica de actualizaciones ya aplicadas
    APPLIED_UPDATES_DIR = os.path.join(UPDATES_DIR, 'applied')

# Intento de creacion de carpetas de operacion en disco local o temporal
try:
    # Crea la carpeta de base de datos si no existe
    os.makedirs(DATA_DIR, exist_ok=True)
    # Crea la carpeta de registros de logs si no existe
    os.makedirs(LOGS_DIR, exist_ok=True)
    # Crea la carpeta de copias de seguridad si no existe
    os.makedirs(BACKUPS_DIR, exist_ok=True)
    # Crea la carpeta de imagenes de reparaciones de mantenimiento
    os.makedirs(MAINTENANCE_UPLOADS_DIR, exist_ok=True)
    # Crea la carpeta de actualizaciones pendientes
    os.makedirs(PENDING_UPDATES_DIR, exist_ok=True)
    # Crea la carpeta de actualizaciones aplicadas
    os.makedirs(APPLIED_UPDATES_DIR, exist_ok=True)
# Manejo de error si el sistema de archivos actual no permite crear carpetas
except Exception:
    # Fallback definitivo a /tmp para datos si falla la creacion local
    DATA_DIR = os.path.join('/tmp', 'data')
    # Fallback definitivo a /tmp para logs del sistema
    LOGS_DIR = os.path.join('/tmp', 'logs')
    # Fallback definitivo a /tmp para respaldos
    BACKUPS_DIR = os.path.join('/tmp', 'backups')
    # Fallback definitivo para fotografias en /tmp
    MAINTENANCE_UPLOADS_DIR = os.path.join('/tmp', 'uploads', 'maintenance')
    # Fallback definitivo para paquetes de actualizacion en /tmp
    UPDATES_DIR = os.path.join('/tmp', 'updates')
    # Fallback definitivo para actualizaciones pendientes en /tmp
    PENDING_UPDATES_DIR = os.path.join(UPDATES_DIR, 'pending')
    # Fallback definitivo para actualizaciones aplicadas en /tmp
    APPLIED_UPDATES_DIR = os.path.join(UPDATES_DIR, 'applied')
    # Segundo intento de creacion en el directorio temporal
    try:
        # Crea la carpeta data dentro de /tmp
        os.makedirs(DATA_DIR, exist_ok=True)
        # Crea la carpeta logs dentro de /tmp
        os.makedirs(LOGS_DIR, exist_ok=True)
        # Crea la carpeta backups dentro de /tmp
        os.makedirs(BACKUPS_DIR, exist_ok=True)
        # Crea la carpeta de uploads dentro de /tmp
        os.makedirs(MAINTENANCE_UPLOADS_DIR, exist_ok=True)
        # Crea la carpeta de actualizaciones pendientes dentro de /tmp
        os.makedirs(PENDING_UPDATES_DIR, exist_ok=True)
        # Crea la carpeta de actualizaciones aplicadas dentro de /tmp
        os.makedirs(APPLIED_UPDATES_DIR, exist_ok=True)
    # Captura silenciosa si ya existen o no pueden crearse
    except Exception:
        # Continua la ejecucion sin detener el servidor
        pass

# Extensiones de imagen autorizadas para fotografias de reparacion
ALLOWED_IMAGE_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp'}

# Limite maximo de tamano de archivo para subida de imagenes (16 MB)
MAX_IMAGE_FILE_SIZE_BYTES = 16 * 1024 * 1024

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

# Variables para integracion opcional con Turso Cloud SQLite (persistencia serverless garantizada en Vercel)
TURSO_DATABASE_URL = os.environ.get('TURSO_DATABASE_URL', '').strip()
TURSO_AUTH_TOKEN = os.environ.get('TURSO_AUTH_TOKEN', '').strip()
USE_TURSO = bool(TURSO_DATABASE_URL and TURSO_AUTH_TOKEN)

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
