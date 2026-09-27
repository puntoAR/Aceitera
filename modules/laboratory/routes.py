# Importa componentes de Flask
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
# Importa decorador de autorizacion por roles
from core.security import roles_required
# Importa metodos del servicio de laboratorio y despacho de camiones
from modules.laboratory.service import (
    record_analysis, get_recent_analyses, get_shift_lab_averages,
    record_oil_truck_dispatch, get_recent_oil_truck_dispatches
)
# Importa turno activo y lista de tanques de aceite
from modules.configuration.service import get_active_shift, get_all_tanks
# Importa registrador de errores
from core.error_logger import log_error
# Importa modulo de auditoria
from core.audit import record_audit_event

# Define Blueprint de laboratorio
laboratory_bp = Blueprint('laboratory', __name__, url_prefix='/laboratory')

# Vista principal del modulo de laboratorio y control de cargas de aceite
@laboratory_bp.route('/', methods=['GET'])
@roles_required('usuario', 'admin_sistema')
def index():
    # Obtiene turno activo
    active_shift = get_active_shift()
    # Obtiene ultimos analisis registrados
    analyses = get_recent_analyses(limit=30)
    # Obtiene promedios de calidad del turno activo
    averages = get_shift_lab_averages(active_shift['shift_id'])
    # Obtiene los tanques activos para seleccionar origen de carga de aceite
    tanks = get_all_tanks(only_active=True)
    # Obtiene los despachos de camiones recientes
    dispatches = get_recent_oil_truck_dispatches(limit=30)
    # Renderiza plantilla de laboratorio con analisis y despachos
    return render_template(
        'laboratory.html',
        active_shift=active_shift,
        analyses=analyses,
        averages=averages,
        tanks=tanks,
        dispatches=dispatches
    )

# Endpoint para registrar un nuevo analisis analitico (directo o gravimetrico)
@laboratory_bp.route('/add', methods=['POST'])
@roles_required('usuario', 'admin_sistema')
def add_analysis():
    # Bloque de captura de errores
    try:
        # Extrae datos basicos del formulario
        sample_code = request.form.get('sample_code', 'M-001').strip()
        product = request.form.get('product', 'semilla').strip()
        press_number = request.form.get('press_number')
        sampling_point = request.form.get('sampling_point', 'Tolva de Ingreso').strip()
        shift_id = request.form.get('shift_id')
        operator_name = request.form.get('operator_name')
        notes = request.form.get('notes', '').strip()

        # Construye el diccionario de datos combinando entrada rapida directa (%) y gravimetrica
        raw_data = {
            # Entrada rapida directa en porcentaje
            'direct_moisture_pct': request.form.get('direct_moisture_pct'),
            'direct_fat_pct': request.form.get('direct_fat_pct'),
            'direct_acidity_pct': request.form.get('direct_acidity_pct'),
            'direct_fm_pct': request.form.get('direct_fm_pct'),
            # Datos brutos de laboratorio gravimetrico
            'moisture_initial_g': request.form.get('moisture_initial_g'),
            'moisture_dry_g': request.form.get('moisture_dry_g'),
            'moisture_tare_g': request.form.get('moisture_tare_g'),
            'fat_sample_g': request.form.get('fat_sample_g'),
            'fat_final_flask_g': request.form.get('fat_final_flask_g'),
            'fat_tare_flask_g': request.form.get('fat_tare_flask_g'),
            'fm_sample_g': request.form.get('fm_sample_g'),
            'fm_impurities_g': request.form.get('fm_impurities_g'),
            'acidity_sample_g': request.form.get('acidity_sample_g'),
            'acidity_naoh_ml': request.form.get('acidity_naoh_ml')
        }

        # Registra el analisis mediante el servicio de laboratorio
        result = record_analysis(sample_code, product, sampling_point, shift_id, operator_name, raw_data, notes, press_number=press_number)
        # Notifica exito al analista especificando si es Prensa 1 o 2
        press_label = f" (Prensa {result.get('press_number')})" if result.get('press_number') else ""
        flash(f'Análisis de {result.get("product", product)}{press_label} ({sample_code}) guardado exitosamente.', 'success')
    except Exception as e:
        # Registra error en log
        log_error('LAB_ROUTE', 'Error al registrar analisis de laboratorio', e)
        # Notifica error
        flash(f'Error al registrar analisis: {str(e)}', 'danger')
    # Redirige a laboratorio
    return redirect(url_for('laboratory.index'))

# Endpoint para registrar el control de carga y precintado de camiones de aceite
@laboratory_bp.route('/truck-dispatch', methods=['POST'])
@roles_required('usuario', 'admin_sistema')
def add_truck_dispatch():
    # Bloque para capturar excepciones
    try:
        # Extrae datos del transporte
        shift_id = request.form.get('shift_id')
        operator_name = request.form.get('operator_name')
        truck_plate = request.form.get('truck_plate')
        trailer_plate = request.form.get('trailer_plate', '')
        driver_name = request.form.get('driver_name')
        driver_dni = request.form.get('driver_dni', '')
        transport_company = request.form.get('transport_company', '')
        destination = request.form.get('destination', '')
        tank_source_id = request.form.get('tank_source_id')
        quantity_kg = request.form.get('quantity_kg', 0.0)
        transport_status = request.form.get('transport_status', 'Apto para Carga')
        seals_numbers = request.form.get('seals_numbers', '')
        sample_delivered = request.form.get('sample_delivered', 'NO')
        sample_code = request.form.get('sample_code', '')
        oil_temperature_c = request.form.get('oil_temperature_c')
        oil_acidity_pct = request.form.get('oil_acidity_pct')
        notes = request.form.get('notes', '')

        # Registra la carga y despacho mediante el servicio
        result = record_oil_truck_dispatch(
            shift_id=shift_id,
            operator_name=operator_name,
            truck_plate=truck_plate,
            trailer_plate=trailer_plate,
            driver_name=driver_name,
            driver_dni=driver_dni,
            transport_company=transport_company,
            destination=destination,
            tank_source_id=tank_source_id,
            quantity_kg=quantity_kg,
            transport_status=transport_status,
            seals_numbers=seals_numbers,
            sample_delivered=sample_delivered,
            sample_code=sample_code,
            oil_temperature_c=oil_temperature_c,
            oil_acidity_pct=oil_acidity_pct,
            notes=notes
        )

        # Emite notificacion de exito con resumen de despacho
        flash(f"Despacho de camión cisterna {result['truck_plate']} ({result['driver_name']}) registrado con éxito. Estado: {result['transport_status']}. Precintos: {result['seals_numbers']}.", 'success')
    except Exception as e:
        # Registra fallo en log de errores
        log_error('LAB_ROUTE_DISPATCH', 'Error al registrar carga de camion de aceite', e)
        # Notifica al usuario
        flash(f'Error al registrar carga de camión: {str(e)}', 'danger')

    # Redirige a la pantalla de laboratorio
    return redirect(url_for('laboratory.index'))
