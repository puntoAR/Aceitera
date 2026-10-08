# Suite de pruebas automatizadas para la busqueda y descarga remota de actualizaciones
# Importa unittest para organizar y ejecutar pruebas
import unittest
# Importa unittest.mock para simular respuestas de red HTTP sin depender de internet real
from unittest.mock import patch, MagicMock
# Importa sys y os
import sys, os
import hashlib
import zipfile
import json
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Importa la aplicacion Flask
from run import app
# Importa funciones de servicio del actualizador remoto
from modules.updater.service import (
    parse_version_tuple, check_for_remote_updates,
    download_and_apply_remote_update, get_current_version_info
)
from core.database import init_db
from config import BASE_DIR

# Clase de pruebas para la busqueda remota y verificacion SHA-256
class TestRemoteUpdater(unittest.TestCase):
    # Configuracion inicial antes de cada prueba
    def setUp(self):
        init_db()
        app.config['TESTING'] = True
        self.client = app.test_client()

    # Prueba 1: Conversion y comparacion de versiones semanticas
    def test_version_tuple_comparison(self):
        # Comprueba que '1.1.0' sea mayor que '1.0.0'
        v1_0_0 = parse_version_tuple('1.0.0')
        v1_1_0 = parse_version_tuple('v1.1.0')
        v1_0_1 = parse_version_tuple('1.0.1')
        self.assertTrue(v1_1_0 > v1_0_0)
        self.assertTrue(v1_0_1 > v1_0_0)
        self.assertEqual(parse_version_tuple('2.0'), (2, 0, 0))

    # Prueba 2: Deteccion de nueva version remota disponible simulada
    @patch('modules.updater.service.requests.get')
    # Metodo de prueba de deteccion de actualizacion remota
    def test_check_remote_update_available(self, mock_get):
        # Simula respuesta exitosa del servidor con version superior 9.9.9
        mock_response = MagicMock()
        # Codigo HTTP 200 OK
        mock_response.status_code = 200
        # Payload simulado de la nueva version remota
        mock_response.json.return_value = {
            'version': '9.9.9',
            'release_date': '2026-10-01',
            'changelog': ['Mejora de rendimiento'],
            'download_url': 'https://updates.aceitera.com/aceitera-v9.9.9.zip',
            'sha256': 'abcdef123456'
        }
        # Asigna el mock a requests.get
        mock_get.return_value = mock_response

        # Ejecuta la comprobacion
        result = check_for_remote_updates('https://updates.aceitera.com/latest.json')
        # Verifica exito en la llamada
        self.assertTrue(result['success'])
        # Verifica que detecte actualizacion disponible
        self.assertTrue(result['update_available'])
        # Verifica la version remota informada
        self.assertEqual(result['remote_version'], '9.9.9')

    # Prueba 3: Deteccion de sistema al dia cuando no hay versiones nuevas
    @patch('modules.updater.service.requests.get')
    # Metodo de prueba cuando el sistema ya esta al dia
    def test_check_remote_already_up_to_date(self, mock_get):
        # Obtiene version instalada actualmente
        cur_v = get_current_version_info()['version']
        # Simula respuesta con la misma version local
        mock_response = MagicMock()
        # Codigo HTTP 200 OK
        mock_response.status_code = 200
        # Payload con version identica a la instalada
        mock_response.json.return_value = {
            'version': cur_v,
            'release_date': '2026-09-21',
            'changelog': []
        }
        # Asigna el mock
        mock_get.return_value = mock_response

        # Ejecuta comprobacion de actualizacion
        result = check_for_remote_updates()
        # Verifica exito de la consulta
        self.assertTrue(result['success'])
        # Confirma que no hay actualizacion disponible
        self.assertFalse(result['update_available'])

    # Prueba 4: Manejo seguro ante corte de internet o timeout en planta
    @patch('modules.updater.service.requests.get')
    def test_check_remote_network_failure(self, mock_get):
        # Simula error de conexion
        mock_get.side_effect = Exception("Conexion rechazada o sin internet")

        result = check_for_remote_updates()
        # No debe colapsar la aplicacion, debe retornar success=False controlado
        self.assertFalse(result['success'])
        self.assertIn('No se pudo consultar', result['error'])

    # Prueba 5: Rechazo de descarga por inconsistencia en hash SHA-256 (seguridad)
    @patch('modules.updater.service.requests.get')
    def test_sha256_mismatch_rejection(self, mock_get):
        # Simula descarga de un archivo con contenido arbitrario
        fake_content = b"fake-corrupted-zip-data"
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.iter_content.return_value = [fake_content]
        mock_get.return_value = mock_response

        # Especifica un hash SHA-256 erroneo a proposito
        invalid_expected_sha = "0000000000000000000000000000000000000000000000000000000000000000"

        # Debe rechazar la descarga y lanzar ValueError por fallo de integridad
        with self.assertRaises(ValueError) as context:
            download_and_apply_remote_update('https://fake.url/pkg.zip', expected_sha256=invalid_expected_sha)
        self.assertIn('Fallo de integridad criptografica', str(context.exception))

    # Prueba 6: Acceso web autenticado a la ruta check-online
    def test_web_route_check_online(self):
        # Inicia sesion como admin
        self.client.post('/login', data={'username': 'admin', 'pin': '1234'})
        # Consulta la vista de busqueda online
        resp = self.client.get('/config/updates/check-online', follow_redirects=True)
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b'Centro de Actualizaciones', resp.data)

# Ejecucion de pruebas
if __name__ == '__main__':
    unittest.main()
