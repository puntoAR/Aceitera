# Modulo de rutas web para la administracion de usuarios, aprobaciones, auditoria y errores
# Importa Blueprint, render_template, request, redirect, url_for, flash, session de Flask
from flask import Blueprint, render_template, request, redirect, url_for, flash, session
# Importa la conexion a base de datos
from core.database import get_db_connection
# Importa los decoradores de seguridad
from core.security import roles_required
# Importa las funciones del servicio de administracion
from modules.admin.service import (
    get_pending_users, get_all_users, approve_user, reject_user,
    admin_blanquear_password, change_user_role, toggle_user_active,
    get_audit_logs, get_system_errors, resolve_system_error,
    admin_create_user, admin_update_user
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
    # Extrae credenciales del ultimo blanqueo si existieran para mostrarlas destacadas
    last_reset_creds = session.pop('last_reset_creds', None)
    # Informacion sobre el estado de persistencia de almacenamiento
    from config import IS_VERCEL, USE_TURSO
    # Define diccionario con el estado del almacenamiento
    storage_status = {
        'is_vercel': IS_VERCEL,
        'use_turso': USE_TURSO,
        'is_ephemeral': IS_VERCEL and not USE_TURSO
    }
    # Renderiza la plantilla de gestion de usuarios con todas las variables necesarias
    return render_template('admin_users.html', pending=pending, users=users, storage_status=storage_status, last_reset_creds=last_reset_creds)

# Endpoint para la creacion directa de un nuevo perfil de usuario por el Administrador
@admin_bp.route('/users/create', methods=['POST'])
@roles_required('admin_sistema')
def create_user_route():
    # Obtiene el nombre de usuario del formulario
    username = request.form.get('username')
    # Obtiene el nombre y apellido del operario
    full_name = request.form.get('full_name')
    # Obtiene el numero de documento nacional de identidad
    dni = request.form.get('dni')
    # Obtiene el telefono celular de contacto
    phone = request.form.get('phone')
    # Obtiene la clave inicial de acceso
    password = request.form.get('password')
    # Obtiene el rol asignado
    role = request.form.get('role', 'usuario')
    # Comprueba si se exige cambio forzoso de clave
    must_change = request.form.get('must_change') == '1'

    # Obtiene los modulos permitidos adicionales (checkboxes)
    allowed_list = request.form.getlist('allowed_modules')
    allowed_modules = ','.join(allowed_list) if allowed_list else None

    # Intenta realizar la creacion del perfil en la base de datos
    try:
        # Llama a la logica de servicio para insertar el usuario
        admin_create_user(username, full_name, dni, phone, password, role, must_change, allowed_modules)
        # Emite mensaje flash de confirmacion exitosa
        flash(f"Usuario '{username}' ({full_name}) creado exitosamente con rol '{role}'.", 'success')
    # Captura errores de validacion como nombre repetido o longitud
    except ValueError as ve:
        # Emite alerta con el detalle especifico
        flash(str(ve), 'danger')
    # Captura errores no previstos
    except Exception as e:
        # Emite alerta de error general
        flash(f"Error al crear usuario: {e}", 'danger')

    # Redirige de regreso a la pantalla de gestion de usuarios
    return redirect(url_for('admin.users_list'))

# Endpoint para aprobar una solicitud de usuario y asignarle su rol
@admin_bp.route('/users/approve/<int:user_id>', methods=['POST'])
@roles_required('admin_sistema')
def approve_user_route(user_id):
    # Obtiene el rol seleccionado desde el formulario
    role = request.form.get('role', 'usuario')
    allowed_list = request.form.getlist('allowed_modules')
    allowed_modules = ','.join(allowed_list) if allowed_list else None
    try:
        # Ejecuta la aprobacion
        approve_user(user_id, role, allowed_modules)
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

# Endpoint para blanquear o reasignar la contrasena de un usuario
@admin_bp.route('/users/reset-password/<int:user_id>', methods=['POST'])
# Requiere rol exclusivo de administrador del sistema
@roles_required('admin_sistema')
def reset_password_route(user_id):
    # Obtiene la clave personalizada si fue provista en el formulario
    custom_pwd = request.form.get('custom_password', '').strip()
    # Verifica si se tildo la casilla para exigir cambio obligatorio
    must_change = request.form.get('must_change') == '1'
    # Bloque de captura de errores para la operacion
    try:
        # Consulta los datos identificatorios del usuario en base de datos
        with get_db_connection() as conn:
            # Obtiene el registro completo del usuario
            u = conn.execute("SELECT id, username, full_name, dni, phone FROM users WHERE id = ?;", (user_id,)).fetchone()
            # Si el usuario no fue encontrado
            if not u:
                # Lanza excepcion de validacion
                raise ValueError("El usuario solicitado no existe.")
        # Ejecuta el blanqueo o asignacion de clave personalizada
        new_pwd = admin_blanquear_password(user_id, custom_password=custom_pwd if custom_pwd else None, must_change=must_change)
        # Guarda las credenciales generadas en la sesion para el banner informativo
        session['last_reset_creds'] = {
            # Nombre de usuario para iniciar sesion
            'username': u['username'],
            # Nombre completo del titular
            'full_name': u['full_name'],
            # DNI alternativo para login
            'dni': u['dni'] or '-',
            # Telefono de contacto
            'phone': u['phone'] or '',
            # Clave asignada
            'password': new_pwd,
            # Indicador de obligatoriedad de cambio
            'must_change': must_change
        }
        # Emite notificacion flash con datos claros de acceso
        flash(f"Contraseña actualizada para {u['full_name']}. Usuario login: '{u['username']}' (o DNI: '{u['dni']}') | Nueva clave: '{new_pwd}'", 'success')
    # Captura errores controlados o imprevistos
    except Exception as e:
        # Emite alerta de peligro con el mensaje de error
        flash(f'Error al blanquear contraseña: {e}', 'danger')
    # Redirige de regreso al panel de administracion de usuarios
    return redirect(url_for('admin.users_list'))

# Endpoint para editar los datos de perfil de un usuario existente
@admin_bp.route('/users/edit/<int:user_id>', methods=['POST'])
# Requiere permisos de administrador del sistema
@roles_required('admin_sistema')
def edit_user_route(user_id):
    # Obtiene el nombre de usuario login sanitizado
    username = request.form.get('username', '').strip()
    # Obtiene el nombre completo del usuario
    full_name = request.form.get('full_name', '').strip()
    # Obtiene el numero de documento nacional de identidad
    dni = request.form.get('dni', '').strip()
    # Obtiene el numero telefonico de contacto
    phone = request.form.get('phone', '').strip()
    # Obtiene el rol operativo o jerarquico asignado
    role = request.form.get('role', 'usuario').strip()
    # Obtiene modulos adicionales permitidos
    allowed_list = request.form.getlist('allowed_modules')
    allowed_modules = ','.join(allowed_list) if allowed_list else ''
    # Bloque de captura de errores durante la actualizacion
    try:
        # Ejecuta el servicio de modificacion de perfil
        admin_update_user(user_id, username, full_name, dni, phone, role, allowed_modules=allowed_modules)
        # Emite confirmacion flash exitosa
        flash(f"Perfil de '{full_name}' (@{username}) actualizado con éxito.", 'success')
    # Captura violaciones de unicidad o campos vacios
    except ValueError as ve:
        # Emite advertencia con la explicacion correspondiente
        flash(str(ve), 'danger')
    # Captura cualquier otro error de base de datos
    except Exception as e:
        # Emite mensaje de falla tecnica
        flash(f"Error al actualizar usuario: {e}", 'danger')
    # Redirige al listado general de usuarios
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
    # Informacion sobre el estado de almacenamiento
    from config import IS_VERCEL, USE_TURSO
    storage_status = {
        'is_vercel': IS_VERCEL,
        'use_turso': USE_TURSO,
        'is_ephemeral': IS_VERCEL and not USE_TURSO
    }
    return render_template('admin_errors.html', errors=errors, storage_status=storage_status)

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

# Endpoint exclusivo para que el Administrador del Sistema reinicie datos operativos a cero para produccion
@admin_bp.route('/database/reset_production', methods=['POST'])
@roles_required('admin_sistema')
def reset_production_database():
    # Obtiene la confirmacion escrita ingresada por el administrador
    confirm_text = request.form.get('confirm_text', '').strip()
    # Verifica que el texto coincida exactamente con la frase de seguridad requerida
    if confirm_text != 'CONFIRMAR_RESET_PRODUCCION':
        # Emite mensaje flash de advertencia si no coincide
        flash("La frase de confirmación es incorrecta. Ingrese 'CONFIRMAR_RESET_PRODUCCION' para autorizar el reinicio a cero.", "warning")
        # Redirige de regreso a administracion
        return redirect(url_for('admin.users_list'))
    # Bloque de ejecucion segura
    try:
        # Importa la funcion de puesta a cero de datos operativos
        from core.database import reset_production_operational_data
        # Ejecuta la limpieza de datos operativos
        reset_production_operational_data()
        # Emite mensaje flash confirmando la puesta a cero para produccion
        flash("Base de datos reiniciada a cero exitosamente para Producción Real. Se preservaron intactos los usuarios, turnos, equipos y repuestos.", "success")
    # Captura cualquier excepcion durante el proceso
    except Exception as e:
        # Emite mensaje flash de error
        flash(f"Error al reiniciar datos operativos: {e}", "danger")
    # Redirige al panel de administracion
    return redirect(url_for('admin.users_list'))
