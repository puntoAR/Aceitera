# Importa Blueprint, render_template, request, redirect, url_for, flash, jsonify, g desde Flask
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, g
# Importa los decoradores de seguridad y autorizacion por rol
from core.security import roles_required
# Importa los metodos del servicio de configuracion
from modules.configuration.service import (
    get_all_tanks, get_tank_by_id, update_tank_config,
    get_all_silos, get_silo_by_id, update_silo_config,
    get_active_shift, set_active_shift
)
# Importa el logger para registrar eventos
from core.error_logger import log_info, log_error
# Importa el modulo de auditoria para registrar modificaciones criticas
from core.audit import record_audit_event
# Importa funciones de gestion de licenciamiento puntoAR
from core.licensing import get_licensing_status, update_licensing_config
# Importa utilidades de conversion numerica segura
from core.utils import safe_float, safe_int

# Define el Blueprint para las rutas de configuracion
config_bp = Blueprint('config', __name__, url_prefix='/config')

# Vista principal para visualizar y editar la configuracion de equipos y parametros
@config_bp.route('/', methods=['GET'])
@roles_required('admin_sistema', 'administrador')
def index():
    # Obtiene todos los tanques registrados
    tanks = get_all_tanks(only_active=False)
    # Obtiene todos los silos registrados
    silos = get_all_silos(only_active=False)
    # Obtiene el turno activo actual
    active_shift = get_active_shift()
    # Obtiene el estado actual de licenciamiento
    licensing = get_licensing_status()
    # Renderiza la plantilla HTML de configuracion
    return render_template('config.html', tanks=tanks, silos=silos, active_shift=active_shift, licensing=licensing)

# Endpoint para actualizar la geometria de un tanque
@config_bp.route('/tank/<int:tank_id>', methods=['POST'])
@roles_required('admin_sistema', 'administrador')
def update_tank(tank_id):
    # Bloque de captura de excepciones para manejo seguro
    try:
        # Extrae los parametros del formulario
        name = request.form.get('name')
        geometry_type = request.form.get('geometry_type')
        diameter_m = safe_float(request.form.get('diameter_m'), 0.0)
        length_m = safe_float(request.form.get('length_m'), 0.0)
        height_m = safe_float(request.form.get('height_m'), 0.0)
        heel_volume_l = safe_float(request.form.get('heel_volume_l'), 0.0)
        default_density = safe_float(request.form.get('default_density'), 0.92)
        is_active_val = request.form.get('is_active')
        if is_active_val is not None:
            is_active = 1 if is_active_val in ('1', 'on', 'true', True, 1) else 0
        else:
            existing = get_tank_by_id(tank_id)
            is_active = existing.get('is_active', 1) if existing else 1
        # Actualiza la configuracion del tanque en base de datos
        update_tank_config(tank_id, name, geometry_type, diameter_m, length_m, height_m, heel_volume_l, default_density, is_active)
        # Registra la modificacion en auditoria
        record_audit_event('CONFIGURACION', 'MODIFICACION_TANQUE', f"Parámetros actualizados para tanque {name} (ID: {tank_id}, Activo: {is_active}).")
        # Notifica al usuario con mensaje de exito
        flash(f'Configuración de tanque {name} actualizada exitosamente.', 'success')
    except Exception as e:
        # Registra el error en log
        log_error('CONFIG_ROUTE', f'Error al actualizar tanque {tank_id}', e)
        # Notifica al usuario del error
        flash(f'Error al actualizar parametros del tanque: {str(e)}', 'danger')
    # Redirige nuevamente a la pantalla de configuracion
    return redirect(url_for('config.index'))

# Endpoint para actualizar la configuracion de un silo
@config_bp.route('/silo/<int:silo_id>', methods=['POST'])
@roles_required('admin_sistema', 'administrador')
def update_silo(silo_id):
    # Bloque para captura de excepciones
    try:
        # Extrae datos del formulario de forma segura
        name = request.form.get('name')
        product_assigned = request.form.get('product_assigned')
        diameter_m = safe_float(request.form.get('diameter_m'), 0.0)
        sheet_height_m = safe_float(request.form.get('sheet_height_m'), 0.99)
        total_sheets = safe_int(request.form.get('total_sheets'), 1)
        bottom_cone_height_m = safe_float(request.form.get('bottom_cone_height_m'), 0.0)
        bottom_cone_type = request.form.get('bottom_cone_type', 'cone')
        min_diam_m = safe_float(request.form.get('bottom_cone_min_diam_m'), 0.0)
        copete_max_height_m = safe_float(request.form.get('copete_max_height_m'), 0.0)
        default_ph = safe_float(request.form.get('default_ph'), 40.0)
        is_active_val = request.form.get('is_active')
        if is_active_val is not None:
            is_active = 1 if is_active_val in ('1', 'on', 'true', True, 1) else 0
        else:
            existing = get_silo_by_id(silo_id)
            is_active = existing.get('is_active', 1) if existing else 1
        # Actualiza la configuracion del silo
        update_silo_config(silo_id, name, product_assigned, diameter_m, sheet_height_m, total_sheets,
                           bottom_cone_height_m, bottom_cone_type, min_diam_m, copete_max_height_m, default_ph, is_active)
        # Registra la modificacion en auditoria
        record_audit_event('CONFIGURACION', 'MODIFICACION_SILO', f"Parámetros actualizados para silo {name} (ID: {silo_id}, Activo: {is_active}).")
        # Notifica exito
        flash(f'Configuración de silo {name} actualizada correctamente.', 'success')
    except Exception as e:
        # Registra error en log
        log_error('CONFIG_ROUTE', f'Error al actualizar silo {silo_id}', e)
        # Notifica error
        flash(f'Error al actualizar silo: {str(e)}', 'danger')
    # Redirige a la pantalla de configuracion
    return redirect(url_for('config.index') + f'#silo-row-{silo_id}')

