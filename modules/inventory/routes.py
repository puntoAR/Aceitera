# Importa componentes de Flask
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, g
# Importa decorador de autorizacion por roles
from core.security import roles_required
# Importa metodos del servicio de inventario
from modules.inventory.service import (
    record_tank_level, record_silo_measurement, record_inventory_movement, get_total_plant_stocks,
    get_recent_tank_readings, update_tank_reading, delete_tank_reading,
    get_recent_silo_readings, update_silo_reading, delete_silo_reading
)
# Importa metodos de configuracion para listar equipos
from modules.configuration.service import get_all_tanks, get_all_silos, get_active_shift
# Importa logger de errores
from core.error_logger import log_error
# Importa modulo de auditoria
from core.audit import record_audit_event
# Importa utilidades de parseo numerico seguro
from core.utils import safe_float, safe_int

# Define el Blueprint de inventario
inventory_bp = Blueprint('inventory', __name__, url_prefix='/inventory')

# Vista principal del modulo de cubicaje e inventario
@inventory_bp.route('/', methods=['GET'])
@roles_required('usuario', 'admin_sistema')
def index():
    # Obtiene existencias totales consolidadas
    stocks = get_total_plant_stocks()
    # Obtiene tanques activos para el formulario de carga
    tanks = get_all_tanks(only_active=True)
    # Obtiene silos activos para el formulario de carga
    silos = get_all_silos(only_active=True)
    # Obtiene el turno activo
    active_shift = get_active_shift()
    # Obtiene historico reciente de cubicajes
    recent_tank_readings = get_recent_tank_readings(limit=50)
    recent_silo_readings = get_recent_silo_readings(limit=50)
    # Renderiza la plantilla de inventario
    return render_template(
        'inventory.html',
        stocks=stocks,
        tanks=tanks,
        silos=silos,
        active_shift=active_shift,
        recent_tank_readings=recent_tank_readings,
        recent_silo_readings=recent_silo_readings
    )

# Endpoint para registrar medicion de nivel de tanque de aceite
@inventory_bp.route('/tank-reading', methods=['POST'])
@roles_required('usuario', 'admin_sistema')
def add_tank_reading():
    # Bloque de captura de errores
    try:
        # Extrae datos del formulario de forma segura
        tank_id = safe_int(request.form.get('tank_id'))
        level_m = safe_float(request.form.get('level_m'), 0.0)
        shift_id = request.form.get('shift_id')
        # Extrae operador del formulario
        form_operator = request.form.get('operator_name')
        # Prioriza usuario autenticado en la sesion
        if hasattr(g, 'user') and g.user and (g.user.get('full_name') or g.user.get('username')):
            if form_operator and form_operator not in ('Operario de Linea 1', 'Operario'):
                operator_name = form_operator
            else:
                operator_name = g.user.get('full_name') or g.user.get('username')
        else:
            operator_name = form_operator or 'Operario'
        density_override = safe_float(request.form.get('density_override'), default=None)
        if density_override is not None and density_override <= 0:
            density_override = None

        if not tank_id:
            raise ValueError("Debe seleccionar un tanque válido.")

        # Registra el nivel mediante el servicio
        result = record_tank_level(tank_id, level_m, shift_id, operator_name, density_override)
        # Registra en auditoria
        record_audit_event('INVENTARIO', 'CUBICAJE_TANQUE', f"Nivel registrado en {result['tank_code']}: {level_m}m -> {result['oil_kg']} kg ({result['liters']} L).", user_override=operator_name)
        # Notifica exito
        flash(f'Nivel en {result["tank_code"]} registrado: {result["oil_kg"]} kg de aceite ({result["liters"]} L).', 'success')
    except Exception as e:
        # Registra error en log
        log_error('INVENTORY_ROUTE', 'Error al registrar nivel de tanque', e)
        # Notifica error
        flash(f'Error al registrar medicion de tanque: {str(e)}', 'danger')
    # Redirige a inventario
    return redirect(url_for('inventory.index'))

