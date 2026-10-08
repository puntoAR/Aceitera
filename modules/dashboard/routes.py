# Importa componentes de Flask para rutas, sesiones, redirecciones y JSON
from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify, g
# Importa urllib.parse para codificar el mensaje de WhatsApp de forma segura
import urllib.parse
# Importa funciones de seguridad, autenticacion, roles y recuperacion de claves
from core.security import (
    authenticate_user, register_user, generate_otp_code, verify_otp_code,
    generate_secure_password, reset_user_password, login_required, roles_required
)
# Importa el servicio del dashboard ejecutivo
from modules.dashboard.service import get_executive_dashboard_data
# Importa el servicio de turnos operativos y turnos disponibles segun rol
from modules.configuration.service import get_active_shift, set_active_shift, get_available_shifts
# Importa el conector de base de datos
from core.database import get_db_connection
# Importa el modulo de auditoria para trazabilidad de accesos
from core.audit import record_audit_event
# Importa logger del sistema
from core.error_logger import log_info, log_error

# Define Blueprint principal de dashboard y acceso
dashboard_bp = Blueprint('dashboard', __name__)

# Pantalla de inicio de sesion unificada con soporte de Usuario o DNI y PIN/Clave
@dashboard_bp.route('/login', methods=['GET', 'POST'])
def login():
    # Si la peticion es POST (envio de credenciales)
    if request.method == 'POST':
        # Extrae identificador (username o DNI)
        identifier = request.form.get('username', '').strip()
        # Extrae la clave o PIN
        pin = request.form.get('pin', '').strip()
        
        # Ejecuta la autenticacion contra la base de datos
        auth_result = authenticate_user(identifier, pin)
        
        # Si la autenticacion fue exitosa
        if auth_result.get('success'):
            # Obtiene los datos del usuario autenticado
            user = auth_result['user']
            # Guarda los datos esenciales en la sesion web
            session['user_id'] = user['id']
            session['username'] = user['username']
            session['full_name'] = user['full_name']
            session['role'] = user['role']
            
            # Registra el ingreso en el registro de auditoria
            record_audit_event(
                category='AUTH',
                action='LOGIN_EXITOSO',
                details=f"Ingreso exitoso al sistema de {user['full_name']} con rol '{user['role']}'.",
                user_override=user['username']
            )
            
            # Si el usuario tiene obligacion de cambiar su clave provisoria
            if user.get('must_change_password') == 1:
                # Emite aviso preventivo
                flash('Por motivos de seguridad, debe definir una nueva contraseña personal antes de continuar.', 'info')
                # Redirige de forma obligatoria a la pantalla de cambio de clave
                return redirect(url_for('dashboard.change_password'))
            
            # Redireccion inteligente segun el rol asignado
            if user['role'] == 'usuario':
                # Rol usuario: va directamente a la pantalla de carga operativa de produccion
                flash(f"Bienvenido/a {user['full_name']}. Acceso a Carga de Producción, Stock y Laboratorio.", 'success')
                return redirect(url_for('production.index'))
            elif user['role'] == 'mantenimiento':
                # Rol mantenimiento: va directamente al panel de mantenimiento industrial y pañol
                flash(f"Bienvenido/a {user['full_name']}. Acceso al Módulo de Mantenimiento Industrial y Pañol.", 'success')
                return redirect(url_for('maintenance.index'))
            else:
                # Roles administrador, gerencia y admin_sistema: van al Dashboard Ejecutivo
                flash(f"Bienvenido/a {user['full_name']} ({user['role'].capitalize()}).", 'success')
                return redirect(url_for('dashboard.index'))
        else:
            # Registra intento fallido en la auditoria del sistema
            err_msg = auth_result.get('message', 'Credenciales incorrectas.')
            record_audit_event(
                category='AUTH',
                action='LOGIN_FALLIDO',
                details=f"Intento fallido para '{identifier}': {err_msg}",
                status='ADVERTENCIA',
                user_override=identifier
            )
            # Emite alerta con el motivo especifico del fallo
            flash(err_msg, 'danger')
            
    # Si es peticion GET, renderiza el formulario de login
    return render_template('login.html')

# Cierre de sesion del usuario con auditoria
@dashboard_bp.route('/logout', methods=['GET'])
def logout():
    # Obtiene el nombre del usuario saliente si existiera
    user_name = session.get('username', 'anonimo')
    # Registra el evento de salida en la auditoria
    record_audit_event('AUTH', 'LOGOUT', f'Cierre de sesión de {user_name}.', user_override=user_name)
    # Limpia todas las variables de la sesion
    session.clear()
    # Notifica salida confirmada
    flash('Sesión cerrada correctamente.', 'info')
    # Redirige a la pantalla de login
    return redirect(url_for('dashboard.login'))

