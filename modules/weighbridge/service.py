# Servicio de gestion de balanza de camiones, importacion/exportacion de pesadas e integracion con existencias
import io
import csv
import datetime
# Importa expresiones regulares para limpieza de etiquetas y prefijos de namespace XML
import re
# Intento protegido de importacion de la libreria openpyxl para manipular planillas Excel
try:
    # Importa el modulo openpyxl
    import openpyxl
    # Importa clases de formato y estilo para celdas Excel
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
# Captura la ausencia de openpyxl en entornos restringidos
except ImportError:
    # Asigna None para permitir la carga del servicio sin dependencias obligatorias
    openpyxl = None
# Intento protegido de importacion de la libreria xlrd para planillas Excel clasicas (.xls)
try:
    # Importa el modulo xlrd
    import xlrd
# Captura la ausencia de xlrd en entornos restringidos
except ImportError:
    # Asigna None si la libreria no esta disponible
    xlrd = None
# Importa el analizador HTML de la biblioteca estandar para procesar planillas .xls formateadas como HTML
from html.parser import HTMLParser
# Importa ElementTree de la biblioteca estandar para procesar planillas .xls en formato XML Spreadsheet
import xml.etree.ElementTree as ET
from core.database import get_db_connection
from core.timezone import get_plant_now_str
from core.audit import record_audit_event
from core.error_logger import log_error, log_info
# Importa funcion de normalizacion de fechas
from core.utils import normalize_date_str # Funcion utilitaria de fechas normalizadas


# Analizador robusto de tablas HTML para archivos generados por balanzas industriales exportados con extension .xls
class HTMLTableParser(HTMLParser):
    # Inicializa el analizador de filas y celdas
    def __init__(self):
        # Llama al constructor de la clase base
        super().__init__()
        # Lista de filas acumuladas
        self.rows = []
        # Fila actual en proceso
        self.current_row = []
        # Contenido de la celda actual
        self.current_cell = []
        # Bandera de celda abierta
        self.in_cell = False

    # Procesa apertura de etiquetas html
    def handle_starttag(self, tag, attrs):
        # Normaliza la etiqueta a minusculas
        tag_l = tag.lower()
        # Si es celda de datos o encabezado
        if tag_l in ('td', 'th'):
            # Activa bandera de celda
            self.in_cell = True
            # Reinicia el acumulador de texto de celda
            self.current_cell = []
        # Si es inicio de fila
        elif tag_l == 'tr':
            # Reinicia la fila actual
            self.current_row = []

    # Procesa texto dentro de las etiquetas
    def handle_data(self, data):
        # Si se encuentra dentro de una celda
        if self.in_cell:
            # Acumula el fragmento de texto
            self.current_cell.append(data)

    # Procesa cierre de etiquetas html
    def handle_endtag(self, tag):
        # Normaliza etiqueta a minusculas
        tag_l = tag.lower()
        # Si se cierra una celda
        if tag_l in ('td', 'th'):
            # Desactiva bandera de celda
            self.in_cell = False
            # Concatena y limpia el texto de la celda
            cell_text = ''.join(self.current_cell).strip()
            # Agrega el texto a la fila actual
            self.current_row.append(cell_text)
        # Si se cierra una fila
        elif tag_l == 'tr':
            # Si la fila tiene al menos una celda con contenido
            if self.current_row:
                # Agrega la fila al conjunto de filas extraidas
                self.rows.append(self.current_row)

# Normaliza texto para comparacion insensible a acentos, espacios, marcas BOM y mayusculas
def _clean_header(h): # Funcion de saneamiento de nombres de columnas
    # Si viene vacio o nulo
    if h is None: # Comprueba si el valor es nulo
        # Retorna cadena vacia
        return '' # Retorna vacio
    # Convierte a texto plano
    h = str(h) # Conversion explicita a cadena
    # Remueve marcas UTF-8 BOM, espacios especiales de no separacion y caracteres de control
    h = re.sub(r'[\ufeff\u200b\u200c\u200d\xa0\x00-\x1f\x7f-\x9f]', '', h) # Sanea caracteres invisibles
    # Convierte a texto en minusculas sin espacios extremos
    h = h.strip().lower() # Minusculas y recorte lateral
    # Reemplaza vocales acentuadas
    h = h.replace('á', 'a').replace('é', 'e').replace('í', 'i').replace('ó', 'o').replace('ú', 'u') # Normaliza tildes
    # Reemplaza signos de puntuacion, guiones y barras por espacios
    h = h.replace('_', ' ').replace('-', ' ').replace('.', '').replace('/', ' ') # Normaliza separadores
    # Retorna texto limpio con espacios unificados
    return ' '.join(h.split()) # Retorna texto estandarizado

# Determina el tipo de operacion y producto estandarizado a partir de texto libre
def _normalize_operation_and_product(raw_op, raw_prod):
    # Limpia tipo de operacion
    op = (raw_op or '').strip().lower()
    # Limpia tipo de producto
    prod = (raw_prod or '').strip().lower()

    # Normalizacion de operacion
    if any(k in op for k in ['egreso', 'salida', 'despacho', 'venta', 'embarque']):
        # Asigna operacion de egreso
        operation_type = 'egreso'
    # Si indica ingreso
    elif any(k in op for k in ['ingreso', 'entrada', 'compra', 'recepcion', 'descarga']):
        # Asigna operacion de ingreso
        operation_type = 'ingreso'
    # Si es movimiento interno
    elif any(k in op for k in ['interno', 'trasvase', 'recirculacion']):
        # Asigna operacion interna
        operation_type = 'interno'
    # Deduccion segun el producto si la operacion no esta explicita
    else:
        # Si es semilla de girasol
        if 'semilla' in prod or 'girasol' in prod:
            # Asigna ingreso
            operation_type = 'ingreso'
        # Si es producto terminado (aceite o expeller)
        elif 'aceite' in prod or 'expeller' in prod:
            # Asigna egreso
            operation_type = 'egreso'
        # Fallback general
        else:
            # Por defecto ingreso
            operation_type = 'ingreso'

    # Normalizacion de producto
    if 'semilla' in prod or 'grano' in prod or 'girasol' in prod:
        # Semilla
        product_norm = 'semilla'
    # Aceite crudo
    elif 'aceite' in prod:
        # Aceite
        product_norm = 'aceite'
    # Expeller
    elif 'expeller' in prod or 'pellet' in prod or 'harina' in prod:
        # Expeller
        product_norm = 'expeller'
    # Insumos
    elif 'insumo' in prod or 'repuesto' in prod or 'quimico' in prod or 'solvente' in prod or 'lena' in prod or 'gas' in prod:
        # Insumos
        product_norm = 'insumos'
    # Otros productos
    else:
        # Conserva nombre o insumos
        product_norm = prod or 'insumos'

    # Retorna tupla de operacion y producto
    return operation_type, product_norm

