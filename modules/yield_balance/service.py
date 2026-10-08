# Importa datetime para estampa de fecha
import datetime
# Importa conexion a base de datos
from core.database import get_db_connection
# Importa funciones de calculo de rendimiento
from modules.calculations.yield_calc import (
    calculate_mass_yield_pct, calculate_available_oil, calculate_oil_recovery_pct,
    calculate_residual_fat_in_expeller, calculate_classified_mass_balance
)
# Importa logger de eventos
from core.error_logger import log_info, log_error
# Importa funciones horarias oficiales de planta (Argentina UTC-3)
from core.timezone import get_plant_now_str, get_plant_today_str

# Realiza la conciliacion de turno y guarda el balance de masa en base de datos
def reconcile_shift(shift_id, seed_processed_kg, expeller_produced_kg, oil_produced_kg,
                    seed_fat_pct=45.0, expeller_fat_pct=10.0, identified_waste_kg=0.0,
                    moisture_loss_kg=0.0, notes=''):
    # Calcula el rendimiento masico de aceite (% de la semilla)
    oil_yield_pct = calculate_mass_yield_pct(oil_produced_kg, seed_processed_kg)
    # Calcula el rendimiento masico de expeller (% de la semilla)
    expeller_yield_pct = calculate_mass_yield_pct(expeller_produced_kg, seed_processed_kg)
    # Calcula la eficiencia de recuperacion del aceite disponible contenido en la semilla
    oil_recovery_pct = calculate_oil_recovery_pct(oil_produced_kg, seed_processed_kg, seed_fat_pct)
    # Calcula la masa de grasa residual no extraida en el expeller
    residual_fat_kg = calculate_residual_fat_in_expeller(expeller_produced_kg, expeller_fat_pct)
    # Realiza el balance de masa clasificado
    balance = calculate_classified_mass_balance(
        seed_processed_kg=seed_processed_kg,
        oil_obtained_kg=oil_produced_kg,
        expeller_obtained_kg=expeller_produced_kg,
        solid_waste_kg=identified_waste_kg,
        moisture_removed_kg=moisture_loss_kg
    )
    # Identificador de turno con fecha oficial de planta (ej. 2026-09-26-TM)
    today_str = get_plant_today_str()
    date_shift = f"{today_str}-{shift_id}"
    now_str = get_plant_now_str()
    # Abre conexion para guardar la conciliacion
    with get_db_connection() as conn:
        cursor = conn.execute("""
            INSERT INTO shift_reconciliations (
                date_shift, shift_id, seed_processed_kg, expeller_produced_kg,
                oil_produced_kg, seed_fat_pct, expeller_fat_pct, identified_waste_kg,
                moisture_loss_kg, mass_difference_kg, mass_diff_pct, oil_yield_pct,
                expeller_yield_pct, oil_recovery_pct, residual_fat_kg, notes, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """, (date_shift, shift_id, seed_processed_kg, expeller_produced_kg,
              oil_produced_kg, seed_fat_pct, expeller_fat_pct, identified_waste_kg,
              moisture_loss_kg, balance['unreconciled_diff_kg'], balance['unreconciled_diff_pct'],
              oil_yield_pct, expeller_yield_pct, oil_recovery_pct, residual_fat_kg, notes, now_str))
        conn.commit()
        rec_id = cursor.lastrowid
    # Registra en log la conciliacion
    log_info('YIELD', f'Conciliacion de {date_shift} guardada: Rend Aceite {oil_yield_pct}%, Recup {oil_recovery_pct}%.')
    # Retorna el informe de rendimiento
    return {
        'id': rec_id,
        'date_shift': date_shift,
        'oil_yield_pct': oil_yield_pct,
        'expeller_yield_pct': expeller_yield_pct,
        'oil_recovery_pct': oil_recovery_pct,
        'residual_fat_kg': residual_fat_kg,
        'mass_diff_kg': balance['unreconciled_diff_kg'],
        'mass_diff_pct': balance['unreconciled_diff_pct'],
        'notes': notes
    }

# Obtiene las conciliaciones de turno recientes
def get_recent_reconciliations(limit=20):
    # Abre conexion a base de datos
    with get_db_connection() as conn:
        rows = conn.execute("""
            SELECT * FROM shift_reconciliations
            ORDER BY created_at DESC
            LIMIT ?;
        """, (limit,)).fetchall()
        # Retorna lista de diccionarios
        return [dict(row) for row in rows]

# Obtiene la ultima conciliacion registrada para el dashboard
def get_latest_reconciliation():
    # Abre conexion a base de datos
    with get_db_connection() as conn:
        row = conn.execute("""
            SELECT * FROM shift_reconciliations
            ORDER BY created_at DESC
            LIMIT 1;
        """).fetchone()
        # Retorna diccionario o None si no hay registros
        return dict(row) if row else None

