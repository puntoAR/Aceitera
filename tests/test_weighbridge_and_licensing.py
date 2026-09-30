# Suite de pruebas automatizadas para el modulo de Balanza de Camiones,
# Sistema de Licenciamiento Programable y Notificaciones del Actualizador
import os
import sys
import io
import unittest
import openpyxl
from datetime import datetime, date, timedelta

# Asegura el directorio raiz en el path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from run import app
from core.database import init_db, get_db_connection
from modules.weighbridge.service import (
    record_weighing, get_recent_weighings, get_weighing_summary_stats,
    import_weighings_from_file, export_weighings_to_excel, export_weighings_to_csv,
    delete_weighing
)
from core.licensing import (
    get_licensing_status, update_licensing_config, check_feature_permission, generate_license_token
)
from modules.updater.service import (
    get_pending_local_update, check_system_update_status
)
from config import PENDING_UPDATES_DIR

class TestWeighbridgeAndLicensing(unittest.TestCase):

    def setUp(self):
        app.config['TESTING'] = True
        app.config['WTF_CSRF_ENABLED'] = False
        self.client = app.test_client()
        init_db()

        # Limpia tablas de prueba
        with get_db_connection() as conn:
            conn.execute("DELETE FROM truck_scale_weighings;")
            # Restablece la configuracion de licencia a su estado inicial por defecto
            conn.execute("""
                UPDATE system_licensing_config
                SET client_name = 'BioBalcarce S.A.',
                    license_mode = 'libre_uso',
                    license_key = 'PTAR-TEST-2026',
                    expiration_date = '2027-09-01',
                    is_active = 1,
                    max_users = 50,
                    block_dashboard = 0,
                    block_data_entry = 0,
                    block_reports = 0,
                    block_updates = 0,
                    status_notes = 'Test Setup'
                WHERE id = 1;
            """)
            conn.commit()

    # -------------------------------------------------------------------------
    # 1. PRUEBAS DE BALANZA DE CAMIONES (SERVICIO Y RUTAS)
    # -------------------------------------------------------------------------
    def test_record_weighing_and_stats(self):
        """Verifica el alta manual de pesada, calculo automatico de neto y metricas resumen"""
        w_id = record_weighing(
            ticket_number="TK-1001",
            truck_plate="AB123CD",
            trailer_plate="AC456EF",
            driver_name="Juan Perez",
            driver_dni="28444555",
            transport_company="TransGirasol",
            operation_type="ingreso",
            product="semilla",
            gross_weight_kg=42500,
            tare_weight_kg=14500,
            origin_name="Necochea",
            destination_name="Planta Balcarce",
            operator_name="Operario Balanza"
        )
        self.assertIsNotNone(w_id)

        # Consulta pesadas
        weighings = get_recent_weighings(limit=10)
        self.assertEqual(len(weighings), 1)
        w = weighings[0]
        self.assertEqual(w['ticket_number'], "TK-1001")
        self.assertEqual(w['net_weight_kg'], 28000.0) # 42500 - 14500
        self.assertEqual(w['net_weight_tons'], 28.0)

        # Estadisticas
        stats = get_weighing_summary_stats()
        self.assertEqual(stats['total_trucks'], 1)
        self.assertEqual(stats['seed_in_tons'], 28.0)
        self.assertEqual(stats['oil_out_tons'], 0.0)
        self.assertEqual(stats['expeller_out_tons'], 0.0)

    def test_delete_weighing(self):
        """Verifica la eliminacion de un registro de pesada"""
        w_id = record_weighing(
            ticket_number="TK-TO-DEL",
            truck_plate="DEL999",
            operation_type="egreso",
            product="aceite",
            gross_weight_kg=30000,
            tare_weight_kg=10000
        )
        self.assertEqual(len(get_recent_weighings()), 1)
        delete_weighing(w_id)
        self.assertEqual(len(get_recent_weighings()), 0)

    def test_date_range_filtering_with_various_formats(self): # Prueba de filtrado por rango de fechas con multiples formatos
        """Verifica que el filtrado por rango de fechas reconozca formatos ISO y DD/MM/YYYY sin omitir pesadas""" # Docstring
        record_weighing( # Registra pesada en formato ISO con hora
            ticket_number="TK-SEP-01", # Numero de ticket
            weigh_date="2026-09-05 10:00:00", # Fecha ISO
            operation_type="ingreso", # Operacion ingreso
            product="semilla", # Producto semilla
            gross_weight_kg=45000, # Bruto
            tare_weight_kg=15000 # Tara
        ) # Cierra llamada
        record_weighing( # Registra pesada con fecha formato latino DD/MM/YYYY con hora
            ticket_number="TK-SEP-02", # Numero de ticket
            weigh_date="25/09/2026 14:30", # Fecha latina con minutos
            operation_type="egreso", # Operacion egreso
            product="expeller", # Producto expeller
            gross_weight_kg=35000, # Bruto
            tare_weight_kg=15000 # Tara
        ) # Cierra llamada
        record_weighing( # Registra pesada con fecha formato latino DD/MM/YYYY sin hora
            ticket_number="TK-SEP-03", # Numero de ticket
            weigh_date="30/09/2026", # Fecha latina de fin de mes
            operation_type="egreso", # Operacion egreso
            product="aceite", # Producto aceite
            gross_weight_kg=32000, # Bruto
            tare_weight_kg=17000 # Tara
        ) # Cierra llamada
        record_weighing( # Registra pesada en mes anterior (agosto)
            ticket_number="TK-AGO-01", # Numero de ticket
            weigh_date="2026-08-31 23:59:59", # Fecha agosto fuera de rango
            operation_type="ingreso", # Operacion ingreso
            product="semilla", # Producto semilla
            gross_weight_kg=40000, # Bruto
            tare_weight_kg=15000 # Tara
        ) # Cierra llamada
        record_weighing( # Registra pesada en mes posterior (octubre)
            ticket_number="TK-OCT-01", # Numero de ticket
            weigh_date="2026-10-01 00:00:01", # Fecha octubre fuera de rango
            operation_type="egreso", # Operacion egreso
            product="expeller", # Producto expeller
            gross_weight_kg=30000, # Bruto
            tare_weight_kg=10000 # Tara
        ) # Cierra llamada

        # Filtra por el mes completo de septiembre 2026
        weighings = get_recent_weighings(start_date="2026-09-01", end_date="2026-09-30") # Consulta pesadas del rango
        # Verifica que solo se hayan recuperado exactamente las 3 pesadas de septiembre
        self.assertEqual(len(weighings), 3) # Comprueba cantidad esperada
        # Obtiene lista de tickets encontrados
        tickets = [w['ticket_number'] for w in weighings] # Lista de comprobantes
        # Valida que los tres tickets de septiembre esten incluidos
        self.assertIn("TK-SEP-01", tickets) # Valida ticket 1
        self.assertIn("TK-SEP-02", tickets) # Valida ticket 2 (formato latino DD/MM/YYYY)
        self.assertIn("TK-SEP-03", tickets) # Valida ticket 3 (formato latino fin de mes)
        # Valida que los tickets fuera de rango hayan sido excluidos
        self.assertNotIn("TK-AGO-01", tickets) # Excluye agosto
        self.assertNotIn("TK-OCT-01", tickets) # Excluye octubre

    def test_kpi_summary_stats_synchronized_with_filters(self): # Prueba de sincronizacion de metricas KPI con filtros
        """Verifica que los indicadores superiores reflejen exactamente los datos filtrados por fecha, producto y busqueda""" # Docstring
        record_weighing( # Registra pesada de semilla en septiembre
            ticket_number="KPI-01", # Ticket
            weigh_date="2026-09-10 10:00:00", # Fecha septiembre
            truck_plate="ABC111", # Patente
            operation_type="ingreso", # Ingreso
            product="semilla", # Semilla
            gross_weight_kg=45000, # 45 Tn bruto
            tare_weight_kg=15000 # 15 Tn tara -> 30 Tn neto
        ) # Cierra llamada
        record_weighing( # Registra pesada de expeller en septiembre
            ticket_number="KPI-02", # Ticket
            weigh_date="2026-09-20 12:00:00", # Fecha septiembre
            truck_plate="DEF222", # Patente
            operation_type="egreso", # Egreso
            product="expeller", # Expeller
            gross_weight_kg=35000, # 35 Tn bruto
            tare_weight_kg=15000 # 15 Tn tara -> 20 Tn neto
        ) # Cierra llamada
        record_weighing( # Registra pesada de aceite en septiembre
            ticket_number="KPI-03", # Ticket
            weigh_date="2026-09-28 16:00:00", # Fecha septiembre
            truck_plate="GHI333", # Patente
            operation_type="egreso", # Egreso
            product="aceite", # Aceite
            gross_weight_kg=30000, # 30 Tn bruto
            tare_weight_kg=15000 # 15 Tn tara -> 15 Tn neto
        ) # Cierra llamada
        record_weighing( # Registra pesada en agosto (fuera del filtro)
            ticket_number="KPI-04", # Ticket
            weigh_date="2026-08-15 10:00:00", # Fecha agosto
            truck_plate="JKL444", # Patente
            operation_type="ingreso", # Ingreso
            product="semilla", # Semilla
            gross_weight_kg=50000, # 50 Tn bruto
            tare_weight_kg=10000 # 10 Tn tara -> 40 Tn neto
        ) # Cierra llamada

        # 1. Metricas filtradas por rango de fechas de septiembre
        stats_sep = get_weighing_summary_stats(start_date="2026-09-01", end_date="2026-09-30") # Consulta KPIs periodo
        self.assertEqual(stats_sep['total_trucks'], 3) # 3 pesadas en septiembre
        self.assertEqual(stats_sep['semilla_ingreso_tons'], 30.0) # 30 Tn semilla
        self.assertEqual(stats_sep['expeller_egreso_tons'], 20.0) # 20 Tn expeller
        self.assertEqual(stats_sep['aceite_egreso_tons'], 15.0) # 15 Tn aceite

        # 2. Metricas filtradas por producto 'aceite' en septiembre
        stats_oil = get_weighing_summary_stats(product="aceite", start_date="2026-09-01", end_date="2026-09-30") # KPIs aceite
        self.assertEqual(stats_oil['total_trucks'], 1) # Solo 1 camion de aceite
        self.assertEqual(stats_oil['aceite_egreso_tons'], 15.0) # 15 Tn de aceite
        self.assertEqual(stats_oil['semilla_ingreso_tons'], 0.0) # Cero de otros productos

        # 3. Metricas filtradas por termino de busqueda de patente
        stats_search = get_weighing_summary_stats(search="DEF222") # Busqueda especifica
        self.assertEqual(stats_search['total_trucks'], 1) # 1 pesada coincidente
        self.assertEqual(stats_search['expeller_egreso_tons'], 20.0) # 20 Tn correspondientes

    def test_migration_17_normalize_dates(self): # Prueba de migracion 17
        """Verifica que la migracion 17 normalice fechas historicas con formato DD/MM/YYYY""" # Docstring
        from core.migrations import backfill_normalize_weighbridge_dates # Importa callback de migracion
        with get_db_connection() as conn: # Abre conexion de prueba
            # Inserta registro con fecha estilo latino DD/MM/YYYY y columnas obligatorias
            conn.execute("""
                INSERT INTO truck_scale_weighings (ticket_number, weigh_date, entry_date, exit_date, operation_type, product)
                VALUES ('MIG17-01', '24/09/2026 11:00', '24/09/2026', '24/09/2026 11:30', 'ingreso', 'semilla');
            """) # Insercion protegida con operacion y producto
            # Ejecuta la normalizacion de fechas
            backfill_normalize_weighbridge_dates(conn) # Aplica normalizacion
            # Consulta la fila actualizada
            row = conn.execute("SELECT weigh_date, entry_date, exit_date FROM truck_scale_weighings WHERE ticket_number = 'MIG17-01';").fetchone() # Consulta
            # Comprueba formato ISO normalizado
            self.assertEqual(row['weigh_date'], '2026-09-24 11:00:00') # Valida weigh_date normalizada
            self.assertEqual(row['entry_date'], '2026-09-24 00:00:00') # Valida entry_date normalizada
            self.assertEqual(row['exit_date'], '2026-09-24 11:30:00') # Valida exit_date normalizada

    def test_export_weighings_excel_and_csv(self): # Prueba de exportación a Excel y CSV
        """Verifica la exportación de pesadas con las 27 columnas estándar de balanza""" # Docstring
        record_weighing( # Registra pesada de prueba con datos estándar
            ticket_number="TK-EXP-1", # Número de ticket
            truck_plate="EXP111", # Patente chasis
            trailer_plate="TRA999", # Patente acoplado
            operation_type="ingreso", # Sentido de la pesada
            product="semilla", # Tipo de producto
            gross_weight_kg=40000, # Peso bruto
            tare_weight_kg=15000, # Tara
            client="Cliente Agro SA", # Cliente
            recipient="Planta Balcarce", # Destinatario
            origin_destination="Necochea", # Procedencia/Destino
            exporter="BioBalcarce Export", # Exportador
            customs="Aduana Mar del Plata", # Aduana
            lot="LOT-01-2026" # Lote
        ) # Cierra llamada
        # Exporta a Excel
        excel_bytes = export_weighings_to_excel() # Genera binario Excel
        self.assertIsInstance(excel_bytes, bytes) # Comprueba que sea tipo bytes
        self.assertTrue(len(excel_bytes) > 1000) # Comprueba tamaño mínimo de archivo

        # Valida que sea un XLSX válido y que posea exactamente las 27 columnas
        wb = openpyxl.load_workbook(io.BytesIO(excel_bytes)) # Carga libro desde stream de memoria
        sheet = wb.active # Obtiene hoja activa
        self.assertIn("Pesadas de Balanza", sheet.title) # Valida título de la hoja
        headers = [cell.value for cell in sheet[1]] # Extrae lista de encabezados de la fila 1
        expected_27 = [ # Lista de las 27 columnas estándar requeridas
            "ID", "Fecha Egreso", "Fecha Ingreso", "Producto", "Cliente", # Columnas 1 a 5
            "Transportista", "Destinatario", "Patente Chasis", "Patente Acoplado", # Columnas 6 a 9
            "Procedencia/Destino", "Nombre Chofer", "Precintos", "Observaciones", # Columnas 10 a 13
            "ID Usuario", "Peso Egreso", "Peso Ingreso", "Peso Neto", # Columnas 14 a 17
            "Exportador", "Tara Manual", "Nacionalidad Chofer", "Bultos", # Columnas 18 a 21
            "Aduana", "LOT", "DNI Chofer", "Usuario", "Pesada Unica", "Destinacion" # Columnas 22 a 27
        ] # Fin lista esperada
        self.assertEqual(headers, expected_27) # Verifica coincidencia exacta de columnas
        wb.close() # Cierra libro Excel

        # Exporta a CSV y comprueba cabeceras y contenido
        csv_bytes = export_weighings_to_csv() # Genera texto delimitado CSV
        self.assertIn("Patente Chasis;Patente Acoplado", csv_bytes) # Verifica cabeceras estándar
        self.assertIn("TK-EXP-1", csv_bytes) # Verifica existencia del registro
        self.assertIn("EXP111", csv_bytes) # Verifica patente del camión

    def test_import_weighings_from_27_columns_standard(self): # Prueba de importación de las 27 columnas estándar
        """Verifica la importación con la cabecera exacta de 27 columnas de balanza industrial""" # Docstring
        header_line = "ID\tFecha Egreso\tFecha Ingreso\tProducto\tCliente\tTransportista\tDestinatario\tPatente Chasis\tPatente Acoplado\tProcedencia/Destino\tNombre Chofer\tPrecintos\tObservaciones\tID Usuario\tPeso Egreso\tPeso Ingreso\tPeso Neto\tExportador\tTara Manual\tNacionalidad Chofer\tBultos\tAduana\tLOT\tDNI Chofer\tUsuario\tPesada Unica\tDestinacion\n" # Cabecera tabulada
        row_line = "901\t2026-09-30 15:00\t2026-09-30 14:15\tSemilla\tAcopio del Sur\tTransBalcarce\tBioBalcarce\tAB987CD\tEF654GH\tNecochea\tJuan Lopez\tP-901\tGrano seco\t1\t14200\t44200\t30000\tBioBalcarce SA\tNO\tArgentina\tGranel\tBalcarce\tL-2026\t30111222\toperador1\tNO\tConsumo\n" # Renglón tabulado
        tsv_content = (header_line + row_line).encode('utf-8') # Concatena y codifica en bytes
        result = import_weighings_from_file(tsv_content, "balanza_estandar.csv", sync_inventory=False) # Importa archivo
        self.assertTrue(result['success']) # Verifica éxito de importación
        self.assertEqual(result['imported_count'], 1) # Comprueba 1 fila incorporada
        weighings = get_recent_weighings() # Consulta pesadas registradas
        w = weighings[0] # Obtiene primer registro
        self.assertEqual(w['truck_plate'], "AB987CD") # Comprueba patente chasis
        self.assertEqual(w['trailer_plate'], "EF654GH") # Comprueba patente acoplado
        self.assertEqual(w['client'], "Acopio del Sur") # Comprueba cliente
        self.assertEqual(w['recipient'], "BioBalcarce") # Comprueba destinatario
        self.assertEqual(w['origin_destination'], "Necochea") # Comprueba procedencia destino
        self.assertEqual(w['entry_weight_kg'], 44200.0) # Comprueba peso ingreso
        self.assertEqual(w['exit_weight_kg'], 14200.0) # Comprueba peso egreso
        self.assertEqual(w['net_weight_kg'], 30000.0) # Comprueba peso neto
        self.assertEqual(w['exporter'], "BioBalcarce SA") # Comprueba exportador
        self.assertEqual(w['driver_nationality'], "Argentina") # Comprueba nacionalidad
        self.assertEqual(w['customs'], "Balcarce") # Comprueba aduana
        self.assertEqual(w['lot'], "L-2026") # Comprueba lote

    def test_import_weighings_from_csv(self):
        """Verifica la importacion flexible desde un archivo CSV con columnas estandar"""
        csv_content = (
            "Ticket;Fecha;Patente;Acoplado;Chofer;Operacion;Producto;Bruto;Tara;Neto;Origen;Destino\n"
            "TK-5501;2026-09-27 10:00:00;AF123ZZ;AC999AA;Carlos Lopez;Ingreso;Semilla Girasol;45000;15000;30000;Loberia;Planta\n"
            "TK-5502;2026-09-27 11:30:00;AE456YY;;Roberto Gomez;Egreso;Aceite;35000;12000;23000;Planta;Puerto Quequen\n"
        ).encode('utf-8')

        result = import_weighings_from_file(csv_content, "balanza_pesadas.csv", sync_inventory=False)
        self.assertTrue(result['success'])
        self.assertEqual(result['imported_count'], 2)

        weighings = get_recent_weighings()
        self.assertEqual(len(weighings), 2)
        plates = [w['truck_plate'] for w in weighings]
        self.assertIn("AF123ZZ", plates)
        self.assertIn("AE456YY", plates)

    def test_import_weighings_from_excel(self):
        """Verifica la importacion desde un archivo Excel binario (.xlsx) con conversion automatica de toneladas a kg"""
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Pesadas"
        # Cabeceras
        ws.append(["Nro Ticket", "Fecha", "Camion", "Chofer", "Movimiento", "Material", "Peso Bruto", "Tara", "Neto Tn"])
        # Fila 1 en toneladas
        ws.append(["TK-EX-99", "2026-09-27 14:00", "EX777TT", "Mario Balza", "Egreso", "Expeller", 38.5, 13.5, 25.0])
        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)
        wb.close()

        result = import_weighings_from_file(buf.read(), "pesadas_reales.xlsx", sync_inventory=False)
        self.assertTrue(result['success'])
        self.assertEqual(result['imported_count'], 1)

        weighings = get_recent_weighings()
        self.assertEqual(len(weighings), 1)
        w = weighings[0]
        self.assertEqual(w['ticket_number'], "TK-EX-99")
        # 25 Tn deben convertirse a 25000 kg
        self.assertEqual(w['net_weight_kg'], 25000.0)
        self.assertEqual(w['net_weight_tons'], 25.0)

    # Prueba de importacion desde archivo .xls que contiene una tabla HTML tipica de balanzas industriales
    def test_import_weighings_from_xls_html_table(self):
        # Contenido HTML de la tabla con etiquetas tr y td
        html_content = (
            "<html><body><table>"
            "<tr><th>Nro Ticket</th><th>Fecha</th><th>Camion</th><th>Chofer</th><th>Movimiento</th><th>Material</th><th>Peso Bruto</th><th>Tara</th><th>Neto Tn</th></tr>"
            "<tr><td>TK-XLS-01</td><td>2026-09-30 10:00</td><td>AA111BB</td><td>Juan Perez</td><td>Ingreso</td><td>Semilla</td><td>40.0</td><td>10.0</td><td>30.0</td></tr>"
            "</table></body></html>"
        ).encode('utf-8')
        # Importa el archivo con extension .xls
        result = import_weighings_from_file(html_content, "ticket_balanza.xls", sync_inventory=False)
        # Verifica que la operacion se haya completado con exito
        self.assertTrue(result['success'])
        # Verifica que se haya importado exactamente 1 pesada
        self.assertEqual(result['imported_count'], 1)
        # Consulta las pesadas en la base de datos
        weighings = get_recent_weighings()
        # Obtiene el primer registro
        w = weighings[0]
        # Verifica el numero de ticket
        self.assertEqual(w['ticket_number'], "TK-XLS-01")
        # Verifica la conversion de 30 toneladas a 30000 kg
        self.assertEqual(w['net_weight_kg'], 30000.0)

    # Prueba de importacion desde archivo .xls en formato SpreadsheetML XML
    def test_import_weighings_from_xls_xml_spreadsheet(self):
        # Contenido XML con estructura Workbook y Table
        xml_content = (
            "<?xml version=\"1.0\"?>\n"
            "<Workbook xmlns=\"urn:schemas-microsoft-com:office:spreadsheet\">\n"
            "  <Worksheet ss:Name=\"Balanza\">\n"
            "    <Table>\n"
            "      <Row>\n"
            "        <Cell><Data ss:Type=\"String\">Ticket</Data></Cell>\n"
            "        <Cell><Data ss:Type=\"String\">Fecha</Data></Cell>\n"
            "        <Cell><Data ss:Type=\"String\">Patente</Data></Cell>\n"
            "        <Cell><Data ss:Type=\"String\">Operacion</Data></Cell>\n"
            "        <Cell><Data ss:Type=\"String\">Producto</Data></Cell>\n"
            "        <Cell><Data ss:Type=\"String\">Neto</Data></Cell>\n"
            "      </Row>\n"
            "      <Row>\n"
            "        <Cell><Data ss:Type=\"String\">TK-XML-88</Data></Cell>\n"
            "        <Cell><Data ss:Type=\"String\">2026-09-30 11:30</Data></Cell>\n"
            "        <Cell><Data ss:Type=\"String\">BB222CC</Data></Cell>\n"
            "        <Cell><Data ss:Type=\"String\">Egreso</Data></Cell>\n"
            "        <Cell><Data ss:Type=\"String\">Aceite</Data></Cell>\n"
            "        <Cell><Data ss:Type=\"Number\">28000</Data></Cell>\n"
            "      </Row>\n"
            "    </Table>\n"
            "  </Worksheet>\n"
            "</Workbook>"
        ).encode('utf-8')
        # Importa el archivo con extension .xls
        result = import_weighings_from_file(xml_content, "export_balanza.xls", sync_inventory=False)
        # Verifica exito en la importacion
        self.assertTrue(result['success'])
        # Verifica que se registro 1 pesada
        self.assertEqual(result['imported_count'], 1)
        # Consulta pesadas registradas
        weighings = get_recent_weighings()
        # Obtiene la pesada
        w = weighings[0]
        # Verifica ticket
        self.assertEqual(w['ticket_number'], "TK-XML-88")
        # Verifica peso neto en kg
        self.assertEqual(w['net_weight_kg'], 28000.0)

    # Prueba de importacion de un archivo delimitado por punto y coma guardado con extension .xls
    def test_import_weighings_from_xls_csv_renamed(self):
        # Contenido CSV con punto y coma
        csv_xls_content = (
            "Ticket;Fecha;Camion;Operacion;Producto;Bruto;Tara;Neto\n"
            "TK-CSV-55;2026-09-30;CC333DD;Ingreso;Semilla;45000;15000;30000\n"
        ).encode('utf-8')
        # Importa con extension .xls
        result = import_weighings_from_file(csv_xls_content, "datos_balanza.xls", sync_inventory=False)
        # Verifica exito
        self.assertTrue(result['success'])
        # Verifica cantidad de pesadas importadas
        self.assertEqual(result['imported_count'], 1)

    # Prueba de resiliencia ante archivos no validos garantizando que no se lance BadZipFile
    def test_import_weighings_badzipfile_resilience(self):
        # Bytes de prueba no validos
        dummy_content = b"XYZ123456789NOTVALID"
        # Verifica que se lance ValueError descriptivo en lugar de BadZipFile
        with self.assertRaises(ValueError) as ctx:
            # Invoca importacion con archivo no valido
            import_weighings_from_file(dummy_content, "corrupt.xls")
        # Comprueba que el mensaje informe sobre los formatos admitidos
        self.assertIn("No fue posible interpretar el archivo", str(ctx.exception))

    def test_weighbridge_web_views_and_roles(self):
        """Verifica acceso web y permisos de balanza: exclusivo gerencia y admin_sistema (bloqueado para operarios)"""
        # 1. Operario (usuario comun): NO tiene acceso ni visualizacion de Balanza
        self.client.get('/logout')
        self.client.post('/login', data={'username': 'operario', 'pin': '1111'})

        # En su pantalla de produccion, el menu NO debe mostrar el enlace a Balanza
        r_prod = self.client.get('/production/')
        self.assertEqual(r_prod.status_code, 200)
        self.assertNotIn(b'Balanza', r_prod.data)

        # Si intenta ingresar directamente por URL a /weighbridge/, debe ser rechazado
        r_user = self.client.get('/weighbridge/', follow_redirects=True)
        self.assertIn(b'No posee permisos autorizados', r_user.data)

        # 2. Gerente: SI tiene acceso y puede ver el enlace y la pantalla
        self.client.get('/logout')
        self.client.post('/login', data={'username': 'gerente', 'pin': '3333'})
        r_mgr_dash = self.client.get('/')
        self.assertIn(b'Balanza', r_mgr_dash.data)

        r_mgr = self.client.get('/weighbridge/')
        self.assertEqual(r_mgr.status_code, 200)
        self.assertIn(b'Balanza de Camiones', r_mgr.data)
        # Gerente puede exportar a excel
        r_exp = self.client.get('/weighbridge/export/excel')
        self.assertEqual(r_exp.status_code, 200)
        self.assertEqual(r_exp.content_type, 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

        # 3. Admin Sistema: SI tiene acceso completo y visualizacion en menu
        self.client.get('/logout')
        self.client.post('/login', data={'username': 'admin', 'pin': '1234'})
        r_adm_dash = self.client.get('/')
        self.assertIn(b'Balanza', r_adm_dash.data)

        r_admin = self.client.get('/weighbridge/')
        self.assertEqual(r_admin.status_code, 200)
        self.assertIn(b'Importar Planilla de Balanza', r_admin.data)

    def test_weighbridge_http_get_with_date_range_filter(self): # Prueba de peticion HTTP con filtro de fechas de balanza
        """Verifica que la ruta HTTP /weighbridge/ filtre correctamente por rango de fechas y actualice los KPIs en pantalla""" # Docstring
        # Inicia sesion con rol administrativo
        self.client.get('/logout') # Cierra sesion
        self.client.post('/login', data={'username': 'admin', 'pin': '1234'}) # Autentica como admin

        # Registra pesada dentro de septiembre 2026
        record_weighing( # Registra pesada
            ticket_number="T-WEB-SEP", # Ticket
            weigh_date="26/09/2026 10:00", # Fecha septiembre estilo DD/MM/YYYY
            truck_plate="WEB123", # Patente
            operation_type="ingreso", # Ingreso
            product="semilla", # Semilla
            gross_weight_kg=45000, # 45 Tn bruto
            tare_weight_kg=15000 # 15 Tn tara -> 30 Tn neto
        ) # Cierra llamada

        # Registra pesada en agosto 2026 (fuera de rango)
        record_weighing( # Registra pesada agosto
            ticket_number="T-WEB-AGO", # Ticket
            weigh_date="2026-08-10 10:00:00", # Fecha agosto
            truck_plate="OLD999", # Patente
            operation_type="ingreso", # Ingreso
            product="semilla", # Semilla
            gross_weight_kg=40000, # 40 Tn bruto
            tare_weight_kg=15000 # 15 Tn tara -> 25 Tn neto
        ) # Cierra llamada

        # Realiza peticion GET con la URL exacta enviada por el usuario
        url = '/weighbridge/?search=&operation_type=todos&product=todos&start_date=2026-09-01&end_date=2026-09-30' # URL de consulta
        res = self.client.get(url) # Ejecuta GET
        self.assertEqual(res.status_code, 200) # Comprueba codigo 200 OK
        # Comprueba que el ticket de septiembre este presente en el HTML
        self.assertIn(b'T-WEB-SEP', res.data) # Valida inclusion de ticket septiembre
        self.assertIn(b'WEB123', res.data) # Valida inclusion de patente septiembre
        # Comprueba que la pesada de agosto fuera de rango NO aparezca en la tabla
        self.assertNotIn(b'T-WEB-AGO', res.data) # Valida exclusion de ticket agosto
        self.assertNotIn(b'OLD999', res.data) # Valida exclusion de patente agosto
        # Comprueba que el contador de pesadas refleje 1 pesada filtrada
        self.assertIn(b'1 pesadas filtradas', res.data) # Valida subtitulo de pesadas filtradas
        # Comprueba que el KPI de semilla de septiembre refleje 30.0 Tn
        self.assertIn(b'30.0', res.data) # Valida KPI reactivo a los filtros

    # -------------------------------------------------------------------------
    # 2. PRUEBAS DE LICENCIAMIENTO PROGRAMABLE (SERVICIO Y RESTRICCIONES)
    # -------------------------------------------------------------------------
    def test_licensing_status_and_defaults(self):
        """Verifica estado por defecto y calculos de fecha de la licencia"""
        status = get_licensing_status()
        self.assertEqual(status['client_name'], 'BioBalcarce S.A.')
        self.assertEqual(status['license_mode'], 'libre_uso')
        self.assertTrue(status['is_active'])
        self.assertFalse(status['is_restricted'])

    def test_licensing_trial_mode_and_countdown(self):
        """Verifica el modo trial con calculo de dias restantes y expiracion controlada"""
        # Configura trial con 45 dias futuros
        future_date = (date.today() + timedelta(days=45)).isoformat()
        update_licensing_config(
            client_name="BioBalcarce S.A.",
            license_mode="trial",
            expiration_date=future_date,
            is_active=1
        )
        status = get_licensing_status()
        self.assertEqual(status['license_mode'], 'trial')
        self.assertFalse(status['is_expired'])
        self.assertFalse(status['is_restricted'])
        self.assertEqual(status['days_remaining'], 45)

        # Ahora simula trial vencido hace 5 dias con restricciones activas
        past_date = (date.today() - timedelta(days=5)).isoformat()
        update_licensing_config(
            client_name="BioBalcarce S.A.",
            license_mode="trial",
            expiration_date=past_date,
            block_data_entry=1,
            block_dashboard=1,
            block_reports=1,
            block_updates=1,
            is_active=1
        )
        expired_status = get_licensing_status()
        self.assertTrue(expired_status['is_expired'])
        self.assertTrue(expired_status['is_restricted'])
        self.assertTrue(expired_status['restrictions']['block_data_entry'])
        self.assertTrue(expired_status['restrictions']['block_dashboard'])
        self.assertTrue(expired_status['restrictions']['block_reports'])
        self.assertTrue(expired_status['restrictions']['block_updates'])

    def test_graceful_licensing_feature_gating_in_web(self):
        """Verifica que las restricciones de licencia funcionen de manera elegante y sin errores 500"""
        # Configura bloqueo de carga de datos y de reportes
        past_date = (date.today() - timedelta(days=10)).isoformat()
        update_licensing_config(
            client_name="BioBalcarce S.A.",
            license_mode="trial",
            expiration_date=past_date,
            block_data_entry=1,
            block_reports=1,
            is_active=1
        )

        # Login como gerente (rol autorizado a balanza, pero restringido por licencia)
        self.client.get('/logout')
        self.client.post('/login', data={'username': 'gerente', 'pin': '3333'})

        # Intenta registrar una pesada por POST (debe rebotar amablemente sin 500)
        resp_post = self.client.post('/weighbridge/add', data={
            'ticket_number': 'BLOCKED-1',
            'truck_plate': 'NO999NO',
            'operation_type': 'ingreso',
            'product': 'semilla',
            'gross_weight_kg': 40000,
            'tare_weight_kg': 15000
        }, follow_redirects=True)

        self.assertEqual(resp_post.status_code, 200)
        self.assertIn(b'restringida por pol', resp_post.data)
        # Confirma que NO se grabo en la base de datos
        self.assertEqual(len(get_recent_weighings()), 0)

        # Intenta descargar reporte Excel (debe rebotar sin 500)
        resp_rep = self.client.get('/weighbridge/export/excel', follow_redirects=True)
        self.assertEqual(resp_rep.status_code, 200)
        self.assertIn(b'Exportaci', resp_rep.data)

    def test_config_licensing_update_route(self):
        """Verifica la ruta /config/licensing/update exclusiva para admin_sistema"""
        self.client.post('/login', data={'username': 'admin', 'pin': '1234'})
        resp = self.client.post('/config/licensing/update', data={
            'client_name': 'BioBalcarce Planta Nueva',
            'license_mode': 'suscripcion',
            'expiration_date': '2028-12-31',
            'is_active': '1',
            'max_users': '100',
            'block_data_entry': 'on',
            'status_notes': 'Prueba ruta configuracion'
        }, follow_redirects=True)
        self.assertEqual(resp.status_code, 200)
        status = get_licensing_status()
        self.assertEqual(status['client_name'], 'BioBalcarce Planta Nueva')
        self.assertEqual(status['license_mode'], 'suscripcion')
        self.assertEqual(status['max_users'], 100)

    # -------------------------------------------------------------------------
    # 3. PRUEBAS DE NOTIFICACION DE ACTUALIZADOR FLOTANTE (ADMIN SISTEMA)
    # -------------------------------------------------------------------------
    def test_floating_update_notification_visibility(self):
        """Verifica que la notificacion flotante de actualizacion solo sea visible para admin_sistema"""
        os.makedirs(PENDING_UPDATES_DIR, exist_ok=True)
        test_zip = os.path.join(PENDING_UPDATES_DIR, 'BioBalcarce_Update_v1.2.0.zip')

        # Crea un paquete ZIP de actualizacion comprobado simulado en updates/pending
        import zipfile
        with zipfile.ZipFile(test_zip, 'w') as zf:
            zf.writestr('version.json', '{"version": "1.2.0", "description": "Mejora de balanza y licenciamiento"}')

        try:
            # Verifica que el servicio detecte el paquete local pendiente
            status = check_system_update_status()
            self.assertTrue(status['available'])
            self.assertEqual(status['version'], '1.2.0')

            # 1. Login como Operario: NO debe ver la alerta flotante
            self.client.get('/logout')
            self.client.post('/login', data={'username': 'operario', 'pin': '1111'})
            r_op = self.client.get('/production/')
            self.assertNotIn(b'system-update-alert-pill', r_op.data)

            # 2. Login como Gerente: NO debe ver la alerta flotante
            self.client.get('/logout')
            self.client.post('/login', data={'username': 'gerente', 'pin': '3333'})
            r_mgr = self.client.get('/')
            self.assertNotIn(b'system-update-alert-pill', r_mgr.data)

            # 3. Login como Admin Sistema: DEBE ver la alerta flotante con la version y el boton de instalar
            self.client.get('/logout')
            self.client.post('/login', data={'username': 'admin', 'pin': '1234'})
            r_adm = self.client.get('/')
            self.assertIn(b'system-update-alert-pill', r_adm.data)
            self.assertIn(b'v1.2.0', r_adm.data)
            self.assertIn(b'Revisar e Instalar', r_adm.data)

        finally: # Bloque de limpieza
            if os.path.exists(test_zip): # Si existe archivo temporal
                os.remove(test_zip) # Elimina archivo zip de prueba

    def test_ticket_identification_and_truncated_headers(self): # Prueba de deteccion de ticket y cabeceras truncadas de balanza
        """Verifica que se identifique el ticket 1095 y las cabeceras truncadas como Transport, Patente A, Destinata, etc.""" # Docstring
        # Cabecera truncada idéntica a BALANZA TOTAL.xls
        header_line = "ID\tFecha Egreso\tFecha Ingreso\tProducto\tCliente\tTransport\tDestinata\tPatente C\tPatente A\tProceden\tNombre C\tPrecintos\tObservaci\tID Usuaric\tPeso Egre\tPeso Ingre\tPeso Net\tExportado\tTara Ma\tNacionali\tBultos\tAduana\tLOT\tDNI Chofe\tUsuario\tPesada Un\tDestinaci\n" # Cabecera con nombres truncados
        row_line = "1095\t11/6/2026 09:40\t11/6/2026 08:30\tSemilla\tAgronorte\tTransChaco\tBioBalcarce\tAA111BB\tCC222DD\tBalcarce\tMario Gomez\tPR-11\tCarga conforme\t1\t15000\t45000\t30000\tBioBalcarce Export\tNO\tArgentina\tGranel\tAduana MdP\tLOT-1095\t20123456\tbalancero1\tNO\tExportacion\n" # Fila de ticket 1095
        tsv_content = (header_line + row_line).encode('utf-8') # Codifica en bytes
        result = import_weighings_from_file(tsv_content, "BALANZA TOTAL.xls", sync_inventory=False) # Importa
        self.assertTrue(result['success']) # Exito
        self.assertEqual(result['imported_count'], 1) # 1 registro
        weighings = get_recent_weighings() # Consulta pesadas
        w = weighings[0] # Primer pesada
        self.assertEqual(w['ticket_number'], "1095") # Ticket correcto 1095
        self.assertEqual(w['transport_company'], "TransChaco") # Transportista
        self.assertEqual(w['trailer_plate'], "CC222DD") # Acoplado
        self.assertEqual(w['truck_plate'], "AA111BB") # Chasis
        self.assertEqual(w['driver_name'], "Mario Gomez") # Chofer
        self.assertEqual(w['exporter'], "BioBalcarce Export") # Exportador
        self.assertEqual(w['manual_tare'], "NO") # Tara manual
        self.assertEqual(w['net_weight_kg'], 30000.0) # Neto en kg

    def test_weighbridge_sorting_by_ticket_and_date(self): # Prueba de ordenamiento numerico de tickets y cronologico
        """Verifica que con filtro de fecha 01/06/2026 al 30/06/2026 el primer ticket mostrado sea el 1095 (ascendente) o 1207 (descendente)""" # Docstring
        record_weighing( # Registra ticket 1207 (fin de junio)
            ticket_number="1207", # Ticket 1207
            weigh_date="2026-06-30 08:34:00", # Fecha 30 de junio
            exit_date="2026-06-30 08:34:00", # Fecha egreso
            truck_plate="ABC120", # Patente
            product="semilla", # Producto
            gross_weight_kg=40000, # Bruto
            tare_weight_kg=10000 # Tara
        ) # Cierra llamada
        record_weighing( # Registra ticket 1095 (primer ticket del mes en la muestra)
            ticket_number="1095", # Ticket 1095
            weigh_date="2026-06-11 09:40:00", # Fecha 11 de junio
            exit_date="2026-06-11 09:40:00", # Fecha egreso
            truck_plate="ABC109", # Patente
            product="semilla", # Producto
            gross_weight_kg=42000, # Bruto
            tare_weight_kg=12000 # Tara
        ) # Cierra llamada
        record_weighing( # Registra ticket intermedio 1150
            ticket_number="1150", # Ticket 1150
            weigh_date="2026-06-20 14:00:00", # Fecha 20 de junio
            exit_date="2026-06-20 14:00:00", # Fecha egreso
            truck_plate="ABC115", # Patente
            product="semilla", # Producto
            gross_weight_kg=41000, # Bruto
            tare_weight_kg=11000 # Tara
        ) # Cierra llamada

        # 1. Consulta con filtro de junio y orden ascendente por ticket (por omision)
        w_asc = get_recent_weighings(start_date="2026-06-01", end_date="2026-06-30", order_by="ticket_asc") # Consulta asc
        self.assertEqual(len(w_asc), 3) # 3 pesadas
        self.assertEqual(w_asc[0]['ticket_number'], "1095") # Primer ticket es el 1095 requerido
        self.assertEqual(w_asc[1]['ticket_number'], "1150") # Segundo ticket 1150
        self.assertEqual(w_asc[2]['ticket_number'], "1207") # Tercer ticket 1207

        # 2. Consulta con orden descendente por ticket
        w_desc = get_recent_weighings(start_date="2026-06-01", end_date="2026-06-30", order_by="ticket_desc") # Consulta desc
        self.assertEqual(len(w_desc), 3) # 3 pesadas
        self.assertEqual(w_desc[0]['ticket_number'], "1207") # Primer ticket es el 1207
        self.assertEqual(w_desc[1]['ticket_number'], "1150") # Segundo ticket 1150
        self.assertEqual(w_desc[2]['ticket_number'], "1095") # Ultimo ticket 1095

    def test_reimport_upsert_fills_missing_tickets(self): # Prueba de enriquecimiento sin duplicar registros
        """Verifica que la re-importacion de una pesada previa sin ticket actualice el ticket_number y transporte""" # Docstring
        # Inserta registro previo que se habia quedado sin ticket_number
        with get_db_connection() as conn: # Abre conexion
            conn.execute("""
                INSERT INTO truck_scale_weighings (ticket_number, weigh_date, exit_date, truck_plate, operation_type, product, transport_company)
                VALUES (NULL, '2026-06-11 09:40:00', '2026-06-11 09:40:00', 'REIMP11', 'egreso', 'aceite', NULL);
            """) # Insercion incompleta
            conn.commit() # Confirma

        self.assertEqual(len(get_recent_weighings()), 1) # Comprueba 1 pesada previa
        w_before = get_recent_weighings()[0] # Obtiene registro
        self.assertIsNone(w_before['ticket_number']) # Ticket previo nulo
        self.assertIsNone(w_before['transport_company']) # Transporte previo nulo

        # Importa archivo con ticket 1095 y transporte para la misma patente y fecha
        header = "ID\tFecha Egreso\tPatente Chasis\tTransportista\tOperacion\tProducto\tPeso Egreso\tPeso Ingreso\n" # Cabeceras
        row = "1095\t2026-06-11 09:40:00\tREIMP11\tTransBio\tegreso\taceite\t30000\t10000\n" # Renglon de actualizacion
        tsv = (header + row).encode('utf-8') # Codifica
        result = import_weighings_from_file(tsv, "BALANZA.xls") # Ejecuta re-importacion
        self.assertTrue(result['success']) # Exito

        # Verifica que NO se duplico el registro y que se actualizo el ticket y transportista
        weighings = get_recent_weighings() # Consulta pesadas
        self.assertEqual(len(weighings), 1) # Exactamente 1 fila sin duplicados
        self.assertEqual(weighings[0]['ticket_number'], "1095") # Ticket actualizado
        self.assertEqual(weighings[0]['transport_company'], "TransBio") # Transporte actualizado

    def test_migration_18_applied(self): # Prueba de aplicacion de migracion 18
        """Verifica que la migracion 18 de indices de ticket se aplique correctamente""" # Docstring
        from core.migrations import apply_pending_migrations, get_applied_migration_versions # Importa funciones de migracion
        apply_pending_migrations() # Aplica pendientes
        applied = get_applied_migration_versions() # Consulta versiones
        self.assertIn(18, applied) # Comprueba version 18 registrada

if __name__ == '__main__': # Punto de entrada de ejecucion
    unittest.main() # Ejecuta pruebas unitarias
