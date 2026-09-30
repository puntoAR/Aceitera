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
from core.timezone import get_plant_now_str, determine_time_slot, get_plant_today_str
# Importa utilidades de conversion numerica segura
from core.utils import safe_float, safe_int

# Registra una determinacion analitica de laboratorio con calculo de parametros o ingreso directo
def record_analysis(sample_code, product, sampling_point, shift_id, operator_name, raw_data, notes='', press_number=None, sample_date=None):
    # Inicializa las variables de resultados
    moisture_pct = None
    # Materia grasa
    fat_pct = None
    # Materia extrana
    foreign_matter_pct = None
    # Acidez libre
    acidity_pct = None

    # Normaliza producto y numero de prensa para aislar Prensa 1 de Prensa 2
    if press_number is not None and str(press_number).strip() != '':
        # Bloque de conversion segura a entero
        try:
            # Convierte a entero
            press_number = int(press_number)
        # Si no es convertible
        except (ValueError, TypeError):
            # Asigna Prensa 2 por defecto
            press_number = 2
    # Si el producto seleccionado fue expeller preliminar de prensa 1
    elif product == 'expeller_p1':
        # Producto base es expeller
        product = 'expeller'
        # Prensa 1
        press_number = 1
    # Si el producto es expeller general
    elif product == 'expeller':
        # Convierte punto a minusculas para detectar menciones a prensa 1
        sp_lower = str(sampling_point).lower()
        # Si contiene referencia explicita a prensa 1
        if 'prensa 1' in sp_lower or 'prensa1' in sp_lower or 'p1' in sp_lower:
            # Prensa 1
            press_number = 1
        # Caso contrario
        else:
            # Prensa 2 relevante comercial
            press_number = 2
    # Para otros productos (semilla o aceite)
    else:
        # No aplica numero de prensa
        press_number = None

    # Si es expeller y no se definio prensa, por defecto es Prensa 2 (producto comercial final)
    if product == 'expeller' and press_number is None:
        # Asigna Prensa 2
        press_number = 2

    # Guarda el numero de prensa en los datos crudos para trazabilidad
    if press_number is not None:
        # Almacena en diccionario
        raw_data['press_number'] = press_number

    # Prioridad A: Entrada directa de porcentajes si fueron provistos en el formulario rapido
    if raw_data.get('direct_moisture_pct') is not None and str(raw_data.get('direct_moisture_pct')).strip() != '':
        # Humedad directa
        moisture_pct = safe_float(raw_data.get('direct_moisture_pct'), default=None)
    # Materia grasa directa
    if raw_data.get('direct_fat_pct') is not None and str(raw_data.get('direct_fat_pct')).strip() != '':
        # Materia grasa directa
        fat_pct = safe_float(raw_data.get('direct_fat_pct'), default=None)
    # Acidez libre directa
    if raw_data.get('direct_acidity_pct') is not None and str(raw_data.get('direct_acidity_pct')).strip() != '':
        # Acidez libre directa
        acidity_pct = safe_float(raw_data.get('direct_acidity_pct'), default=None)
    # Materia extrana directa
    if raw_data.get('direct_fm_pct') is not None and str(raw_data.get('direct_fm_pct')).strip() != '':
        # Materia extrana directa
        foreign_matter_pct = safe_float(raw_data.get('direct_fm_pct'), default=None)

    # Prioridad B: Calculo de humedad si se proveyeron pesadas gravimetricas y no se paso directo
    if moisture_pct is None and raw_data.get('moisture_initial_g') and raw_data.get('moisture_dry_g'):
        # Masa inicial
        init_g = safe_float(raw_data.get('moisture_initial_g'), 0.0)
        # Masa seca
        dry_g = safe_float(raw_data.get('moisture_dry_g'), 0.0)
        # Tara capsula
        tare_g = safe_float(raw_data.get('moisture_tare_g'), 0.0)
        # Si se especifico tara de capsula
        if tare_g > 0:
            # Calcula con tara
            moisture_pct = calculate_moisture_with_tare(tare_g, init_g, dry_g)
        # Si fue gravimetrico directo sin tara
        else:
            # Calcula porcentaje estandar
            moisture_pct = calculate_moisture_pct(init_g, dry_g)

    # Prioridad C: Calculo de materia grasa si se proveyeron pesadas gravimetricas y no se paso directo
    if fat_pct is None and raw_data.get('fat_sample_g') and raw_data.get('fat_final_flask_g') and raw_data.get('fat_tare_flask_g'):
        # Masa muestra
        sample_g = safe_float(raw_data.get('fat_sample_g'), 0.0)
        # Masa balon con grasa
        final_flask_g = safe_float(raw_data.get('fat_final_flask_g'), 0.0)
        # Tara del balon
        tare_flask_g = safe_float(raw_data.get('fat_tare_flask_g'), 0.0)
        # Calcula porcentaje de materia grasa
        fat_pct = calculate_fat_pct(sample_g, final_flask_g, tare_flask_g)

    # Prioridad D: Calculo de materia extrana si se proveyeron datos de zarandeo
    if foreign_matter_pct is None and raw_data.get('fm_sample_g') and raw_data.get('fm_impurities_g'):
        # Masa muestra
        fm_sample_g = safe_float(raw_data.get('fm_sample_g'), 0.0)
        # Masa impurezas
        fm_impurities_g = safe_float(raw_data.get('fm_impurities_g'), 0.0)
        # Calcula porcentaje de materia extrana
        foreign_matter_pct = calculate_foreign_matter_pct(fm_sample_g, fm_impurities_g)

    # Prioridad E: Calculo de acidez libre si es aceite vegetal y se titularon muestras
    if acidity_pct is None and product == 'aceite' and raw_data.get('acidity_sample_g') and raw_data.get('acidity_naoh_ml'):
        # Masa aceite
        acidity_sample_g = safe_float(raw_data.get('acidity_sample_g'), 0.0)
        # Mililitros de NaOH gastados
        naoh_ml = safe_float(raw_data.get('acidity_naoh_ml'), 0.0)
        # Normalidad de NaOH
        naoh_n = safe_float(raw_data.get('acidity_naoh_normality'), 0.0997)
        # Factor titulometrico de acido oleico
        ft = safe_float(raw_data.get('acidity_ft_factor'), 0.282)
        # Calcula porcentaje de acidez oleica
        acidity_pct = calculate_oil_acidity_pct(acidity_sample_g, naoh_ml, naoh_n, ft)

    # Estampa de tiempo oficial de planta al momento de la carga (Argentina UTC-3)
    now_str = get_plant_now_str()
    # Determina franja horaria segun reloj de carga
    slot_info = determine_time_slot(now_str)

    # Determina la fecha de la muestra (si no se especifica, toma la fecha actual de planta)
    clean_sample_date = str(sample_date).strip() if sample_date and str(sample_date).strip() else get_plant_today_str()

    # Normaliza el turno correspondiente a la muestra
    clean_shift = str(shift_id).strip().upper() if shift_id and str(shift_id).strip() and str(shift_id).strip().lower() != 'auto' else None
    # Si no se envio turno especifico
    if not clean_shift:
        # Asigna el turno deducido del momento
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

    # Guarda en la tabla lab_analyses incluyendo la franja horaria y la fecha de muestra
    with get_db_connection() as conn:
        # Inserta registro de analisis
        cursor = conn.execute("""
            INSERT INTO lab_analyses (
                timestamp, sample_code, product, sampling_point, press_number, shift_id,
                operator_name, moisture_pct, fat_pct, foreign_matter_pct,
                acidity_pct, raw_data_json, notes, time_slot, sample_date
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """, (now_str, sample_code, product, sampling_point, press_number, clean_shift,
              operator_name, moisture_pct, fat_pct, foreign_matter_pct,
              acidity_pct, json.dumps(raw_data), notes, time_slot, clean_sample_date))
        # Confirma los cambios
        conn.commit()
        # Obtiene el identificador autogenerado
        analysis_id = cursor.lastrowid

    # Etiqueta descriptiva para log
    press_tag = f" (Prensa {press_number})" if press_number else ""
    # Registra en log el ensayo
    log_info('LAB', f'Analisis {sample_code} de {product}{press_tag} del {clean_sample_date} (Turno {clean_shift}) guardado (MG: {fat_pct}%, H: {moisture_pct}%, Acidez: {acidity_pct}%).')
    # Registra en auditoria de planta
    record_audit_event('LABORATORIO', 'ANALISIS_CALIDAD', f"Muestra {sample_code} ({product}{press_tag}) del {clean_sample_date} (Turno {clean_shift}) registrada en {sampling_point}. Humedad: {moisture_pct}%, Grasa: {fat_pct}%, Acidez: {acidity_pct}%. Obs: {notes}")

    # Retorna el resumen del analisis
    return {
        'id': analysis_id,
        'timestamp': now_str,
        'sample_date': clean_sample_date,
        'shift_id': clean_shift,
        'time_slot': time_slot,
        'sample_code': sample_code,
        'product': product,
        'press_number': press_number,
        'moisture_pct': moisture_pct,
        'fat_pct': fat_pct,
        'foreign_matter_pct': foreign_matter_pct,
        'acidity_pct': acidity_pct
    }

