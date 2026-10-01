# Modulo de rutas web y controladores para Mantenimiento Industrial y Pañol de Repuestos
# Importa componentes basicos de Flask para enrutamiento, respuestas, renderizado y mensajes
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, Response, make_response, g
# Importa decorador de proteccion por roles
from core.security import roles_required
# Importa funciones de negocio del servicio de mantenimiento
from modules.maintenance.service import (
    create_maintenance_activity, get_maintenance_activities, get_activity_by_id,
    update_activity_status, save_maintenance_image, get_activity_images,
    get_all_recent_images, create_or_update_spare_part, get_spare_parts,
    get_spare_part_by_id, record_spare_part_movement, get_spare_parts_report_data,
    get_maintenance_repairs_report, get_maintenance_image_data,
    get_placeholder_image_svg, delete_maintenance_image
)
# Importa el servicio de configuracion para obtener equipos y turnos
from modules.configuration.service import get_all_equipment, get_active_shift
# Importa csv e io para la exportacion de reportes
import csv
# Importa io para el buffer en memoria del archivo CSV
import io
# Importa funcion de registro de excepciones tecnicas
from core.error_logger import log_error
# Importa utilidades de conversion numerica segura
from core.utils import safe_float, safe_int

# Crea el Blueprint para el modulo de mantenimiento
maintenance_bp = Blueprint('maintenance', __name__, url_prefix='/maintenance')

# Vista principal del tablero de mantenimiento y pañol
@maintenance_bp.route('/')
# Permite acceso a usuarios operarios y administradores del sistema
@roles_required('usuario', 'admin_sistema', 'administrador', 'gerencia')
def index():
    # Obtiene filtro de categoria si fue provisto
    category_filter = request.args.get('category')
    # Obtiene filtro de estado si fue provisto
    status_filter = request.args.get('status')
    # Obtiene filtro de stock critico para repuestos
    low_stock_filter = request.args.get('low_stock') == '1'
    # Obtiene categoria de repuesto si fue provista
    part_cat_filter = request.args.get('part_category')
    # Obtiene la lista de actividades segun filtros
    activities = get_maintenance_activities(category=category_filter, status=status_filter)
    # Obtiene la lista de repuestos del pañol
    spare_parts = get_spare_parts(filter_low_stock=low_stock_filter, category=part_cat_filter)
    # Obtiene las fotografias recientes de intervenciones
    recent_photos = get_all_recent_images(limit=18)
    # Obtiene datos consolidados del reporte de repuestos
    report_data = get_spare_parts_report_data()
    # Obtiene los equipos configurados en planta para el selector
    equipment_data = get_all_equipment()
    # Obtiene el turno activo
    active_shift = get_active_shift()
    # Renderiza la plantilla principal de mantenimiento
    return render_template(
        'maintenance.html',
        activities=activities,
        spare_parts=spare_parts,
        recent_photos=recent_photos,
        report_data=report_data,
        equipment_data=equipment_data,
        active_shift=active_shift,
        selected_category=category_filter,
        selected_status=status_filter,
        low_stock_filter=low_stock_filter,
        selected_part_category=part_cat_filter
    )

