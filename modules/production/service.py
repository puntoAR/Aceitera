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
from core.timezone import get_plant_now_str, determine_time_slot, get_plant_now, get_plant_today_str
# Importa el servicio de auditoria de eventos
from core.audit import record_audit_event

# Registra un muestreo de pesada de bolsa con calculo automatico de velocidad y fecha/turno de muestra
def record_weighing(shift_id, operator_name, sample_point, gross_weight_kg,
                    tare_weight_kg, fill_time_seconds, line_status='operando', notes='',
                    sample_date=None):
    # Calcula el peso neto descontando la tara
    net_weight_kg = calculate_net_weight(gross_weight_kg, tare_weight_kg)
    # Inicializa las variables de velocidad y proyeccion
    speed_kg_h = 0.0
    # Proyeccion a 8 horas
    proj_8h_kg = 0.0
    # Proyeccion a 24 horas
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
    # Obtiene la fecha y hora oficial de planta al momento de la carga (Argentina UTC-3)
    now_str = get_plant_now_str()
    # Determina la franja horaria segun el momento de carga
    slot_info = determine_time_slot(now_str)

    # Determina la fecha de la muestra (si no se envia toma la fecha actual de planta)
    clean_sample_date = str(sample_date).strip() if sample_date and str(sample_date).strip() else get_plant_today_str()

    # Normaliza el turno correspondiente a la muestra
    clean_shift = str(shift_id).strip().upper() if shift_id and str(shift_id).strip() and str(shift_id).strip().lower() != 'auto' else None
    # Si no se envio turno especifico
    if not clean_shift:
        # Asigna el turno de la franja horaria
        clean_shift = slot_info['shift_id']

    # Asigna la franja horaria correspondiente al turno de la muestra
    if clean_shift == 'TM':
        # Turno Manana
        time_slot = '06:00 - 14:00'
    elif clean_shift == 'TT':
        # Turno Tarde
        time_slot = '14:00 - 22:00'
    elif clean_shift == 'TN':
        # Turno Noche
        time_slot = '22:00 - 06:00'
    else:
        # Franja horaria por defecto
        time_slot = slot_info['time_slot']

    # Abre conexion para insertar el registro en base de datos
    with get_db_connection() as conn:
        # Inserta la pesada en la tabla de produccion incluyendo la fecha y turno de muestra
        cursor = conn.execute("""
            INSERT INTO production_weighings (
                timestamp, shift_id, operator_name, sample_point,
                gross_weight_kg, tare_weight_kg, net_weight_kg, fill_time_seconds,
                line_status, speed_kg_h, proj_8h_kg, proj_24h_kg, notes, params_snapshot, time_slot, sample_date
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """, (now_str, clean_shift, operator_name, sample_point,
              gross_weight_kg, tare_weight_kg, net_weight_kg, fill_time_seconds,
              line_status, speed_kg_h, proj_8h_kg, proj_24h_kg, notes, params_snapshot, time_slot, clean_sample_date))
        # Confirma la transaccion
        conn.commit()
        # Obtiene el ID asignado a la nueva pesada
        weighing_id = cursor.lastrowid
    # Registra en log el muestreo de produccion
    log_info('PRODUCTION', f'Pesada ID {weighing_id} registrada: {sample_point} a {speed_kg_h} kg/h del {clean_sample_date} en turno {clean_shift} (Franja: {time_slot}).')
    # Retorna el diccionario con la pesada registrada
    return {
        'id': weighing_id,
        'timestamp': now_str,
        'sample_date': clean_sample_date,
        'shift_id': clean_shift,
        'time_slot': time_slot,
        'sample_point': sample_point,
        'net_weight_kg': net_weight_kg,
        'speed_kg_h': speed_kg_h,
        'proj_8h_kg': proj_8h_kg,
        'proj_24h_kg': proj_24h_kg
    }

