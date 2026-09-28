# Modulo central de seguridad, autenticacion, control de accesos por roles y recuperacion de claves
# Importa functools para envolver decoradores de rutas
import functools
# Importa secrets y string para generacion criptografica segura de contrasenas y codigos OTP
import secrets
import string
# Importa datetime para controlar la expiracion de codigos de recuperacion
import datetime
# Importa componentes web de Flask
from flask import session, redirect, url_for, flash, g, request
# Importa la conexion a base de datos SQLite
from core.database import get_db_connection
# Importa el modulo de auditoria de eventos
from core.audit import record_audit_event
# Importa funciones horarias oficiales de planta BioBalcarce (Argentina UTC-3)
from core.timezone import get_plant_now, get_plant_now_str

# Genera una contrasena segura y memorable para recuperacion automatica
def generate_secure_password(length=8):
    # Prefijo corporativo de la planta
    prefix = "Bio-"
    # Genera 4 digitos numericos aleatorios
    digits = ''.join(secrets.choice(string.digits) for _ in range(4))
    # Caracter especial seguro
    symbol = secrets.choice("!#$*")
    # Letra aleatoria para garantizar complejidad
    letter = secrets.choice(string.ascii_letters)
    # Retorna la contrasena completa compuesta (ej: Bio-8492!x)
    return f"{prefix}{digits}{symbol}{letter}"

# Genera un codigo OTP de 6 digitos para verificacion por SMS / WhatsApp
def generate_otp_code(user_id):
    # Genera un numero aleatorio de 6 digitos entre 100000 y 999999
    code = f"{secrets.randbelow(900000) + 100000}"
    # Calcula la fecha de expiracion a 15 minutos en el futuro segun hora oficial de planta
    created_at = get_plant_now_str()
    expires_at = (get_plant_now() + datetime.timedelta(minutes=15)).strftime('%Y-%m-%d %H:%M:%S')
    # Abre conexion para persistir el codigo en la tabla password_reset_codes
    with get_db_connection() as conn:
        # Invalida codigos previos no utilizados para este usuario
        conn.execute("UPDATE password_reset_codes SET used = 1 WHERE user_id = ? AND used = 0;", (user_id,))
        # Inserta el nuevo codigo generado con su estampa oficial de planta
        conn.execute("""
            INSERT INTO password_reset_codes (user_id, code, created_at, expires_at, used)
            VALUES (?, ?, ?, ?, 0);
        """, (user_id, code, created_at, expires_at))
        conn.commit()
    # Retorna el codigo de 6 digitos
    return code

# Valida si un codigo OTP ingresado es correcto y no ha expirado
def verify_otp_code(user_id, code):
    # Fecha y hora oficial de planta para comparar expiracion
    now_str = get_plant_now_str()
    # Abre conexion para buscar el codigo
    with get_db_connection() as conn:
        # Busca el codigo activo no usado y no expirado
        row = conn.execute("""
            SELECT id FROM password_reset_codes
            WHERE user_id = ? AND code = ? AND used = 0 AND expires_at > ?
            ORDER BY created_at DESC LIMIT 1;
        """, (user_id, str(code).strip(), now_str)).fetchone()
        # Si coincide exactamente
        if row:
            # Marca el codigo como consumido
            conn.execute("UPDATE password_reset_codes SET used = 1 WHERE id = ?;", (row['id'],))
            conn.commit()
            # Retorna verdadero indicando exito
            return True
    # Retorna falso si el codigo es invalido o ya expiro
    return False

