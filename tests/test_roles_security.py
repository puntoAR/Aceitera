# Suite de pruebas automatizadas para la seguridad, 3 niveles de roles, auto-recuperacion y auditoria
# Importa unittest para ejecucion estructurada de pruebas
import unittest
# Importa os y sys para anadir la raiz del proyecto al path
import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Importa la aplicacion Flask configurada
from run import app
# Importa inicializacion y conector de base de datos
from core.database import init_db, get_db_connection
# Importa servicios de seguridad y administracion
from core.security import authenticate_user, register_user, generate_otp_code, verify_otp_code, reset_user_password
from modules.admin.service import (
    get_pending_users, approve_user, admin_blanquear_password,
    get_audit_logs, get_system_errors, resolve_system_error,
    admin_create_user, admin_update_user
)
# Importa servicio de movimientos de inventario
from modules.inventory.service import record_inventory_movement
# Importa registrador de errores
from core.error_logger import log_error

# Clase de pruebas de control de acceso por roles y ciclo de vida de usuarios
class TestRolesAndSecurity(unittest.TestCase):
    # Metodo que se ejecuta antes de cada caso de prueba
    def setUp(self):
        # Habilita el modo testing en Flask
        app.config['TESTING'] = True
        app.config['WTF_CSRF_ENABLED'] = False
        # Crea el cliente de pruebas HTTP
        self.client = app.test_client()
        # Inicializa la base de datos
        init_db()
        # Limpia usuarios creados durante tests y asegura estado de claves de prueba
        with get_db_connection() as conn:
            # Elimina codigos de recuperacion asociados a usuarios que no son base
            conn.execute("DELETE FROM password_reset_codes WHERE user_id NOT IN (SELECT id FROM users WHERE username IN ('admin', 'gerente', 'operario', 'laboratorio', 'jroman'));")
            # Elimina usuarios secundarios creados en tests anteriores
            conn.execute("DELETE FROM users WHERE username NOT IN ('admin', 'gerente', 'operario', 'laboratorio', 'jroman');")
            # Asegura la existencia de operario
            conn.execute("INSERT OR IGNORE INTO users (username, full_name, role, pin, dni, phone, approval_status) VALUES ('operario', 'Operario de Planta', 'usuario', '1111', '30000000', '5492266000003', 'aprobado');")
            # Restablece clave predeterminada de operario
            conn.execute("UPDATE users SET pin = '1111', must_change_password = 0 WHERE username = 'operario';")
            # Restablece clave predeterminada de gerente
            conn.execute("UPDATE users SET pin = '3333', must_change_password = 0 WHERE username = 'gerente';")
            # Restablece clave predeterminada de admin
            conn.execute("UPDATE users SET pin = '1234', must_change_password = 0 WHERE username = 'admin';")
            # Restablece clave predeterminada de jroman
            conn.execute("UPDATE users SET pin = 'Admin2026*', must_change_password = 0 WHERE username = 'jroman';")
            # Confirma las operaciones
            conn.commit()

    # Prueba 1: Acceso restringido del rol 'usuario' (Carga, Cubicaje y Lab unicamente)
    def test_usuario_role_permissions(self):
        # Inicia sesion con el usuario 'operario' (rol: usuario, PIN: 1111)
        resp = self.client.post('/login', data={'username': 'operario', 'pin': '1111'}, follow_redirects=True)
        self.assertEqual(resp.status_code, 200)
        # Debe redirigir automaticamente al panel de produccion
        self.assertIn(b'Registrar Muestra de Bolsa', resp.data)

        # Puede acceder a produccion
        r_prod = self.client.get('/production/')
        self.assertEqual(r_prod.status_code, 200)

        # Puede acceder a cubicaje e inventario
        r_inv = self.client.get('/inventory/')
        self.assertEqual(r_inv.status_code, 200)

        # Puede acceder a laboratorio
        r_lab = self.client.get('/laboratory/')
        self.assertEqual(r_lab.status_code, 200)

        # NO puede acceder al Dashboard ejecutivo (debe ser redirigido a produccion)
        r_dash = self.client.get('/', follow_redirects=True)
        self.assertIn(b'No posee permisos autorizados', r_dash.data)

        # NO puede acceder al modulo de Rendimiento y Balance
        r_yield = self.client.get('/yield/', follow_redirects=True)
        self.assertIn(b'No posee permisos autorizados', r_yield.data)

        # NO puede acceder a Configuracion de equipos
        r_cfg = self.client.get('/config/', follow_redirects=True)
        self.assertIn(b'No posee permisos autorizados', r_cfg.data)

        # NO puede acceder a Administracion de usuarios
        r_adm = self.client.get('/admin/users', follow_redirects=True)
        self.assertIn(b'No posee permisos autorizados', r_adm.data)

    # Prueba 2: Acceso exclusivo del rol 'administrador' (Dashboard solamente)
    def test_administrador_role_permissions(self):
        # Inicia sesion con 'gerente' (rol: administrador, PIN: 3333)
        resp = self.client.post('/login', data={'username': 'gerente', 'pin': '3333'}, follow_redirects=True)
        self.assertEqual(resp.status_code, 200)
        # Redirige al Dashboard Ejecutivo
        self.assertIn(b'Tablero de Control', resp.data)

        # Puede acceder al Dashboard
        r_dash = self.client.get('/')
        self.assertEqual(r_dash.status_code, 200)

        # NO puede acceder a Carga de Produccion (redirige al dashboard)
        r_prod = self.client.get('/production/', follow_redirects=True)
        self.assertIn(b'No posee permisos autorizados', r_prod.data)

        # NO puede acceder a Cubicaje
        r_inv = self.client.get('/inventory/', follow_redirects=True)
        self.assertIn(b'No posee permisos autorizados', r_inv.data)

        # NO puede acceder a Laboratorio
        r_lab = self.client.get('/laboratory/', follow_redirects=True)
        self.assertIn(b'No posee permisos autorizados', r_lab.data)

        # Puede acceder a Rendimiento en modo solo lectura (sin formulario de carga)
        r_yield = self.client.get('/yield/')
        # Verifica codigo 200 de acceso permitido
        self.assertEqual(r_yield.status_code, 200)
        # Verifica insignia de solo lectura
        self.assertIn('Vista Ejecutiva de Rendimiento (Solo Lectura)'.encode('utf-8'), r_yield.data)
        # Verifica que NO tenga el formulario de conciliacion
        self.assertNotIn(b'Calcular y Conciliar Balance de Masa', r_yield.data)

        # NO puede registrar conciliacion de balance (POST bloqueado para Gerente)
        r_post_yield = self.client.post('/yield/reconcile', data={'shift_id': 'TM', 'seed_processed_kg': 1000}, follow_redirects=True)
        # Verifica redireccion y mensaje de falta de permisos
        self.assertIn(b'No posee permisos autorizados', r_post_yield.data)

        # NO puede acceder a Administracion de usuarios
        r_adm = self.client.get('/admin/users', follow_redirects=True)
        self.assertIn(b'No posee permisos autorizados', r_adm.data)

    # Prueba 3: Acceso total del rol 'admin_sistema'
    def test_admin_sistema_full_access(self):
        # Inicia sesion con 'admin' (rol: admin_sistema, PIN: 1234)
        resp = self.client.post('/login', data={'username': 'admin', 'pin': '1234'}, follow_redirects=True)
        self.assertEqual(resp.status_code, 200)

        # Verifica acceso permitido a todos los paneles
        rutas = ['/', '/production/', '/inventory/', '/laboratory/', '/yield/', '/config/', '/admin/users', '/admin/audit', '/admin/errors']
        for ruta in rutas:
            r = self.client.get(ruta)
            self.assertEqual(r.status_code, 200, f"Fallo al acceder a {ruta} como admin_sistema")

    # Prueba 4: Flujo completo de autoregistro, aprobacion y asignacion de rol
    def test_self_registration_and_approval_flow(self):
        # Registra un nuevo postulante
        dni_test = "45123987"
        r_reg = self.client.post('/register', data={
            'full_name': 'Carlos Operario Nuevo',
            'dni': dni_test,
            'phone': '2266987654',
            'password': 'password123',
            'password_confirm': 'password123'
        }, follow_redirects=True)
        self.assertEqual(r_reg.status_code, 200)
        self.assertIn(b'solicitud de registro', r_reg.data)

        # Intento de ingreso previo a aprobacion debe ser rechazado
        r_login_fail = self.client.post('/login', data={'username': dni_test, 'pin': 'password123'}, follow_redirects=True)
        self.assertIn(b'pendiente de aprobaci', r_login_fail.data)

        # Admin del sistema aprueba la solicitud
        pending = get_pending_users()
        user_pending = next((u for u in pending if u['dni'] == dni_test), None)
        self.assertIsNotNone(user_pending)
        approve_user(user_pending['id'], role='usuario')

        # Ahora el usuario puede ingresar correctamente
        r_login_ok = self.client.post('/login', data={'username': dni_test, 'pin': 'password123'}, follow_redirects=True)
        self.assertEqual(r_login_ok.status_code, 200)
        # Redirigido a produccion por rol 'usuario'
        self.assertIn(b'Registrar Muestra de Bolsa', r_login_ok.data)

    # Prueba 5: Recuperacion automatica de contrasena con OTP y cambio forzado de clave provisoria
    def test_password_recovery_and_mandatory_change(self):
        # Solicita recuperacion por DNI
        r_forgot = self.client.post('/forgot-password', data={'identifier': 'operario'}, follow_redirects=True)
        self.assertEqual(r_forgot.status_code, 200)
        self.assertIn(b'Validar C', r_forgot.data)

        # Obtiene el codigo OTP desde la base de datos para simular lectura de WhatsApp
        with get_db_connection() as conn:
            user = conn.execute("SELECT id FROM users WHERE username = 'operario';").fetchone()
            code_row = conn.execute("SELECT code FROM password_reset_codes WHERE user_id = ? AND used = 0 ORDER BY id DESC LIMIT 1;", (user['id'],)).fetchone()
            otp_code = code_row['code']

        # Envia el codigo OTP de 6 digitos
        r_verify = self.client.post('/verify-reset-code', data={'code': otp_code}, follow_redirects=True)
        self.assertEqual(r_verify.status_code, 200)
        self.assertIn(b'Contrase\xc3\xb1a Generada', r_verify.data)

        # Consulta la nueva clave provisoria asignada
        with get_db_connection() as conn:
            u_updated = conn.execute("SELECT pin, must_change_password FROM users WHERE id = ?;", (user['id'],)).fetchone()
            temp_pwd = u_updated['pin']
            self.assertEqual(u_updated['must_change_password'], 1)

        # Intenta iniciar sesion con la clave provisoria
        r_login_temp = self.client.post('/login', data={'username': 'operario', 'pin': temp_pwd}, follow_redirects=True)
        # Debe interceptar y redirigir a cambio obligatorio de clave
        self.assertIn(b'Actualizar Contrase', r_login_temp.data)

        # Intento de navegar a otra ruta antes de cambiar la clave debe ser interceptado
        r_nav = self.client.get('/production/', follow_redirects=True)
        self.assertIn(b'Actualizar Contrase', r_nav.data)

        # Realiza el cambio de clave definitivo
        r_change = self.client.post('/change-password', data={
            'current_pin': temp_pwd,
            'new_pin': '1111',
            'confirm_pin': '1111'
        }, follow_redirects=True)
        self.assertEqual(r_change.status_code, 200)
        self.assertIn(b'Registrar Muestra de Bolsa', r_change.data)

        # Comprueba que el flag de cambio obligatorio volvio a 0
        with get_db_connection() as conn:
            u_final = conn.execute("SELECT must_change_password FROM users WHERE id = ?;", (user['id'],)).fetchone()
            self.assertEqual(u_final['must_change_password'], 0)

    # Prueba 6: Blanqueo de contrasena directo por el Administrador del Sistema
    def test_admin_blanquear_password(self):
        with get_db_connection() as conn:
            u = conn.execute("SELECT id FROM users WHERE username = 'operario';").fetchone()
            user_id = u['id']

        # Blanqueo directo
        new_pwd = admin_blanquear_password(user_id)
        self.assertTrue(new_pwd.startswith('Ace-'))

        with get_db_connection() as conn:
            u_check = conn.execute("SELECT pin, must_change_password FROM users WHERE id = ?;", (user_id,)).fetchone()
            self.assertEqual(u_check['pin'], new_pwd)
            self.assertEqual(u_check['must_change_password'], 1)

        # Restaura la clave original para no afectar otras pruebas
        reset_user_password(user_id, '1111', must_change=False)

    # Prueba 7: Registro de auditoria y trazabilidad
    def test_audit_logs_recording(self):
        logs = get_audit_logs(limit=50)
        self.assertGreater(len(logs), 0)
        # Verifica que las categorias existan
        cats = [l['category'] for l in logs]
        self.assertTrue(any(c in ['AUTH', 'PRODUCCION', 'INVENTARIO', 'USUARIOS', 'SISTEMA'] for c in cats))

    # Prueba 8: Registro y resolucion de excepciones de sistema con origen exacto
    def test_system_error_logging_and_resolution(self):
        # Registra un error de prueba
        try:
            # Provoca excepcion inducida para probar la captura
            raise RuntimeError("Error simulado de pruebas unitarias")
        except Exception as e:
            # Registra la excepcion con la funcion central
            log_error("TEST_UNIT", "Fallo inducido para verificar trazabilidad", e)

        # Verifica que figure en la tabla de errores
        errors = get_system_errors(limit=10)
        # Busca el error inducido por mensaje
        target = next((err for err in errors if "Fallo inducido" in err['error_message']), None)
        # Comprueba que el incidente fue registrado
        self.assertIsNotNone(target)
        # Comprueba que se encuentre inicialmente pendiente
        self.assertEqual(target['resolved'], 0)
        # Comprueba que se haya capturado el archivo de origen
        self.assertIsNotNone(target.get('origin_file'))
        # Comprueba que contenga el nombre del archivo de prueba
        self.assertIn('test_roles_security.py', target['origin_file'])
        # Comprueba que se haya capturado el numero de linea
        self.assertIsNotNone(target.get('origin_line'))
        # Comprueba que el numero de linea sea mayor a cero
        self.assertGreater(target['origin_line'], 0)
        # Comprueba que se haya capturado el nombre de la funcion
        self.assertEqual(target.get('origin_func'), 'test_system_error_logging_and_resolution')

        # Inicia sesion como admin_sistema para consultar la vista web
        self.client.post('/login', data={'username': 'admin', 'pin': '1234'}, follow_redirects=True)
        # Consulta la pantalla de errores
        resp_errors = self.client.get('/admin/errors')
        # Verifica respuesta HTTP exitosa
        self.assertEqual(resp_errors.status_code, 200)
        # Decodifica el HTML resultante
        html_errors = resp_errors.data.decode('utf-8')
        # Comprueba que el archivo figure en la vista
        self.assertIn('test_roles_security.py', html_errors)
        # Comprueba que el numero de linea figure en la vista
        self.assertIn(str(target['origin_line']), html_errors)
        # Comprueba que el boton de copiado de traza este presente
        self.assertIn('Copiar Traza', html_errors)

        # Resuelve el incidente
        resolve_system_error(target['id'])
        # Consulta nuevamente la lista de incidentes
        errors_after = get_system_errors(limit=10)
        # Localiza el incidente actualizado
        target_after = next((err for err in errors_after if err['id'] == target['id']), None)
        # Comprueba que el estado sea resuelto
        self.assertEqual(target_after['resolved'], 1)

    # Prueba 9: Creacion directa de perfiles de usuario por el Administrador con nombres comunes
    def test_admin_create_user_custom_profile(self):
        # 1. Inicia sesion como Administrador del Sistema
        self.client.post('/login', data={'username': 'admin', 'pin': '1234'}, follow_redirects=True)

        # 2. Crea un perfil gerencial con nombre comun 'jmartinez'
        resp_crear_gerente = self.client.post('/admin/users/create', data={
            'username': 'jmartinez',
            'full_name': 'Juan Martínez (Gerencia)',
            'dni': '32111222',
            'phone': '2266459999',
            'password': 'ClaveGerente2026!',
            'role': 'administrador',
            'must_change': '0'
        }, follow_redirects=True)
        self.assertEqual(resp_crear_gerente.status_code, 200)
        self.assertIn(b'jmartinez', resp_crear_gerente.data)

        # 3. Crea un perfil operativo con nombre comun 'carlos_linea'
        resp_crear_operario = self.client.post('/admin/users/create', data={
            'username': 'carlos_linea',
            'full_name': 'Carlos Planta',
            'dni': '33444555',
            'phone': '2266458888',
            'password': 'ClaveOperario123!',
            'role': 'usuario',
            'must_change': '0'
        }, follow_redirects=True)
        self.assertEqual(resp_crear_operario.status_code, 200)
        self.assertIn(b'carlos_linea', resp_crear_operario.data)

        # 4. Intento de duplicar nombre de usuario debe ser rechazado
        resp_duplicado = self.client.post('/admin/users/create', data={
            'username': 'jmartinez',
            'full_name': 'Otro Juan',
            'dni': '99999999',
            'password': 'otra_clave_123',
            'role': 'usuario'
        }, follow_redirects=True)
        self.assertEqual(resp_duplicado.status_code, 200)
        self.assertIn(b'ya est\xc3\xa1 en uso', resp_duplicado.data)

        # 5. Cierra sesion de administrador
        self.client.get('/logout', follow_redirects=True)

        # 6. Prueba inicio de sesion con el nuevo usuario 'jmartinez'
        resp_login_gerente = self.client.post('/login', data={'username': 'jmartinez', 'pin': 'ClaveGerente2026!'}, follow_redirects=True)
        self.assertEqual(resp_login_gerente.status_code, 200)
        # Verifica acceso al Dashboard Ejecutivo por rol administrador
        self.assertIn(b'Dashboard Ejecutivo', resp_login_gerente.data)

        # 7. Cierra sesion gerente
        self.client.get('/logout', follow_redirects=True)

        # 8. Prueba inicio de sesion con el nuevo usuario 'carlos_linea'
        resp_login_operario = self.client.post('/login', data={'username': 'carlos_linea', 'pin': 'ClaveOperario123!'}, follow_redirects=True)
        self.assertEqual(resp_login_operario.status_code, 200)
        # Verifica acceso al panel operativo por rol usuario
        self.assertIn(b'Registrar Muestra de Bolsa', resp_login_operario.data)

    # Prueba 10: Disponibilidad de rutas y encabezados PWA (manifest y service worker)
    def test_pwa_routes(self):
        # Consulta el manifiesto de la aplicacion
        r_manifest = self.client.get('/manifest.json')
        self.assertEqual(r_manifest.status_code, 200)
        self.assertIn(b'Aceitera', r_manifest.data)
        self.assertIn(b'standalone', r_manifest.data)

        # Consulta el Service Worker
        r_sw = self.client.get('/sw.js')
        self.assertEqual(r_sw.status_code, 200)
        self.assertEqual(r_sw.headers.get('Service-Worker-Allowed'), '/')
        self.assertIn(b'aceitera-pwa', r_sw.data)

    # Prueba 11: Validacion de asignacion de rol 'gerencia' y visualizacion de etiqueta
    def test_gerencia_role_assignment_and_display(self):
        # Inicia sesion como admin_sistema
        self.client.post('/login', data={'username': 'admin', 'pin': '1234'}, follow_redirects=True)

        # Crea un nuevo usuario con rol directo 'gerencia'
        resp_create = self.client.post('/admin/users/create', data={
            'username': 'gerente_planta',
            'full_name': 'Mariana Dirección',
            'dni': '28999888',
            'phone': '2266457777',
            'password': 'ClaveGerencia2026!',
            'role': 'gerencia',
            'must_change': '0'
        }, follow_redirects=True)
        self.assertEqual(resp_create.status_code, 200)

        # Consulta la pantalla de administracion de usuarios y comprueba que figure Gerencia
        resp_admin = self.client.get('/admin/users')
        self.assertIn('Gerencia', resp_admin.data.decode('utf-8'))

        # Cierra sesion admin
        self.client.get('/logout', follow_redirects=True)

        # Inicia sesion con el nuevo usuario de gerencia
        resp_login = self.client.post('/login', data={'username': 'gerente_planta', 'pin': 'ClaveGerencia2026!'}, follow_redirects=True)
        self.assertEqual(resp_login.status_code, 200)
        html_content = resp_login.data.decode('utf-8')
        # Verifica que la insignia contenga (Gerencia) y el menu contenga el boton Dashboard Ejecutivo exactamente una vez
        self.assertIn('Gerencia', html_content)
        self.assertEqual(html_content.count('Dashboard Ejecutivo</a>'), 1, "Dashboard Ejecutivo no debe figurar duplicado en la barra de navegación")

    # Prueba 11: Verificacion del adaptador Turso Cloud SQLite y estado de almacenamiento
    def test_turso_adapter_and_storage_status(self):
        # Importa clases del adaptador Turso
        from core.database import TursoRow, TursoCursor, TursoConnection
        # Verifica comportamiento del objeto TursoRow
        cols = ['id', 'username', 'role']
        # Valores simulados de fila
        vals = [10, 'carlos_planta', 'usuario']
        # Instancia objeto TursoRow
        row = TursoRow(cols, vals)
        # Comprueba acceso por nombre de columna
        self.assertEqual(row['username'], 'carlos_planta')
        # Comprueba acceso por indice numerico
        self.assertEqual(row[0], 10)
        # Comprueba acceso a rol por indice
        self.assertEqual(row[2], 'usuario')
        # Comprueba conversion a diccionario
        self.assertEqual(dict(row), {'id': 10, 'username': 'carlos_planta', 'role': 'usuario'})

        # Verifica comportamiento del cursor TursoCursor
        cursor = TursoCursor(cols, [vals, [11, 'mariana_gerencia', 'gerencia']], last_insert_rowid=99)
        # Comprueba lastrowid
        self.assertEqual(cursor.lastrowid, 99)
        # Comprueba fetchone
        first_row = cursor.fetchone()
        self.assertEqual(first_row['username'], 'carlos_planta')
        # Comprueba fetchall restante
        remaining = cursor.fetchall()
        self.assertEqual(len(remaining), 1)
        self.assertEqual(remaining[0]['username'], 'mariana_gerencia')

        # Verifica serializacion de parametros en TursoConnection
        turso = TursoConnection("libsql://aceitera-test.turso.io", "test-token")
        # Comprueba URL del pipeline v2
        self.assertEqual(turso.pipeline_url, "https://aceitera-test.turso.io/v2/pipeline")
        # Comprueba serializacion de valor nulo
        self.assertEqual(turso._to_turso_arg(None), {"type": "null"})
        # Comprueba serializacion de valor entero
        self.assertEqual(turso._to_turso_arg(42), {"type": "integer", "value": "42"})
        # Comprueba serializacion de valor flotante
        self.assertEqual(turso._to_turso_arg(3.14), {"type": "float", "value": 3.14})
        # Comprueba serializacion de cadena de texto
        self.assertEqual(turso._to_turso_arg("test"), {"type": "text", "value": "test"})
        # Comprueba que TursoConnection provea metodo cursor() compatible con sqlite3
        cur_stmt = turso.cursor()
        # Verifica que el cursor no sea nulo
        self.assertIsNotNone(cur_stmt)
        # Comprueba que el cursor posea metodo execute
        self.assertTrue(callable(getattr(cur_stmt, 'execute', None)))
        # Comprueba que el cursor posea metodo executemany
        self.assertTrue(callable(getattr(cur_stmt, 'executemany', None)))
        # Comprueba que el cursor posea metodo fetchone
        self.assertTrue(callable(getattr(cur_stmt, 'fetchone', None)))
        # Comprueba que el cursor posea metodo fetchall
        self.assertTrue(callable(getattr(cur_stmt, 'fetchall', None)))

    # Prueba 12: Registro de movimiento de inventario sin errores de marcadores SQL
    def test_inventory_movement_flow_and_no_error(self):
        # Inicia sesion como usuario operario con su PIN valido (1111)
        self.client.post('/login', data={'username': 'operario', 'pin': '1111'}, follow_redirects=True)

        # Ejecuta el registro de un movimiento de ingreso de semilla mediante HTTP POST
        resp = self.client.post('/inventory/movement', data={
            'product': 'semilla',
            'movement_type': 'ingreso',
            'origin': 'Camión Planta 101',
            'destination': 'Silo 1 Semilla Girasol',
            'quantity_kg': '28500.0',
            'document_ref': 'REM-2026-999',
            'shift_id': 'TM',
            'operator_name': 'Operario Guardia',
            'notes': 'Descarga completa de girasol'
        }, follow_redirects=True)
        # Comprueba que la redireccion haya sido exitosa con codigo 200
        self.assertEqual(resp.status_code, 200)
        # Decodifica el HTML resultante
        html_resp = resp.data.decode('utf-8')
        # Verifica mensaje flash de exito
        self.assertIn('registrado exitosamente', html_resp)
        # Verifica que no haya mensaje de error
        self.assertNotIn('Error al registrar movimiento', html_resp)

        # Comprueba la persistencia directa en la base de datos
        with get_db_connection() as conn:
            # Consulta el registro insertado
            row = conn.execute("SELECT * FROM inventory_movements WHERE document_ref = 'REM-2026-999';").fetchone()
            # Verifica que el registro exista
            self.assertIsNotNone(row)
            # Verifica producto
            self.assertEqual(row['product'], 'semilla')
            # Verifica tipo de movimiento
            self.assertEqual(row['movement_type'], 'ingreso')
            # Verifica cantidad en kg
            self.assertEqual(row['quantity_kg'], 28500.0)
            # Verifica destino
            self.assertEqual(row['destination'], 'Silo 1 Semilla Girasol')

    # Prueba 13: Pagina Acerca de con logo transparente, contacto mailto y navegacion completa
    def test_about_page_and_navigation(self):
        # 1. Acceso publico a la ruta /about sin necesidad de inicio de sesion
        resp = self.client.get('/about')
        self.assertEqual(resp.status_code, 200)
        html = resp.data.decode('utf-8')

        # Verifica elementos institucionales requeridos (exclusivos de la empresa puntoAR)
        self.assertIn('Acerca de puntoAR', html)
        self.assertNotIn('logo_full.png', html)
        self.assertNotIn('BioBalcarce Aceite', html)
        self.assertNotIn('BioBalcarce &bull;', html)
        self.assertNotIn('Diseño y Desarrollo de Software', html)
        self.assertIn('CONTACTO Y SOPORTE', html)
        self.assertNotIn('de la empresa', html)
        self.assertIn('logo_puntoar_dark.png', html)
        self.assertIn('El valor de estar presentes', html)
        # Verifica enlace directo mailto para envio de correos
        self.assertIn('mailto:empresa.puntoar@gmail.com', html)
        self.assertIn('empresa.puntoar@gmail.com', html)

        # 2. Verifica presencia de enlace Acerca de en la pantalla de Login
        resp_login = self.client.get('/login')
        self.assertEqual(resp_login.status_code, 200)
        html_login = resp_login.data.decode('utf-8')
        self.assertIn('/about', html_login)
        self.assertIn('logo_puntoar', html_login)

        # 3. Verifica presencia de Acerca de en el navbar y footer estando autenticado
        self.client.post('/login', data={'username': 'admin', 'pin': '1234'}, follow_redirects=True)
        resp_dash = self.client.get('/')
        self.assertEqual(resp_dash.status_code, 200)
        html_dash = resp_dash.data.decode('utf-8')
        # Verifica enlace en barra de navegacion
        self.assertIn('ℹ️ Acerca de', html_dash)
        self.assertIn('/about', html_dash)
        # Verifica enlace en pie de pagina
        self.assertIn('Aceitera - Sistema Industrial de Control de Proceso', html_dash)

    # Prueba 13: Compatibilidad y arranque serverless en Vercel
    def test_vercel_serverless_handler_and_config(self):
        # Importa el modulo de entrada de Vercel
        import api.index
        # Verifica que el objeto handler este definido y sea ejecutable
        self.assertTrue(callable(api.index.handler))
        # Verifica que las carpetas requeridas de actualizacion esten definidas en config
        import config
        # Comprueba existencia de UPDATES_DIR
        self.assertTrue(hasattr(config, 'UPDATES_DIR'))
        # Comprueba existencia de PENDING_UPDATES_DIR
        self.assertTrue(hasattr(config, 'PENDING_UPDATES_DIR'))
        # Comprueba existencia de APPLIED_UPDATES_DIR
        self.assertTrue(hasattr(config, 'APPLIED_UPDATES_DIR'))
        # Ejecuta una peticion al endpoint de login a traves del cliente de prueba
        test_client = api.index.app.test_client()
        # Obtiene la respuesta de la pantalla de login
        response = test_client.get('/login')
        # Verifica que el codigo de estado HTTP sea 200 OK
        self.assertEqual(response.status_code, 200)

    # Prueba 14: Edicion de perfil de usuario y validaciones de duplicados por el Administrador
    def test_admin_update_user_and_routes(self):
        # Inicia sesion con usuario administrador
        self.client.post('/login', data={'username': 'admin', 'pin': '1234'}, follow_redirects=True)
        # Crea un usuario dedicado para probar la edicion de perfil
        with get_db_connection() as conn:
            # Elimina registros previos si existieran
            conn.execute("DELETE FROM users WHERE username IN ('temp_user_edit', 'cschisano');")
            # Inserta el usuario de prueba
            cur = conn.execute("""
                INSERT INTO users (username, full_name, dni, pin, role, approval_status, must_change_password, is_active)
                VALUES ('temp_user_edit', 'Temp Name', '99887766', '1234', 'usuario', 'aprobado', 0, 1);
            """)
            # Guarda identificador asignado
            user_id = cur.lastrowid
            # Confirma la insercion
            conn.commit()

        # Actualiza el perfil asignando nombre de usuario cschisano y DNI
        res = admin_update_user(user_id, 'cschisano', 'Cristian Schisano', '36442025', '2266123456', 'usuario')
        # Verifica que la actualizacion haya retornado True
        self.assertTrue(res)

        # Comprueba en base de datos que los campos fueron modificados
        with get_db_connection() as conn:
            # Consulta el registro actualizado
            u_updated = conn.execute("SELECT username, full_name, dni, phone, role FROM users WHERE id = ?;", (user_id,)).fetchone()
            # Verifica que el username sea cschisano
            self.assertEqual(u_updated['username'], 'cschisano')
            # Verifica que el full_name sea Cristian Schisano
            self.assertEqual(u_updated['full_name'], 'Cristian Schisano')
            # Verifica que el DNI sea 36442025
            self.assertEqual(u_updated['dni'], '36442025')
            # Verifica el telefono
            self.assertEqual(u_updated['phone'], '2266123456')

        # Comprueba que intentar asignar el mismo username cschisano a otro usuario lance ValueError
        with get_db_connection() as conn:
            # Obtiene el id del gerente
            g_id = conn.execute("SELECT id FROM users WHERE username = 'gerente';").fetchone()['id']
        # Intenta usar username cschisano en otro id y espera ValueError
        with self.assertRaises(ValueError):
            # Ejecuta actualizacion conflictiva
            admin_update_user(g_id, 'cschisano', 'Otro Nombre', '99999999', '111', 'gerencia')

        # Comprueba que intentar asignar el mismo DNI 36442025 a otro usuario lance ValueError
        with self.assertRaises(ValueError):
            # Ejecuta actualizacion conflictiva de DNI
            admin_update_user(g_id, 'gerente_alt', 'Otro Nombre', '36442025', '111', 'gerencia')

        # Prueba endpoint web POST /admin/users/edit/<id>
        resp_post = self.client.post(f'/admin/users/edit/{user_id}', data={
            # Envia username confirmado
            'username': 'cschisano',
            # Envia nombre completo
            'full_name': 'Cristian Schisano',
            # Envia DNI
            'dni': '36442025',
            # Envia nuevo telefono
            'phone': '2266998877',
            # Envia rol
            'role': 'usuario'
        }, follow_redirects=True)
        # Verifica status HTTP 200 tras redireccion
        self.assertEqual(resp_post.status_code, 200)
        # Verifica mensaje flash de exito
        self.assertIn('actualizado con', resp_post.data.decode('utf-8'))

        # Limpia el usuario de prueba al finalizar
        with get_db_connection() as conn:
            # Elimina el registro de prueba
            conn.execute("DELETE FROM users WHERE id = ?;", (user_id,))
            # Confirma borrado
            conn.commit()

    # Prueba 15: Asignacion de contrasena personalizada y blanqueo interactivo
    def test_admin_blanquear_custom_password_and_route(self):
        # Crea un usuario dedicado para probar asignacion de clave
        with get_db_connection() as conn:
            # Elimina registros previos si existieran
            conn.execute("DELETE FROM users WHERE username = 'user_pwd_test';")
            # Inserta usuario de prueba
            cur = conn.execute("""
                INSERT INTO users (username, full_name, dni, pin, role, approval_status, must_change_password, is_active)
                VALUES ('user_pwd_test', 'User Clave Test', '88776655', 'original_pin', 'usuario', 'aprobado', 0, 1);
            """)
            # Guarda identificador
            user_id = cur.lastrowid
            # Confirma la insercion
            conn.commit()

        # Asigna una contrasena personalizada especifica con cambio obligatorio deshabilitado
        pwd = admin_blanquear_password(user_id, custom_password='clave_personalizada', must_change=False)
        # Verifica que la clave devuelta sea la personalizada
        self.assertEqual(pwd, 'clave_personalizada')

        # Verifica en la base de datos el pin y el flag must_change_password
        with get_db_connection() as conn:
            # Consulta el registro
            u_check = conn.execute("SELECT pin, must_change_password FROM users WHERE id = ?;", (user_id,)).fetchone()
            # Verifica el pin
            self.assertEqual(u_check['pin'], 'clave_personalizada')
            # Verifica que no exige cambio obligatorio
            self.assertEqual(u_check['must_change_password'], 0)

        # Inicia sesion como admin para probar endpoint web
        self.client.post('/login', data={'username': 'admin', 'pin': '1234'}, follow_redirects=True)
        # Envia solicitud POST de asignacion de clave personalizada con cambio forzoso
        resp = self.client.post(f'/admin/users/reset-password/{user_id}', data={
            # Clave provisoria elegida por el admin
            'custom_password': 'clave_provisoria_123',
            # Exige cambio obligatorio
            'must_change': '1'
        }, follow_redirects=True)
        # Verifica codigo HTTP 200
        self.assertEqual(resp.status_code, 200)
        # Verifica mensaje flash y banner de credenciales en el HTML
        html = resp.data.decode('utf-8')
        # Verifica presencia del banner de credenciales
        self.assertIn('Credenciales de Acceso Actualizadas', html)
        # Verifica presencia de la clave asignada
        self.assertIn('clave_provisoria_123', html)

        # Limpia el usuario de prueba al finalizar
        with get_db_connection() as conn:
            # Elimina registro de prueba
            conn.execute("DELETE FROM users WHERE id = ?;", (user_id,))
            # Confirma eliminacion
            conn.commit()

    # Prueba 16: Autenticacion inteligente, case-insensitivity y resolucion automatica de alias
    def test_smart_authentication_and_alias_resolution(self):
        # Inserta un usuario con username igual a su DNI numerico y nombre Cristian Schisano
        with get_db_connection() as conn:
            # Elimina si existiera previamente
            conn.execute("DELETE FROM users WHERE dni = '36442025';")
            # Inserta el registro de prueba simulando registro inicial
            conn.execute("""
                INSERT INTO users (username, full_name, dni, pin, role, approval_status, must_change_password, is_active)
                VALUES ('36442025', 'Cristian Schisano', '36442025', 'clave_test', 'usuario', 'aprobado', 0, 1);
            """)
            # Confirma insercion
            conn.commit()

        # Intento 1: Autenticacion usando el alias natural cschisano (primera letra + apellido)
        r1 = authenticate_user('cschisano', 'clave_test')
        # Verifica exito en la autenticacion
        self.assertTrue(r1['success'])
        # Verifica que el usuario identificado sea Cristian Schisano
        self.assertEqual(r1['user']['full_name'], 'Cristian Schisano')

        # Intento 2: Autenticacion con mayusculas Cschisano
        r2 = authenticate_user('Cschisano', 'clave_test')
        # Verifica exito
        self.assertTrue(r2['success'])

        # Intento 3: Autenticacion con DNI formateado con puntos 36.442.025
        r3 = authenticate_user('36.442.025', 'clave_test')
        # Verifica exito
        self.assertTrue(r3['success'])

        # Intento 4: Autenticacion con DNI plano 36442025
        r4 = authenticate_user('36442025', 'clave_test')
        # Verifica exito
        self.assertTrue(r4['success'])

        # Intento 5: Clave incorrecta debe devolver bad_password
        r5 = authenticate_user('cschisano', 'clave_incorrecta')
        # Verifica fallo
        self.assertFalse(r5['success'])
        # Verifica tipo de error
        self.assertEqual(r5['error_type'], 'bad_password')

        # Limpia el usuario de prueba
        with get_db_connection() as conn:
            # Elimina registro
            conn.execute("DELETE FROM users WHERE dni = '36442025';")
            # Confirma borrado
            conn.commit()

    # Prueba 19: Validacion de ingreso del usuario administrador jroman
    def test_jroman_admin_login_and_access(self):
        # 1. Autenticacion con username jroman y contrasena Admin2026*
        auth = authenticate_user('jroman', 'Admin2026*')
        self.assertTrue(auth['success'])
        self.assertEqual(auth['user']['role'], 'admin_sistema')
        self.assertEqual(auth['user']['username'], 'jroman')

        # 2. Inicio de sesion web via POST /login
        resp_login = self.client.post('/login', data={'username': 'jroman', 'pin': 'Admin2026*'}, follow_redirects=True)
        self.assertEqual(resp_login.status_code, 200)
        self.assertIn(b'J. Rom', resp_login.data)

        # 3. Acceso a paneles administrativos restringidos a admin_sistema
        for admin_route in ['/admin/users', '/admin/audit', '/admin/errors', '/config/']:
            r = self.client.get(admin_route)
            self.assertEqual(r.status_code, 200, f"Error al acceder a {admin_route} como jroman")

# Permite ejecutar las pruebas individualmente
if __name__ == '__main__':
    unittest.main()
