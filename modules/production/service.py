# Importa datetime para marcas de tiempo operativas
import datetime
# Importa json para crear snapshots de parametros
import json
# Importa la conexion a base de datos
from core.database import get_db_connection
# Importa las funciones del motor de velocidad desacoplado
from modules.calculations.speed_calc import (
    calculate_net_weight, calculate_instant_speed,
    project_shift_production, project_daily_production,
    calculate_arithmetic_average_speed, calculate_aggregated_speed,
    calculate_estimated_production
)
# Importa el registrador de eventos
from core.error_logger import log_info, log_error
# Importa la funcion horaria oficial de planta BioBalcarce (Argentina UTC-3)
from core.timezone import get_plant_now_str

# Registra un muestreo de pesada de bolsa con calculo automatico de velocidad y proyeccion
def record_weighing(shift_id, operator_name, sample_point, gross_weight_kg,
                    tare_weight_kg, fill_time_seconds, line_status='operando', notes=''):
    # Calcula el peso neto descontando la tara
    net_weight_kg = calculate_net_weight(gross_weight_kg, tare_weight_kg)
    # Inicializa las variables de velocidad y proyeccion
    speed_kg_h = 0.0
    proj_8h_kg = 0.0
    proj_24h_kg = 0.0
    # Si la linea esta operando y el tiempo es valido
    if line_status == 'operando' and fill_time_seconds > 0:
        # Calcula la velocidad instantanea en kg/h
        speed_kg_h = calculate_instant_speed(net_weight_kg, fill_time_seconds)
        # Calcula la proyeccion para 8 horas
        proj_8h_kg = project_shift_production(speed_kg_h)
        # Calcula la proyeccion para 24 horas
        proj_24h_kg = project_daily_production(speed_kg_h)
    # Genera el snapshot de parametros aplicados para trazabilidad historica
    params_snapshot = json.dumps({
        'gross_weight_kg': gross_weight_kg,
        'tare_weight_kg': tare_weight_kg,
        'net_weight_kg': net_weight_kg,
        'fill_time_seconds': fill_time_seconds,
        'formula_speed': '(net_weight / fill_time) * 3600',
        'formula_proj_8h': 'speed * 8',
        'formula_proj_24h': 'speed * 24'
    })
    # Obtiene la fecha y hora oficial de planta (Argentina UTC-3)
    now_str = get_plant_now_str()
    # Abre conexion para insertar el registro en base de datos
    with get_db_connection() as conn:
        # Inserta la pesada en la tabla de produccion
        cursor = conn.execute("""
            INSERT INTO production_weighings (
                timestamp, shift_id, operator_name, sample_point,
                gross_weight_kg, tare_weight_kg, net_weight_kg, fill_time_seconds,
                line_status, speed_kg_h, proj_8h_kg, proj_24h_kg, notes, params_snapshot
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """, (now_str, shift_id, operator_name, sample_point,
              gross_weight_kg, tare_weight_kg, net_weight_kg, fill_time_seconds,
              line_status, speed_kg_h, proj_8h_kg, proj_24h_kg, notes, params_snapshot))
        # Confirma la transaccion
        conn.commit()
        # Obtiene el ID asignado a la nueva pesada
        weighing_id = cursor.lastrowid
    # Registra en log el muestreo de produccion
    log_info('PRODUCTION', f'Pesada ID {weighing_id} registrada: {sample_point} a {speed_kg_h} kg/h en turno {shift_id}.')
    # Retorna el diccionario con la pesada registrada
    return {
        'id': weighing_id,
        'timestamp': now_str,
        'shift_id': shift_id,
        'sample_point': sample_point,
        'net_weight_kg': net_weight_kg,
        'speed_kg_h': speed_kg_h,
        'proj_8h_kg': proj_8h_kg,
        'proj_24h_kg': proj_24h_kg
    }

# Obtiene las ultimas pesadas registradas para un turno o fecha
def get_recent_weighings(shift_id=None, limit=50):
    # Abre conexion a base de datos
    with get_db_connection() as conn:
        # Si se especifico un turno en particular
        if shift_id:
            # Consulta pesadas filtrando por turno ordenadas cronologicamente descendente
            rows = conn.execute("""
                SELECT * FROM production_weighings
                WHERE shift_id = ?
                ORDER BY timestamp DESC
                LIMIT ?;
            """, (shift_id, limit)).fetchall()
        else:
            # Consulta las ultimas pesadas globales de la planta
            rows = conn.execute("""
                SELECT * FROM production_weighings
                ORDER BY timestamp DESC
                LIMIT ?;
            """, (limit,)).fetchall()
        # Retorna lista de diccionarios
        return [dict(row) for row in rows]

# Registra una parada o detencion en la linea de proceso
def record_line_stop(shift_id, duration_minutes, reason, operator_name):
    # Obtiene la fecha y hora oficial de planta (Argentina UTC-3)
    now_str = get_plant_now_str()
    # Abre conexion para registrar la parada
    with get_db_connection() as conn:
        # Inserta la detencion en la tabla line_stops
        conn.execute("""
            INSERT INTO line_stops (shift_id, start_time, duration_minutes, reason, operator_name)
            VALUES (?, ?, ?, ?, ?);
        """, (shift_id, now_str, duration_minutes, reason, operator_name))
        # Confirma la transaccion
        conn.commit()
    # Registra el evento en log
    log_info('PRODUCTION', f'Parada de linea registrada en turno {shift_id}: {duration_minutes} min ({reason}).')