# Endpoint para registrar una nueva actividad o solicitud de intervencion
@maintenance_bp.route('/activity/create', methods=['POST'])
# Requiere rol de usuario operario o admin
@roles_required('usuario', 'admin_sistema')
def create_activity():
    # Bloque de captura de errores de formulario
    try:
        # Extrae titulo de la tarea
        title = request.form.get('title')
        # Extrae categoria oficial (operativa, planificada_con_parada, planificada_sin_parada)
        category = request.form.get('category')
        # Extrae equipo intervenido
        equipment_tag = request.form.get('equipment_tag')
        # Extrae prioridad asignada
        priority = request.form.get('priority', 'media')
        # Extrae descripcion detallada de la intervencion
        description = request.form.get('description', '')
        # Extrae responsable asignado opcional
        assigned_to = request.form.get('assigned_to', '')
        # Extrae fecha programada si aplica
        scheduled_date = request.form.get('scheduled_date')
        # Nombre del usuario que reporta desde la sesion activa
        reported_by = g.user.get('full_name', 'Operario') if hasattr(g, 'user') and g.user else 'Operario'
        # Crea la actividad en base de datos
        activity_id = create_maintenance_activity(
            title, category, equipment_tag, priority, description, reported_by, assigned_to, scheduled_date
        )
        # Si se adjunto una fotografia en el formulario de alta
        if 'photo' in request.files and request.files['photo'].filename:
            # Obtiene el archivo subido
            photo_file = request.files['photo']
            # Guarda la imagen asociada a la nueva actividad
            save_maintenance_image(activity_id, photo_file, caption="Registro inicial de falla")
        # Emite mensaje flash de confirmacion
        flash(f"Actividad de mantenimiento #{activity_id} registrada con éxito.", "success")
        # Si la peticion proviene de AJAX/Fetch
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.is_json:
            # Retorna confirmacion en formato JSON
            return jsonify({'success': True, 'activity_id': activity_id, 'message': f"Actividad #{activity_id} registrada con éxito."})
    # Captura errores de validacion
    except ValueError as ve:
        # Notifica error al usuario
        flash(str(ve), "danger")
        # Si la peticion proviene de AJAX/Fetch
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.is_json:
            # Retorna JSON con codigo de error 400
            return jsonify({'success': False, 'error': str(ve)}), 400
    # Captura otros errores inesperados
    except Exception as e:
        # Notifica error general
        flash(f"Error al registrar actividad: {e}", "danger")
        # Si la peticion proviene de AJAX/Fetch
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.is_json:
            # Retorna JSON con codigo de error 500
            return jsonify({'success': False, 'error': str(e)}), 500
    # Redirige al tablero principal de mantenimiento
    return redirect(url_for('maintenance.index'))

# Endpoint para actualizar el estado de una actividad (en progreso, completada, cancelada)
@maintenance_bp.route('/activity/<int:activity_id>/status', methods=['POST'])
@roles_required('usuario', 'admin_sistema')
def update_status(activity_id):
    # Bloque de captura de excepciones
    try:
        # Obtiene el nuevo estado deseado
        new_status = request.form.get('status')
        # Obtiene nueva categoria opcional para reclasificacion
        category = request.form.get('category')
        # Obtiene notas de resolucion tecnica
        resolution_notes = request.form.get('resolution_notes', '')
        # Nombre del operario que efectua el cambio
        operator_name = g.user.get('full_name', 'Operario') if hasattr(g, 'user') and g.user else 'Operario'
        # Ejecuta la actualizacion de estado y categoria mediante el servicio
        update_activity_status(activity_id, new_status, resolution_notes=resolution_notes, operator_name=operator_name, category=category)
        # Si ademas se cargo una foto de la reparacion terminada
        if 'photo' in request.files and request.files['photo'].filename:
            # Guarda la imagen de cierre
            save_maintenance_image(activity_id, request.files['photo'], caption=f"Intervención: {new_status}")
        # Emite mensaje de exito
        flash(f"Estado de la actividad #{activity_id} actualizado a '{new_status}'.", "success")
        # Si la peticion proviene de AJAX/Fetch
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.is_json:
            # Retorna confirmacion en formato JSON
            return jsonify({'success': True, 'activity_id': activity_id, 'message': f"Estado de la actividad #{activity_id} actualizado a '{new_status}'."})
    # Captura errores
    except Exception as e:
        # Notifica error
        flash(f"Error al actualizar estado: {e}", "danger")
        # Si la peticion proviene de AJAX/Fetch
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.is_json:
            # Retorna error JSON con codigo 400
            return jsonify({'success': False, 'error': str(e)}), 400
    # Retorna al tablero
    return redirect(url_for('maintenance.index'))

# Endpoint para adjuntar una fotografia adicional a una actividad existente
@maintenance_bp.route('/activity/<int:activity_id>/photo', methods=['POST'])
@roles_required('usuario', 'admin_sistema')
def upload_photo(activity_id):
    # Bloque de captura
    try:
        # Extrae archivo de imagen
        photo_file = request.files.get('photo')
        # Extrae epigrafe o descripcion
        caption = request.form.get('caption', 'Registro visual')
        # Guarda la fotografia
        save_maintenance_image(activity_id, photo_file, caption=caption)
        # Emite mensaje flash
        flash("Fotografía adjuntada correctamente al histórico de la reparación.", "success")
        # Si la peticion proviene de AJAX/Fetch
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.is_json:
            # Retorna confirmacion en formato JSON
            return jsonify({'success': True, 'activity_id': activity_id, 'message': 'Fotografía adjuntada correctamente al histórico de la reparación.'})
    # Captura errores
    except Exception as e:
        # Notifica advertencia
        flash(f"Error al cargar fotografía: {e}", "danger")
        # Si la peticion proviene de AJAX/Fetch
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.is_json:
            # Retorna error JSON con codigo 400
            return jsonify({'success': False, 'error': str(e)}), 400
    # Retorna al tablero
    return redirect(url_for('maintenance.index'))

