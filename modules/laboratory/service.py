# Importa datetime para estampa de fecha y hora
import datetime
# Importa json para almacenar datos brutos analiticos
import json
# Importa conexion a la base de datos
from core.database import get_db_connection
# Importa funciones analiticas de calculo de laboratorio
from modules.calculations.lab_calc import (
    calculate_moisture_pct, calculate_moisture_with_tare,
    calculate_fat_pct, calculate_foreign_matter_pct, calculate_oil_acidity_pct
)
# Importa el registrador de eventos
from core.error_logger import log_info, log_error
# Importa auditoria de eventos
from core.audit import record_audit_event
# Importa la funcion horaria oficial de planta BioBalcarce (Argentina UTC-3)
from core.timezone import get_plant_now_str

# Registra una determinacion analitica de laboratorio con calculo de parametros o ingreso directo
def record_analysis(sample_code, product, sampling_point, shift_id, operator_name, raw_data, notes='', press_number=None):
    # Inicializa las variables de resultados
    moisture_pct = None
    fat_pct = None
    foreign_matter_pct = None
    acidity_pct = None

    # Normaliza producto y numero de prensa para aislar Prensa 1 de Prensa 2
    if press_number is not None and str(press_number).strip() != '':
        try:
            press_number = int(press_number)
        except (ValueError, TypeError):
            press_number = 2
    elif product == 'expeller_p1':
        product = 'expeller'
        press_number = 1
    elif product == 'expeller':
        sp_lower = str(sampling_point).lower()
        if 'prensa 1' in sp_lower or 'prensa1' in sp_lower or 'p1' in sp_lower:
            press_number = 1
        else:
            press_number = 2
    else:
        press_number = None

    # Si es expeller y no se definio prensa, por defecto es Prensa 2 (producto comercial final)
    if product == 'expeller' and press_number is None:
        press_number = 2

    # Guarda el numero de prensa en los datos crudos para trazabilidad
    if press_number is not None:
        raw_data['press_number'] = press_number

    # Prioridad A: Entrada directa de porcentajes si fueron provistos en el formulario rapido
    if raw_data.get('direct_moisture_pct') is not None and str(raw_data.get('direct_moisture_pct')).strip() != '':
        moisture_pct = float(raw_data['direct_moisture_pct'])
    if raw_data.get('direct_fat_pct') is not None and str(raw_data.get('direct_fat_pct')).strip() != '':
        fat_pct = float(raw_data['direct_fat_pct'])
    if raw_data.get('direct_acidity_pct') is not None and str(raw_data.get('direct_acidity_pct')).strip() != '':
        acidity_pct = float(raw_data['direct_acidity_pct'])
    if raw_data.get('direct_fm_pct') is not None and str(raw_data.get('direct_fm_pct')).strip() != '':
        foreign_matter_pct = float(raw_data['direct_fm_pct'])

    # Prioridad B: Calculo de humedad si se proveyeron pesadas gravimetricas y no se paso directo
    if moisture_pct is None and raw_data.get('moisture_initial_g') and raw_data.get('moisture_dry_g'):
        init_g = float(raw_data['moisture_initial_g'])
        dry_g = float(raw_data['moisture_dry_g'])
        tare_g = float(raw_data.get('moisture_tare_g', 0.0))
        # Si se especifico tara de capsula
        if tare_g > 0:
            moisture_pct = calculate_moisture_with_tare(tare_g, init_g, dry_g)
        else:
            moisture_pct = calculate_moisture_pct(init_g, dry_g)

    # Prioridad C: Calculo de materia grasa si se proveyeron pesadas gravimetricas y no se paso directo
    if fat_pct is None and raw_data.get('fat_sample_g') and raw_data.get('fat_final_flask_g') and raw_data.get('fat_tare_flask_g'):
        sample_g = float(raw_data['fat_sample_g'])
        final_flask_g = float(raw_data['fat_final_flask_g'])
        tare_flask_g = float(raw_data['fat_tare_flask_g'])
        fat_pct = calculate_fat_pct(sample_g, final_flask_g, tare_flask_g)

    # Prioridad D: Calculo de materia extrana si se proveyeron datos de zarandeo
    if foreign_matter_pct is None and raw_data.get('fm_sample_g') and raw_data.get('fm_impurities_g'):
        fm_sample_g = float(raw_data['fm_sample_g'])
        fm_impurities_g = float(raw_data['fm_impurities_g'])
        foreign_matter_pct = calculate_foreign_matter_pct(fm_sample_g, fm_impurities_g)

    # Prioridad E: Calculo de acidez libre si es aceite vegetal y se titularon muestras
    if acidity_pct is None and product == 'aceite' and raw_data.get('acidity_sample_g') and raw_data.get('acidity_naoh_ml'):
        acidity_sample_g = float(raw_data['acidity_sample_g'])
        naoh_ml = float(raw_data['acidity_naoh_ml'])
        naoh_n = float(raw_data.get('acidity_naoh_normality', 0.0997))
        ft = float(raw_data.get('acidity_ft_factor', 0.282))
        acidity_pct = calculate_oil_acidity_pct(acidity_sample_g, naoh_ml, naoh_n, ft)

    # Estampa de tiempo oficial de planta (Argentina UTC-3)
    now_str = get_plant_now_str()

    # Guarda en la tabla lab_analyses
    with get_db_connection() as conn:
        cursor = conn.execute("""
            INSERT INTO lab_analyses (
                timestamp, sample_code, product, sampling_point, press_number, shift_id,
                operator_name, moisture_pct, fat_pct, foreign_matter_pct,
                acidity_pct, raw_data_json, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """, (now_str, sample_code, product, sampling_point, press_number, shift_id,
              operator_name, moisture_pct, fat_pct, foreign_matter_pct,
              acidity_pct, json.dumps(raw_data), notes))
        conn.commit()
        analysis_id = cursor.lastrowid

    # Etiqueta descriptiva para log
    press_tag = f" (Prensa {press_number})" if press_number else ""
    # Registra en log el ensayo
    log_info('LAB', f'Analisis {sample_code} de {product}{press_tag} guardado (MG: {fat_pct}%, H: {moisture_pct}%, Acidez: {acidity_pct}%).')
    # Registra en auditoria de planta
    record_audit_event('LABORATORIO', 'ANALISIS_CALIDAD', f"Muestra {sample_code} ({product}{press_tag}) registrada en {sampling_point}. Humedad: {moisture_pct}%, Grasa: {fat_pct}%, Acidez: {acidity_pct}%. Obs: {notes}")

    # Retorna el resumen del analisis
    return {
        'id': analysis_id,
        'sample_code': sample_code,
        'product': product,
        'press_number': press_number,
        'moisture_pct': moisture_pct,
        'fat_pct': fat_pct,
        'foreign_matter_pct': foreign_matter_pct,
        'acidity_pct': acidity_pct
    }

