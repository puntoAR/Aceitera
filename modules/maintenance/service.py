# Modulo de logica de negocio para mantenimiento industrial y stock de repuestos
# Importa datetime para marcas de tiempo y fechas programadas
import datetime
# Importa os para operaciones con rutas de archivos y directorios
import os
# Importa uuid para generar identificadores unicos de nombres de imagenes
import uuid
# Importa base64 para codificacion de fotografias de persistencia permanente
import base64
# Importa io para manejo de buffers de bytes en memoria
import io
# Importa secure_filename para sanitizar nombres de archivos cargados
from werkzeug.utils import secure_filename
# Importa Pillow para procesamiento, optimizacion y compresion de imagenes
try:
    from PIL import Image, ImageOps
except ImportError:
    Image = None
    ImageOps = None
# Importa la conexion de base de datos relacional
from core.database import get_db_connection
# Importa el registrador de auditoria de eventos de planta
from core.audit import record_audit_event
# Importa el registrador de errores del sistema
from core.error_logger import log_error, log_info
# Importa configuraciones del sistema para rutas y extensiones
import config
# Importa funciones horarias oficiales de planta BioBalcarce (Argentina UTC-3)
from core.timezone import get_plant_now, get_plant_now_str

# Registra una nueva actividad o solicitud de intervencion de mantenimiento
def create_maintenance_activity(title, category, equipment_tag, priority, description, reported_by, assigned_to=None, scheduled_date=None):
    # Valida que el titulo no este vacio
    if not title or not title.strip():
        # Lanza error si falta el titulo de la tarea
        raise ValueError("El título de la actividad de mantenimiento es obligatorio.")
    # Valida que la categoria sea una de las autorizadas (planificadas y no planificadas, con o sin parada de planta)
    valid_categories = (
        'operativa',
        'planificada_con_parada',
        'planificada_sin_parada',
        'no_planificada_con_parada',
        'no_planificada_sin_parada'
    )
    # Comprueba la presencia de la categoria en la tupla
    if category not in valid_categories:
        # Lanza error si la categoria no coincide con las autorizadas
        raise ValueError(f"Categoría inválida. Debe ser una de: {', '.join(valid_categories)}")
    # Obtiene estampa horaria oficial de planta (Argentina UTC-3)
    created_at = get_plant_now_str()
    # Abre conexion para insertar la actividad
    with get_db_connection() as conn:
        # Ejecuta la insercion en la tabla de actividades
        cursor = conn.execute("""
            INSERT INTO maintenance_activities (title, category, equipment_tag, priority, status, description, reported_by, assigned_to, scheduled_date, created_at)
            VALUES (?, ?, ?, ?, 'pendiente', ?, ?, ?, ?, ?);
        """, (title.strip(), category, equipment_tag.strip() if equipment_tag else 'General', priority, description.strip() if description else '', reported_by, assigned_to, scheduled_date, created_at))
        # Obtiene el identificador asignado a la nueva actividad
        activity_id = cursor.lastrowid
        # Confirma la transaccion
        conn.commit()
    # Registra el evento en auditoria
    record_audit_event('MANTENIMIENTO', 'ACTIVIDAD_CREADA', f"Creada actividad #{activity_id} ({category}): {title} en {equipment_tag or 'General'}.")
    # Retorna el id de la actividad generada
    return activity_id

# Obtiene la lista de actividades de mantenimiento con filtros opcionales
def get_maintenance_activities(category=None, status=None, limit=100):
    # Abre conexion a la base de datos
    with get_db_connection() as conn:
        # Consulta base seleccionando todos los campos
        query = "SELECT * FROM maintenance_activities WHERE 1=1"
        # Lista para almacenar los parametros posicionales
        params = []
        # Si se especifica una categoria particular
        if category:
            if category in ('no_planificada_sin_parada', 'operativa'):
                query += " AND category IN ('no_planificada_sin_parada', 'operativa')"
            else:
                query += " AND category = ?"
                params.append(category)
        # Si se especifica un estado particular
        if status:
            if status in ('pendiente', 'activas'):
                query += " AND status IN ('pendiente', 'en_progreso')"
            else:
                query += " AND status = ?"
                params.append(status)
        # Agrega ordenamiento descendente por fecha y limite
        query += " ORDER BY id DESC LIMIT ?"
        # Agrega el limite a la lista
        params.append(limit)
        # Ejecuta la consulta en la base
        rows = conn.execute(query, tuple(params)).fetchall()
        # Convierte cada fila a diccionario
        activities = [dict(row) for row in rows]
        # Itera para adjuntar el conteo de fotografias asociadas a cada tarea
        for act in activities:
            # Consulta la cantidad de imagenes vinculadas
            img_count = conn.execute("SELECT COUNT(*) FROM maintenance_images WHERE activity_id = ?;", (act['id'],)).fetchone()[0]
            # Asigna el contador al diccionario
            act['images_count'] = img_count
        # Retorna el listado enriquecido
        return activities

# Obtiene una actividad de mantenimiento por su identificador unico
def get_activity_by_id(activity_id):
    # Abre conexion para consultar
    with get_db_connection() as conn:
        # Busca el registro correspondiente
        row = conn.execute("SELECT * FROM maintenance_activities WHERE id = ?;", (activity_id,)).fetchone()
        # Retorna el diccionario o None si no existe
        return dict(row) if row else None