# Endpoint JSON para obtener las fotografias de una intervencion especifica
@maintenance_bp.route('/activity/<int:activity_id>/images', methods=['GET'])
@roles_required('usuario', 'admin_sistema', 'administrador', 'gerencia')
def get_images_json(activity_id):
    # Consulta las imagenes de la actividad
    images = get_activity_images(activity_id)
    # Retorna en formato JSON
    return jsonify({'success': True, 'activity_id': activity_id, 'images': images})

# Endpoint para servir fotografias de mantenimiento por su ID numérico
@maintenance_bp.route('/image/<int:image_id>') # Ruta por ID
def serve_image_by_id(image_id): # Funcion del endpoint
    # Recupera bytes y tipo MIME desde base de datos o disco
    img_bytes, mime_type = get_maintenance_image_data(image_id) # Obtiene datos
    # Si la fotografia existe
    if img_bytes: # Comprueba bytes
        # Crea respuesta HTTP con los bytes binarios
        resp = make_response(img_bytes) # Crea respuesta
        # Asigna el tipo MIME detectado
        resp.headers['Content-Type'] = mime_type or 'image/jpeg' # Header content-type
        # Cabecera de cache publica para imagenes confirmadas
        resp.headers['Cache-Control'] = 'public, max-age=86400, stale-while-revalidate=604800' # Header cache
        # Retorna la respuesta con la imagen real
        return resp # Retorna
    # Si la imagen no está disponible, sirve un SVG placeholder SIN cachear para reintentos inmediatos
    svg_bytes, svg_mime = get_placeholder_image_svg(title="Mantenimiento BioBalcarce", message=f"Fotografía #{image_id} archivada") # Placeholder
    # Crea respuesta con el SVG vectorial
    resp = make_response(svg_bytes) # Crea respuesta
    # Asigna MIME type SVG
    resp.headers['Content-Type'] = svg_mime # Header content-type
    # Deshabilita estrictamente el cacheo del placeholder para evitar bloqueos persistentes en otros navegadores
    resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate' # No cache
    # Compatibilidad con proxies HTTP/1.0
    resp.headers['Pragma'] = 'no-cache' # Pragma
    # Expiracion inmediata
    resp.headers['Expires'] = '0' # Expires
    # Retorna placeholder
    return resp # Retorna

# Endpoint para servir fotografias de mantenimiento por su nombre de archivo
@maintenance_bp.route('/image/<path:filename>') # Ruta por filename
def serve_image_by_filename(filename): # Funcion del endpoint
    # Si se solicita explícitamente el placeholder SVG
    if filename in ('placeholder.svg', 'default.svg'): # Si es placeholder directo
        # Genera placeholder por defecto
        svg_bytes, svg_mime = get_placeholder_image_svg() # Genera svg
        # Crea respuesta HTTP
        resp = make_response(svg_bytes) # Crea respuesta
        # Asigna MIME type SVG
        resp.headers['Content-Type'] = svg_mime # Header content-type
        # Evita almacenamiento en cache del placeholder
        resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate' # No cache
        # Compatibilidad HTTP/1.0
        resp.headers['Pragma'] = 'no-cache' # Pragma
        # Expiracion
        resp.headers['Expires'] = '0' # Expires
        # Retorna respuesta
        return resp # Retorna
    # Busca por filename en base de datos o disco con auto-recuperacion
    img_bytes, mime_type = get_maintenance_image_data(filename) # Obtiene datos
    # Si se encontro la imagen binaria
    if img_bytes: # Comprueba bytes
        # Crea respuesta con la imagen real
        resp = make_response(img_bytes) # Crea respuesta
        # Asigna tipo MIME
        resp.headers['Content-Type'] = mime_type or 'image/jpeg' # Header content-type
        # Cache publico para imagenes reales existentes
        resp.headers['Cache-Control'] = 'public, max-age=86400, stale-while-revalidate=604800' # Header cache
        # Retorna la respuesta
        return resp # Retorna
    # Fallback SVG si no se encuentra en ningun repositorio (sin cachear)
    svg_bytes, svg_mime = get_placeholder_image_svg(title="Mantenimiento BioBalcarce", message="Fotografía no disponible") # Genera svg
    # Crea respuesta
    resp = make_response(svg_bytes) # Crea respuesta
    # Asigna MIME SVG
    resp.headers['Content-Type'] = svg_mime # Header content-type
    # Deshabilita almacenamiento en cache para reintentar cuando se sincronice
    resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate' # No cache
    # Header pragma
    resp.headers['Pragma'] = 'no-cache' # Pragma
    # Header expires
    resp.headers['Expires'] = '0' # Expires
    # Retorna placeholder
    return resp # Retorna