# Endpoint para registrar cubicaje de un silo
@inventory_bp.route('/silo-reading', methods=['POST'])
@roles_required('usuario', 'admin_sistema')
def add_silo_reading():
    # Bloque de captura de excepciones
    try:
        # Extrae datos del formulario de forma segura
        silo_id = safe_int(request.form.get('silo_id'))
        covered_sheets = safe_float(request.form.get('covered_sheets'), 0.0)
        partial_sheet_h = safe_float(request.form.get('partial_sheet_height_m'), 0.0)
        cone_status = request.form.get('cone_occupied_status', 'lleno')
        copete_height_m = safe_float(request.form.get('copete_height_m'), 0.0)
        ph_override = safe_float(request.form.get('ph_override'), default=None)
        if ph_override is not None and ph_override <= 0:
            ph_override = None
        shift_id = request.form.get('shift_id')
        # Extrae operador del formulario
        form_operator = request.form.get('operator_name')
        # Prioriza usuario autenticado en la sesion
        if hasattr(g, 'user') and g.user and (g.user.get('full_name') or g.user.get('username')):
            if form_operator and form_operator not in ('Operario de Linea 1', 'Operario'):
                operator_name = form_operator
            else:
                operator_name = g.user.get('full_name') or g.user.get('username')
        else:
            operator_name = form_operator or 'Operario'

        if not silo_id:
            raise ValueError("Debe seleccionar un silo válido.")

        # Registra cubicaje de silo
        result = record_silo_measurement(
            silo_id, covered_sheets, partial_sheet_h, cone_status,
            copete_height_m, shift_id, operator_name, ph_override
        )
        # Registra en auditoria
        record_audit_event('INVENTARIO', 'CUBICAJE_SILO', f"Cubicaje registrado en {result['silo_code']}: {covered_sheets} chapas -> {result['stock_kg']} kg ({result['stock_tons']} Tn).", user_override=operator_name)
        # Notifica exito
        flash(f'Cubicaje en {result["silo_code"]} registrado: {result["stock_kg"]} kg ({result["stock_tons"]} Tn).', 'success')
    except Exception as e:
        # Registra error en log
        log_error('INVENTORY_ROUTE', 'Error al registrar cubicaje de silo', e)
        # Notifica error
        flash(f'Error al registrar cubicaje de silo: {str(e)}', 'danger')
    # Redirige a inventario
    return redirect(url_for('inventory.index'))

# Endpoint para registrar un movimiento de entrada o despacho
@inventory_bp.route('/movement', methods=['POST'])
@roles_required('usuario', 'admin_sistema')
def add_movement():
    # Bloque de captura de errores
    try:
        # Extrae datos del formulario de forma segura
        product = request.form.get('product')
        movement_type = request.form.get('movement_type')
        origin = request.form.get('origin', '')
        destination = request.form.get('destination', '')
        quantity_kg = safe_float(request.form.get('quantity_kg'), 0.0)
        document_ref = request.form.get('document_ref', '')
        shift_id = request.form.get('shift_id')
        # Extrae operador del formulario
        form_operator = request.form.get('operator_name')
        # Prioriza usuario autenticado en la sesion
        if hasattr(g, 'user') and g.user and (g.user.get('full_name') or g.user.get('username')):
            if form_operator and form_operator not in ('Operario de Linea 1', 'Operario'):
                operator_name = form_operator
            else:
                operator_name = g.user.get('full_name') or g.user.get('username')
        else:
            operator_name = form_operator or 'Operario'
        notes = request.form.get('notes', '')

        if not product or not movement_type:
            raise ValueError("Producto y tipo de movimiento son campos obligatorios.")

        # Registra el movimiento
        record_inventory_movement(product, movement_type, origin, destination, quantity_kg, document_ref, shift_id, operator_name, notes)
        # Registra en auditoria
        record_audit_event('INVENTARIO', 'MOVIMIENTO_STOCK', f"Movimiento {movement_type} de {quantity_kg} kg ({product}) doc: {document_ref}.", user_override=operator_name)
        # Notifica exito
        flash(f'Movimiento de {movement_type} de {quantity_kg} kg registrado exitosamente.', 'info')
    except Exception as e:
        # Registra error en log
        log_error('INVENTORY_ROUTE', 'Error al registrar movimiento', e)
        # Notifica error
        flash(f'Error al registrar movimiento: {str(e)}', 'danger')
    # Redirige a inventario
    return redirect(url_for('inventory.index'))

# API JSON de existencias para refresco dinamico del dashboard
@inventory_bp.route('/api/stocks', methods=['GET'])
@roles_required('usuario', 'gerencia', 'administrador', 'admin_sistema')
def api_stocks():
    # Retorna stocks en formato JSON
    return jsonify(get_total_plant_stocks())

