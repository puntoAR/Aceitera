import unittest
import datetime
from core.timezone import PLANT_TZ, get_plant_now, get_plant_now_str, get_plant_today_str
from core.database import init_db, get_db_connection
from core.migrations import apply_pending_migrations
from modules.production.service import record_weighing, record_line_stop, get_recent_weighings, get_shift_stops

class TestPlantTimezone(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()
        apply_pending_migrations()

    def test_plant_timezone_offset(self):
        """Verifica que la zona horaria sea UTC-3 estricta (Argentina)."""
        now = get_plant_now()
        self.assertIsNotNone(now.tzinfo)
        offset = now.utcoffset()
        self.assertEqual(offset, datetime.timedelta(hours=-3))

    def test_plant_now_str_format(self):
        """Verifica que el string generado cumpla con el formato YYYY-MM-DD HH:MM:SS."""
        now_str = get_plant_now_str()
        self.assertEqual(len(now_str), 19)
        # Debe poder parsearse sin errores
        parsed = datetime.datetime.strptime(now_str, '%Y-%m-%d %H:%M:%S')
        self.assertIsInstance(parsed, datetime.datetime)

    def test_plant_today_str_format(self):
        """Verifica que la fecha calendario cumpla con YYYY-MM-DD."""
        today_str = get_plant_today_str()
        self.assertEqual(len(today_str), 10)
        parsed = datetime.datetime.strptime(today_str, '%Y-%m-%d')
        self.assertIsInstance(parsed, datetime.datetime)

    def test_production_weighing_and_stop_use_plant_time(self):
        """Verifica que las pesadas y paradas se guarden con la fecha y hora de planta."""
        w = record_weighing(
            shift_id='TM',
            operator_name='Tester Horario',
            sample_point='ingreso_semilla',
            gross_weight_kg=15.0,
            tare_weight_kg=0.5,
            fill_time_seconds=30.0,
            line_status='operando'
        )
        self.assertIn('timestamp', w)
        # La hora guardada debe coincidir con el día actual de la planta
        plant_today = get_plant_today_str()
        self.assertTrue(w['timestamp'].startswith(plant_today))

        # Registrar parada
        record_line_stop('TM', 10.0, 'Prueba de parada de línea', 'Tester Horario')
        stops = get_shift_stops('TM')
        self.assertGreater(len(stops), 0)
        latest_stop = stops[0]
        self.assertTrue(latest_stop['start_time'].startswith(plant_today))

    def test_migration_9_applied(self):
        """Verifica que la migración 9 de ajuste de horas históricas se encuentre registrada."""
        with get_db_connection() as conn:
            row = conn.execute("SELECT * FROM schema_migrations WHERE version = 9;").fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row['name'], 'adjust_legacy_utc_timestamps_to_art')

if __name__ == '__main__':
    unittest.main()