# Pantalla informativa Acerca de con datos institucionales de la empresa puntoAR
@dashboard_bp.route('/about', methods=['GET'])
def about():
    # Renderiza la vista Acerca de con el estilo inmersivo de login
    return render_template('about.html')

# Registro publico de nuevos usuarios
@dashboard_bp.route('/register', methods=['GET', 'POST'])
def register():
    # Si el formulario fue enviado
    if request.method == 'POST':
        # Obtiene los datos del formulario
        full_name = request.form.get('full_name', '').strip()
        dni = request.form.get('dni', '').strip()
        phone = request.form.get('phone', '').strip()
        password = request.form.get('password', '').strip()
        password_confirm = request.form.get('password_confirm', '').strip()
        
        # Validacion de campos obligatorios
        if not full_name or not dni or not phone or not password:
            flash('Todos los campos son obligatorios para registrar su solicitud.', 'danger')
            return render_template('register.html')
            
        # Validacion de coincidencia de contrasenas
        if password != password_confirm:
            flash('Las contraseñas ingresadas no coinciden. Verifique ambas casillas.', 'danger')
            return render_template('register.html')
            
        # Validacion de longitud minima de contrasena
        if len(password) < 4:
            flash('La contraseña debe contener al menos 4 caracteres.', 'danger')
            return render_template('register.html')
            
        # Intenta registrar el nuevo usuario
        try:
            # Registra al usuario en estado pendiente de aprobacion
            register_user(full_name, dni, phone, password)
            # Notifica que la solicitud fue enviada y aguarda aprobacion
            flash('Su solicitud de registro ha sido enviada con éxito. El Administrador del Sistema revisará sus datos y asignará su nivel de acceso.', 'success')
            # Redirige a la pantalla de login
            return redirect(url_for('dashboard.login'))
        except ValueError as ve:
            # Emite mensaje si el DNI ya se encuentra registrado
            flash(str(ve), 'danger')
            return render_template('register.html')
        except Exception as e:
            # Registra error no previsto
            log_error('AUTH_REGISTER', 'Error inesperado durante registro de usuario', e)
            flash(f'Ocurrió un error al procesar el registro: {str(e)}', 'danger')
            return render_template('register.html')
            
    # Si es GET, muestra el formulario de registro
    return render_template('register.html')

# Solicitud de recuperacion de contrasena
@dashboard_bp.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    # Si el usuario envia su identificador para recuperar clave
    if request.method == 'POST':
        # Obtiene el dato ingresado (DNI, usuario o telefono)
        ident = request.form.get('identifier', '').strip()
        
        # Busca el usuario en la base de datos
        with get_db_connection() as conn:
            user = conn.execute("""
                SELECT id, username, full_name, dni, phone, approval_status, is_active
                FROM users
                WHERE (dni = ? OR username = ? OR phone = ?)
                LIMIT 1;
            """, (ident, ident, ident)).fetchone()
            
        # Si el usuario no fue hallado
        if not user:
            flash('No se encontró ninguna cuenta asociada al DNI, usuario o teléfono ingresado.', 'danger')
            return render_template('forgot_password.html')
            
        # Si la cuenta no esta activa o aprobada
        if user['approval_status'] != 'aprobado' or not user['is_active']:
            flash('La cuenta indicada no se encuentra activa o no fue aprobada por el Administrador.', 'warning')
            return render_template('forgot_password.html')
            
        # Genera el codigo OTP numerico de 6 digitos
        otp_code = generate_otp_code(user['id'])
        
        # Formatea el telefono para el enlace de WhatsApp
        raw_phone = ''.join(c for c in str(user['phone']) if c.isdigit())
        # Si no tiene codigo de pais Argentina 54, lo agrega
        if not raw_phone.startswith('54') and len(raw_phone) == 10:
            clean_phone = '549' + raw_phone
        elif not raw_phone.startswith('54'):
            clean_phone = '54' + raw_phone
        else:
            clean_phone = raw_phone
            
        # Mensaje formateado para el envio por WhatsApp
        msg_text = f"Control de Planta: Hola {user['full_name']}, su código de recuperación de contraseña es: *{otp_code}*. Válido por 15 minutos."
        # Codifica la URL de wa.me
        wa_url = f"https://wa.me/{clean_phone}?text={urllib.parse.quote(msg_text)}"
        
        # Guarda temporalmente el ID de usuario en sesion para la validacion del codigo
        session['reset_user_id'] = user['id']
        session['reset_phone'] = user['phone']
        session['reset_full_name'] = user['full_name']
        session['reset_wa_url'] = wa_url
        session['reset_otp_preview'] = otp_code
        
        # Registra el evento en auditoria
        record_audit_event(
            category='AUTH',
            action='SOLICITUD_OTP',
            details=f"Generado código OTP para recuperación de contraseña de {user['full_name']} (DNI {user['dni']}).",
            user_override=user['username']
        )
        
        # Notifica generacion del codigo
        flash(f"Código de recuperación de 6 dígitos generado para {user['full_name']}. Puede enviarlo vía WhatsApp haciendo clic en el botón o ingresarlo directamente.", 'info')
        # Redirige a la pantalla de ingreso del codigo OTP
        return redirect(url_for('dashboard.verify_reset_code'))
        
    # Si es GET, muestra la pantalla de solicitud
    return render_template('forgot_password.html')

