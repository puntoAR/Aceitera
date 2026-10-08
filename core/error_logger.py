# Importa el modulo datetime para manejar marcas temporales en los logs
import datetime
# Importa el modulo os para verificacion y manejo de archivos de registro
import os
# Importa re para analisis de expresiones regulares sobre trazas de error
import re
# Importa el modulo traceback para capturar la traza completa de excepciones
import traceback
# Importa la ruta del archivo de logs definida en la configuracion central
from config import LOG_FILE_PATH
# Importa la funcion horaria oficial de planta (Argentina UTC-3)
from core.timezone import get_plant_now_str

# Analiza una traza de error en texto plano para deducir el archivo, linea, funcion y codigo causante
def parse_traceback_origin(tb_text):
    # Si la traza de texto esta vacia retorna estructura con valores nulos
    if not tb_text:
        return {'origin_file': None, 'origin_line': None, 'origin_func': None, 'origin_code': None}
    # Expresion regular para extraer el patron estandar de traceback de Python
    pattern = r'File\s+"([^"]+)",\s+line\s+(\d+),\s+in\s+([^\r\n]+)(?:[\r\n]+\s*(.+))?'
    # Busca todas las coincidencias en la cadena de traza
    matches = list(re.finditer(pattern, str(tb_text)))
    # Si se encontraron coincidencias en la traza
    if matches:
        # Toma el ultimo cuadro de ejecucion donde se produjo el error
        last_match = matches[-1]
        # Normaliza la ruta del archivo con barras inclinadas
        raw_filepath = last_match.group(1).replace('\\', '/')
        # Si la ruta contiene modulos del proyecto extrae la ruta relativa legible
        if 'modules/' in raw_filepath:
            filepath = 'modules/' + raw_filepath.split('modules/')[-1]
        # Si la ruta contiene el directorio central core
        elif 'core/' in raw_filepath:
            filepath = 'core/' + raw_filepath.split('core/')[-1]
        # Si la ruta contiene api o run
        elif 'api/' in raw_filepath:
            filepath = 'api/' + raw_filepath.split('api/')[-1]
        # En caso general utiliza el nombre base del archivo
        else:
            filepath = os.path.basename(raw_filepath)
        # Extrae el numero de linea como entero
        lineno = int(last_match.group(2))
        # Extrae el nombre de la funcion o ambito
        func = last_match.group(3).strip()
        # Extrae la instruccion de codigo fuente si fue capturada
        code = last_match.group(4).strip() if last_match.group(4) else ''
        # Retorna el diccionario con la informacion de origen
        return {
            'origin_file': filepath,
            'origin_line': lineno,
            'origin_func': func,
            'origin_code': code
        }
    # Si no hubo coincidencia retorna valores nulos
    return {'origin_file': None, 'origin_line': None, 'origin_func': None, 'origin_code': None}

# Define la funcion principal para registrar mensajes con nivel de severidad
def log_event(level, module_name, message, exc=None):
    # Obtiene la fecha y hora oficial de planta (Argentina UTC-3) para auditoria
    now_str = get_plant_now_str()
    # Prepara el texto del detalle de la excepcion si fue provista
    exc_details = ''
    # Variables de localizacion del origen del error
    origin_file = None
    origin_line = None
    origin_func = None
    origin_code = None
    # Verifica si se paso un objeto de excepcion para extraer su traza
    if exc is not None:
        # Extrae la traza formateada completa de la excepcion ocurrida
        exc_details = '\n' + ''.join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        try:
            # Extrae la lista de cuadros de la llamada
            frames = traceback.extract_tb(exc.__traceback__)
            # Si existen cuadros en la pila
            if frames:
                # Toma el ultimo cuadro donde se produjo la falla
                last_frame = frames[-1]
                # Normaliza la ruta del archivo con barras inclinadas
                raw_filename = last_frame.filename.replace('\\', '/')
                # Simplifica la ruta a partir de los directorios clave del proyecto
                if 'modules/' in raw_filename:
                    origin_file = 'modules/' + raw_filename.split('modules/')[-1]
                elif 'core/' in raw_filename:
                    origin_file = 'core/' + raw_filename.split('core/')[-1]
                elif 'api/' in raw_filename:
                    origin_file = 'api/' + raw_filename.split('api/')[-1]
                elif 'diagnostics/' in raw_filename:
                    origin_file = 'diagnostics/' + raw_filename.split('diagnostics/')[-1]
                elif 'tests/' in raw_filename:
                    origin_file = 'tests/' + raw_filename.split('tests/')[-1]
                else:
                    origin_file = os.path.basename(raw_filename)
                # Almacena el numero de linea
                origin_line = int(last_frame.lineno)
                # Almacena el nombre de la funcion o metodo
                origin_func = str(last_frame.name)
                # Almacena la linea de codigo afectada
                origin_code = str(last_frame.line).strip() if last_frame.line else ''
        except Exception:
            # Continua si ocurriera algun error en la inspeccion del marco
            pass

    # Prepara mensaje enriquecido combinando el contexto y la descripcion de la excepcion
    if exc is not None:
        # Cadena representativa de la excepcion
        exc_str = str(exc).strip()
        # Si la excepcion tiene contenido y no esta duplicada en el mensaje
        if exc_str and exc_str not in str(message):
            detailed_message = f"{message}: {exc_str}"
        else:
            detailed_message = str(message)
    else:
        detailed_message = str(message)

    # Formatea la linea de registro con fecha, nivel, modulo y mensaje
    log_line = f"[{now_str}] [{level.upper()}] [{module_name}] {detailed_message}{exc_details}\n"
    # Abre el archivo de registro en modo de anexo con codificacion utf-8
    try:
        with open(LOG_FILE_PATH, 'a', encoding='utf-8') as f:
            f.write(log_line)
    except Exception:
        # En entornos serverless con filesystem restringido, emite a stdout/stderr
        try:
            print(log_line.strip())
        except Exception:
            pass

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
                try:
                    # Intenta insertar con las columnas extendidas de diagnostico
                    conn.execute("""
                        INSERT INTO system_errors (
                            timestamp, user_id, username, endpoint,
                            error_type, error_message, traceback,
                            origin_file, origin_line, origin_func, origin_code
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                    """, (now_str, user_id, username, endpoint,
                          type(exc).__name__ if exc else 'Exception',
                          detailed_message, exc_details.strip() if exc_details else None,
                          origin_file, origin_line, origin_func, origin_code))
                except Exception:
                    # Si la base aun no cuenta con las columnas extendidas, usa la estructura previa
                    conn.execute("""
                        INSERT INTO system_errors (
                            timestamp, user_id, username, endpoint,
                            error_type, error_message, traceback
                        ) VALUES (?, ?, ?, ?, ?, ?, ?);
                    """, (now_str, user_id, username, endpoint,
                          type(exc).__name__ if exc else 'Exception',
                          detailed_message, exc_details.strip() if exc_details else None))
                # Confirma la insercion en base de datos
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
