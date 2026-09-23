# Importa el modulo math para funciones trigonometricas y constantes pi y raiz cuadrada
import math
# Importa los factores de conversion de volumen desde la configuracion
from config import LITROS_POR_M3

# Calcula el volumen ocupado en un tanque cilindrico vertical de fondo plano
def calculate_vertical_tank_volume(diameter_m, height_m, level_m):
    # Valida que el diametro del tanque sea un numero positivo
    if diameter_m <= 0:
        # Lanza excepcion si el diametro es menor o igual a cero
        raise ValueError("El diametro del tanque vertical debe ser mayor a 0 metros.")
    # Valida que la altura util del tanque sea positiva
    if height_m <= 0:
        # Lanza excepcion si la altura del tanque no es valida
        raise ValueError("La altura util del tanque vertical debe ser mayor a 0 metros.")
    # Valida que el nivel medido no sea negativo
    if level_m < 0:
        # Lanza excepcion si el nivel de aceite es negativo
        raise ValueError("El nivel medido de aceite no puede ser negativo.")
    # Valida que el nivel no exceda la altura fisica del tanque
    if level_m > height_m:
        # Lanza excepcion indicando desborde o error de medicion
        raise ValueError(f"El nivel medido ({level_m} m) supera la altura maxima del tanque ({height_m} m).")
    # Calcula el radio interior del tanque dividiendo el diametro por dos
    radius = diameter_m / 2.0
    # Aplica la formula de volumen cilindrico: V = pi * r^2 * h
    volume_m3 = math.pi * (radius ** 2) * level_m
    # Retorna el volumen en metros cubicos redondeado a 4 decimales
    return round(volume_m3, 4)

# Calcula la capacidad total maxima de un tanque cilindrico vertical
def calculate_vertical_tank_max_volume(diameter_m, height_m):
    # Llama a la funcion con el nivel igual a la altura maxima
    return calculate_vertical_tank_volume(diameter_m, height_m, height_m)

# Calcula el volumen ocupado en un tanque cilindrico horizontal segun su nivel
def calculate_horizontal_tank_volume(diameter_m, length_m, level_m):
    # Valida que el diametro del tanque sea positivo
    if diameter_m <= 0:
        # Lanza excepcion si el diametro no es valido
        raise ValueError("El diametro del tanque horizontal debe ser mayor a 0 metros.")
    # Valida que la longitud del tanque sea positiva
    if length_m <= 0:
        # Lanza excepcion si la longitud es menor o igual a cero
        raise ValueError("La longitud del tanque horizontal debe ser mayor a 0 metros.")
    # Valida que el nivel de liquido no sea negativo
    if level_m < 0:
        # Lanza excepcion si el nivel es negativo
        raise ValueError("El nivel medido de aceite no puede ser negativo.")
    # Valida que el nivel no supere el diametro fisico del tanque horizontal
    if level_m > diameter_m:
        # Lanza excepcion por nivel superior al tope del cilindro horizontal
        raise ValueError(f"El nivel ({level_m} m) supera el diametro del tanque horizontal ({diameter_m} m).")
    # Calcula el radio interior del tanque
    r = diameter_m / 2.0
    # Longitud interior del tanque
    l = length_m
    # Caso borde: tanque completamente vacio
    if level_m == 0:
        # Retorna volumen cero
        return 0.0
    # Caso borde: tanque completamente lleno (nivel igual al diametro 2*r)
    if math.isclose(level_m, diameter_m, rel_tol=1e-5):
        # Retorna el volumen cilindrico total pi * r^2 * L
        return round(math.pi * (r ** 2) * l, 4)
    # Caso especial: tanque exactamente a medio llenar (nivel igual al radio)
    if math.isclose(level_m, r, rel_tol=1e-5):
        # Retorna exactamente la mitad del volumen cilindrico total
        return round((math.pi * (r ** 2) * l) / 2.0, 4)
    # Variable de altura de fluido h
    h = level_m
    # Calcula el termino interior para el arcocoseno asegurando rango valido [-1, 1]
    term = max(-1.0, min(1.0, (r - h) / r))
    # Calcula el angulo alfa en radianes mediante arcocoseno
    alpha = math.acos(term)
    # Calcula el termino de la raiz cuadrada: sqrt(2*r*h - h^2)
    sqrt_term = math.sqrt(max(0.0, (2.0 * r * h) - (h ** 2)))
    # Aplica la formula geometrica exacta del tanque horizontal: V = L * [r^2 * acos((r-h)/r) - (r-h)*sqrt(2*r*h - h^2)]
    volume_m3 = l * ((r ** 2) * alpha - (r - h) * sqrt_term)
    # Retorna el volumen calculado en metros cubicos
    return round(volume_m3, 4)

# Calcula la capacidad maxima total de un tanque cilindrico horizontal
def calculate_horizontal_tank_max_volume(diameter_m, length_m):
    # Llama a la funcion horizontal con nivel igual al diametro completo
    return calculate_horizontal_tank_volume(diameter_m, length_m, diameter_m)

# Convierte volumen en metros cubicos a litros y masa en kilogramos
def convert_volume_to_mass(volume_m3, density_kg_l=0.92, heel_liters=0.0):
    # Valida que la densidad del aceite sea positiva
    if density_kg_l <= 0:
        # Lanza excepcion si la densidad no es positiva
        raise ValueError("La densidad del aceite debe ser mayor a 0 kg/L.")
    # Valida que el talon no bombeable no sea negativo
    if heel_liters < 0:
        # Lanza excepcion si el talon es negativo
        raise ValueError("El volumen de talon no bombeable no puede ser negativo.")
    # Convierte metros cubicos a litros multiplicando por 1000
    total_liters = volume_m3 * LITROS_POR_M3
    # Calcula los litros utiles descontando el talon no bombeable
    useful_liters = max(0.0, total_liters - heel_liters)
    # Convierte litros totales a masa total en kilogramos usando la densidad
    total_mass_kg = total_liters * density_kg_l
    # Convierte litros utiles a masa util en kilogramos
    useful_mass_kg = useful_liters * density_kg_l
    # Retorna un diccionario con todas las magnitudes calculadas
    return {
        'volume_m3': round(volume_m3, 4),           # Volumen ocupado en m3
        'total_liters': round(total_liters, 2),       # Litros totales contenidos
        'useful_liters': round(useful_liters, 2),     # Litros utiles disponibles
        'heel_liters': round(heel_liters, 2),         # Litros de fondo no bombeable
        'total_mass_kg': round(total_mass_kg, 2),     # Masa total de aceite en kg
        'useful_mass_kg': round(useful_mass_kg, 2),   # Masa util de aceite en kg
        'density_kg_l': density_kg_l                  # Densidad aplicada
    }

# Calcula la produccion neta de aceite en un periodo considerando despachos
def calculate_net_oil_production(initial_stock_kg, final_stock_kg, external_outflows_kg=0.0, external_inflows_kg=0.0):
    # Valida que los valores ingresados no sean negativos
    if initial_stock_kg < 0 or final_stock_kg < 0:
        # Lanza excepcion si los stocks son menores a cero
        raise ValueError("Los stocks inicial y final no pueden ser negativos.")
    # Aplica la formula de conciliacion: S_final - S_inicial + Salidas - Entradas
    net_production_kg = final_stock_kg - initial_stock_kg + external_outflows_kg - external_inflows_kg
    # Retorna la produccion neta en kilogramos
    return round(net_production_kg, 2)