# Verificacion del codigo OTP de 6 digitos y entrega de contrasena provisoria
@dashboard_bp.route('/verify-reset-code', methods=['GET', 'POST'])
def verify_reset_code():
    # Obtiene el usuario pendiente en sesion
    user_id = session.get('reset_user_id')
    # Si no hay sesion de restablecimiento activa
    if not user_id:
        flash('La sesión de recuperación ha expirado o es inválida. Inicie el proceso nuevamente.', 'warning')
        return redirect(url_for('dashboard.forgot_password'))
        
    # Si el usuario envia el codigo de 6 digitos
    if request.method == 'POST':
        # Extrae el codigo ingresado
        code = request.form.get('code', '').strip()
        
        # Verifica la validez del codigo
        if verify_otp_code(user_id, code):
            # Genera una nueva contrasena segura provisoria
            temp_password = generate_secure_password(length=8)
            # Actualiza la clave en base de datos con obligacion de cambio en el primer ingreso
            reset_user_password(user_id, temp_password, must_change=True)
            
            # Obtiene los datos del usuario
            with get_db_connection() as conn:
                user = conn.execute("SELECT * FROM users WHERE id = ?;", (user_id,)).fetchone()
                
            # Limpia los datos de sesion de recuperacion
            session.pop('reset_user_id', None)
            wa_url = session.pop('reset_wa_url', None)
            
            # Registra la recuperacion exitosa en auditoria
            record_audit_event(
                category='AUTH',
                action='RECUPERACION_EXITOSA',
                details=f"Contraseña provisoria generada exitosamente mediante código OTP para {user['full_name']}.",
                user_override=user['username']
            )
            
            # Prepara mensaje opcional de WhatsApp con la nueva clave provisoria
            raw_phone = ''.join(c for c in str(user['phone']) if c.isdigit())
            if not raw_phone.startswith('54') and len(raw_phone) == 10:
                clean_phone = '549' + raw_phone
            else:
                clean_phone = raw_phone
            pwd_msg = f"Control de Planta: Hola {user['full_name']}, su nueva contraseña provisoria de acceso es: *{temp_password}*. Recuerde que deberá cambiarla en su primer ingreso."
            wa_pwd_url = f"https://wa.me/{clean_phone}?text={urllib.parse.quote(pwd_msg)}"
            
            # Renderiza la pantalla de confirmacion de clave provisoria
            return render_template(
                'reset_success.html',
                temp_password=temp_password,
                user=dict(user),
                wa_pwd_url=wa_pwd_url
            )
        else:
            # Emite advertencia de codigo invalido o vencido
            flash('El código de 6 dígitos ingresado es incorrecto o ha expirado (validez: 15 minutos). Verifique e intente nuevamente.', 'danger')
            
    # Si es GET, renderiza la pantalla de ingreso de codigo
    return render_template(
        'verify_code.html',
        phone=session.get('reset_phone'),
        full_name=session.get('reset_full_name'),
        wa_url=session.get('reset_wa_url'),
        otp_preview=session.get('reset_otp_preview')
    )

