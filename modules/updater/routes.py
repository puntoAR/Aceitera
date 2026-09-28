# Rutas web del modulo de actualizacion y respaldos
# Importa componentes de Flask para rutas, formularios, subida de archivos y mensajes
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
# Importa decoradores de seguridad por roles
from core.security import roles_required
# Importa servicios de actualizacion, respaldos y migraciones
from modules.updater.service import (
    get_current_version_info, apply_update_package,
    check_for_remote_updates, download_and_apply_remote_update,
    get_pending_local_update, apply_pending_local_update
)
from core.backup_manager import list_backups, create_backup, restore_backup
from core.migrations import get_migration_history
# Importa logger
from core.error_logger import log_error, log_info
# Importa auditoria de eventos
from core.audit import record_audit_event
# Importa os y werkzeug para guardar archivos subidos temporalmente
import os
from werkzeug.utils import secure_filename
from config import BASE_DIR, DEFAULT_UPDATE_SERVER_URL

# Define el Blueprint de actualizaciones
updater_bp = Blueprint('updater', __name__, url_prefix='/config/updates')

# Vista principal del centro de actualizaciones y respaldos
@updater_bp.route('/', methods=['GET'])
@roles_required('admin_sistema')
def index():
    # Obtiene version actual del sistema
    version_info = get_current_version_info()
    # Obtiene la lista de respaldos disponibles
    backups = list_backups()
    # Obtiene el historial de migraciones de base de datos
    migrations = get_migration_history()
    # Obtiene si hay una actualizacion local comprobada pendiente
    pending_update = get_pending_local_update()
    # Renderiza la plantilla de actualizaciones
    return render_template('updates.html', version_info=version_info, backups=backups,
                           migrations=migrations, pending_update=pending_update)

# Endpoint para aceptar e instalar una actualizacion local comprobada
@updater_bp.route('/install-pending', methods=['POST'])
@roles_required('admin_sistema')
def install_pending():
    filename = request.form.get('filename')
    try:
        if not filename:
            flash('No se especificó el archivo de actualización a instalar.', 'warning')
            return redirect(url_for('updater.index'))

        result = apply_pending_local_update(filename)
        record_audit_event('SISTEMA', 'ACTUALIZACION_LOCAL_COMPROBADA', f"Actualización comprobada aplicada a versión {result['version']}.")
        flash(f'¡Actualización v{result["version"]} instalada exitosamente con respaldo previo y migraciones automáticas!', 'success')
    except Exception as e:
        log_error('UPDATER_ROUTE', f'Error al instalar actualización local {filename}', e)
        flash(f'Error al instalar actualización comprobada: {str(e)}', 'danger')
    return redirect(url_for('updater.index'))

# Endpoint para subir y aplicar un paquete ZIP de actualizacion
@updater_bp.route('/upload', methods=['POST'])
@roles_required('admin_sistema')
def upload_update():
    # Bloque de captura de errores
    try:
        # Verifica si se envio el archivo
        if 'update_file' not in request.files:
            flash('No se seleccionó ningún archivo de actualización.', 'warning')
            return redirect(url_for('updater.index'))

        file = request.files['update_file']
        if file.filename == '':
            flash('Nombre de archivo vacío.', 'warning')
            return redirect(url_for('updater.index'))

        # Asegura nombre de archivo valido
        filename = secure_filename(file.filename)
        temp_dir = os.path.join(BASE_DIR, 'temp_upload')
        os.makedirs(temp_dir, exist_ok=True)
        temp_file_path = os.path.join(temp_dir, filename)
        # Guarda el archivo en disco
        file.save(temp_file_path)

        # Aplica el paquete mediante el servicio
        result = apply_update_package(temp_file_path)
        # Elimina el archivo temporal
        if os.path.exists(temp_file_path):
            os.remove(temp_file_path)

        # Registra en auditoria
        record_audit_event('SISTEMA', 'ACTUALIZACION_APLICADA', f"Actualización local aplicada exitosamente a versión {result['version']}.")
        # Notifica exito
        flash(f'Actualización a versión {result["version"]} aplicada exitosamente sin reinstalar.', 'success')
    except Exception as e:
        log_error('UPDATER_ROUTE', 'Fallo al procesar paquete de actualizacion', e)
        flash(f'Error durante la actualización: {str(e)}', 'danger')

    return redirect(url_for('updater.index'))

