# Modulo de calculos de balance de masa, rendimientos y eficiencias industriales

# Calcula el consumo neto de semilla a partir de balances de stock y movimientos
def calculate_seed_consumed(initial_stock_kg, inflows_kg, final_stock_kg, external_outflows_kg=0.0):
    # Valida que los valores de inventario no sean negativos
    if initial_stock_kg < 0 or final_stock_kg < 0 or inflows_kg < 0:
        # Lanza excepcion si se ingresan valores negativos
        raise ValueError("Las existencias y movimientos de semilla no pueden ser negativos.")
    # Aplica la formula: S_inicial + Ingresos - S_final - Salidas ajenas
    consumed_kg = initial_stock_kg + inflows_kg - final_stock_kg - external_outflows_kg
    # Retorna el consumo neto de semilla en kg
    return round(consumed_kg, 2)

# Calcula el rendimiento masico porcentual de un producto respecto a la semilla procesada
def calculate_mass_yield_pct(product_kg, seed_processed_kg):
    # Valida que la semilla procesada sea mayor a cero para evitar division por cero
    if seed_processed_kg <= 0:
        # Retorna cero si no hubo procesamiento de semilla
        return 0.0
    # Valida que el producto obtenido no sea negativo
    if product_kg < 0:
        # Lanza excepcion si la masa de producto es negativa
        raise ValueError("La masa de producto obtenido no puede ser negativa.")
    # Aplica la formula de rendimiento masico: (M_producto / M_semilla) * 100
    yield_pct = (product_kg / seed_processed_kg) * 100.0
    # Retorna el rendimiento masico redondeado a dos decimales
    return round(yield_pct, 2)

# Calcula el aceite disponible teorico contenido en la semilla procesada
def calculate_available_oil(seed_processed_kg, seed_fat_pct):
    # Valida que la semilla no sea negativa
    if seed_processed_kg < 0:
        # Lanza excepcion por masa de semilla negativa
        raise ValueError("La semilla procesada no puede ser negativa.")
    # Valida que el porcentaje de materia grasa este entre 0 y 100
    if seed_fat_pct < 0 or seed_fat_pct > 100:
        # Lanza excepcion por porcentaje fuera de rango
        raise ValueError("El porcentaje de materia grasa de la semilla debe estar entre 0 y 100%.")
    # Calcula la masa teorica de aceite: M_semilla * (MG_semilla / 100)
    available_oil_kg = seed_processed_kg * (seed_fat_pct / 100.0)
    # Retorna el aceite disponible en kilogramos
    return round(available_oil_kg, 2)

# Calcula el porcentaje de recuperacion del aceite disponible (extraccion real vs teorica)
def calculate_oil_recovery_pct(oil_recovered_kg, seed_processed_kg, seed_fat_pct):
    # Calcula primero la cantidad teorica de aceite disponible en la semilla
    available_oil_kg = calculate_available_oil(seed_processed_kg, seed_fat_pct)
    # Si no hay aceite disponible o la semilla fue cero
    if available_oil_kg <= 0:
        # Retorna 0.0 para evitar division por cero
        return 0.0
    # Aplica la formula de recuperacion: (Aceite_obtenido / Aceite_disponible) * 100
    recovery_pct = (oil_recovered_kg / available_oil_kg) * 100.0
    # Retorna la eficiencia de recuperacion porcentual
    return round(recovery_pct, 2)

# Calcula la masa de grasa residual retenida en el subproducto expeller
def calculate_residual_fat_in_expeller(expeller_kg, expeller_fat_pct):
    # Valida que el expeller no sea negativo
    if expeller_kg < 0:
        # Lanza excepcion por masa negativa
        raise ValueError("La masa de expeller no puede ser negativa.")
    # Valida el rango de materia grasa residual del expeller
    if expeller_fat_pct < 0 or expeller_fat_pct > 100:
        # Lanza excepcion si el porcentaje esta fuera de limite
        raise ValueError("El porcentaje de materia grasa del expeller debe estar entre 0 y 100%.")
    # Aplica la formula: M_expeller * (MG_expeller / 100)
    residual_fat_kg = expeller_kg * (expeller_fat_pct / 100.0)
    # Retorna la masa de grasa no extraida en kilogramos
    return round(residual_fat_kg, 2)