# Calcula el informe de eficiencia y rendimientos a partir de un juego de datos personalizado o manual
def calculate_custom_efficiency(seed_processed_kg, expeller_produced_kg, oil_produced_kg=None,
                                seed_fat_pct=45.0, expeller_fat_pct=10.0,
                                waste_kg=0.0, moisture_loss_kg=0.0):
    # Asegura conversion numerica flotante de los datos ingresados de semilla
    s_kg = max(0.0, float(seed_processed_kg or 0.0))
    # Asegura valor numerico positivo para expeller
    e_kg = max(0.0, float(expeller_produced_kg or 0.0))
    # Asegura porcentaje valido de materia grasa en semilla
    s_fat = max(0.0, min(100.0, float(seed_fat_pct if seed_fat_pct is not None else 45.0)))
    # Asegura porcentaje valido de materia grasa en expeller
    e_fat = max(0.0, min(100.0, float(expeller_fat_pct if expeller_fat_pct is not None else 10.0)))
    # Desechos y mermas identificadas
    w_kg = max(0.0, float(waste_kg or 0.0))
    # Humedad y agua evaporada
    m_kg = max(0.0, float(moisture_loss_kg or 0.0))

    # Si no se indico el aceite producido, se calcula por balance masico (semilla - expeller - mermas)
    if oil_produced_kg is None or str(oil_produced_kg).strip() == '':
        # Formula diferencial de masa de aceite obtenido
        o_kg = max(0.0, s_kg - e_kg - w_kg - m_kg)
    else:
        # Utiliza el aceite explicitamente ingresado por el usuario
        o_kg = max(0.0, float(oil_produced_kg))

    # Calcula el rendimiento masico de aceite (% de la semilla procesada)
    oil_yield_pct = calculate_mass_yield_pct(o_kg, s_kg)
    # Calcula el rendimiento masico de expeller (% de la semilla procesada)
    expeller_yield_pct = calculate_mass_yield_pct(e_kg, s_kg)
    # Calcula el aceite disponible teorico contenido en la semilla
    available_oil_kg = calculate_available_oil(s_kg, s_fat)
    # Calcula la eficiencia de recuperacion del aceite disponible
    oil_recovery_pct = calculate_oil_recovery_pct(o_kg, s_kg, s_fat)
    # Calcula los kilos de grasa que permanecen retenidos en el expeller
    residual_fat_kg = calculate_residual_fat_in_expeller(e_kg, e_fat)
    # Realiza el balance de masa clasificado
    balance = calculate_classified_mass_balance(
        seed_processed_kg=s_kg,
        oil_obtained_kg=o_kg,
        expeller_obtained_kg=e_kg,
        solid_waste_kg=w_kg,
        moisture_removed_kg=m_kg
    )

    # Determina la etiqueta de evaluacion del rendimiento industrial
    if oil_recovery_pct >= 85.0:
        # Estado optimo de recuperacion
        status = 'Óptimo'
        # Color verde esmeralda
        status_color = '#15803d'
    elif oil_recovery_pct >= 75.0:
        # Estado normal o aceptable
        status = 'Normal'
        # Color azul corporativo
        status_color = '#1d4ed8'
    else:
        # Estado por debajo de los estandares de extraccion
        status = 'Ajustar Prensas'
        # Color ambar de advertencia
        status_color = '#b45309'

    # Construye el resultado estructurado
    res = {
        'is_automatic': False,
        'source': 'juego_de_datos_manual',
        'seed_processed_kg': round(s_kg, 1),
        'expeller_produced_kg': round(e_kg, 1),
        'oil_produced_kg': round(o_kg, 1),
        'seed_fat_pct': round(s_fat, 1),
        'expeller_fat_pct': round(e_fat, 1),
        'waste_kg': round(w_kg, 1),
        'moisture_loss_kg': round(m_kg, 1),
        'available_oil_kg': round(available_oil_kg, 1),
        'available_fat_kg': round(available_oil_kg, 1),
        'oil_yield_pct': oil_yield_pct,
        'expeller_yield_pct': expeller_yield_pct,
        'oil_recovery_pct': oil_recovery_pct,
        'residual_fat_kg': residual_fat_kg,
        'total_output_kg': round(o_kg + e_kg + w_kg + m_kg, 1),
        'mass_diff_kg': balance['unreconciled_diff_kg'],
        'mass_difference_kg': balance['unreconciled_diff_kg'],
        'mass_diff_pct': balance['unreconciled_diff_pct'],
        'status': status,
        'status_color': status_color
    }
    # Agrega copia accesible como calculated_kpis para compatibilidad con plantillas
    res['calculated_kpis'] = dict(res)
    # Retorna el paquete completo con el resultado de la evaluacion
    return res

