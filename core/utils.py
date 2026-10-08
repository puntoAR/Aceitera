"""
Módulo de utilidades generales para Control de Planta Aceitera.
Proporciona funciones para conversión robusta de tipos numéricos,
normalización y sanitización de entradas de formularios web e importaciones.
"""

def safe_float(value, default=0.0):
    """
    Convierte de forma segura cualquier valor (incluyendo cadenas vacías, espacios,
    números con coma decimal estilo Argentina/Español '12,5', None, etc.) a float.
    Si default es None y el valor está vacío o no es numérico, retorna None.
    """
    if value is None:
        return default
    if isinstance(value, float):
        return value
    if isinstance(value, int):
        return float(value)
    
    # Limpia la cadena y normaliza comas a puntos decimales
    s = str(value).strip().replace(',', '.')
    if not s:
        return default
    try:
        return float(s)
    except (ValueError, TypeError):
        return default

def safe_int(value, default=0):
    """
    Convierte de forma segura cualquier valor a entero, limpiando posibles
    formatos decimales ('10.0' -> 10) o valores nulos/vacíos.
    Si default es None y el valor está vacío o no es numérico, retorna None.
    """
    if value is None:
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    
    # Limpia la cadena y remueve cualquier fracción decimal
    s = str(value).strip().split('.')[0].split(',')[0]
    if not s:
        return default
    try:
        return int(s)
    except (ValueError, TypeError):
        return default

# Importa expresiones regulares para reconocimiento de formatos de fechas
import re # Modulo re para expresiones regulares
# Importa datetime para manipulacion de objetos temporales
import datetime # Modulo datetime para fechas y horas

# Funcion para normalizar cadenas de fecha y hora a formato estandar ISO YYYY-MM-DD HH:MM:SS
def normalize_date_str(val): # Recibe valor de fecha en texto, objeto date/datetime o numerico
    # Si el valor recibido es nulo retorna cadena vacia
    if val is None: # Comprobacion de valor nulo
        # Retorna texto vacio
        return '' # Valor por omision vacio
    # Si ya es un objeto datetime de Python
    if isinstance(val, datetime.datetime): # Comprobacion de tipo datetime
        # Retorna en formato ISO con hora, minutos y segundos
        return val.strftime('%Y-%m-%d %H:%M:%S') # Formatea a cadena estandar
    # Si es un objeto date de Python
    if isinstance(val, datetime.date): # Comprobacion de tipo date
        # Retorna en formato ISO con hora cero
        return val.strftime('%Y-%m-%d 00:00:00') # Formatea a cadena estandar
    # Si es un numero (posible numero de serie de fecha de Excel)
    if isinstance(val, (int, float)): # Comprobacion de tipo numerico
        # Si el rango corresponde a fechas de Excel contemporaneas
        if 20000 <= val <= 80000: # Rango de dias seriales de Excel
            # Bloque de proteccion ante error de conversion
            try: # Intento de conversion
                # Calcula la fecha a partir del dia base de Excel (1899-12-30)
                base_dt = datetime.datetime(1899, 12, 30) + datetime.timedelta(days=float(val)) # Suma dias a fecha base
                # Retorna la fecha calculada
                return base_dt.strftime('%Y-%m-%d %H:%M:%S') # Retorna ISO estandar
            # Si ocurre un fallo en el calculo
            except Exception: # Captura excepcion
                # Continua con conversion a texto
                pass # Pasa
    # Convierte a cadena de texto sin espacios en los bordes
    s = str(val).strip() # Limpieza de espacios
    # Si el texto quedo vacio o representa valores nulos
    if not s or s.lower() in ('none', 'null', '-', 'nan'): # Verificacion de valores vacios o nulos
        # Retorna cadena vacia
        return '' # Retorna vacio
    # Comprueba patron ISO: YYYY-MM-DD o YYYY/MM/DD seguido de hora opcional
    m_iso = re.match(r'^(\d{4})[-/](\d{1,2})[-/](\d{1,2})(.*)', s) # Expresion regular ISO
    # Si coincide con formato ISO
    if m_iso: # Coincidencia ISO
        # Extrae grupos de anio, mes, dia y resto horario
        y, m, d, rest = m_iso.groups() # Asigna partes
        # Limpia caracteres de hora y reemplaza separador T
        time_part = rest.strip().replace('T', ' ') # Limpia hora
        # Si no tiene parte horaria
        if not time_part: # Sin hora
            # Asigna medianoche por defecto
            time_part = '00:00:00' # Hora cero
        # Si tiene hora y minutos sin segundos
        elif len(time_part.split(':')) == 2: # Hora HH:MM
            # Agrega segundos en cero
            time_part += ':00' # Agrega segundos
        # Retorna fecha ISO normalizada con ceros a la izquierda
        return f"{int(y):04d}-{int(m):02d}-{int(d):02d} {time_part}".strip() # Ensambla fecha normalizada
    # Comprueba patron latino: DD/MM/YYYY o DD-MM-YYYY seguido de hora opcional
    m_lat = re.match(r'^(\d{1,2})[-/](\d{1,2})[-/](\d{2,4})(.*)', s) # Expresion regular latina
    # Si coincide con formato latino
    if m_lat: # Coincidencia latina
        # Extrae dia, mes, anio y resto horario
        d, m, y, rest = m_lat.groups() # Asigna partes
        # Convierte anio a entero
        y_int = int(y) # Anio numerico
        # Si el anio fue expresado en 2 digitos (ej. 26)
        if y_int < 100: # Anio corto
            # Convierte a siglo XXI
            y_int += 2000 # Convierte a 20XX
        # Limpia caracteres de hora
        time_part = rest.strip().replace('T', ' ') # Limpia hora
        # Si no tiene parte horaria
        if not time_part: # Sin hora
            # Asigna medianoche por defecto
            time_part = '00:00:00' # Hora cero
        # Si tiene hora y minutos sin segundos
        elif len(time_part.split(':')) == 2: # Hora HH:MM
            # Agrega segundos en cero
            time_part += ':00' # Agrega segundos
        # Retorna fecha ISO estandar YYYY-MM-DD HH:MM:SS
        return f"{y_int:04d}-{int(m):02d}-{int(d):02d} {time_part}".strip() # Ensambla fecha ISO
    # Retorna cadena original como fallback
    return s # Fallback