# Registra una pesada de balanza de camion en la base de datos con las 27 columnas estandar
def record_weighing(
    ticket_number=None, weigh_date=None, operation_type='ingreso', product='semilla',
    truck_plate=None, trailer_plate=None, transport_company=None,
    driver_name=None, driver_dni=None,
    gross_weight_kg=0.0, tare_weight_kg=0.0, net_weight_kg=None,
    origin=None, destination=None, origin_name=None, destination_name=None,
    seals_numbers=None, notes=None,
    operator_name='Balanza', shift_id='TC', sync_inventory=False,
    exit_date=None, entry_date=None, client=None, recipient=None,
    origin_destination=None, user_id_code='1', exit_weight_kg=None,
    entry_weight_kg=None, exporter=None, manual_tare='NO',
    driver_nationality='Argentina', packages=None, customs=None,
    lot=None, single_weighing='NO', customs_destination=None,
    conn=None # Conexion opcional para ejecucion en lote reutilizable
): # Fin de firma de record_weighing
    # Asigna origen de la carga
    origin = origin or origin_name or ''
    # Asigna destino de la carga
    destination = destination or destination_name or ''
    # Conversion segura a punto flotante de peso bruto
    gross = float(gross_weight_kg or 0.0)
    # Conversion segura a punto flotante de tara
    tare = float(tare_weight_kg or 0.0)

    # Normaliza fecha de pesada o recurre a fechas de egreso/ingreso o fecha oficial de planta
    weigh_date = normalize_date_str(weigh_date) or normalize_date_str(exit_date) or normalize_date_str(entry_date) or get_plant_now_str() # Fecha oficial normalizada
    # Normaliza fecha de ingreso
    entry_date = normalize_date_str(entry_date) or (weigh_date if operation_type == 'ingreso' else weigh_date) # Fecha ingreso normalizada
    # Normaliza fecha de egreso
    exit_date = normalize_date_str(exit_date) or (weigh_date if operation_type == 'egreso' else weigh_date) # Fecha egreso normalizada


    # Procedencia o destino consolidado
    origin_destination = origin_destination or destination or origin or 'BioBalcarce'
    # Cliente
    client = client or destination or ''
    # Destinatario
    recipient = recipient or destination or ''

    # Peso en ingreso
    if entry_weight_kg is not None and float(entry_weight_kg or 0.0) > 0:
        # Usa valor explicitamente enviado
        p_ingreso = float(entry_weight_kg)
    # Si no vino
    else:
        # En egreso entra vacio (tara), en ingreso entra cargado (bruto)
        p_ingreso = tare if operation_type == 'egreso' and tare > 0 else (gross if gross > 0 else 0.0)

    # Peso en egreso
    if exit_weight_kg is not None and float(exit_weight_kg or 0.0) > 0:
        # Usa valor explicitamente enviado
        p_egreso = float(exit_weight_kg)
    # Si no vino
    else:
        # En egreso sale cargado (bruto), en ingreso sale vacio (tara)
        p_egreso = gross if operation_type == 'egreso' and gross > 0 else (tare if tare > 0 else 0.0)

    # Si no se envio neto explicito, se calcula por diferencia
    if net_weight_kg is not None and float(net_weight_kg) > 0:
        # Asigna peso neto recibido
        net = float(net_weight_kg)
    # Si hay pesos de ingreso y egreso
    elif p_ingreso > 0 and p_egreso > 0:
        # Neto es la diferencia absoluta
        net = abs(p_ingreso - p_egreso)
    # Fallback por bruto y tara
    else:
        # Diferencia de bruto menos tara
        net = max(0.0, gross - tare)

    # Convierte neto a toneladas
    net_tons = round(net / 1000.0, 3)

    # Define funcion interna para ejecutar el INSERT y sincronizacion
    def _do_record_insert(target_conn): # Funcion auxiliar de insercion
        # Inserta la pesada completa con las 27 columnas estandar
        cursor = target_conn.execute("""
            INSERT INTO truck_scale_weighings (
                ticket_number, weigh_date, operation_type, product,
                truck_plate, trailer_plate, transport_company,
                driver_name, driver_dni,
                gross_weight_kg, tare_weight_kg, net_weight_kg, net_weight_tons,
                origin, destination, seals_numbers, notes,
                operator_name, shift_id, sync_inventory,
                exit_date, entry_date, client, recipient, origin_destination,
                user_id_code, exit_weight_kg, entry_weight_kg, exporter,
                manual_tare, driver_nationality, packages, customs,
                lot, single_weighing, customs_destination
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                      ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """, (
            ticket_number, weigh_date, operation_type, product,
            (truck_plate or '').upper(), (trailer_plate or '').upper() if trailer_plate else None,
            transport_company, driver_name, driver_dni,
            gross, tare, net, net_tons,
            origin, destination, seals_numbers, notes,
            operator_name, shift_id, 1 if sync_inventory else 0,
            exit_date, entry_date, client, recipient, origin_destination,
            str(user_id_code or '1'), p_egreso, p_ingreso, exporter,
            manual_tare or 'NO', driver_nationality or 'Argentina', packages, customs,
            lot, single_weighing or 'NO', customs_destination
        )) # Fin ejecucion SQL
        # Obtiene ID asignado a la fila
        weighing_id = cursor.lastrowid # Asigna lastrowid
        # Si se solicita sincronizar con existencias de inventario
        if sync_inventory and net > 0: # Comprobacion de flag y neto
            # Importa servicio de movimientos de inventario
            from modules.inventory.service import record_inventory_movement # Importa servicio
            # Captura posibles excepciones sin abortar pesada
            try: # Bloque protegido
                # El movimiento de inventario impacta en el stock general
                inv_mov_type = 'ingreso' if operation_type == 'ingreso' else 'despacho' # Tipo de movimiento
                # Normaliza producto para silos y tanques
                inv_prod = product if product in ['semilla', 'aceite', 'expeller'] else 'semilla' # Producto de stock
                # Detalle del comprobante
                inv_notes = f"Balanza Ticket {ticket_number or weighing_id} - Camión {truck_plate or '-'}" # Comentario
                # Registra el movimiento
                record_inventory_movement( # Llama servicio
                    product=inv_prod, # Producto
                    movement_type=inv_mov_type, # Tipo
                    origin=origin or 'Balanza Báscula', # Origen
                    destination=destination or 'Planta BioBalcarce', # Destino
                    quantity_kg=net, # Kilos netos
                    document_ref=f"BAL-{ticket_number or weighing_id}", # Referencia documental
                    shift_id=shift_id, # Turno
                    operator_name=operator_name, # Operador
                    notes=inv_notes # Observaciones
                ) # Fin llamada
            # Manejo de error de sincronizacion
            except Exception as e: # Captura error
                # Registra en bitacora
                log_error('WEIGHBRIDGE_SERVICE', f"No se pudo sincronizar inventario para pesada {weighing_id}", e) # Log error
        # Confirma transaccion en base de datos
        target_conn.commit() # Confirma transaccion
        # Retorna ID de pesada
        return weighing_id # Retorna identificador

    # Si se proporciono una conexion existente
    if conn is not None: # Verifica conexion externa
        # Ejecuta la insercion con la conexion suministrada
        return _do_record_insert(conn) # Insercion directa
    # Si no se suministro conexion
    else: # Abre nueva conexion
        # Abre conexion para insertar el registro
        with get_db_connection() as new_conn: # Conexion propia
            # Ejecuta la insercion y retorna el ID
            return _do_record_insert(new_conn) # Insercion segura

# Expresion SQL para normalizar y comparar fechas en SQLite y Turso (soporta ISO, DD/MM/YYYY y DD-MM-YYYY)
_SQL_WEIGH_DATE_EXPR = """
CASE
  WHEN COALESCE(NULLIF(weigh_date, ''), NULLIF(exit_date, ''), NULLIF(entry_date, '')) LIKE '__/__/____%'
    THEN substr(COALESCE(NULLIF(weigh_date, ''), NULLIF(exit_date, ''), NULLIF(entry_date, '')), 7, 4) || '-' ||
         substr(COALESCE(NULLIF(weigh_date, ''), NULLIF(exit_date, ''), NULLIF(entry_date, '')), 4, 2) || '-' ||
         substr(COALESCE(NULLIF(weigh_date, ''), NULLIF(exit_date, ''), NULLIF(entry_date, '')), 1, 2) ||
         substr(COALESCE(NULLIF(weigh_date, ''), NULLIF(exit_date, ''), NULLIF(entry_date, '')), 11)
  WHEN COALESCE(NULLIF(weigh_date, ''), NULLIF(exit_date, ''), NULLIF(entry_date, '')) LIKE '_/__/____%'
    THEN substr(COALESCE(NULLIF(weigh_date, ''), NULLIF(exit_date, ''), NULLIF(entry_date, '')), 6, 4) || '-' ||
         substr(COALESCE(NULLIF(weigh_date, ''), NULLIF(exit_date, ''), NULLIF(entry_date, '')), 3, 2) || '-0' ||
         substr(COALESCE(NULLIF(weigh_date, ''), NULLIF(exit_date, ''), NULLIF(entry_date, '')), 1, 1) ||
         substr(COALESCE(NULLIF(weigh_date, ''), NULLIF(exit_date, ''), NULLIF(entry_date, '')), 10)
  WHEN COALESCE(NULLIF(weigh_date, ''), NULLIF(exit_date, ''), NULLIF(entry_date, '')) LIKE '__-__-____%'
    THEN substr(COALESCE(NULLIF(weigh_date, ''), NULLIF(exit_date, ''), NULLIF(entry_date, '')), 7, 4) || '-' ||
         substr(COALESCE(NULLIF(weigh_date, ''), NULLIF(exit_date, ''), NULLIF(entry_date, '')), 4, 2) || '-' ||
         substr(COALESCE(NULLIF(weigh_date, ''), NULLIF(exit_date, ''), NULLIF(entry_date, '')), 1, 2) ||
         substr(COALESCE(NULLIF(weigh_date, ''), NULLIF(exit_date, ''), NULLIF(entry_date, '')), 11)
  ELSE COALESCE(NULLIF(weigh_date, ''), NULLIF(exit_date, ''), NULLIF(entry_date, ''))
END
"""

# Obtiene la lista filtrada de pesadas de balanza para la vista web con soporte de ordenamiento
def get_recent_weighings(limit=500, product=None, operation_type=None, search=None, start_date=None, end_date=None, order_by='ticket_asc'): # Consulta pesadas con filtros completos y orden
    # Sentencia base de consulta
    query = "SELECT * FROM truck_scale_weighings WHERE 1=1" # Base SQL
    # Lista de parametros para prevenir inyecciones SQL
    params = [] # Parametros

    # Filtro por producto
    if product and product != 'todos': # Si se especifico un producto
        # Agrega clausula de producto
        query += " AND product = ?" # Filtro producto
        # Agrega parametro
        params.append(product) # Parametro producto

    # Filtro por operacion
    if operation_type and operation_type != 'todos': # Si se especifico operacion
        # Agrega clausula de operacion
        query += " AND operation_type = ?" # Filtro operacion
        # Agrega parametro
        params.append(operation_type) # Parametro operacion

    # Filtro de busqueda textual
    if search: # Si hay texto de busqueda
        # Formatea comodines para busqueda parcial
        term = f"%{search.strip()}%" # Termino con comodines
        # Agrega condiciones que cubren patentes, tickets, chofer, transportista, cliente, notas y DNI
        query += " AND (truck_plate LIKE ? OR trailer_plate LIKE ? OR ticket_number LIKE ? OR driver_name LIKE ? OR transport_company LIKE ? OR notes LIKE ? OR client LIKE ? OR recipient LIKE ? OR origin_destination LIKE ? OR driver_dni LIKE ?)" # Cobertura de busqueda
        # Extiende parametros con 10 repeticiones del termino
        params.extend([term] * 10) # 10 campos buscados

    # Filtro de fecha inicial
    if start_date: # Si se indico fecha desde
        # Normaliza fecha inicial a YYYY-MM-DD
        s_norm = normalize_date_str(start_date)[:10] if start_date else '' # Extrae primeros 10 caracteres ISO
        # Si la fecha inicial es valida
        if s_norm: # Fecha valida
            # Compara subcadena normalizada de la fecha
            query += f" AND substr(({_SQL_WEIGH_DATE_EXPR}), 1, 10) >= ?" # Condicion de fecha inicial
            # Agrega parametro normalizado
            params.append(s_norm) # Parametro fecha inicial

    # Filtro de fecha final
    if end_date: # Si se indico fecha hasta
        # Normaliza fecha final a YYYY-MM-DD
        e_norm = normalize_date_str(end_date)[:10] if end_date else '' # Extrae primeros 10 caracteres ISO
        # Si la fecha final es valida
        if e_norm: # Fecha valida
            # Compara subcadena normalizada de la fecha
            query += f" AND substr(({_SQL_WEIGH_DATE_EXPR}), 1, 10) <= ?" # Condicion de fecha final
            # Agrega parametro normalizado
            params.append(e_norm) # Parametro fecha final

    # Normaliza opcion de ordenamiento solicitada
    ob = str(order_by or 'ticket_asc').strip().lower() # Limpia texto de ordenamiento
    # Si se solicito orden por ticket descendente
    if ob == 'ticket_desc': # Caso ticket descendente
        # Ordena tickets numericos de mayor a menor y nulos al final
        order_clause = """
            CASE WHEN ticket_number IS NOT NULL AND ticket_number != '' AND ticket_number NOT GLOB '*[^0-9]*' THEN 0 ELSE 1 END,
            CASE WHEN ticket_number IS NOT NULL AND ticket_number != '' AND ticket_number NOT GLOB '*[^0-9]*' THEN CAST(ticket_number AS INTEGER) ELSE id END DESC,
            ticket_number DESC, id DESC
        """ # Clausula SQL descendente
    # Si se solicito orden cronologico descendente (mas reciente primero)
    elif ob == 'date_desc': # Caso fecha descendente
        # Ordena por fecha normalizada descendente
        order_clause = f"({_SQL_WEIGH_DATE_EXPR}) DESC, id DESC" # Clausula SQL fecha desc
    # Si se solicito orden cronologico ascendente (mas antigua primero)
    elif ob == 'date_asc': # Caso fecha ascendente
        # Ordena por fecha normalizada ascendente
        order_clause = f"({_SQL_WEIGH_DATE_EXPR}) ASC, id ASC" # Clausula SQL fecha asc
    # Por omision: ticket ascendente (1095, 1096... 1207)
    else: # Caso ticket ascendente por defecto
        # Ordena tickets numericos de menor a mayor y alfanumericos al final
        order_clause = """
            CASE WHEN ticket_number IS NOT NULL AND ticket_number != '' AND ticket_number NOT GLOB '*[^0-9]*' THEN 0 ELSE 1 END,
            CASE WHEN ticket_number IS NOT NULL AND ticket_number != '' AND ticket_number NOT GLOB '*[^0-9]*' THEN CAST(ticket_number AS INTEGER) ELSE id END ASC,
            ticket_number ASC, id ASC
        """ # Clausula SQL ascendente

    # Concatena clausula ORDER BY en la consulta SQL
    query += f" ORDER BY {order_clause}" # Aplica orden

    # Si se especifico un limite maximo de registros
    if limit: # Limite definido
        # Concatena clausula LIMIT
        query += " LIMIT ?" # Limite SQL
        # Agrega valor de limite
        params.append(limit) # Parametro limite

    # Abre conexion protegida
    with get_db_connection() as conn: # Conexion
        # Ejecuta consulta parametrizada
        rows = conn.execute(query, params).fetchall() # Obtiene filas
        # Retorna lista de diccionarios
        return [dict(r) for r in rows] # Retorna resultados

