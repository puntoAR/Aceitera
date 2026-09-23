# Importa math para pi y operaciones geometricas
import math
# Importa los factores de conversion desde la configuracion global
from config import FACTOR_CONVERSION_PH, KG_POR_TONELADA

# Calcula el volumen del cuerpo cilindrico del silo segun chapas cubiertas
def calculate_cylinder_volume(diameter_m, sheet_height_m, covered_sheets, partial_sheet_height_m=0.0):
    # Valida que el diametro del silo sea mayor a cero
    if diameter_m <= 0:
        # Lanza excepcion si el diametro es invalido
        raise ValueError("El diametro del silo debe ser mayor a 0 metros.")
    # Valida que la altura unitaria de la chapa sea mayor a cero
    if sheet_height_m <= 0:
        # Lanza excepcion si la altura de chapa es invalida
        raise ValueError("La altura de la chapa debe ser mayor a 0 metros.")
    # Valida que la cantidad de chapas no sea negativa
    if covered_sheets < 0:
        # Lanza excepcion si las chapas cubiertas son negativas
        raise ValueError("La cantidad de chapas cubiertas no puede ser negativa.")
    # Valida que la altura adicional no sea negativa
    if partial_sheet_height_m < 0:
        # Lanza excepcion si la altura adicional es negativa
        raise ValueError("La altura adicional en chapa parcial no puede ser negativa.")
    # Calcula el radio del cilindro dividiendo el diametro por dos
    radius = diameter_m / 2.0
    # Calcula la altura cilindrica total ocupada: (N * H_chapa) + H_adicional
    height_cylinder = (covered_sheets * sheet_height_m) + partial_sheet_height_m
    # Aplica la formula de volumen cilindrico: V = pi * r^2 * H_c
    volume_m3 = math.pi * (radius ** 2) * height_cylinder
    # Retorna el volumen cilindrico calculado en metros cubicos
    return round(volume_m3, 4)

# Calcula el volumen del cono inferior del silo
def calculate_bottom_cone_volume(diameter_m, cone_height_m, cone_type='cone', min_diameter_m=0.0, status='lleno'):
    # Valida que el diametro del silo sea positivo
    if diameter_m <= 0:
        # Lanza excepcion por diametro invalido
        raise ValueError("El diametro del silo debe ser mayor a 0 metros.")
    # Valida que la altura del cono no sea negativa
    if cone_height_m < 0:
        # Lanza excepcion si la altura es negativa
        raise ValueError("La altura del cono no puede ser negativa.")
    # Si la altura del cono es cero o el estado es vacio
    if cone_height_m == 0 or status == 'vacio':
        # Retorna volumen cero
        return 0.0
    # Calcula el radio mayor del cono
    r_major = diameter_m / 2.0
    # Verifica si es un cono conico completo
    if cone_type == 'cone' or min_diameter_m <= 0:
        # Aplica la formula de cono regular: V = (1/3) * pi * r^2 * h
        volume_cone = (1.0 / 3.0) * math.pi * (r_major ** 2) * cone_height_m
    else:
        # Es un tronco de cono: calcula el radio menor de la base inferior
        r_minor = min_diameter_m / 2.0
        # Aplica la formula de tronco de cono: V = (1/3) * pi * h * (R^2 + R*r + r^2)
        volume_cone = (1.0 / 3.0) * math.pi * cone_height_m * ((r_major ** 2) + (r_major * r_minor) + (r_minor ** 2))
    # Si el estado es parcial, estima el 50% del cono
    if status == 'parcial':
        # Reduce a la mitad el volumen del cono
        volume_cone *= 0.5
    # Retorna el volumen del cono en m3
    return round(volume_cone, 4)

# Calcula el volumen del copete superior conico del silo
def calculate_copete_volume(diameter_m, copete_height_m):
    # Valida que el diametro sea positivo
    if diameter_m <= 0:
        # Lanza excepcion si el diametro es invalido
        raise ValueError("El diametro del silo debe ser mayor a 0 metros.")
    # Valida que la altura del copete no sea negativa
    if copete_height_m < 0:
        # Lanza excepcion si la altura del copete es negativa
        raise ValueError("La altura del copete no puede ser negativa.")
    # Si no hay copete o su altura es cero
    if copete_height_m == 0:
        # Retorna volumen cero
        return 0.0
    # Calcula el radio de la base del copete
    radius = diameter_m / 2.0
    # Aplica la formula de volumen conico del copete: V = (1/3) * pi * r^2 * h_copete
    volume_copete = (1.0 / 3.0) * math.pi * (radius ** 2) * copete_height_m
    # Retorna el volumen del copete en m3
    return round(volume_copete, 4)

