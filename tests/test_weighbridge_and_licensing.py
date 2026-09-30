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

    def test_export_weighings_excel_and_csv(self):
        """Verifica la exportacion de pesadas a Excel (.xlsx) y CSV"""
        record_weighing(
            ticket_number="TK-EXP-1",
            truck_plate="EXP111",
            operation_type="ingreso",
            product="semilla",
            gross_weight_kg=40000,
            tare_weight_kg=15000
        )
        # Exporta a Excel
        excel_bytes = export_weighings_to_excel()
        self.assertIsInstance(excel_bytes, bytes)
        self.assertTrue(len(excel_bytes) > 1000)

        # Valida que sea un XLSX valido leyendolo con openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(excel_bytes))
        sheet = wb.active
        self.assertIn("Pesadas de Balanza", sheet.title)
        wb.close()

        # Exporta a CSV
        csv_bytes = export_weighings_to_csv()
        self.assertIn("TK-EXP-1", csv_bytes)
        self.assertIn("EXP111", csv_bytes)

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
