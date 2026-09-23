# Modulo de servicio para gestion administrativa de usuarios, aprobaciones, auditoria y errores
# Importa la conexion a la base de datos
from core.database import get_db_connection
# Importa la funcion de generacion de claves seguras y reseteo
from core.security import generate_secure_password, reset_user_password
# Importa el registrador de auditoria
from core.audit import record_audit_event

# Obtiene la lista de usuarios con solicitud de registro pendiente de aprobacion
def get_pending_users():
    # Abre conexion para consultar usuarios
    with get_db_connection() as conn:
        # Consulta los usuarios en estado pendiente
        rows = conn.execute("""
            SELECT id, username, full_name, dni, phone, created_at, role
            FROM users
            WHERE approval_status = 'pendiente'
            ORDER BY created_at ASC;
        """).fetchall()
        # Retorna la lista convertida a diccionarios
        return [dict(r) for r in rows]

# Obtiene la lista de todos los usuarios registrados en el sistema
def get_all_users():
    # Abre conexion a la base de datos
    with get_db_connection() as conn:
        # Consulta usuarios ordenados por estado y nombre
        rows = conn.execute("""
            SELECT id, username, full_name, dni, phone, role, approval_status,
                   must_change_password, is_active, created_at
            FROM users
            ORDER BY CASE WHEN approval_status = 'pendiente' THEN 0 ELSE 1 END, full_name ASC;
        """).fetchall()
        # Retorna lista de diccionarios
        return [dict(r) for r in rows]

# Aprueba una solicitud de registro y le asigna el nivel de acceso seleccionado
def approve_user(user_id, role):
    # Valida que el rol asignado sea uno de los tres oficiales
    if role not in ('usuario', 'administrador', 'admin_sistema'):
        # Lanza excepcion si el rol no es valido
        raise ValueError(f"El rol {role} no es válido. Debe ser: usuario, administrador o admin_sistema.")
    
    # Abre conexion para actualizar el usuario
    with get_db_connection() as conn:
        # Obtiene datos del usuario para auditoria
        u = conn.execute("SELECT full_name, dni, username FROM users WHERE id = ?;", (user_id,)).fetchone()
        # Si el usuario no existe
        if not u:
            raise ValueError(f"Usuario con ID {user_id} no encontrado.")
        # Actualiza el estado a aprobado, activa la cuenta y fija el rol
        conn.execute("""
            UPDATE users
            SET approval_status = 'aprobado', is_active = 1, role = ?
            WHERE id = ?;
        """, (role, user_id))
        conn.commit()

    # Registra el evento en auditoria
    record_audit_event(
        category='USUARIOS',
        action='APROBACION_USUARIO',
        details=f"Usuario aprobado: {u['full_name']} (DNI {u['dni']}) con rol asignado: '{role}'."
    )
    return True

# Rechaza una solicitud de registro
def reject_user(user_id):
    # Abre conexion para actualizar el usuario
    with get_db_connection() as conn:
        # Obtiene datos del usuario
        u = conn.execute("SELECT full_name, dni, username FROM users WHERE id = ?;", (user_id,)).fetchone()
        if not u:
            raise ValueError(f"Usuario con ID {user_id} no encontrado.")
        # Marca como rechazado e inactivo
        conn.execute("""
            UPDATE users
            SET approval_status = 'rechazado', is_active = 0
            WHERE id = ?;
        """, (user_id,))
        conn.commit()

    # Registra en auditoria el rechazo
    record_audit_event(
        category='USUARIOS',
        action='RECHAZO_USUARIO',
        details=f"Solicitud de registro rechazada para: {u['full_name']} (DNI {u['dni']}).",
        status='ADVERTENCIA'
    )
    return True

