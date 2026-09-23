# Importa constantes de tiempo y factores de conversion desde el archivo de configuracion
from config import SEGUNDOS_POR_HORA, HORAS_POR_TURNO, HORAS_POR_DIA, KG_POR_TONELADA

# Calcula el peso neto efectivo descontando la tara del recipiente o bolsa
def calculate_net_weight(gross_weight_kg, tare_weight_kg=0.0):
    # Valida que el peso bruto no sea un numero negativo
    if gross_weight_kg < 0:
        # Lanza excepcion descriptiva si el valor ingresado es fisicamente imposible
        raise ValueError("El peso bruto no puede ser negativo.")
    # Valida que la tara no sea un numero negativo
    if tare_weight_kg < 0:
        # Lanza excepcion si la tara ingresada es negativa
        raise ValueError("La tara no puede ser negativa.")
    # Calcula la diferencia entre peso bruto y tara
    net_weight = gross_weight_kg - tare_weight_kg
    # Valida que la tara no supere al peso bruto total
    if net_weight < 0:
        # Lanza error si el peso neto resultante es negativo
        raise ValueError("La tara no puede ser mayor que el peso bruto.")
    # Retorna el peso neto redondeado con alta precision decimal
    return round(net_weight, 4)

# Calcula la velocidad instantanea de linea a partir de la pesada de una bolsa
def calculate_instant_speed(net_weight_kg, fill_time_seconds):
    # Valida que el tiempo de llenado sea estrictamente mayor a cero para evitar division por cero
    if fill_time_seconds <= 0:
        # Lanza excepcion indicando que el tiempo debe ser positivo
        raise ValueError("El tiempo de llenado de la bolsa debe ser mayor a 0 segundos.")
    # Valida que el peso neto no sea negativo
    if net_weight_kg < 0:
        # Lanza excepcion si el peso es menor a cero
        raise ValueError("El peso neto no puede ser negativo.")
    # Aplica la formula industrial: (P_bolsa / t_seg) * 3600 segundos/hora
    speed_kg_h = (net_weight_kg / fill_time_seconds) * SEGUNDOS_POR_HORA
    # Retorna la velocidad instantanea calculada en kilogramos por hora
    return round(speed_kg_h, 2)

# Proyecta la produccion para un turno de 8 horas de trabajo continuo
def project_shift_production(speed_kg_h, shift_hours=HORAS_POR_TURNO):
    # Valida que la velocidad no sea negativa
    if speed_kg_h < 0:
        # Lanza excepcion si la velocidad ingresada es negativa
        raise ValueError("La velocidad de produccion no puede ser negativa.")
    # Multiplica la velocidad en kg/h por la cantidad de horas del turno (8 horas)
    projected_kg = speed_kg_h * shift_hours
    # Retorna la produccion proyectada del turno en kilogramos
    return round(projected_kg, 2)

# Proyecta la produccion teorica diaria para 24 horas continuas
def project_daily_production(speed_kg_h, day_hours=HORAS_POR_DIA):
    # Valida que la velocidad no sea negativa
    if speed_kg_h < 0:
        # Lanza excepcion si la velocidad es menor a cero
        raise ValueError("La velocidad de produccion no puede ser negativa.")
    # Multiplica la velocidad en kg/h por 24 horas del dia
    projected_daily_kg = speed_kg_h * day_hours
    # Retorna la produccion proyectada de 24 horas en kilogramos
    return round(projected_daily_kg, 2)

# Calcula la produccion estimada considerando horas efectivas reales de operacion
def calculate_estimated_production(speed_kg_h, effective_hours):
    # Valida que las horas efectivas no sean negativas
    if effective_hours < 0:
        # Lanza excepcion si las horas son negativas
        raise ValueError("Las horas efectivas de operacion no pueden ser negativas.")
    # Multiplica la velocidad representativa por las horas reales sin paradas
    return round(speed_kg_h * effective_hours, 2)

# Calcula el promedio aritmetico de las velocidades horarias registradas
def calculate_arithmetic_average_speed(speeds_list):
    # Verifica si la lista de velocidades esta vacia
    if not speeds_list:
        # Retorna 0.0 si no existen muestras registradas
        return 0.0
    # Suma todas las velocidades registradas
    total_speed = sum(speeds_list)
    # Divide la suma por la cantidad total de muestras n
    avg_speed = total_speed / len(speeds_list)
    # Retorna el promedio aritmetico redondeado a dos decimales
    return round(avg_speed, 2)

# Calcula la velocidad agregada considerando el peso total acumulado y tiempo total
def calculate_aggregated_speed(samples):
    # Verifica si la lista de muestras esta vacia
    if not samples:
        # Retorna 0.0 si no hay muestras provistas
        return 0.0
    # Inicializa el acumulador de peso neto de las muestras
    total_weight = 0.0
    # Inicializa el acumulador de tiempo total de muestreo en segundos
    total_time_seconds = 0.0
    # Itera sobre cada muestra de la lista
    for sample in samples:
        # Suma el peso neto de la muestra actual
        total_weight += sample.get('net_weight_kg', 0.0)
        # Suma el tiempo de llenado en segundos de la muestra actual
        total_time_seconds += sample.get('fill_time_seconds', 0.0)
    # Valida que el tiempo total acumulado no sea cero
    if total_time_seconds <= 0:
        # Retorna 0.0 para evitar division por cero
        return 0.0
    # Aplica la formula de velocidad agregada: (Sum(P) / Sum(t)) * 3600
    agg_speed = (total_weight / total_time_seconds) * SEGUNDOS_POR_HORA
    # Retorna la velocidad agregada en kg/h
    return round(agg_speed, 2)
