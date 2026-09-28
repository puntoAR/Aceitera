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
    # Valida que el rol asignado sea uno de los oficiales
    if role not in ('usuario', 'administrador', 'gerencia', 'admin_sistema'):
        # Lanza excepcion si el rol no es valido
        raise ValueError(f"El rol {role} no es válido. Debe ser: usuario, gerencia o admin_sistema.")
    
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

# Blanquea o actualiza la contrasena de un usuario asignando una clave provisoria o personalizada
def admin_blanquear_password(user_id, custom_password=None, must_change=True):
    # Si se especifico una clave personalizada no vacia
    if custom_password and str(custom_password).strip():
        # Utiliza la clave personalizada provista
        temp_password = str(custom_password).strip()
    else:
        # Genera una contrasena segura y memorable
        temp_password = generate_secure_password(length=8)
    # Actualiza la contrasena en la base de datos y define flag de cambio obligatorio
    reset_user_password(user_id, temp_password, must_change=must_change)
    
    # Obtiene datos del usuario para auditoria
    with get_db_connection() as conn:
        # Consulta los datos identificatorios del usuario
        u = conn.execute("SELECT full_name, username, dni FROM users WHERE id = ?;", (user_id,)).fetchone()

    # Registra el evento en auditoria con el detalle de credenciales
    record_audit_event(
        category='USUARIOS',
        action='BLANQUEO_PASSWORD',
        details=f"Blanqueo de contraseña realizado por el Administrador para {u['full_name']} (Usuario: {u['username']}, DNI: {u['dni']}). Cambio obligatorio: {'SI' if must_change else 'NO'}."
    )
    # Retorna la clave temporal para comunicarsela al usuario
    return temp_password

# Actualiza los datos de perfil de un usuario existente en el sistema
def admin_update_user(user_id, username, full_name, dni, phone, role):
    # Limpia y normaliza el nombre de usuario
    u_name = str(username).strip()
    # Limpia y normaliza el nombre completo
    f_name = str(full_name).strip()
    # Limpia y normaliza el documento de identidad
    d_num = str(dni).strip()
    # Limpia y normaliza el numero de telefono
    p_num = str(phone).strip() if phone else ""
    # Limpia y normaliza el rol
    r_val = str(role).strip()

    # Valida que los campos criticos no esten vacios
    if not u_name:
        # Lanza error si falta el nombre de usuario
        raise ValueError("El nombre de usuario es obligatorio.")
    if not f_name:
        # Lanza error si falta el nombre y apellido
        raise ValueError("El nombre y apellido son obligatorios.")
    if not d_num:
        # Lanza error si falta el DNI
        raise ValueError("El número de DNI es obligatorio.")

    # Valida que el rol seleccionado sea valido
    if r_val not in ('usuario', 'administrador', 'gerencia', 'admin_sistema'):
        # Lanza error si el rol no es valido
        raise ValueError(f"Rol '{r_val}' no permitido. Debe ser: usuario, gerencia o admin_sistema.")

    # Abre conexion para verificar unicidad y actualizar datos
    with get_db_connection() as conn:
        # Comprueba que el usuario a editar exista
        cur_u = conn.execute("SELECT id, username, full_name, dni, phone, role FROM users WHERE id = ?;", (user_id,)).fetchone()
        # Si no existe el registro
        if not cur_u:
            # Lanza excepcion de usuario no encontrado
            raise ValueError(f"Usuario con ID {user_id} no encontrado.")

        # Verifica unicidad del nombre de usuario descartando el mismo usuario
        dup_u = conn.execute("SELECT id FROM users WHERE LOWER(username) = LOWER(?) AND id != ?;", (u_name, user_id)).fetchone()
        # Si otro usuario ya tiene ese nombre de usuario
        if dup_u:
            # Lanza error de duplicidad
            raise ValueError(f"El nombre de usuario '{u_name}' ya está en uso por otra cuenta.")

        # Verifica unicidad del DNI descartando el mismo usuario
        dup_d = conn.execute("SELECT id FROM users WHERE dni = ? AND id != ?;", (d_num, user_id)).fetchone()
        # Si otro usuario ya tiene ese DNI registrado
        if dup_d:
            # Lanza error de duplicidad
            raise ValueError(f"El DNI '{d_num}' ya se encuentra registrado en otra cuenta.")

        # Actualiza los datos del usuario en la base de datos
        conn.execute("""
            UPDATE users
            SET username = ?, full_name = ?, dni = ?, phone = ?, role = ?
            WHERE id = ?;
        """, (u_name, f_name, d_num, p_num, r_val, user_id))
        # Confirma la transaccion
        conn.commit()

    # Registra el evento en auditoria
    record_audit_event(
        category='USUARIOS',
        action='EDICION_PERFIL',
        details=f"Perfil actualizado para {f_name} (ID {user_id}): @{cur_u['username']} -> @{u_name}, DNI: {d_num}, Rol: {r_val}."
    )
    # Retorna confirmacion de exito
    return True

# Actualiza el rol de un usuario existente
def change_user_role(user_id, new_role):
    # Valida el rol
    if new_role not in ('usuario', 'administrador', 'gerencia', 'admin_sistema'):
        raise ValueError(f"Rol {new_role} no permitido. Debe ser: usuario, gerencia o admin_sistema.")
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