# Actualiza y ajusta una pesada historica con registro detallado en bitacora de auditoria
def update_weighing(weighing_id, sample_point, gross_weight_kg, tare_weight_kg,
                    fill_time_seconds, line_status='operando', notes='',
                    edit_reason='', operator_name=None, sample_date=None, shift_id=None):
    # Convierte peso bruto
    gross_weight_kg = float(gross_weight_kg)
    # Convierte tara
    tare_weight_kg = float(tare_weight_kg)
    # Convierte tiempo
    fill_time_seconds = float(fill_time_seconds)
    # Calcula peso neto efectivo
    net_weight_kg = calculate_net_weight(gross_weight_kg, tare_weight_kg)

    # Inicializa velocidad calculada
    speed_kg_h = 0.0
    # Proyeccion 8h
    proj_8h_kg = 0.0
    # Proyeccion 24h
    proj_24h_kg = 0.0
    # Si la linea esta operando y el tiempo es positivo
    if line_status == 'operando' and fill_time_seconds > 0:
        # Calcula velocidad instantanea
        speed_kg_h = calculate_instant_speed(net_weight_kg, fill_time_seconds)
        # Calcula proyeccion 8h
        proj_8h_kg = project_shift_production(speed_kg_h)
        # Calcula proyeccion 24h
        proj_24h_kg = project_daily_production(speed_kg_h)

    # Abre conexion para actualizar pesada
    with get_db_connection() as conn:
        # Busca registro anterior
        old = conn.execute("SELECT * FROM production_weighings WHERE id = ?;", (weighing_id,)).fetchone()
        # Si no existe
        if not old:
            # Lanza error
            raise ValueError(f"Pesada con ID #{weighing_id} no encontrada.")
        # Convierte a diccionario
        old_dict = dict(old)

        # Determina nueva fecha de muestra
        new_sample_date = str(sample_date).strip() if sample_date and str(sample_date).strip() else old_dict.get('sample_date')
        # Determina nuevo turno de muestra
        new_shift = str(shift_id).strip().upper() if shift_id and str(shift_id).strip() and str(shift_id).strip().lower() != 'auto' else old_dict.get('shift_id')
        # Determina operador responsable actualizado o preserva anterior
        new_operator = str(operator_name).strip() if operator_name and str(operator_name).strip() else old_dict.get('operator_name')

        # Actualiza registro en base de datos
        conn.execute("""
            UPDATE production_weighings
            SET sample_point = ?, gross_weight_kg = ?, tare_weight_kg = ?,
                net_weight_kg = ?, fill_time_seconds = ?, line_status = ?,
                speed_kg_h = ?, proj_8h_kg = ?, proj_24h_kg = ?, notes = ?,
                sample_date = ?, shift_id = ?, operator_name = ?
            WHERE id = ?;
        """, (sample_point, gross_weight_kg, tare_weight_kg, net_weight_kg,
              fill_time_seconds, line_status, speed_kg_h, proj_8h_kg, proj_24h_kg,
              notes, new_sample_date, new_shift, new_operator, weighing_id))
        # Confirma cambios
        conn.commit()

    # Registra en auditoria de planta
    details = (
        f"Edición de Pesada #{weighing_id} ({old_dict.get('shift_id', '-')}). Motivo: '{edit_reason or 'Ajuste operativo'}'. "
        f"Antes: [Fecha={old_dict.get('sample_date')}, Turno={old_dict.get('shift_id')}, Punto={old_dict.get('sample_point')}, Bruto={old_dict.get('gross_weight_kg')}kg, "
        f"Tara={old_dict.get('tare_weight_kg')}kg, Neto={old_dict.get('net_weight_kg')}kg, "
        f"Tiempo={old_dict.get('fill_time_seconds')}s, Vel={old_dict.get('speed_kg_h')}kg/h, Estado={old_dict.get('line_status')}]. "
        f"Ahora: [Fecha={new_sample_date}, Turno={new_shift}, Punto={sample_point}, Bruto={gross_weight_kg}kg, "
        f"Tara={tare_weight_kg}kg, Neto={net_weight_kg}kg, "
        f"Tiempo={fill_time_seconds}s, Vel={speed_kg_h}kg/h, Estado={line_status}]."
    )
    # Registra evento de auditoria
    record_audit_event('PRODUCCION', 'EDICION_PESADA', details, user_override=operator_name)
    # Registra en log de produccion
    log_info('PRODUCTION', f"Pesada #{weighing_id} modificada por {operator_name or 'usuario'}: {details}")
    # Retorna exito
    return True