# Pantalla de cambio de contrasena (obligatoria o voluntaria)
@dashboard_bp.route('/change-password', methods=['GET', 'POST'])
@login_required
def change_password():
    # Si se envia el formulario de cambio
    if request.method == 'POST':
        # Extrae datos del formulario
        current_pin = request.form.get('current_pin', '').strip()
        new_pin = request.form.get('new_pin', '').strip()
        confirm_pin = request.form.get('confirm_pin', '').strip()
        
        # Valida que la clave actual coincida con la registrada
        if current_pin != g.user['pin']:
            flash('La contraseña actual ingresada es incorrecta.', 'danger')
            return render_template('change_password.html')
            
        # Valida coincidencia entre nueva clave y confirmacion
        if new_pin != confirm_pin:
            flash('La nueva contraseña y su repetición no coinciden.', 'danger')
            return render_template('change_password.html')
            
        # Valida longitud minima
        if len(new_pin) < 4:
            flash('La nueva contraseña debe tener al menos 4 caracteres.', 'danger')
            return render_template('change_password.html')
            
        # Actualiza la contrasena y desactiva el flag de cambio obligatorio
        reset_user_password(g.user['id'], new_pin, must_change=False)
        
        # Registra el cambio en la auditoria
        record_audit_event(
            category='AUTH',
            action='CAMBIO_PASSWORD',
            details=f"El usuario {g.user['full_name']} actualizó exitosamente su contraseña personal.",
            user_override=g.user['username']
        )
        
        # Notifica exito
        flash('Su contraseña ha sido actualizada con éxito.', 'success')
        
        # Redirige segun el rol del usuario
        if g.user['role'] == 'usuario':
            return redirect(url_for('production.index'))
        else:
            return redirect(url_for('dashboard.index'))
            
    # Si es GET, muestra el formulario de cambio de clave
    return render_template('change_password.html')

# Vista principal del Dashboard Administrativo Ejecutivo en un solo golpe de vista
@dashboard_bp.route('/', methods=['GET'])
@roles_required('gerencia', 'administrador', 'admin_sistema')
def index():
    # Obtiene parametro de turnos seleccionados (ej: 'all', 'TM', 'TT', 'TN', o 'TM,TT')
    shifts_param = request.args.get('shifts', 'all').strip()
    # Obtiene parametros de fecha (dia puntual, rango desde/hasta o mes completo)
    date_param = request.args.get('date', '').strip() or None
    start_date_param = request.args.get('start_date', '').strip() or None
    end_date_param = request.args.get('end_date', '').strip() or None
    month_param = request.args.get('month', '').strip() or None

    # Obtiene el paquete completo de datos consolidados segun los filtros
    data = get_executive_dashboard_data(
        selected_shifts=shifts_param,
        target_date=date_param,
        start_date=start_date_param,
        end_date=end_date_param,
        month=month_param
    )
    # Renderiza la plantilla del dashboard
    return render_template(
        'dashboard.html',
        data=data,
        selected_shifts_param=shifts_param,
        selected_date_param=date_param,
        selected_start_date=start_date_param,
        selected_end_date=end_date_param,
        selected_month_param=month_param
    )

# Vista de gestion y cambio de turno operativo
@dashboard_bp.route('/shifts', methods=['GET', 'POST'])
@login_required
def shifts():
    # Si se envio cambio de turno
    if request.method == 'POST':
        shift_id = request.form.get('shift_id')
        operator_name = request.form.get('operator_name')
        if shift_id and operator_name:
            try:
                # Intenta actualizar el turno validando permisos si es Turno Central
                set_active_shift(shift_id, operator_name, user_role=g.user.get('role'))
                # Registra el cambio de guardia en auditoria
                record_audit_event('PRODUCCION', 'CAMBIO_TURNO', f"Guardia asignada a {shift_id} a cargo de {operator_name}.")
                flash(f'Guardia actualizada: {shift_id} a cargo de {operator_name}.', 'success')
                # Redirige segun rol
                if g.user['role'] == 'usuario':
                    return redirect(url_for('production.index'))
                return redirect(url_for('dashboard.index'))
            except PermissionError as pe:
                # Emite error si un operario intenta tomar el Turno Central reservado para Admin
                flash(str(pe), 'danger')
    # Obtiene turno activo
    active_shift = get_active_shift()
    # Obtiene la lista de turnos autorizados segun el perfil del usuario
    available_shifts = get_available_shifts(user_role=g.user.get('role'))
    # Renderiza pantalla de turnos con los turnos disponibles
    return render_template('shifts.html', active_shift=active_shift, available_shifts=available_shifts)

# Endpoint API JSON para actualizacion automatica de KPIs en pantallas de planta o celular
@dashboard_bp.route('/api/kpis', methods=['GET'])
@roles_required('gerencia', 'administrador', 'admin_sistema')
def api_kpis():
    # Obtiene parametros de turnos y fecha
    shifts_param = request.args.get('shifts', 'all').strip()
    date_param = request.args.get('date', '').strip() or None
    start_date_param = request.args.get('start_date', '').strip() or None
    end_date_param = request.args.get('end_date', '').strip() or None
    month_param = request.args.get('month', '').strip() or None

    # Retorna los datos ejecutivos en formato JSON
    return jsonify(get_executive_dashboard_data(
        selected_shifts=shifts_param,
        target_date=date_param,
        start_date=start_date_param,
        end_date=end_date_param,
        month=month_param
    ))