# Actualiza el estado, notas tecnicas de cierre y opcionalmente reclasifica la categoria de una actividad
def update_activity_status(activity_id, status, resolution_notes=None, completed_at=None, operator_name='Sistema', category=None):
    # Valida los estados permitidos
    valid_statuses = ('pendiente', 'en_progreso', 'completada', 'cancelada')
    # Verifica que el estado indicado este contemplado
    if status not in valid_statuses:
        # Lanza error si el estado es desconocido
        raise ValueError(f"Estado inválido. Debe ser: {', '.join(valid_statuses)}")
    
    # Valida la categoria si fue suministrada
    valid_categories = (
        'operativa',
        'planificada_con_parada',
        'planificada_sin_parada',
        'no_planificada_con_parada',
        'no_planificada_sin_parada'
    )
    if category and category not in valid_categories:
        raise ValueError(f"Categoría inválida. Debe ser una de: {', '.join(valid_categories)}")

    # Si el estado es completada y no se paso fecha, toma la hora oficial de planta (Argentina UTC-3)
    if status == 'completada' and not completed_at:
        completed_at = get_plant_now_str()
    # Abre conexion para modificar el registro
    with get_db_connection() as conn:
        # Ejecuta el update de estado, categoria y resolucion
        if category:
            conn.execute("""
                UPDATE maintenance_activities
                SET status = ?, resolution_notes = COALESCE(?, resolution_notes), completed_at = COALESCE(?, completed_at), category = ?
                WHERE id = ?;
            """, (status, resolution_notes, completed_at, category, activity_id))
        else:
            conn.execute("""
                UPDATE maintenance_activities
                SET status = ?, resolution_notes = COALESCE(?, resolution_notes), completed_at = COALESCE(?, completed_at)
                WHERE id = ?;
            """, (status, resolution_notes, completed_at, activity_id))
        # Confirma la modificacion
        conn.commit()
    # Registra en auditoria el cambio de estado
    cat_desc = f" (categoría: {category})" if category else ""
    record_audit_event('MANTENIMIENTO', 'ESTADO_ACTUALIZADO', f"Actividad #{activity_id} actualizada a '{status}'{cat_desc} por {operator_name}.")
    # Retorna verdadero confirmando la actualizacion
    return True

# Optimiza y codifica la fotografia en Base64 para persistencia permanente en base de datos
def _process_and_encode_image(file_storage, max_dimension=1280, quality=80):
    """
    Procesa un archivo de imagen optimizándolo para almacenamiento resiliente:
    - Corrige orientación física EXIF (rotación automática)
    - Redimensiona proporcionalmente a un máximo de 1280px
    - Comprime a JPEG con calidad 80 y optimización
    - Genera Data URI base64 lista para almacenamiento en base de datos
    - Fallback resiliente si Pillow no está disponible o para streams simulados en pruebas
    """
    try:
        # Lee los bytes del archivo subido
        file_storage.seek(0)
        raw_bytes = file_storage.read()
        file_storage.seek(0)
        
        if not raw_bytes:
            return 'image/jpeg', None, b''
            
        if Image is not None:
            try:
                # Abre con Pillow desde el buffer de memoria
                with Image.open(io.BytesIO(raw_bytes)) as img:
                    # Corrige orientación física según metadatos EXIF de cámaras y celulares
                    if ImageOps is not None:
                        try:
                            img = ImageOps.exif_transpose(img)
                        except Exception:
                            pass
                    
                    # Convierte a modo RGB si tiene canales alfa o es paleta indexada
                    if img.mode in ('RGBA', 'LA', 'P'):
                        bg = Image.new('RGB', img.size, (255, 255, 255))
                        if img.mode == 'P':
                            img = img.convert('RGBA')
                        bg.paste(img, mask=img.split()[-1] if len(img.split()) == 4 else None)
                        img = bg
                    elif img.mode != 'RGB':
                        img = img.convert('RGB')
                        
                    # Redimensiona proporcionalmente si supera la dimension maxima
                    resample_filter = getattr(getattr(Image, 'Resampling', Image), 'LANCZOS', Image.BICUBIC)
                    img.thumbnail((max_dimension, max_dimension), resample=resample_filter)
                    
                    # Guarda el resultado comprimido en memoria
                    buffer = io.BytesIO()
                    img.save(buffer, format='JPEG', quality=quality, optimize=True)
                    processed_bytes = buffer.getvalue()
                    mime_type = 'image/jpeg'
                    b64_str = base64.b64encode(processed_bytes).decode('ascii')
                    data_uri = f"data:{mime_type};base64,{b64_str}"
                    return mime_type, data_uri, processed_bytes
            except Exception:
                # Fallback en caso de archivos simulados o formatos binarios no raster
                pass
                
        # Fallback estándar directo
        mime_type = 'image/jpeg'
        b64_str = base64.b64encode(raw_bytes).decode('ascii')
        data_uri = f"data:{mime_type};base64,{b64_str}"
        return mime_type, data_uri, raw_bytes
    except Exception as e:
        log_error("ERROR_OPTIMIZAR_IMAGEN_MANTENIMIENTO", f"Fallo al procesar imagen: {e}")
        return 'image/jpeg', None, b''

