"""
Módulo de gestión de zona horaria oficial de planta BioBalcarce.
La planta industrial opera en Balcarce, Buenos Aires, Argentina (UTC-3).
Argentina no aplica horario de verano desde 2009 (UTC-3 permanente).
Garantiza que todas las marcas de tiempo (pesadas, paradas, laboratorio,
auditoría, etc.) coincidan con el reloj local de los operarios y planta,
tanto en ejecuciones locales como en servidores serverless en la nube (Vercel/AWS).
"""
import datetime

# Zona horaria oficial de Balcarce, Argentina: UTC-3 fijo permanente
PLANT_TZ = datetime.timezone(datetime.timedelta(hours=-3), name="ART")

def get_plant_now() -> datetime.datetime:
    """
    Retorna objeto datetime consciente de la zona horaria de planta BioBalcarce (UTC-3).
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
