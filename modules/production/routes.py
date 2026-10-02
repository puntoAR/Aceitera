# Importa componentes de Flask para rutas, plantillas y JSON
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, g
# Importa decoradores de seguridad por rol
from core.security import roles_required
# Importa los metodos del servicio de produccion
from modules.production.service import (
    record_weighing, update_weighing, delete_weighing, get_recent_weighings,
    record_line_stop, update_line_stop, delete_line_stop, get_shift_stops, get_shift_speed_summary
)
# Importa el servicio de configuracion para obtener el turno activo
from modules.configuration.service import get_active_shift
# Importa el logger para registrar eventos
from core.error_logger import log_error
# Importa auditoria de eventos
from core.audit import record_audit_event
# Importa utilidades de conversion numerica segura
from core.utils import safe_float
# Importa funcion horaria oficial de fecha de planta
from core.timezone import get_plant_today_str

# Define el Blueprint para produccion
production_bp = Blueprint('production', __name__, url_prefix='/production')

# Vista principal del modulo de produccion para operarios de linea
@production_bp.route('/', methods=['GET'])
# Requiere rol de usuario o administrador de sistema
@roles_required('usuario', 'admin_sistema')
# Controlador de vista principal
def index():
    # Obtiene el turno activo actual
    active_shift = get_active_shift()
    # Obtiene la fecha oficial de planta
    plant_today = get_plant_today_str()
    # Extrae la fecha objetivo del query param o usa la de hoy
    target_date = request.args.get('target_date', plant_today)
    # Bandera para consultar todas las paradas o unicamente las de la fecha en curso
    show_all_stops = request.args.get('all_stops', '0') == '1'
    # Obtiene las ultimas pesadas del turno activo ordenadas cronologicamente
    weighings = get_recent_weighings(shift_id=active_shift['shift_id'], limit=30)
    # Obtiene el resumen de velocidad y proyecciones filtradas por fecha de muestra
    summary = get_shift_speed_summary(shift_id=active_shift['shift_id'], target_date=target_date)
    # Obtiene las paradas registradas en la fecha operativa en curso (o todo el historial si se solicita)
    if show_all_stops:
        # Consulta historial completo sin filtro de fecha
        stops = get_shift_stops(target_date=None)
    # Si se visualiza el reporte normal
    else:
        # Filtra exclusivamente por la fecha en curso
        stops = get_shift_stops(target_date=target_date)
    # Renderiza la vista de produccion pasando fecha, turno y bandera de paradas
    return render_template('production.html', active_shift=active_shift,
                           weighings=weighings, summary=summary, stops=stops,
                           plant_today=plant_today, target_date=target_date,
                           show_all_stops=show_all_stops)

