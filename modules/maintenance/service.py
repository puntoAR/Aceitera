# Modulo de logica de negocio para mantenimiento industrial y stock de repuestos
# Importa datetime para marcas de tiempo y fechas programadas
import datetime
# Importa os para operaciones con rutas de archivos y directorios
import os
# Importa uuid para generar identificadores unicos de nombres de imagenes
import uuid
# Importa secure_filename para sanitizar nombres de archivos cargados
from werkzeug.utils import secure_filename
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
    # Valida que la categoria sea una de las tres oficiales
    valid_categories = ('operativa', 'planificada_con_parada', 'planificada_sin_parada')
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
            # Agrega clausula de filtro por categoria
            query += " AND category = ?"
            # Agrega el valor a los parametros
            params.append(category)
        # Si se especifica un estado particular
        if status:
            # Agrega clausula de filtro por estado
            query += " AND status = ?"
            # Agrega el valor del estado a los parametros
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

# Actualiza el estado y notas tecnicas de cierre de una actividad
def update_activity_status(activity_id, status, resolution_notes=None, completed_at=None, operator_name='Sistema'):
    # Valida los estados permitidos
    valid_statuses = ('pendiente', 'en_progreso', 'completada', 'cancelada')
    # Verifica que el estado indicado este contemplado
    if status not in valid_statuses:
        # Lanza error si el estado es desconocido
        raise ValueError(f"Estado inválido. Debe ser: {', '.join(valid_statuses)}")
    # Si el estado es completada y no se paso fecha, toma la hora oficial de planta (Argentina UTC-3)
    if status == 'completada' and not completed_at:
        completed_at = get_plant_now_str()
    # Abre conexion para modificar el registro
    with get_db_connection() as conn:
        # Ejecuta el update de estado y resolucion
        conn.execute("""
            UPDATE maintenance_activities
            SET status = ?, resolution_notes = COALESCE(?, resolution_notes), completed_at = COALESCE(?, completed_at)
            WHERE id = ?;
        """, (status, resolution_notes, completed_at, activity_id))
        # Confirma la modificacion
        conn.commit()
    # Registra en auditoria el cambio de estado
    record_audit_event('MANTENIMIENTO', 'ESTADO_ACTUALIZADO', f"Actividad #{activity_id} actualizada a '{status}' por {operator_name}.")
    # Retorna verdadero confirmando la actualizacion
    return True

# Guarda una fotografia de reparacion en disco y la asocia a la actividad
def save_maintenance_image(activity_id, file_storage, caption=None):
    # Verifica que el objeto de archivo sea valido y tenga nombre
    if not file_storage or not file_storage.filename:
        # Lanza excepcion si no se recibio archivo
        raise ValueError("No se seleccionó ningún archivo de imagen para cargar.")
    # Sanitiza el nombre original del archivo
    orig_name = secure_filename(file_storage.filename)
    # Extrae la extension en minusculas
    ext = orig_name.rsplit('.', 1)[-1].lower() if '.' in orig_name else ''
    # Comprueba si la extension esta dentro de las autorizadas
    if ext not in config.ALLOWED_IMAGE_EXTENSIONS:
        # Lanza error de extension no permitida
        raise ValueError(f"Formato no permitido. Use: {', '.join(config.ALLOWED_IMAGE_EXTENSIONS)}")
    # Genera un nombre de archivo seguro y unico
    unique_filename = f"maint_{activity_id}_{uuid.uuid4().hex[:10]}.{ext}"
    # Define la ruta absoluta en disco donde se guardara la fotografia
    destination_path = os.path.join(config.MAINTENANCE_UPLOADS_DIR, unique_filename)
    # Guarda el archivo fisico en disco
    file_storage.save(destination_path)
    # Abre conexion para registrar la imagen en la base de datos
    with get_db_connection() as conn:
        # Inserta el registro en maintenance_images
        cursor = conn.execute("""
            INSERT INTO maintenance_images (activity_id, filename, caption)
            VALUES (?, ?, ?);
        """, (activity_id, unique_filename, caption.strip() if caption else 'Registro visual'))
        # Obtiene el identificador asignado
        image_id = cursor.lastrowid
        # Confirma la transaccion
        conn.commit()
    # Registra en auditoria la subida de la imagen
    record_audit_event('MANTENIMIENTO', 'FOTO_SUBIDA', f"Foto #{image_id} cargada para actividad #{activity_id} ({unique_filename}).")
    # Retorna el nombre de archivo almacenado
    return unique_filename

# Obtiene todas las imagenes vinculadas a una actividad especifica
def get_activity_images(activity_id):
    # Abre conexion a la base de datos
    with get_db_connection() as conn:
        # Consulta las imagenes asociadas a la actividad ordenadas cronologicamente
        rows = conn.execute("SELECT * FROM maintenance_images WHERE activity_id = ? ORDER BY id ASC;", (activity_id,)).fetchall()
        # Retorna la lista de imagenes como diccionarios
        return [dict(row) for row in rows]

# Obtiene las fotografias mas recientes de todas las intervenciones para galeria general
def get_all_recent_images(limit=30):
    # Abre conexion
    with get_db_connection() as conn:
        # Consulta imagenes cruzadas con el titulo de la actividad
        rows = conn.execute("""
            SELECT mi.*, ma.title as activity_title, ma.category as activity_category, ma.equipment_tag
            FROM maintenance_images mi
            JOIN maintenance_activities ma ON mi.activity_id = ma.id
            ORDER BY mi.id DESC LIMIT ?;
        """, (limit,)).fetchall()
        # Retorna el resultado estructurado
        return [dict(row) for row in rows]

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

# Obtiene los tres indicadores clave de mantenimiento para el cockpit ejecutivo
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
                'planned_stop_count': 0
            }
        
        # Conteo de tareas pendientes
        pending = conn.execute("SELECT COUNT(*) FROM maintenance_activities WHERE status = 'pendiente';").fetchone()[0]
        # Conteo de tareas operativas (urgencias / en marcha)
        operative = conn.execute("SELECT COUNT(*) FROM maintenance_activities WHERE category = 'operativa';").fetchone()[0]
        # Conteo de tareas planificadas con parada de planta
        planned_stop = conn.execute("SELECT COUNT(*) FROM maintenance_activities WHERE category = 'planificada_con_parada';").fetchone()[0]
        
        # Retorna el diccionario de KPIs para el dashboard
        return {
            'pending_count': int(pending or 0),
            'operative_count': int(operative or 0),
            'planned_stop_count': int(planned_stop or 0)
        }

