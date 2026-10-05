# Suite de pruebas unitarias automatizadas para identificacion de usuario que carga y filtrado de paradas en fecha en curso
import unittest # Importa modulo de testing
import sys # Importa sys
import os # Importa os

# Agrega directorio raiz al path de Python
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))) # Configura path

# Importa inicializador de base de datos y utilidades
from core.database import init_db, get_db_connection # Importa db
from run import app # Importa aplicacion Flask
from core.security import create_user # Importa creador de usuario
from core.migrations import apply_pending_migrations # Importa ejecutor de migraciones
from modules.production.service import ( # Importa servicios de produccion
    record_weighing, get_recent_weighings, record_line_stop, get_shift_stops, get_shift_speed_summary # Funciones de servicio
) # Cierre importacion
from core.timezone import get_plant_today_str # Importa funcion de fecha actual

# Clase de pruebas unitarias
class TestOperatorIdentificationAndStopsFilter(unittest.TestCase): # Define clase TestCase
    # Configuracion previa a cada prueba
    def setUp(self): # Metodo setUp
        init_db() # Inicializa o actualiza esquema de base de datos
        apply_pending_migrations() # Aplica todas las migraciones incluyendo v23
        app.config['TESTING'] = True # Habilita modo testing en Flask
        app.config['WTF_CSRF_ENABLED'] = False # Deshabilita proteccion CSRF para pruebas
        self.client = app.test_client() # Crea cliente de prueba HTTP
        self.plant_today = get_plant_today_str() # Obtiene la fecha de planta actual

        # Limpia registros de prueba para aislamiento
        with get_db_connection() as conn: # Abre conexion
            conn.execute("DELETE FROM production_weighings WHERE notes LIKE '%TEST_OP_%';") # Limpia pesadas test
            conn.execute("DELETE FROM line_stops WHERE reason LIKE '%TEST_OP_%';") # Limpia paradas test
            conn.commit() # Confirma limpieza

        # Asegura la existencia del usuario JAVIER en base de datos
        self.user_javier_id = None # Inicializa ID de Javier
        try: # Bloque de creacion
            self.user_javier_id = create_user('JAVIER', 'Javier Fernandez', 'admin_sistema', '11223344', 'JavierPass123!') # Crea o actualiza usuario
        except Exception: # Captura si ya existia
            pass # Continua

        # Si no devolvio ID directo, lo consulta
        if not self.user_javier_id: # Verifica ID
            with get_db_connection() as conn: # Abre conexion
                row = conn.execute("SELECT id FROM users WHERE LOWER(username) = 'javier' OR LOWER(full_name) LIKE '%javier%';").fetchone() # Consulta
                if row: # Si existe
                    self.user_javier_id = row['id'] # Asigna ID

    # Prueba 1: Identificacion automatica del usuario en sesion al registrar pesada por HTTP
    def test_add_weighing_identifies_logged_in_user(self): # Prueba de atribucion de pesada
        # Inicia sesion como JAVIER
        with self.client.session_transaction() as sess: # Transaccion de sesion
            sess['user_id'] = self.user_javier_id # Asigna ID de Javier
            sess['username'] = 'JAVIER' # Asigna username

        # Simula envio desde formulario que contenia el placeholder por defecto 'Operario de Linea 1'
        resp = self.client.post('/production/weighing', data={ # Realiza POST HTTP
            'sample_date': self.plant_today, # Fecha de hoy
            'shift_id': 'TM', # Turno manana
            'operator_name': 'Operario de Linea 1', # Placeholder por defecto del turno
            'sample_point': 'salida_expeller', # Punto de muestreo
            'gross_weight_kg': '12.5', # Peso bruto
            'tare_weight_kg': '0.5', # Tara
            'fill_time_seconds': '30.0', # Tiempo
            'line_status': 'operando', # Estado
            'notes': 'TEST_OP_IDENT_01' # Nota identificatoria
        }, follow_redirects=True) # Sigue redireccion

        # Verifica respuesta exitosa
        self.assertEqual(resp.status_code, 200) # Codigo 200

        # Consulta en base de datos la pesada registrada
        with get_db_connection() as conn: # Abre conexion
            w = conn.execute("SELECT * FROM production_weighings WHERE notes = 'TEST_OP_IDENT_01';").fetchone() # Consulta pesada
        self.assertIsNotNone(w) # Asegura existencia
        # Debe haberse atribuido al usuario logueado ('Javier Fernandez' o 'JAVIER'), NO a 'Operario de Linea 1'
        self.assertNotEqual(w['operator_name'], 'Operario de Linea 1') # Verifica que no es el placeholder
        self.assertTrue('Javier' in w['operator_name'] or 'JAVIER' in w['operator_name']) # Verifica atribucion a Javier

    # Prueba 2: Identificacion automatica del usuario en sesion al registrar parada por HTTP
    def test_add_stop_identifies_logged_in_user(self): # Prueba de atribucion de parada
        # Inicia sesion como JAVIER
        with self.client.session_transaction() as sess: # Transaccion de sesion
            sess['user_id'] = self.user_javier_id # Asigna ID
            sess['username'] = 'JAVIER' # Asigna username

        # Simula envio de parada con placeholder 'Operario de Linea 1'
        resp = self.client.post('/production/stop', data={ # Realiza POST HTTP
            'stop_date': self.plant_today, # Fecha actual
            'shift_id': 'TM', # Turno manana
            'operator_name': 'Operario de Linea 1', # Placeholder
            'duration_minutes': '25', # Duracion
            'reason': 'TEST_OP_STOP_01' # Motivo
        }, follow_redirects=True) # Sigue redireccion

        # Verifica respuesta exitosa
        self.assertEqual(resp.status_code, 200) # Codigo 200

        # Consulta en base de datos la parada registrada
        with get_db_connection() as conn: # Abre conexion
            s = conn.execute("SELECT * FROM line_stops WHERE reason = 'TEST_OP_STOP_01';").fetchone() # Consulta parada
        self.assertIsNotNone(s) # Asegura existencia
        # Debe haberse guardado con el usuario en sesion
        self.assertNotEqual(s['operator_name'], 'Operario de Linea 1') # No es placeholder
        self.assertTrue('Javier' in s['operator_name'] or 'JAVIER' in s['operator_name']) # Es Javier

    # Prueba 3: Filtrado de paradas por fecha en curso en la vista de produccion
    def test_production_view_filters_stops_by_current_date(self): # Prueba de filtrado por fecha en curso
        # Inicia sesion
        with self.client.session_transaction() as sess: # Sesion
            sess['user_id'] = self.user_javier_id # ID
            sess['username'] = 'JAVIER' # Username

        # Inserta una parada de una fecha pasada (ej. 2026-09-20)
        past_date = '2026-09-20' # Fecha pasada
        record_line_stop('TM', 45.0, 'TEST_OP_PAST_STOP', 'Operario', stop_date=past_date) # Graba parada pasada

        # Inserta una parada de la fecha actual
        record_line_stop('TM', 15.0, 'TEST_OP_TODAY_STOP', 'Javier', stop_date=self.plant_today) # Graba parada hoy

        # Consulta vista principal de produccion sin parametros (toma fecha en curso por defecto)
        resp = self.client.get('/production/') # GET produccion
        html = resp.data.decode('utf-8') # Decodifica HTML

        # La parada de hoy DEBE estar presente
        self.assertIn('TEST_OP_TODAY_STOP', html) # Parada de hoy visible
        # La parada historica NO debe estar presente en el listado de fecha en curso
        self.assertNotIn('TEST_OP_PAST_STOP', html) # Parada vieja oculta

        # Ahora solicita la vista con el parametro all_stops=1
        resp_all = self.client.get('/production/?all_stops=1') # GET con historial completo
        html_all = resp_all.data.decode('utf-8') # Decodifica HTML

        # En el historial completo DEBEN figurar ambas
        self.assertIn('TEST_OP_TODAY_STOP', html_all) # Hoy visible
        self.assertIn('TEST_OP_PAST_STOP', html_all) # Pasada visible

    # Prueba 4: Retro-atribucion de migracion v23 para muestras del 2/10
    def test_migration_23_backfills_october_2_samples(self): # Prueba migracion retroactiva
        # Inserta manualmente una pesada del 2026-10-02 con 'Operario de Linea 1'
        with get_db_connection() as conn: # Abre conexion
            cursor = conn.execute("""
                INSERT INTO production_weighings (
                    timestamp, shift_id, operator_name, sample_point,
                    gross_weight_kg, tare_weight_kg, net_weight_kg, fill_time_seconds,
                    line_status, speed_kg_h, proj_8h_kg, proj_24h_kg, notes, sample_date
                ) VALUES ('2026-10-02 10:47:00', 'TM', 'Operario de Linea 1', 'salida_expeller',
                          11.55, 0.0, 11.55, 60.0, 'operando', 693.0, 5544.0, 16632.0, 'TEST_OP_RETRO_OCT2', '2026-10-02');
            """) # Inserta fila simulada
            conn.commit() # Confirma

        # Ejecuta la funcion de callback de la migracion 23
        from core.migrations import backfill_production_operator_attribution # Importa funcion
        with get_db_connection() as conn: # Abre conexion
            backfill_production_operator_attribution(conn) # Ejecuta retro-atribucion

        # Verifica que la pesada ahora tenga el usuario real (Javier)
        with get_db_connection() as conn: # Abre conexion
            row = conn.execute("SELECT operator_name FROM production_weighings WHERE notes = 'TEST_OP_RETRO_OCT2';").fetchone() # Consulta
        self.assertIsNotNone(row) # Existe
        self.assertNotEqual(row['operator_name'], 'Operario de Linea 1') # Ya no es generico
        self.assertTrue('Javier' in row['operator_name'] or 'JAVIER' in row['operator_name']) # Actualizado a Javier

    # Prueba 5: Verificacion de migracion v27 (columna comments en line_stops)
    def test_migration_27_comments_column_exists(self):
        from core.migrations import apply_pending_migrations, get_applied_migration_versions
        apply_pending_migrations()
        applied = get_applied_migration_versions()
        self.assertIn(27, applied)
        with get_db_connection() as conn:
            columns = [col['name'] for col in conn.execute("PRAGMA table_info(line_stops);").fetchall()]
            self.assertIn('comments', columns)

# Ejecucion del test en ejecucion directa
if __name__ == '__main__': # Si se corre directamente
    unittest.main() # Ejecuta pruebas unitarias