# Endpoint para registrar un nuevo muestreo de bolsa
@production_bp.route('/weighing', methods=['POST'])
# Requiere permisos de operario o administrador
@roles_required('usuario', 'admin_sistema')
# Controlador de insercion de pesada
def add_weighing():
    # Bloque de captura de errores
    try:
        # Extrae turno de la muestra del formulario
        shift_id = request.form.get('shift_id')
        # Extrae fecha de la toma de muestra del formulario
        sample_date = request.form.get('sample_date')
        # Extrae nombre del operario enviado en el formulario
        form_operator = request.form.get('operator_name')
        # Prioriza el usuario autenticado en sesion para identificar fehacientemente quien carga la muestra
        if hasattr(g, 'user') and g.user and (g.user.get('full_name') or g.user.get('username')):
            # Si el formulario trajo un operario personalizado explicito
            if form_operator and form_operator not in ('Operario de Linea 1', 'Operario'):
                # Utiliza el operador explicito
                operator_name = form_operator
            # De lo contrario
            else:
                # Utiliza el nombre del usuario autenticado en la sesion
                operator_name = g.user.get('full_name') or g.user.get('username')
        # Caso sin sesion web activa
        else:
            # Utiliza el operador del formulario o fallback
            operator_name = form_operator or (active_shift.get('operator_name') if 'active_shift' in locals() and active_shift else None) or 'Operario'
        # Extrae punto de muestreo (semilla o expeller)
        sample_point = request.form.get('sample_point')
        # Extrae peso bruto
        gross_weight_kg = safe_float(request.form.get('gross_weight_kg'), 0.0)
        # Extrae tara del recipiente
        tare_weight_kg = safe_float(request.form.get('tare_weight_kg'), 0.0)
        # Extrae tiempo de llenado en segundos
        fill_time_seconds = safe_float(request.form.get('fill_time_seconds'), 0.0)
        # Extrae estado de operacion de linea
        line_status = request.form.get('line_status', 'operando')
        # Extrae notas u observaciones
        notes = request.form.get('notes', '')
        # Registra la pesada mediante el servicio asociando fecha y turno de origen
        result = record_weighing(
            shift_id=shift_id,
            operator_name=operator_name,
            sample_point=sample_point,
            gross_weight_kg=gross_weight_kg,
            tare_weight_kg=tare_weight_kg,
            fill_time_seconds=fill_time_seconds,
            line_status=line_status,
            notes=notes,
            sample_date=sample_date
        )
        # Registra pesada en auditoria
        record_audit_event('PRODUCCION', 'PESADA_REGISTRADA', f"Pesada en {sample_point} (Muestra: {result.get('sample_date')} - {result.get('shift_id')}): {gross_weight_kg - tare_weight_kg:.2f} kg en {fill_time_seconds:.1f}s -> {result['speed_kg_h']} kg/h.", user_override=operator_name)
        # Notifica exito al operario
        flash(f'Pesada de {sample_point} registrada con éxito por {operator_name} para la fecha {result.get("sample_date")}: {result["speed_kg_h"]} kg/h.', 'success')
    # Captura posibles excepciones durante el guardado
    except Exception as e:
        # Registra error en log
        log_error('PRODUCTION_ROUTE', 'Error al registrar pesada de linea', e)
        # Notifica error al usuario
        flash(f'Error al registrar pesada: {str(e)}', 'danger')
    # Redirige a la vista de produccion
    return redirect(url_for('production.index'))

# Endpoint para registrar una parada de linea
@production_bp.route('/stop', methods=['POST'])
@roles_required('usuario', 'admin_sistema', 'administrador', 'gerencia')
def add_stop():
    # Bloque de captura de errores
    try:
        # Extrae datos de la parada de forma segura
        shift_id = request.form.get('shift_id')
        stop_date = request.form.get('stop_date')
        duration_minutes = safe_float(request.form.get('duration_minutes'), 0.0)
        reason = request.form.get('reason', 'Mantenimiento / Despeje')
        # Extrae nombre de operario del formulario
        form_operator = request.form.get('operator_name')
        # Prioriza el usuario autenticado en sesion
        if hasattr(g, 'user') and g.user and (g.user.get('full_name') or g.user.get('username')):
            # Si el formulario trajo nombre explicito no generico
            if form_operator and form_operator not in ('Operario de Linea 1', 'Operario'):
                operator_name = form_operator
            else:
                operator_name = g.user.get('full_name') or g.user.get('username')
        else:
            operator_name = form_operator or 'Operario'
        # Registra la parada (si shift_id o stop_date no vienen, usa turno y fecha por defecto según hora)
        result = record_line_stop(
            shift_id=shift_id,
            duration_minutes=duration_minutes,
            reason=reason,
            operator_name=operator_name,
            stop_date=stop_date
        )
        # Registra parada en auditoria
        record_audit_event('PRODUCCION', 'PARADA_LINEA', f"Parada de {duration_minutes} min registrada en turno {result['shift_id']} ({result['start_time']}). Motivo: {reason}.", status='ADVERTENCIA', user_override=operator_name)
        # Emite notificacion de advertencia informativa
        flash(f"Parada de línea registrada ({duration_minutes} min en turno {result['shift_id']}): {reason}", 'warning')
    except Exception as e:
        # Registra error en log
        log_error('PRODUCTION_ROUTE', 'Error al registrar parada de linea', e)
        # Notifica error
        flash(f'Error al registrar parada: {str(e)}', 'danger')
    # Redirige a produccion
    return redirect(url_for('production.index'))

