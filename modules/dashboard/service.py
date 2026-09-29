# Importa los servicios de inventario, produccion, laboratorio y rendimiento
from modules.inventory.service import get_total_plant_stocks
from modules.production.service import get_shift_speed_summary, get_recent_weighings
from modules.configuration.service import get_active_shift
# Importa get_latest_reconciliation y get_recent_reconciliations para el historial de balances
from modules.yield_balance.service import get_latest_reconciliation, get_recent_reconciliations
# Importa el servicio de KPIs de mantenimiento para el cockpit ejecutivo
from modules.maintenance.service import get_maintenance_dashboard_kpis
# Importa la conexion a la base de datos
from core.database import get_db_connection
# Importa la determinacion de franjas horarias oficiales de planta (UTC-3)
from core.timezone import (
    determine_time_slot, get_current_time_slot, get_current_operational_date,
    get_plant_now, get_plant_today_str
)
# Importa funciones analiticas de calculo de velocidad y proyeccion
from modules.calculations.speed_calc import (
    calculate_arithmetic_average_speed, calculate_aggregated_speed,
    project_shift_production, project_daily_production, calculate_estimated_production
)

# Calcula promedios parciales del turno en curso, promedio del dia y comparativo entre turnos
def get_shift_and_daily_performance(target_date=None, selected_shifts=None):
    """
    Determina la franja horaria de las muestras y calcula:
    1. Promedios parciales del turno en curso (según la hora oficial de planta UTC-3).
    2. Promedio consolidado del día (24h) por defecto, o del subconjunto de turnos seleccionados.
    3. Comparativo de performance detallado entre los turnos TM, TT y TN.
    """
    current_slot = get_current_time_slot()
    current_shift_id = current_slot['shift_id']
    current_op_date = current_slot['operational_date']

    all_shifts_keys = ['TM', 'TT', 'TN']
    if not selected_shifts or selected_shifts == 'all':
        selected_shifts_list = list(all_shifts_keys)
        is_all_selected = True
    elif isinstance(selected_shifts, str):
        parsed = [s.strip().upper() for s in selected_shifts.split(',') if s.strip().upper() in all_shifts_keys]
        if not parsed:
            selected_shifts_list = list(all_shifts_keys)
            is_all_selected = True
        else:
            selected_shifts_list = parsed
            is_all_selected = (set(selected_shifts_list) == set(all_shifts_keys))
    elif isinstance(selected_shifts, (list, tuple, set)):
        parsed = [str(s).strip().upper() for s in selected_shifts if str(s).strip().upper() in all_shifts_keys]
        if not parsed:
            selected_shifts_list = list(all_shifts_keys)
            is_all_selected = True
        else:
            selected_shifts_list = parsed
            is_all_selected = (set(selected_shifts_list) == set(all_shifts_keys))
    else:
        selected_shifts_list = list(all_shifts_keys)
        is_all_selected = True

    # Consulta pesadas, paradas y analisis de laboratorio desde la base de datos
    with get_db_connection() as conn:
        weighings_rows = [dict(r) for r in conn.execute("SELECT * FROM production_weighings ORDER BY timestamp ASC;").fetchall()]
        stops_rows = [dict(r) for r in conn.execute("SELECT * FROM line_stops ORDER BY start_time ASC;").fetchall()]
        lab_rows = [dict(r) for r in conn.execute("SELECT * FROM lab_analyses ORDER BY timestamp ASC;").fetchall()]

    dates_with_data = set()
    for w in weighings_rows:
        slot = determine_time_slot(w.get('timestamp'))
        w['_op_date'] = slot['operational_date']
        w['_slot_shift'] = slot['shift_id']
        w['_time_slot'] = slot['time_slot']
        dates_with_data.add(slot['operational_date'])

    for s in stops_rows:
        slot = determine_time_slot(s.get('start_time'))
        s['_op_date'] = slot['operational_date']
        s['_slot_shift'] = slot['shift_id']
        s['_time_slot'] = slot['time_slot']
        dates_with_data.add(slot['operational_date'])

    for l in lab_rows:
        slot = determine_time_slot(l.get('timestamp'))
        l['_op_date'] = slot['operational_date']
        l['_slot_shift'] = slot['shift_id']
        l['_time_slot'] = slot['time_slot']
        dates_with_data.add(slot['operational_date'])

    if target_date:
        active_op_date = target_date
    elif current_op_date in dates_with_data:
        active_op_date = current_op_date
    elif dates_with_data:
        active_op_date = sorted(list(dates_with_data), reverse=True)[0]
    else:
        active_op_date = current_op_date

    day_weighings = [w for w in weighings_rows if w.get('_op_date') == active_op_date]
    day_stops = [s for s in stops_rows if s.get('_op_date') == active_op_date]
    day_labs = [l for l in lab_rows if l.get('_op_date') == active_op_date]

    shift_meta = {
        'TM': {'name': 'Turno Mañana', 'time_slot': '06:00 - 14:00', 'icon': '🌅', 'color': '#0284c7'},
        'TT': {'name': 'Turno Tarde', 'time_slot': '14:00 - 22:00', 'icon': '☀️', 'color': '#ea580c'},
        'TN': {'name': 'Turno Noche', 'time_slot': '22:00 - 06:00', 'icon': '🌙', 'color': '#6366f1'}
    }

    shifts_comparison = []
    shifts_by_id = {}

    for s_id in all_shifts_keys:
        meta = shift_meta[s_id]
        is_cur = (s_id == current_shift_id and active_op_date == current_op_date)
        is_sel = (s_id in selected_shifts_list)

        s_weighings = [w for w in day_weighings if w.get('_slot_shift') == s_id or (w.get('shift_id') == s_id and not w.get('_slot_shift'))]
        s_seed_weighings = [w for w in s_weighings if w.get('sample_point') == 'ingreso_semilla' and w.get('line_status', 'operando') == 'operando']
        s_exp_weighings = [w for w in s_weighings if w.get('sample_point') == 'salida_expeller' and w.get('line_status', 'operando') == 'operando']

        seed_speeds = [w['speed_kg_h'] for w in s_seed_weighings if w.get('speed_kg_h') is not None]
        exp_speeds = [w['speed_kg_h'] for w in s_exp_weighings if w.get('speed_kg_h') is not None]

        seed_avg_speed = calculate_arithmetic_average_speed(seed_speeds)
        exp_avg_speed = calculate_arithmetic_average_speed(exp_speeds)
        exp_yield_pct = round((exp_avg_speed / seed_avg_speed * 100.0), 2) if seed_avg_speed > 0 else 0.0

        s_stops = [st for st in day_stops if st.get('_slot_shift') == s_id or (st.get('shift_id') == s_id and not st.get('_slot_shift'))]
        stop_minutes = round(sum(st.get('duration_minutes', 0.0) for st in s_stops), 1)
        effective_hours = max(0.0, round(8.0 - (stop_minutes / 60.0), 2))

        seed_proj_8h = project_shift_production(seed_avg_speed)
        seed_proj_8h_tn = round(seed_proj_8h / 1000.0, 2)
        exp_proj_8h = project_shift_production(exp_avg_speed)
        exp_proj_8h_tn = round(exp_proj_8h / 1000.0, 2)

        seed_estimated_kg = calculate_estimated_production(seed_avg_speed, effective_hours)
        seed_estimated_tn = round(seed_estimated_kg / 1000.0, 2)
        exp_estimated_kg = calculate_estimated_production(exp_avg_speed, effective_hours)
        exp_estimated_tn = round(exp_estimated_kg / 1000.0, 2)

        s_labs = [l for l in day_labs if l.get('_slot_shift') == s_id or (l.get('shift_id') == s_id and not l.get('_slot_shift'))]
        labs_p2 = [l for l in s_labs if l.get('product') == 'expeller' and (l.get('press_number') == 2 or (l.get('press_number') is None and 'prensa 1' not in str(l.get('sampling_point', '')).lower() and 'p1' not in str(l.get('sampling_point', '')).lower()))]
        labs_p1 = [l for l in s_labs if l.get('product') == 'expeller' and (l.get('press_number') == 1 or (l.get('press_number') is None and ('prensa 1' in str(l.get('sampling_point', '')).lower() or 'p1' in str(l.get('sampling_point', '')).lower())))]
        labs_oil = [l for l in s_labs if l.get('product') == 'aceite']

        f_p2_vals = [l['fat_pct'] for l in labs_p2 if l.get('fat_pct') is not None]
        avg_fat_p2 = round(sum(f_p2_vals) / len(f_p2_vals), 2) if f_p2_vals else None

        f_p1_vals = [l['fat_pct'] for l in labs_p1 if l.get('fat_pct') is not None]
        avg_fat_p1 = round(sum(f_p1_vals) / len(f_p1_vals), 2) if f_p1_vals else None

        m_exp_vals = [l['moisture_pct'] for l in labs_p2 if l.get('moisture_pct') is not None]
        avg_moist_exp = round(sum(m_exp_vals) / len(m_exp_vals), 2) if m_exp_vals else None

        acid_vals = [l['acidity_pct'] for l in labs_oil if l.get('acidity_pct') is not None]
        avg_acidity = round(sum(acid_vals) / len(acid_vals), 2) if acid_vals else None

        total_samples = len(s_seed_weighings) + len(s_exp_weighings) + len(s_labs)

        if is_cur:
            status_label = "En curso (Parcial)"
            status_badge = "badge-current"
        elif total_samples > 0:
            status_label = "Finalizado"
            status_badge = "badge-completed"
        else:
            status_label = "Sin datos"
            status_badge = "badge-nodata"

        shift_obj = {
            'shift_id': s_id,
            'shift_name': meta['name'],
            'time_slot': meta['time_slot'],
            'icon': meta['icon'],
            'color': meta['color'],
            'is_current': is_cur,
            'is_selected': is_sel,
            'status_label': status_label,
            'status_badge': status_badge,
            'total_samples': total_samples,
            'seed_samples_count': len(s_seed_weighings),
            'exp_samples_count': len(s_exp_weighings),
            'lab_samples_count': len(s_labs),
            'seed_avg_speed': seed_avg_speed,
            'exp_avg_speed': exp_avg_speed,
            'exp_yield_pct': exp_yield_pct,
            'seed_proj_8h_tn': seed_proj_8h_tn,
            'exp_proj_8h_tn': exp_proj_8h_tn,
            'seed_estimated_tn': seed_estimated_tn,
            'exp_estimated_tn': exp_estimated_tn,
            'stop_minutes': stop_minutes,
            'effective_hours': effective_hours,
            'avg_fat_p2': avg_fat_p2,
            'avg_fat_p1': avg_fat_p1,
            'avg_moist_exp': avg_moist_exp,
            'avg_acidity': avg_acidity
        }
        shifts_comparison.append(shift_obj)
        shifts_by_id[s_id] = shift_obj

    current_shift_data = shifts_by_id.get(current_shift_id, shifts_comparison[0])

    sel_seed_weighings = []
    sel_exp_weighings = []
    sel_stops = []
    for s_id in selected_shifts_list:
        s_w = [w for w in day_weighings if w.get('_slot_shift') == s_id or (w.get('shift_id') == s_id and not w.get('_slot_shift'))]
        sel_seed_weighings.extend([w for w in s_w if w.get('sample_point') == 'ingreso_semilla' and w.get('line_status', 'operando') == 'operando'])
        sel_exp_weighings.extend([w for w in s_w if w.get('sample_point') == 'salida_expeller' and w.get('line_status', 'operando') == 'operando'])
        s_st = [st for st in day_stops if st.get('_slot_shift') == s_id or (st.get('shift_id') == s_id and not st.get('_slot_shift'))]
        sel_stops.extend(s_st)

    sel_seed_speeds = [w['speed_kg_h'] for w in sel_seed_weighings if w.get('speed_kg_h') is not None]
    sel_exp_speeds = [w['speed_kg_h'] for w in sel_exp_weighings if w.get('speed_kg_h') is not None]

    cons_seed_avg = calculate_arithmetic_average_speed(sel_seed_speeds)
    cons_seed_agg = calculate_aggregated_speed(sel_seed_weighings)
    cons_exp_avg = calculate_arithmetic_average_speed(sel_exp_speeds)
    cons_exp_agg = calculate_aggregated_speed(sel_exp_weighings)

    cons_stop_minutes = round(sum(st.get('duration_minutes', 0.0) for st in sel_stops), 1)
    hours_budget = len(selected_shifts_list) * 8.0
    cons_effective_hours = max(0.0, round(hours_budget - (cons_stop_minutes / 60.0), 2))

    cons_seed_proj_8h = project_shift_production(cons_seed_avg)
    cons_seed_proj_24h = project_daily_production(cons_seed_avg)
    cons_seed_estimated = calculate_estimated_production(cons_seed_avg, cons_effective_hours)

    cons_exp_proj_8h = project_shift_production(cons_exp_avg)
    cons_exp_proj_24h = project_daily_production(cons_exp_avg)
    cons_exp_estimated = calculate_estimated_production(cons_exp_avg, cons_effective_hours)

    cons_exp_yield_pct = round((cons_exp_avg / cons_seed_avg * 100.0), 2) if cons_seed_avg > 0 else 0.0
    cons_oil_speed = round(max(0.0, cons_seed_avg - cons_exp_avg), 2) if cons_seed_avg > 0 else 0.0
    cons_oil_estimated_shift_kg = round(cons_oil_speed * cons_effective_hours, 2)

    if is_all_selected:
        selected_scope_label = "Promedio del Día (24 Horas)"
    elif len(selected_shifts_list) == 1:
        s_code = selected_shifts_list[0]
        selected_scope_label = f"{shift_meta[s_code]['name']} ({shift_meta[s_code]['time_slot']})"
    else:
        selected_scope_label = f"Comparativo ({', '.join(selected_shifts_list)})"

    consolidated_speed = {
        'shift_id': ','.join(selected_shifts_list) if not is_all_selected else '24H',
        'effective_hours': cons_effective_hours,
        'stop_minutes': cons_stop_minutes,
        'seed_sample_count': len(sel_seed_weighings),
        'seed_avg_speed': cons_seed_avg,
        'seed_agg_speed': cons_seed_agg,
        'seed_proj_8h': cons_seed_proj_8h,
        'seed_proj_24h': cons_seed_proj_24h,
        'seed_estimated': cons_seed_estimated,
        'expeller_sample_count': len(sel_exp_weighings),
        'expeller_avg_speed': cons_exp_avg,
        'expeller_agg_speed': cons_exp_agg,
        'expeller_proj_8h': cons_exp_proj_8h,
        'expeller_proj_24h': cons_exp_proj_24h,
        'expeller_estimated': cons_exp_estimated,
        'expeller_yield_pct': cons_exp_yield_pct,
        'oil_estimated_speed': cons_oil_speed,
        'oil_estimated_shift_kg': cons_oil_estimated_shift_kg
    }

    return {
        'operational_date': active_op_date,
        'current_shift_id': current_shift_id,
        'current_time_slot': current_slot['time_slot'],
        'current_shift': current_shift_data,
        'shifts_comparison': shifts_comparison,
        'shifts_by_id': shifts_by_id,
        'selected_shifts': selected_shifts_list,
        'is_all_selected': is_all_selected,
        'selected_scope_label': selected_scope_label,
        'consolidated_speed': consolidated_speed
    }

