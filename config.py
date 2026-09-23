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

# Define la ruta del directorio de almacenamiento de datos SQLite y respaldos
DATA_DIR = os.path.join(BASE_DIR, 'data')

# Define la ruta del directorio de logs para el sistema de diagnostico
LOGS_DIR = os.path.join(BASE_DIR, 'logs')

# Asegura que el directorio de datos exista, creandolo si no esta presente
os.makedirs(DATA_DIR, exist_ok=True)

# Asegura que el directorio de logs exista, creandolo si no esta presente
os.makedirs(LOGS_DIR, exist_ok=True)

# Define la ruta del archivo de base de datos principal de SQLite
DATABASE_PATH = os.path.join(DATA_DIR, 'biobalcarce.db')

# Define la ruta del archivo de log de eventos y diagnostico de errores
LOG_FILE_PATH = os.path.join(LOGS_DIR, 'system.log')

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