# Blanquea la contrasena de un usuario asignando una clave segura provisoria
def admin_blanquear_password(user_id):
    # Genera una contrasena segura y memorable
    temp_password = generate_secure_password(length=8)
    # Actualiza la contrasena en la base de datos y marca cambio obligatorio
    reset_user_password(user_id, temp_password, must_change=True)
    
    # Obtiene datos del usuario para auditoria
    with get_db_connection() as conn:
        u = conn.execute("SELECT full_name, username, dni FROM users WHERE id = ?;", (user_id,)).fetchone()

    # Registra el evento en auditoria
    record_audit_event(
        category='USUARIOS',
        action='BLANQUEO_PASSWORD',
        details=f"Blanqueo de contraseña realizado por el Administrador para {u['full_name']} (DNI {u['dni']}). Clave provisoria generada."
    )
    # Retorna la clave temporal para comunicarsela al usuario
    return temp_password

# Actualiza el rol de un usuario existente
def change_user_role(user_id, new_role):
    # Valida el rol
    if new_role not in ('usuario', 'administrador', 'admin_sistema'):
        raise ValueError(f"Rol {new_role} no permitido.")
    # Actualiza en base de datos
    with get_db_connection() as conn:
        u = conn.execute("SELECT full_name, role FROM users WHERE id = ?;", (user_id,)).fetchone()
        if not u:
            raise ValueError("Usuario no encontrado.")
        old_role = u['role']
        conn.execute("UPDATE users SET role = ? WHERE id = ?;", (new_role, user_id))
        conn.commit()

    # Registra en auditoria
    record_audit_event(
        category='USUARIOS',
        action='CAMBIO_ROL',
        details=f"Cambio de rol para {u['full_name']}: de '{old_role}' a '{new_role}'."
    )
    return True

# Habilita o deshabilita la cuenta de un usuario
def toggle_user_active(user_id, is_active):
    # Convierte a valor binario 1 o 0
    status_val = 1 if is_active else 0
    # Actualiza en la base de datos
    with get_db_connection() as conn:
        u = conn.execute("SELECT full_name, username FROM users WHERE id = ?;", (user_id,)).fetchone()
        if not u:
            raise ValueError("Usuario no encontrado.")
        conn.execute("UPDATE users SET is_active = ? WHERE id = ?;", (status_val, user_id))
        conn.commit()

    # Accion textual para el log
    action_text = "Habilitación" if status_val == 1 else "Desactivación"
    # Registra en auditoria
    record_audit_event(
        category='USUARIOS',
        action='CAMBIO_ESTADO',
        details=f"{action_text} de cuenta para {u['full_name']} ({u['username']})."
    )
    return True

# Obtiene registros de auditoria con filtros opcionales
def get_audit_logs(category=None, username=None, limit=100):
    # Abre conexion
    with get_db_connection() as conn:
        # Construye consulta parametrizada
        query = "SELECT * FROM audit_logs WHERE 1=1"
        params = []
        if category:
            query += " AND category = ?"
            params.append(category)
        if username:
            query += " AND username LIKE ?"
            params.append(f"%{username}%")
        query += " ORDER BY id DESC LIMIT ?;"
        params.append(limit)

        rows = conn.execute(query, tuple(params)).fetchall()
        return [dict(r) for r in rows]

# Obtiene la lista de errores del sistema registrados
def get_system_errors(limit=100):
    # Abre conexion
    with get_db_connection() as conn:
        rows = conn.execute("""
            SELECT * FROM system_errors
            ORDER BY id DESC LIMIT ?;
        """, (limit,)).fetchall()
        return [dict(r) for r in rows]

# Marca un error del sistema como resuelto o revisado
def resolve_system_error(error_id):
    # Abre conexion
    with get_db_connection() as conn:
        conn.execute("UPDATE system_errors SET resolved = 1 WHERE id = ?;", (error_id,))
        conn.commit()
    # Registra en auditoria
    record_audit_event('CONFIG', 'ERROR_RESUELTO', f"Error ID {error_id} marcado como resuelto.")
    return True