# Endpoint para eliminar una fotografía de mantenimiento
@maintenance_bp.route('/image/<int:image_id>/delete', methods=['POST'])
@roles_required('usuario', 'admin_sistema', 'administrador')
def delete_photo(image_id):
    # Elimina la foto de la base de datos y de disco
    success = delete_maintenance_image(image_id)
    # Si la solicitud vino via AJAX/Fetch
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.is_json:
        return jsonify({'success': success})
    # Si vino via formulario HTML tradicional
    if success:
        flash(f"Fotografía #{image_id} eliminada correctamente.", "success")
    else:
        flash(f"No se pudo encontrar la fotografía #{image_id}.", "warning")
    return redirect(request.referrer or url_for('maintenance.index'))

# Endpoint para dar de alta o editar un repuesto en el catalogo
@maintenance_bp.route('/spare_part/save', methods=['POST'])
@roles_required('usuario', 'admin_sistema')
def save_spare_part():
    # Bloque protegido
    try:
        # Obtiene ID si es edicion
        part_id = request.form.get('part_id')
        # Codigo de repuesto
        code = request.form.get('code')
        # Denominacion del repuesto
        name = request.form.get('name')
        # Categoria de pieza
        category = request.form.get('category', 'General')
        # Equipo asignado
        equipment_assigned = request.form.get('equipment_assigned', 'Planta General')
        # Indicador de consumible (1 si esta marcado, 0 si no)
        is_consumable = request.form.get('is_consumable') == '1'
        # Stock actual inicial
        stock_quantity = safe_float(request.form.get('stock_quantity'), 0.0)
        # Stock minimo de seguridad
        min_stock = safe_float(request.form.get('min_stock'), 0.0)
        # Unidad de medida
        unit = request.form.get('unit', 'unidades')
        # Ubicacion fisica
        location = request.form.get('location', '')
        # Observaciones tecnicas
        notes = request.form.get('notes', '')
        # Ejecuta alta o modificacion
        saved_id = create_or_update_spare_part(
            code, name, category, equipment_assigned, is_consumable,
            stock_quantity, min_stock, unit, location, notes,
            part_id=safe_int(part_id, default=None)
        )
        # Emite mensaje flash
        flash(f"Repuesto '{code}' guardado correctamente.", "success")
    # Captura errores
    except Exception as e:
        # Notifica error
        flash(f"Error al guardar repuesto: {e}", "danger")
    # Redirige a la pestaña de repuestos
    return redirect(url_for('maintenance.index') + '#tab-spare-parts')

# Endpoint para asentar un movimiento de stock (ingreso o egreso por reparacion)
@maintenance_bp.route('/spare_part/movement', methods=['POST'])
@roles_required('usuario', 'admin_sistema')
def spare_part_movement():
    # Bloque de captura
    try:
        # ID del repuesto
        part_id = safe_int(request.form.get('spare_part_id'), default=None)
        if not part_id:
            raise ValueError("Debe seleccionar un repuesto válido.")
        # Tipo de movimiento
        movement_type = request.form.get('movement_type')
        # Cantidad del movimiento
        quantity = safe_float(request.form.get('quantity'), 0.0)
        # Motivo o reparacion
        reason = request.form.get('reason', '')
        # Actividad vinculada opcional
        activity_id = request.form.get('activity_id')
        # Nombre del operador responsable
        operator_name = g.user.get('full_name', 'Operario') if hasattr(g, 'user') and g.user else 'Operario'
        # Registra el movimiento mediante el servicio
        new_stock = record_spare_part_movement(
            part_id, movement_type, quantity, operator_name,
            reason=reason, activity_id=safe_int(activity_id, default=None)
        )
        # Emite mensaje flash
        flash(f"Movimiento de stock asentado con éxito. Nuevo stock: {new_stock}.", "success")
    # Captura errores
    except Exception as e:
        # Registra la excepcion en bitacora y en la base de datos de errores
        log_error('MAINTENANCE_ROUTE', 'Error al registrar movimiento de repuesto', e)
        # Notifica error
        flash(f"Error al registrar movimiento: {e}", "danger")
    # Redirige al pañol
    return redirect(url_for('maintenance.index') + '#tab-spare-parts')

