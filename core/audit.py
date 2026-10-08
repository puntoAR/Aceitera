# Modulo de auditoria de actividades para trazabilidad y cumplimiento de seguridad
# Importa datetime para estampas de fecha y hora precisas
import datetime
# Importa la conexion a base de datos de SQLite
from core.database import get_db_connection
# Importa error_logger para registrar incidencias de auditoria
from core.error_logger import log_info, log_error
# Importa funcion horaria oficial de planta (Argentina UTC-3)
from core.timezone import get_plant_now_str

# Intenta importar el contexto de peticion de Flask para extraer IP y usuario activo
try:
    # Importa request y g de Flask
    from flask import request, g, has_request_context
except ImportError:
    # Modo fallback sin contexto de Flask para scripts CLI
    has_request_context = lambda: False
    request = None
    g = None

# Registra un evento en la tabla de auditoria del sistema
def record_audit_event(category, action, details, status='OK', user_override=None, ip_override=None):
    # Inicializa variables de identificacion
    user_id = None
    username = 'SISTEMA'
    role = 'SISTEMA'
    ip_address = '127.0.0.1'

    # Verifica si se ejecuta dentro del ciclo de vida de una peticion web
    if has_request_context() and request is not None:
        # Extrae la direccion IP del cliente (considerando proxies si existen)
        if request.headers.get('X-Forwarded-For'):
            # Toma la primera IP de la cadena de reenvio
            ip_address = request.headers.get('X-Forwarded-For').split(',')[0].strip()
        else:
            # Toma la IP directa reportada por el socket
            ip_address = request.remote_addr or '127.0.0.1'
        
        # Verifica si hay un usuario autenticado cargado en g.user
        if hasattr(g, 'user') and g.user:
            # Asigna el ID del usuario
            user_id = g.user.get('id')
            # Asigna el nombre de usuario
            username = g.user.get('username', 'DESCONOCIDO')
            # Asigna el rol
            role = g.user.get('role', 'DESCONOCIDO')

    # Permite sobrescribir el usuario si se pasa explícitamente (ej. intentos de login fallidos)
    if user_override:
        # Asigna el nombre provisto
        username = str(user_override)
        
    # Permite sobrescribir la IP si se pasa explícitamente
    if ip_override:
        # Asigna la IP provista
        ip_address = str(ip_override)

    # Estampa de tiempo oficial de planta (Argentina UTC-3)
    now_str = get_plant_now_str()

    try:
        # Abre conexion para insertar el registro de auditoria
        with get_db_connection() as conn:
            # Inserta el evento en la tabla audit_logs
            conn.execute("""
                INSERT INTO audit_logs (
                    timestamp, user_id, username, role, ip_address,
                    category, action, details, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
            """, (now_str, user_id, username, role, ip_address, category, action, details, status))
            # Confirma la transaccion
            conn.commit()
    except Exception as e:
        # Registra en log de texto si ocurre un fallo al escribir la auditoria
        log_error('AUDIT', f'Error al registrar auditoria: {action} - {details}', e)
