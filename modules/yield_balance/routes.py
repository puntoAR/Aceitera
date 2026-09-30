# Importa componentes de Flask
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
# Importa autorizacion por roles
from core.security import roles_required
# Importa metodos de servicio de rendimiento y balance
from modules.yield_balance.service import (
    reconcile_shift, get_recent_reconciliations, get_auto_efficiency_data,
    calculate_custom_efficiency, save_auto_reconciliation
)
from modules.calculations.yield_calc import calculate_line_yield_and_oil_efficiency
# Importa turno activo y promedios de laboratorio y produccion
from modules.configuration.service import get_active_shift
from modules.production.service import get_shift_speed_summary
from modules.laboratory.service import get_shift_lab_averages
# Importa logger
from core.error_logger import log_error
# Importa auditoria
from core.audit import record_audit_event
# Importa utilidades de conversion numerica segura
# Importa utilidades de conversion numerica segura
from core.utils import safe_float
# Importa funcion horaria oficial de fecha de planta
from core.timezone import get_plant_today_str

# Define Blueprint de rendimiento y balance
yield_bp = Blueprint('yield', __name__, url_prefix='/yield')

# Vista principal de rendimiento y balance de masa (autorizada para Gerencia y Admin de sistema)
@yield_bp.route('/', methods=['GET'])
# Permite acceso de visualizacion a administradores (gerencia) y administradores de sistema
@roles_required('gerencia', 'administrador', 'admin_sistema')
# Controlador de vista de rendimiento
def index():
    # Obtiene turno activo
    active_shift = get_active_shift()
    # Obtiene la fecha oficial de planta
    plant_today = get_plant_today_str()
    # Extrae la fecha objetivo desde los parametros o usa la fecha oficial
    target_date = request.args.get('target_date', plant_today)
    # Obtiene el resumen de velocidades y produccion estimada del turno para la fecha
    prod_summary = get_shift_speed_summary(active_shift['shift_id'], target_date=target_date)
    # Obtiene las medias de laboratorio para materia grasa para la fecha
    lab_averages = get_shift_lab_averages(active_shift['shift_id'], target_date=target_date)
    # Calcula la eficiencia y rendimientos en forma automatica a partir de la informacion registrada en el sistema
    auto_efficiency = get_auto_efficiency_data(active_shift['shift_id'], target_date=target_date)
    # Calcula el rendimiento de linea y eficiencia de extraccion cruzando caudales con analitica de laboratorio
    line_yield_info = calculate_line_yield_and_oil_efficiency(
        seed_speed_kg_h=prod_summary.get('seed_avg_speed', 0.0),
        expeller_speed_kg_h=prod_summary.get('expeller_avg_speed', 0.0),
        seed_fat_pct=lab_averages.get('seed_fat_pct', 45.0),
        expeller_fat_pct=lab_averages.get('expeller_fat_pct', 10.0)
    )
    # Obtiene historial de conciliaciones
    reconciliations = get_recent_reconciliations(limit=15)
    # Renderiza plantilla de rendimiento con el juego automatico y el simulador de datos
    return render_template('yield.html', active_shift=active_shift,
                           prod_summary=prod_summary, lab_averages=lab_averages,
                           auto_efficiency=auto_efficiency,
                           line_yield_info=line_yield_info,
                           reconciliations=reconciliations,
                           plant_today=plant_today, target_date=target_date)