# Endpoint para editar una parada de linea historica
@production_bp.route('/stop/edit/<int:stop_id>', methods=['POST'])
@roles_required('usuario', 'admin_sistema', 'administrador', 'gerencia')
def edit_stop(stop_id):
    try:
        duration_minutes = safe_float(request.form.get('duration_minutes'), 0.0)
        reason = request.form.get('reason', '').strip()
        shift_id = request.form.get('shift_id')
        stop_date = request.form.get('stop_date')
        edit_reason = request.form.get('edit_reason', '').strip()
        # Extrae nombre de operario del formulario
        form_operator = request.form.get('operator_name')
        # Prioriza el usuario autenticado en la sesion
        if hasattr(g, 'user') and g.user and (g.user.get('full_name') or g.user.get('username')):
            # Si el formulario trajo operario especifico
            if form_operator and form_operator not in ('Operario de Linea 1', 'Operario'):
                op_name = form_operator
            else:
                op_name = g.user.get('full_name') or g.user.get('username')
        else:
            op_name = form_operator or 'Operario'

        if not edit_reason:
            flash('Debe especificar el motivo de la modificación para el registro de auditoría.', 'warning')
            return redirect(url_for('production.index'))

        update_line_stop(
            stop_id=stop_id,
            duration_minutes=duration_minutes,
            reason=reason,
            edit_reason=edit_reason,
            operator_name=op_name,
            shift_id=shift_id,
            stop_date=stop_date
        )
        flash(f'Parada #{stop_id} actualizada correctamente.', 'success')
    except Exception as e:
        log_error('PRODUCTION_ROUTE', f'Error al editar parada #{stop_id}', e)
        flash(f'Error al modificar parada: {str(e)}', 'danger')
    return redirect(url_for('production.index'))

# Endpoint para eliminar una parada de linea
@production_bp.route('/stop/delete/<int:stop_id>', methods=['POST'])
@roles_required('usuario', 'admin_sistema', 'administrador', 'gerencia')
def delete_stop_route(stop_id):
    try:
        delete_reason = request.form.get('delete_reason', '').strip()
        # Extrae operador del formulario
        form_operator = request.form.get('operator_name')
        # Prioriza el usuario autenticado en la sesion
        if hasattr(g, 'user') and g.user and (g.user.get('full_name') or g.user.get('username')):
            if form_operator and form_operator not in ('Operario de Linea 1', 'Operario'):
                op_name = form_operator
            else:
                op_name = g.user.get('full_name') or g.user.get('username')
        else:
            op_name = form_operator or 'Operario'

        if not delete_reason:
            flash('Debe especificar el motivo de la eliminación para el registro de auditoría.', 'warning')
            return redirect(url_for('production.index'))

        delete_line_stop(stop_id=stop_id, delete_reason=delete_reason, operator_name=op_name)
        flash(f'Parada #{stop_id} eliminada correctamente. Trazabilidad registrada en auditoría.', 'success')
    except Exception as e:
        log_error('PRODUCTION_ROUTE', f'Error al eliminar parada #{stop_id}', e)
        flash(f'Error al eliminar parada: {str(e)}', 'danger')
    return redirect(url_for('production.index'))

# API JSON para actualizar graficos en tiempo real desde JavaScript
@production_bp.route('/api/shift-summary', methods=['GET'])
# Requiere rol operativo o administrador
@roles_required('usuario', 'admin_sistema')
# Controlador de api de resumen de turno
def api_shift_summary():
    # Obtiene el turno activo
    active_shift = get_active_shift()
    # Obtiene la fecha objetivo desde los parametros o usa la fecha oficial de planta
    target_date = request.args.get('target_date', get_plant_today_str())
    # Obtiene el resumen del turno activo para la fecha dada
    summary = get_shift_speed_summary(shift_id=active_shift['shift_id'], target_date=target_date)
    # Obtiene las ultimas 20 pesadas
    weighings = get_recent_weighings(shift_id=active_shift['shift_id'], limit=20)
    # Retorna respuesta en formato JSON
    return jsonify({'summary': summary, 'weighings': weighings})