# Obtiene la lista de errores del sistema registrados con diagnostico enriquecido de origen y linea
def get_system_errors(limit=100):
    # Importa el analizador de traza para inferir origen si no estuviera precargado
    from core.error_logger import parse_traceback_origin
    # Abre conexion con base de datos
    with get_db_connection() as conn:
        # Consulta los errores registrados ordenados descendentemente
        rows = conn.execute("""
            SELECT * FROM system_errors
            ORDER BY id DESC LIMIT ?;
        """, (limit,)).fetchall()
        # Lista estructurada de resultados enriquecidos
        result = []
        # Itera sobre cada registro de error obtenido
        for r in rows:
            # Convierte la fila SQLite en diccionario Python
            item = dict(r)
            # Si no posee archivo o linea de origen pero si tiene traza de error
            if (not item.get('origin_file') or not item.get('origin_line')) and item.get('traceback'):
                # Deduce el origen analizando la traza con la funcion auxiliar
                parsed = parse_traceback_origin(item.get('traceback'))
                # Asigna el archivo de origen si estaba vacio
                if not item.get('origin_file'):
                    item['origin_file'] = parsed.get('origin_file')
                # Asigna la linea causante si estaba vacia
                if not item.get('origin_line'):
                    item['origin_line'] = parsed.get('origin_line')
                # Asigna el nombre de la funcion si estaba vacio
                if not item.get('origin_func'):
                    item['origin_func'] = parsed.get('origin_func')
                # Asigna el codigo fuente afectado si estaba vacio
                if not item.get('origin_code'):
                    item['origin_code'] = parsed.get('origin_code')
            # Agrega el incidente a la lista procesada
            result.append(item)
        # Retorna el listado completo de incidentes
        return result

# Marca un error del sistema como resuelto o revisado registrando la fecha
def resolve_system_error(error_id):
    # Importa datetime para estampar la fecha de resolucion
    import datetime
    # Genera estampa de tiempo actual
    now_str = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    # Abre conexion
    with get_db_connection() as conn:
        try:
            # Intenta actualizar el indicador y la marca de tiempo de resolucion
            conn.execute("UPDATE system_errors SET resolved = 1, resolved_at = ? WHERE id = ?;", (now_str, error_id))
        except Exception:
            # Fallback en caso de esquemas sin columna resolved_at
            conn.execute("UPDATE system_errors SET resolved = 1 WHERE id = ?;", (error_id,))
        # Confirma la actualizacion
        conn.commit()
    # Registra en auditoria el cierre del incidente
    record_audit_event('CONFIG', 'ERROR_RESUELTO', f"Error ID {error_id} marcado como resuelto.")
    # Retorna confirmacion de exito
    return True

# Crea un nuevo perfil de usuario directamente por el Administrador del Sistema
def admin_create_user(username, full_name, dni, phone, password, role, must_change=False):
    # Limpia y valida el nombre de usuario
    user_clean = str(username).strip()
    # Limpia el nombre completo
    name_clean = str(full_name).strip()
    # Limpia el documento nacional de identidad
    dni_clean = str(dni).strip() if dni else None
    # Limpia el numero telefonico
    phone_clean = str(phone).strip() if phone else None
    # Limpia la clave de acceso
    pwd_clean = str(password).strip()

    # Valida que el nombre de usuario no este vacio
    if not user_clean:
        raise ValueError("El nombre de usuario es obligatorio.")
    # Valida que el nombre completo no este vacio
    if not name_clean:
        raise ValueError("El nombre y apellido son obligatorios.")
    # Valida la longitud minima de la contrasena
    if len(pwd_clean) < 4:
        raise ValueError("La contraseña debe contener al menos 4 caracteres.")
    # Valida que el rol seleccionado sea uno de los oficiales
    if role not in ('usuario', 'administrador', 'gerencia', 'admin_sistema'):
        raise ValueError(f"El rol '{role}' no es válido. Debe ser: usuario, gerencia o admin_sistema.")

    # Abre conexion para validar duplicados e insertar el nuevo usuario
    with get_db_connection() as conn:
        # Verifica si el nombre de usuario ya existe
        existing_user = conn.execute("SELECT id FROM users WHERE username = ?;", (user_clean,)).fetchone()
        # Si ya existe un usuario con ese nombre
        if existing_user:
            raise ValueError(f"El nombre de usuario '{user_clean}' ya está en uso. Por favor elija otro.")

        # Verifica si el DNI ya esta registrado (si fue ingresado)
        if dni_clean:
            existing_dni = conn.execute("SELECT id FROM users WHERE dni = ?;", (dni_clean,)).fetchone()
            if existing_dni:
                raise ValueError(f"El DNI '{dni_clean}' ya se encuentra registrado en el sistema.")

        # Determina la bandera de cambio obligatorio de clave
        change_flag = 1 if must_change else 0

        # Inserta el nuevo registro directamente como aprobado y activo
        cursor = conn.execute("""
            INSERT INTO users (username, full_name, role, pin, dni, phone, approval_status, must_change_password, is_active)
            VALUES (?, ?, ?, ?, ?, ?, 'aprobado', ?, 1);
        """, (user_clean, name_clean, role, pwd_clean, dni_clean, phone_clean, change_flag))
        # Confirma la transaccion
        conn.commit()
        # Obtiene el ID asignado
        new_id = cursor.lastrowid

    # Registra la creacion del perfil en la bitacora de auditoria
    record_audit_event(
        category='USUARIOS',
        action='ALTA_USUARIO',
        details=f"Perfil creado directamente por Administrador: usuario '{user_clean}' ({name_clean}) con rol '{role}'."
    )
    # Retorna el identificador del nuevo usuario creado
    return new_id