# Obtiene las ultimas pesadas registradas para un turno o fecha de muestra
def get_recent_weighings(shift_id=None, limit=50, target_date=None):
    # Abre conexion a base de datos
    with get_db_connection() as conn:
        # Si se filtro por turno y fecha de muestra
        if shift_id and target_date:
            # Consulta pesadas con ambos filtros ordenando cronologicamente por fecha de muestra
            rows = conn.execute("""
                SELECT * FROM production_weighings
                WHERE shift_id = ? AND COALESCE(sample_date, date(timestamp)) = ?
                ORDER BY COALESCE(sample_date, date(timestamp)) DESC, timestamp DESC
                LIMIT ?;
            """, (shift_id, str(target_date).strip(), limit)).fetchall()
        # Si se filtro solo por turno
        elif shift_id:
            # Consulta pesadas del turno ordenando por fecha de muestra
            rows = conn.execute("""
                SELECT * FROM production_weighings
                WHERE shift_id = ?
                ORDER BY COALESCE(sample_date, date(timestamp)) DESC, timestamp DESC
                LIMIT ?;
            """, (shift_id, limit)).fetchall()
        # Si se filtro solo por fecha de muestra
        elif target_date:
            # Consulta pesadas de la fecha ordenando cronologicamente
            rows = conn.execute("""
                SELECT * FROM production_weighings
                WHERE COALESCE(sample_date, date(timestamp)) = ?
                ORDER BY COALESCE(sample_date, date(timestamp)) DESC, timestamp DESC
                LIMIT ?;
            """, (str(target_date).strip(), limit)).fetchall()
        # Si no hay filtros
        else:
            # Consulta las ultimas pesadas globales ordenadas por fecha de muestra
            rows = conn.execute("""
                SELECT * FROM production_weighings
                ORDER BY COALESCE(sample_date, date(timestamp)) DESC, timestamp DESC
                LIMIT ?;
            """, (limit,)).fetchall()
        # Retorna lista de diccionarios
        return [dict(row) for row in rows]

# Registra una parada o detencion en la linea de proceso con seleccion de turno, fecha y observaciones
def record_line_stop(shift_id=None, duration_minutes=0.0, reason='Mantenimiento', operator_name=None, stop_date=None, start_time=None, comments=''):
    """
    Registra una parada o detención de planta con motivo y comentarios detallados.
    Si shift_id o stop_date no se proporcionan, toma automáticamente el turno al que corresponde
    el horario de carga y el día de carga oficial de planta (UTC-3).
    """
    now = get_plant_now()
    now_str = get_plant_now_str()
    slot_info = determine_time_slot(now)

    # Si no se pasó fecha, toma la fecha operativa actual de la planta
    clean_date = str(stop_date).strip() if stop_date and str(stop_date).strip() else None

    # Si no se pasó shift_id o viene 'auto' o vacío, toma el turno correspondiente al horario de carga
    clean_shift = str(shift_id).strip().upper() if shift_id and str(shift_id).strip() and str(shift_id).strip().lower() != 'auto' else None
    if not clean_shift:
        clean_shift = slot_info['shift_id']

    # Determina la marca de tiempo de inicio
    if start_time and str(start_time).strip():
        final_start_time = str(start_time).strip()
    elif clean_date:
        time_part = now.strftime('%H:%M:%S')
        final_start_time = f"{clean_date} {time_part}"
    else:
        final_start_time = now_str

    duration_val = float(duration_minutes or 0.0)
    comments_clean = str(comments or '').strip()

    with get_db_connection() as conn:
        cursor = conn.execute("""
            INSERT INTO line_stops (shift_id, start_time, duration_minutes, reason, operator_name, comments)
            VALUES (?, ?, ?, ?, ?, ?);
        """, (clean_shift, final_start_time, duration_val, reason, operator_name or 'Operario', comments_clean))
        conn.commit()
        stop_id = cursor.lastrowid

    log_info('PRODUCTION', f'Parada ID {stop_id} registrada: {duration_val} min en turno {clean_shift} ({reason}) el {final_start_time}. Detalle: {comments_clean}.')
    return {
        'id': stop_id,
        'shift_id': clean_shift,
        'start_time': final_start_time,
        'duration_minutes': duration_val,
        'reason': reason,
        'operator_name': operator_name,
        'comments': comments_clean
    }

# Actualiza y ajusta una detencion de linea historica con registro en auditoria
def update_line_stop(stop_id, duration_minutes, reason, edit_reason='', operator_name=None, shift_id=None, stop_date=None, comments=None):
    """
    Modifica una detención de planta y registra la trazabilidad en la bitácora de auditoría.
    """
    duration_val = float(duration_minutes or 0.0)
    with get_db_connection() as conn:
        old = conn.execute("SELECT * FROM line_stops WHERE id = ?;", (stop_id,)).fetchone()
        if not old:
            raise ValueError(f"Detención con ID #{stop_id} no encontrada.")
        old_dict = dict(old)

        new_shift = shift_id if shift_id and str(shift_id).strip() and str(shift_id).strip().lower() != 'auto' else old_dict['shift_id']

        if stop_date and str(stop_date).strip():
            old_time_part = old_dict['start_time'].split(' ')[-1] if ' ' in old_dict['start_time'] else '12:00:00'
            new_start_time = f"{str(stop_date).strip()} {old_time_part}"
        else:
            new_start_time = old_dict['start_time']

        new_comments = str(comments).strip() if comments is not None else old_dict.get('comments', '')

        conn.execute("""
            UPDATE line_stops
            SET duration_minutes = ?, reason = ?, shift_id = ?, start_time = ?, comments = ?
            WHERE id = ?;
        """, (duration_val, reason, new_shift, new_start_time, new_comments, stop_id))
        conn.commit()

    details = (
        f"Parada #{stop_id} modificada por {operator_name or 'usuario'}. Motivo del ajuste: '{edit_reason or 'Corrección de datos'}'. "
        f"Antes: [{old_dict.get('duration_minutes')} min, Turno {old_dict.get('shift_id')}, Motivo: {old_dict.get('reason')}, Obs: '{old_dict.get('comments', '')}', Inicio: {old_dict.get('start_time')}]. "
        f"Ahora: [{duration_val} min, Turno {new_shift}, Motivo: {reason}, Obs: '{new_comments}', Inicio: {new_start_time}]."
    )
    record_audit_event('PRODUCCION', 'EDICION_PARADA', details, user_override=operator_name)
    log_info('PRODUCTION', details)
    return True