# Endpoint para recalcular masivamente todas las mediciones de silos
@config_bp.route('/silo/recalculate-all', methods=['POST'])
@roles_required('admin_sistema', 'administrador')
def recalculate_all_silos_route():
    try:
        from modules.configuration.service import recalculate_all_silos
        recalculate_all_silos()
        record_audit_event('CONFIGURACION', 'RECALCULAR_SILOS', "Recálculo masivo de existencias de silos ejecutado con parámetros maestros actuales.")
        flash('Todas las mediciones de silos fueron recalculadas exitosamente con los parámetros geométricos y densidades actuales.', 'success')
    except Exception as e:
        log_error('CONFIG_ROUTE', 'Error al recalcular mediciones de silos', e)
        flash(f'Error al recalcular mediciones: {str(e)}', 'danger')
    return redirect(url_for('config.index') + '#silos-config')

# Endpoint para cambiar el turno activo
@config_bp.route('/shift/change', methods=['POST'])
@roles_required('usuario', 'admin_sistema')
def change_shift():
    # Extrae el nuevo turno y el operario responsable
    shift_id = request.form.get('shift_id')
    operator_name = request.form.get('operator_name')
    # Si ambos campos fueron provistos
    if shift_id and operator_name:
        try:
            # Actualiza el turno activo verificando permisos de rol
            set_active_shift(shift_id, operator_name, user_role=g.user.get('role'))
            # Registra en auditoria
            record_audit_event('PRODUCCION', 'CAMBIO_TURNO', f"Guardia asignada a {shift_id} - Operario: {operator_name}.")
            # Notifica al usuario
            flash(f'Guardia cambiada: Turno {shift_id} - Operario: {operator_name}', 'info')
        except PermissionError as pe:
            flash(str(pe), 'danger')
    else:
        # Notifica campos incompletos
        flash('Debe seleccionar turno y operario responsable.', 'warning')
    # Redirige a la pagina previa o al dashboard
    return redirect(request.referrer or url_for('dashboard.index'))

# Endpoint para actualizar politicas de licenciamiento del sistema (exclusivo admin_sistema)
@config_bp.route('/licensing/update', methods=['POST'])
@roles_required('admin_sistema')
def update_licensing():
    try:
        client_name = request.form.get('client_name', 'Aceitera S.A.')
        license_mode = request.form.get('license_mode', 'libre_uso')
        expiration_date = request.form.get('expiration_date', '')
        start_date = request.form.get('start_date', '')
        license_key = request.form.get('license_key', '')
        max_users = safe_int(request.form.get('max_users'), 50)
        is_active = 1 if request.form.get('is_active') == '1' else 0
        block_dashboard = 1 if request.form.get('block_dashboard') == 'on' else 0
        block_data_entry = 1 if request.form.get('block_data_entry') == 'on' else 0
        block_reports = 1 if request.form.get('block_reports') == 'on' else 0
        block_updates = 1 if request.form.get('block_updates') == 'on' else 0
        status_notes = request.form.get('status_notes', '')

        operator = g.user.get('username') if hasattr(g, 'user') and g.user else 'admin_sistema'
        update_licensing_config(
            client_name=client_name,
            license_mode=license_mode,
            expiration_date=expiration_date,
            start_date=start_date,
            license_key=license_key,
            block_dashboard=block_dashboard,
            block_data_entry=block_data_entry,
            block_reports=block_reports,
            block_updates=block_updates,
            max_users=max_users,
            is_active=is_active,
            status_notes=status_notes,
            updated_by=operator
        )
        record_audit_event('CONFIGURACION', 'MODIFICACION_LICENCIA', f"Políticas de licencia actualizadas: modo={license_mode}, expira={expiration_date}.")
        flash('Configuración de licenciamiento y políticas de uso actualizada exitosamente.', 'success')
    except Exception as e:
        log_error('CONFIG_ROUTE', 'Error al actualizar licenciamiento', e)
        flash(f'Error al guardar configuración de licencia: {str(e)}', 'danger')

    return redirect(url_for('config.index'))

