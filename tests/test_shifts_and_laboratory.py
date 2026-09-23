# Suite de pruebas automatizadas para los 4 turnos, Turno Central exclusivo, modulo de laboratorio y despacho de camiones cisterna
# Importa el modulo unittest para estructurar las pruebas
import unittest
# Importa sys para manipular el PYTHONPATH
import sys
# Importa os para manejo de rutas de archivos
import os
# Agrega la carpeta raiz del proyecto al path de Python
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Importa la aplicacion Flask desde run.py
from run import app
# Importa inicializador y conector de base de datos
from core.database import init_db, get_db_connection
# Importa servicios de configuracion y gestion de turnos
from modules.configuration.service import get_available_shifts, set_active_shift, get_active_shift
# Importa servicios de laboratorio y despacho de camiones de aceite
from modules.laboratory.service import record_analysis, record_oil_truck_dispatch, get_recent_oil_truck_dispatches
# Importa servicio de auditoria para verificar logs
from modules.admin.service import get_audit_logs

# Clase de casos de prueba para turnos, laboratorio y despacho de camiones
class TestShiftsAndLaboratory(unittest.TestCase):
    # Metodo de inicializacion que se ejecuta antes de cada prueba
    def setUp(self):
        # Configura Flask en modo pruebas
        app.config['TESTING'] = True
        # Desactiva la proteccion CSRF en entorno de pruebas
        app.config['WTF_CSRF_ENABLED'] = False
        # Instancia el cliente HTTP de pruebas
        self.client = app.test_client()
        # Asegura esquema de base de datos al dia
        init_db()
        # Abre conexion para limpiar registros de prueba
        with get_db_connection() as conn:
            # Elimina despachos de prueba previos
            conn.execute("DELETE FROM oil_truck_dispatches;")
            # Elimina analisis de laboratorio previos
            conn.execute("DELETE FROM lab_analyses;")
            # Elimina logs de auditoria de pruebas previas
            conn.execute("DELETE FROM audit_logs WHERE action IN ('CARGA_CAMION_ACEITE', 'CAMBIO_TURNO');")
            # Restablece clave y estado del operario
            conn.execute("UPDATE users SET pin = '1111', must_change_password = 0 WHERE username = 'operario';")
            # Restablece clave y estado del gerente
            conn.execute("UPDATE users SET pin = '3333', must_change_password = 0 WHERE username = 'gerente';")
            # Restablece clave y estado del admin
            conn.execute("UPDATE users SET pin = '1234', must_change_password = 0 WHERE username = 'admin';")
            # Confirma las transacciones en base de datos
            conn.commit()

    # Prueba 1: Verifica los 4 turnos y que Turno Central (TC) este restringido a admin_sistema
    def test_four_shifts_and_tc_admin_only(self):
        # Consulta los turnos disponibles para rol operario ('usuario')
        shifts_user = get_available_shifts(user_role='usuario')
        # Obtiene lista de identificadores para usuario
        ids_user = [s['id'] for s in shifts_user]
        # Verifica que contenga TM (Turno Manana)
        self.assertIn('TM', ids_user)
        # Verifica que contenga TT (Turno Tarde)
        self.assertIn('TT', ids_user)
        # Verifica que contenga TN (Turno Noche)
        self.assertIn('TN', ids_user)
        # Verifica que NO contenga TC (Turno Central) para operario
        self.assertNotIn('TC', ids_user)

        # Consulta los turnos disponibles para rol 'admin_sistema'
        shifts_admin = get_available_shifts(user_role='admin_sistema')
        # Obtiene lista de identificadores para admin
        ids_admin = [s['id'] for s in shifts_admin]
        # Verifica que contenga los 4 turnos para el administrador
        self.assertEqual(len(ids_admin), 4)
        # Verifica que contenga TC para el administrador
        self.assertIn('TC', ids_admin)

        # Intento de activar Turno Central como usuario comun debe arrojar PermissionError
        with self.assertRaises(PermissionError):
            # Llama a set_active_shift con rol no admin
            set_active_shift('TC', 'Operario 1', user_role='usuario')

        # Activacion de Turno Central como admin_sistema debe ser exitosa
        set_active_shift('TC', 'Admin Principal', user_role='admin_sistema')
        # Consulta el turno activo actual desde la base de datos
        active_tc = get_active_shift()
        # Verifica que el turno activo retornado sea TC
        self.assertEqual(active_tc['shift_id'], 'TC')

        # Activacion de turno regular TM como operario debe ser exitosa
        set_active_shift('TM', 'Operario 1', user_role='usuario')
        # Consulta el turno activo actual
        active_tm = get_active_shift()
        # Verifica que el turno activo sea TM
        self.assertEqual(active_tm['shift_id'], 'TM')

    # Prueba 2: Verifica proteccion en rutas web para cambio de turno
    def test_shift_web_route_security(self):
        # Inicia sesion como operario
        self.client.post('/login', data={'username': 'operario', 'pin': '1111'})
        # Intenta enviar POST para activar Turno Central (TC)
        r_post_user = self.client.post('/shifts', data={'shift_id': 'TC', 'operator_name': 'Operario Juan'}, follow_redirects=True)
        # Verifica que la respuesta reporte el mensaje de restriccion del turno central
        self.assertIn('El Turno Central (08:00 a 16:00) está reservado'.encode('utf-8'), r_post_user.data)

        # Cierra sesion
        self.client.get('/logout')
        # Inicia sesion como administrador del sistema
        self.client.post('/login', data={'username': 'admin', 'pin': '1234'})
        # Envia POST para activar Turno Central como admin
        r_post_admin = self.client.post('/shifts', data={'shift_id': 'TC', 'operator_name': 'Admin Jefe'}, follow_redirects=True)
        # Verifica que el turno se haya activado con exito
        self.assertIn('Guardia actualizada: TC a cargo de Admin Jefe.'.encode('utf-8'), r_post_admin.data)

    # Prueba 3: Registro de analisis de laboratorio con porcentajes directos y observaciones
    def test_lab_direct_percentage_and_observations(self):
        # Inicia sesion como operario
        self.client.post('/login', data={'username': 'operario', 'pin': '1111'})
        # Envia analisis de semilla con % de humedad, materia grasa y observaciones al endpoint /laboratory/add
        r_seed = self.client.post('/laboratory/add', data={
            'shift_id': 'TM',
            'operator_name': 'Operario Lab',
            'product': 'semilla',
            'sample_code': 'M-SEM-01',
            'sampling_point': 'Tolva de Ingreso',
            'direct_moisture_pct': '8.5',
            'direct_fat_pct': '43.2',
            'notes': 'Semilla de girasol lote 402 - buena calidad'
        }, follow_redirects=True)
        # Verifica que el registro sea exitoso
        self.assertEqual(r_seed.status_code, 200)
        # Verifica mensaje de confirmacion
        self.assertIn('guardado exitosamente'.encode('utf-8'), r_seed.data)

        # Envia analisis de expeller con humedad y grasa residual
        r_exp = self.client.post('/laboratory/add', data={
            'shift_id': 'TM',
            'operator_name': 'Operario Lab',
            'product': 'expeller',
            'sample_code': 'M-EXP-01',
            'sampling_point': 'Prensa 1',
            'direct_moisture_pct': '9.1',
            'direct_fat_pct': '7.8',
            'notes': 'Expeller de primera prensada uniforme'
        }, follow_redirects=True)
        # Verifica exito del registro
        self.assertEqual(r_exp.status_code, 200)

        # Envia analisis de aceite crudo con acidez directa
        r_oil = self.client.post('/laboratory/add', data={
            'shift_id': 'TM',
            'operator_name': 'Operario Lab',
            'product': 'aceite',
            'sample_code': 'M-OIL-01',
            'sampling_point': 'TK-01',
            'direct_acidity_pct': '1.35',
            'notes': 'Aceite decantado con acidez dentro de norma'
        }, follow_redirects=True)
        # Verifica exito del registro de aceite
        self.assertEqual(r_oil.status_code, 200)

        # Consulta la base de datos para verificar guardado fiel
        with get_db_connection() as conn:
            # Recupera los analisis insertados
            rows = conn.execute("SELECT product, moisture_pct, fat_pct, acidity_pct, notes FROM lab_analyses ORDER BY id ASC;").fetchall()
            # Verifica que haya 3 analisis registrados
            self.assertEqual(len(rows), 3)
            # Verifica valores del analisis de semilla
            self.assertEqual(rows[0]['product'], 'semilla')
            # Verifica humedad de semilla
            self.assertAlmostEqual(rows[0]['moisture_pct'], 8.5)
            # Verifica materia grasa de semilla
            self.assertAlmostEqual(rows[0]['fat_pct'], 43.2)
            # Verifica observacion guardada
            self.assertIn('lote 402', rows[0]['notes'])
            # Verifica acidez de aceite
            self.assertAlmostEqual(rows[2]['acidity_pct'], 1.35)

    # Prueba 4: Flujo completo de despacho e inspeccion de camion cisterna de aceite
    def test_oil_truck_dispatch_flow(self):
        # Inicia sesion como operario
        self.client.post('/login', data={'username': 'operario', 'pin': '1111'})
        # Envia formulario de carga y despacho de camion cisterna
        r_dispatch = self.client.post('/laboratory/truck-dispatch', data={
            'shift_id': 'TM',
            'operator_name': 'Operario Lab',
            'transport_status': 'Completado y Precintado',
            'seals_numbers': 'Valvula descarga: P-8801, Cúpula 1: P-8802, Cúpula 2: P-8803',
            'sample_delivered': 'SI',
            'truck_plate': 'AF789JK',
            'trailer_plate': 'AD123LM',
            'driver_name': 'Carlos Perez',
            'driver_dni': '30123456',
            'transport_company': 'Logistica Cerealera SA',
            'destination': 'Puerto Quequen',
            'tank_source_id': '1',
            'quantity_kg': '28980',
            'oil_temperature_c': '25.2',
            'oil_acidity_pct': '1.28',
            'notes': 'Cisterna higienizada, precintos verificados con chofer.'
        }, follow_redirects=True)
        # Verifica codigo de respuesta exitoso
        self.assertEqual(r_dispatch.status_code, 200)
        # Verifica mensaje flash en la interfaz
        self.assertIn('Despacho de camión cisterna'.encode('utf-8'), r_dispatch.data)

        # Consulta la lista de despachos mediante el servicio
        dispatches = get_recent_oil_truck_dispatches(limit=10)
        # Verifica que exista al menos 1 despacho registrado
        self.assertGreater(len(dispatches), 0)
        # Obtiene el primer despacho
        d = dispatches[0]
        # Verifica patente del chasis
        self.assertEqual(d['truck_plate'], 'AF789JK')
        # Verifica patente del acoplado
        self.assertEqual(d['trailer_plate'], 'AD123LM')
        # Verifica nombre del chofer
        self.assertEqual(d['driver_name'], 'Carlos Perez')
        # Verifica DNI del chofer
        self.assertEqual(d['driver_dni'], '30123456')
        # Verifica estado de transporte
        self.assertEqual(d['transport_status'], 'Completado y Precintado')
        # Verifica numeracion de precintos
        self.assertIn('P-8801', d['seals_numbers'])
        # Verifica indicador obligatorio de muestra entregada
        self.assertEqual(d['sample_delivered'], 'SI')
        # Verifica temperatura de aceite
        self.assertAlmostEqual(d['oil_temperature_c'], 25.2)
        # Verifica acidez de aceite
        self.assertAlmostEqual(d['oil_acidity_pct'], 1.28)

        # Verifica que se haya generado el registro de auditoria correspondiente
        logs = get_audit_logs(limit=20)
        # Busca log con la accion de despacho de camion de aceite
        truck_log = next((l for l in logs if l['action'] == 'CARGA_CAMION_ACEITE'), None)
        # Verifica que el log no sea nulo
        self.assertIsNotNone(truck_log)
        # Verifica que detalle la patente y el estado
        self.assertIn('AF789JK', truck_log['details'])

    # Prueba 5: Restriccion del Gerente (administrador) a solo lectura sin botones de carga
    def test_gerente_dashboard_read_only_and_cannot_load_data(self):
        # Inicia sesion con el rol 'administrador' (Gerente)
        self.client.post('/login', data={'username': 'gerente', 'pin': '3333'})
        # Accede al Dashboard ejecutivo
        r_dash = self.client.get('/')
        # Verifica codigo 200
        self.assertEqual(r_dash.status_code, 200)
        # Verifica insignia de solo lectura para el gerente
        self.assertIn('Monitoreo Ejecutivo (Solo Lectura)'.encode('utf-8'), r_dash.data)
        # Verifica que NO aparezca el boton de carga de pesada
        self.assertNotIn(b'+ Cargar Pesada', r_dash.data)
        # Verifica que NO aparezca el boton de cubicar nivel
        self.assertNotIn(b'+ Cubicar Nivel', r_dash.data)
        # Verifica que NO aparezca el boton de conciliar turno
        self.assertNotIn(b'Conciliar Turno', r_dash.data)
        # Verifica que exista el modal de historial de rendimiento
        self.assertIn(b'modal-yield-history', r_dash.data)
        # Verifica que exista el modal de historial de evolucion horaria de velocidad
        self.assertIn(b'modal-speed-history', r_dash.data)
        # Verifica que contenga la llamada JS para abrir el historial de rendimiento
        self.assertIn(b'openYieldHistoryModal()', r_dash.data)
        # Verifica que contenga la llamada JS para abrir el historial de velocidad
        self.assertIn(b'openSpeedHistoryModal()', r_dash.data)

        # Intento de registrar despacho de camion como gerente debe ser denegado
        r_post_dispatch = self.client.post('/laboratory/truck-dispatch', data={
            'shift_id': 'TM',
            'operator_name': 'Gerente',
            'transport_status': 'Apto para Carga',
            'seals_numbers': 'P-1',
            'sample_delivered': 'SI',
            'truck_plate': 'AA111BB',
            'driver_name': 'Intento Indebido'
        }, follow_redirects=True)
        # Debe redirigir y mostrar mensaje de falta de permisos
        self.assertIn('No posee permisos autorizados'.encode('utf-8'), r_post_dispatch.data)

        # Intento de registrar pesada como gerente debe ser denegado
        r_post_weighing = self.client.post('/production/weighing', data={
            'shift_id': 'TM',
            'operator_name': 'Gerente',
            'gross_kg': 30,
            'tare_kg': 0,
            'duration_seconds': 60
        }, follow_redirects=True)
        # Debe redirigir y mostrar mensaje de falta de permisos
        self.assertIn('No posee permisos autorizados'.encode('utf-8'), r_post_weighing.data)

# Permite ejecutar las pruebas directamente con python
if __name__ == '__main__':
    # Ejecuta el runner de pruebas de unittest
    unittest.main()
