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

        finally:
            if os.path.exists(test_zip):
                os.remove(test_zip)

if __name__ == '__main__':
    unittest.main()