# Genera el dato de eficiencia y rendimiento en forma automatica a partir de la informacion registrada en el sistema
def get_auto_efficiency_data(shift_id=None, target_date=None):
    # Importa el servicio de configuracion para obtener el turno activo si no se especifico
    from modules.configuration.service import get_active_shift
    # Importa el servicio de produccion para obtener velocidades y pesadas de guardia
    from modules.production.service import get_shift_speed_summary, get_recent_weighings
    # Importa el servicio de laboratorio para obtener porcentajes de grasa registrados
    from modules.laboratory.service import get_shift_lab_averages
    # Importa funciones de calculo horario de linea
    from modules.calculations.yield_calc import calculate_line_yield_and_oil_efficiency

    # Sanitiza o establece la fecha operativa objetivo
    clean_date = str(target_date).strip() if target_date and str(target_date).strip() else get_plant_today_str()

    # Si no se paso identificador de turno, consulta el turno actualmente en curso
    if not shift_id:
        # Obtiene la guardia activa
        active_shift = get_active_shift()
        # Asigna el id del turno activo
        target_shift_id = active_shift['shift_id']
        # Asigna el nombre del turno activo
        shift_name = active_shift['shift_name']
    else:
        # Usa el id de turno solicitado
        target_shift_id = shift_id
        # Nombre de referencia
        shift_name = f"Turno {shift_id}"

    # Identificador textual de fecha y turno
    date_shift = f"{clean_date}-{target_shift_id}"

    # Obtiene el resumen de velocidad y produccion estimada del turno segun pesadas para la fecha
    prod_summary = get_shift_speed_summary(target_shift_id, target_date=clean_date)
    # Obtiene las medias de laboratorio registradas en planta para materia grasa para la fecha
    lab_averages = get_shift_lab_averages(target_shift_id, target_date=clean_date)

    # Cantidad de pesadas registradas en el turno
    seed_count = prod_summary.get('seed_sample_count', 0)
    expeller_count = prod_summary.get('expeller_sample_count', 0)
    has_records = (seed_count > 0 or expeller_count > 0)

    # Horas efectivas de marcha registradas
    effective_hours = prod_summary.get('effective_hours', 8.0)
    # Velocidad promedio de semilla registrada
    seed_avg_speed = prod_summary.get('seed_avg_speed', 0.0)
    # Velocidad promedio de expeller registrada
    expeller_avg_speed = prod_summary.get('expeller_avg_speed', 0.0)

    # Si hay pesadas registradas en el turno
    if has_records and seed_avg_speed > 0:
        # Semilla procesada estimada segun velocidad y horas efectivas
        seed_kg = prod_summary.get('seed_estimated', 0.0)
        # Expeller obtenido estimado segun velocidad y horas efectivas
        expeller_kg = prod_summary.get('expeller_estimated', 0.0)
        # Aceite estimado segun diferencial de velocidad y horas de marcha
        oil_kg = prod_summary.get('oil_estimated_shift_kg', 0.0)
        # Si el calculo dio cero pero hay semilla, calcula aceite por balance masico
        if oil_kg <= 0 and seed_kg > 0:
            oil_kg = max(0.0, seed_kg - expeller_kg)
    else:
        # Si el turno actual aun no tiene pesadas registradas, busca pesadas recientes globales de planta
        recent_w = get_recent_weighings(limit=10)
        # Filtra pesadas de semilla recientes
        recent_seed = [w['speed_kg_h'] for w in recent_w if w['sample_point'] == 'ingreso_semilla' and w['line_status'] == 'operando']
        # Filtra pesadas de expeller recientes
        recent_exp = [w['speed_kg_h'] for w in recent_w if w['sample_point'] == 'salida_expeller' and w['line_status'] == 'operando']
        # Si hay pesadas historicas en planta
        if recent_seed and recent_exp:
            # Velocidad de semilla promedio reciente
            seed_avg_speed = sum(recent_seed) / len(recent_seed)
            # Velocidad de expeller promedio reciente
            expeller_avg_speed = sum(recent_exp) / len(recent_exp)
            # Semilla proyectada para las horas de marcha
            seed_kg = round(seed_avg_speed * effective_hours, 1)
            # Expeller proyectado para las horas de marcha
            expeller_kg = round(expeller_avg_speed * effective_hours, 1)
            # Aceite proyectado
            oil_kg = max(0.0, seed_kg - expeller_kg)
            # Marca que tiene registros historicos aunque no del turno
            has_records = True
        else:
            # Si no hay ninguna pesada en la base de datos, aplica estandares nominales de planta
            seed_avg_speed = 1800.0
            expeller_avg_speed = 1150.0
            seed_kg = round(seed_avg_speed * effective_hours, 1)
            expeller_kg = round(expeller_avg_speed * effective_hours, 1)
            oil_kg = max(0.0, seed_kg - expeller_kg)
            has_records = False

    # Porcentaje de materia grasa en semilla obtenido de laboratorio
    seed_fat_pct = lab_averages.get('seed_fat_pct', 45.0)
    # Porcentaje de materia grasa en expeller obtenido de laboratorio
    expeller_fat_pct = lab_averages.get('expeller_fat_pct', 10.0)

    # Calcula la eficiencia y rendimientos a partir de los datos automaticos consolidados
    eff_result = calculate_custom_efficiency(
        seed_processed_kg=seed_kg,
        expeller_produced_kg=expeller_kg,
        oil_produced_kg=oil_kg,
        seed_fat_pct=seed_fat_pct,
        expeller_fat_pct=expeller_fat_pct
    )

    # Calcula el rendimiento de linea y cruce analitico continuo
    line_yield_info = calculate_line_yield_and_oil_efficiency(
        seed_speed_kg_h=seed_avg_speed,
        expeller_speed_kg_h=expeller_avg_speed,
        seed_fat_pct=seed_fat_pct,
        expeller_fat_pct=expeller_fat_pct
    )

    # Determina si el calculo proviene de registros reales o es una proyeccion nominal fallback
    if has_records and (seed_count > 0 or expeller_count > 0):
        # Descripcion del sustento registrado con pesadas del turno
        basis_description = f"Basado en {seed_count} pesadas de semilla y {expeller_count} de expeller ({effective_hours}h de marcha)"
        # Bandera de fallback desactivada
        is_fallback = False
    elif has_records:
        # Descripcion con pesadas globales recientes
        basis_description = f"Basado en pesadas recientes de planta y {effective_hours}h efectivas de marcha"
        # Bandera de fallback desactivada
        is_fallback = False
    else:
        # Descripcion cuando se usan parametros nominales
        basis_description = f"Estimación basada en parámetros nominales de planta ({seed_avg_speed:,.0f} kg/h semilla)"
        # Bandera de fallback activada
        is_fallback = True

    # Actualiza metadata de origen automatico
    eff_result.update({
        'is_automatic': True,
        'source': 'informacion_registrada_sistema',
        'is_fallback': is_fallback,
        'basis_description': basis_description,
        'has_records': has_records,
        'shift_id': target_shift_id,
        'shift_name': shift_name,
        'date_shift': date_shift,
        'seed_avg_speed': round(seed_avg_speed, 1),
        'expeller_avg_speed': round(expeller_avg_speed, 1),
        'effective_hours': round(effective_hours, 1),
        'seed_sample_count': seed_count,
        'expeller_sample_count': expeller_count,
        'line_extraction_eff_pct': line_yield_info.get('oil_extraction_efficiency_pct', 0.0),
        'badge_text': '⚡ Automático (Registros)' if not is_fallback else '⚡ Automático (Nominal)',
        'badge_color': '#166534' if not is_fallback else '#b45309',
        'badge_bg': '#dcfce7' if not is_fallback else '#fef3c7',
    })
    # Sincroniza calculated_kpis con todos los campos del resultado
    eff_result['calculated_kpis'] = dict(eff_result)

    # Retorna la estructura completa de eficiencia automatica
    return eff_result

# Guarda en el historial de conciliaciones el balance masico y eficiencia generados automaticamente
def save_auto_reconciliation(shift_id=None, notes=''):
    # Genera los datos automaticos a partir de los registros del turno
    auto_data = get_auto_efficiency_data(shift_id)
    # Mensaje o nota explicativa
    final_notes = notes.strip() if notes else f"Balance automático generado a partir de {auto_data.get('seed_sample_count', 0)} pesadas de semilla y {auto_data.get('expeller_sample_count', 0)} de expeller."
    # Guarda la conciliacion mediante el metodo oficial
    result = reconcile_shift(
        shift_id=auto_data['shift_id'],
        seed_processed_kg=auto_data['seed_processed_kg'],
        expeller_produced_kg=auto_data['expeller_produced_kg'],
        oil_produced_kg=auto_data['oil_produced_kg'],
        seed_fat_pct=auto_data['seed_fat_pct'],
        expeller_fat_pct=auto_data['expeller_fat_pct'],
        identified_waste_kg=0.0,
        moisture_loss_kg=0.0,
        notes=final_notes
    )
    # Retorna el resultado guardado
    return result
