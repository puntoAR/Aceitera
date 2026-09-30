# Modulo puente de compatibilidad para autenticacion y seguridad
from core.security import ( # Importa funciones de seguridad desde core.security
    authenticate_user, # Funcion de autenticacion de credenciales
    register_user, # Funcion de registro publico de nuevos usuarios
    create_user, # Funcion de alta directa de usuario
    reset_user_password, # Funcion de blanqueo o reseteo de claves
    generate_secure_password, # Generador de contrasenas temporales seguras
    generate_otp_code, # Generador de codigos OTP
    verify_otp_code, # Validador de codigos OTP
    has_module_access, # Validador de permisos por modulo
    get_user_allowed_modules, # Consulta de modulos permitidos
    roles_required, # Decorador de control de acceso por rol
    load_logged_in_user # Middleware de sesion de usuario
) # Cierra bloque de importacion