# Genera un placeholder SVG cuando la imagen histórica no está disponible
def get_placeholder_image_svg(title="Mantenimiento BioBalcarce", message="Fotografía no disponible"):
    """
    Retorna un gráfico SVG vectorial estilizado para servir como fallback
    ante fotografías anteriores cuya copia efímera en disco fue purgada.
    """
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="600" height="400" viewBox="0 0 600 400">
  <defs>
    <linearGradient id="bg" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#0f172a" />
      <stop offset="100%" stop-color="#1e293b" />
    </linearGradient>
  </defs>
  <rect width="600" height="400" fill="url(#bg)" />
  <rect x="20" y="20" width="560" height="360" rx="12" fill="none" stroke="#334155" stroke-width="2" stroke-dasharray="6 6" />
  <g transform="translate(300, 160)" text-anchor="middle">
    <circle cx="0" cy="-20" r="42" fill="#334155" />
    <path d="M -18,-15 L -10,-28 L 10,-28 L 18,-15 L 24,-15 C 27,-15 29,-13 29,-10 L 29,8 C 29,11 27,13 24,13 L -24,13 C -27,13 -29,11 -29,8 L -29,-10 C -29,-13 -27,-15 -24,-15 Z" fill="#94a3b8" />
    <circle cx="0" cy="-1" r="10" fill="#0f172a" stroke="#f59e0b" stroke-width="2.5" />
    <text y="50" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="18" font-weight="700" fill="#f8fafc">{title}</text>
    <text y="75" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="13" fill="#94a3b8">{message}</text>
  </g>
