# Suite de pruebas unitarias automatizadas para identificacion de fecha y turno de toma de muestra
# Importa unittest para ejecucion y aserciones de prueba
import unittest
# Importa componentes de sistema y ruta
import sys, os
# Importa datetime para manejo de fechas
import datetime
# Agrega el directorio raiz del repositorio al sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Importa inicializador de base de datos
from core.database import init_db, get_db_connection
# Importa la aplicacion Flask
from run import app
# Importa servicios de laboratorio
from modules.laboratory.service import (
    record_analysis, update_analysis, get_shift_lab_averages, get_recent_analyses
)
# Importa servicios de produccion
from modules.production.service import (
    record_weighing, update_weighing, get_shift_speed_summary, get_recent_weighings
)
# Importa servicio de dashboard
from modules.dashboard.service import get_dashboard_shift_comparison
# Importa funciones de tiempo oficial de planta
from core.timezone import get_plant_today_str, get_plant_now_str
# Importa modelos de usuario para sesion de prueba
from core.auth import create_user, authenticate_user

# Clase de pruebas para desacople de fecha de toma de muestra vs fecha de carga
class TestSampleDateShiftIdentification(unittest.TestCase):
    # Metodo de configuracion ejecutado antes de cada prueba
    def setUp(self):
        # Inicializa o migra la base de datos
        init_db()
        # Habilita modo pruebas en Flask
        app.config['TESTING'] = True
        # Desactiva proteccion CSRF en pruebas
        app.config['WTF_CSRF_ENABLED'] = False
        # Crea cliente de pruebas HTTP
        self.client = app.test_client()

        # Limpia registros operativos de prueba para aislamiento
        with get_db_connection() as conn:
            # Elimina pesadas de prueba
            conn.execute("DELETE FROM production_weighings WHERE notes LIKE '%TEST_SAMPLE%';")
            # Elimina analisis de prueba
            conn.execute("DELETE FROM lab_analyses WHERE sample_code LIKE 'TST-%';")
            # Elimina paradas de prueba
            conn.execute("DELETE FROM line_stops WHERE reason LIKE '%TEST_SAMPLE%';")
            # Confirma limpieza
            conn.commit()

        # Crea y autentica usuario admin_sistema para llamadas HTTP
        try:
            # Intenta crear el usuario de prueba
            create_user('admin_test_sample', 'Test Admin', 'admin_sistema', '12345678', 'AdminPass123!')
        # Si ya existe continua
        except Exception:
            # Pasa si el usuario ya fue creado
            pass

        # Autentica al usuario de prueba en la sesion de Flask
        with self.client.session_transaction() as sess:
            # Asigna ID de usuario
            sess['user_id'] = 999
            # Asigna username
            sess['username'] = 'admin_test_sample'
            # Asigna rol admin_sistema
            sess['role'] = 'admin_sistema'
            # Asigna nombre completo
            sess['full_name'] = 'Test Admin'

    # Metodo de limpieza ejecutado luego de cada prueba
    def tearDown(self):
        # Abre conexion para purgar datos de prueba
        with get_db_connection() as conn:
            # Limpia pesadas
            conn.execute("DELETE FROM production_weighings WHERE notes LIKE '%TEST_SAMPLE%';")
            # Limpia analisis
            conn.execute("DELETE FROM lab_analyses WHERE sample_code LIKE 'TST-%';")
            # Limpia paradas
            conn.execute("DELETE FROM line_stops WHERE reason LIKE '%TEST_SAMPLE%';")
            # Confirma transaccion
            conn.commit()

    # Prueba 1: Desacople de fecha de toma vs fecha de carga en laboratorio
    def test_laboratory_sample_date_decoupled_from_load_timestamp(self):
        # Fecha de hoy en planta (momento de la carga del dato)
        today = get_plant_today_str()
        # Fecha anterior simulada (momento de la toma fisica de la muestra)
        past_date = "2026-09-10"
        # Turno de toma fisica
        past_shift = "TM"

        # Registra un analisis indicando explicitamente fecha anterior y turno manana
        res = record_analysis(
            sample_code="TST-LAB-01",
            product="expeller",
            sampling_point="Prensa 2",
            moisture_pct=8.5,
            fat_pct=11.2,
            acidity_pct=None,
            impurities_pct=None,
            operator_name="Laboratorista Test",
            press_number=2,
            notes="TEST_SAMPLE_DESACOPLE",
            sample_date=past_date,
            shift_id=past_shift
        )

        # Verifica que la respuesta contenga la fecha de muestra asignada
        self.assertEqual(res['sample_date'], past_date)
        # Verifica que el turno asignado sea el indicado
        self.assertEqual(res['shift_id'], past_shift)

        # Consulta promedios analiticos filtrados por la fecha real de la muestra
        avg_past = get_shift_lab_averages(shift_id=past_shift, target_date=past_date)
        # Verifica que la materia grasa calculada para la fecha de muestra coincida con la cargada
        self.assertIsNotNone(avg_past['expeller_fat_pct'])
        # Compara valor esperado
        self.assertEqual(avg_past['expeller_fat_pct'], 11.2)

        # Consulta promedios para hoy (cuando se ingreso el dato en el sistema)
        avg_today = get_shift_lab_averages(shift_id=past_shift, target_date=today)
        # Verifica que el dato NO contamine los promedios del turno de hoy
        self.assertNotEqual(avg_today.get('expeller_fat_pct'), 11.2)

    # Prueba 2: Desacople de fecha de toma vs fecha de carga en pesadas de velocidad
    def test_production_weighing_sample_date_decoupled(self):
        # Fecha actual de carga
        today = get_plant_today_str()
        # Fecha historica de extraccion de la muestra
        past_date = "2026-09-12"
        # Turno de la toma
        past_shift = "TT"

        # Registra pesada de bolsa indicando fecha pasada y turno tarde
        w = record_weighing(
            shift_id=past_shift,
            operator_name="Operario Test",
            sample_point="salida_expeller",
            gross_weight_kg=12.5,
            tare_weight_kg=0.5,
            fill_time_seconds=30.0,
            line_status="operando",
            notes="TEST_SAMPLE_WEIGHING",
            sample_date=past_date
        )

        # Verifica que la pesada retorne la fecha de muestra
        self.assertEqual(w['sample_date'], past_date)
        # Verifica que retorne el turno de muestra
        self.assertEqual(w['shift_id'], past_shift)
        # Neto: 12.0 kg en 30s -> 1440 kg/h
        self.assertEqual(w['speed_kg_h'], 1440.0)

        # Obtiene el resumen de velocidad para la fecha historica de la muestra
        summary_past = get_shift_speed_summary(shift_id=past_shift, target_date=past_date)
        # Verifica que reconozca la pesada en la fecha de muestra
        self.assertGreaterEqual(summary_past['expeller_sample_count'], 1)
        # Verifica que el promedio horario refleje la velocidad calculada
        self.assertEqual(summary_past['expeller_avg_speed'], 1440.0)

    # Prueba 3: Modificacion de fecha y turno de muestra con bitacora de auditoria
    def test_update_sample_date_and_shift(self):
        # Registra pesada inicial
        w = record_weighing(
            shift_id="TM",
            operator_name="Op Test",
            sample_point="ingreso_semilla",
            gross_weight_kg=15.0,
            tare_weight_kg=0.0,
            fill_time_seconds=30.0,
            line_status="operando",
            notes="TEST_SAMPLE_EDIT",
            sample_date="2026-09-14"
        )
        # ID de la pesada
        w_id = w['id']

        # Actualiza la pesada reasignando su fecha y turno de origen
        update_weighing(
            weighing_id=w_id,
            sample_point="ingreso_semilla",
            gross_weight_kg=16.0,
            tare_weight_kg=0.0,
            fill_time_seconds=30.0,
            line_status="operando",
            notes="TEST_SAMPLE_EDIT_UPDATED",
            edit_reason="Muestra tomada en Turno Tarde el 15",
            operator_name="Supervisor Test",
            sample_date="2026-09-15",
            shift_id="TT"
        )

        # Consulta el registro actualizado en base de datos
        with get_db_connection() as conn:
            # Obtiene fila modificada
            row = conn.execute("SELECT * FROM production_weighings WHERE id = ?;", (w_id,)).fetchone()
            # Obtiene auditoria del cambio
            audit = conn.execute("SELECT * FROM audit_logs WHERE event_type = 'EDICION_PESADA' ORDER BY timestamp DESC LIMIT 1;").fetchone()

        # Verifica que la fecha de muestra sea la nueva
        self.assertEqual(row['sample_date'], '2026-09-15')
        # Verifica que el turno de muestra sea TT
        self.assertEqual(row['shift_id'], 'TT')
        # Verifica que la auditoria haya registrado el motivo
        self.assertIn("Muestra tomada en Turno Tarde", audit['details'])

    # Prueba 4: Verificacion de rutas HTTP para alta y edicion con fecha y turno de muestra
    def test_http_routes_sample_date_and_shift_integration(self):
        # POST para registrar pesada desde la interfaz web
        resp_prod = self.client.post('/production/weighing', data={
            'sample_date': '2026-09-18',
            'shift_id': 'TN',
            'operator_name': 'Operario Web',
            'sample_point': 'salida_expeller',
            'gross_weight_kg': '10.0',
            'tare_weight_kg': '0.0',
            'fill_time_seconds': '30',
            'line_status': 'operando',
            'notes': 'TEST_SAMPLE_HTTP'
        }, follow_redirects=True)
        # Verifica codigo HTTP 200 de exito
        self.assertEqual(resp_prod.status_code, 200)

        # Verifica que la pesada se haya guardado con sample_date y shift_id
        with get_db_connection() as conn:
            # Consulta pesada web
            saved_w = conn.execute("SELECT * FROM production_weighings WHERE notes = 'TEST_SAMPLE_HTTP';").fetchone()
        # Verifica no nulo
        self.assertIsNotNone(saved_w)
        # Verifica fecha de muestra
        self.assertEqual(saved_w['sample_date'], '2026-09-18')
        # Verifica turno
        self.assertEqual(saved_w['shift_id'], 'TN')

        # POST para registrar analisis de laboratorio desde la interfaz web
        resp_lab = self.client.post('/laboratory/add', data={
            'sample_date': '2026-09-18',
            'shift_id': 'TN',
            'sample_code': 'TST-HTTP-01',
            'product': 'expeller',
            'sampling_point': 'Prensa 2',
            'press_number': '2',
            'fat_pct': '10.5',
            'moisture_pct': '8.0',
            'operator_name': 'Quimico Web',
            'notes': 'TEST_SAMPLE_HTTP_LAB'
        }, follow_redirects=True)
        # Verifica codigo HTTP 200
        self.assertEqual(resp_lab.status_code, 200)

        # Verifica que el analisis de laboratorio contenga la fecha y turno
        with get_db_connection() as conn:
            # Consulta analisis web
            saved_l = conn.execute("SELECT * FROM lab_analyses WHERE sample_code = 'TST-HTTP-01';").fetchone()
        # Verifica existencia
        self.assertIsNotNone(saved_l)
        # Verifica fecha de muestra
        self.assertEqual(saved_l['sample_date'], '2026-09-18')
        # Verifica turno de muestra
        self.assertEqual(saved_l['shift_id'], 'TN')

    # Prueba 5: Verificacion de agregacion y clasificacion en el Dashboard segun fecha de muestra
    def test_dashboard_aggregation_by_sample_date(self):
        # Registra pesada con fecha operativa especifica
        record_weighing(
            shift_id="TM",
            operator_name="Op Dash",
            sample_point="ingreso_semilla",
            gross_weight_kg=20.0,
            tare_weight_kg=0.0,
            fill_time_seconds=30.0,
            line_status="operando",
            notes="TEST_SAMPLE_DASH",
            sample_date="2026-09-22"
        )
        # Registra analisis con la misma fecha operativa
        record_analysis(
            sample_code="TST-DASH-01",
            product="expeller",
            sampling_point="Prensa 2",
            moisture_pct=7.5,
            fat_pct=9.8,
            operator_name="Lab Dash",
            press_number=2,
            notes="TEST_SAMPLE_DASH_LAB",
            sample_date="2026-09-22",
            shift_id="TM"
        )

        # Ejecuta la conciliacion multi-turno del dashboard para la fecha de muestra 2026-09-22
        dash_data = get_dashboard_shift_comparison(target_date="2026-09-22")
        # Verifica que la fecha activa del dashboard sea la fecha de la muestra
        self.assertEqual(dash_data['active_op_date'], "2026-09-22")

        # Busca el turno manana en el comparativo
        tm_shift = next((s for s in dash_data['shifts_comparison'] if s['shift_id'] == 'TM'), None)
        # Verifica existencia del turno
        self.assertIsNotNone(tm_shift)
        # Verifica que haya contabilizado la muestra de semilla
        self.assertEqual(tm_shift['seed_samples_count'], 1)
        # Verifica que la velocidad coincida (20kg en 30s = 2400 kg/h)
        self.assertEqual(tm_shift['seed_avg_speed'], 2400.0)
        # Verifica que la media analitica de expeller prensa 2 sea 9.8%
        self.assertEqual(tm_shift['avg_fat_p2'], 9.8)

# Ejecuta las pruebas si se invoca como modulo principal
if __name__ == '__main__':
    # Corre suite de pruebas
    unittest.main()
