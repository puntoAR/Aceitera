# Modulo de calculos analiticos de laboratorio para control de calidad

# Calcula el porcentaje de humedad por perdida de masa en secado
def calculate_moisture_pct(initial_sample_mass_g, dry_sample_mass_g):
    # Valida que la masa inicial de la muestra sea estrictamente positiva
    if initial_sample_mass_g <= 0:
        # Lanza excepcion si la masa inicial no es valida
        raise ValueError("La masa inicial de la muestra debe ser mayor a 0 gramos.")
    # Valida que la masa seca no sea negativa
    if dry_sample_mass_g < 0:
        # Lanza excepcion si la masa seca es menor a cero
        raise ValueError("La masa seca de la muestra no puede ser negativa.")
    # Valida que la masa seca no sea mayor a la masa inicial
    if dry_sample_mass_g > initial_sample_mass_g:
        # Lanza excepcion por inconsistencia fisica (aumento de masa durante secado)
        raise ValueError("La masa seca no puede ser mayor que la masa inicial de la muestra.")
    # Calcula la masa de agua evaporada: M_inicial - M_seca
    water_lost_g = initial_sample_mass_g - dry_sample_mass_g
    # Aplica la formula de porcentaje: (Agua / Masa_inicial) * 100
    moisture_pct = (water_lost_g / initial_sample_sample_mass_g if False else (water_lost_g / initial_sample_mass_g) * 100.0)
    # Retorna el porcentaje de humedad redondeado a dos decimales
    return round(moisture_pct, 2)

# Calcula la humedad considerando la tara del recipiente de pesada
def calculate_moisture_with_tare(tare_mass_g, initial_total_mass_g, dry_total_mass_g):
    # Calcula la masa neta inicial de la muestra
    initial_sample = initial_total_mass_g - tare_mass_g
    # Calcula la masa neta seca de la muestra
    dry_sample = dry_total_mass_g - tare_mass_g
    # Llama a la funcion principal de calculo de humedad
    return calculate_moisture_pct(initial_sample, dry_sample)

# Calcula el porcentaje de materia grasa por extraccion gravimetrica
def calculate_fat_pct(sample_mass_g, final_flask_mass_g, tare_flask_mass_g):
    # Valida que la masa de muestra analizada sea positiva
    if sample_mass_g <= 0:
        # Lanza excepcion si la masa de la muestra no es positiva
        raise ValueError("La masa de muestra para materia grasa debe ser mayor a 0 gramos.")
    # Calcula la masa neta de grasa extraida por diferencia de matraces
    fat_extracted_g = final_flask_mass_g - tare_flask_mass_g
    # Valida que la grasa extraida no sea negativa
    if fat_extracted_g < 0:
        # Lanza excepcion si el peso final del matraz es menor que la tara
        raise ValueError("La masa final del balon o matraz no puede ser menor que su tara.")
    # Aplica la formula gravimetrica: ((M_final - M_tara) * 100) / M_muestra
    fat_pct = (fat_extracted_g * 100.0) / sample_mass_g
    # Retorna el porcentaje de materia grasa redondeado a dos decimales
    return round(fat_pct, 2)

# Calcula el porcentaje de materia extrana o impurezas en la muestra
def calculate_foreign_matter_pct(initial_sample_mass_g, foreign_matter_mass_g):
    # Valida que la masa de muestra sea positiva
    if initial_sample_mass_g <= 0:
        # Lanza excepcion si la masa es menor o igual a cero
        raise ValueError("La masa inicial de muestra para materia extrana debe ser mayor a 0 gramos.")
    # Valida que la masa de impurezas no sea negativa
    if foreign_matter_mass_g < 0:
        # Lanza excepcion si las impurezas son negativas
        raise ValueError("La masa de materia extrana no puede ser negativa.")
    # Valida que las impurezas no superen a la muestra total
    if foreign_matter_mass_g > initial_sample_mass_g:
        # Lanza excepcion si las impurezas superan la muestra
        raise ValueError("La masa de materia extrana no puede ser mayor que la masa de la muestra.")
    # Aplica la formula: (M_materia_extrana / M_muestra) * 100
    foreign_matter_pct = (foreign_matter_mass_g / initial_sample_mass_g) * 100.0
    # Retorna el porcentaje de materia extrana redondeado a dos decimales
    return round(foreign_matter_pct, 2)

# Calcula el porcentaje de acidez libre en aceite vegetal crudo (como acido oleico)
def calculate_oil_acidity_pct(sample_mass_g, naoh_volume_ml, naoh_normality=0.0997, ft_factor=0.282):
    # Valida que la masa de aceite analizado sea positiva
    if sample_mass_g <= 0:
        # Lanza excepcion si la masa de muestra es invalida
        raise ValueError("La masa de muestra de aceite debe ser mayor a 0 gramos.")
    # Valida que el volumen de hidroxido de sodio no sea negativo
    if naoh_volume_ml < 0:
        # Lanza excepcion si el volumen gastado de NaOH es negativo
        raise ValueError("El volumen gastado de NaOH no puede ser negativo.")
    # Valida que la concentracion de reactivo sea positiva
    if naoh_normality <= 0 or ft_factor <= 0:
        # Lanza excepcion por parametros de titulacion no validos
        raise ValueError("La normalidad del titulante y el factor estequiometrico deben ser positivos.")
    # Aplica la formula analitica: (V * N * Ft * 100) / Muestra
    acidity_pct = (naoh_volume_ml * naoh_normality * ft_factor * 100.0) / sample_mass_g
    # Retorna el porcentaje de acidez redondeado a dos decimales
    return round(acidity_pct, 2)