# Endpoint para editar y ajustar una pesada existente con trazabilidad
@production_bp.route('/weighing/edit/<int:weighing_id>', methods=['POST'])
# Requiere roles autorizados
@roles_required('usuario', 'admin_sistema', 'administrador', 'gerencia')
# Controlador de edicion de pesada
def edit_weighing(weighing_id):
    # Captura de errores en edicion
    try:
        # Extrae punto de muestreo
        sample_point = request.form.get('sample_point')
        # Extrae fecha de la toma de muestra
        sample_date = request.form.get('sample_date')
        # Extrae turno al que pertenece la muestra
        shift_id = request.form.get('shift_id')
        # Extrae peso bruto
        gross_weight_kg = safe_float(request.form.get('gross_weight_kg'), 0.0)
        # Extrae peso de la tara
        tare_weight_kg = safe_float(request.form.get('tare_weight_kg'), 0.0)
        # Extrae tiempo de llenado
        fill_time_seconds = safe_float(request.form.get('fill_time_seconds'), 0.0)
        # Extrae estado de linea
        line_status = request.form.get('line_status', 'operando')
        # Extrae notas u observaciones
        notes = request.form.get('notes', '').strip()
        # Extrae justificacion obligatoria del cambio
        edit_reason = request.form.get('edit_reason', '').strip()
        # Extrae operador del formulario
        form_operator = request.form.get('operator_name')
        # Prioriza el usuario autenticado en sesion para auditoria y asignacion
        if hasattr(g, 'user') and g.user and (g.user.get('full_name') or g.user.get('username')):
            if form_operator and form_operator not in ('Operario de Linea 1', 'Operario'):
                op_name = form_operator
            else:
                op_name = g.user.get('full_name') or g.user.get('username')
        else:
            op_name = form_operator or 'Operario'

        # Valida que se haya ingresado motivo de auditoria
        if not edit_reason:
            # Notifica requerimiento
            flash('Debe especificar el motivo de la modificación para el registro de auditoría.', 'warning')
            # Redirige a produccion
            return redirect(url_for('production.index'))

        # Actualiza el registro de pesada con los nuevos valores y trazabilidad
        update_weighing(
            weighing_id=weighing_id,
            sample_point=sample_point,
            gross_weight_kg=gross_weight_kg,
            tare_weight_kg=tare_weight_kg,
            fill_time_seconds=fill_time_seconds,
            line_status=line_status,
            notes=notes,
            edit_reason=edit_reason,
            operator_name=op_name,
            sample_date=sample_date,
            shift_id=shift_id
        )
        # Notifica exito en modificacion
        flash(f'Pesada #{weighing_id} actualizada correctamente. Modificación registrada en auditoría.', 'success')
    # Captura errores en ejecucion
    except Exception as e:
        # Registra error en log
        log_error('PRODUCTION_ROUTE', f'Error al editar pesada #{weighing_id}', e)
        # Notifica fallo al usuario
        flash(f'Error al modificar pesada: {str(e)}', 'danger')
    # Redirige a la vista de produccion
    return redirect(url_for('production.index'))

# Endpoint para eliminar una pesada historica
@production_bp.route('/weighing/delete/<int:weighing_id>', methods=['POST'])
@roles_required('usuario', 'admin_sistema', 'administrador', 'gerencia')
def delete_weighing_route(weighing_id):
    try:
        delete_reason = request.form.get('delete_reason', '').strip()
        # Extrae operador del formulario
        form_operator = request.form.get('operator_name')
        # Prioriza el usuario autenticado en la sesion
        if hasattr(g, 'user') and g.user and (g.user.get('full_name') or g.user.get('username')):
            if form_operator and form_operator not in ('Operario de Linea 1', 'Operario'):
                op_name = form_operator
            else:
                op_name = g.user.get('full_name') or g.user.get('username')
        else:
            op_name = form_operator or 'Operario'

        if not delete_reason:
            flash('Debe especificar el motivo de la eliminación para el registro de auditoría.', 'warning')
            return redirect(url_for('production.index'))

        delete_weighing(weighing_id=weighing_id, delete_reason=delete_reason, operator_name=op_name)
        flash(f'Pesada #{weighing_id} eliminada correctamente. Registro de auditoría guardado.', 'success')
    except Exception as e:
        log_error('PRODUCTION_ROUTE', f'Error al eliminar pesada #{weighing_id}', e)
        flash(f'Error al eliminar pesada: {str(e)}', 'danger')
    return redirect(url_for('production.index'))