# Actualiza y ajusta un analisis historico con registro en bitacora de auditoria
def update_analysis(analysis_id, sampling_point, moisture_pct, fat_pct,
                    acidity_pct=None, foreign_matter_pct=None, notes='', press_number=None,
                    edit_reason='', operator_name=None, sample_code=None, product=None,
                    sample_date=None, shift_id=None):
    # Convierte humedad de manera segura
    m_val = safe_float(moisture_pct, default=None)
    # Convierte materia grasa de manera segura
    f_val = safe_float(fat_pct, default=None)
    # Convierte acidez de manera segura
    a_val = safe_float(acidity_pct, default=None)
    # Convierte materia extrana de manera segura
    fm_val = safe_float(foreign_matter_pct, default=None)
    # Convierte numero de prensa de manera segura
    p_num = safe_int(press_number, default=None)

    # Abre conexion para actualizar el registro
    with get_db_connection() as conn:
        # Consulta el valor anterior del analisis
        old = conn.execute("SELECT * FROM lab_analyses WHERE id = ?;", (analysis_id,)).fetchone()
        # Si no existe lanza excepcion
        if not old:
            # Lanza error
            raise ValueError(f"Análisis con ID #{analysis_id} no encontrado.")
        # Convierte fila anterior a diccionario
        old_dict = dict(old)

        # Determina nuevo codigo de muestra
        new_sample_code = sample_code if sample_code is not None else old_dict.get('sample_code')
        # Determina nuevo producto
        new_product = product if product is not None else old_dict.get('product')
        # Determina nueva fecha de muestra
        new_sample_date = str(sample_date).strip() if sample_date and str(sample_date).strip() else old_dict.get('sample_date')
        # Determina nuevo turno de muestra
        new_shift_id = str(shift_id).strip().upper() if shift_id and str(shift_id).strip() else old_dict.get('shift_id')

        # Ejecuta actualizacion en tabla lab_analyses
        conn.execute("""
            UPDATE lab_analyses
            SET sampling_point = ?, moisture_pct = ?, fat_pct = ?,
                acidity_pct = ?, foreign_matter_pct = ?, notes = ?, press_number = ?,
                sample_code = ?, product = ?, sample_date = ?, shift_id = ?
            WHERE id = ?;
        """, (sampling_point, m_val, f_val, a_val, fm_val, notes, p_num,
              new_sample_code, new_product, new_sample_date, new_shift_id, analysis_id))
        # Confirma cambios
        conn.commit()

    # Construye el detalle de cambios para auditoria
    details = (
        f"Edición de Análisis #{analysis_id} ({old_dict.get('sample_code', '-')}, {old_dict.get('product', '-')}). Motivo: '{edit_reason or 'Ajuste analítico'}'. "
        f"Antes: [Fecha={old_dict.get('sample_date')}, Turno={old_dict.get('shift_id')}, Punto={old_dict.get('sampling_point')}, H={old_dict.get('moisture_pct')}%, "
        f"MG={old_dict.get('fat_pct')}%, Acidez={old_dict.get('acidity_pct')}%, ME={old_dict.get('foreign_matter_pct')}%, Prensa={old_dict.get('press_number')}]. "
        f"Ahora: [Fecha={new_sample_date}, Turno={new_shift_id}, Punto={sampling_point}, H={m_val}%, "
        f"MG={f_val}%, Acidez={a_val}%, ME={fm_val}%, Prensa={p_num}]."
    )
    # Registra evento en bitacora de auditoria
    record_audit_event('LABORATORIO', 'EDICION_ANALISIS', details, user_override=operator_name)
    # Registra en log de informacion
    log_info('LAB', f"Análisis #{analysis_id} modificado por {operator_name or 'usuario'}: {details}")
    # Retorna verdadero
    return True

