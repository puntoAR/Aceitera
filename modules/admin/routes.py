# Modulo de rutas web para la administracion de usuarios, aprobaciones, auditoria y errores
# Importa Blueprint, render_template, request, redirect, url_for, flash de Flask
from flask import Blueprint, render_template, request, redirect, url_for, flash
# Importa los decoradores de seguridad
from core.security import roles_required
# Importa las funciones del servicio de administracion
from modules.admin.service import (
    get_pending_users, get_all_users, approve_user, reject_user,
    admin_blanquear_password, change_user_role, toggle_user_active,
    get_audit_logs, get_system_errors, resolve_system_error
)

# Crea el blueprint de administracion
admin_bp = Blueprint('admin', __name__, url_prefix='/admin')

# Vista principal de gestion de usuarios y solicitudes de registro
@admin_bp.route('/users')
# Protege la vista exclusivamente para el Administrador del Sistema
@roles_required('admin_sistema')
def users_list():
    # Obtiene solicitudes pendientes
    pending = get_pending_users()
    # Obtiene lista general de usuarios
    users = get_all_users()
    # Renderiza la plantilla de gestion de usuarios
    return render_template('admin_users.html', pending=pending, users=users)

# Endpoint para aprobar una solicitud de usuario y asignarle su rol
@admin_bp.route('/users/approve/<int:user_id>', methods=['POST'])
@roles_required('admin_sistema')
def approve_user_route(user_id):
    # Obtiene el rol seleccionado desde el formulario
    role = request.form.get('role', 'usuario')
    try:
        # Ejecuta la aprobacion
        approve_user(user_id, role)
        flash(f'Usuario aprobado con éxito. Nivel de acceso asignado: {role}.', 'success')
    except Exception as e:
        flash(f'Error al aprobar usuario: {e}', 'danger')
    return redirect(url_for('admin.users_list'))

# Endpoint para rechazar una solicitud de registro
@admin_bp.route('/users/reject/<int:user_id>', methods=['POST'])
@roles_required('admin_sistema')
def reject_user_route(user_id):
    try:
        # Ejecuta el rechazo
        reject_user(user_id)
        flash('La solicitud de registro ha sido rechazada.', 'info')
    except Exception as e:
        flash(f'Error al procesar el rechazo: {e}', 'danger')
    return redirect(url_for('admin.users_list'))

# Endpoint para blanquear la contrasena de un usuario
@admin_bp.route('/users/reset-password/<int:user_id>', methods=['POST'])
@roles_required('admin_sistema')
def reset_password_route(user_id):
    try:
        # Ejecuta el blanqueo y obtiene la clave provisoria generada
        new_pwd = admin_blanquear_password(user_id)
        flash(f'Contraseña blanqueada con éxito. Clave provisoria generada: {new_pwd} (Se solicitará cambio obligatorio en su primer ingreso).', 'warning')
    except Exception as e:
        flash(f'Error al blanquear contraseña: {e}', 'danger')
    return redirect(url_for('admin.users_list'))

# Endpoint para modificar el rol de un usuario existente
@admin_bp.route('/users/change-role/<int:user_id>', methods=['POST'])
@roles_required('admin_sistema')
def change_role_route(user_id):
    # Obtiene el nuevo rol
    new_role = request.form.get('role')
    try:
        change_user_role(user_id, new_role)
        flash(f'Rol del usuario actualizado a: {new_role}.', 'success')
    except Exception as e:
        flash(f'Error al cambiar rol: {e}', 'danger')
    return redirect(url_for('admin.users_list'))

# Endpoint para habilitar o deshabilitar una cuenta de usuario
@admin_bp.route('/users/toggle-active/<int:user_id>', methods=['POST'])
@roles_required('admin_sistema')
def toggle_active_route(user_id):
    # Obtiene el nuevo estado deseado
    is_active = request.form.get('is_active') == '1'
    try:
        toggle_user_active(user_id, is_active)
        state_label = "habilitado" if is_active else "desactivado"
        flash(f'Usuario {state_label} correctamente.', 'info')
    except Exception as e:
        flash(f'Error al cambiar estado: {e}', 'danger')
    return redirect(url_for('admin.users_list'))

# Vista del registro de auditoria del sistema
@admin_bp.route('/audit')
@roles_required('admin_sistema')
def audit_view():
    # Obtiene filtros opcionales de la URL
    category = request.args.get('category') or None
    username = request.args.get('username') or None
    # Obtiene registros filtrados
    logs = get_audit_logs(category=category, username=username, limit=150)
    return render_template('admin_audit.html', logs=logs, selected_cat=category, selected_user=username)

# Vista de registro de errores tecnicos y excepciones
@admin_bp.route('/errors')
@roles_required('admin_sistema')
def errors_view():
    # Obtiene los errores de ejecucion registrados
    errors = get_system_errors(limit=100)
    return render_template('admin_errors.html', errors=errors)

# Endpoint para marcar un error como resuelto
@admin_bp.route('/errors/resolve/<int:error_id>', methods=['POST'])
@roles_required('admin_sistema')
def resolve_error_route(error_id):
    try:
        resolve_system_error(error_id)
        flash(f'Error #{error_id} marcado como resuelto.', 'success')
    except Exception as e:
        flash(f'Error al actualizar: {e}', 'danger')
    return redirect(url_for('admin.errors_view'))