# Calcula el cubicaje completo del silo sumando cono, cilindro y copete
def calculate_silo_total_volume(diameter_m, sheet_height_m, covered_sheets, partial_sheet_height_m,
                               bottom_cone_height_m, bottom_cone_type, min_diameter_m, cone_status,
                               copete_height_m):
    # Calcula el volumen del cuerpo cilindrico
    v_cylinder = calculate_cylinder_volume(diameter_m, sheet_height_m, covered_sheets, partial_sheet_height_m)
    # Calcula el volumen del cono inferior
    v_cone = calculate_bottom_cone_volume(diameter_m, bottom_cone_height_m, bottom_cone_type, min_diameter_m, cone_status)
    # Calcula el volumen del copete superior
    v_copete = calculate_copete_volume(diameter_m, copete_height_m)
    # Suma los tres componentes volumetricos
    total_volume_m3 = v_cylinder + v_cone + v_copete
    # Retorna un desglose detallado con cada componente y el total
    return {
        'v_cylinder_m3': v_cylinder,                # Volumen del cuerpo de chapas
        'v_cone_m3': v_cone,                        # Volumen del cono inferior
        'v_copete_m3': v_copete,                    # Volumen del copete superior
        'total_volume_m3': round(total_volume_m3, 4) # Volumen total en m3
    }

# Convierte el volumen de semilla a masa en kilogramos usando peso hectolitrico
def convert_silo_volume_to_seed_mass(volume_m3, hectolitric_weight_kg_hl=44.0):
    # Valida que el peso hectolitrico sea positivo
    if hectolitric_weight_kg_hl <= 0:
        # Lanza excepcion si el peso hectolitrico no es positivo
        raise ValueError("El peso hectolitrico debe ser mayor a 0 kg/hl.")
    # Convierte peso hectolitrico a densidad aparente en kg/m3 (multiplicando por 10)
    bulk_density_kg_m3 = hectolitric_weight_kg_hl * FACTOR_CONVERSION_PH
    # Multiplica el volumen total en m3 por la densidad aparente para obtener masa en kg
    total_mass_kg = volume_m3 * bulk_density_kg_m3
    # Convierte masa a toneladas dividiendo por 1000
    total_tons = total_mass_kg / KG_POR_TONELADA
    # Retorna diccionario con resultados
    return {
        'volume_m3': round(volume_m3, 4),
        'ph_kg_hl': hectolitric_weight_kg_hl,
        'bulk_density_kg_m3': round(bulk_density_kg_m3, 2),
        'total_mass_kg': round(total_mass_kg, 2),
        'total_tons': round(total_tons, 3)
    }

# Convierte el volumen de expeller a masa en kilogramos usando densidad aparente
def convert_silo_volume_to_expeller_mass(volume_m3, bulk_density_kg_m3=250.0):
    # Valida que la densidad aparente sea positiva
    if bulk_density_kg_m3 <= 0:
        # Lanza excepcion si la densidad aparente no es valida
        raise ValueError("La densidad aparente del expeller debe ser mayor a 0 kg/m3.")
    # Multiplica volumen por densidad aparente
    total_mass_kg = volume_m3 * bulk_density_kg_m3
    # Convierte masa a toneladas
    total_tons = total_mass_kg / KG_POR_TONELADA
    # Retorna diccionario con resultados
    return {
        'volume_m3': round(volume_m3, 4),
        'bulk_density_kg_m3': bulk_density_kg_m3,
        'total_mass_kg': round(total_mass_kg, 2),
        'total_tons': round(total_tons, 3)
    }

# Calcula la densidad aparente a partir del llenado de un recipiente de prueba
def calculate_bulk_density_from_container(container_liters, full_weight_kg, empty_weight_kg=0.0):
    # Valida que los litros del recipiente sean mayores a cero
    if container_liters <= 0:
        # Lanza excepcion si el volumen del recipiente es invalido
        raise ValueError("El volumen del recipiente debe ser mayor a 0 litros.")
    # Calcula el peso neto del material
    net_weight_kg = full_weight_kg - empty_weight_kg
    # Valida que el peso neto no sea negativo
    if net_weight_kg <= 0:
        # Lanza excepcion si el peso neto no es positivo
        raise ValueError("El peso neto del material en el recipiente debe ser mayor a 0 kg.")
    # Convierte litros a metros cubicos (L / 1000)
    container_m3 = container_liters / 1000.0
    # Calcula la densidad aparente: masa / volumen
    bulk_density = net_weight_kg / container_m3
    # Retorna la densidad aparente en kg/m3
    return round(bulk_density, 2)
