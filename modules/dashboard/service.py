# Importa modulos de fecha y calendario para calculos de periodos y dias
import datetime
import calendar

# Importa los servicios de inventario, produccion, laboratorio y rendimiento
from modules.inventory.service import get_total_plant_stocks
from modules.production.service import get_shift_speed_summary, get_recent_weighings
from modules.configuration.service import get_active_shift
# Importa get_latest_reconciliation, get_recent_reconciliations y get_auto_efficiency_data para el balance de masa
from modules.yield_balance.service import get_latest_reconciliation, get_recent_reconciliations, get_auto_efficiency_data
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

# Resuelve de forma robusta el rango de fechas solicitado para el dashboard
def resolve_dashboard_date_range(target_date=None, start_date=None, end_date=None, month=None):
    """
    Normaliza y resuelve el alcance de fechas para el Dashboard Administrativo:
    - Día único: target_date o start_date
    - Franja de días: start_date y end_date
    - Mes completo: month (YYYY-MM)
    - Predeterminado: Día en curso oficial de planta (UTC-3)
    """
    current_slot = get_current_time_slot()
    today_str = current_slot['operational_date']

    clean_month = str(month).strip() if month and str(month).strip() else None
    clean_target = str(target_date).strip() if target_date and str(target_date).strip() else None
    clean_start = str(start_date).strip() if start_date and str(start_date).strip() else None
    clean_end = str(end_date).strip() if end_date and str(end_date).strip() else None

    meses_es = {
        1: 'Enero', 2: 'Febrero', 3: 'Marzo', 4: 'Abril',
        5: 'Mayo', 6: 'Junio', 7: 'Julio', 8: 'Agosto',
        9: 'Septiembre', 10: 'Octubre', 11: 'Noviembre', 12: 'Diciembre'
    }

    if clean_month:
        try:
            parts = clean_month.split('-')
            y = int(parts[0])
            m = int(parts[1])
            last_d = calendar.monthrange(y, m)[1]
            s_date = f"{y:04d}-{m:02d}-01"
            e_date = f"{y:04d}-{m:02d}-{last_d:02d}"
            month_label = f"{meses_es.get(m, 'Mes')} {y}"
            scope_mode = 'month'
        except Exception:
            s_date = today_str
            e_date = today_str
            month_label = None
            scope_mode = 'day'
    elif clean_start and clean_end:
        s_date = clean_start
        e_date = clean_end
        month_label = None
        scope_mode = 'range' if s_date != e_date else 'day'
    elif clean_target:
        s_date = clean_target
        e_date = clean_target
        month_label = None
        scope_mode = 'day'
    elif clean_start:
        s_date = clean_start
        e_date = clean_start
        month_label = None
        scope_mode = 'day'
    else:
        s_date = today_str
        e_date = today_str
        month_label = None
        scope_mode = 'day'

    # Ordena si vinieron invertidas
    if s_date > e_date:
        s_date, e_date = e_date, s_date

    try:
        d1 = datetime.date.fromisoformat(s_date)
        d2 = datetime.date.fromisoformat(e_date)
        days_count = max(1, (d2 - d1).days + 1)
    except Exception:
        days_count = 1

    is_single_day = (days_count == 1)
    is_today = (is_single_day and s_date == today_str)

    if is_today:
        scope_date_label = f"Día en curso: {s_date}"
    elif is_single_day:
        scope_date_label = f"Jornada: {s_date}"
    elif scope_mode == 'month' and month_label:
        scope_date_label = f"Mes: {month_label} ({days_count} días)"
    else:
        scope_date_label = f"Período: {s_date} al {e_date} ({days_count} días)"

    # Atajos de calendario para la interfaz UI
    try:
        t_dt = datetime.date.fromisoformat(today_str)
        yesterday_str = (t_dt - datetime.timedelta(days=1)).isoformat()
        last_7d_start = (t_dt - datetime.timedelta(days=6)).isoformat()
        cur_month_str = f"{t_dt.year:04d}-{t_dt.month:02d}"
    except Exception:
        yesterday_str = today_str
        last_7d_start = today_str
        cur_month_str = today_str[:7]

    return {
        'start_date': s_date,
        'end_date': e_date,
        'days_count': days_count,
        'is_single_day': is_single_day,
        'is_today': is_today,
        'scope_mode': scope_mode,
        'scope_date_label': scope_date_label,
        'month_param': clean_month,
        'month_label': month_label if scope_mode == 'month' else None,
        'today_str': today_str,
        'yesterday_str': yesterday_str,
        'last_7d_start': last_7d_start,
        'cur_month_str': cur_month_str
    }