# Obtiene las paradas registradas para un turno
def get_shift_stops(shift_id):
    # Abre conexion a base de datos
    with get_db_connection() as conn:
        # Consulta las paradas del turno especificado
        rows = conn.execute("""
            SELECT * FROM line_stops
            WHERE shift_id = ?
            ORDER BY start_time DESC;
        """, (shift_id,)).fetchall()
        # Retorna lista de diccionarios
        return [dict(row) for row in rows]

# Calcula las metricas consolidadas de velocidad para un turno (semilla y expeller)
def get_shift_speed_summary(shift_id):
    # Abre conexion a base de datos
    with get_db_connection() as conn:
        # Obtiene las pesadas del turno
        rows = conn.execute("""
            SELECT sample_point, net_weight_kg, fill_time_seconds, speed_kg_h
            FROM production_weighings
            WHERE shift_id = ? AND line_status = 'operando';
        """, (shift_id,)).fetchall()
        # Obtiene los minutos totales de parada del turno
        stop_row = conn.execute("""
            SELECT COALESCE(SUM(duration_minutes), 0.0) as total_stop_min
            FROM line_stops
            WHERE shift_id = ?;
        """, (shift_id,)).fetchone()
    # Minutos totales detenidos
    total_stop_minutes = stop_row['total_stop_min'] if stop_row else 0.0
    # Horas detenidas
    stop_hours = total_stop_minutes / 60.0
    # Horas efectivas de marcha en turno de 8 horas
    effective_hours = max(0.0, 8.0 - stop_hours)
    # Separa muestras de semilla y expeller
    seed_samples = [dict(r) for r in rows if r['sample_point'] == 'ingreso_semilla']
    expeller_samples = [dict(r) for r in rows if r['sample_point'] == 'salida_expeller']
    # Lista de velocidades de semilla
    seed_speeds = [s['speed_kg_h'] for s in seed_samples]
    # Lista de velocidades de expeller
    expeller_speeds = [s['speed_kg_h'] for s in expeller_samples]
    # Promedio aritmetico de semilla
    seed_avg_arithmetic = calculate_arithmetic_average_speed(seed_speeds)
    # Velocidad agregada de semilla
    seed_agg_speed = calculate_aggregated_speed(seed_samples)
    # Promedio aritmetico de expeller
    expeller_avg_arithmetic = calculate_arithmetic_average_speed(expeller_speeds)
    # Velocidad agregada de expeller
    expeller_agg_speed = calculate_aggregated_speed(expeller_samples)
    # Produccion proyectada de 8h para semilla segun promedio
    seed_proj_8h = project_shift_production(seed_avg_arithmetic)
    # Produccion proyectada de 24h para semilla segun ritmo diario
    seed_proj_24h = project_daily_production(seed_avg_arithmetic)
    # Produccion estimada real de semilla considerando horas efectivas
    seed_estimated = calculate_estimated_production(seed_avg_arithmetic, effective_hours)
    # Produccion proyectada de 8h para expeller
    expeller_proj_8h = project_shift_production(expeller_avg_arithmetic)
    # Produccion proyectada de 24h para expeller segun ritmo diario
    expeller_proj_24h = project_daily_production(expeller_avg_arithmetic)
    # Produccion estimada real de expeller considerando paradas
    expeller_estimated = calculate_estimated_production(expeller_avg_arithmetic, effective_hours)
    # Rendimiento de Expeller por relacion porcentual de caudales horarios: (Promedio Expeller / Promedio Semilla) * 100
    expeller_yield_pct = round((expeller_avg_arithmetic / seed_avg_arithmetic * 100.0), 2) if seed_avg_arithmetic > 0 else 0.0
    # Caudal masico horario estimado de aceite bruto: Promedio Semilla - Promedio Expeller
    oil_estimated_speed = round(max(0.0, seed_avg_arithmetic - expeller_avg_arithmetic), 2) if seed_avg_arithmetic > 0 else 0.0
    # Produccion estimada de aceite en el turno considerando horas efectivas
    oil_estimated_shift_kg = round(oil_estimated_speed * effective_hours, 2)
    # Retorna el resumen consolidado de velocidad del turno
    return {
        'shift_id': shift_id,
        'effective_hours': round(effective_hours, 2),
        'stop_minutes': round(total_stop_minutes, 1),
        'seed_sample_count': len(seed_samples),
        'seed_avg_speed': seed_avg_arithmetic,
        'seed_agg_speed': seed_agg_speed,
        'seed_proj_8h': seed_proj_8h,
        'seed_proj_24h': seed_proj_24h,
        'seed_estimated': seed_estimated,
        'expeller_sample_count': len(expeller_samples),
        'expeller_avg_speed': expeller_avg_arithmetic,
        'expeller_agg_speed': expeller_agg_speed,
        'expeller_proj_8h': expeller_proj_8h,
        'expeller_proj_24h': expeller_proj_24h,
        'expeller_estimated': expeller_estimated,
        'expeller_yield_pct': expeller_yield_pct,
        'oil_estimated_speed': oil_estimated_speed,
        'oil_estimated_shift_kg': oil_estimated_shift_kg
    }