</svg>"""
    return svg.encode('utf-8'), 'image/svg+xml'

# Guarda una fotografia de reparacion en base de datos y cache en disco
# Guarda una fotografia de reparacion en base de datos y cache en disco
def save_maintenance_image(activity_id, file_storage, caption=None): # Guarda fotografia
    # Verifica que el objeto de archivo sea valido y tenga nombre
    if not file_storage or not file_storage.filename: # Valida archivo recibido
        # Lanza excepcion si no se recibio archivo
        raise ValueError("No se seleccionó ningún archivo de imagen para cargar.") # Error si falta
    # Sanitiza el nombre original del archivo
    orig_name = secure_filename(file_storage.filename) # Sanitiza nombre
    # Extrae la extension en minusculas
    ext = orig_name.rsplit('.', 1)[-1].lower() if '.' in orig_name else '' # Obtiene extension
    # Comprueba si la extension esta dentro de las autorizadas
    if ext not in config.ALLOWED_IMAGE_EXTENSIONS: # Valida extension autorizada
        # Lanza error de extension no permitida
        raise ValueError(f"Formato no permitido. Use: {', '.join(config.ALLOWED_IMAGE_EXTENSIONS)}") # Error formato
    # Procesa y optimiza la imagen para base de datos y cache en disco
    mime_type, data_uri, processed_bytes = _process_and_encode_image(file_storage) # Procesa imagen
    # Si el resultado es JPEG, normaliza la extension a .jpg para consistencia MIME
    effective_ext = 'jpg' if mime_type == 'image/jpeg' else ext # Extension efectiva
    # Genera un nombre de archivo seguro y unico con la extension normalizada
    unique_filename = f"maint_{activity_id}_{uuid.uuid4().hex[:10]}.{effective_ext}" # Nombre unico
    # Intenta guardar una copia local en disco como cache rapido
    try: # Bloque try cache disco
        # Crea directorio de subidas si no existe
        os.makedirs(config.MAINTENANCE_UPLOADS_DIR, exist_ok=True) # Crea carpeta
        # Ruta destino en disco
        destination_path = os.path.join(config.MAINTENANCE_UPLOADS_DIR, unique_filename) # Ruta destino
        # Si se obtuvieron bytes procesados optimizados
        if processed_bytes: # Si hay bytes procesados
            # Escribe los bytes procesados directamente al archivo
            with open(destination_path, 'wb') as f: # Abre archivo en escritura binaria
                # Escribe bytes
                f.write(processed_bytes) # Escribe bytes
        else: # Si no hubo bytes procesados
            # Posiciona al inicio del stream original
            file_storage.seek(0) # Seek 0
            # Guarda usando metodo nativo de Flask
            file_storage.save(destination_path) # Guarda nativo
    except Exception as e: # En entornos serverless read-only
        # Registra aviso informativo sin interrumpir la operacion
        log_info("MAINTENANCE_IMAGE_DISK_WRITE", f"No se pudo escribir en disco (normal en serverless): {e}") # Log aviso
    # Abre conexion para registrar la imagen en la base de datos persistente
    with get_db_connection() as conn: # Abre conexion
        # Inserta el registro en maintenance_images con datos persistentes
        cursor = conn.execute("""
            INSERT INTO maintenance_images (activity_id, filename, caption, image_data, mime_type)
            VALUES (?, ?, ?, ?, ?);
        """, (activity_id, unique_filename, caption.strip() if caption else 'Registro visual', data_uri, mime_type)) # Inserta registro
        # Obtiene el identificador asignado
        image_id = cursor.lastrowid # ID asignado
        # Confirma la transaccion
        conn.commit() # Confirma
    # Registra en auditoria la subida de la imagen
    record_audit_event('MANTENIMIENTO', 'FOTO_SUBIDA', f"Foto #{image_id} cargada para actividad #{activity_id} ({unique_filename}).") # Auditoria
    # Retorna el nombre de archivo almacenado
    return unique_filename # Retorna nombre

# Recupera los datos binarios y MIME type de una imagen por ID o filename
def get_maintenance_image_data(identifier): # Recupera datos de imagen
    """
    Recupera los datos binarios y el MIME type de una imagen de mantenimiento
    a partir de su ID numérico o de su nombre de archivo (filename).
    Busca prioritariamente en la columna 'image_data' (base64) de la base de datos;
    si no está disponible, intenta cargar desde el disco local y auto-repara la BD.
    Retorna tupla: (binary_bytes, mime_type) o (None, None) si no existe.
    """ # Docstring
    # Inicializa variable de fila
    row = None # Inicializa row
    # Limpia identificador si contiene parametros de consulta
    clean_id = str(identifier).split('?')[0].split('#')[0] if identifier is not None else '' # Limpia query string
    # Abre conexion a la base de datos
    with get_db_connection() as conn: # Abre conexion
        # Si es un entero o una cadena numérica
        if isinstance(identifier, int) or clean_id.isdigit(): # Comprueba si es ID numerico
            # Consulta por ID numérico en la tabla
            row = conn.execute("SELECT * FROM maintenance_images WHERE id = ?;", (int(clean_id),)).fetchone() # Consulta por ID
        # Si no se encontró por ID o el identificador es un filename de texto
        if not row and clean_id: # Si no se encontro fila
            # Consulta por nombre exacto de archivo
            row = conn.execute("SELECT * FROM maintenance_images WHERE filename = ?;", (clean_id,)).fetchone() # Consulta por filename
            # Si no se encuentra y tiene extension, busca por prefijo sin importar extension jpg/png
            if not row and '.' in clean_id: # Si tiene punto de extension
                # Extrae nombre base sin extension
                stem = clean_id.rsplit('.', 1)[0] # Nombre base
                # Busca registro cuyo nombre empiece con la misma raiz
                row = conn.execute("SELECT * FROM maintenance_images WHERE filename LIKE ?;", (f"{stem}.%",)).fetchone() # Consulta por patron
    # Si se encontró registro en base de datos
    if row: # Si existe registro
        # Convierte fila a diccionario
        row_dict = dict(row) # Convierte a dict
        # Extrae datos base64 persistidos
        img_data = row_dict.get('image_data') # Obtiene image_data
        # Extrae tipo MIME almacenado o default JPEG
        mime = row_dict.get('mime_type') or 'image/jpeg' # Obtiene mime_type
        # Extrae nombre de archivo de la fila
        fn = row_dict.get('filename') # Obtiene filename
        # Si la fila contiene datos binarios en base64
        if img_data: # Si hay image_data
            # Bloque de decodificacion segura
            try: # Bloque try decodificacion
                # Si tiene prefijo data:mime;base64,
                if ',' in img_data: # Comprueba data URI
                    # Separa cabecera y cuerpo base64
                    header, b64_part = img_data.split(',', 1) # Separa cabecera
                    # Si la cabecera especifica el tipo de imagen
                    if 'image/' in header: # Valida prefijo mime
                        # Extrae el MIME type exacto
                        mime = header.split(';')[0].replace('data:', '').strip() # Extrae mime
                else: # Si no tiene prefijo
                    # Asigna directamente el cuerpo base64
                    b64_part = img_data # Cuerpo base64
                # Decodifica la cadena base64 a bytes binarios limpios
                binary_bytes = base64.b64decode(b64_part.strip()) # Decodifica base64
                # Recrea copia local en disco como cache si no existe (resiliencia multi-PC)
                if fn and binary_bytes: # Si hay filename y bytes
                    # Bloque protegido para cache en disco
                    try: # Bloque try cache disco
                        # Asegura la existencia de la carpeta de uploads
                        os.makedirs(config.MAINTENANCE_UPLOADS_DIR, exist_ok=True) # Crea carpeta
                        # Construye ruta de cache local
                        disk_cache_path = os.path.join(config.MAINTENANCE_UPLOADS_DIR, fn) # Ruta en disco
                        # Si el archivo no existe fisicamente en el disco de esta PC
                        if not os.path.isfile(disk_cache_path): # Verifica si no existe
                            # Escribe los bytes descargados de la base de datos
                            with open(disk_cache_path, 'wb') as cf: # Abre archivo
                                # Guarda copia en disco
                                cf.write(binary_bytes) # Guarda bytes
                    except Exception: # Si el disco es de solo lectura o falla
                        # Continua sin error
                        pass # Pasa
                # Retorna tupla de bytes y tipo MIME
                return binary_bytes, mime # Retorna imagen
            except Exception as e: # Si falla la decodificacion
                # Registra advertencia de decodificacion
                log_error("ERROR_DECODE_IMAGE_DATA", f"Error al decodificar base64 de imagen #{row_dict.get('id')}: {e}") # Log error
        # Si no había image_data o falló, busca archivo fisico en disco y auto-repara la BD
        if fn: # Si hay filename en la fila
            # Carpetas potenciales para buscar la imagen fisica
            potential_dirs = [ # Lista de carpetas
                config.MAINTENANCE_UPLOADS_DIR, # Carpeta configurada
                os.path.join(str(config.BASE_DIR), 'static', 'uploads', 'maintenance'), # Carpeta estatica oficial
                os.path.join(str(config.BASE_DIR), 'static', 'uploads') # Carpeta estatica general
            ] # Fin lista
            # Itera sobre las carpetas potenciales
            for pdir in potential_dirs: # Itera carpetas
                # Construye ruta candidata
                disk_path = os.path.join(pdir, fn) # Ruta candidata
                # Si el archivo existe fisicamente en disco
                if os.path.isfile(disk_path): # Verifica existencia
                    # Bloque de lectura y auto-reparacion
                    try: # Bloque try auto-sync
                        # Abre y lee el archivo binario
                        with open(disk_path, 'rb') as f: # Abre archivo
                            # Lee los bytes del archivo
                            disk_bytes = f.read() # Lee bytes
                        # Si se obtuvieron bytes validos
                        if disk_bytes: # Si hay contenido
                            # Detecta extension para tipo MIME
                            ext = fn.rsplit('.', 1)[-1].lower() if '.' in fn else 'jpg' # Obtiene extension
                            # Asigna tipo MIME segun extension
                            detected_mime = 'image/png' if ext == 'png' else 'image/webp' if ext == 'webp' else 'image/jpeg' # Detecta mime
                            # Codifica a Base64 para persistir permanentemente
                            b64_str = base64.b64encode(disk_bytes).decode('ascii') # Codifica base64
                            # Construye Data URI estandar
                            data_uri = f"data:{detected_mime};base64,{b64_str}" # Data URI
                            # Auto-sincroniza hacia la base de datos relacional (self-healing)
                            try: # Bloque try actualizacion BD
                                # Abre conexion para escribir la reparacion
                                with get_db_connection() as up_conn: # Abre conexion
                                    # Actualiza la fila sin perder el resto de metadatos
                                    up_conn.execute("""
                                        UPDATE maintenance_images
                                        SET image_data = ?, mime_type = ?
                                        WHERE id = ?;
                                    """, (data_uri, detected_mime, row_dict['id'])) # Ejecuta UPDATE
                                    # Confirma los cambios en la base de datos
                                    up_conn.commit() # Confirma
                                # Registra la auto-reparacion en bitacora
                                log_info("MAINTENANCE_SELF_HEAL", f"Imagen #{row_dict['id']} ({fn}) sincronizada a base de datos.") # Log
                            except Exception as sync_err: # Si falla el UPDATE
                                # Registra advertencia
                                log_error("MAINTENANCE_SELF_HEAL", f"Aviso al sincronizar #{row_dict['id']}: {sync_err}") # Error log
                            # Retorna los bytes leidos y el tipo MIME
                            return disk_bytes, detected_mime # Retorna bytes
                    except Exception: # Si falla la lectura
                        # Pasa a siguiente intento
                        pass # Pasa
    # Si no hubo registro en BD pero clean_id es un string de archivo valido
    if clean_id and not clean_id.isdigit(): # Comprueba identificador de archivo directo
        # Carpetas potenciales para buscar la imagen fisica directa
        potential_dirs = [ # Lista de carpetas
            config.MAINTENANCE_UPLOADS_DIR, # Carpeta configurada
            os.path.join(str(config.BASE_DIR), 'static', 'uploads', 'maintenance') # Carpeta estatica
        ] # Fin lista
        # Itera sobre las carpetas potenciales
        for pdir in potential_dirs: # Itera carpetas
            # Construye ruta candidata
            disk_path = os.path.join(pdir, clean_id) # Ruta candidata
            # Si el archivo existe fisicamente en disco
            if os.path.isfile(disk_path): # Comprueba existencia
                # Bloque de lectura protegida
                try: # Bloque try lectura
                    # Detecta extension
                    ext = clean_id.rsplit('.', 1)[-1].lower() if '.' in clean_id else 'jpg' # Obtiene extension
                    # Detecta mime type
                    mime = 'image/png' if ext == 'png' else 'image/webp' if ext == 'webp' else 'image/jpeg' # Detecta mime
                    # Abre y lee el archivo
                    with open(disk_path, 'rb') as f: # Abre archivo
                        # Retorna tupla de bytes leidos y mime
                        return f.read(), mime # Retorna bytes
                except Exception: # Si falla
                    # Pasa a siguiente
                    pass # Pasa
    # Si no se encontro por ningun medio, retorna tupla None
    return None, None # Retorna None

# Elimina una fotografia de mantenimiento de la base de datos y del disco
def delete_maintenance_image(image_id):
    """
    Elimina permanentemente una fotografía de mantenimiento de la base de datos
    y remueve el archivo físico de disco si existiera.
    """
    with get_db_connection() as conn:
        row = conn.execute("SELECT * FROM maintenance_images WHERE id = ?;", (image_id,)).fetchone()
        if not row:
            return False
        row_dict = dict(row)
        filename = row_dict.get('filename')
        activity_id = row_dict.get('activity_id')
        
        # Elimina de la base de datos
        conn.execute("DELETE FROM maintenance_images WHERE id = ?;", (image_id,))
        conn.commit()
        
    # Intenta borrar el archivo de disco si existe
    if filename:
        try:
            disk_path = os.path.join(config.MAINTENANCE_UPLOADS_DIR, filename)
            if os.path.isfile(disk_path):
                os.remove(disk_path)
        except Exception:
            pass
            
    record_audit_event('MANTENIMIENTO', 'FOTO_ELIMINADA', f"Foto #{image_id} eliminada de actividad #{activity_id} ({filename}).")
    return True

# Obtiene todas las imagenes vinculadas a una actividad especifica
def get_activity_images(activity_id): # Obtiene imagenes de actividad
    # Abre conexion a la base de datos
    with get_db_connection() as conn: # Abre conexion
        # Consulta las imagenes asociadas a la actividad ordenadas cronologicamente
        rows = conn.execute("""
            SELECT id, activity_id, filename, caption, uploaded_at, mime_type,
                   (image_data IS NOT NULL AND image_data != '') as has_data
            FROM maintenance_images
            WHERE activity_id = ?
            ORDER BY id ASC;
        """, (activity_id,)).fetchall() # Ejecuta consulta
        # Lista de resultados con URL y version para cache buster
        result = [] # Inicializa lista
        # Itera sobre cada registro obtenido
        for row in rows: # Itera filas
            # Convierte fila a diccionario
            r = dict(row) # Convierte a dict
            # Genera version para evitar cache stale de placeholders anteriores en otros navegadores
            v_tag = str(r.get('uploaded_at') or r['id']).replace(' ', '_').replace(':', '') # Genera tag de version
            # Asigna la URL del endpoint sirviendo la imagen con version
            r['url'] = f"/maintenance/image/{r['id']}?v={v_tag}" # Asigna url
            # Agrega el registro a la lista
            result.append(r) # Agrega resultado
        # Retorna la lista formateada
        return result # Retorna lista

# Obtiene las fotografias mas recientes de todas las intervenciones para galeria general
def get_all_recent_images(limit=30): # Obtiene fotos recientes
    # Abre conexion
    with get_db_connection() as conn: # Abre conexion
        # Consulta imagenes cruzadas con el titulo de la actividad
        rows = conn.execute("""
            SELECT mi.id, mi.activity_id, mi.filename, mi.caption, mi.uploaded_at, mi.mime_type,
                   (mi.image_data IS NOT NULL AND mi.image_data != '') as has_data,
                   ma.title as activity_title, ma.category as activity_category, ma.equipment_tag
            FROM maintenance_images mi
            JOIN maintenance_activities ma ON mi.activity_id = ma.id
            ORDER BY mi.id DESC LIMIT ?;
        """, (limit,)).fetchall() # Ejecuta consulta
        # Lista de resultados formateados
        result = [] # Inicializa lista
        # Itera sobre cada registro
        for row in rows: # Itera filas
            # Convierte a diccionario
            r = dict(row) # Convierte a dict
            # Genera version para evitar cache stale de placeholders anteriores en otros navegadores
            v_tag = str(r.get('uploaded_at') or r['id']).replace(' ', '_').replace(':', '') # Genera tag de version
            # Asigna la URL del endpoint sirviendo la imagen con version
            r['url'] = f"/maintenance/image/{r['id']}?v={v_tag}" # Asigna url
            # Agrega a la lista
            result.append(r) # Agrega resultado
        # Retorna lista de imagenes
        return result # Retorna lista

# Da de alta o actualiza los datos de un repuesto en el inventario del pañol
def create_or_update_spare_part(code, name, category, equipment_assigned, is_consumable, stock_quantity, min_stock, unit='unidades', location='', notes='', part_id=None):
    # Valida presencia de codigo y nombre
    if not code or not name:
        # Lanza error si faltan datos esenciales
        raise ValueError("El código y la denominación del repuesto son obligatorios.")
    # Abre conexion para realizar la operacion
    with get_db_connection() as conn:
        # Si se especifico part_id, realiza una actualizacion
        if part_id:
            # Actualiza el registro existente
            conn.execute("""
                UPDATE spare_parts
                SET code = ?, name = ?, category = ?, equipment_assigned = ?, is_consumable = ?,
                    stock_quantity = ?, min_stock = ?, unit = ?, location = ?, notes = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?;
            """, (code.strip(), name.strip(), category.strip(), equipment_assigned.strip(), 1 if is_consumable else 0, float(stock_quantity), float(min_stock), unit.strip(), location.strip(), notes.strip(), part_id))
            # Confirma la actualizacion
            conn.commit()
            # Retorna el id actualizado
            return part_id
        # Si no se recibio part_id, verifica si ya existe un repuesto con el mismo codigo
        else:
            # Busca si ya existe un repuesto registrado con el codigo proporcionado
            existing = conn.execute("SELECT id FROM spare_parts WHERE code = ?;", (code.strip(),)).fetchone()
            # Si el repuesto ya existe en el catalogo
            if existing:
                # Actualiza el registro preexistente con los nuevos valores suministrados
                conn.execute("""
                    UPDATE spare_parts
                    SET code = ?, name = ?, category = ?, equipment_assigned = ?, is_consumable = ?,
                        stock_quantity = ?, min_stock = ?, unit = ?, location = ?, notes = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?;
                """, (code.strip(), name.strip(), category.strip(), equipment_assigned.strip(), 1 if is_consumable else 0, float(stock_quantity), float(min_stock), unit.strip(), location.strip(), notes.strip(), existing['id']))
                # Confirma la actualizacion en la base de datos
                conn.commit()
                # Retorna el identificador del repuesto existente
                return existing['id']
            # Si es un codigo nuevo que no existe
            else:
                # Inserta el nuevo repuesto en la tabla
                cursor = conn.execute("""
                    INSERT INTO spare_parts (code, name, category, equipment_assigned, is_consumable, stock_quantity, min_stock, unit, location, notes)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """, (code.strip(), name.strip(), category.strip(), equipment_assigned.strip(), 1 if is_consumable else 0, float(stock_quantity), float(min_stock), unit.strip(), location.strip(), notes.strip()))
                # Obtiene el nuevo id generado
                new_id = cursor.lastrowid
                # Confirma la insercion en la base de datos
                conn.commit()
                # Retorna el nuevo id generado
                return new_id

# Obtiene el catalogo de repuestos con calculo de alerta de stock critico
def get_spare_parts(filter_low_stock=False, category=None):
    # Abre conexion para consultar
    with get_db_connection() as conn:
        # Consulta base
        query = "SELECT * FROM spare_parts WHERE 1=1"
        # Lista de parametros
        params = []
        # Si se solicita solo stock critico
        if filter_low_stock:
            # Filtra repuestos cuya existencia sea menor o igual al minimo
            query += " AND stock_quantity <= min_stock"
        # Si se filtra por categoria
        if category:
            # Agrega filtro de categoria
            query += " AND category = ?"
            # Agrega parametro
            params.append(category)
        # Ordena alfabeticamente por nombre
        query += " ORDER BY name ASC;"
        # Ejecuta la consulta
        rows = conn.execute(query, tuple(params)).fetchall()
        # Convierte a lista de diccionarios
        parts = [dict(row) for row in rows]
        # Itera para computar indicador booleano de criticidad
        for p in parts:
            # True si el stock esta en o por debajo del stock minimo
            p['is_critical'] = (p['stock_quantity'] <= p['min_stock'])
        # Retorna el listado con indicador
        return parts

# Obtiene un repuesto por su identificador unico
def get_spare_part_by_id(part_id):
    # Abre conexion
    with get_db_connection() as conn:
        # Busca el repuesto por id
        row = conn.execute("SELECT * FROM spare_parts WHERE id = ?;", (part_id,)).fetchone()
        # Si existe, retorna con el indicador de criticidad
        if row:
            # Convierte a diccionario
            p = dict(row)
            # Evalua criticidad
            p['is_critical'] = (p['stock_quantity'] <= p['min_stock'])
            # Retorna el repuesto
            return p
        # Retorna None si no fue encontrado
        return None

# Registra un movimiento de entrada o salida de stock de un repuesto
def record_spare_part_movement(spare_part_id, movement_type, quantity, operator_name, reason='', activity_id=None):
    # Valida cantidad positiva
    qty = float(quantity)
    # Comprueba que la cantidad sea estrictamente mayor a cero
    if qty <= 0:
        # Lanza error si la cantidad es invalida
        raise ValueError("La cantidad del movimiento debe ser mayor a cero.")
    # Valida tipos de movimiento permitidos
    valid_types = ('ingreso', 'egreso_mantenimiento', 'ajuste')
    # Comprueba el tipo
    if movement_type not in valid_types:
        # Lanza error si el tipo no es reconocido
        raise ValueError(f"Tipo de movimiento inválido. Debe ser: {', '.join(valid_types)}")
    # Abre conexion para registrar movimiento y actualizar stock
    with get_db_connection() as conn:
        # Obtiene el stock actual
        row = conn.execute("SELECT stock_quantity, name, code FROM spare_parts WHERE id = ?;", (spare_part_id,)).fetchone()
        # Si no existe el repuesto
        if not row:
            # Lanza excepcion de inexistencia
            raise ValueError(f"El repuesto con ID #{spare_part_id} no existe.")
        # Stock actual
        current_stock = float(row['stock_quantity'])
        # Calcula el nuevo stock segun el tipo de movimiento
        if movement_type == 'ingreso':
            # Suma al stock actual
            new_stock = current_stock + qty
        elif movement_type == 'egreso_mantenimiento':
            # Resta del stock actual
            new_stock = max(0.0, current_stock - qty)
        else: # ajuste directo
            # Asigna la cantidad como nuevo stock total
            new_stock = qty
        # Actualiza el stock en la tabla principal y registra el movimiento con horario oficial de planta
        now_str = get_plant_now_str()
        conn.execute("UPDATE spare_parts SET stock_quantity = ?, updated_at = ? WHERE id = ?;", (new_stock, now_str, spare_part_id))
        # Inserta el movimiento en el historial
        conn.execute("""
            INSERT INTO spare_parts_movements (spare_part_id, activity_id, movement_type, quantity, operator_name, reason, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?);
        """, (spare_part_id, activity_id, movement_type, qty, operator_name, reason.strip() if reason else '', now_str))
        # Confirma la transaccion en disco
        conn.commit()
    # Registra el evento en auditoria
    record_audit_event('PAÑOL', 'MOVIMIENTO_STOCK', f"Movimiento {movement_type} de {qty} unidades en repuesto #{spare_part_id} ({row['code']}). Nuevo stock: {new_stock}.")
    # Retorna el nuevo stock resultante
    return new_stock

# Genera los datos consolidados para el reporte impreso y descargable de repuestos
def get_spare_parts_report_data():
    # Obtiene todos los repuestos registrados
    parts = get_spare_parts()
    # Conteo total de items
    total_items = len(parts)
    # Conteo de articulos con stock critico o bajo minimo
    critical_items = sum(1 for p in parts if p['is_critical'])
    # Conteo de consumibles
    consumables_items = sum(1 for p in parts if p['is_consumable'] == 1)
    # Conteo de repuestos mecanicos
    mechanical_items = total_items - consumables_items
    # Obtiene lista de categorias unicas presentes
    categories = sorted(list(set(p['category'] for p in parts if p['category'])))
    # Retorna el diccionario consolidado
    return {
        'parts': parts,
        'total_items': total_items,
        'critical_items': critical_items,
        'consumables_items': consumables_items,
        'mechanical_items': mechanical_items,
        'categories': categories,
        'generated_at': get_plant_now().strftime('%d/%m/%Y %H:%M')
    }

# Obtiene los indicadores clave de mantenimiento para el cockpit ejecutivo (5 categorias y tareas activas)
def get_maintenance_dashboard_kpis():
    # Abre conexion a la base de datos
    with get_db_connection() as conn:
        # Comprueba si la tabla de actividades existe para evitar excepciones
        table_check = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='maintenance_activities';").fetchone()
        if not table_check:
            # Retorna valores en cero si la tabla no fue creada aun
            return {
                'pending_count': 0,
                'operative_count': 0,
                'unplanned_stop_count': 0,
                'unplanned_no_stop_count': 0,
                'planned_stop_count': 0,
                'planned_no_stop_count': 0,
                'total_active_count': 0
            }
        
        # Conteo de tareas pendientes o en curso (no concluidas ni canceladas)
        pending = conn.execute("SELECT COUNT(*) FROM maintenance_activities WHERE status IN ('pendiente', 'en_progreso');").fetchone()[0]
        # Conteo de tareas no planificadas con parada de planta (roturas críticas, trabas de equipo)
        unplanned_stop = conn.execute("SELECT COUNT(*) FROM maintenance_activities WHERE category = 'no_planificada_con_parada' AND status != 'cancelada';").fetchone()[0]
        # Conteo de tareas no planificadas sin parada de planta (urgencias en marcha, incluye 'operativa')
        unplanned_no_stop = conn.execute("SELECT COUNT(*) FROM maintenance_activities WHERE category IN ('no_planificada_sin_parada', 'operativa') AND status != 'cancelada';").fetchone()[0]
        # Conteo de tareas planificadas con parada de planta
        planned_stop = conn.execute("SELECT COUNT(*) FROM maintenance_activities WHERE category = 'planificada_con_parada' AND status != 'cancelada';").fetchone()[0]
        # Conteo de tareas planificadas sin parada de planta
        planned_no_stop = conn.execute("SELECT COUNT(*) FROM maintenance_activities WHERE category = 'planificada_sin_parada' AND status != 'cancelada';").fetchone()[0]
        # Conteo para retrocompatibilidad con codigo o tests que lean operative_count
        operative = conn.execute("SELECT COUNT(*) FROM maintenance_activities WHERE category IN ('operativa', 'no_planificada_sin_parada') AND status != 'cancelada';").fetchone()[0]
        
        # Retorna el diccionario de KPIs para el dashboard
        return {
            'pending_count': int(pending or 0),
            'operative_count': int(operative or 0),
            'unplanned_stop_count': int(unplanned_stop or 0),
            'unplanned_no_stop_count': int(unplanned_no_stop or 0),
            'planned_stop_count': int(planned_stop or 0),
            'planned_no_stop_count': int(planned_no_stop or 0),
            'total_active_count': int(pending or 0)
        }

# Genera el conjunto de datos para el reporte imprimible de actividades de reparacion con filtros
def get_maintenance_repairs_report(start_date=None, end_date=None, equipment_tag=None, category=None, status=None):
    with get_db_connection() as conn:
        query = "SELECT * FROM maintenance_activities WHERE 1=1"
        params = []

        # Filtro de fecha desde (sobre created_at o completed_at o scheduled_date)
        if start_date and start_date.strip():
            s_date = start_date.strip()
            query += " AND (date(created_at) >= ? OR (completed_at IS NOT NULL AND date(completed_at) >= ?) OR (scheduled_date IS NOT NULL AND scheduled_date >= ?))"
            params.extend([s_date, s_date, s_date])

        # Filtro de fecha hasta
        if end_date and end_date.strip():
            e_date = end_date.strip()
            query += " AND (date(created_at) <= ? OR (completed_at IS NOT NULL AND date(completed_at) <= ?) OR (scheduled_date IS NOT NULL AND scheduled_date <= ?))"
            params.extend([e_date, e_date, e_date])

        # Filtro de equipo o sector
        if equipment_tag and equipment_tag.strip() and equipment_tag.strip().lower() != 'todos':
            eq = equipment_tag.strip()
            query += " AND (equipment_tag = ? OR equipment_tag LIKE ?)"
            params.extend([eq, f"%{eq}%"])

        # Filtro de categoria
        if category and category.strip() and category.strip().lower() != 'todas':
            cat = category.strip()
            if cat in ('no_planificada_sin_parada', 'operativa'):
                query += " AND category IN ('no_planificada_sin_parada', 'operativa')"
            else:
                query += " AND category = ?"
                params.append(cat)

        # Filtro de estado
        if status and status.strip() and status.strip().lower() != 'todos':
            st = status.strip()
            if st == 'activas':
                query += " AND status IN ('pendiente', 'en_progreso')"
            else:
                query += " AND status = ?"
                params.append(st)

        query += " ORDER BY id DESC;"
        rows = conn.execute(query, tuple(params)).fetchall()
        activities = [dict(r) for r in rows]

        # Enriquecer cada actividad con fotos asociadas
        for act in activities:
            img_count = conn.execute("SELECT COUNT(*) FROM maintenance_images WHERE activity_id = ?;", (act['id'],)).fetchone()[0]
            act['images_count'] = img_count

        # Estadisticas resumen para la cabecera del reporte
        total_activities = len(activities)
        completed_count = sum(1 for a in activities if a['status'] == 'completada')
        pending_count = sum(1 for a in activities if a['status'] in ('pendiente', 'en_progreso'))
        unplanned_stop_count = sum(1 for a in activities if a['category'] == 'no_planificada_con_parada')
        unplanned_no_stop_count = sum(1 for a in activities if a['category'] in ('no_planificada_sin_parada', 'operativa'))
        planned_stop_count = sum(1 for a in activities if a['category'] == 'planificada_con_parada')
        planned_no_stop_count = sum(1 for a in activities if a['category'] == 'planificada_sin_parada')

        return {
            'activities': activities,
            'stats': {
                'total': total_activities,
                'completed': completed_count,
                'pending': pending_count,
                'unplanned_stop': unplanned_stop_count,
                'unplanned_no_stop': unplanned_no_stop_count,
                'planned_stop': planned_stop_count,
                'planned_no_stop': planned_no_stop_count,
                'total_stoppage': unplanned_stop_count + planned_stop_count,
                'total_running': unplanned_no_stop_count + planned_no_stop_count
            },
            'filters': {
                'start_date': start_date or '',
                'end_date': end_date or '',
                'equipment': equipment_tag if equipment_tag and equipment_tag.lower() != 'todos' else 'Todos los Equipos',
                'category': category if category and category.lower() != 'todas' else 'Todas las Categorías',
                'status': status if status and status.lower() != 'todos' else 'Todos los Estados'
            },
            'generated_at': get_plant_now().strftime('%d/%m/%Y %H:%M')
        }

