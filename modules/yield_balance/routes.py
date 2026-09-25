# Importa componentes de Flask
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
# Importa autorizacion por roles
from core.security import roles_required
# Importa metodos de servicio de rendimiento
from modules.yield_balance.service import reconcile_shift, get_recent_reconciliations
# Importa turno activo y promedios de laboratorio y produccion
from modules.configuration.service import get_active_shift
from modules.production.service import get_shift_speed_summary
from modules.laboratory.service import get_shift_lab_averages
# Importa logger
from core.error_logger import log_error
# Importa auditoria
from core.audit import record_audit_event

# Define Blueprint de rendimiento y balance
yield_bp = Blueprint('yield', __name__, url_prefix='/yield')

# Vista principal de rendimiento y balance de masa (autorizada para Gerencia en solo lectura y Admin de sistema)
@yield_bp.route('/', methods=['GET'])
# Permite acceso de visualizacion a administradores (gerencia) y administradores de sistema
@roles_required('gerencia', 'administrador', 'admin_sistema')
def index():
    # Obtiene turno activo
    active_shift = get_active_shift()
    # Obtiene el resumen de velocidades y produccion estimada del turno
    prod_summary = get_shift_speed_summary(active_shift['shift_id'])
    # Obtiene las medias de laboratorio para materia grasa
    lab_averages = get_shift_lab_averages(active_shift['shift_id'])
    # Obtiene historial de conciliaciones
    reconciliations = get_recent_reconciliations(limit=15)
    # Renderiza plantilla de rendimiento
    return render_template('yield.html', active_shift=active_shift,
                           prod_summary=prod_summary, lab_averages=lab_averages,
                           reconciliations=reconciliations)

# Endpoint para procesar y guardar la conciliacion de turno
@yield_bp.route('/reconcile', methods=['POST'])
@roles_required('admin_sistema')
def add_reconciliation():
    # Bloque de captura de errores
    try:
        # Extrae valores del formulario
        shift_id = request.form.get('shift_id')
        seed_processed_kg = float(request.form.get('seed_processed_kg', 0.0))
        expeller_produced_kg = float(request.form.get('expeller_produced_kg', 0.0))
        oil_produced_kg = float(request.form.get('oil_produced_kg', 0.0))
        seed_fat_pct = float(request.form.get('seed_fat_pct', 45.0))
        expeller_fat_pct = float(request.form.get('expeller_fat_pct', 10.0))
        identified_waste_kg = float(request.form.get('identified_waste_kg', 0.0))
        moisture_loss_kg = float(request.form.get('moisture_loss_kg', 0.0))
        notes = request.form.get('notes', '')
        # Ejecuta la conciliacion
        result = reconcile_shift(
            shift_id, seed_processed_kg, expeller_produced_kg, oil_produced_kg,
            seed_fat_pct, expeller_fat_pct, identified_waste_kg, moisture_loss_kg, notes
        )
        # Registra en auditoria
        record_audit_event('RENDIMIENTO', 'CONCILIACION_TURNO', f"Conciliación turno {shift_id}: Semilla {seed_processed_kg} kg, Aceite {oil_produced_kg} kg (Rend: {result['oil_yield_pct']}%, Rec: {result['oil_recovery_pct']}%).")
        # Notifica exito
        flash(f'Conciliación guardada: Extracción {result["oil_yield_pct"]}%, Recuperación {result["oil_recovery_pct"]}%.', 'success')
    except Exception as e:
        # Registra error en log
        log_error('YIELD_ROUTE', 'Error al conciliar turno', e)
        # Notifica error
        flash(f'Error al procesar conciliación: {str(e)}', 'danger')
    # Redirige a la vista de rendimiento
    return redirect(url_for('yield.index'))
