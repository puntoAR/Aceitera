# Script de pruebas de integracion extremo a extremo para el sistema BioBalcarce
# Importa unittest para organizar y ejecutar la suite
import unittest
# Importa sys y os para configurar el path
import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Importa la aplicacion Flask configurada
from run import app
# Importa las funciones de inicializacion y conexion de base de datos
from core.database import init_db, get_db_connection
# Importa servicios de cada modulo
from modules.production.service import record_weighing, record_line_stop, get_shift_speed_summary
from modules.inventory.service import record_tank_level, record_silo_measurement, get_total_plant_stocks
from modules.laboratory.service import record_analysis, get_shift_lab_averages
from modules.yield_balance.service import reconcile_shift, get_recent_reconciliations
from modules.dashboard.service import get_executive_dashboard_data

# Clase de prueba de integracion completa
class TestBioBalcarceIntegration(unittest.TestCase):
    # Metodo que se ejecuta antes de cada prueba para garantizar estado limpio
    def setUp(self):
        # Configura la app Flask en modo de pruebas
        app.config['TESTING'] = True
        app.config['WTF_CSRF_ENABLED'] = False
        # Crea el cliente de pruebas HTTP de Flask
        self.client = app.test_client()
        # Asegura que la base de datos este inicializada
        init_db()
        # Limpia registros operativos previos para garantizar determinismo en las pruebas
        with get_db_connection() as conn:
            conn.execute("DELETE FROM production_weighings;")
            conn.execute("DELETE FROM line_stops;")
            conn.execute("DELETE FROM inventory_tanks;")
            conn.execute("DELETE FROM inventory_silos;")
            conn.execute("DELETE FROM lab_analyses;")
            conn.execute("DELETE FROM shift_reconciliations;")
            conn.commit()

    # Prueba 1: Flujo completo de registro de produccion y calculo de velocidad
    def test_production_flow(self):
        # Registra pesada de semilla: 30 kg en 60 seg = 1800 kg/h
        w1 = record_weighing('TM', 'Operario 1', 'ingreso_semilla', 30.0, 0.0, 60.0, 'operando')
        self.assertEqual(w1['speed_kg_h'], 1800.0)
        self.assertEqual(w1['proj_8h_kg'], 14400.0)

        # Registra segunda pesada de semilla: 32 kg en 60 seg = 1920 kg/h
        w2 = record_weighing('TM', 'Operario 1', 'ingreso_semilla', 32.0, 0.0, 60.0, 'operando')
        self.assertEqual(w2['speed_kg_h'], 1920.0)

        # Registra pesada de expeller: 15 kg en 60 seg = 900 kg/h
        w3 = record_weighing('TM', 'Operario 1', 'salida_expeller', 15.0, 0.0, 60.0, 'operando')
        self.assertEqual(w3['speed_kg_h'], 900.0)

        # Registra parada de linea de 30 minutos
        record_line_stop('TM', 30.0, 'Limpieza de prensa', 'Operario 1')

        # Obtiene el resumen consolidado de velocidad del turno
        summary = get_shift_speed_summary('TM')
        # Verifica promedio aritmetico de semilla: (1800 + 1920) / 2 = 1860.0
        self.assertEqual(summary['seed_avg_speed'], 1860.0)
        # Verifica horas efectivas: 8h - 0.5h = 7.5h
        self.assertEqual(summary['effective_hours'], 7.5)
        # Verifica produccion estimada: 1860 * 7.5 = 13950 kg
        self.assertEqual(summary['seed_estimated'], 13950.0)
        # Verifica rendimiento de expeller en linea: 900 / 1860 * 100 = 48.39%
        self.assertEqual(summary['expeller_yield_pct'], 48.39)
        # Verifica caudal masico horario estimado de aceite: 1860 - 900 = 960 kg/h
        self.assertEqual(summary['oil_estimated_speed'], 960.0)
        # Verifica produccion estimada de aceite del turno: 960 * 7.5 = 7200 kg
        self.assertEqual(summary['oil_estimated_shift_kg'], 7200.0)

    # Prueba 2: Flujo completo de cubicaje de tanques y silos
    def test_inventory_flow(self):
        # Obtiene tanques disponibles
        with get_db_connection() as conn:
            tk1 = conn.execute("SELECT id FROM equipment_tanks WHERE code = 'TK-01';").fetchone()
            silo1 = conn.execute("SELECT id FROM equipment_silos WHERE code = 'SILO-01';").fetchone()

        # Registra nivel en Tanque 1 (Horizontal D=2.50, L=6.50) a 1.25m (medio tanque)
        r_tank = record_tank_level(tk1['id'], 1.25, 'TM', 'Operario 1')
        self.assertGreater(r_tank['oil_kg'], 14000.0) # ~15.95 m3 * 920 = ~14677 kg

        # Registra cubicaje en Silo 1 (3 chapas, cono lleno, copete 0, PH=40)
        r_silo = record_silo_measurement(silo1['id'], 3.0, 0.0, 'lleno', 0.0, 'TM', 'Operario 1')
        self.assertGreater(r_silo['stock_kg'], 10000.0)

        # Consulta existencias consolidadas para el dashboard
        stocks = get_total_plant_stocks()
        self.assertGreater(stocks['total_oil_kg'], 0.0)
        self.assertGreater(stocks['total_seed_kg'], 0.0)

    # Prueba 3: Flujo de laboratorio y determinacion de parametros
    def test_laboratory_flow(self):
        raw_seed = {
            'moisture_initial_g': 10.0,
            'moisture_dry_g': 9.1,
            'fat_sample_g': 2.0,
            'fat_final_flask_g': 122.9,
            'fat_tare_flask_g': 122.0,
            'fm_sample_g': 50.0,
            'fm_impurities_g': 1.0
        }
        res = record_analysis('M-TEST-1', 'semilla', 'Tolva', 'TM', 'Analista', raw_seed)
        self.assertEqual(res['moisture_pct'], 9.0)
        self.assertEqual(res['fat_pct'], 45.0)
        self.assertEqual(res['foreign_matter_pct'], 2.0)

    # Prueba 4: Flujo de rendimiento industrial y balance de masa
    def test_yield_reconciliation_flow(self):
        # 20.000 kg semilla procesada, 8.000 kg aceite, 11.200 kg expeller, MG semilla 45%
        rec = reconcile_shift('TM', 20000.0, 11200.0, 8000.0, seed_fat_pct=45.0, expeller_fat_pct=10.0)
        # Rendimiento de extraccion masico: 8000 / 20000 * 100 = 40.0%
        self.assertEqual(rec['oil_yield_pct'], 40.0)
        # Rendimiento masico de expeller: 11200 / 20000 * 100 = 56.0%
        self.assertEqual(rec['expeller_yield_pct'], 56.0)
        # Eficiencia de recuperacion del aceite disponible: 8000 / 9000 * 100 = 88.89%
        self.assertEqual(rec['oil_recovery_pct'], 88.89)

    # Prueba 5: Cliente web HTTP y proteccion de rutas con login
    def test_web_routes_and_security(self):
        # Intento de entrar a / sin sesion debe redirigir a /login (codigo 302)
        resp = self.client.get('/')
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/login', resp.headers['Location'])

        # Iniciar sesion como admin
        login_resp = self.client.post('/login', data={'username': 'admin', 'pin': '1234'}, follow_redirects=True)
        self.assertEqual(login_resp.status_code, 200)
        self.assertIn(b'Tablero de Control', login_resp.data)

        # Acceder a las pantallas principales
        for route in ['/', '/production/', '/inventory/', '/laboratory/', '/yield/', '/config/', '/shifts']:
            r = self.client.get(route)
            self.assertEqual(r.status_code, 200, f"Fallo al acceder a {route}")

# Ejecuta las pruebas si es invocado directamente
if __name__ == '__main__':
    unittest.main()