# Elimina una detencion de linea y asienta en bitacora de auditoria
def delete_line_stop(stop_id, delete_reason='', operator_name=None):
    """
    Elimina una detención de planta y registra el evento en la bitácora de auditoría.
    """
    with get_db_connection() as conn:
        old = conn.execute("SELECT * FROM line_stops WHERE id = ?;", (stop_id,)).fetchone()
        if not old:
            raise ValueError(f"Detención con ID #{stop_id} no encontrada.")
        old_dict = dict(old)

        conn.execute("DELETE FROM line_stops WHERE id = ?;", (stop_id,))
        conn.commit()

    details = (
        f"Parada #{stop_id} eliminada por {operator_name or 'usuario'}. Motivo: '{delete_reason or 'Registro erróneo'}'. "
        f"Datos eliminados: [{old_dict.get('duration_minutes')} min en Turno {old_dict.get('shift_id')}, Motivo: {old_dict.get('reason')}, Inicio: {old_dict.get('start_time')}]."
    )
    record_audit_event('PRODUCCION', 'ELIMINACION_PARADA', details, user_override=operator_name)
    log_info('PRODUCTION', details)
    return True

# Elimina una pesada historica con registro en bitacora de auditoria
def delete_weighing(weighing_id, delete_reason='', operator_name=None):
    """
    Elimina una pesada de producción y registra el evento en la bitácora de auditoría.
    """
    with get_db_connection() as conn:
        old = conn.execute("SELECT * FROM production_weighings WHERE id = ?;", (weighing_id,)).fetchone()
        if not old:
            raise ValueError(f"Pesada con ID #{weighing_id} no encontrada.")
        old_dict = dict(old)

        conn.execute("DELETE FROM production_weighings WHERE id = ?;", (weighing_id,))
        conn.commit()

    details = (
        f"Pesada #{weighing_id} ({old_dict.get('sample_point')}) eliminada por {operator_name or 'usuario'}. Motivo: '{delete_reason or 'Ingreso incorrecto'}'. "
        f"Datos eliminados: [Neto={old_dict.get('net_weight_kg')} kg, Tiempo={old_dict.get('fill_time_seconds')} s, Velocidad={old_dict.get('speed_kg_h')} kg/h, Turno={old_dict.get('shift_id')}, Fecha={old_dict.get('timestamp')}]."
    )
    record_audit_event('PRODUCCION', 'ELIMINACION_PESADA', details, user_override=operator_name)
    log_info('PRODUCTION', details)
    return True

# Obtiene las paradas registradas para un turno y/o fecha operativa en curso
def get_shift_stops(shift_id=None, target_date=None):
    with get_db_connection() as conn:
        clean_date = str(target_date).strip() if target_date and str(target_date).strip() else None
        is_all_shift = (shift_id is None or str(shift_id).strip().lower() in ('all', 'todos', ''))
        if not is_all_shift and clean_date:
            rows = conn.execute("""
                SELECT * FROM line_stops
                WHERE shift_id = ? AND (date(start_time) = ? OR start_time LIKE ?)
                ORDER BY start_time DESC;
            """, (shift_id, clean_date, f"{clean_date}%")).fetchall()
        elif clean_date:
            rows = conn.execute("""
                SELECT * FROM line_stops
                WHERE (date(start_time) = ? OR start_time LIKE ?)
                ORDER BY start_time DESC;
            """, (clean_date, f"{clean_date}%")).fetchall()
        elif not is_all_shift:
            rows = conn.execute("""
                SELECT * FROM line_stops
                WHERE shift_id = ?
                ORDER BY start_time DESC;
            """, (shift_id,)).fetchall()
        else:
            rows = conn.execute("""
                SELECT * FROM line_stops
                ORDER BY start_time DESC
                LIMIT 50;
            """).fetchall()
        return [dict(row) for row in rows]

