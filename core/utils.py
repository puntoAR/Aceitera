"""
Módulo de utilidades generales para BioBalcarce.
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