# Autentica a un usuario por Nombre de Usuario o DNI y clave
def authenticate_user(identifier, pin_or_password):
    # Limpia espacios en blanco del identificador
    ident = str(identifier).strip()
    # Limpia caracteres de puntuacion comunes en DNI como puntos y guiones
    ident_clean_dni = ident.replace('.', '').replace('-', '').replace(' ', '')
    # Limpia espacios en blanco de la clave ingresada
    secret = str(pin_or_password).strip()

    # Abre conexion para buscar el usuario por username o por DNI
    with get_db_connection() as conn:
        # Busca coincidencia insensible a mayusculas/minusculas en username o coincidencia en DNI
        user = conn.execute("""
            SELECT * FROM users
            WHERE (LOWER(username) = LOWER(?) OR dni = ? OR dni = ?)
            LIMIT 1;
        """, (ident, ident, ident_clean_dni)).fetchone()

        # Si no hubo coincidencia directa y el identificador no es solo numerico
        if not user and not ident.isdigit():
            # Consulta usuarios para verificar coincidencia por alias de nombre y apellido
            all_users = conn.execute("SELECT * FROM users;").fetchall()
            # Recorre cada usuario para calcular alias naturales
            for cand in all_users:
                # Obtiene las palabras del nombre completo en minusculas
                fn_parts = [p.lower() for p in (cand['full_name'] or '').split() if p]
                # Si tiene al menos nombre y apellido
                if len(fn_parts) >= 2:
                    # Genera alias tipo primera letra + apellido (ej: cschisano)
                    alias1 = fn_parts[0][0] + fn_parts[-1]
                    # Genera alias tipo nombre.apellido (ej: cristian.schisano)
                    alias2 = f"{fn_parts[0]}.{fn_parts[-1]}"
                    # Genera alias todo junto (ej: cristianschisano)
                    alias3 = "".join(fn_parts)
                    # Si el identificador ingresado coincide con algun alias
                    if ident.lower() in (alias1, alias2, alias3):
                        # Asigna el usuario candidato encontrado
                        user = cand
                        # Finaliza la busqueda de alias
                        break

    # Si no existe ningun usuario con ese identificador
    if not user:
        # Retorna diccionario indicando credenciales invalidas
        return {'success': False, 'error_type': 'not_found', 'message': 'El usuario o DNI ingresado no se encuentra registrado en el sistema.'}

    # Convierte a diccionario
    user_dict = dict(user)

    # Verifica si la cuenta esta pendiente de aprobacion por el Administrador del Sistema
    if user_dict.get('approval_status') == 'pendiente':
        # Retorna error informando que requiere aprobacion previa
        return {'success': False, 'error_type': 'pending_approval', 'message': 'Su cuenta está pendiente de aprobación por el Administrador del Sistema. Se le notificará cuando esté habilitada.'}

    # Verifica si la cuenta fue rechazada o dada de baja
    if user_dict.get('approval_status') == 'rechazado' or not user_dict.get('is_active'):
        # Retorna error de cuenta inhabilitada
        return {'success': False, 'error_type': 'inactive', 'message': 'Su cuenta ha sido inhabilitada o rechazada. Contacte al Administrador del Sistema.'}

    # Comprueba la clave o PIN almacenado
    if user_dict['pin'] != secret:
        # Retorna error de clave incorrecta
        return {'success': False, 'error_type': 'bad_password', 'message': 'La contraseña o clave ingresada es incorrecta.'}

    # Si supero todas las validaciones retorna el usuario con exito
    return {'success': True, 'user': user_dict}

# Registra un nuevo usuario en estado pendiente de aprobacion
def register_user(full_name, dni, phone, password):
    # Limpia los datos de entrada
    fn = str(full_name).strip()
    d = str(dni).strip()
    p = str(phone).strip()
    pwd = str(password).strip()

    # Abre conexion para verificar unicidad de DNI
    with get_db_connection() as conn:
        # Comprueba si ya existe un usuario con ese DNI
        existing = conn.execute("SELECT id FROM users WHERE dni = ?;", (d,)).fetchone()
        # Si el DNI ya esta en uso
        if existing:
            # Lanza excepcion de validacion
            raise ValueError(f"Ya existe una cuenta registrada con el DNI {d}.")
        
        # Genera un username por defecto a partir del DNI o nombre
        username = d
        # Verifica si el username esta en conflicto
        u_exists = conn.execute("SELECT id FROM users WHERE username = ?;", (username,)).fetchone()
        if u_exists:
            # Genera un username alternativo unico
            username = f"user_{d}"

        # Inserta el nuevo registro con rol 'usuario' y estado 'pendiente'
        cursor = conn.execute("""
            INSERT INTO users (
                username, full_name, role, pin, dni, phone,
                approval_status, must_change_password, is_active
            ) VALUES (?, ?, 'usuario', ?, ?, ?, 'pendiente', 0, 0);
        """, (username, fn, pwd, d, p))
        conn.commit()
        # Obtiene el ID asignado
        new_id = cursor.lastrowid

    # Registra el evento en auditoria
    record_audit_event('AUTH', 'REGISTRO_SOLICITUD', f'Nueva solicitud de usuario: {fn} (DNI {d}, Tel: {p}) pendiente de aprobacion.', user_override=username)
    # Retorna el nuevo identificador
    return new_id