# Realiza el balance de masa clasificado y conciliacion de materias
def calculate_classified_mass_balance(seed_processed_kg, oil_obtained_kg, expeller_obtained_kg,
                                     separated_impurities_kg=0.0, solid_waste_kg=0.0,
                                     spills_losses_kg=0.0, moisture_removed_kg=0.0,
                                     in_process_variation_kg=0.0):
    # Valida que la masa de semilla sea mayor o igual a cero
    if seed_processed_kg < 0:
        # Lanza excepcion si la semilla es negativa
        raise ValueError("La masa de semilla procesada no puede ser negativa.")
    # Suma todas las salidas utiles principales del proceso
    main_products_kg = oil_obtained_kg + expeller_obtained_kg
    # Suma las perdidas y salidas identificadas secundarias
    identified_exits_kg = (separated_impurities_kg + solid_waste_kg +
                           spills_losses_kg + moisture_removed_kg + in_process_variation_kg)
    # Calcula la diferencia no conciliada: Semilla - Productos - Salidas identificadas
    unreconciled_diff_kg = seed_processed_kg - main_products_kg - identified_exits_kg
    # Calcula el porcentaje de diferencia no conciliada respecto a la semilla
    unreconciled_diff_pct = 0.0
    # Si hubo procesamiento de semilla
    if seed_processed_kg > 0:
        # Calcula el ratio porcentual absoluto de conciliacion
        unreconciled_diff_pct = (abs(unreconciled_diff_kg) / seed_processed_kg) * 100.0
    # Calcula el porcentaje de perdidas materiales identificadas
    identified_losses_pct = 0.0
    # Si hubo procesamiento de semilla
    if seed_processed_kg > 0:
        # Suma de perdidas fisicas directas (impurezas + residuos + derrames)
        physical_losses_kg = separated_impurities_kg + solid_waste_kg + spills_losses_kg
        # Calcula el porcentaje de perdidas
        identified_losses_pct = (physical_losses_kg / seed_processed_kg) * 100.0
    # Retorna un diccionario con el balance completo y desglosado
    return {
        'seed_processed_kg': round(seed_processed_kg, 2),
        'oil_obtained_kg': round(oil_obtained_kg, 2),
        'expeller_obtained_kg': round(expeller_obtained_kg, 2),
        'separated_impurities_kg': round(separated_impurities_kg, 2),
        'solid_waste_kg': round(solid_waste_kg, 2),
        'spills_losses_kg': round(spills_losses_kg, 2),
        'moisture_removed_kg': round(moisture_removed_kg, 2),
        'in_process_variation_kg': round(in_process_variation_kg, 2),
        'unreconciled_diff_kg': round(unreconciled_diff_kg, 2),
        'unreconciled_diff_pct': round(unreconciled_diff_pct, 2),
        'identified_losses_pct': round(identified_losses_pct, 2)
    }

# Calcula el rendimiento de expeller y la eficiencia de extraccion cruzando caudales de linea con laboratorio
def calculate_line_yield_and_oil_efficiency(seed_speed_kg_h, expeller_speed_kg_h, seed_fat_pct=45.0, expeller_fat_pct=10.0):
    # Si no hay caudal de semilla procesada retorna ceros de referencia
    if seed_speed_kg_h <= 0:
        return {
            'expeller_yield_pct': 0.0,
            'theoretical_oil_speed_kg_h': 0.0,
            'fat_in_seed_kg_h': 0.0,
            'fat_in_expeller_kg_h': 0.0,
            'extracted_oil_fat_kg_h': 0.0,
            'oil_extraction_efficiency_pct': 0.0
        }
    
    # Rendimiento de Expeller por relacion de caudales de linea: (Promedio Expeller / Promedio Semilla) * 100
    expeller_yield_pct = round((expeller_speed_kg_h / seed_speed_kg_h) * 100.0, 2)
    
    # Caudal masico estimado de aceite bruto obtenido: Caudal Semilla - Caudal Expeller
    theoretical_oil_speed = round(max(0.0, seed_speed_kg_h - expeller_speed_kg_h), 2)
    
    # Caudal horario de materia grasa ingresada con la semilla: Caudal Semilla * (% MG Semilla / 100)
    fat_in_seed = round(seed_speed_kg_h * (seed_fat_pct / 100.0), 2)
    
    # Caudal horario de materia grasa residual retenida en expeller: Caudal Expeller * (% MG Expeller / 100)
    fat_in_expeller = round(expeller_speed_kg_h * (expeller_fat_pct / 100.0), 2)
    
    # Grasa efectivamente extraida en corriente de aceite: Grasa Semilla - Grasa Expeller
    extracted_fat = round(max(0.0, fat_in_seed - fat_in_expeller), 2)
    
    # Eficiencia de extraccion de aceite (% de la grasa disponible recuperada)
    extraction_eff_pct = round((extracted_fat / fat_in_seed) * 100.0, 2) if fat_in_seed > 0 else 0.0
    
    return {
        'expeller_yield_pct': expeller_yield_pct,
        'theoretical_oil_speed_kg_h': theoretical_oil_speed,
        'fat_in_seed_kg_h': fat_in_seed,
        'fat_in_expeller_kg_h': fat_in_expeller,
        'extracted_oil_fat_kg_h': extracted_fat,
        'oil_extraction_efficiency_pct': extraction_eff_pct
    }