# Obtiene metricas agregadas para las tarjetas superiores de KPI sincronizadas con todos los filtros activos
def get_weighing_summary_stats(start_date=None, end_date=None, product=None, operation_type=None, search=None, **kwargs): # Recibe todos los filtros aplicados
    # Sentencia SQL agregada por tipo de operacion y producto
    query = """
        SELECT operation_type, product, SUM(net_weight_kg) as total_kg, COUNT(*) as count 
        FROM truck_scale_weighings 
        WHERE 1=1
    """ # Consulta base agregada
    # Lista de parametros SQL
    params = [] # Parametros

    # Filtro opcional por producto
    if product and product != 'todos': # Si no es comodin todos
        # Agrega condicion de producto
        query += " AND product = ?" # Filtro producto
        # Agrega parametro
        params.append(product) # Parametro producto

    # Filtro opcional por tipo de operacion
    if operation_type and operation_type != 'todos': # Si no es comodin todos
        # Agrega condicion de operacion
        query += " AND operation_type = ?" # Filtro operacion
        # Agrega parametro
        params.append(operation_type) # Parametro operacion

    # Filtro de texto de busqueda
    if search: # Si hay termino de busqueda
        # Formatea termino con comodines
        term = f"%{search.strip()}%" # Termino busqueda
        # Cobertura sobre patentes, chofer, transporte, cliente, destinatario, notas y DNI
        query += " AND (truck_plate LIKE ? OR trailer_plate LIKE ? OR ticket_number LIKE ? OR driver_name LIKE ? OR transport_company LIKE ? OR notes LIKE ? OR client LIKE ? OR recipient LIKE ? OR origin_destination LIKE ? OR driver_dni LIKE ?)" # Filtro busqueda
        # Extiende parametros
        params.extend([term] * 10) # 10 campos

    # Filtro por fecha inicial
    if start_date: # Si se indico fecha desde
        # Normaliza fecha inicial
        s_norm = normalize_date_str(start_date)[:10] if start_date else '' # Normalizacion a YYYY-MM-DD
        # Si la fecha inicial es valida
        if s_norm: # Fecha inicial valida
            # Condicion de fecha inicial
            query += f" AND substr(({_SQL_WEIGH_DATE_EXPR}), 1, 10) >= ?" # Filtro fecha inicial
            # Parametro fecha inicial
            params.append(s_norm) # Parametro

    # Filtro por fecha final
    if end_date: # Si se indico fecha hasta
        # Normaliza fecha final
        e_norm = normalize_date_str(end_date)[:10] if end_date else '' # Normalizacion a YYYY-MM-DD
        # Si la fecha final es valida
        if e_norm: # Fecha final valida
            # Condicion de fecha final
            query += f" AND substr(({_SQL_WEIGH_DATE_EXPR}), 1, 10) <= ?" # Filtro fecha final
            # Parametro fecha final
            params.append(e_norm) # Parametro

    # Agrupa por operacion y producto
    query += " GROUP BY operation_type, product" # Agrupamiento SQL

    # Abre conexion protegida
    with get_db_connection() as conn: # Conexion activa
        # Ejecuta consulta de metricas
        rows = conn.execute(query, params).fetchall() # Obtiene filas agrupadas

    # Estructura de metricas acumuladas
    stats = { # Diccionario de estadisticas
        'total_trucks': 0, # Total de camiones/pesadas
        'total_ingreso_tons': 0.0, # Toneladas totales de ingreso
        'total_egreso_tons': 0.0, # Toneladas totales de egreso
        'semilla_ingreso_tons': 0.0, # Toneladas de semilla ingresadas
        'expeller_egreso_tons': 0.0, # Toneladas de expeller egresadas
        'aceite_egreso_tons': 0.0, # Toneladas de aceite egresadas
        'insumos_tons': 0.0 # Toneladas de insumos varios
    } # Fin estructura de estadisticas

    # Itera los resultados agrupados
    for r in rows: # Itera cada grupo
        # Sentido de operacion
        op = r['operation_type'] # Operacion
        # Denominacion del producto
        prod = r['product'] # Producto
        # Peso total en toneladas con 2 decimales
        tons = round((r['total_kg'] or 0.0) / 1000.0, 2) # Conversion a toneladas
        # Cantidad de pesadas en el grupo
        count = r['count'] or 0 # Conteo de registros

        # Suma camiones totales
        stats['total_trucks'] += count # Acumula total de pesadas
        # Si la operacion es de ingreso
        if op == 'ingreso': # Operacion ingreso
            # Acumula total ingresado
            stats['total_ingreso_tons'] += tons # Acumula toneladas
            # Si el producto es semilla
            if prod == 'semilla': # Semilla
                # Acumula semilla
                stats['semilla_ingreso_tons'] += tons # Acumula semilla
            # Otros productos de ingreso
            else: # Insumos
                # Acumula insumos
                stats['insumos_tons'] += tons # Acumula insumos
        # Si la operacion es de egreso
        elif op == 'egreso': # Operacion egreso
            # Acumula total egresado
            stats['total_egreso_tons'] += tons # Acumula toneladas
            # Si el producto es expeller
            if prod == 'expeller': # Expeller
                # Acumula expeller
                stats['expeller_egreso_tons'] += tons # Acumula expeller
            # Si el producto es aceite
            elif prod == 'aceite': # Aceite
                # Acumula aceite
                stats['aceite_egreso_tons'] += tons # Acumula aceite
            # Otros productos de egreso
            else: # Otros
                # Acumula insumos
                stats['insumos_tons'] += tons # Acumula insumos

    # Redondeo de seguridad
    stats['total_ingreso_tons'] = round(stats['total_ingreso_tons'], 2) # Redondeo ingreso
    stats['total_egreso_tons'] = round(stats['total_egreso_tons'], 2) # Redondeo egreso
    stats['semilla_ingreso_tons'] = round(stats['semilla_ingreso_tons'], 2) # Redondeo semilla
    stats['expeller_egreso_tons'] = round(stats['expeller_egreso_tons'], 2) # Redondeo expeller
    stats['aceite_egreso_tons'] = round(stats['aceite_egreso_tons'], 2) # Redondeo aceite
    stats['insumos_tons'] = round(stats['insumos_tons'], 2) # Redondeo insumos

    # Aliases de compatibilidad
    stats['seed_in_tons'] = stats['semilla_ingreso_tons'] # Alias semilla
    stats['oil_out_tons'] = stats['aceite_egreso_tons'] # Alias aceite
    stats['expeller_out_tons'] = stats['expeller_egreso_tons'] # Alias expeller

    # Retorna diccionario de estadisticas
    return stats # Retorna stats