# Obtiene los analisis recientes de laboratorio
def get_recent_analyses(product=None, limit=50):
    # Abre conexion a base de datos
    with get_db_connection() as conn:
        # Si se filtro por producto
        if product:
            rows = conn.execute("""
                SELECT * FROM lab_analyses
                WHERE product = ?
                ORDER BY timestamp DESC
                LIMIT ?;
            """, (product, limit)).fetchall()
        else:
            rows = conn.execute("""
                SELECT * FROM lab_analyses
                ORDER BY timestamp DESC
                LIMIT ?;
            """, (limit,)).fetchall()
        # Retorna lista de diccionarios
        return [dict(row) for row in rows]

# Obtiene los parametros analiticos promedio de calidad para un turno
def get_shift_lab_averages(shift_id=None):
    # Abre conexion a base de datos
    with get_db_connection() as conn:
        seed_row = None
        exp_p2_shift_row = None
        exp_p1_shift_row = None
        oil_row = None

        # Si se paso un turno en particular, calcula las muestras registradas en ese turno
        if shift_id:
            seed_row = conn.execute("""
                SELECT AVG(fat_pct) as avg_fat, AVG(moisture_pct) as avg_moist, AVG(foreign_matter_pct) as avg_fm
                FROM lab_analyses
                WHERE shift_id = ? AND product = 'semilla';
            """, (shift_id,)).fetchone()

            # Prensa 2 (Relevante / Producto Final): excluye estrictamente determinaciones de Prensa 1
            exp_p2_shift_row = conn.execute("""
                SELECT AVG(fat_pct) as avg_fat, AVG(moisture_pct) as avg_moist
                FROM lab_analyses
                WHERE shift_id = ? AND product = 'expeller'
                  AND (press_number = 2 OR (press_number IS NULL AND LOWER(sampling_point) NOT LIKE '%prensa 1%' AND LOWER(sampling_point) NOT LIKE '%prensa1%' AND LOWER(sampling_point) NOT LIKE '%p1%'));
            """, (shift_id,)).fetchone()

            # Prensa 1 (Indicativo preliminar)
            exp_p1_shift_row = conn.execute("""
                SELECT AVG(fat_pct) as avg_fat, AVG(moisture_pct) as avg_moist
                FROM lab_analyses
                WHERE shift_id = ? AND product = 'expeller'
                  AND (press_number = 1 OR (press_number IS NULL AND (LOWER(sampling_point) LIKE '%prensa 1%' OR LOWER(sampling_point) LIKE '%prensa1%' OR LOWER(sampling_point) LIKE '%p1%')));
            """, (shift_id,)).fetchone()

            oil_row = conn.execute("""
                SELECT AVG(acidity_pct) as avg_acidity, AVG(moisture_pct) as avg_moist
                FROM lab_analyses
                WHERE shift_id = ? AND product = 'aceite';
            """, (shift_id,)).fetchone()

        # Fallbacks si en ese turno no hubo muestras del producto
        if not seed_row or seed_row['avg_fat'] is None:
            seed_row = conn.execute("""
                SELECT fat_pct as avg_fat, moisture_pct as avg_moist, foreign_matter_pct as avg_fm
                FROM lab_analyses
                WHERE product = 'semilla'
                ORDER BY timestamp DESC LIMIT 1;
            """).fetchone()

        # Fallback Prensa 2: ultimo registro de Prensa 2 en planta
        exp_p2_latest = conn.execute("""
            SELECT fat_pct as avg_fat, moisture_pct as avg_moist
            FROM lab_analyses
            WHERE product = 'expeller'
              AND (press_number = 2 OR (press_number IS NULL AND LOWER(sampling_point) NOT LIKE '%prensa 1%' AND LOWER(sampling_point) NOT LIKE '%prensa1%' AND LOWER(sampling_point) NOT LIKE '%p1%'))
            ORDER BY timestamp DESC LIMIT 1;
        """).fetchone()

        # Fallback Prensa 1: ultimo registro de Prensa 1 en planta
        exp_p1_latest = conn.execute("""
            SELECT fat_pct as avg_fat, moisture_pct as avg_moist
            FROM lab_analyses
            WHERE product = 'expeller'
              AND (press_number = 1 OR (press_number IS NULL AND (LOWER(sampling_point) LIKE '%prensa 1%' OR LOWER(sampling_point) LIKE '%prensa1%' OR LOWER(sampling_point) LIKE '%p1%')))
            ORDER BY timestamp DESC LIMIT 1;
        """).fetchone()

        if not oil_row or oil_row['avg_acidity'] is None:
            oil_row = conn.execute("""
                SELECT acidity_pct as avg_acidity, moisture_pct as avg_moist
                FROM lab_analyses
                WHERE product = 'aceite'
                ORDER BY timestamp DESC LIMIT 1;
            """).fetchone()

        # Promedio del dia para Prensa 2: ultimas 24 horas
        day_p2_row = conn.execute("""
            SELECT AVG(fat_pct) as avg_fat, AVG(moisture_pct) as avg_moist
            FROM lab_analyses
            WHERE product = 'expeller'
              AND (press_number = 2 OR (press_number IS NULL AND LOWER(sampling_point) NOT LIKE '%prensa 1%' AND LOWER(sampling_point) NOT LIKE '%prensa1%' AND LOWER(sampling_point) NOT LIKE '%p1%'))
              AND timestamp >= datetime('now', '-3 hours', '-24 hours');
        """).fetchone()

        # Si en 24h no hay muestras, fallback al dia del ultimo registro de Prensa 2
        if not day_p2_row or day_p2_row['avg_fat'] is None:
            day_p2_row = conn.execute("""
                SELECT AVG(fat_pct) as avg_fat, AVG(moisture_pct) as avg_moist
                FROM lab_analyses
                WHERE product = 'expeller'
                  AND (press_number = 2 OR (press_number IS NULL AND LOWER(sampling_point) NOT LIKE '%prensa 1%' AND LOWER(sampling_point) NOT LIKE '%prensa1%' AND LOWER(sampling_point) NOT LIKE '%p1%'))
                  AND date(timestamp) = (
                      SELECT date(timestamp) FROM lab_analyses
                      WHERE product = 'expeller' AND (press_number = 2 OR (press_number IS NULL AND LOWER(sampling_point) NOT LIKE '%prensa 1%' AND LOWER(sampling_point) NOT LIKE '%prensa1%' AND LOWER(sampling_point) NOT LIKE '%p1%'))
                      ORDER BY timestamp DESC LIMIT 1
                  );
            """).fetchone()

        # Valores de Prensa 2 para cada uno de los 3 turnos de planta (TM, TT, TN)
        shifts_p2 = {'TM': None, 'TT': None, 'TN': None}
        for s_code in ['TM', 'TT', 'TN']:
            s_row = conn.execute("""
                SELECT AVG(fat_pct) as avg_fat
                FROM lab_analyses
                WHERE product = 'expeller'
                  AND shift_id = ?
                  AND (press_number = 2 OR (press_number IS NULL AND LOWER(sampling_point) NOT LIKE '%prensa 1%' AND LOWER(sampling_point) NOT LIKE '%prensa1%' AND LOWER(sampling_point) NOT LIKE '%p1%'))
                  AND timestamp >= datetime('now', '-3 hours', '-24 hours');
            """, (s_code,)).fetchone()

            if not s_row or s_row['avg_fat'] is None:
                s_row = conn.execute("""
                    SELECT fat_pct as avg_fat
                    FROM lab_analyses
                    WHERE product = 'expeller'
                      AND shift_id = ?
                      AND (press_number = 2 OR (press_number IS NULL AND LOWER(sampling_point) NOT LIKE '%prensa 1%' AND LOWER(sampling_point) NOT LIKE '%prensa1%' AND LOWER(sampling_point) NOT LIKE '%p1%'))
                    ORDER BY timestamp DESC LIMIT 1;
                """, (s_code,)).fetchone()

            if s_row and s_row['avg_fat'] is not None:
                shifts_p2[s_code] = round(float(s_row['avg_fat']), 2)

        # Calculo final de valores de Prensa 2 (Turno)
        if exp_p2_shift_row and exp_p2_shift_row['avg_fat'] is not None:
            exp_fat_val = round(float(exp_p2_shift_row['avg_fat']), 2)
        elif exp_p2_latest and exp_p2_latest['avg_fat'] is not None:
            exp_fat_val = round(float(exp_p2_latest['avg_fat']), 2)
        else:
            exp_fat_val = 10.0

        if exp_p2_shift_row and exp_p2_shift_row['avg_moist'] is not None:
            exp_moist_val = round(float(exp_p2_shift_row['avg_moist']), 2)
        elif exp_p2_latest and exp_p2_latest['avg_moist'] is not None:
            exp_moist_val = round(float(exp_p2_latest['avg_moist']), 2)
        else:
            exp_moist_val = 7.5

        # Calculo de promedio del dia para Prensa 2
        if day_p2_row and day_p2_row['avg_fat'] is not None:
            exp_day_fat_val = round(float(day_p2_row['avg_fat']), 2)
        else:
            exp_day_fat_val = exp_fat_val

        # Calculo indicativo de Prensa 1 (solo orientativo)
        exp_p1_fat_val = None
        if exp_p1_shift_row and exp_p1_shift_row['avg_fat'] is not None:
            exp_p1_fat_val = round(float(exp_p1_shift_row['avg_fat']), 2)
        elif exp_p1_latest and exp_p1_latest['avg_fat'] is not None:
            exp_p1_fat_val = round(float(exp_p1_latest['avg_fat']), 2)

    # Retorna diccionario consolidado con medias analiticas
    return {
        'seed_fat_pct': round(seed_row['avg_fat'], 2) if seed_row and seed_row['avg_fat'] is not None else 45.0,
        'seed_moist_pct': round(seed_row['avg_moist'], 2) if seed_row and seed_row['avg_moist'] is not None else 9.0,
        'seed_fm_pct': round(seed_row['avg_fm'], 2) if seed_row and seed_row['avg_fm'] is not None else 2.0,
        'expeller_fat_pct': exp_fat_val,
        'expeller_moist_pct': exp_moist_val,
        'expeller_day_fat_pct': exp_day_fat_val,
        'expeller_p1_fat_pct': exp_p1_fat_val,
        'shifts_p2': shifts_p2,
        'oil_acidity_pct': round(oil_row['avg_acidity'], 2) if oil_row and oil_row['avg_acidity'] is not None else 0.8
    }