# Endpoint para generar una copia de seguridad manual en cualquier momento
@updater_bp.route('/backup-now', methods=['POST'])
@roles_required('admin_sistema')
def manual_backup():
    try:
        label = request.form.get('label', 'manual')
        backup_path = create_backup(label=label)
        record_audit_event('SISTEMA', 'BACKUP_CREADO', f"Copia de seguridad manual creada: {label}.")
        flash(f'Copia de seguridad manual creada exitosamente.', 'success')
    except Exception as e:
        log_error('UPDATER_ROUTE', 'Error al crear respaldo manual', e)
        flash(f'Error al crear respaldo: {str(e)}', 'danger')
    return redirect(url_for('updater.index'))

# Endpoint para revertir a un punto de respaldo seguro (Rollback)
@updater_bp.route('/rollback', methods=['POST'])
@roles_required('admin_sistema')
def execute_rollback():
    try:
        backup_folder = request.form.get('backup_folder')
        if not backup_folder:
            flash('Debe seleccionar una copia de seguridad para restaurar.', 'warning')
            return redirect(url_for('updater.index'))

        backup_path = os.path.join(BASE_DIR, 'backups', backup_folder)
        # Ejecuta la restauracion
        restore_backup(backup_path)
        record_audit_event('SISTEMA', 'ROLLBACK_EJECUTADO', f"Restauración realizada a partir de {backup_folder}.")
        flash(f'Sistema restaurado exitosamente a partir de {backup_folder}.', 'info')
    except Exception as e:
        log_error('UPDATER_ROUTE', 'Error durante la restauracion manual de respaldo', e)
        flash(f'Error al restaurar copia: {str(e)}', 'danger')
    return redirect(url_for('updater.index'))

# Endpoint para consultar el servidor remoto en busqueda de actualizaciones
@updater_bp.route('/check-online', methods=['GET', 'POST'])
@roles_required('admin_sistema')
def check_online():
    # Permite especificar una URL personalizada desde el formulario si se desea
    custom_url = request.form.get('update_url') if request.method == 'POST' else None
    # Realiza la consulta remota
    result = check_for_remote_updates(custom_url)
    # Si la consulta fallo (ej. sin conexion)
    if not result.get('success'):
        flash(result.get('error', 'Error al consultar actualizaciones remotas.'), 'warning')
    # Si hay una version nueva disponible
    elif result.get('update_available'):
        flash(f'¡Nueva versión v{result["remote_version"]} disponible! Lanzada el {result["release_date"]}.', 'info')
    # Si el sistema ya esta en la ultima version
    else:
        flash(f'El sistema se encuentra al día con la versión oficial más reciente (v{result["current_version"]}).', 'success')

    # Datos para renderizar la vista
    version_info = get_current_version_info()
    backups = list_backups()
    migrations = get_migration_history()
    return render_template('updates.html', version_info=version_info, backups=backups,
                           migrations=migrations, check_result=result,
                           server_url=custom_url or DEFAULT_UPDATE_SERVER_URL)

# Endpoint para descargar y aplicar automaticamente la actualizacion remota
@updater_bp.route('/install-remote', methods=['POST'])
@roles_required('admin_sistema')
def install_remote():
    try:
        # Extrae la URL de descarga y el hash criptografico del formulario
        download_url = request.form.get('download_url')
        sha256 = request.form.get('sha256')
        # Valida que la URL exista
        if not download_url:
            flash('URL de descarga remota no provista o inválida.', 'warning')
            return redirect(url_for('updater.index'))

        # Descarga, valida hash SHA-256 y aplica el paquete in-place
        result = download_and_apply_remote_update(download_url, sha256)
        record_audit_event('SISTEMA', 'ACTUALIZACION_REMOTA', f"Actualización remota aplicada a versión {result['version']}.")
        # Emite notificacion de exito
        flash(f'¡Sistema actualizado con éxito a la versión v{result["version"]} de forma remota y segura!', 'success')
    except Exception as e:
        # Registra error en log
        log_error('UPDATER_ROUTE', 'Error durante la instalacion remota', e)
        # Emite mensaje de alerta
        flash(f'Error al instalar actualización remota: {str(e)}', 'danger')
    return redirect(url_for('updater.index'))