# Extrae renglones crudos soportando XLSX moderno, XLS binario, XLS HTML, XLS XML y CSV/TSV
def _extract_rows_from_file(raw_bytes, filename=''):
    # Inicializa lista de filas extraidas
    raw_rows = []
    # Normaliza el nombre de archivo a minusculas
    fn = str(filename).lower()

    # 1. Intento A: Si empieza con firma ZIP (PK\x03\x04) o tiene extension .xlsx, intenta con openpyxl
    if raw_bytes.startswith(b'PK\x03\x04') or fn.endswith('.xlsx'):
        # Si openpyxl esta disponible en el entorno
        if openpyxl is not None:
            # Captura posibles excepciones de openpyxl
            try:
                # Carga el libro Excel con solo valores de datos
                wb = openpyxl.load_workbook(io.BytesIO(raw_bytes), data_only=True)
                # Selecciona la hoja activa
                sheet = wb.active
                # Itera sobre las filas de la hoja
                for row in sheet.iter_rows(values_only=True):
                    # Agrega la fila como lista
                    raw_rows.append(list(row))
                # Si obtuvo datos validos, los retorna de inmediato
                if raw_rows and len(raw_rows) >= 2:
                    # Retorna las filas extraidas
                    return raw_rows
            # Si falla openpyxl (por ejemplo si el archivo no es un zip real)
            except Exception:
                # Continua con los siguientes analizadores alternativos
                pass

    # 2. Intento B: Si empieza con firma OLE2 (Compound File \xd0\xcf\x11\xe0) o tiene extension .xls binaria
    if raw_bytes.startswith(b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1') or fn.endswith('.xls'):
        # Si xlrd esta disponible
        if xlrd is not None:
            # Bloque de captura de errores de formato binario
            try:
                # Abre el libro binario con xlrd
                wb = xlrd.open_workbook(file_contents=raw_bytes)
                # Selecciona la primera hoja de calculo
                sheet = wb.sheet_by_index(0)
                # Itera por el numero de filas de la hoja
                for r in range(sheet.nrows):
                    # Lista de valores de la fila
                    row_vals = []
                    # Itera sobre cada columna
                    for c in range(sheet.ncols):
                        # Obtiene el tipo de celda
                        c_type = sheet.cell_type(r, c)
                        # Obtiene el valor crudo de la celda
                        c_val = sheet.cell_value(r, c)
                        # Si la celda es de tipo fecha
                        if c_type == xlrd.XL_CELL_DATE:
                            # Intenta convertir la fecha Excel a formato estandar
                            try:
                                # Convierte a tupla de fecha
                                dt_tuple = xlrd.xldate_as_tuple(c_val, wb.datemode)
                                # Crea el objeto datetime
                                dt = datetime.datetime(*dt_tuple)
                                # Agrega fecha formateada
                                row_vals.append(dt.strftime('%Y-%m-%d %H:%M:%S'))
                            # En caso de error en la fecha
                            except Exception:
                                # Guarda representacion textual
                                row_vals.append(str(c_val))
                        # Si la celda es de tipo numerico
                        elif c_type == xlrd.XL_CELL_NUMBER:
                            # Si es un numero entero
                            if isinstance(c_val, float) and c_val.is_integer():
                                # Agrega como entero
                                row_vals.append(int(c_val))
                            # Si tiene decimales
                            else:
                                # Agrega el numero flotante
                                row_vals.append(c_val)
                        # Para otros tipos de celdas (texto, booleano, etc.)
                        else:
                            # Agrega el valor directamente
                            row_vals.append(c_val)
                    # Agrega la fila a la coleccion
                    raw_rows.append(row_vals)
                # Si obtuvo datos validos, los retorna
                if raw_rows and len(raw_rows) >= 2:
                    # Retorna las filas
                    return raw_rows
            # Si no es un archivo BIFF8 soportado
            except Exception:
                # Continua con otros analizadores
                pass

    # 3. Intento C: Decodificacion textual (HTML Table, SpreadsheetML XML, CSV o TSV)
    # Intenta decodificar con distintos encodings comunes en software de balanzas
    text_content = None
    # Lista de codificaciones a probar
    for enc in ['utf-8', 'latin-1', 'cp1252', 'iso-8859-1']:
        # Intenta decodificar
        try:
            # Decodifica los bytes
            text_content = raw_bytes.decode(enc)
            # Corta el bucle si tuvo exito
            break
        # Captura error de decodificacion
        except (UnicodeDecodeError, Exception):
            # Prueba con el siguiente encoding
            continue

    # Si se logro decodificar a texto
    if text_content:
        # Muestra en minusculas para deteccion de etiquetas
        sample = text_content[:4096].lower()

        # C1. Analisis si es una tabla HTML exportada con extension .xls
        if '<table' in sample or '<tr' in sample or '<html' in sample:
            # Intento de parseo con HTMLTableParser
            try:
                # Instancia el analizador HTML
                html_p = HTMLTableParser()
                # Procesa el contenido completo
                html_p.feed(text_content)
                # Si encontro filas validas
                if html_p.rows and len(html_p.rows) >= 2:
                    # Retorna las filas de la tabla HTML
                    return html_p.rows
            # Si ocurre error al parsear HTML
            except Exception:
                # Continua con las demas opciones
                pass

        # C2. Analisis si es un SpreadsheetML XML exportado como .xls
        if '<workbook' in sample or '<?xml' in sample:
            # Intento de parseo de XML Spreadsheet
            try:
                # Limpia prefijos de namespace de etiquetas como ss: para evitar errores de unbound prefix
                cleaned_xml = re.sub(r'<(/?)(\w+):', r'<\1', text_content)
                # Limpia prefijos de atributos con namespace como ss:Name o ss:Type
                cleaned_xml = re.sub(r'\s+(\w+):(\w+)=', r' \2=', cleaned_xml)
                # Parsea el arbol XML saneado
                root = ET.fromstring(cleaned_xml)
                # Lista contenedora de filas XML extraidas
                xml_rows = []
                # Itera buscando elementos de fila en el documento
                for elem in root.iter():
                    # Si el tag termina en Row (insensible al namespace)
                    if elem.tag.endswith('Row'):
                        # Celdas de la fila actual
                        row_cells = []
                        # Itera sobre los elementos hijos directos de la fila
                        for cell_elem in elem:
                            # Valor por defecto de la celda
                            cell_val = ''
                            # Itera sobre los elementos contenidos en la celda
                            for child in cell_elem:
                                # Si el elemento es un contenedor de datos Data
                                if child.tag.endswith('Data'):
                                    # Extrae el texto del dato
                                    cell_val = child.text or ''
                                    # Finaliza la busqueda de dato para esta celda
                                    break
                            # Si no tenia hijo Data pero tenia texto directo en la celda
                            if not cell_val and cell_elem.text and cell_elem.text.strip():
                                # Asigna el texto directo encontrado
                                cell_val = cell_elem.text.strip()
                            # Agrega el valor de texto a la fila
                            row_cells.append(cell_val)
                        # Si la fila contiene al menos una celda
                        if row_cells:
                            # Agrega la fila a la coleccion de filas
                            xml_rows.append(row_cells)
                # Si extrajo al menos fila de cabecera y una fila de datos
                if xml_rows and len(xml_rows) >= 2:
                    # Retorna las filas de la planilla XML
                    return xml_rows
            # Si falla el parseo XML
            except Exception:
                # Continua con la siguiente estrategia
                pass

        # C3. Analisis si es texto delimitado (CSV / TSV / punto y coma)
        # Cuenta ocurrencias de delimitadores en la muestra
        cnt_tab = sample.count('\t')
        # Cuenta punto y coma
        cnt_semi = sample.count(';')
        # Cuenta comas
        cnt_comma = sample.count(',')
        # Determina el delimitador mas probable
        if cnt_tab > cnt_semi and cnt_tab > cnt_comma and cnt_tab > 2:
            # Tabulador
            delim = '\t'
        elif cnt_semi > cnt_comma:
            # Punto y coma
            delim = ';'
        else:
            # Coma por defecto
            delim = ','

        # Intento de lectura CSV
        try:
            # Crea lector CSV
            csv_reader = csv.reader(io.StringIO(text_content), delimiter=delim)
            # Extrae todas las filas
            csv_rows = [list(r) for r in csv_reader if r]
            # Si obtuvo datos coherentes
            if csv_rows and len(csv_rows) >= 2:
                # Retorna las filas CSV
                return csv_rows
        # Si falla el lector CSV
        except Exception:
            # Continua
            pass

    # 4. Fallback final: Si openpyxl todavia no se intento y esta disponible
    if openpyxl is not None and not raw_bytes.startswith(b'PK\x03\x04'):
        # Intenta una ultima vez con openpyxl
        try:
            # Carga el archivo
            wb = openpyxl.load_workbook(io.BytesIO(raw_bytes), data_only=True)
            # Lee filas
            raw_rows = [list(r) for r in wb.active.iter_rows(values_only=True)]
            # Si tiene datos
            if raw_rows and len(raw_rows) >= 2:
                # Retorna filas
                return raw_rows
        # Si falla
        except Exception:
            # Pasa
            pass

    # Si ninguno de los analizadores logro extraer los datos
    if not raw_rows or len(raw_rows) < 2:
        # Lanza error descriptivo indicando las alternativas compatibles
        raise ValueError(
            "No fue posible interpretar el archivo de balanza. El sistema admite Excel moderno (.xlsx), "
            "Excel clásico (.xls en formato binario, HTML o XML) y texto delimitado (.csv). "
            "Verifique que el archivo contenga datos o guarde la planilla en formato .xlsx o .csv antes de subirla."
        )

    # Retorna las filas
    return raw_rows

# Importador inteligente de archivos Excel (.xlsx, .xls) y CSV de balanza
def import_weighings_from_file(file_storage, filename=None, operator_name='Balanza', shift_id='TC', sync_inventory=False):
    # Si no se envio el nombre del archivo, intenta obtenerlo del objeto file_storage
    if filename is None:
        # Obtiene el nombre del archivo adjunto
        filename = getattr(file_storage, 'filename', '') or ''
    # Normaliza el nombre del archivo a minusculas
    filename = str(filename).lower()
    # Inicializa la lista de registros procesados
    records = []

    # Extrae el contenido en bytes del archivo recibido
    if isinstance(file_storage, bytes):
        # Asigna directamente si ya son bytes
        raw_bytes = file_storage
    # Si es un objeto tipo stream o archivo de Flask
    elif hasattr(file_storage, 'read'):
        # Lee los bytes del flujo
        raw_bytes = file_storage.read()
        # Si tiene soporte para rebobinar el cursor, lo reinicia
        if hasattr(file_storage, 'seek'):
            # Vuelve el puntero al inicio
            file_storage.seek(0)
    # En caso de cadenas de texto u otros tipos
    else:
        # Convierte a representacion en bytes
        raw_bytes = str(file_storage).encode('utf-8')

    # Extrae las filas del archivo utilizando el extractor multitipo universal
    raw_rows = _extract_rows_from_file(raw_bytes, filename=filename)

    # Verifica que el archivo no este vacio o contenga un solo renglon
    if not raw_rows or len(raw_rows) < 2:
        # Lanza error si no hay datos suficientes
        raise ValueError("El archivo se encuentra vacío o no posee renglones de datos.")

    # Busca la fila de encabezados analizando las primeras 10 lineas
    header_idx = -1
    col_map = {}

    for idx, row in enumerate(raw_rows[:10]):
        if not row:
            continue
        cleaned = [_clean_header(c) for c in row if c is not None]
        # Si la fila contiene palabras clave de balanza
        keywords = ['ticket', 'fecha', 'patente', 'bruto', 'tara', 'neto', 'producto', 'chofer', 'camion', 'material']
        match_count = sum(1 for kw in keywords if any(kw in c for c in cleaned))
        if match_count >= 2:
            header_idx = idx
            break

    if header_idx == -1:
        # Fallback al primer renglon si no se detectaron encabezados tipicos
        header_idx = 0

    header_row = raw_rows[header_idx] # Fila detectada que contiene las cabeceras
    for c_idx, cell in enumerate(header_row): # Itera cada celda de encabezado
        norm = _clean_header(cell) # Limpia y normaliza texto del encabezado
        if not norm: # Si la celda está vacía continúa
            continue # Salta a siguiente columna

        # Mapeo de columnas estándar de balanza y sus variantes abreviadas o truncadas
        if 'fecha egreso' in norm or ('salida' in norm and 'fecha' in norm): # Cabecera de fecha de egreso
            col_map['fecha_egreso'] = c_idx # Guarda índice de fecha egreso
        elif 'fecha ingreso' in norm or ('entrada' in norm and 'fecha' in norm): # Cabecera de fecha de ingreso
            col_map['fecha_ingreso'] = c_idx # Guarda índice de fecha ingreso
        elif any(k in norm for k in ['fecha', 'hora', 'date', 'timestamp']): # Cabecera genérica de fecha
            if 'fecha' not in col_map: # Prioriza primer campo fecha detectado
                col_map['fecha'] = c_idx # Guarda índice general de fecha
        elif any(k in norm for k in ['peso egreso', 'peso egr', 'egreso peso']) or ('salida' in norm and 'peso' in norm): # Cabecera de peso de egreso
            col_map['peso_egreso'] = c_idx # Guarda índice de peso egreso
        elif any(k in norm for k in ['peso ingreso', 'peso ing', 'ingreso peso']) or ('entrada' in norm and 'peso' in norm): # Cabecera de peso de ingreso
            col_map['peso_ingreso'] = c_idx # Guarda índice de peso ingreso
        elif any(k in norm for k in ['peso neto', 'peso net']) or norm in ['neto', 'net'] or 'kg neto' in norm: # Cabecera de peso neto
            col_map['neto'] = c_idx # Guarda índice de peso neto
        elif any(k in norm for k in ['peso bruto', 'peso brut']) or norm in ['bruto', 'brut'] or 'kg bruto' in norm or 'pesada 1' in norm: # Cabecera de peso bruto
            col_map['bruto'] = c_idx # Guarda índice de peso bruto
        elif 'tara m' in norm or norm in ['tara_m', 'tara manual', 'tara ma']: # Cabecera de tara manual
            col_map['tara_manual'] = c_idx # Guarda índice de tara manual
        elif 'peso tara' in norm or norm == 'tara' or 'kg tara' in norm or 'pesada 2' in norm: # Cabecera de peso tara estándar
            col_map['tara'] = c_idx # Guarda índice de peso tara
        elif any(k in norm for k in ['id usuar', 'id_usuar', 'cod usuar', 'id op', 'id usuaric']): # Cabecera de código ID de usuario
            col_map['id_usuario'] = c_idx # Guarda índice de ID usuario
        elif norm in ['usuario', 'operador', 'user', 'usuar']: # Cabecera de nombre de usuario/operador
            col_map['usuario'] = c_idx # Guarda índice de usuario
        elif norm in ['id', 'ticket', 'comprobante', 'remito', 'boleta', 'nro', 'n', 'no', '#'] or (norm.startswith('id') and 'usuar' not in norm and 'user' not in norm and 'op' not in norm): # Cabecera identificadora de pesada/ticket
            if 'ticket' not in col_map: # Asigna si no fue mapeado previamente
                col_map['ticket'] = c_idx # Guarda índice de ticket o ID
        elif 'cliente' in norm: # Cabecera de cliente
            col_map['cliente'] = c_idx # Guarda índice de cliente
        elif 'proceden' in norm and 'destino' in norm: # Cabecera combinada Procedencia/Destino (evaluada antes de destino solo)
            col_map['procedencia_destino'] = c_idx # Guarda índice de procedencia/destino
        elif 'destinat' in norm: # Cabecera de destinatario (cubre Destinatario y Destinata)
            col_map['destinatario'] = c_idx # Guarda índice de destinatario
        elif any(k in norm for k in ['transport', 'transp', 'empresa', 'razon social']): # Cabecera de empresa transportista (cubre 'Transport' y 'Transportista')
            col_map['transporte'] = c_idx # Guarda índice de transporte
        elif any(k in norm for k in ['acoplado', 'acop', 'patente a', 'pat a', 'trailer', 'semi']): # Cabecera de patente de acoplado (cubre 'Patente A')
            col_map['acoplado'] = c_idx # Guarda índice de acoplado
        elif any(k in norm for k in ['chasis', 'camion', 'patente c', 'pat c', 'dominio']) or ('patente' in norm and 'acoplado' not in norm and 'patente a' not in norm): # Cabecera de patente de chasis
            if 'chasis' not in col_map: # Si no se ha asignado patente de chasis
                col_map['chasis'] = c_idx # Guarda índice de chasis
        elif any(k in norm for k in ['origen', 'proceden', 'proveedor']): # Cabecera de origen o procedencia (cubre 'Proceden')
            col_map['origen'] = c_idx # Guarda índice de origen
        elif any(k in norm for k in ['destino']): # Cabecera de destino
            col_map['destino'] = c_idx # Guarda índice de destino
        elif any(k in norm for k in ['dni', 'cuit', 'documento']): # Cabecera de documento del chofer (evaluada antes de chofer)
            col_map['dni'] = c_idx # Guarda índice de DNI chofer
        elif any(k in norm for k in ['chofer', 'conductor', 'nombre c', 'chofe']) and 'dni' not in norm: # Cabecera de nombre de chofer
            col_map['chofer'] = c_idx # Guarda índice de chofer
        elif 'nacionali' in norm: # Cabecera de nacionalidad del chofer (cubre 'Nacionali' y 'Nacionalidad')
            col_map['nacionalidad'] = c_idx # Guarda índice de nacionalidad
        elif 'export' in norm: # Cabecera de exportador (cubre 'Exportado')
            col_map['exportador'] = c_idx # Guarda índice de exportador
        elif any(k in norm for k in ['bulto', 'bultos', 'paquete', 'paquetes']): # Cabecera de cantidad de bultos
            col_map['bultos'] = c_idx # Guarda índice de bultos
        elif 'aduana' in norm: # Cabecera de aduana
            col_map['aduana'] = c_idx # Guarda índice de aduana
        elif norm in ['lot', 'lote'] or 'lote' in norm: # Cabecera de lote o LOT
            col_map['lot'] = c_idx # Guarda índice de LOT
        elif any(k in norm for k in ['pesada u', 'pesada_u']): # Cabecera de pesada única (cubre 'Pesada Un')
            col_map['pesada_unica'] = c_idx # Guarda índice de pesada única
        elif any(k in norm for k in ['destinac', 'destinacion']): # Cabecera de destinación aduanera (cubre 'Destinaci')
            col_map['destinacion'] = c_idx # Guarda índice de destinación
        elif any(k in norm for k in ['producto', 'material', 'cereal', 'mercaderia']): # Cabecera de producto o material
            col_map['producto'] = c_idx # Guarda índice de producto
        elif any(k in norm for k in ['operacion', 'movimiento', 'sentido', 'tipo']): # Cabecera de tipo de operación
            col_map['operacion'] = c_idx # Guarda índice de tipo de operación
        elif any(k in norm for k in ['precinto', 'precintos', 'seals']): # Cabecera de precintos
            col_map['precintos'] = c_idx # Guarda índice de precintos
        elif any(k in norm for k in ['observa', 'notas', 'obs']): # Cabecera de observaciones (cubre 'Observaci')
            col_map['notas'] = c_idx # Guarda índice de observaciones

    # Fallback garantizado para Ticket en la primera columna si no fue asignado previamente
    if 'ticket' not in col_map and len(header_row) > 0: # Si ticket aun no esta en el mapa de columnas
        first_col_norm = _clean_header(header_row[0]) # Normaliza cabecera de la primera celda
        if not any(k in first_col_norm for k in ['fecha', 'date', 'peso', 'neto', 'bruto', 'tara', 'prod']): # Verifica no ser metrica o fecha
            col_map['ticket'] = 0 # Asigna columna 0 como identificador irrepetible de ticket

    imported_count = 0 # Inicializa contador de importados exitosos
    skipped_count = 0 # Inicializa contador de registros ignorados
    errors = [] # Lista de errores detectados en la importación

    # Procesa cada fila de datos a partir de header_idx + 1
    for r_idx, row in enumerate(raw_rows[header_idx + 1:], start=header_idx + 2): # Itera filas de datos
        if not row or all(c is None or str(c).strip() == '' for c in row): # Verifica si la fila está en blanco
            continue # Ignora fila vacía

        def get_val(key, default=''): # Función auxiliar para obtener cadena de texto
            if key in col_map and col_map[key] < len(row): # Si la clave está en el mapa
                v = row[col_map[key]] # Obtiene valor de celda
                if v is None: # Si es None
                    return default # Retorna valor por omisión
                if isinstance(v, datetime.datetime): # Si es tipo datetime
                    return v.strftime('%Y-%m-%d %H:%M:%S') # Formatea a texto con hora
                if isinstance(v, datetime.date): # Si es tipo date
                    return v.strftime('%Y-%m-%d') # Formatea a texto solo fecha
                if isinstance(v, float) and v.is_integer(): # Si es flotante entero ej 1095.0
                    return str(int(v)) # Formatea a numero entero en cadena
                if isinstance(v, int): # Si ya es entero
                    return str(v) # Retorna como cadena
                s = str(v).strip() # Limpia espacios de la cadena
                if re.match(r'^\d+\.0+$', s): # Si es cadena con decimales ceros
                    s = s.split('.')[0] # Remueve ceros decimales innecesarios
                return s # Retorna cadena sin espacios laterales
            return default # Retorna valor por omisión si no existe la columna

        def get_float(key, default=0.0): # Función auxiliar para obtener número de punto flotante
            val_str = get_val(key) # Obtiene valor en texto
            if not val_str: # Si está vacío
                return default # Retorna número por omisión
            try: # Intenta conversión numérica
                # Normaliza separadores de miles y decimales
                val_str = val_str.replace('.', '').replace(',', '.') if ',' in val_str and '.' in val_str else val_str.replace(',', '.') # Conversión de formato
                return float(val_str) # Retorna valor flotante convertido
            except ValueError: # Si falla la conversión
                return default # Retorna número por omisión

        ticket = get_val('ticket') # Extrae número de ticket o comprobante
        if ticket and re.match(r'^\d+\.0+$', ticket): # Si el ticket tiene formato decimal ej 1095.0
            ticket = ticket.split('.')[0] # Limpia a entero puro
        fecha_egreso = normalize_date_str(get_val('fecha_egreso')) # Extrae fecha de egreso normalizada
        fecha_ingreso = normalize_date_str(get_val('fecha_ingreso')) # Extrae fecha de ingreso normalizada
        fecha = fecha_egreso or fecha_ingreso or normalize_date_str(get_val('fecha')) or get_plant_now_str() # Resuelve fecha de la pesada normalizada
        chasis = get_val('chasis') # Extrae patente de chasis
        acoplado = get_val('acoplado') # Extrae patente de acoplado
        chofer = get_val('chofer') # Extrae nombre de chofer
        dni = get_val('dni') # Extrae DNI de chofer
        transporte = get_val('transporte') # Extrae empresa transportista
        raw_prod = get_val('producto') # Extrae denominación de producto
        raw_op = get_val('operacion') # Extrae operación original
        peso_egreso = get_float('peso_egreso') # Extrae peso de egreso en kg
        peso_ingreso = get_float('peso_ingreso') # Extrae peso de ingreso en kg
        bruto = get_float('bruto') # Extrae peso bruto en kg
        tara = get_float('tara') # Extrae tara en kg
        neto = get_float('neto') # Extrae peso neto en kg
        cliente = get_val('cliente') # Extrae cliente
        destinatario = get_val('destinatario') # Extrae destinatario
        origen_destino = get_val('procedencia_destino') # Extrae texto combinado procedencia/destino
        origen = get_val('origen') or origen_destino # Extrae origen o fallback a procedencia/destino
        destino = get_val('destino') or destinatario or cliente # Extrae destino o fallback
        precintos = get_val('precintos') # Extrae precintos
        notas = get_val('notas') # Extrae observaciones
        id_usuario = get_val('id_usuario') or '1' # Extrae ID de usuario balancero
        usuario = get_val('usuario') # Extrae nombre de usuario
        exportador = get_val('exportador') # Extrae exportador
        tara_manual = get_val('tara_manual') or 'NO' # Extrae indicador de tara manual
        nacionalidad = get_val('nacionalidad') or 'Argentina' # Extrae nacionalidad de chofer
        bultos = get_val('bultos') # Extrae bultos
        aduana = get_val('aduana') # Extrae aduana
        lot = get_val('lot') # Extrae LOT
        pesada_unica = get_val('pesada_unica') or 'NO' # Extrae indicador de pesada única
        destinacion = get_val('destinacion') # Extrae destinación

        # Si no hay chasis ni ticket ni pesos, saltea fila vacía
        if not chasis and not ticket and bruto == 0.0 and neto == 0.0 and peso_egreso == 0.0 and peso_ingreso == 0.0: # Condición de fila vacía
            skipped_count += 1 # Incrementa contador de omitidos
            continue # Salta al siguiente renglón

        # Deducir pesos si solo vienen peso_egreso y peso_ingreso
        if peso_egreso > 0.0 and peso_ingreso > 0.0: # Si ambos pesos de báscula están presentes
            if peso_egreso > peso_ingreso: # Si peso de egreso es mayor es una salida de producto cargado
                if not raw_op: # Si no se especificó la operación
                    raw_op = 'egreso' # Asigna egreso como tipo de operación
                if bruto <= 0.0: # Si no había peso bruto explícito
                    bruto = peso_egreso # El peso de egreso corresponde al bruto
                if tara <= 0.0: # Si no había tara explícita
                    tara = peso_ingreso # El peso de ingreso corresponde a la tara
            elif peso_ingreso > peso_egreso: # Si peso de ingreso es mayor es una entrada de materia prima
                if not raw_op: # Si no se especificó la operación
                    raw_op = 'ingreso' # Asigna ingreso como tipo de operación
                if bruto <= 0.0: # Si no había peso bruto explícito
                    bruto = peso_ingreso # El peso de ingreso corresponde al bruto
                if tara <= 0.0: # Si no había tara explícita
                    tara = peso_egreso # El peso de egreso corresponde a la tara
            if neto <= 0.0: # Si el peso neto no vino informado
                neto = abs(peso_egreso - peso_ingreso) # Calcula neto como diferencia absoluta
        elif peso_egreso > 0.0 and peso_ingreso == 0.0: # Si solo vino peso de egreso
            if not raw_op: # Si no se especificó la operación
                raw_op = 'egreso' # Asigna operación de egreso
            if bruto <= 0.0: # Si bruto no está definido
                bruto = peso_egreso # Toma peso de egreso como bruto
        elif peso_ingreso > 0.0 and peso_egreso == 0.0: # Si solo vino peso de ingreso
            if not raw_op: # Si no se especificó la operación
                raw_op = 'ingreso' # Asigna operación de ingreso
            if bruto <= 0.0: # Si bruto no está definido
                bruto = peso_ingreso # Toma peso de ingreso como bruto

        # Si el neto es 0 pero hay bruto y tara, calcula neto por diferencia
        if neto <= 0.0 and bruto > 0.0 and tara > 0.0: # Comprueba si se puede derivar el neto
            neto = max(0.0, abs(bruto - tara)) # Deriva neto positivo

        # Normaliza unidades si los pesos vinieron en toneladas
        if 0 < neto < 150: # Detección de magnitud menor a 150 (toneladas)
            neto = neto * 1000.0 # Convierte neto a kilogramos
            bruto = bruto * 1000.0 if bruto < 150 else bruto # Convierte bruto a kilogramos
            tara = tara * 1000.0 if tara < 150 else tara # Convierte tara a kilogramos
            peso_egreso = peso_egreso * 1000.0 if 0 < peso_egreso < 150 else peso_egreso # Convierte peso egreso a kg
            peso_ingreso = peso_ingreso * 1000.0 if 0 < peso_ingreso < 150 else peso_ingreso # Convierte peso ingreso a kg

        # Normaliza tipo de operación y producto
        op_type, prod_norm = _normalize_operation_and_product(raw_op, raw_prod) # Invoca normalizador
        # Infiere sentido de operación según producto si no vino definido
        if not raw_op: # Si no vino operación en el archivo
            if prod_norm == 'semilla': # Si es semilla normalmente es recepción
                op_type = 'ingreso' # Asigna ingreso
            elif prod_norm in ['expeller', 'aceite']: # Si es aceite o expeller normalmente es despacho
                op_type = 'egreso' # Asigna egreso

        # Asegura valores para peso egreso y peso ingreso si no vinieron explícitos
        if peso_egreso == 0.0 and peso_ingreso == 0.0: # Si no estaban seteados
            if op_type == 'egreso': # Para despachos
                peso_egreso = bruto if bruto > 0.0 else neto # Egreso con carga
                peso_ingreso = tara # Ingreso vacío
            else: # Para ingresos de materia prima
                peso_ingreso = bruto if bruto > 0.0 else neto # Ingreso con carga
                peso_egreso = tara # Egreso vacío

        # Verifica si ya existe una pesada previa para actualizarla o registrar nueva
        existing_id = None # Inicializa identificador de registro existente
        try: # Intento de busqueda de registro preexistente
            with get_db_connection() as conn: # Abre conexion a base de datos
                if ticket: # Si se especifico numero de ticket
                    # Consulta pesada por comprobante o ticket exacto
                    row_found = conn.execute("SELECT id FROM truck_scale_weighings WHERE ticket_number = ?;", (ticket,)).fetchone() # Busca ticket
                    if not row_found and str(ticket).isdigit(): # Intenta coincidencia por ticket numerico
                        row_found = conn.execute("SELECT id FROM truck_scale_weighings WHERE CAST(ticket_number AS INTEGER) = ?;", (int(ticket),)).fetchone() # Numerico
                    if row_found: # Si encontro registro coincidente
                        existing_id = row_found['id'] if isinstance(row_found, dict) else row_found[0] # Obtiene identificador existente
                # Si no encontro por ticket y el ticket corresponde a la secuencia historica (1000 a 1228)
                if not existing_id and ticket and str(ticket).isdigit(): # Comprobacion de rango historico
                    t_num = int(ticket) # Numero de ticket entero
                    if 1000 <= t_num <= 1228: # Rango historico
                        cand_id = 1228 - t_num # Id calculado
                        row_found = conn.execute("SELECT id FROM truck_scale_weighings WHERE id = ?;", (cand_id,)).fetchone() # Busca por id historico
                        if row_found: # Si encontro
                            existing_id = row_found['id'] if isinstance(row_found, dict) else row_found[0] # Asigna id
                # Si no encontro por ticket pero hay patente y fecha
                if not existing_id and chasis and (fecha_egreso or fecha_ingreso or fecha): # Condiciones para deduccion
                    t_day = (fecha_egreso or fecha_ingreso or fecha)[:10] # Solo YYYY-MM-DD para comparar sin problemas de segundos
                    # Busca pesadas previas por patente y dia calendario
                    row_found = conn.execute("""
                        SELECT id FROM truck_scale_weighings 
                        WHERE (ticket_number IS NULL OR ticket_number = '' OR ticket_number = ?) 
                          AND truck_plate = ? 
                          AND (substr(weigh_date, 1, 10) = ? OR substr(exit_date, 1, 10) = ? OR substr(entry_date, 1, 10) = ?);
                    """, (ticket, chasis.upper(), t_day, t_day, t_day)).fetchone() # Busca coincidencia
                    if row_found: # Si encontro registro previo
                        existing_id = row_found['id'] if isinstance(row_found, dict) else row_found[0] # Asigna ID para actualizar
        except Exception: # Captura fallos de busqueda sin abortar proceso
            existing_id = None # Restablece identificador

        # Si el registro ya existia previamente
        if existing_id: # Pesada preexistente encontrada
            try: # Intento de actualizacion de datos
                with get_db_connection() as conn: # Abre conexion para update
                    # Actualiza pesada existente completando campos de ticket y metadatos faltantes
                    conn.execute("""
                        UPDATE truck_scale_weighings SET
                            ticket_number = COALESCE(NULLIF(?, ''), ticket_number),
                            weigh_date = COALESCE(NULLIF(?, ''), weigh_date),
                            operation_type = COALESCE(NULLIF(?, ''), operation_type),
                            product = COALESCE(NULLIF(?, ''), product),
                            truck_plate = COALESCE(NULLIF(?, ''), truck_plate),
                            trailer_plate = COALESCE(NULLIF(?, ''), trailer_plate),
                            transport_company = COALESCE(NULLIF(?, ''), transport_company),
                            driver_name = COALESCE(NULLIF(?, ''), driver_name),
                            driver_dni = COALESCE(NULLIF(?, ''), driver_dni),
                            gross_weight_kg = CASE WHEN ? > 0 THEN ? ELSE gross_weight_kg END,
                            tare_weight_kg = CASE WHEN ? > 0 THEN ? ELSE tare_weight_kg END,
                            net_weight_kg = CASE WHEN ? > 0 THEN ? ELSE net_weight_kg END,
                            net_weight_tons = CASE WHEN ? > 0 THEN ? ELSE net_weight_tons END,
                            origin = COALESCE(NULLIF(?, ''), origin),
                            destination = COALESCE(NULLIF(?, ''), destination),
                            seals_numbers = COALESCE(NULLIF(?, ''), seals_numbers),
                            notes = COALESCE(NULLIF(?, ''), notes),
                            exit_date = COALESCE(NULLIF(?, ''), exit_date),
                            entry_date = COALESCE(NULLIF(?, ''), entry_date),
                            client = COALESCE(NULLIF(?, ''), client),
                            recipient = COALESCE(NULLIF(?, ''), recipient),
                            origin_destination = COALESCE(NULLIF(?, ''), origin_destination),
                            user_id_code = COALESCE(NULLIF(?, ''), user_id_code),
                            exit_weight_kg = CASE WHEN ? > 0 THEN ? ELSE exit_weight_kg END,
                            entry_weight_kg = CASE WHEN ? > 0 THEN ? ELSE entry_weight_kg END,
                            exporter = COALESCE(NULLIF(?, ''), exporter),
                            manual_tare = COALESCE(NULLIF(?, ''), manual_tare),
                            driver_nationality = COALESCE(NULLIF(?, ''), driver_nationality),
                            packages = COALESCE(NULLIF(?, ''), packages),
                            customs = COALESCE(NULLIF(?, ''), customs),
                            lot = COALESCE(NULLIF(?, ''), lot),
                            single_weighing = COALESCE(NULLIF(?, ''), single_weighing),
                            customs_destination = COALESCE(NULLIF(?, ''), customs_destination)
                        WHERE id = ?;
                    """, (
                        ticket, fecha, op_type, prod_norm,
                        chasis.upper(), (acoplado or '').upper() if acoplado else None,
                        transporte, chofer, dni,
                        bruto, bruto,
                        tara, tara,
                        neto, neto,
                        round(neto / 1000.0, 3), round(neto / 1000.0, 3),
                        origen, destino, precintos, notas,
                        fecha_egreso, fecha_ingreso, cliente, destinatario, origen_destino,
                        str(id_usuario or '1'),
                        peso_egreso, peso_egreso,
                        peso_ingreso, peso_ingreso,
                        exportador, tara_manual, nacionalidad,
                        bultos, aduana, lot, pesada_unica, destinacion,
                        existing_id
                    )) # Ejecuta sentencia SQL
                    conn.commit() # Confirma cambios
                imported_count += 1 # Incrementa contador de registros procesados
            except Exception as e: # Captura fallo en actualizacion
                errors.append(f"Fila {r_idx} (Actualización #{existing_id}): {str(e)}") # Almacena detalle
                skipped_count += 1 # Incrementa omitidos
        else: # Si no existia previamente, realiza insercion normal
            try: # Intenta registrar la pesada en la base de datos
                record_weighing( # Invoca servicio de registro con todas las columnas estándar
                    ticket_number=ticket, # Número de ticket
                    weigh_date=fecha, # Fecha general de pesada
                    operation_type=op_type, # Tipo de operación (ingreso/egreso)
                    product=prod_norm, # Producto estandarizado
                    truck_plate=chasis, # Patente de chasis
                    trailer_plate=acoplado, # Patente de acoplado
                    transport_company=transporte, # Empresa transportista
                    driver_name=chofer, # Nombre de conductor
                    driver_dni=dni, # Documento de conductor
                    gross_weight_kg=bruto, # Peso bruto en kg
                    tare_weight_kg=tara, # Peso tara en kg
                    net_weight_kg=neto, # Peso neto en kg
                    origin=origen, # Origen de carga
                    destination=destino, # Destino de carga
                    seals_numbers=precintos, # Números de precinto
                    notes=notas, # Observaciones adicionales
                    operator_name=usuario or operator_name, # Nombre del operador
                    shift_id=shift_id, # Turno asignado
                    sync_inventory=sync_inventory, # Flag de sincronización con existencias
                    exit_date=fecha_egreso, # Fecha de egreso de balanza
                    entry_date=fecha_ingreso, # Fecha de ingreso de balanza
                    client=cliente, # Cliente
                    recipient=destinatario, # Destinatario
                    origin_destination=origen_destino, # Procedencia/Destino
                    user_id_code=id_usuario, # ID numérico del usuario de balanza
                    exit_weight_kg=peso_egreso, # Peso al egreso de balanza
                    entry_weight_kg=peso_ingreso, # Peso al ingreso de balanza
                    exporter=exportador, # Razón social del exportador
                    manual_tare=tara_manual, # Indicador de tara manual
                    driver_nationality=nacionalidad, # Nacionalidad del chofer
                    packages=bultos, # Cantidad de bultos
                    customs=aduana, # Nombre o código de aduana
                    lot=lot, # Número o código de LOT
                    single_weighing=pesada_unica, # Indicador de pesada única
                    customs_destination=destinacion # Destinación aduanera
                ) # Fin de llamada a record_weighing
                imported_count += 1 # Incrementa contador de pesadas importadas
            except Exception as e: # Captura excepción en procesamiento de fila
                errors.append(f"Fila {r_idx}: {str(e)}") # Almacena mensaje descriptivo de error
                skipped_count += 1 # Incrementa contador de omitidos

    record_audit_event('BALANZA', 'IMPORTACION_EXCEL', f"Importación de balanza: {imported_count} registros incorporados, {skipped_count} omitidos.") # Auditoría
    return { # Retorno estructurado de resultado
        'success': True, # Indicador de éxito
        'imported_count': imported_count, # Total importados
        'skipped_count': skipped_count, # Total omitidos
        'errors': errors # Detalle de errores
    } # Fin de retorno

# Exporta los registros a un archivo Excel (.xlsx) estructurado con las 27 columnas estándar
def export_weighings_to_excel(weighings=None, as_stream=False, order_by='ticket_asc'): # Función de exportación a Excel
    # Verifica la disponibilidad de la libreria openpyxl
    if openpyxl is None: # Si openpyxl no está instalado
        # Lanza excepcion descriptiva si no se encuentra instalada
        raise RuntimeError("La exportación a formato Excel requiere la librería openpyxl instalada.") # Error
    if weighings is None: # Si no se suministraron registros
        weighings = get_recent_weighings(limit=5000, order_by=order_by) # Consulta registros recientes con orden especificado
    wb = openpyxl.Workbook() # Crea nuevo libro Excel
    ws = wb.active # Obtiene hoja activa
    ws.title = "Pesadas de Balanza" # Establece título de pestaña

    # Estilos corporativos de BioBalcarce
    header_fill = PatternFill(start_color="0F172A", end_color="0F172A", fill_type="solid") # Fondo oscuro slate 900
    header_font = Font(name="Arial", size=10, bold=True, color="FFFFFF") # Fuente blanca en negrita
    data_font = Font(name="Arial", size=9) # Fuente regular para datos
    bold_font = Font(name="Arial", size=9, bold=True) # Fuente en negrita para totales y netos
    center_align = Alignment(horizontal="center", vertical="center") # Alineación centrada
    left_align = Alignment(horizontal="left", vertical="center") # Alineación a la izquierda
    right_align = Alignment(horizontal="right", vertical="center") # Alineación a la derecha
    thin_border = Border( # Borde fino para celdas
        left=Side(style='thin', color='E2E8F0'), # Borde izquierdo
        right=Side(style='thin', color='E2E8F0'), # Borde derecho
        top=Side(style='thin', color='E2E8F0'), # Borde superior
        bottom=Side(style='thin', color='E2E8F0') # Borde inferior
    ) # Fin de configuración de bordes

    # Encabezados con las 27 columnas estándar requeridas para báscula
    headers = [ # Lista ordenada de títulos de columnas
        "ID", # 1. ID de pesada
        "Fecha Egreso", # 2. Fecha y hora de egreso
        "Fecha Ingreso", # 3. Fecha y hora de ingreso
        "Producto", # 4. Tipo de producto / grano
        "Cliente", # 5. Nombre o razón social del cliente
        "Transportista", # 6. Empresa de transporte
        "Destinatario", # 7. Destinatario de la mercadería
        "Patente Chasis", # 8. Dominio del camión tractor
        "Patente Acoplado", # 9. Dominio del acoplado o semi
        "Procedencia/Destino", # 10. Localidad o planta origen/destino
        "Nombre Chofer", # 11. Nombre y apellido del transportista
        "Precintos", # 12. Identificación de precintos de seguridad
        "Observaciones", # 13. Notas y comentarios operativos
        "ID Usuario", # 14. Código identificador del usuario balancero
        "Peso Egreso", # 15. Peso registrado en salida en kg
        "Peso Ingreso", # 16. Peso registrado en entrada en kg
        "Peso Neto", # 17. Peso neto resultante en kg
        "Exportador", # 18. Razón social del exportador
        "Tara Manual", # 19. Indicador si la tara fue manual (SI/NO)
        "Nacionalidad Chofer", # 20. País de procedencia del chofer
        "Bultos", # 21. Número de bultos o contenedores
        "Aduana", # 22. Aduana interviniente
        "LOT", # 23. Código o número de lote
        "DNI Chofer", # 24. Documento nacional del conductor
        "Usuario", # 25. Nombre de usuario del operador
        "Pesada Unica", # 26. Indicador de pesada única (SI/NO)
        "Destinacion" # 27. Destinación aduanera
    ] # Fin de lista de encabezados

    ws.append(headers) # Agrega cabecera a la hoja
    for col_num in range(1, len(headers) + 1): # Estiliza cada encabezado
        cell = ws.cell(row=1, column=col_num) # Accede a celda de título
        cell.fill = header_fill # Aplica relleno corporativo
        cell.font = header_font # Aplica fuente de encabezado
        cell.alignment = center_align # Centra el texto del encabezado

    ws.row_dimensions[1].height = 26 # Altura generosa para la cabecera

    for r_idx, w in enumerate(weighings, start=2): # Recorre cada registro de pesada
        # Construye la fila de 27 columnas respetando la secuencia exacta
        row_data = [ # Inicio de lista de celdas por fila
            w.get('ticket_number') or w.get('id'), # 1. ID de pesada o ticket registrado
            w.get('exit_date') or (w.get('weigh_date') if w.get('operation_type') == 'egreso' else '-'), # 2. Fecha Egreso
            w.get('entry_date') or (w.get('weigh_date') if w.get('operation_type') == 'ingreso' else '-'), # 3. Fecha Ingreso
            (w.get('product') or '').capitalize(), # 4. Producto capitalizado
            w.get('client') or w.get('destination') or w.get('origin') or '-', # 5. Cliente
            w.get('transport_company') or '-', # 6. Transportista
            w.get('recipient') or w.get('destination') or '-', # 7. Destinatario
            w.get('truck_plate') or '-', # 8. Patente Chasis
            w.get('trailer_plate') or '-', # 9. Patente Acoplado
            w.get('origin_destination') or w.get('origin') or w.get('destination') or '-', # 10. Procedencia/Destino
            w.get('driver_name') or '-', # 11. Nombre Chofer
            w.get('seals_numbers') or '-', # 12. Precintos
            w.get('notes') or '-', # 13. Observaciones
            w.get('user_id_code') or '1', # 14. ID Usuario
            float(w.get('exit_weight_kg') or 0.0), # 15. Peso Egreso (kg)
            float(w.get('entry_weight_kg') or 0.0), # 16. Peso Ingreso (kg)
            float(w.get('net_weight_kg') or 0.0), # 17. Peso Neto (kg)
            w.get('exporter') or '-', # 18. Exportador
            w.get('manual_tare') or 'NO', # 19. Tara Manual
            w.get('driver_nationality') or 'Argentina', # 20. Nacionalidad Chofer
            w.get('packages') or '-', # 21. Bultos
            w.get('customs') or '-', # 22. Aduana
            w.get('lot') or '-', # 23. LOT
            w.get('driver_dni') or '-', # 24. DNI Chofer
            w.get('operator_name') or '-', # 25. Usuario operador
            w.get('single_weighing') or 'NO', # 26. Pesada Unica
            w.get('customs_destination') or '-' # 27. Destinacion
        ] # Fin de lista de datos
        ws.append(row_data) # Añade fila a la hoja de cálculo
        ws.row_dimensions[r_idx].height = 20 # Ajusta altura de fila

        for col_idx in range(1, len(row_data) + 1): # Aplica estilos celda por celda
            c = ws.cell(row=r_idx, column=col_idx) # Obtiene objeto celda
            c.font = data_font # Aplica fuente de datos
            c.border = thin_border # Aplica borde fino
            if col_idx in [15, 16, 17]: # Columnas numéricas de pesos en kg
                c.number_format = '#,##0' # Formato numérico entero con separador de miles
                c.alignment = right_align # Alineación a la derecha
                if col_idx == 17: # Peso neto destacado
                    c.font = bold_font # Aplica tipografía en negrita
            elif col_idx in [1, 2, 3, 8, 9, 14, 19, 20, 23, 24, 26]: # Columnas cortas o códigos
                c.alignment = center_align # Alineación centrada
            else: # Resto de columnas de texto
                c.alignment = left_align # Alineación a la izquierda

    # Autoajuste de anchos de columna
    for col in ws.columns: # Recorre columnas
        max_len = max(len(str(cell.value or '')) for cell in col) # Determina longitud máxima
        col_letter = openpyxl.utils.get_column_letter(col[0].column) # Convierte índice a letra
        ws.column_dimensions[col_letter].width = max(max_len + 3, 11) # Asigna ancho suficiente

    output = io.BytesIO() # Flujo en memoria de bytes
    wb.save(output) # Guarda libro en memoria
    output.seek(0) # Rebobina puntero
    if as_stream: # Si se pide como flujo
        return output # Retorna stream
    return output.getvalue() # Retorna bytes binarios

# Exporta los registros a formato CSV estructurado con las 27 columnas estándar
def export_weighings_to_csv(weighings=None, order_by='ticket_asc'): # Función de exportación CSV con soporte de orden
    if weighings is None: # Si no se suministraron registros
        weighings = get_recent_weighings(limit=5000, order_by=order_by) # Obtiene pesadas respetando el orden seleccionado
    output = io.StringIO() # Flujo de texto en memoria
    writer = csv.writer(output, delimiter=';') # Crea escritor CSV delimitado por punto y coma

    # Encabezados de las 27 columnas estándar para exportación CSV
    headers = [ # Lista de encabezados CSV
        "ID", # 1. ID
        "Fecha Egreso", # 2. Fecha Egreso
        "Fecha Ingreso", # 3. Fecha Ingreso
        "Producto", # 4. Producto
        "Cliente", # 5. Cliente
        "Transportista", # 6. Transportista
        "Destinatario", # 7. Destinatario
        "Patente Chasis", # 8. Patente Chasis
        "Patente Acoplado", # 9. Patente Acoplado
        "Procedencia/Destino", # 10. Procedencia/Destino
        "Nombre Chofer", # 11. Nombre Chofer
        "Precintos", # 12. Precintos
        "Observaciones", # 13. Observaciones
        "ID Usuario", # 14. ID Usuario
        "Peso Egreso", # 15. Peso Egreso
        "Peso Ingreso", # 16. Peso Ingreso
        "Peso Neto", # 17. Peso Neto
        "Exportador", # 18. Exportador
        "Tara Manual", # 19. Tara Manual
        "Nacionalidad Chofer", # 20. Nacionalidad Chofer
        "Bultos", # 21. Bultos
        "Aduana", # 22. Aduana
        "LOT", # 23. LOT
        "DNI Chofer", # 24. DNI Chofer
        "Usuario", # 25. Usuario
        "Pesada Unica", # 26. Pesada Unica
        "Destinacion" # 27. Destinacion
    ] # Fin de lista de cabeceras
    writer.writerow(headers) # Escribe fila de cabeceras en el stream CSV

    for w in weighings: # Itera sobre las pesadas
        writer.writerow([ # Escribe fila de datos con las 27 columnas
            w.get('ticket_number') or w.get('id'), # 1. ID de pesada o ticket registrado
            w.get('exit_date') or (w.get('weigh_date') if w.get('operation_type') == 'egreso' else ''), # 2. Fecha Egreso
            w.get('entry_date') or (w.get('weigh_date') if w.get('operation_type') == 'ingreso' else ''), # 3. Fecha Ingreso
            w.get('product') or '', # 4. Producto
            w.get('client') or w.get('destination') or w.get('origin') or '', # 5. Cliente
            w.get('transport_company') or '', # 6. Transportista
            w.get('recipient') or w.get('destination') or '', # 7. Destinatario
            w.get('truck_plate') or '', # 8. Patente Chasis
            w.get('trailer_plate') or '', # 9. Patente Acoplado
            w.get('origin_destination') or w.get('origin') or w.get('destination') or '', # 10. Procedencia/Destino
            w.get('driver_name') or '', # 11. Nombre Chofer
            w.get('seals_numbers') or '', # 12. Precintos
            w.get('notes') or '', # 13. Observaciones
            w.get('user_id_code') or '1', # 14. ID Usuario
            w.get('exit_weight_kg') or 0.0, # 15. Peso Egreso
            w.get('entry_weight_kg') or 0.0, # 16. Peso Ingreso
            w.get('net_weight_kg') or 0.0, # 17. Peso Neto
            w.get('exporter') or '', # 18. Exportador
            w.get('manual_tare') or 'NO', # 19. Tara Manual
            w.get('driver_nationality') or 'Argentina', # 20. Nacionalidad Chofer
            w.get('packages') or '', # 21. Bultos
            w.get('customs') or '', # 22. Aduana
            w.get('lot') or '', # 23. LOT
            w.get('driver_dni') or '', # 24. DNI Chofer
            w.get('operator_name') or '', # 25. Usuario
            w.get('single_weighing') or 'NO', # 26. Pesada Unica
            w.get('customs_destination') or '' # 27. Destinacion
        ]) # Fin de fila de pesada

    output.seek(0) # Rebobina puntero del stream
    return output.getvalue() # Retorna texto CSV generado

# Elimina una pesada (solo admin)
def delete_weighing(weighing_id, admin_user='admin_sistema'):
    with get_db_connection() as conn:
        row = conn.execute("SELECT * FROM truck_scale_weighings WHERE id = ?;", (weighing_id,)).fetchone()
        if not row:
            raise ValueError(f"Pesada con ID {weighing_id} no encontrada.")
        conn.execute("DELETE FROM truck_scale_weighings WHERE id = ?;", (weighing_id,))
        conn.commit()
    record_audit_event('BALANZA', 'ELIMINACION_PESADA', f"Pesada ID {weighing_id} (Ticket: {row['ticket_number']}, Camión: {row['truck_plate']}) eliminada por {admin_user}.")
    return True
