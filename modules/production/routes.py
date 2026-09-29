# Importa componentes de Flask para rutas, plantillas y JSON
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, g
# Importa decoradores de seguridad por rol
from core.security import roles_required
# Importa los metodos del servicio de produccion
from modules.production.service import (
    record_weighing, update_weighing, get_recent_weighings,
    record_line_stop, get_shift_stops, get_shift_speed_summary
)
# Importa el servicio de configuracion para obtener el turno activo
from modules.configuration.service import get_active_shift
# Importa el logger para registrar eventos
from core.error_logger import log_error
# Importa auditoria de eventos
from core.audit import record_audit_event
# Importa utilidades de conversion numerica segura
from core.utils import safe_float

# Define el Blueprint para produccion
production_bp = Blueprint('production', __name__, url_prefix='/production')

# Vista principal del modulo de produccion para operarios de linea
@production_bp.route('/', methods=['GET'])
@roles_required('usuario', 'admin_sistema')
def index():
    # Obtiene el turno activo actual
    active_shift = get_active_shift()
    # Obtiene las ultimas pesadas del turno activo
    weighings = get_recent_weighings(shift_id=active_shift['shift_id'], limit=30)
    # Obtiene el resumen de velocidad y proyecciones
    summary = get_shift_speed_summary(shift_id=active_shift['shift_id'])
    # Obtiene las paradas registradas en el turno
    stops = get_shift_stops(shift_id=active_shift['shift_id'])
    # Renderiza la vista de produccion
    return render_template('production.html', active_shift=active_shift,
                           weighings=weighings, summary=summary, stops=stops)

# Endpoint para registrar un nuevo muestreo de bolsa
@production_bp.route('/weighing', methods=['POST'])
@roles_required('usuario', 'admin_sistema')
def add_weighing():
    # Bloque de captura de errores
    try:
        # Extrae datos del formulario
        shift_id = request.form.get('shift_id')
        operator_name = request.form.get('operator_name')
        sample_point = request.form.get('sample_point')
        gross_weight_kg = safe_float(request.form.get('gross_weight_kg'), 0.0)
        tare_weight_kg = safe_float(request.form.get('tare_weight_kg'), 0.0)
        fill_time_seconds = safe_float(request.form.get('fill_time_seconds'), 0.0)
        line_status = request.form.get('line_status', 'operando')
        notes = request.form.get('notes', '')
        # Registra la pesada mediante el servicio
        result = record_weighing(
            shift_id, operator_name, sample_point, gross_weight_kg,
            tare_weight_kg, fill_time_seconds, line_status, notes
        )
        # Registra pesada en auditoria
        record_audit_event('PRODUCCION', 'PESADA_REGISTRADA', f"Pesada en {sample_point}: {gross_weight_kg - tare_weight_kg:.2f} kg en {fill_time_seconds:.1f}s -> {result['speed_kg_h']} kg/h.")
        # Notifica exito al operario
        flash(f'Pesada de {sample_point} registrada con éxito: {result["speed_kg_h"]} kg/h.', 'success')
    except Exception as e:
        # Registra error en log
        log_error('PRODUCTION_ROUTE', 'Error al registrar pesada de linea', e)
        # Notifica error al usuario
        flash(f'Error al registrar pesada: {str(e)}', 'danger')
    # Redirige a la vista de produccion
    return redirect(url_for('production.index'))

# Endpoint para registrar una parada de linea
@production_bp.route('/stop', methods=['POST'])
@roles_required('usuario', 'admin_sistema')
def add_stop():
    # Bloque de captura de errores
    try:
        # Extrae datos de la parada de forma segura
        shift_id = request.form.get('shift_id')
        duration_minutes = safe_float(request.form.get('duration_minutes'), 0.0)
        reason = request.form.get('reason', 'Mantenimiento / Despeje')
        operator_name = request.form.get('operator_name', 'Operario')
        # Registra la parada
        record_line_stop(shift_id, duration_minutes, reason, operator_name)
        # Registra parada en auditoria
        record_audit_event('PRODUCCION', 'PARADA_LINEA', f"Parada de {duration_minutes} min registrada en turno {shift_id}. Motivo: {reason}.", status='ADVERTENCIA')
        # Emite notificacion de advertencia informativa
        flash(f'Parada de línea registrada ({duration_minutes} min): {reason}', 'warning')
    except Exception as e:
        # Registra error en log
        log_error('PRODUCTION_ROUTE', 'Error al registrar parada de linea', e)
        # Notifica error
        flash(f'Error al registrar parada: {str(e)}', 'danger')
    # Redirige a produccion
    return redirect(url_for('production.index'))

# API JSON para actualizar graficos en tiempo real desde JavaScript
@production_bp.route('/api/shift-summary', methods=['GET'])
@roles_required('usuario', 'admin_sistema')
def api_shift_summary():
    # Obtiene el turno activo
    active_shift = get_active_shift()
    # Obtiene el resumen del turno activo
    summary = get_shift_speed_summary(shift_id=active_shift['shift_id'])
    # Obtiene las ultimas 20 pesadas
    weighings = get_recent_weighings(shift_id=active_shift['shift_id'], limit=20)
    # Retorna respuesta en formato JSON
    return jsonify({'summary': summary, 'weighings': weighings})

# Endpoint para editar y ajustar una pesada existente con trazabilidad
@production_bp.route('/weighing/edit/<int:weighing_id>', methods=['POST'])
@roles_required('usuario', 'admin_sistema', 'administrador', 'gerencia')
def edit_weighing(weighing_id):
    try:
        sample_point = request.form.get('sample_point')
        gross_weight_kg = safe_float(request.form.get('gross_weight_kg'), 0.0)
        tare_weight_kg = safe_float(request.form.get('tare_weight_kg'), 0.0)
        fill_time_seconds = safe_float(request.form.get('fill_time_seconds'), 0.0)
        line_status = request.form.get('line_status', 'operando')
        notes = request.form.get('notes', '').strip()
        edit_reason = request.form.get('edit_reason', '').strip()
        op_name = request.form.get('operator_name') or (g.user.get('full_name') if hasattr(g, 'user') and g.user else 'Operario')

        if not edit_reason:
            flash('Debe especificar el motivo de la modificación para el registro de auditoría.', 'warning')
            return redirect(url_for('production.index'))

        update_weighing(
            weighing_id=weighing_id,
            sample_point=sample_point,
            gross_weight_kg=gross_weight_kg,
            tare_weight_kg=tare_weight_kg,
            fill_time_seconds=fill_time_seconds,
            line_status=line_status,
            notes=notes,
            edit_reason=edit_reason,
            operator_name=op_name
        )
        flash(f'Pesada #{weighing_id} actualizada correctamente. Modificación registrada en auditoría.', 'success')
    except Exception as e:
        log_error('PRODUCTION_ROUTE', f'Error al editar pesada #{weighing_id}', e)
        flash(f'Error al modificar pesada: {str(e)}', 'danger')
    return redirect(url_for('production.index'))
