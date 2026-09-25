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
    admin_create_user
)
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
            conn.execute("DELETE FROM users WHERE username NOT IN ('admin', 'gerente', 'operario', 'laboratorio');")
            conn.execute("UPDATE users SET pin = '1111', must_change_password = 0 WHERE username = 'operario';")
            conn.execute("UPDATE users SET pin = '3333', must_change_password = 0 WHERE username = 'gerente';")
            conn.execute("UPDATE users SET pin = '1234', must_change_password = 0 WHERE username = 'admin';")
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
        self.assertTrue(new_pwd.startswith('Bio-'))

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

    # Prueba 8: Registro y resolucion de excepciones de sistema
    def test_system_error_logging_and_resolution(self):
        # Registra un error de prueba
        try:
            raise RuntimeError("Error simulado de pruebas unitarias")
        except Exception as e:
            log_error("TEST_UNIT", "Fallo inducido para verificar trazabilidad", e)

        # Verifica que figure en la tabla de errores
        errors = get_system_errors(limit=10)
        target = next((err for err in errors if "Fallo inducido" in err['error_message']), None)
        self.assertIsNotNone(target)
        self.assertEqual(target['resolved'], 0)

        # Resuelve el incidente
        resolve_system_error(target['id'])
        errors_after = get_system_errors(limit=10)
        target_after = next((err for err in errors_after if err['id'] == target['id']), None)
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
        self.assertIn(b'BioBalcarce', r_manifest.data)
        self.assertIn(b'standalone', r_manifest.data)

        # Consulta el Service Worker
        r_sw = self.client.get('/sw.js')
        self.assertEqual(r_sw.status_code, 200)
        self.assertEqual(r_sw.headers.get('Service-Worker-Allowed'), '/')
        self.assertIn(b'biobalcarce-pwa', r_sw.data)

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
        # Verifica que la insignia contenga (Gerencia) y el menu contenga Dashboard Ejecutivo
        self.assertIn('Gerencia', html_content)
        self.assertIn('Dashboard Ejecutivo', html_content)

# Permite ejecutar las pruebas individualmente
if __name__ == '__main__':
    unittest.main()
