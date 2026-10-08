"""
Módulo de gestión de zona horaria oficial de planta.
La planta industrial opera con huso horario de Argentina (UTC-3).
Argentina no aplica horario de verano desde 2009 (UTC-3 permanente).
Garantiza que todas las marcas de tiempo (pesadas, paradas, laboratorio,
auditoría, etc.) coincidan con el reloj local de los operarios y planta,
tanto en ejecuciones locales como en servidores serverless en la nube (Vercel/AWS).
"""
import datetime

# Zona horaria oficial de planta, Argentina: UTC-3 fijo permanente
PLANT_TZ = datetime.timezone(datetime.timedelta(hours=-3), name="ART")

def get_plant_now() -> datetime.datetime:
    """
    Retorna objeto datetime consciente de la zona horaria de planta (UTC-3).
    """
    return datetime.datetime.now(PLANT_TZ)

def get_plant_now_str(fmt: str = '%Y-%m-%d %H:%M:%S') -> str:
    """
    Retorna la fecha y hora actual de la planta formateada en cadena de texto.
    Por defecto: 'YYYY-MM-DD HH:MM:SS'.
    """
    return get_plant_now().strftime(fmt)

def get_plant_today_str() -> str:
    """
    Retorna la fecha calendario actual de la planta en formato ISO 'YYYY-MM-DD'.
    """
    return get_plant_now().strftime('%Y-%m-%d')


def determine_time_slot(dt_or_str=None) -> dict:
    """
    Determina la franja horaria y turno operativo para una fecha/hora dada o la actual.
    Turnos oficiales de planta:
      - TM (Turno Mañana): 06:00 a 13:59:59 (06:00 - 14:00)
      - TT (Turno Tarde):  14:00 a 21:59:59 (14:00 - 22:00)
      - TN (Turno Noche):  22:00 a 05:59:59 (22:00 - 06:00)
    
    Retorna un diccionario con:
      - 'shift_id': 'TM' | 'TT' | 'TN'
      - 'shift_name': 'Turno Mañana (06:00 - 14:00)' | ...
      - 'time_slot': '06:00 - 14:00' | ...
      - 'operational_date': 'YYYY-MM-DD' (el TN de madrugada 00-06h pertenece a la jornada iniciada a las 22h del día anterior)
      - 'calendar_date': 'YYYY-MM-DD'
    """
    if dt_or_str is None:
        dt = get_plant_now()
    elif isinstance(dt_or_str, datetime.datetime):
        dt = dt_or_str
    elif isinstance(dt_or_str, str):
        cleaned = dt_or_str.strip()
        # Admite formatos ISO con y sin segundos
        dt = None
        for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M', '%Y-%m-%dT%H:%M:%S', '%Y-%m-%d'):
            try:
                dt = datetime.datetime.strptime(cleaned, fmt)
                break
            except ValueError:
                continue
        if dt is None:
            dt = get_plant_now()
    else:
        dt = get_plant_now()

    hour = dt.hour
    if 6 <= hour < 14:
        shift_id = 'TM'
        shift_name = 'Turno Mañana (06:00 - 14:00)'
        time_slot = '06:00 - 14:00'
        operational_date = dt.strftime('%Y-%m-%d')
    elif 14 <= hour < 22:
        shift_id = 'TT'
        shift_name = 'Turno Tarde (14:00 - 22:00)'
        time_slot = '14:00 - 22:00'
        operational_date = dt.strftime('%Y-%m-%d')
    else:
        shift_id = 'TN'
        shift_name = 'Turno Noche (22:00 - 06:00)'
        time_slot = '22:00 - 06:00'
        # Si la muestra fue registrada entre 00:00 y 05:59, pertenece al turno noche iniciado a las 22:00 de la jornada anterior
        if hour < 6:
            prev_day = dt - datetime.timedelta(days=1)
            operational_date = prev_day.strftime('%Y-%m-%d')
        else:
            operational_date = dt.strftime('%Y-%m-%d')

    return {
        'shift_id': shift_id,
        'shift_name': shift_name,
        'time_slot': time_slot,
        'operational_date': operational_date,
        'calendar_date': dt.strftime('%Y-%m-%d')
    }


def get_current_time_slot() -> dict:
    """
    Retorna la franja horaria y turno actualmente en curso en la planta.
    """
    return determine_time_slot(get_plant_now())


def get_current_operational_date() -> str:
    """
    Retorna la fecha operativa actual de la planta.
    """
    return get_current_time_slot()['operational_date']