# Endpoint para exportar el inventario de repuestos a un archivo CSV estructurado
@maintenance_bp.route('/report/csv')
@roles_required('usuario', 'admin_sistema', 'administrador', 'gerencia')
def export_csv():
    # Obtiene todos los repuestos con indicadores de criticidad
    parts = get_spare_parts()
    # Crea un buffer de texto en memoria
    output = io.StringIO()
    # Escribe BOM UTF-8 para compatibilidad nativa con Microsoft Excel
    output.write('\ufeff')
    # Inicializa el escritor CSV con delimitador punto y coma tipico de Excel en espanol
    writer = csv.writer(output, delimiter=';')
    # Escribe cabecera de columnas
    writer.writerow([
        'Código', 'Denominación del Repuesto', 'Categoría', 'Equipo Asignado',
        'Tipo', 'Stock Actual', 'Stock Mínimo', 'Unidad', 'Estado de Stock',
        'Ubicación en Pañol', 'Observaciones'
    ])
    # Itera sobre cada repuesto del inventario
    for p in parts:
        # Determina texto descriptivo del tipo
        tipo_str = 'Consumible' if p['is_consumable'] == 1 else 'Repuesto Mecánico'
        # Determina texto de estado de reposicion
        estado_str = 'CRÍTICO - REPOSICIÓN' if p['is_critical'] else 'NORMAL'
        # Escribe la fila de datos
        writer.writerow([
            p['code'], p['name'], p['category'], p['equipment_assigned'],
            tipo_str, f"{p['stock_quantity']:.2f}", f"{p['min_stock']:.2f}",
            p['unit'], estado_str, p['location'], p['notes']
        ])
    # Crea la respuesta HTTP con el archivo adjunto
    response = Response(output.getvalue(), mimetype='text/csv; charset=utf-8')
    # Define la cabecera para descarga con nombre fechado
    response.headers['Content-Disposition'] = 'attachment; filename=Reporte_Repuestos_BioBalcarce.csv'
    # Retorna el archivo CSV generado
    return response

# Vista dedicada para impresion limpia del reporte de repuestos
@maintenance_bp.route('/report/print')
@roles_required('usuario', 'admin_sistema', 'administrador', 'gerencia')
def print_report():
    # Obtiene datos consolidados del reporte
    report_data = get_spare_parts_report_data()
    # Renderiza plantilla minimalista para impresion
    return render_template('maintenance_print.html', report=report_data)

# Vista dedicada para impresion oficial del reporte de reparaciones e intervenciones
@maintenance_bp.route('/report/repairs/print')
@roles_required('usuario', 'admin_sistema', 'administrador', 'gerencia')
def print_repairs_report():
    # Obtiene parametros de filtrado desde la URL
    start_date = request.args.get('start_date', '').strip()
    end_date = request.args.get('end_date', '').strip()
    equipment_tag = request.args.get('equipment', '').strip()
    category = request.args.get('category', '').strip()
    status = request.args.get('status', '').strip()

    # Genera el conjunto de datos enriquecidos y metricas
    report_data = get_maintenance_repairs_report(
        start_date=start_date,
        end_date=end_date,
        equipment_tag=equipment_tag,
        category=category,
        status=status
    )
    # Obtiene listado de equipos para el selector de filtros de pantalla
    equipment_list = get_all_equipment()

    # Renderiza la plantilla imprimible oficial
    return render_template(
        'maintenance_activities_print.html',
        report=report_data,
        equipment_list=equipment_list
    )