# Calcula promedios parciales del turno en curso, promedio del dia o consolidado de periodo (franja/mes)
def get_shift_and_daily_performance(target_date=None, selected_shifts=None, start_date=None, end_date=None, month=None):
    """
    Determina la franja horaria de las muestras y calcula:
    1. Promedios parciales del turno en curso (si la fecha incluye el momento actual).
    2. Promedio consolidado de la jornada o período multidia (franja o mes completo).
    3. Comparativo de performance detallado entre los turnos TM, TT y TN para el período seleccionado.
    """
    date_info = resolve_dashboard_date_range(target_date=target_date, start_date=start_date, end_date=end_date, month=month)
    s_date = date_info['start_date']
    e_date = date_info['end_date']
    days_count = date_info['days_count']
    is_single_day = date_info['is_single_day']
    is_today = date_info['is_today']

    current_slot = get_current_time_slot()
    current_shift_id = current_slot['shift_id']

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

    for w in weighings_rows:
        slot = determine_time_slot(w.get('timestamp'))
        w['_op_date'] = w.get('sample_date') or slot['operational_date']
        w['_slot_shift'] = w.get('shift_id') or slot['shift_id']
        w['_time_slot'] = w.get('time_slot') or slot['time_slot']

    for s in stops_rows:
        slot = determine_time_slot(s.get('start_time'))
        s['_op_date'] = slot['operational_date']
        s['_slot_shift'] = s.get('shift_id') or slot['shift_id']
        s['_time_slot'] = slot['time_slot']

    for l in lab_rows:
        slot = determine_time_slot(l.get('timestamp'))
        l['_op_date'] = l.get('sample_date') or slot['operational_date']
        l['_slot_shift'] = l.get('shift_id') or slot['shift_id']
        l['_time_slot'] = l.get('time_slot') or slot['time_slot']

    # Filtra por el rango de fechas seleccionado (inclusive)
    period_weighings = [w for w in weighings_rows if s_date <= str(w.get('_op_date', '')) <= e_date]
    period_stops = [s for s in stops_rows if s_date <= str(s.get('_op_date', '')) <= e_date]
    period_labs = [l for l in lab_rows if s_date <= str(l.get('_op_date', '')) <= e_date]

    shift_meta = {
        'TM': {'name': 'Turno Mañana', 'time_slot': '06:00 - 14:00', 'icon': '🌅', 'color': '#0284c7'},
        'TT': {'name': 'Turno Tarde', 'time_slot': '14:00 - 22:00', 'icon': '☀️', 'color': '#ea580c'},
        'TN': {'name': 'Turno Noche', 'time_slot': '22:00 - 06:00', 'icon': '🌙', 'color': '#6366f1'}
    }

    shifts_comparison = []
    shifts_by_id = {}

    for s_id in all_shifts_keys:
        meta = shift_meta[s_id]
        is_cur = (s_id == current_shift_id and is_today)
        is_sel = (s_id in selected_shifts_list)

        s_weighings = [w for w in period_weighings if w.get('_slot_shift') == s_id or (w.get('shift_id') == s_id and not w.get('_slot_shift'))]
        s_seed_weighings = [w for w in s_weighings if w.get('sample_point') == 'ingreso_semilla' and w.get('line_status', 'operando') == 'operando']
        s_exp_weighings = [w for w in s_weighings if w.get('sample_point') == 'salida_expeller' and w.get('line_status', 'operando') == 'operando']

        seed_speeds = [w['speed_kg_h'] for w in s_seed_weighings if w.get('speed_kg_h') is not None]
        exp_speeds = [w['speed_kg_h'] for w in s_exp_weighings if w.get('speed_kg_h') is not None]

        seed_avg_speed = calculate_arithmetic_average_speed(seed_speeds)
        exp_avg_speed = calculate_arithmetic_average_speed(exp_speeds)
        exp_yield_pct = round((exp_avg_speed / seed_avg_speed * 100.0), 2) if seed_avg_speed > 0 else 0.0

        s_stops = [st for st in period_stops if st.get('_slot_shift') == s_id or (st.get('shift_id') == s_id and not st.get('_slot_shift'))]
        stop_minutes = round(sum(st.get('duration_minutes', 0.0) for st in s_stops), 1)
        shift_budget_hours = days_count * 8.0
        effective_hours = max(0.0, round(shift_budget_hours - (stop_minutes / 60.0), 2))

        seed_proj_8h = project_shift_production(seed_avg_speed)
        seed_proj_8h_tn = round(seed_proj_8h / 1000.0, 2)
        exp_proj_8h = project_shift_production(exp_avg_speed)
        exp_proj_8h_tn = round(exp_proj_8h / 1000.0, 2)

        seed_estimated_kg = calculate_estimated_production(seed_avg_speed, effective_hours)
        seed_estimated_tn = round(seed_estimated_kg / 1000.0, 2)
        exp_estimated_kg = calculate_estimated_production(exp_avg_speed, effective_hours)
        exp_estimated_tn = round(exp_estimated_kg / 1000.0, 2)

        s_labs = [l for l in period_labs if l.get('_slot_shift') == s_id or (l.get('shift_id') == s_id and not l.get('_slot_shift'))]
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
            status_label = f"Con datos ({total_samples} m.)" if not is_single_day else "Finalizado"
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
        s_w = [w for w in period_weighings if w.get('_slot_shift') == s_id or (w.get('shift_id') == s_id and not w.get('_slot_shift'))]
        sel_seed_weighings.extend([w for w in s_w if w.get('sample_point') == 'ingreso_semilla' and w.get('line_status', 'operando') == 'operando'])
        sel_exp_weighings.extend([w for w in s_w if w.get('sample_point') == 'salida_expeller' and w.get('line_status', 'operando') == 'operando'])
        s_st = [st for st in period_stops if st.get('_slot_shift') == s_id or (st.get('shift_id') == s_id and not st.get('_slot_shift'))]
        sel_stops.extend(s_st)

    sel_seed_speeds = [w['speed_kg_h'] for w in sel_seed_weighings if w.get('speed_kg_h') is not None]
    sel_exp_speeds = [w['speed_kg_h'] for w in sel_exp_weighings if w.get('speed_kg_h') is not None]

    cons_seed_avg = calculate_arithmetic_average_speed(sel_seed_speeds)
    cons_seed_agg = calculate_aggregated_speed(sel_seed_weighings)
    cons_exp_avg = calculate_arithmetic_average_speed(sel_exp_speeds)
    cons_exp_agg = calculate_aggregated_speed(sel_exp_weighings)

    cons_stop_minutes = round(sum(st.get('duration_minutes', 0.0) for st in sel_stops), 1)
    stop_hours = round(cons_stop_minutes / 60.0, 1)
    shifts_per_day = len(selected_shifts_list)
    hours_budget = round(days_count * shifts_per_day * 8.0, 1)
    cons_effective_hours = max(0.0, round(hours_budget - (cons_stop_minutes / 60.0), 2))

    cons_seed_proj_8h = project_shift_production(cons_seed_avg)
    cons_seed_proj_24h = project_daily_production(cons_seed_avg)
    cons_seed_estimated = calculate_estimated_production(cons_seed_avg, cons_effective_hours)

    cons_exp_proj_8h = project_shift_production(cons_exp_avg)
    cons_exp_proj_24h = project_daily_production(cons_exp_avg)
    cons_exp_estimated = calculate_estimated_production(cons_exp_avg, cons_effective_hours)

    cons_exp_yield_pct = round((cons_exp_avg / cons_seed_avg * 100.0), 2) if cons_seed_avg > 0 else 0.0
    cons_oil_speed = round(max(0.0, cons_seed_avg - cons_exp_avg), 2) if cons_seed_avg > 0 else 0.0
    cons_oil_estimated_kg = round(cons_oil_speed * cons_effective_hours, 2)

    # Alcance de etiqueta descriptiva
    if is_all_selected:
        selected_scope_label = "Día Completo (24h)" if is_single_day else f"Período Completo (24h × {days_count}d)"
    elif len(selected_shifts_list) == 1:
        s_code = selected_shifts_list[0]
        selected_scope_label = f"{shift_meta[s_code]['name']} ({shift_meta[s_code]['time_slot']})"
    else:
        selected_scope_label = f"Comparativo ({', '.join(selected_shifts_list)})"

    # Promedios de laboratorio para todo el periodo seleccionado
    p_labs_p2 = [l for l in period_labs if l.get('product') == 'expeller' and (l.get('press_number') == 2 or (l.get('press_number') is None and 'prensa 1' not in str(l.get('sampling_point', '')).lower() and 'p1' not in str(l.get('sampling_point', '')).lower()))]
    p_labs_p1 = [l for l in period_labs if l.get('product') == 'expeller' and (l.get('press_number') == 1 or (l.get('press_number') is None and ('prensa 1' in str(l.get('sampling_point', '')).lower() or 'p1' in str(l.get('sampling_point', '')).lower())))]
    p_labs_oil = [l for l in period_labs if l.get('product') == 'aceite']

    p_f2 = [l['fat_pct'] for l in p_labs_p2 if l.get('fat_pct') is not None]
    period_avg_fat_p2 = round(sum(p_f2) / len(p_f2), 2) if p_f2 else None

    p_f1 = [l['fat_pct'] for l in p_labs_p1 if l.get('fat_pct') is not None]
    period_avg_fat_p1 = round(sum(p_f1) / len(p_f1), 2) if p_f1 else None

    p_m_exp = [l['moisture_pct'] for l in p_labs_p2 if l.get('moisture_pct') is not None]
    period_avg_moist_exp = round(sum(p_m_exp) / len(p_m_exp), 2) if p_m_exp else None

    p_acid = [l['acidity_pct'] for l in p_labs_oil if l.get('acidity_pct') is not None]
    period_avg_acidity = round(sum(p_acid) / len(p_acid), 2) if p_acid else None

    consolidated_speed = {
        'shift_id': ','.join(selected_shifts_list) if not is_all_selected else '24H',
        'effective_hours': cons_effective_hours,
        'stop_minutes': cons_stop_minutes,
        'stop_hours': stop_hours,
        'total_hours_budget': hours_budget,
        'days_count': days_count,
        'is_single_day': is_single_day,
        'seed_sample_count': len(sel_seed_weighings),
        'seed_avg_speed': cons_seed_avg,
        'seed_agg_speed': cons_seed_agg,
        'seed_proj_8h': cons_seed_proj_8h,
        'seed_proj_24h': cons_seed_proj_24h,
        'seed_estimated': cons_seed_estimated,
        'seed_estimated_tn': round(cons_seed_estimated / 1000.0, 2),
        'expeller_sample_count': len(sel_exp_weighings),
        'expeller_avg_speed': cons_exp_avg,
        'expeller_agg_speed': cons_exp_agg,
        'expeller_proj_8h': cons_exp_proj_8h,
        'expeller_proj_24h': cons_exp_proj_24h,
        'expeller_estimated': cons_exp_estimated,
        'expeller_estimated_tn': round(cons_exp_estimated / 1000.0, 2),
        'expeller_yield_pct': cons_exp_yield_pct,
        'oil_estimated_speed': cons_oil_speed,
        'oil_estimated_kg': cons_oil_estimated_kg,
        'oil_estimated_shift_kg': cons_oil_estimated_kg
    }

    return {
        'start_date': s_date,
        'end_date': e_date,
        'operational_date': s_date if is_single_day else f"{s_date} a {e_date}",
        'active_op_date': s_date,
        'days_count': days_count,
        'is_single_day': is_single_day,
        'is_today': is_today,
        'scope_mode': date_info['scope_mode'],
        'scope_date_label': date_info['scope_date_label'],
        'month_param': date_info['month_param'],
        'month_label': date_info['month_label'],
        'today_str': date_info['today_str'],
        'yesterday_str': date_info['yesterday_str'],
        'last_7d_start': date_info['last_7d_start'],
        'cur_month_str': date_info['cur_month_str'],
        'date_info': date_info,
        'current_shift_id': current_shift_id,
        'current_time_slot': current_slot['time_slot'],
        'current_shift': current_shift_data,
        'shifts_comparison': shifts_comparison,
        'shifts_by_id': shifts_by_id,
        'selected_shifts': selected_shifts_list,
        'is_all_selected': is_all_selected,
        'selected_scope_label': selected_scope_label,
        'consolidated_speed': consolidated_speed,
        'avg_fat_p2': period_avg_fat_p2,
        'avg_fat_p1': period_avg_fat_p1,
        'avg_moist_exp': period_avg_moist_exp,
        'avg_acidity': period_avg_acidity,
        'total_lab_samples': len(period_labs),
        'total_weighings_samples': len(sel_seed_weighings) + len(sel_exp_weighings)
    }