# Registra la inspeccion, carga y despacho de un camion cisterna de aceite
def record_oil_truck_dispatch(shift_id, operator_name, truck_plate, trailer_plate, driver_name, driver_dni,
                              transport_company, destination, tank_source_id, quantity_kg, transport_status,
                              seals_numbers, sample_delivered='NO', sample_code=None, oil_temperature_c=None,
                              oil_acidity_pct=None, notes=''):
    # Limpia y valida campos obligatorios del transporte
    plate = str(truck_plate).strip().upper()
    trailer = str(trailer_plate).strip().upper() if trailer_plate else ''
    driver = str(driver_name).strip()
    dni = str(driver_dni).strip() if driver_dni else ''
    status = str(transport_status).strip()
    seals = str(seals_numbers).strip()
    sample_deliv = 'SI' if str(sample_delivered).strip().upper() in ('SI', 'S', '1', 'TRUE', 'YES') else 'NO'
    qty_kg = float(quantity_kg or 0.0)
    qty_tons = round(qty_kg / 1000.0, 3)
    tank_id = int(tank_source_id) if tank_source_id else None
    temp_c = float(oil_temperature_c) if oil_temperature_c else None
    acid_pct = float(oil_acidity_pct) if oil_acidity_pct else None

    # Valida que los datos criticos no esten vacios
    if not plate or not driver or not seals or not status:
        raise ValueError("Patente, Chofer, Estado de Transporte y Numeración de Precintos son campos obligatorios.")

    # Estampa de tiempo oficial de planta (Argentina UTC-3)
    now_str = get_plant_now_str()

    # Abre conexion para insertar el registro de despacho
    with get_db_connection() as conn:
        cursor = conn.execute("""
            INSERT INTO oil_truck_dispatches (
                timestamp, shift_id, operator_name, truck_plate, trailer_plate,
                driver_name, driver_dni, transport_company, destination, tank_source_id,
                quantity_kg, quantity_tons, transport_status, seals_numbers,
                sample_delivered, sample_code, oil_temperature_c, oil_acidity_pct, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """, (now_str, shift_id, operator_name, plate, trailer,
              driver, dni, transport_company, destination, tank_id,
              qty_kg, qty_tons, status, seals, sample_deliv, sample_code,
              temp_c, acid_pct, notes))
        conn.commit()
        dispatch_id = cursor.lastrowid

    # Registra evento en log
    log_info('LAB_DISPATCH', f"Despacho #{dispatch_id}: Camion {plate} ({driver}), {qty_kg} kg aceite. Estado: {status}, Precintos: {seals}, Muestra: {sample_deliv}.")
    # Registra en auditoria de planta
    record_audit_event(
        'LABORATORIO',
        'CARGA_CAMION_ACEITE',
        f"Carga y precintado de camión {plate} ({trailer}) - Chofer: {driver} (DNI: {dni}). Estado: {status}. Precintos: '{seals}'. Muestra entregada: {sample_deliv}. Kilos: {qty_kg} kg."
    )

    # Retorna diccionario con la informacion del despacho registrado
    return {
        'id': dispatch_id,
        'timestamp': now_str,
        'truck_plate': plate,
        'trailer_plate': trailer,
        'driver_name': driver,
        'quantity_kg': qty_kg,
        'quantity_tons': qty_tons,
        'transport_status': status,
        'seals_numbers': seals,
        'sample_delivered': sample_deliv
    }

# Obtiene la lista cronologica de cargas y despachos de camiones de aceite
def get_recent_oil_truck_dispatches(limit=50):
    # Abre conexion a la base de datos
    with get_db_connection() as conn:
        # Consulta los despachos vinculando con la denominacion del tanque de origen si existe
        rows = conn.execute("""
            SELECT d.*, t.name as tank_name, t.code as tank_code, s.name as shift_name
            FROM oil_truck_dispatches d
            LEFT JOIN equipment_tanks t ON d.tank_source_id = t.id
            LEFT JOIN shifts s ON d.shift_id = s.id
            ORDER BY d.timestamp DESC
            LIMIT ?;
        """, (limit,)).fetchall()
        # Retorna la lista convertida a diccionarios
        return [dict(r) for r in rows]