# Endpoint para editar una medicion de tanque
@inventory_bp.route('/tank-reading/edit/<int:reading_id>', methods=['POST'])
@roles_required('usuario', 'admin_sistema', 'administrador', 'gerencia')
def edit_tank_reading(reading_id):
    try:
        level_m = safe_float(request.form.get('level_m'), 0.0)
        density_override = safe_float(request.form.get('density_override'), default=None)
        if density_override is not None and density_override <= 0:
            density_override = None
        edit_reason = request.form.get('edit_reason', '').strip()
        op_name = request.form.get('operator_name') or (g.user.get('full_name') if hasattr(g, 'user') and g.user else 'Operario')

        if not edit_reason:
            flash('Debe especificar el motivo del ajuste para el registro de auditoría.', 'warning')
            return redirect(url_for('inventory.index'))

        update_tank_reading(reading_id, level_m, density_override, edit_reason, op_name)
        flash(f'Medición de tanque #{reading_id} actualizada correctamente.', 'success')
    except Exception as e:
        log_error('INVENTORY_ROUTE', f'Error al editar medición de tanque #{reading_id}', e)
        flash(f'Error al modificar medición de tanque: {str(e)}', 'danger')
    return redirect(url_for('inventory.index'))

# Endpoint para eliminar una medicion de tanque
@inventory_bp.route('/tank-reading/delete/<int:reading_id>', methods=['POST'])
@roles_required('usuario', 'admin_sistema', 'administrador', 'gerencia')
def delete_tank_reading_route(reading_id):
    try:
        delete_reason = request.form.get('delete_reason', '').strip()
        op_name = request.form.get('operator_name') or (g.user.get('full_name') if hasattr(g, 'user') and g.user else 'Operario')

        if not delete_reason:
            flash('Debe especificar el motivo de la eliminación para el registro de auditoría.', 'warning')
            return redirect(url_for('inventory.index'))

        delete_tank_reading(reading_id, delete_reason, op_name)
        flash(f'Medición de tanque #{reading_id} eliminada. Existencias recalculadas.', 'success')
    except Exception as e:
        log_error('INVENTORY_ROUTE', f'Error al eliminar medición de tanque #{reading_id}', e)
        flash(f'Error al eliminar medición de tanque: {str(e)}', 'danger')
    return redirect(url_for('inventory.index'))

# Endpoint para editar un cubicaje de silo
@inventory_bp.route('/silo-reading/edit/<int:reading_id>', methods=['POST'])
@roles_required('usuario', 'admin_sistema', 'administrador', 'gerencia')
def edit_silo_reading(reading_id):
    try:
        covered_sheets = safe_float(request.form.get('covered_sheets'), 0.0)
        partial_sheet_h = safe_float(request.form.get('partial_sheet_height_m'), 0.0)
        cone_status = request.form.get('cone_occupied_status', 'lleno')
        copete_height_m = safe_float(request.form.get('copete_height_m'), 0.0)
        ph_override = safe_float(request.form.get('ph_override'), default=None)
        if ph_override is not None and ph_override <= 0:
            ph_override = None
        edit_reason = request.form.get('edit_reason', '').strip()
        op_name = request.form.get('operator_name') or (g.user.get('full_name') if hasattr(g, 'user') and g.user else 'Operario')

        if not edit_reason:
            flash('Debe especificar el motivo del ajuste para el registro de auditoría.', 'warning')
            return redirect(url_for('inventory.index'))

        update_silo_reading(reading_id, covered_sheets, partial_sheet_h, cone_status, copete_height_m, ph_override, edit_reason, op_name)
        flash(f'Cubicaje de silo #{reading_id} actualizado correctamente.', 'success')
    except Exception as e:
        log_error('INVENTORY_ROUTE', f'Error al editar cubicaje de silo #{reading_id}', e)
        flash(f'Error al modificar cubicaje de silo: {str(e)}', 'danger')
    return redirect(url_for('inventory.index'))

# Endpoint para eliminar un cubicaje de silo
@inventory_bp.route('/silo-reading/delete/<int:reading_id>', methods=['POST'])
@roles_required('usuario', 'admin_sistema', 'administrador', 'gerencia')
def delete_silo_reading_route(reading_id):
    try:
        delete_reason = request.form.get('delete_reason', '').strip()
        op_name = request.form.get('operator_name') or (g.user.get('full_name') if hasattr(g, 'user') and g.user else 'Operario')

        if not delete_reason:
            flash('Debe especificar el motivo de la eliminación para el registro de auditoría.', 'warning')
            return redirect(url_for('inventory.index'))

        delete_silo_reading(reading_id, delete_reason, op_name)
        flash(f'Cubicaje de silo #{reading_id} eliminado. Existencias recalculadas.', 'success')
    except Exception as e:
        log_error('INVENTORY_ROUTE', f'Error al eliminar cubicaje de silo #{reading_id}', e)
        flash(f'Error al eliminar cubicaje de silo: {str(e)}', 'danger')
    return redirect(url_for('inventory.index'))

