# Modulo de pruebas automatizadas para el calculo automatico de eficiencia y simulador por juego de datos
# Importa el modulo estandar unittest para definir y ejecutar casos de prueba
import unittest
# Importa sys para manipular las rutas de importacion del interprete Python
import sys
# Importa os para operaciones con rutas del sistema operativo
import os
# Importa json para serializacion y deserializacion en pruebas de endpoints API
import json

# Agrega el directorio raiz del repositorio al PYTHONPATH
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Importa la aplicacion principal Flask configurada
from run import app
# Importa funciones de inicializacion y conexion a base de datos SQLite
from core.database import init_db, get_db_connection
# Importa las funciones del servicio de rendimiento a testear
from modules.yield_balance.service import (
    calculate_custom_efficiency,
    get_auto_efficiency_data,
    save_auto_reconciliation,
    get_recent_reconciliations
)
# Importa servicios de produccion y laboratorio para insertar datos de prueba
from modules.production.service import record_weighing
# Importa servicio de registro analitico de laboratorio
from modules.laboratory.service import record_analysis
# Importa servicio del dashboard ejecutivo
from modules.dashboard.service import get_executive_dashboard_data

# Clase principal de pruebas unitarias y de integracion para la funcionalidad de eficiencia
class TestAutoAndCustomYieldEfficiency(unittest.TestCase):
    # Metodo de configuracion que se ejecuta antes de cada caso de prueba
    def setUp(self):
        # Activa el modo de pruebas en la aplicacion Flask
        app.config['TESTING'] = True
        # Deshabilita CSRF en pruebas para simplificar peticiones HTTP
        app.config['WTF_CSRF_ENABLED'] = False
        # Inicializa el cliente HTTP simulado de Flask
        self.client = app.test_client()
        # Asegura la existencia y creacion de tablas en la base de datos
        init_db()
        # Abre conexion para limpiar tablas operativas y evitar contaminacion entre pruebas
        with get_db_connection() as conn:
            # Borra pesadas operativas de produccion
            conn.execute("DELETE FROM production_weighings;")
            # Borra paradas de planta
            conn.execute("DELETE FROM line_stops;")
            # Borra analisis de laboratorio
            conn.execute("DELETE FROM lab_analyses;")
            # Borra conciliaciones de rendimiento historicas
            conn.execute("DELETE FROM shift_reconciliations;")
            # Confirma los cambios de borrado en la base
            conn.commit()

    # Prueba de la logica pura de calculo personalizado (Modo 2)
    def test_calculate_custom_efficiency_balanced_scenario(self):
        # Ejecuta el calculo con un juego de datos nominal estandar
        kpis = calculate_custom_efficiency(
            seed_processed_kg=20000.0,
            expeller_produced_kg=12000.0,
            oil_produced_kg=7000.0,
            seed_fat_pct=45.0,
            expeller_fat_pct=9.0,
            waste_kg=500.0,
            moisture_loss_kg=500.0
        )
        # Verifica que el rendimiento de extraccion de aceite sea (7000 / 20000) * 100 = 35.0%
        self.assertEqual(kpis['oil_yield_pct'], 35.0)
        # Verifica que el rendimiento de expeller sea (12000 / 20000) * 100 = 60.0%
        self.assertEqual(kpis['expeller_yield_pct'], 60.0)
        # Grasa disponible: 20000 * 0.45 = 9000 kg. Eficiencia: (7000 / 9000) * 100 = 77.78%
        self.assertEqual(kpis['oil_recovery_pct'], 77.78)
        # Grasa residual en expeller: 12000 * 0.09 = 1080 kg
        self.assertEqual(kpis['residual_fat_kg'], 1080.0)
        # Salida total: 7000 + 12000 + 500 + 500 = 20000 kg
        self.assertEqual(kpis['total_output_kg'], 20000.0)
        # Desvio masico absoluto: 0 kg
        self.assertEqual(kpis['mass_difference_kg'], 0.0)
        # Porcentaje de desvio: 0.0%
        self.assertEqual(kpis['mass_diff_pct'], 0.0)

    # Prueba de resiliencia ante ceros o valores no validos
    def test_calculate_custom_efficiency_zero_seed(self):
        # Invoca la funcion pasando semilla en cero
        kpis = calculate_custom_efficiency(
            seed_processed_kg=0.0,
            expeller_produced_kg=0.0,
            oil_produced_kg=0.0
        )
        # Verifica que no lance ZeroDivisionError y retorne ceros seguros
        self.assertEqual(kpis['oil_yield_pct'], 0.0)
        # Verifica recuperacion en cero
        self.assertEqual(kpis['oil_recovery_pct'], 0.0)

    # Prueba de obtencion de eficiencia automatica con fallback cuando no hay datos
    def test_get_auto_efficiency_data_fallback(self):
        # Invoca obtencion automatica con base vacia
        auto_data = get_auto_efficiency_data(shift_id=None)
        # Verifica que se marque como fallback nominal
        self.assertTrue(auto_data['is_fallback'])
        # Verifica que contenga la descripcion de la base
        self.assertIn('nominal', auto_data['basis_description'].lower())
        # Verifica que los KPIs calculados contengan valores coherentes
        self.assertGreater(auto_data['calculated_kpis']['oil_recovery_pct'], 0.0)
        # Verifica que el rendimiento de expeller sea mayor a cero
        self.assertGreater(auto_data['calculated_kpis']['expeller_yield_pct'], 0.0)

    # Prueba de obtencion automatica basada en registros operativos reales
    def test_get_auto_efficiency_data_with_registered_plant_data(self):
        # Registra pesada de semilla: 30 kg en 60s = 1800 kg/h
        record_weighing('TM', 'Operador Turno', 'ingreso_semilla', 30.0, 0.0, 60.0, 'operando')
        # Registra pesada de expeller: 20 kg en 60s = 1200 kg/h
        record_weighing('TM', 'Operador Turno', 'salida_expeller', 20.0, 0.0, 60.0, 'operando')
        # Registra analisis de semilla con 44.5% materia grasa en formato dict
        record_analysis('M-SEM-01', 'semilla', 'ingreso', 'TM', 'Laboratorista', {'direct_fat_pct': 44.5})
        # Registra analisis de expeller con 9.5% materia grasa en formato dict
        record_analysis('M-EXP-01', 'expeller', 'salida', 'TM', 'Laboratorista', {'direct_fat_pct': 9.5}, press_number=2)

        # Obtiene los datos de eficiencia automatica para el turno TM
        auto_data = get_auto_efficiency_data(shift_id='TM')
        # Verifica que no sea fallback ya que existen registros reales
        self.assertFalse(auto_data['is_fallback'])
        # Verifica que los valores analiticos coincidan con los registrados
        self.assertEqual(auto_data['seed_fat_pct'], 44.5)
        # Verifica el porcentaje de expeller
        self.assertEqual(auto_data['expeller_fat_pct'], 9.5)
        # Verifica que la semilla estimada sea mayor a cero
        self.assertGreater(auto_data['seed_processed_kg'], 0.0)
        # Verifica que el aceite estimado sea mayor a cero
        self.assertGreater(auto_data['oil_produced_kg'], 0.0)
        # Verifica que la eficiencia de recuperacion calculada sea positiva
        self.assertGreater(auto_data['calculated_kpis']['oil_recovery_pct'], 0.0)

    # Prueba de persistencia de conciliacion automatica
    def test_save_auto_reconciliation(self):
        # Registra pesadas basicas
        record_weighing('TM', 'Operador Test', 'ingreso_semilla', 30.0, 0.0, 60.0, 'operando')
        # Guarda la conciliacion automatica
        saved = save_auto_reconciliation(shift_id='TM', notes='Conciliación de prueba automatizada')
        # Verifica que retorne el objeto guardado
        self.assertIsNotNone(saved)
        # Verifica el campo de notas
        self.assertEqual(saved['notes'], 'Conciliación de prueba automatizada')
        # Verifica que aparezca en el historial de conciliaciones
        recent = get_recent_reconciliations(limit=5)
        # Comprueba que la lista no este vacia
        self.assertGreaterEqual(len(recent), 1)

    # Prueba del endpoint API reactivo de simulacion (/yield/api/calculate-custom)
    def test_api_calculate_custom_endpoint(self):
        # Configura una sesion autorizada con rol gerencia
        with self.client.session_transaction() as sess:
            # Asigna identificador de usuario
            sess['user_id'] = 1
            # Asigna rol con permisos
            sess['role'] = 'gerencia'
            # Asigna nombre de usuario
            sess['username'] = 'gerente'
        # Envia una solicitud POST con carga JSON al endpoint
        response = self.client.post(
            '/yield/api/calculate-custom',
            data=json.dumps({
                'seed_processed_kg': 15000,
                'expeller_produced_kg': 9000,
                'oil_produced_kg': 5200,
                'seed_fat_pct': 44.0,
                'expeller_fat_pct': 8.5,
                'waste_kg': 200,
                'moisture_loss_kg': 600
            }),
            content_type='application/json'
        )
        # Verifica que la respuesta HTTP sea 200 OK
        self.assertEqual(response.status_code, 200)
        # Parsea los datos JSON recibidos
        data = json.loads(response.data.decode('utf-8'))
        # Verifica que los KPIs esten presentes en la respuesta
        self.assertIn('oil_yield_pct', data)
        # Verifica el calculo del rendimiento de aceite
        self.assertAlmostEqual(data['oil_yield_pct'], (5200 / 15000) * 100, places=1)
        # Verifica presencia de recuperacion de aceite
        self.assertIn('oil_recovery_pct', data)

    # Prueba del endpoint de guardado automatico con perfil administrador
    def test_save_auto_route_admin_access(self):
        # Configura una sesion simulada de administrador del sistema
        with self.client.session_transaction() as sess:
            # Asigna el ID del usuario administrador
            sess['user_id'] = 1
            # Asigna el rol correspondiente
            sess['role'] = 'admin_sistema'
            # Asigna nombre del usuario
            sess['username'] = 'admin_test'
            # Asigna nombre completo
            sess['full_name'] = 'Admin Pruebas'

        # Realiza peticion POST a la ruta de guardado automatico
        res = self.client.post('/yield/save-auto', data={'shift_id': 'TM', 'notes': 'Guardado auto admin'})
        # Verifica redireccion al listado de rendimiento
        self.assertEqual(res.status_code, 302)

    # Prueba de integracion del dashboard ejecutivo con el KPI de eficiencia automatico
    def test_dashboard_efficiency_kpi_presence(self):
        # Obtiene los datos del dashboard ejecutivo
        dash = get_executive_dashboard_data()
        # Verifica que la clave efficiency_kpi este presente en el diccionario del dashboard
        self.assertIn('efficiency_kpi', dash)
        # Verifica que contenga los campos minimos requeridos por la vista
        kpi = dash['efficiency_kpi']
        # Comprueba presencia de rendimiento de aceite
        self.assertIn('oil_yield_pct', kpi)
        # Comprueba presencia de recuperacion de aceite
        self.assertIn('oil_recovery_pct', kpi)
        # Comprueba presencia de insignia descriptiva
        self.assertIn('badge_text', kpi)

    # Prueba de renderizado HTTP de la vista de rendimiento (/yield/)
    def test_render_yield_page(self):
        # Configura la sesion con rol de administrador
        with self.client.session_transaction() as sess:
            # Asigna identificadores de sesion
            sess['user_id'] = 1
            # Asigna rol
            sess['role'] = 'admin_sistema'
            # Asigna nombre
            sess['username'] = 'admin'

        # Realiza la peticion GET a la vista
        res = self.client.get('/yield/')
        # Verifica que el codigo de estado sea 200
        self.assertEqual(res.status_code, 200)
        # Verifica que el HTML contenga el texto del Modo 1
        self.assertIn('Modo 1: Eficiencia Automática por Registros del Turno', res.data.decode('utf-8'))
        # Verifica que el HTML contenga el texto del Modo 2
        self.assertIn('Modo 2: Cálculo con Juego de Datos Ingresado', res.data.decode('utf-8'))

# Ejecucion directa de las pruebas si el script se corre como principal
if __name__ == '__main__':
    # Dispara la ejecucion de la suite de pruebas unitarias
    unittest.main()
