# Archivo principal de ejecucion y arranque del servidor web industrial BioBalcarce
# Importa sys y os para configurar el entorno de ejecucion
import sys
import os

# Agrega la ruta raiz de la aplicacion al path del interprete
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

# Importa variables de configuracion (auto-vincula el entorno virtual local si existe)
from config import SECRET_KEY, PORT, HOST, DEBUG, MAINTENANCE_UPLOADS_DIR

# Bloque de captura para verificar disponibilidad de Flask
try:
    # Importa componentes principales de Flask para el servidor web y PWA
    from flask import Flask, render_template, redirect, url_for, g, send_from_directory, make_response, flash
except ModuleNotFoundError:
    print("\n[ERROR CRITICO] Flask no esta instalado en este entorno de Python.")
    print(f"Python actual: {sys.executable}")
    print("Para solucionarlo ejecute:")
    print("  .venv\\Scripts\\pip install -r requirements.txt")
    print("o inicie el sistema utilizando: iniciar_sistema.bat\n")
    sys.exit(1)
# Importa inicializador de base de datos
from core.database import init_db
# Importa funcion para cargar el usuario logueado en g.user y validador de permisos de modulos
from core.security import load_logged_in_user, has_module_access
# Importa el registrador de eventos
from core.error_logger import log_info, log_error
# Importa gestor de politicas de licenciamiento y verificacion de actualizaciones
from core.licensing import get_licensing_status
from modules.updater.service import check_system_update_status

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
# Importa el blueprint de mantenimiento industrial y pañol de repuestos
from modules.maintenance.routes import maintenance_bp
# Importa el blueprint de balanza de camiones (registro, importacion y exportacion)
from modules.weighbridge.routes import weighbridge_bp
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

    # Verificacion elegante de politicas de licenciamiento (trial, bloqueos o expiracion)
    if hasattr(g, 'user') and g.user:
        # Rutas exentas para gestion administrativa, autenticacion y estaticos
        exempt_prefixes = ('/config', '/auth', '/static', '/change-password', '/logout')
        is_exempt = any(request.path.startswith(p) for p in exempt_prefixes)

        if not is_exempt:
            try:
                lic_status = get_licensing_status()
                restr = lic_status.get('restrictions', {})

                # 1. Restriccion de carga o modificacion de datos nuevos
                if restr.get('block_data_entry') and request.method == 'POST':
                    if g.user.get('role') != 'admin_sistema':
                        flash(f"Operación suspendida: La carga de nuevos registros se encuentra restringida por políticas de licenciamiento ({lic_status.get('status_label')}). Contacte a soporte de puntoAR para regularizar la suscripción.", "warning")
                        return redirect(request.referrer or url_for('dashboard.index'))

                # 2. Restriccion de descarga de reportes y exportaciones
                if restr.get('block_reports') and ('/export' in request.path or '/report' in request.path):
                    if g.user.get('role') != 'admin_sistema':
                        flash(f"Exportación restringida: La generación de reportes y descargas está deshabilitada en el estado actual de la licencia ({lic_status.get('status_label')}).", "warning")
                        return redirect(request.referrer or url_for('dashboard.index'))

                # 3. Restriccion de aplicacion de actualizaciones
                if restr.get('block_updates') and request.path.startswith('/config/updates/install'):
                    flash("La instalación de nuevas actualizaciones se encuentra deshabilitada según las políticas de licenciamiento vigentes.", "warning")
                    return redirect(url_for('updater.index'))
            except Exception as e:
                log_error('LICENSING_MIDDLEWARE', 'Fallo al evaluar restricciones de licencia', e)

# Inyecta variables de sistema (licenciamiento y actualizaciones) a todas las plantillas Jinja2
@app.context_processor
def inject_system_context():
    try:
        licensing = get_licensing_status()
    except Exception:
        licensing = None
    try:
        update_status = check_system_update_status()
    except Exception:
        update_status = {'available': False}
    return {
        'licensing_info': licensing,
        'system_update': update_status,
        'has_module_access': has_module_access
    }


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
# Registra el blueprint de mantenimiento industrial y pañol de repuestos
app.register_blueprint(maintenance_bp)
# Registra el blueprint de balanza de camiones
app.register_blueprint(weighbridge_bp)

# Ruta publica para servir el manifiesto PWA que permite la instalacion en celulares
@app.route('/manifest.json')
def manifest_json():
    # Retorna el archivo manifest.json desde static con el mimetype oficial de aplicacion web
    return send_from_directory('static', 'manifest.json', mimetype='application/manifest+json')

# Ruta publica para servir el Service Worker con alcance global en toda la aplicacion
@app.route('/sw.js')
def service_worker_js():
    # Obtiene la respuesta enviando el archivo sw.js desde static/js
    response = make_response(send_from_directory(os.path.join('static', 'js'), 'sw.js', mimetype='application/javascript'))
    # Cabecera que permite al Service Worker interceptar rutas en la raiz /
    response.headers['Service-Worker-Allowed'] = '/'
    # Retorna la respuesta configurada
    return response

# Ruta publica para servir fotografias de intervenciones de mantenimiento
@app.route('/static/uploads/maintenance/<path:filename>')
def serve_maintenance_upload(filename):
    # Si el archivo existe físicamente en disco, lo envía directamente
    disk_path = os.path.join(MAINTENANCE_UPLOADS_DIR, filename)
    if os.path.isfile(disk_path):
        return send_from_directory(MAINTENANCE_UPLOADS_DIR, filename)
    # Si no existe en disco (entornos serverless como Vercel), consulta la base de datos
    try:
        from modules.maintenance.service import get_maintenance_image_data, get_placeholder_image_svg
        img_bytes, mime_type = get_maintenance_image_data(filename)
        if img_bytes:
            resp = make_response(img_bytes)
            resp.headers['Content-Type'] = mime_type or 'image/jpeg'
            resp.headers['Cache-Control'] = 'public, max-age=31536000, immutable'
            return resp
        # Si no existe en base de datos, sirve un SVG placeholder elegante
        svg_bytes, svg_mime = get_placeholder_image_svg()
        resp = make_response(svg_bytes)
        resp.headers['Content-Type'] = svg_mime
        resp.headers['Cache-Control'] = 'public, max-age=86400'
        return resp
    except Exception:
        return send_from_directory(MAINTENANCE_UPLOADS_DIR, filename)

# Inicializa la base de datos y esquemas relacionales al cargar la aplicacion (compatible con Vercel)
with app.app_context():
    # Bloque protegido para inicializar base de datos sin abortar el contenedor en fallos transitorios
    try:
        # Verifica y crea las tablas si no existen
        init_db()
        # Aplica las migraciones de esquema incrementales
        apply_pending_migrations()
    # Captura cualquier error de conectividad o arranque en base de datos
    except Exception as startup_db_err:
        # Registra la excepcion en el log de auditoria de errores
        log_error('DATABASE_STARTUP', 'Fallo al inicializar base de datos en arranque', startup_db_err)

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