# Elimina una determinacion analitica de laboratorio con registro en auditoria
def delete_analysis(analysis_id, delete_reason='', operator_name=None):
    """
    Elimina un análisis de laboratorio y registra el evento en la bitácora de auditoría.
    """
    # Abre conexion a la base de datos
    with get_db_connection() as conn:
        # Busca el analisis antes de eliminarlo
        old = conn.execute("SELECT * FROM lab_analyses WHERE id = ?;", (analysis_id,)).fetchone()
        # Si no existe
        if not old:
            # Lanza error
            raise ValueError(f"Análisis con ID #{analysis_id} no encontrado.")
        # Convierte a diccionario
        old_dict = dict(old)

        # Elimina el registro por id
        conn.execute("DELETE FROM lab_analyses WHERE id = ?;", (analysis_id,))
        # Confirma transaccion
        conn.commit()

    # Construye detalle para auditoria
    details = (
        f"Análisis #{analysis_id} ({old_dict.get('sample_code', '-')}, {old_dict.get('product', '-')}) eliminado por {operator_name or 'usuario'}. "
        f"Motivo: '{delete_reason or 'Eliminación de análisis erróneo'}'. "
        f"Datos eliminados: [Fecha Muestra={old_dict.get('sample_date')}, Punto={old_dict.get('sampling_point')}, H={old_dict.get('moisture_pct')}%, "
        f"MG={old_dict.get('fat_pct')}%, Acidez={old_dict.get('acidity_pct')}%, "
        f"Turno={old_dict.get('shift_id')}, Carga={old_dict.get('timestamp')}]."
    )
    # Registra auditoria
    record_audit_event('LABORATORIO', 'ELIMINACION_ANALISIS', details, user_override=operator_name)
    # Registra en log
    log_info('LAB', details)
    # Retorna exito
    return True