# Genera el resumen consolidado ejecutivo de la planta en un golpe de vista
def get_executive_dashboard_data(selected_shifts=None):
    # Obtiene existencias totales de los 3 stocks clave
    stocks = get_total_plant_stocks()
    # Obtiene datos del turno activo y guardia en marcha
    active_shift = get_active_shift()

    # Obtiene metricas por franja horaria, comparativo de turnos y promedio del dia
    shift_performance = get_shift_and_daily_performance(selected_shifts=selected_shifts)

    # Si hay pesadas computadas en el scope seleccionado, las usa para los pilares del cockpit
    if (shift_performance['consolidated_speed']['seed_sample_count'] > 0 or 
        shift_performance['consolidated_speed']['expeller_sample_count'] > 0):
        speed_summary = shift_performance['consolidated_speed']
    else:
        # Fallback al resumen del turno activo si la fecha operativa actual aún no contiene pesadas
        speed_summary = get_shift_speed_summary(active_shift['shift_id'])

    # Obtiene las ultimas pesadas para la curva cronologica del grafico
    recent_weighings = get_recent_weighings(shift_id=active_shift['shift_id'], limit=12)
    chronological_weighings = list(reversed(recent_weighings))
    chart_labels = []
    seed_chart_data = []
    expeller_chart_data = []
    for w in chronological_weighings:
        time_part = w['timestamp'].split(' ')[-1][:5]
        if time_part not in chart_labels:
            chart_labels.append(time_part)
        if w['sample_point'] == 'ingreso_semilla':
            seed_chart_data.append({'time': time_part, 'speed': w['speed_kg_h']})
        else:
            expeller_chart_data.append({'time': time_part, 'speed': w['speed_kg_h']})

    latest_yield = get_latest_reconciliation()
    yield_history = get_recent_reconciliations(limit=50)
    all_recent_weighings = get_recent_weighings(limit=50)
    maintenance_kpis = get_maintenance_dashboard_kpis()

    return {
        'stocks': stocks,
        'active_shift': active_shift,
        'speed_summary': speed_summary,
        'shift_performance': shift_performance,
        'chart_labels': chart_labels,
        'seed_chart_data': seed_chart_data,
        'expeller_chart_data': expeller_chart_data,
        'recent_weighings': recent_weighings[:8],
        'latest_yield': latest_yield,
        'yield_history': yield_history,
        'all_recent_weighings': all_recent_weighings,
        'maintenance_kpis': maintenance_kpis
    }
