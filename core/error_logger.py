# Importa el modulo datetime para manejar marcas temporales en los logs
import datetime
# Importa el modulo os para verificacion y manejo de archivos de registro
import os
# Importa el modulo traceback para capturar la traza completa de excepciones
import traceback
# Importa la ruta del archivo de logs definida en la configuracion central
from config import LOG_FILE_PATH

# Define la funcion principal para registrar mensajes con nivel de severidad
def log_event(level, module_name, message, exc=None):
    # Obtiene la fecha y hora actual en formato legible ISO para auditoria
    now_str = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    # Prepara el texto del detalle de la excepcion si fue provista
    exc_details = ''
    # Verifica si se paso un objeto de excepcion para extraer su traza
    if exc is not None:
        # Extrae la traza formateada completa de la excepcion ocurrida
        exc_details = '\n' + ''.join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    # Formatea la linea de registro con fecha, nivel, modulo y mensaje
    log_line = f"[{now_str}] [{level.upper()}] [{module_name}] {message}{exc_details}\n"
    # Abre el archivo de registro en modo de anexo con codificacion utf-8
    with open(LOG_FILE_PATH, 'a', encoding='utf-8') as f:
        # Escribe la linea de registro en el archivo persistente en disco
        f.write(log_line)

    # Si el evento es un ERROR, tambien lo almacena en la tabla system_errors de la base de datos
    if level.upper() == 'ERROR':
        try:
            # Importa dinamicamente la conexion a base de datos
            from core.database import get_db_connection
            # Intenta obtener usuario y endpoint del contexto de Flask si existe
            user_id = None
            username = 'SISTEMA'
            endpoint = module_name
            try:
                # Importa componentes de Flask
                from flask import request, g, has_request_context
                # Si estamos dentro de una peticion web
                if has_request_context():
                    # Asigna la ruta de la peticion
                    endpoint = request.path or module_name
                    # Si hay usuario autenticado
                    if hasattr(g, 'user') and g.user:
                        user_id = g.user.get('id')
                        username = g.user.get('username', 'DESCONOCIDO')
            except Exception:
                pass
            # Abre conexion con base de datos
            with get_db_connection() as conn:
                # Inserta el error en system_errors
                conn.execute("""
                    INSERT INTO system_errors (
                        timestamp, user_id, username, endpoint,
                        error_type, error_message, traceback
                    ) VALUES (?, ?, ?, ?, ?, ?, ?);
                """, (now_str, user_id, username, endpoint,
                      type(exc).__name__ if exc else 'Exception',
                      str(message), exc_details.strip() if exc_details else None))
                conn.commit()
        except Exception:
            # Evita fallos en cascada si la base de datos no estuviera disponible
            pass

# Funcion utilitaria para registrar mensajes informativos normales del sistema
def log_info(module_name, message):
    # Llama a log_event con el nivel INFO para auditoria de operacion habitual
    log_event('INFO', module_name, message)

# Funcion utilitaria para registrar advertencias o condiciones atipicas
def log_warning(module_name, message):
    # Llama a log_event con el nivel WARNING para alertar desviaciones
    log_event('WARNING', module_name, message)

# Funcion utilitaria para registrar errores críticos o excepciones capturadas
def log_error(module_name, message, exc=None):
    # Llama a log_event con el nivel ERROR incluyendo la traza del error
    log_event('ERROR', module_name, message, exc=exc)

# Funcion para leer las ultimas lineas de log para el sistema de diagnostico
def get_recent_logs(max_lines=50):
    # Verifica si el archivo de log no existe todavia en el disco
    if not os.path.exists(LOG_FILE_PATH):
        # Retorna una lista vacia si el archivo no ha sido creado aun
        return []
    # Abre el archivo de log en modo lectura para inspeccionar las lineas
    with open(LOG_FILE_PATH, 'r', encoding='utf-8') as f:
        # Lee todas las lineas almacenadas en el archivo de texto
        lines = f.readlines()
        # Retorna las ultimas N lineas solicitadas para visualizacion rapida
        return lines[-max_lines:]