# Obtiene los analisis recientes de laboratorio ordenados cronologicamente por fecha de muestra
def get_recent_analyses(product=None, limit=50):
    # Abre conexion a base de datos
    with get_db_connection() as conn:
        # Si se filtro por producto
        if product:
            # Consulta filtrada por producto ordenando por fecha de muestra y estampa
            rows = conn.execute("""
                SELECT * FROM lab_analyses
                WHERE product = ?
                ORDER BY COALESCE(sample_date, date(timestamp)) DESC, timestamp DESC
                LIMIT ?;
            """, (product, limit)).fetchall()
        # Si no se filtro producto
        else:
            # Consulta todos los analisis ordenados por fecha de muestra
            rows = conn.execute("""
                SELECT * FROM lab_analyses
                ORDER BY COALESCE(sample_date, date(timestamp)) DESC, timestamp DESC
                LIMIT ?;
            """, (limit,)).fetchall()
        # Retorna lista de diccionarios
        return [dict(row) for row in rows]

# Obtiene los parametros analiticos promedio de calidad para un turno y fecha de muestra
def get_shift_lab_averages(shift_id=None, target_date=None):
    # Normaliza la fecha de muestra objetivo o usa la fecha actual de planta
    clean_target_date = str(target_date).strip() if target_date and str(target_date).strip() else get_plant_today_str()
    # Abre conexion a base de datos
    with get_db_connection() as conn:
        # Inicializa filas de consulta
        seed_row = None
        # Fila Prensa 2 turno
        exp_p2_shift_row = None
        # Fila Prensa 1 turno
        exp_p1_shift_row = None
        # Fila aceite turno
        oil_row = None

        # Si se paso un turno en particular, calcula las muestras de esa fecha y turno
        if shift_id:
            # Consulta semilla para la fecha de muestra y turno especificados
            seed_row = conn.execute("""
                SELECT AVG(fat_pct) as avg_fat, AVG(moisture_pct) as avg_moist, AVG(foreign_matter_pct) as avg_fm
                FROM lab_analyses
                WHERE shift_id = ? AND product = 'semilla'
                  AND COALESCE(sample_date, date(timestamp)) = ?;
            """, (shift_id, clean_target_date)).fetchone()

            # Si no hubo muestras en esa fecha de muestra, busca promedio global del turno
            if not seed_row or seed_row['avg_fat'] is None:
                # Consulta promedio del turno sin filtrar fecha
                seed_row = conn.execute("""
                    SELECT AVG(fat_pct) as avg_fat, AVG(moisture_pct) as avg_moist, AVG(foreign_matter_pct) as avg_fm
                    FROM lab_analyses
                    WHERE shift_id = ? AND product = 'semilla';
                """, (shift_id,)).fetchone()

            # Prensa 2 (Relevante / Producto Final): busca muestras de la fecha y turno
            exp_p2_shift_row = conn.execute("""
                SELECT AVG(fat_pct) as avg_fat, AVG(moisture_pct) as avg_moist
                FROM lab_analyses
                WHERE shift_id = ? AND product = 'expeller'
                  AND (press_number = 2 OR (press_number IS NULL AND LOWER(sampling_point) NOT LIKE '%prensa 1%' AND LOWER(sampling_point) NOT LIKE '%prensa1%' AND LOWER(sampling_point) NOT LIKE '%p1%'))
                  AND COALESCE(sample_date, date(timestamp)) = ?;
            """, (shift_id, clean_target_date)).fetchone()

            # Fallback a muestras globales del turno para Prensa 2 si no hay en la fecha
            if not exp_p2_shift_row or exp_p2_shift_row['avg_fat'] is None:
                # Consulta turno global
                exp_p2_shift_row = conn.execute("""
                    SELECT AVG(fat_pct) as avg_fat, AVG(moisture_pct) as avg_moist
                    FROM lab_analyses
                    WHERE shift_id = ? AND product = 'expeller'
                      AND (press_number = 2 OR (press_number IS NULL AND LOWER(sampling_point) NOT LIKE '%prensa 1%' AND LOWER(sampling_point) NOT LIKE '%prensa1%' AND LOWER(sampling_point) NOT LIKE '%p1%'));
                """, (shift_id,)).fetchone()

            # Prensa 1 (Indicativo preliminar) en la fecha y turno
            exp_p1_shift_row = conn.execute("""
                SELECT AVG(fat_pct) as avg_fat, AVG(moisture_pct) as avg_moist
                FROM lab_analyses
                WHERE shift_id = ? AND product = 'expeller'
                  AND (press_number = 1 OR (press_number IS NULL AND (LOWER(sampling_point) LIKE '%prensa 1%' OR LOWER(sampling_point) LIKE '%prensa1%' OR LOWER(sampling_point) LIKE '%p1%')))
                  AND COALESCE(sample_date, date(timestamp)) = ?;
            """, (shift_id, clean_target_date)).fetchone()

            # Fallback Prensa 1 al turno global
            if not exp_p1_shift_row or exp_p1_shift_row['avg_fat'] is None:
                # Consulta turno global Prensa 1
                exp_p1_shift_row = conn.execute("""
                    SELECT AVG(fat_pct) as avg_fat, AVG(moisture_pct) as avg_moist
                    FROM lab_analyses
                    WHERE shift_id = ? AND product = 'expeller'
                      AND (press_number = 1 OR (press_number IS NULL AND (LOWER(sampling_point) LIKE '%prensa 1%' OR LOWER(sampling_point) LIKE '%prensa1%' OR LOWER(sampling_point) LIKE '%p1%')));
                """, (shift_id,)).fetchone()

            # Aceite en la fecha y turno
            oil_row = conn.execute("""
                SELECT AVG(acidity_pct) as avg_acidity, AVG(moisture_pct) as avg_moist
                FROM lab_analyses
                WHERE shift_id = ? AND product = 'aceite'
                  AND COALESCE(sample_date, date(timestamp)) = ?;
            """, (shift_id, clean_target_date)).fetchone()

            # Fallback aceite al turno global
            if not oil_row or oil_row['avg_acidity'] is None:
                # Consulta turno global aceite
                oil_row = conn.execute("""
                    SELECT AVG(acidity_pct) as avg_acidity, AVG(moisture_pct) as avg_moist
                    FROM lab_analyses
                    WHERE shift_id = ? AND product = 'aceite';
                """, (shift_id,)).fetchone()

        # Fallbacks si en ese turno no hubo muestras del producto
        if not seed_row or seed_row['avg_fat'] is None:
            # Ultimo registro de semilla en planta
            seed_row = conn.execute("""
                SELECT fat_pct as avg_fat, moisture_pct as avg_moist, foreign_matter_pct as avg_fm
                FROM lab_analyses
                WHERE product = 'semilla'
                ORDER BY COALESCE(sample_date, date(timestamp)) DESC, timestamp DESC LIMIT 1;
            """).fetchone()

        # Fallback Prensa 2: ultimo registro de Prensa 2 en planta
        exp_p2_latest = conn.execute("""
            SELECT fat_pct as avg_fat, moisture_pct as avg_moist
            FROM lab_analyses
            WHERE product = 'expeller'
              AND (press_number = 2 OR (press_number IS NULL AND LOWER(sampling_point) NOT LIKE '%prensa 1%' AND LOWER(sampling_point) NOT LIKE '%prensa1%' AND LOWER(sampling_point) NOT LIKE '%p1%'))
            ORDER BY COALESCE(sample_date, date(timestamp)) DESC, timestamp DESC LIMIT 1;
        """).fetchone()

        # Fallback Prensa 1: ultimo registro de Prensa 1 en planta
        exp_p1_latest = conn.execute("""
            SELECT fat_pct as avg_fat, moisture_pct as avg_moist
            FROM lab_analyses
            WHERE product = 'expeller'
              AND (press_number = 1 OR (press_number IS NULL AND (LOWER(sampling_point) LIKE '%prensa 1%' OR LOWER(sampling_point) LIKE '%prensa1%' OR LOWER(sampling_point) LIKE '%p1%')))
            ORDER BY COALESCE(sample_date, date(timestamp)) DESC, timestamp DESC LIMIT 1;
        """).fetchone()

        # Fallback aceite: ultimo registro de aceite en planta
        if not oil_row or oil_row['avg_acidity'] is None:
            # Consulta ultimo analisis de aceite
            oil_row = conn.execute("""
                SELECT acidity_pct as avg_acidity, moisture_pct as avg_moist
                FROM lab_analyses
                WHERE product = 'aceite'
                ORDER BY COALESCE(sample_date, date(timestamp)) DESC, timestamp DESC LIMIT 1;
            """).fetchone()

        # Promedio del dia para Prensa 2 basado en la fecha de la muestra objetivo
        day_p2_row = conn.execute("""
            SELECT AVG(fat_pct) as avg_fat, AVG(moisture_pct) as avg_moist
            FROM lab_analyses
            WHERE product = 'expeller'
              AND (press_number = 2 OR (press_number IS NULL AND LOWER(sampling_point) NOT LIKE '%prensa 1%' AND LOWER(sampling_point) NOT LIKE '%prensa1%' AND LOWER(sampling_point) NOT LIKE '%p1%'))
              AND COALESCE(sample_date, date(timestamp)) = ?;
        """, (clean_target_date,)).fetchone()

        # Si en la fecha de muestra objetivo no hay muestras, fallback al dia del ultimo registro con muestras de Prensa 2
        if not day_p2_row or day_p2_row['avg_fat'] is None:
            # Consulta dia mas reciente con datos de Prensa 2
            day_p2_row = conn.execute("""
                SELECT AVG(fat_pct) as avg_fat, AVG(moisture_pct) as avg_moist
                FROM lab_analyses
                WHERE product = 'expeller'
                  AND (press_number = 2 OR (press_number IS NULL AND LOWER(sampling_point) NOT LIKE '%prensa 1%' AND LOWER(sampling_point) NOT LIKE '%prensa1%' AND LOWER(sampling_point) NOT LIKE '%p1%'))
                  AND COALESCE(sample_date, date(timestamp)) = (
                      SELECT COALESCE(sample_date, date(timestamp)) FROM lab_analyses
                      WHERE product = 'expeller' AND (press_number = 2 OR (press_number IS NULL AND LOWER(sampling_point) NOT LIKE '%prensa 1%' AND LOWER(sampling_point) NOT LIKE '%prensa1%' AND LOWER(sampling_point) NOT LIKE '%p1%'))
                      ORDER BY COALESCE(sample_date, date(timestamp)) DESC, timestamp DESC LIMIT 1
                  );
            """).fetchone()

        # Valores de Prensa 2 para cada uno de los 3 turnos de planta (TM, TT, TN) en la fecha objetivo
        shifts_p2 = {'TM': None, 'TT': None, 'TN': None}
        # Itera por los turnos oficiales
        for s_code in ['TM', 'TT', 'TN']:
            # Consulta promedio de grasa para ese turno en la fecha de muestra
            s_row = conn.execute("""
                SELECT AVG(fat_pct) as avg_fat
                FROM lab_analyses
                WHERE product = 'expeller'
                  AND shift_id = ?
                  AND (press_number = 2 OR (press_number IS NULL AND LOWER(sampling_point) NOT LIKE '%prensa 1%' AND LOWER(sampling_point) NOT LIKE '%prensa1%' AND LOWER(sampling_point) NOT LIKE '%p1%'))
                  AND COALESCE(sample_date, date(timestamp)) = ?;
            """, (s_code, clean_target_date)).fetchone()

            # Si no hubo muestras en esa fecha, busca el ultimo registro historico de ese turno
            if not s_row or s_row['avg_fat'] is None:
                # Consulta el ultimo disponible
                s_row = conn.execute("""
                    SELECT fat_pct as avg_fat
                    FROM lab_analyses
                    WHERE product = 'expeller'
                      AND shift_id = ?
                      AND (press_number = 2 OR (press_number IS NULL AND LOWER(sampling_point) NOT LIKE '%prensa 1%' AND LOWER(sampling_point) NOT LIKE '%prensa1%' AND LOWER(sampling_point) NOT LIKE '%p1%'))
                    ORDER BY COALESCE(sample_date, date(timestamp)) DESC, timestamp DESC LIMIT 1;
                """, (s_code,)).fetchone()

            # Si se obtuvo dato numerico
            if s_row and s_row['avg_fat'] is not None:
                # Redondea y almacena en diccionario
                shifts_p2[s_code] = round(float(s_row['avg_fat']), 2)

        # Calculo final de valores de Prensa 2 (Turno)
        if exp_p2_shift_row and exp_p2_shift_row['avg_fat'] is not None:
            # Grasa residual turno
            exp_fat_val = round(float(exp_p2_shift_row['avg_fat']), 2)
        # Fallback al ultimo de planta
        elif exp_p2_latest and exp_p2_latest['avg_fat'] is not None:
            # Grasa residual ultimo
            exp_fat_val = round(float(exp_p2_latest['avg_fat']), 2)
        # Valor estandar por defecto
        else:
            # 10 por ciento
            exp_fat_val = 10.0

        # Humedad Prensa 2 (Turno)
        if exp_p2_shift_row and exp_p2_shift_row['avg_moist'] is not None:
            # Humedad turno
            exp_moist_val = round(float(exp_p2_shift_row['avg_moist']), 2)
        # Fallback a ultimo de planta
        elif exp_p2_latest and exp_p2_latest['avg_moist'] is not None:
            # Humedad ultimo
            exp_moist_val = round(float(exp_p2_latest['avg_moist']), 2)
        # Valor estandar por defecto
        else:
            # 7.5 por ciento
            exp_moist_val = 7.5

        # Calculo de promedio del dia para Prensa 2
        if day_p2_row and day_p2_row['avg_fat'] is not None:
            # Asigna valor del dia
            exp_day_fat_val = round(float(day_p2_row['avg_fat']), 2)
        # Fallback a valor del turno
        else:
            # Asigna valor de turno
            exp_day_fat_val = exp_fat_val

        # Calculo indicativo de Prensa 1 (solo orientativo)
        exp_p1_fat_val = None
        # Si se obtuvo promedio para Prensa 1 en turno
        if exp_p1_shift_row and exp_p1_shift_row['avg_fat'] is not None:
            # Asigna valor
            exp_p1_fat_val = round(float(exp_p1_shift_row['avg_fat']), 2)
        # Fallback al ultimo de planta
        elif exp_p1_latest and exp_p1_latest['avg_fat'] is not None:
            # Asigna ultimo valor
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
    qty_kg = safe_float(quantity_kg, 0.0)
    qty_tons = round(qty_kg / 1000.0, 3)
    tank_id = safe_int(tank_source_id, default=None)
    temp_c = safe_float(oil_temperature_c, default=None)
    acid_pct = safe_float(oil_acidity_pct, default=None)

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
