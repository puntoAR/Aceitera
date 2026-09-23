# Servicio logico para la aplicacion de actualizaciones in-place sin reinstalar
# Importa zipfile para descompresion de paquetes de actualizacion
import zipfile
# Importa os y sys para operaciones en el arbol de archivos
import os
import sys
# Importa shutil para mover y limpiar directorios temporales
import shutil
# Importa json para manipular manifiestos de version
import json
# Importa subprocess para ejecutar la suite de diagnostico independiente
import subprocess

# Importa requests para realizar consultas HTTP/HTTPS salientes al servidor de versiones
import requests
# Importa hashlib para verificar la integridad criptografica SHA-256 de los parches
import hashlib

# Importa variables de configuracion
from config import BASE_DIR, DATABASE_PATH, DEFAULT_UPDATE_SERVER_URL
# Importa el gestor de respaldos preventivos y restauracion
from core.backup_manager import create_backup, restore_backup
# Importa el motor de migraciones
from core.migrations import apply_pending_migrations
# Importa logger de auditoria
from core.error_logger import log_info, log_error

# Obtiene la informacion de la version actual del software desde version.json
def get_current_version_info():
    version_file = os.path.join(BASE_DIR, 'version.json')
    if os.path.exists(version_file):
        with open(version_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {
        'version': '1.0.0',
        'release_date': '2026-09-21',
        'app_name': 'BioBalcarce Control Industrial',
        'changelog': []
    }

# Aplica un paquete de actualizacion en caliente (archivo ZIP o directorio)
def apply_update_package(source_path):
    # Verifica que la fuente de actualizacion exista en disco
    if not os.path.exists(source_path):
        raise FileNotFoundError(f"No se encontro el archivo o carpeta de actualizacion: {source_path}")

    # Carpeta temporal de extraccion y verificacion previa
    staging_dir = os.path.join(BASE_DIR, 'temp_update_staging')
    if os.path.exists(staging_dir):
        shutil.rmtree(staging_dir)
    os.makedirs(staging_dir, exist_ok=True)

    # 1. Extraccion del paquete a la zona temporal
    if zipfile.is_zipfile(source_path):
        with zipfile.ZipFile(source_path, 'r') as zip_ref:
            zip_ref.extractall(staging_dir)
    elif os.path.isdir(source_path):
        shutil.copytree(source_path, staging_dir, dirs_exist_ok=True)
    else:
        shutil.rmtree(staging_dir)
        raise ValueError("El paquete debe ser un archivo ZIP valido o una carpeta de actualizacion.")

    # 2. Verificacion de manifiesto de version en el paquete
    new_version_file = os.path.join(staging_dir, 'version.json')
    target_version = "desconocida"
    if os.path.exists(new_version_file):
        with open(new_version_file, 'r', encoding='utf-8') as f:
            target_version = json.load(f).get('version', 'actualizada')

    # 3. Creacion obligatoria de respaldo de seguridad antes de modificar nada
    backup_path = create_backup(label=f"pre_update_{target_version}")

    # Bloque de aplicacion protegida con rollback automatico en caso de error
    try:
        # 4. Despliegue seguro de archivos in-place (excluyendo data/ y logs/ para preservar la base de datos)
        for root, dirs, files in os.walk(staging_dir):
            # Obtiene la ruta relativa respecto a staging_dir
            rel_path = os.path.relpath(root, staging_dir)
            # Ignora si se intenta sobreescribir la carpeta data o logs
            if rel_path.startswith('data') or rel_path.startswith('logs') or rel_path.startswith('backups'):
                continue
            # Destino en el directorio de la aplicacion
            dest_dir = os.path.join(BASE_DIR, rel_path) if rel_path != '.' else BASE_DIR
            os.makedirs(dest_dir, exist_ok=True)
            # Copia cada archivo modificado
            for file_name in files:
                # No permite nunca sobreescribir el archivo de base de datos
                if file_name.endswith('.db'):
                    continue
                src_file_path = os.path.join(root, file_name)
                dst_file_path = os.path.join(dest_dir, file_name)
                shutil.copy2(src_file_path, dst_file_path)

        # 5. Ejecuta migraciones de esquema pendientes sin tocar datos existentes
        migrations_applied = apply_pending_migrations()
        log_info('UPDATER', f'Se aplicaron {migrations_applied} migraciones de base de datos.')

        # 6. Certificacion automatica de salud con el diagnosticador independiente
        diag_script = os.path.join(BASE_DIR, 'diagnostics', 'system_diagnostics.py')
        diag_result = subprocess.run([sys.executable, diag_script], capture_output=True, text=True)

        # Si el diagnosticador detecta cualquier anomalia (codigo distinto de 0)
        if diag_result.returncode != 0:
            # Emite error y gatilla el rollback preventivo inmediato
            log_error('UPDATER', f'Fallo de diagnostico post-actualizacion. Iniciando Rollback automatico.\n{diag_result.stdout}')
            restore_backup(backup_path)
            raise RuntimeError(f"La actualizacion no supero la auditoria de salud del sistema. Se ejecuto un Rollback automatico al estado anterior seguro. Detalle:\n{diag_result.stdout}")

        # 7. Limpia la carpeta temporal de staging
        shutil.rmtree(staging_dir)
        # Registra exito de actualizacion
        log_info('UPDATER', f'Sistema actualizado con exito a la version {target_version} sin reinstalar.')
        return {
            'success': True,
            'version': target_version,
            'backup_created': backup_path,
            'migrations_applied': migrations_applied
        }

    except Exception as e:
        # Limpia staging
        if os.path.exists(staging_dir):
            shutil.rmtree(staging_dir)
        # Si no fue el error de rollback previo, ejecuta restauracion
        if "Rollback automatico" not in str(e):
            log_error('UPDATER', 'Excepcion durante actualizacion. Ejecutando Rollback de emergencia.', e)
            restore_backup(backup_path)
        # Relanza el error para notificar al usuario
        raise e

# Convierte una cadena de version semantica "1.2.3" en tupla de enteros (1, 2, 3) para comparacion matematica
def parse_version_tuple(version_str):
    # Elimina espacios y prefijos como 'v'
    clean_ver = str(version_str).strip().lstrip('v')
    # Extrae solo digitos de cada componente
    parts = []
    for p in clean_ver.split('.'):
        if p.isdigit():
            parts.append(int(p))
    # Asegura al menos tres numeros (major, minor, patch)
    while len(parts) < 3:
        parts.append(0)
    # Retorna tupla de 3 enteros
    return tuple(parts[:3])

# Consulta el servidor remoto para verificar si existe una nueva version disponible
def check_for_remote_updates(update_url=None):
    # Usa la URL provista o la configurada por defecto
    target_url = update_url or DEFAULT_UPDATE_SERVER_URL
    # Obtiene version instalada
    current_info = get_current_version_info()
    current_ver = current_info.get('version', '1.0.0')
    curr_tuple = parse_version_tuple(current_ver)

    try:
        # Registra en log la busqueda de parches
        log_info('UPDATER', f'Consultando servidor de actualizaciones en {target_url}')
        # Realiza peticion GET con tiempo maximo de 5 segundos para evitar colgar la interfaz
        resp = requests.get(target_url, timeout=5)
        # Si el servidor responde con error HTTP
        if resp.status_code != 200:
            return {
                'success': False,
                'error': f'El servidor de actualizaciones respondio con codigo HTTP {resp.status_code}.',
                'current_version': current_ver
            }
        # Parsea el JSON del manifiesto remoto
        data = resp.json()
        remote_ver = data.get('version', current_ver)
        remote_tuple = parse_version_tuple(remote_ver)
        # Compara versiones: True si la remota es mayor a la instalada
        update_available = remote_tuple > curr_tuple

        # Retorna el estado completo
        return {
            'success': True,
            'update_available': update_available,
            'current_version': current_ver,
            'remote_version': remote_ver,
            'release_date': data.get('release_date', 'N/D'),
            'changelog': data.get('changelog', []),
            'download_url': data.get('download_url', ''),
            'sha256': data.get('sha256', ''),
            'description': data.get('description', '')
        }
    except requests.exceptions.Timeout:
        # Manejo amigable de timeout por internet lento
        return {
            'success': False,
            'error': 'Tiempo de espera agotado al conectar con el servidor remoto. Verifique la conexion a internet de la planta.',
            'current_version': current_ver
        }
    except Exception as e:
        # Manejo general de excepciones de conexion
        return {
            'success': False,
            'error': f'No se pudo consultar actualizaciones remotas: {str(e)}',
            'current_version': current_ver
        }

# Descarga un paquete remoto de actualizacion, verifica su hash SHA-256 y lo aplica in-place
def download_and_apply_remote_update(download_url, expected_sha256=None):
    # Valida que la URL no este vacia
    if not download_url:
        raise ValueError("URL de descarga no provista o vacia.")

    # Directorio temporal de descarga
    temp_dir = os.path.join(BASE_DIR, 'temp_download')
    os.makedirs(temp_dir, exist_ok=True)
    zip_dest_path = os.path.join(temp_dir, 'remote_update_package.zip')

    try:
        # Registra el inicio de descarga
        log_info('UPDATER', f'Iniciando descarga segura de parche desde {download_url}')
        # Descarga por streaming con timeout de 30 segundos
        resp = requests.get(download_url, stream=True, timeout=30)
        resp.raise_for_status()

        # Acumulador de hash criptografico SHA-256
        sha256_hash = hashlib.sha256()
        # Escribe los bloques en disco y calcula el hash simultaneamente
        with open(zip_dest_path, 'wb') as f:
            for chunk in resp.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
                    sha256_hash.update(chunk)

        # Hash calculado del archivo descargado
        calculated_sha = sha256_hash.hexdigest()
        # Si se especifico un hash esperado en el manifiesto
        if expected_sha256 and expected_sha256.strip():
            # Si no coinciden exactamente
            if calculated_sha.lower() != expected_sha256.strip().lower():
                raise ValueError(f"Fallo de integridad criptografica: el hash SHA-256 no coincide (Esperado: {expected_sha256}, Calculado: {calculated_sha}). Descarga cancelada por seguridad.")

        # Aplica el archivo ZIP utilizando el motor de despliegue, respaldo y migracion existente
        res = apply_update_package(zip_dest_path)
        return res
    finally:
        # Limpia siempre el directorio temporal de descarga
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)
