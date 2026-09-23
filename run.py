# Archivo principal de ejecucion y arranque del servidor web industrial BioBalcarce
# Importa sys y os para configurar el entorno de ejecucion
import sys
import os

# Agrega la ruta raiz de la aplicacion al path del interprete
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

# Importa variables de configuracion (auto-vincula el entorno virtual local si existe)
from config import SECRET_KEY, PORT, HOST, DEBUG

# Importa Flask, render_template y redirect para estructurar la aplicacion
try:
    from flask import Flask, render_template, redirect, url_for, g
except ModuleNotFoundError:
    print("\n[ERROR CRITICO] Flask no esta instalado en este entorno de Python.")
    print(f"Python actual: {sys.executable}")
    print("Para solucionarlo ejecute:")
    print("  .venv\\Scripts\\pip install -r requirements.txt")
    print("o inicie el sistema utilizando: iniciar_sistema.bat\n")
    sys.exit(1)
# Importa inicializador de base de datos
from core.database import init_db
# Importa funcion para cargar el usuario logueado en g.user
from core.security import load_logged_in_user
# Importa el registrador de eventos
from core.error_logger import log_info, log_error

# Importa los blueprints de cada modulo de negocio independiente
from modules.dashboard.routes import dashboard_bp
from modules.production.routes import production_bp
from modules.inventory.routes import inventory_bp
from modules.laboratory.routes import laboratory_bp
from modules.yield_balance.routes import yield_bp
from modules.configuration.routes import config_bp
from modules.updater.routes import updater_bp
# Importa el blueprint de administracion de usuarios, auditoria y errores
from modules.admin.routes import admin_bp
# Importa request para inspeccionar la ruta solicitada en before_request
from flask import request
# Importa el ejecutor de migraciones automaticas
from core.migrations import apply_pending_migrations

# Crea la instancia de la aplicacion web Flask
app = Flask(__name__)

# Configura la clave secreta para la proteccion de sesiones
app.secret_key = SECRET_KEY

# Habilita la recarga automatica de plantillas HTML ante cualquier cambio
app.config['TEMPLATES_AUTO_RELOAD'] = True

# Registra la funcion de carga de usuario antes de cada peticion HTTP
@app.before_request
def before_request():
    # Carga el usuario logueado en el contexto global de Flask
    load_logged_in_user()
    # Verifica si el usuario logueado tiene pendiente el cambio obligatorio de clave
    if hasattr(g, 'user') and g.user and g.user.get('must_change_password') == 1:
        # Permite acceso unicament a cambio de clave, cierre de sesion y recursos estaticos
        allowed_endpoints = ('dashboard.change_password', 'dashboard.logout', 'static')
        if request.endpoint and request.endpoint not in allowed_endpoints:
            # Redirige forzosamente a la pantalla de cambio de clave
            return redirect(url_for('dashboard.change_password'))

# Registra los blueprints modulares desacoplados
app.register_blueprint(dashboard_bp)
app.register_blueprint(production_bp)
app.register_blueprint(inventory_bp)
app.register_blueprint(laboratory_bp)
app.register_blueprint(yield_bp)
app.register_blueprint(config_bp)
app.register_blueprint(updater_bp)
# Registra el blueprint de administracion
app.register_blueprint(admin_bp)

# Manejador de error HTTP 404 (Pagina no encontrada)
@app.errorhandler(404)
def page_not_found(e):
    # Renderiza la vista de error amigable con codigo 404
    return render_template('error.html', error_code=404, message="La pantalla o recurso solicitado no existe."), 404

# Manejador de error HTTP 500 (Error interno del servidor)
@app.errorhandler(500)
def internal_server_error(e):
    # Registra la excepcion en el log para auditoria
    log_error('SERVER', 'Error interno no capturado en servidor web', e)
    # Renderiza la vista de error amigable con sugerencia de diagnostico
    return render_template('error.html', error_code=500, message="Ha ocurrido un error interno. Puede ejecutar el diagnosticador para conocer la causa."), 500

# Punto de inicio si el archivo se ejecuta directamente
if __name__ == '__main__':
    # Inicializa las tablas de base de datos SQLite y carga datos iniciales
    init_db()
    # Ejecuta migraciones de esquema pendientes sin perdida de informacion
    apply_pending_migrations()
    # Registra en log el arranque del servidor
    log_info('SERVER', f'Iniciando servidor BioBalcarce en http://{HOST}:{PORT}')
    # Imprime mensaje en consola para el usuario
    print(f"\n========================================================")
    print(f" SISTEMA INDUSTRIAL MODULAR BIOBALCARCE INICIADO")
    print(f" Acceso local: http://localhost:{PORT}")
    print(f" Acceso en red planta / celular: http://{HOST}:{PORT}")
    print(f" Diagnostico independiente: python diagnostics/system_diagnostics.py")
    print(f"========================================================\n")
    # Inicia el servidor Flask
    app.run(host=HOST, port=PORT, debug=DEBUG)
