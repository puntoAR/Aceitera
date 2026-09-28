"""
Pruebas unitarias para validar las correcciones de errores del sistema BioBalcarce:
1. Parseo seguro de cadenas vacías a float en cubicaje de tanques (density_override).
2. Parseo seguro de cadenas vacías a float en cubicaje de silos (ph_override).
3. Inserción correcta de 10 columnas en inventory_movements sin error de desajuste.
4. Robustez general de utilidades safe_float y safe_int ante entradas vacías y comas decimales.
"""
import unittest
import sys, os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import app
from core.database import init_db, get_db_connection
from core.utils import safe_float, safe_int
from modules.inventory.service import (
    record_inventory_movement, record_tank_level, record_silo_measurement
)

class TestErrorFixes(unittest.TestCase):
    def setUp(self):
        app.config['TESTING'] = True
        app.config['WTF_CSRF_ENABLED'] = False
        self.client = app.test_client()
        init_db()

        # Inicia sesion como admin
        self.client.post('/login', data={'username': 'admin', 'pin': '1234'}, follow_redirects=True)

    def test_safe_float_utility(self):
        """Verifica que safe_float maneje cadenas vacias, espacios, nulos, comas y fallbacks."""
        # Cadenas vacias y espacios con default
        self.assertEqual(safe_float("", 0.0), 0.0)
        self.assertEqual(safe_float("   ", 0.0), 0.0)
        self.assertIsNone(safe_float("", None))
        self.assertIsNone(safe_float("   ", None))
        self.assertIsNone(safe_float(None, None))

        # Numeros con punto y coma decimal
        self.assertEqual(safe_float("0.920"), 0.92)
        self.assertEqual(safe_float("0,920"), 0.92)
        self.assertEqual(safe_float("44,5"), 44.5)
        self.assertEqual(safe_float("12500,75"), 12500.75)

        # Tipos numericos directos
        self.assertEqual(safe_float(10), 10.0)
        self.assertEqual(safe_float(10.5), 10.5)

        # Textos invalidos con fallback
        self.assertEqual(safe_float("no_es_numero", 5.0), 5.0)
        self.assertIsNone(safe_float("invalido", None))

    def test_safe_int_utility(self):
        """Verifica que safe_int maneje cadenas vacias, comas, decimales y fallbacks."""
        self.assertEqual(safe_int("", 0), 0)
        self.assertEqual(safe_int("   ", 0), 0)
        self.assertIsNone(safe_int("", None))
        self.assertIsNone(safe_int(None, None))

        self.assertEqual(safe_int("10"), 10)
        self.assertEqual(safe_int("10.5"), 10)
        self.assertEqual(safe_int("15,8"), 15)
        self.assertEqual(safe_int(7), 7)
        self.assertEqual(safe_int(8.9), 8)

        self.assertEqual(safe_int("invalido", 42), 42)
        self.assertIsNone(safe_int("invalido", None))

    def test_tank_reading_with_empty_density_override(self):
        """
        Simula el Error #2: El operario envia el formulario de tanque
        dejando la densidad opcional en blanco ('').
        Debe procesarse sin ValueError y registrar la medicion con la densidad por defecto del tanque.
        """
        response = self.client.post('/inventory/tank-reading', data={
            'tank_id': '1',
            'level_m': '2.50',
            'shift_id': 'TM',
            'operator_name': 'jroman',
            'density_override': ''  # Cadena vacia enviada por el navegador
        }, follow_redirects=True)

        self.assertEqual(response.status_code, 200)
        # Verifica que no hubo mensaje de error en el flash
        self.assertIn(b'registrado', response.data.lower())
        self.assertNotIn(b'could not convert string to float', response.data)

    def test_silo_reading_with_empty_ph_override(self):
        """
        Simula el Error #3: El operario envia el cubicaje de silo
        dejando el peso hectolitrico opcional en blanco ('').
        Debe procesarse sin ValueError y registrar el cubicaje con el pH por defecto.
        """
        response = self.client.post('/inventory/silo-reading', data={
            'silo_id': '1',
            'covered_sheets': '3',
            'partial_sheet_height_m': '0.00',
            'cone_occupied_status': 'lleno',
            'copete_height_m': '0.00',
            'ph_override': '',  # Cadena vacia enviada por el navegador
            'shift_id': 'TM',
            'operator_name': 'jroman'
        }, follow_redirects=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn(b'registrado', response.data.lower())
        self.assertNotIn(b'could not convert string to float', response.data)

    def test_record_inventory_movement_column_match(self):
        """
        Simula el Error #1: Registro de movimiento de existencias.
        Verifica que la sentencia SQL posea exactamente 10 columnas y 10 valores,
        guardando y recuperando el registro en base de datos sin OperationalError.
        """
        # Prueba directa del servicio
        record_inventory_movement(
            product='aceite',
            movement_type='despacho',
            origin='Tanque 1',
            destination='Camion Cisterna Patente AA123BB',
            quantity_kg=28500.0,
            document_ref='REM-009988',
            shift_id='TT',
            operator_name='jroman',
            notes='Despacho verificado sin error'
        )

        with get_db_connection() as conn:
            row = conn.execute("""
                SELECT * FROM inventory_movements WHERE document_ref = 'REM-009988';
            """).fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row['product'], 'aceite')
            self.assertEqual(row['movement_type'], 'despacho')
            self.assertEqual(row['quantity_kg'], 28500.0)
            self.assertEqual(row['operator_name'], 'jroman')

        # Prueba a traves de la ruta web
        response = self.client.post('/inventory/movement', data={
            'product': 'expeller',
            'movement_type': 'ingreso',
            'origin': 'Prensa 2',
            'destination': 'Silo 4',
            'quantity_kg': '15000',
            'document_ref': 'REM-009989',
            'shift_id': 'TT',
            'operator_name': 'jroman',
            'notes': 'Ingreso interno'
        }, follow_redirects=True)

        self.assertEqual(response.status_code, 200)
        self.assertNotIn(b'SQLite error', response.data)
        self.assertNotIn(b'values for', response.data)
        self.assertIn(b'registrado exitosamente', response.data.lower())

if __name__ == '__main__':
    unittest.main()