# Calcula las metricas consolidadas de velocidad para un turno o la jornada completa (semilla y expeller)
def get_shift_speed_summary(shift_id=None, target_date=None):
    clean_date = str(target_date).strip() if target_date and str(target_date).strip() else get_plant_today_str()
    is_all = (shift_id is None or str(shift_id).strip().lower() in ('all', 'todos', ''))
    with get_db_connection() as conn:
        if is_all:
            rows = conn.execute("""
                SELECT sample_point, net_weight_kg, fill_time_seconds, speed_kg_h
                FROM production_weighings
                WHERE COALESCE(sample_date, date(timestamp)) = ? AND line_status = 'operando';
            """, (clean_date,)).fetchall()
            if not rows and target_date is None:
                rows = conn.execute("""
                    SELECT sample_point, net_weight_kg, fill_time_seconds, speed_kg_h
                    FROM production_weighings
                    WHERE line_status = 'operando'
                    ORDER BY COALESCE(sample_date, date(timestamp)) DESC, timestamp DESC
                    LIMIT 30;
                """).fetchall()
            stop_row = conn.execute("""
                SELECT COALESCE(SUM(duration_minutes), 0.0) as total_stop_min
                FROM line_stops
                WHERE (date(start_time) = ? OR start_time LIKE ?);
            """, (clean_date, f"{clean_date}%")).fetchone()
        else:
            rows = conn.execute("""
                SELECT sample_point, net_weight_kg, fill_time_seconds, speed_kg_h
                FROM production_weighings
                WHERE shift_id = ? AND COALESCE(sample_date, date(timestamp)) = ? AND line_status = 'operando';
            """, (shift_id, clean_date)).fetchall()
            if not rows and target_date is None:
                rows = conn.execute("""
                    SELECT sample_point, net_weight_kg, fill_time_seconds, speed_kg_h
                    FROM production_weighings
                    WHERE shift_id = ? AND line_status = 'operando'
                    ORDER BY COALESCE(sample_date, date(timestamp)) DESC, timestamp DESC
                    LIMIT 30;
                """, (shift_id,)).fetchall()
            stop_row = conn.execute("""
                SELECT COALESCE(SUM(duration_minutes), 0.0) as total_stop_min
                FROM line_stops
                WHERE shift_id = ? AND (date(start_time) = ? OR start_time LIKE ?);
            """, (shift_id, clean_date, f"{clean_date}%")).fetchone()

        total_stop_minutes = float(stop_row['total_stop_min'] or 0.0) if stop_row else 0.0
    stop_hours = total_stop_minutes / 60.0
    nominal_hours = 24.0 if is_all else 8.0
    effective_hours = max(0.0, nominal_hours - stop_hours)
    seed_samples = [dict(r) for r in rows if r['sample_point'] == 'ingreso_semilla']
    expeller_samples = [dict(r) for r in rows if r['sample_point'] == 'salida_expeller']
    seed_speeds = [s['speed_kg_h'] for s in seed_samples]
    expeller_speeds = [s['speed_kg_h'] for s in expeller_samples]
    seed_avg_arithmetic = calculate_arithmetic_average_speed(seed_speeds)
    seed_agg_speed = calculate_aggregated_speed(seed_samples)
    expeller_avg_arithmetic = calculate_arithmetic_average_speed(expeller_speeds)
    expeller_agg_speed = calculate_aggregated_speed(expeller_samples)
    seed_proj_8h = project_shift_production(seed_avg_arithmetic)
    seed_proj_24h = project_daily_production(seed_avg_arithmetic)
    seed_estimated = calculate_estimated_production(seed_avg_arithmetic, effective_hours)
    expeller_proj_8h = project_shift_production(expeller_avg_arithmetic)
    expeller_proj_24h = project_daily_production(expeller_avg_arithmetic)
    expeller_estimated = calculate_estimated_production(expeller_avg_arithmetic, effective_hours)
    expeller_yield_pct = round((expeller_avg_arithmetic / seed_avg_arithmetic * 100.0), 2) if seed_avg_arithmetic > 0 else 0.0
    oil_estimated_speed = round(max(0.0, seed_avg_arithmetic - expeller_avg_arithmetic), 2) if seed_avg_arithmetic > 0 else 0.0
    oil_estimated_shift_kg = round(oil_estimated_speed * effective_hours, 2)
    return {
        'shift_id': 'all' if is_all else shift_id,
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