# Restablece la contrasena de un usuario (por auto-recuperacion o blanqueo del admin)
def reset_user_password(user_id, new_password, must_change=True):
    # Convierte a entero el flag de cambio obligatorio
    flag = 1 if must_change else 0
    # Abre conexion para actualizar la base de datos
    with get_db_connection() as conn:
        # Actualiza el campo pin y must_change_password
        conn.execute("""
            UPDATE users
            SET pin = ?, must_change_password = ?
            WHERE id = ?;
        """, (str(new_password).strip(), flag, user_id))
        conn.commit()

# Carga la informacion del usuario en el contexto de peticion g de Flask
def load_logged_in_user():
    # Obtiene el identificador del usuario desde la sesion activa
    user_id = session.get('user_id')
    # Si no hay sesion de usuario iniciada
    if user_id is None:
        # Asigna None a la variable global de usuario
        g.user = None
    else:
        # Abre conexion para consultar los datos actualizados del usuario
        with get_db_connection() as conn:
            # Busca los datos del usuario por su identificador
            user = conn.execute("SELECT * FROM users WHERE id = ?;", (user_id,)).fetchone()
            # Asigna el resultado al contexto global de la peticion
            g.user = dict(user) if user else None

# Decorador para restringir el acceso a vistas que requieren inicio de sesion
def login_required(view):
    # Envuelve la vista original conservando su metadata
    @functools.wraps(view)
    def wrapped_view(**kwargs):
        # Si no hay ningun usuario cargado en el contexto de peticion
        if g.user is None:
            # Emite un mensaje de advertencia al usuario
            flash('Debe iniciar sesión para acceder a este módulo.', 'warning')
            # Redirige a la pantalla de inicio de sesion
            return redirect(url_for('dashboard.login'))
        
        # Si el usuario tiene la marca de cambio obligatorio de contrasena y no esta en esa pantalla
        if g.user.get('must_change_password') == 1 and request.endpoint not in ('dashboard.change_password', 'dashboard.logout'):
            # Emite aviso preventivo
            flash('Por razones de seguridad, debe cambiar su contraseña provisoria antes de continuar.', 'info')
            # Redirige obligatoriamente al formulario de cambio de clave
            return redirect(url_for('dashboard.change_password'))
            
        # Ejecuta la vista solicitada si el usuario esta autenticado
        return view(**kwargs)
    # Retorna la funcion decorada
    return wrapped_view

# Decorador para restringir el acceso segun una lista de roles permitidos
def roles_required(*allowed_roles):
    # Define la funcion decoradora exterior
    def decorator(view):
        # Envuelve la vista original
        @functools.wraps(view)
        def wrapped_view(**kwargs):
            # Si el usuario no ha iniciado sesion
            if g.user is None:
                # Emite aviso y redirige a login
                flash('Debe iniciar sesión para continuar.', 'warning')
                return redirect(url_for('dashboard.login'))
            
            # Intercepta si tiene cambio obligatorio de clave pendiente
            if g.user.get('must_change_password') == 1 and request.endpoint not in ('dashboard.change_password', 'dashboard.logout'):
                flash('Debe actualizar su contraseña provisoria antes de acceder al sistema.', 'warning')
                return redirect(url_for('dashboard.change_password'))

            # Si el rol del usuario no esta en la lista de roles autorizados
            # Soporte interoperable y transparente para rol gerencial ('gerencia' y 'administrador')
            effective_roles = set(allowed_roles)
            if 'administrador' in effective_roles or 'gerencia' in effective_roles:
                effective_roles.add('administrador')
                effective_roles.add('gerencia')

            if g.user['role'] not in effective_roles:
                # Emite mensaje de permisos insuficientes
                flash('No posee permisos autorizados para acceder a esta sección.', 'danger')
                # Redireccion inteligente segun el rol del usuario
                if g.user['role'] == 'usuario':
                    # Operarios y tecnicos van a su panel de produccion
                    return redirect(url_for('production.index'))
                elif g.user['role'] in ('administrador', 'gerencia'):
                    # Gerencia de direccion va al dashboard
                    return redirect(url_for('dashboard.index'))
                else:
                    # Otros casos van al login
                    return redirect(url_for('dashboard.login'))
                    
            # Permite el paso a la vista protegida
            return view(**kwargs)
        # Retorna la vista envuelta
        return wrapped_view
    # Retorna el decorador configurado
    return decorator
