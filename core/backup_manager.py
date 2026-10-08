# Modulo de gestion de respaldos (backups) y restauraciones (rollback) preventivas
# Permite resguardar y recuperar el sistema antes y despues de cada actualizacion

# Importa os y sys para operaciones con el sistema de archivos
import os
import sys
# Importa shutil para copias de archivos y arboles de directorios
import shutil
# Importa datetime para estampas de fecha en carpetas de respaldo
import datetime
# Importa json para metadata de respaldos
import json
# Importa sqlite3 para copias de seguridad consistentes en caliente
import sqlite3
# Importa rutas desde la configuracion
from config import BASE_DIR, DATABASE_PATH, BACKUPS_DIR
# Importa logger
from core.error_logger import log_info, log_error
# Importa funciones horarias oficiales de planta (Argentina UTC-3)
from core.timezone import get_plant_now, get_plant_now_str

# Asegura que el directorio de respaldos exista de manera segura
try:
    os.makedirs(BACKUPS_DIR, exist_ok=True)
except Exception:
    pass

# Crea un respaldo completo del sistema (Base de datos SQLite + Codigo + Version)
def create_backup(label="pre_update"):
    # Genera estampa de tiempo formateada con hora oficial de planta: YYYYMMDD_HHMMSS
    now_tag = get_plant_now().strftime('%Y%m%d_%H%M%S')
    # Nombre de la carpeta de respaldo
    backup_folder_name = f"backup_{now_tag}_{label}"
    # Ruta absoluta de la carpeta de respaldo
    backup_path = os.path.join(BACKUPS_DIR, backup_folder_name)
    # Crea la carpeta de respaldo
    os.makedirs(backup_path, exist_ok=True)

    # 1. Respaldo seguro en caliente de la base de datos SQLite usando la API backup
    db_name = os.path.basename(DATABASE_PATH)
    db_backup_path = os.path.join(backup_path, db_name)
    if os.path.exists(DATABASE_PATH):
        # Conecta a la base activa en modo lectura
        src_conn = sqlite3.connect(DATABASE_PATH)
        # Conecta a la base destino en la carpeta de respaldo
        dst_conn = sqlite3.connect(db_backup_path)
        # Ejecuta la copia fisica de paginas garantizando consistencia ACID
        with dst_conn:
            src_conn.backup(dst_conn)
        # Cierra las conexiones
        dst_conn.close()
        src_conn.close()

    # 2. Respaldo del manifiesto de version
    version_file = os.path.join(BASE_DIR, 'version.json')
    current_version = "1.0.0"
    if os.path.exists(version_file):
        shutil.copy2(version_file, os.path.join(backup_path, 'version.json'))
        # Bloque de proteccion ante archivos JSON vacios o corruptos
        try:
            # Abre el manifiesto de version en modo lectura
            with open(version_file, 'r', encoding='utf-8') as f:
                # Decodifica los datos y lee el campo version
                current_version = json.load(f).get('version', '1.0.5')
        # Captura errores en caso de fallo de lectura o formato
        except Exception:
            # Establece version base en caso de contingencia
            current_version = '1.0.5'

    # 3. Respaldo de los directorios de codigo clave
    code_folders = ['core', 'modules', 'diagnostics', 'static', 'templates']
    for folder in code_folders:
        src_folder = os.path.join(BASE_DIR, folder)
        if os.path.exists(src_folder):
            # Ruta de destino del directorio en el paquete de respaldo
            dst_folder = os.path.join(backup_path, folder)
            # Copia el arbol de archivos ignorando carpetas __pycache__ y binarios .pyc
            shutil.copytree(src_folder, dst_folder, dirs_exist_ok=True, ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '*.pyo'))

    # 4. Respaldo de archivos individuales clave
    single_files = ['run.py', 'config.py']
    for file_name in single_files:
        src_file = os.path.join(BASE_DIR, file_name)
        if os.path.exists(src_file):
            shutil.copy2(src_file, os.path.join(backup_path, file_name))

    # 5. Genera archivo de metadatos del respaldo
    meta = {
        'folder_name': backup_folder_name,
        'label': label,
        'created_at': get_plant_now_str(),
        'version': current_version,
        'has_database': os.path.exists(db_backup_path)
    }
    with open(os.path.join(backup_path, 'backup_meta.json'), 'w', encoding='utf-8') as f:
        json.dump(meta, f, indent=4)

    # Registra en log la creacion del respaldo
    log_info('BACKUP', f'Respaldo preventivo creado exitosamente en {backup_folder_name} (v{current_version}).')
    # Retorna la ruta del respaldo
    return backup_path

