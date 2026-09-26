# Suite de pruebas unitarias e integrales para el modulo de Mantenimiento y Pañol de Repuestos
# Importa unittest para ejecucion automatizada de casos de prueba
import unittest
# Importa tempfile para crear bases de datos aisladas de prueba
import tempfile
# Importa os para manipulacion de archivos temporales
import os
# Importa io para simular archivos de imagen en memoria
import io
# Importa sqlite3 para verificaciones directas de registros
import sqlite3

# Importa componentes principales de la aplicacion
from run import app
# Importa inicializador de base de datos
from core.database import init_db, reset_production_operational_data, get_db_connection
# Importa ejecutor de migraciones
from core.migrations import apply_pending_migrations
# Importa funciones de servicio de mantenimiento
from modules.maintenance.service import (
    create_maintenance_activity, get_maintenance_activities, get_activity_by_id,
    update_activity_status, save_maintenance_image, get_activity_images,
    create_or_update_spare_part, get_spare_parts, get_spare_part_by_id,
    record_spare_part_movement, get_spare_parts_report_data, get_maintenance_dashboard_kpis
)


# Clase de pruebas para mantenimiento y stock
class TestMaintenanceAndSpareParts(unittest.TestCase):
    # Metodo de configuracion previo a cada test
    def setUp(self):
        # Habilita el modo de pruebas en Flask
        app.config['TESTING'] = True
        # Deshabilita proteccion CSRF en pruebas
        app.config['WTF_CSRF_ENABLED'] = False
        # Crea un archivo temporal para la base de datos de prueba
        self.db_fd, self.db_path = tempfile.mkstemp(suffix='.db')
        # Crea un directorio temporal para subida de imagenes de prueba
        self.upload_dir = tempfile.mkdtemp(prefix='maint_test_uploads_')
        # Redirige la ruta de base de datos en config
        import config
        # Importa core.database para asegurar actualizacion de variable exportada
        import core.database
        # Guarda la ruta original
        self.orig_db_path = config.DATABASE_PATH
        # Guarda el directorio original de uploads
        self.orig_upload_dir = config.MAINTENANCE_UPLOADS_DIR
        # Asigna la base temporal en config
        config.DATABASE_PATH = self.db_path
        # Asigna la base temporal en core.database
        core.database.DATABASE_PATH = self.db_path
        # Asigna la carpeta de subidas temporal
        config.MAINTENANCE_UPLOADS_DIR = self.upload_dir
        # Inicializa esquema de tablas completo
        init_db()
        # Aplica migraciones incrementales
        apply_pending_migrations()
        # Crea el cliente de pruebas HTTP
        self.client = app.test_client()

    # Metodo de limpieza posterior a cada test
    def tearDown(self):
        # Restaura rutas originales
        import config
        # Importa core.database para restauracion de variable exportada
        import core.database
        # Restaura base de datos en config
        config.DATABASE_PATH = self.orig_db_path
        # Restaura base de datos en core.database
        core.database.DATABASE_PATH = self.orig_db_path
        # Restaura directorio de uploads
        config.MAINTENANCE_UPLOADS_DIR = self.orig_upload_dir
        # Cierra descriptor de archivo temporal
        os.close(self.db_fd)
        # Elimina archivo temporal si existe
        if os.path.exists(self.db_path):
            os.remove(self.db_path)
        # Limpia archivos del directorio de uploads de prueba
        if os.path.exists(self.upload_dir):
            import shutil
            shutil.rmtree(self.upload_dir, ignore_errors=True)

    # Autentica sesion con un usuario y rol especifico
    def login_as(self, username='admin', role='admin_sistema', full_name='Administrador'):
        # Abre el contexto de sesion de Flask
        with self.client.session_transaction() as sess:
            # Asigna ID de usuario simulado
            sess['user_id'] = 1
            # Asigna nombre de usuario
            sess['username'] = username
            # Asigna rol
            sess['role'] = role
            # Asigna nombre completo
            sess['full_name'] = full_name

    # Prueba la creacion de actividades en las 3 categorias oficiales
    def test_create_activities_by_categories(self):
        # 1. Crea actividad Operativa (en marcha)
        id_op = create_maintenance_activity(
            title="Reparación urgente pérdida de aceite prensa 1",
            category="operativa",
            equipment_tag="Prensa 1",
            priority="alta",
            description="Se detectó fuga en sello delantero",
            reported_by="Operario Guardia"
        )
        # Verifica que se haya asignado un ID valido
        self.assertGreater(id_op, 0)

        # 2. Crea actividad Planificada con Parada
        id_plan_parada = create_maintenance_activity(
            title="Cambio general de forros y maza prensa 2",
            category="planificada_con_parada",
            equipment_tag="Prensa 2",
            priority="critica",
            description="Desgaste acumulado requiere 12 horas de parada de linea",
            reported_by="Jefe Mantenimiento",
            scheduled_date="2026-10-05"
        )
        # Verifica ID valido
        self.assertGreater(id_plan_parada, 0)

        # 3. Crea actividad Planificada sin Parada
        id_plan_sin = create_maintenance_activity(
            title="Pintura y engrase de tolva de descarga",
            category="planificada_sin_parada",
            equipment_tag="Tolva Descarga",
            priority="baja",
            description="Mantenimiento cosmetico y preventivo",
            reported_by="Supervisor"
        )
        # Verifica ID valido
        self.assertGreater(id_plan_sin, 0)

        # Consulta todas las actividades
        all_acts = get_maintenance_activities()
        # Comprueba que existan al menos las 3 creadas
        self.assertEqual(len(all_acts), 3)

        # Filtra solo actividades operativas
        op_acts = get_maintenance_activities(category='operativa')
        # Verifica que solo devuelva 1
        self.assertEqual(len(op_acts), 1)
        # Verifica que coincida el ID
        self.assertEqual(op_acts[0]['id'], id_op)

        # Verifica rechazo de categoria no contemplada
        with self.assertRaises(ValueError):
            create_maintenance_activity(
                title="Prueba invalida",
                category="categoria_inexistente",
                equipment_tag="Test",
                priority="baja",
                description="Test",
                reported_by="Tester"
            )

    # Prueba la actualizacion de estados y notas de resolucion
    def test_update_activity_status_flow(self):
        # Crea una actividad inicial
        act_id = create_maintenance_activity(
            title="Reemplazo de fusible principal tablero 2",
            category="operativa",
            equipment_tag="Tablero 2",
            priority="alta",
            description="Fusible quemado en arranque",
            reported_by="Operario"
        )
        # Cambia estado a en_progreso
        res = update_activity_status(act_id, 'en_progreso', operator_name='Tecnico')
        # Confirma exito
        self.assertTrue(res)
        # Verifica estado actualizado
        act = get_activity_by_id(act_id)
        # Comprueba estado
        self.assertEqual(act['status'], 'en_progreso')

        # Cambia estado a completada con resolucion
        update_activity_status(act_id, 'completada', resolution_notes="Fusible NH 63A reemplazado y medido 380V OK.", operator_name='Tecnico')
        # Consulta estado final
        act_closed = get_activity_by_id(act_id)
        # Verifica estado
        self.assertEqual(act_closed['status'], 'completada')
        # Verifica notas de resolucion
        self.assertIn("Fusible NH 63A", act_closed['resolution_notes'])
        # Verifica que se haya completado la fecha
        self.assertIsNotNone(act_closed['completed_at'])

    # Prueba el control de stock, alerta de minimo y consumibles
    def test_spare_parts_stock_and_critical_alert(self):
        # Da de alta un repuesto mecanico con stock superior al minimo
        part1_id = create_or_update_spare_part(
            code="ROD-TEST-100",
            name="Rodamiento Blindado 6205",
            category="Rodamientos",
            equipment_assigned="Molino",
            is_consumable=False,
            stock_quantity=10.0,
            min_stock=3.0,
            unit="unidades"
        )
        # Consulta la pieza
        p1 = get_spare_part_by_id(part1_id)
        # Verifica que NO este en estado critico
        self.assertFalse(p1['is_critical'])
        # Verifica que no sea consumible
        self.assertEqual(p1['is_consumable'], 0)

        # Da de alta un consumible con stock critico (menor al minimo)
        part2_id = create_or_update_spare_part(
            code="GRASA-TEST-EP",
            name="Grasa Azul para Rodamientos",
            category="Lubricantes",
            equipment_assigned="General",
            is_consumable=True,
            stock_quantity=2.0,
            min_stock=5.0,
            unit="kg"
        )
        # Consulta el consumible
        p2 = get_spare_part_by_id(part2_id)
        # Verifica que SI este en estado critico
        self.assertTrue(p2['is_critical'])
        # Verifica flag de consumible
        self.assertEqual(p2['is_consumable'], 1)

        # Realiza un movimiento de egreso en part1 que lo deja en stock critico
        new_stock = record_spare_part_movement(part1_id, 'egreso_mantenimiento', 8.0, 'Mecanico', reason="Reparacion urgente")
        # Verifica el nuevo stock resultante (10 - 8 = 2)
        self.assertEqual(new_stock, 2.0)
        # Consulta nuevamente part1
        p1_updated = get_spare_part_by_id(part1_id)
        # Verifica que ahora SI este en nivel critico (2 <= 3)
        self.assertTrue(p1_updated['is_critical'])

        # Realiza un ingreso de reposicion
        new_stock_after_buy = record_spare_part_movement(part1_id, 'ingreso', 10.0, 'Pañolero', reason="Compra factura #999")
        # Verifica stock restablecido (2 + 10 = 12)
        self.assertEqual(new_stock_after_buy, 12.0)
        # Consulta nuevamente
        self.assertFalse(get_spare_part_by_id(part1_id)['is_critical'])

    # Prueba la carga y asociacion de imagenes de reparaciones
    def test_save_maintenance_image_and_gallery(self):
        # Crea una actividad base
        act_id = create_maintenance_activity(
            title="Desarme reductor elevador principal",
            category="planificada_con_parada",
            equipment_tag="Elevador 1",
            priority="alta",
            description="Cambio de engranaje helicoidal",
            reported_by="Mecanico"
        )
        # Simula un archivo de imagen en memoria
        fake_image = (io.BytesIO(b"FAKE_IMAGE_DATA_HEADER_PNG"), 'foto_falla.png')
        # Sube la fotografia
        from werkzeug.datastructures import FileStorage
        file_obj = FileStorage(stream=fake_image[0], filename=fake_image[1], content_type='image/png')
        filename = save_maintenance_image(act_id, file_obj, caption="Daño en chavetero")
        # Verifica que se haya guardado y retornado el nombre
        self.assertTrue(filename.startswith(f"maint_{act_id}_"))
        # Verifica que el archivo exista fisicamente en la carpeta de uploads temporal
        import config
        self.assertTrue(os.path.exists(os.path.join(config.MAINTENANCE_UPLOADS_DIR, filename)))

        # Consulta las imagenes asociadas a la actividad
        imgs = get_activity_images(act_id)
        # Comprueba que exista 1 imagen
        self.assertEqual(len(imgs), 1)
        # Comprueba el epigrafe
        self.assertEqual(imgs[0]['caption'], "Daño en chavetero")

    # Prueba los reportes imprimibles y la exportacion a archivo CSV
    def test_reports_and_csv_export(self):
        # Autentica sesion
        self.login_as(role='usuario')
        # Agrega un repuesto de prueba
        create_or_update_spare_part(
            code="RET-TEST-01",
            name="Reten 40x60x10",
            category="Retenes",
            equipment_assigned="Prensa",
            is_consumable=False,
            stock_quantity=1.0,
            min_stock=2.0
        )
        # Prueba el endpoint de exportacion CSV
        res_csv = self.client.get('/maintenance/report/csv')
        # Comprueba respuesta exitosa
        self.assertEqual(res_csv.status_code, 200)
        # Comprueba que el tipo de contenido sea text/csv
        self.assertIn('text/csv', res_csv.headers['Content-Type'])
        # Comprueba que el contenido incluya las cabeceras esperadas
        data_text = res_csv.data.decode('utf-8')
        self.assertIn("Código", data_text)
        self.assertIn("RET-TEST-01", data_text)
        self.assertIn("CRÍTICO", data_text)

        # Prueba el endpoint de impresion limpia
        res_print = self.client.get('/maintenance/report/print')
        # Comprueba HTTP 200
        self.assertEqual(res_print.status_code, 200)
        # Comprueba que contenga el titulo del reporte
        self.assertIn("REPORTE OFICIAL DE EXISTENCIAS", res_print.data.decode('utf-8'))

    # Prueba que la funcion de reset de produccion limpie datos operativos pero preserve datos maestros
    def test_reset_production_operational_data_preserves_master_records(self):
        # Inserta datos operativos de prueba directamente en la base
        with get_db_connection() as conn:
            # Inserta pesada de prueba
            conn.execute("""
            INSERT INTO production_weighings (timestamp, shift_id, operator_name, sample_point, gross_weight_kg, tare_weight_kg, net_weight_kg, fill_time_seconds, speed_kg_h, proj_8h_kg, proj_24h_kg)
            VALUES (CURRENT_TIMESTAMP, 'TM', 'Tester', 'salida_expeller', 10.0, 0.5, 9.5, 12.0, 2850.0, 22800.0, 68400.0);
            """)
            # Inserta parada de prueba
            conn.execute("""
            INSERT INTO line_stops (shift_id, start_time, duration_minutes, reason, operator_name)
            VALUES ('TM', CURRENT_TIMESTAMP, 15.0, 'Prueba de parada', 'Tester');
            """)
            # Inserta analisis de laboratorio de prueba
            conn.execute("""
            INSERT INTO lab_analyses (timestamp, sample_code, product, sampling_point, shift_id, operator_name, moisture_pct, fat_pct)
            VALUES (CURRENT_TIMESTAMP, 'LAB-TEST', 'semilla', 'Silo 1', 'TM', 'Analista Test', 8.5, 48.2);
            """)
            # Confirma la insercion
            conn.commit()

        # Comprueba que existan datos operativos antes de la limpieza
        with get_db_connection() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM production_weighings;").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM line_stops;").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM lab_analyses;").fetchone()[0], 1)
            # Cuenta usuarios y turnos maestros
            initial_users = conn.execute("SELECT COUNT(*) FROM users;").fetchone()[0]
            initial_shifts = conn.execute("SELECT COUNT(*) FROM shifts;").fetchone()[0]
            initial_tanks = conn.execute("SELECT COUNT(*) FROM equipment_tanks;").fetchone()[0]
            initial_silos = conn.execute("SELECT COUNT(*) FROM equipment_silos;").fetchone()[0]
            # Deben ser mayores a cero
            self.assertGreater(initial_users, 0)
            self.assertGreater(initial_shifts, 0)

        # Ejecuta la limpieza de produccion
        reset_production_operational_data()

        # Comprueba que las tablas operativas queden vacias (0 filas)
        with get_db_connection() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM production_weighings;").fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM line_stops;").fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM lab_analyses;").fetchone()[0], 0)
            # COMPRUEBA QUE LOS DATOS MAESTROS ESTEN 100% PRESERVADOS
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM users;").fetchone()[0], initial_users)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM shifts;").fetchone()[0], initial_shifts)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM equipment_tanks;").fetchone()[0], initial_tanks)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM equipment_silos;").fetchone()[0], initial_silos)
            # Comprueba que se haya dejado un registro en auditoria documentando el reset
            audit_reset = conn.execute("SELECT COUNT(*) FROM audit_logs WHERE action = 'RESET_PRODUCCION';").fetchone()[0]
            self.assertEqual(audit_reset, 1)

    # Prueba de los 3 KPIs de mantenimiento en el dashboard y el renderizado de la barra lateral
    def test_maintenance_dashboard_kpis_and_cockpit_sidebar(self):
        # 1. Verifica estado inicial en cero
        kpis_initial = get_maintenance_dashboard_kpis()
        self.assertEqual(kpis_initial['pending_count'], 0)
        self.assertEqual(kpis_initial['operative_count'], 0)
        self.assertEqual(kpis_initial['planned_stop_count'], 0)

        # 2. Registra una tarea operativa urgente
        act1_id = create_maintenance_activity(
            title="Ajuste de correa de prensa",
            category="operativa",
            equipment_tag="PRENSA-01",
            priority="alta",
            description="Vibración detectada en marcha",
            reported_by="Operario 1"
        )
        self.assertIsNotNone(act1_id)

        # 3. Registra una tarea planificada con parada de planta
        act2_id = create_maintenance_activity(
            title="Cambio de rodamiento principal",
            category="planificada_con_parada",
            equipment_tag="EXTRUSOR-01",
            priority="critica",
            description="Mantenimiento preventivo programado",
            reported_by="Mantenimiento"
        )
        self.assertIsNotNone(act2_id)

        # 4. Verifica los contadores actualizados
        kpis = get_maintenance_dashboard_kpis()
        self.assertEqual(kpis['pending_count'], 2)
        self.assertEqual(kpis['operative_count'], 1)
        self.assertEqual(kpis['planned_stop_count'], 1)

        # 5. Verifica la consulta completa del dashboard ejecutivo
        from modules.dashboard.service import get_executive_dashboard_data
        dash_data = get_executive_dashboard_data()
        self.assertIn('maintenance_kpis', dash_data)
        self.assertEqual(dash_data['maintenance_kpis']['pending_count'], 2)
        self.assertEqual(dash_data['maintenance_kpis']['operative_count'], 1)
        self.assertEqual(dash_data['maintenance_kpis']['planned_stop_count'], 1)

        # 6. Verifica la respuesta HTTP del dashboard con rol gerencia / administrador
        with self.client.session_transaction() as sess:
            sess['user_id'] = 1
            sess['username'] = 'admin'
            sess['full_name'] = 'Administrador Planta'
            sess['role'] = 'administrador'

        resp = self.client.get('/')
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)

        # Verifica presencia del contenedor wrapper y la barra lateral de mantenimiento
        self.assertIn('cockpit-layout-wrapper', html)
        self.assertIn('cockpit-maint-sidebar', html)
        self.assertIn('Tareas Pendientes', html)
        self.assertIn('Operativas (En Marcha)', html)
        self.assertIn('Planificadas c/ Parada', html)
        self.assertIn('Intervenciones en espera', html)
        self.assertIn('Urgencias del momento', html)
        self.assertIn('Requieren detener planta', html)

# Bloque de ejecucion si el archivo se llama directamente
if __name__ == '__main__':
    unittest.main()