# Endpoint para procesar y guardar la conciliacion con juego de datos ingresado por el usuario
@yield_bp.route('/reconcile', methods=['POST'])
@roles_required('admin_sistema')
def add_reconciliation():
    # Bloque de captura de errores
    try:
        # Extrae identificador de guardia o turno
        shift_id = request.form.get('shift_id')
        # Extrae valores del formulario de forma segura
        seed_processed_kg = safe_float(request.form.get('seed_processed_kg'), 0.0)
        # Extrae expeller producido de forma segura
        expeller_produced_kg = safe_float(request.form.get('expeller_produced_kg'), 0.0)
        # Extrae entrada de aceite
        oil_input = request.form.get('oil_produced_kg')
        # Si el usuario no especifico el aceite obtenido, se calcula por diferencia
        if oil_input and str(oil_input).strip():
            # Convierte valor ingresado de forma segura
            oil_produced_kg = safe_float(oil_input, 0.0)
        # Rama diferencial si no se ingreso aceite
        else:
            # Estima aceite por diferencia de masa
            oil_produced_kg = max(0.0, seed_processed_kg - expeller_produced_kg)
        # Extrae porcentaje de materia grasa en semilla
        seed_fat_pct = safe_float(request.form.get('seed_fat_pct'), 45.0)
        # Extrae porcentaje de materia grasa en expeller
        expeller_fat_pct = safe_float(request.form.get('expeller_fat_pct'), 10.0)
        # Extrae residuos identificados
        identified_waste_kg = safe_float(request.form.get('identified_waste_kg'), 0.0)
        # Extrae merma de evaporacion
        moisture_loss_kg = safe_float(request.form.get('moisture_loss_kg'), 0.0)
        notes = request.form.get('notes', '')
        # Ejecuta la conciliacion
        result = reconcile_shift(
            shift_id, seed_processed_kg, expeller_produced_kg, oil_produced_kg,
            seed_fat_pct, expeller_fat_pct, identified_waste_kg, moisture_loss_kg, notes
        )
        # Registra en auditoria
        record_audit_event('RENDIMIENTO', 'CONCILIACION_TURNO', f"Conciliación turno {shift_id}: Semilla {seed_processed_kg} kg, Aceite {oil_produced_kg} kg (Rend: {result['oil_yield_pct']}%, Rec: {result['oil_recovery_pct']}%).")
        # Notifica exito
        flash(f'Conciliación guardada exitosamente: Extracción {result["oil_yield_pct"]}%, Recuperación {result["oil_recovery_pct"]}%.', 'success')
    except Exception as e:
        # Registra error en log
        log_error('YIELD_ROUTE', 'Error al conciliar turno', e)
        # Notifica error
        flash(f'Error al procesar conciliación: {str(e)}', 'danger')
    # Redirige a la vista de rendimiento
    return redirect(url_for('yield.index'))

# Endpoint para guardar directamente el balance y eficiencia generados automaticamente
@yield_bp.route('/save-auto', methods=['POST'])
@roles_required('admin_sistema')
def save_auto_route():
    # Bloque de captura de errores
    try:
        # Obtiene notas opcionales del formulario
        notes = request.form.get('notes', '')
        # Guarda el balance automatico a partir de los datos registrados
        res = save_auto_reconciliation(notes=notes)
        # Registra en auditoria
        record_audit_event('RENDIMIENTO', 'BALANCE_AUTOMATICO', f"Balance automático guardado para {res['date_shift']}: Rend Aceite {res['oil_yield_pct']}%, Recup {res['oil_recovery_pct']}%.")
        # Notifica exito con mensaje informativo
        flash(f'Balance automático guardado con éxito para {res["date_shift"]}. Recuperación: {res["oil_recovery_pct"]}%.', 'success')
    except Exception as e:
        # Registra error en log
        log_error('YIELD_AUTO', 'Error al guardar balance automatico', e)
        # Notifica error
        flash(f'Error al guardar balance automático: {str(e)}', 'danger')
    # Redirige al modulo de rendimiento
    return redirect(url_for('yield.index'))

# Endpoint API para calcular la eficiencia en tiempo real a partir de un juego de datos
@yield_bp.route('/api/calculate-custom', methods=['POST'])
@roles_required('gerencia', 'administrador', 'admin_sistema')
def api_calculate_custom():
    # Intenta obtener datos JSON o datos de formulario
    data = request.get_json(silent=True) or request.form
    # Extrae variables numericas
    seed_kg = float(data.get('seed_processed_kg', 0.0) or 0.0)
    expeller_kg = float(data.get('expeller_produced_kg', 0.0) or 0.0)
    oil_val = data.get('oil_produced_kg')
    oil_kg = float(oil_val) if oil_val and str(oil_val).strip() else None
    seed_fat = float(data.get('seed_fat_pct', 45.0) or 45.0)
    expeller_fat = float(data.get('expeller_fat_pct', 10.0) or 10.0)
    waste_kg = float(data.get('waste_kg', 0.0) or 0.0)
    moisture_kg = float(data.get('moisture_loss_kg', 0.0) or 0.0)
    # Ejecuta el calculo de eficiencia con el juego de datos provisto
    res = calculate_custom_efficiency(
        seed_processed_kg=seed_kg,
        expeller_produced_kg=expeller_kg,
        oil_produced_kg=oil_kg,
        seed_fat_pct=seed_fat,
        expeller_fat_pct=expeller_fat,
        waste_kg=waste_kg,
        moisture_loss_kg=moisture_kg
    )
    # Retorna la respuesta en formato JSON
    return jsonify(res)