# Obtiene la lista de todos los respaldos existentes ordenados cronologicamente descendente
def list_backups():
    # Lista para almacenar los respaldos encontrados
    backups = []
    # Si la carpeta de respaldos no existe retorna lista vacia
    if not os.path.exists(BACKUPS_DIR):
        return []
    # Itera sobre los elementos dentro de la carpeta backups
    for item in os.listdir(BACKUPS_DIR):
        item_path = os.path.join(BACKUPS_DIR, item)
        # Si es un directorio y tiene el prefijo backup_
        if os.path.isdir(item_path) and item.startswith('backup_'):
            meta_path = os.path.join(item_path, 'backup_meta.json')
            if os.path.exists(meta_path):
                with open(meta_path, 'r', encoding='utf-8') as f:
                    meta = json.load(f)
                    meta['path'] = item_path
                    backups.append(meta)
            else:
                # Divide el nombre del directorio por guiones bajos
                parts = item.split('_')
                # Variable para almacenar la fecha inferida
                inferred_date = ''
                # Variable para almacenar la etiqueta inferida
                inferred_label = 'desconocido'
                # Si el nombre tiene la estructura backup_YYYYMMDD_HHMMSS
                if len(parts) >= 3:
                    # Formatea la fecha y hora extraida del nombre
                    inferred_date = f"{parts[1][:4]}-{parts[1][4:6]}-{parts[1][6:8]} {parts[2][:2]}:{parts[2][2:4]}:{parts[2][4:6]}"
                    # Une las partes restantes como etiqueta
                    inferred_label = "_".join(parts[3:]) if len(parts) > 3 else 'desconocido'
                # Agrega el diccionario de datos del respaldo a la lista
                db_name = os.path.basename(DATABASE_PATH)
                backups.append({
                    'folder_name': item,
                    'label': inferred_label,
                    'created_at': inferred_date,
                    'version': 'N/D',
                    'path': item_path,
                    'has_database': any(f.endswith('.db') for f in os.listdir(item_path)) if os.path.isdir(item_path) else False
                })
    # Ordena del mas reciente al mas antiguo
    backups.sort(key=lambda x: x.get('created_at', ''), reverse=True)
    return backups

# Restaura el sistema completo a partir de un respaldo (Rollback)
def restore_backup(backup_folder_path):
    # Verifica que la carpeta de respaldo exista
    if not os.path.exists(backup_folder_path):
        raise ValueError(f"La carpeta de respaldo especificada no existe: {backup_folder_path}")

    # 1. Restaura la base de datos de manera consistente usando el API backup de SQLite
    db_name = os.path.basename(DATABASE_PATH)
    db_backup = os.path.join(backup_folder_path, db_name)
    if not os.path.exists(db_backup):
        # Busca cualquier archivo .db presente en la carpeta de respaldo para restauracion
        candidates = [f for f in os.listdir(backup_folder_path) if f.endswith('.db')]
        if candidates:
            db_backup = os.path.join(backup_folder_path, candidates[0])
    # Verifica si el archivo de base de datos existe en el respaldo
    if os.path.exists(db_backup):
        # Abre conexion en modo lectura con la base de respaldo
        src_conn = sqlite3.connect(db_backup)
        # Abre conexion con la base de produccion
        dst_conn = sqlite3.connect(DATABASE_PATH)
        # Transfiere paginas de datos en caliente con garantia ACID
        with dst_conn:
            # Ejecuta la sincronizacion binaria de paginas SQLite
            src_conn.backup(dst_conn)
        # Cierra la conexion de destino
        dst_conn.close()
        # Cierra la conexion de origen
        src_conn.close()

    # 2. Restaura el archivo de version
    ver_backup = os.path.join(backup_folder_path, 'version.json')
    if os.path.exists(ver_backup):
        shutil.copy2(ver_backup, os.path.join(BASE_DIR, 'version.json'))

    # 3. Restaura los directorios de codigo
    code_folders = ['core', 'modules', 'diagnostics', 'static', 'templates']
    for folder in code_folders:
        src_folder = os.path.join(backup_folder_path, folder)
        if os.path.exists(src_folder):
            # Ruta de destino del directorio en la raiz del proyecto
            dst_folder = os.path.join(BASE_DIR, folder)
            # Restaura el arbol de archivos ignorando archivos de cache temporal
            shutil.copytree(src_folder, dst_folder, dirs_exist_ok=True, ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '*.pyo'))

    # 4. Restaura archivos sueltos
    single_files = ['run.py', 'config.py']
    for file_name in single_files:
        src_file = os.path.join(backup_folder_path, file_name)
        if os.path.exists(src_file):
            shutil.copy2(src_file, os.path.join(BASE_DIR, file_name))

    # Registra en log la restauracion
    log_info('BACKUP', f'Sistema restaurado exitosamente desde {backup_folder_path}.')
    return True