# Genera el resumen consolidado ejecutivo de la planta en un golpe de vista
def get_executive_dashboard_data(selected_shifts=None, target_date=None, start_date=None, end_date=None, month=None):
    # Obtiene metricas por franja horaria, comparativo de turnos y período seleccionado
    shift_performance = get_shift_and_daily_performance(
        target_date=target_date,
        selected_shifts=selected_shifts,
        start_date=start_date,
        end_date=end_date,
        month=month
    )
    s_date = shift_performance['start_date']
    e_date = shift_performance['end_date']
    is_single_day = shift_performance['is_single_day']
    active_shift = get_active_shift()

    # Obtiene existencias totales al corte de fecha del período (último cubicaje disponible registrado hasta e_date)
    stocks = get_total_plant_stocks(as_of_date=e_date)

    # Resumen de velocidades consolidado para el período
    speed_summary = shift_performance['consolidated_speed']

    # Pesadas del período para el gráfico cronológico y mini-tabla
    with get_db_connection() as conn:
        period_rows = conn.execute("""
            SELECT * FROM production_weighings
            WHERE COALESCE(sample_date, date(timestamp)) >= ?
              AND COALESCE(sample_date, date(timestamp)) <= ?
            ORDER BY timestamp ASC;
        """, (s_date, e_date)).fetchall()
        period_weighings_all = [dict(r) for r in period_rows]

    # Filtra por turnos seleccionados si no es 'all'
    if shift_performance['is_all_selected']:
        chart_weighings = period_weighings_all
    else:
        sel_set = set(shift_performance['selected_shifts'])
        chart_weighings = [w for w in period_weighings_all if w.get('shift_id') in sel_set]

    chart_labels = []
    seed_chart_data = []
    expeller_chart_data = []

    for w in chart_weighings:
        ts = w.get('timestamp', '')
        time_part = ts.split(' ')[-1][:5] if ' ' in ts else ts[:5]
        date_part = w.get('sample_date') or (ts.split(' ')[0] if ' ' in ts else '')
        if is_single_day:
            point_label = time_part
        else:
            try:
                d_obj = datetime.date.fromisoformat(date_part)
                day_month = d_obj.strftime("%d/%m")
            except Exception:
                day_month = date_part[8:10] + '/' + date_part[5:7] if len(date_part) >= 10 else date_part
            point_label = f"{day_month} {time_part}"

        unique_label = point_label
        dup_count = 1
        while unique_label in chart_labels:
            dup_count += 1
            unique_label = f"{point_label} (#{dup_count})"

        chart_labels.append(unique_label)
        if w.get('sample_point') == 'ingreso_semilla':
            seed_chart_data.append({'time': unique_label, 'speed': w.get('speed_kg_h', 0.0)})
        else:
            expeller_chart_data.append({'time': unique_label, 'speed': w.get('speed_kg_h', 0.0)})

    # Mini-tabla de ultimos muestreos de linea del periodo (los mas recientes primero)
    recent_period_weighings = list(reversed(chart_weighings))

    latest_yield = get_latest_reconciliation()
    auto_efficiency = get_auto_efficiency_data(active_shift['shift_id'])

    # Si hay pesadas computadas en el período, calcula eficiencia consolidada del período
    if speed_summary['seed_avg_speed'] > 0 and speed_summary['expeller_avg_speed'] > 0:
        eff_rend_exp = speed_summary['expeller_yield_pct']
        oil_extr_pct = round(max(0.0, 100.0 - eff_rend_exp), 2)
        recup_pct = round((oil_extr_pct / 44.0) * 100.0, 2)

        efficiency_kpi = {
            'oil_yield_pct': oil_extr_pct,
            'recup_oil_pct': recup_pct,
            'expeller_yield_pct': eff_rend_exp,
            'diff_balance_pct': 0.0,
            'status': 'Consolidado del Período' if not is_single_day else 'Automático (Registros)',
            'status_color': '#15803d',
            'badge_text': '⚡ Período Consolidado' if not is_single_day else '⚡ Automático (Registros)',
            'badge_color': '#166534',
            'badge_bg': '#dcfce7',
            'source_text': f"Telemetría ({shift_performance['scope_date_label']})",
            'is_automatic': True,
            'has_records': True
        }
    elif auto_efficiency.get('has_records', False):
        efficiency_kpi = auto_efficiency
    elif latest_yield:
        efficiency_kpi = dict(latest_yield)
        efficiency_kpi['is_automatic'] = False
        efficiency_kpi['status'] = 'Balance Registrado'
        efficiency_kpi['status_color'] = '#15803d'
        efficiency_kpi['badge_text'] = '📋 Balance Conciliado'
        efficiency_kpi['badge_color'] = '#166534'
        efficiency_kpi['badge_bg'] = '#dcfce7'
        efficiency_kpi['source_text'] = 'Conciliación Guardada'
    else:
        efficiency_kpi = dict(auto_efficiency)
        if 'badge_text' not in efficiency_kpi:
            efficiency_kpi['badge_text'] = '⚡ Automático (Registros)'
            efficiency_kpi['badge_color'] = '#166534'
            efficiency_kpi['badge_bg'] = '#dcfce7'
        efficiency_kpi['source_text'] = 'Telemetría y Pesadas'

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
        'recent_weighings': recent_period_weighings[:10],
        'latest_yield': latest_yield,
        'auto_efficiency': auto_efficiency,
        'efficiency_kpi': efficiency_kpi,
        'yield_history': yield_history,
        'all_recent_weighings': all_recent_weighings,
        'maintenance_kpis': maintenance_kpis,
        'operational_date': shift_performance['operational_date']
    }

# Alias retrocompatible para comparativo de turnos en el dashboard
get_dashboard_shift_comparison = get_shift_and_daily_performance
