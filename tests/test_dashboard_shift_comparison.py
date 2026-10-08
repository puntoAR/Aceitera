import os
import sqlite3
import tempfile
import datetime
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from run import app
from core.database import get_db_connection, init_db, reset_production_operational_data
from modules.dashboard.service import (
    resolve_dashboard_date_range,
    get_shift_and_daily_performance,
    get_executive_dashboard_data
)
from modules.inventory.service import get_total_plant_stocks

class TestDashboardDateRangeAndPerformance(unittest.TestCase):
    def setUp(self):
        self.temp_db_fd, self.temp_db_path = tempfile.mkstemp(suffix=".db")
        os.close(self.temp_db_fd)
        os.environ['DATABASE_PATH'] = self.temp_db_path
        os.environ['SECRET_KEY'] = 'test-secret-key'

        self.app = app
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()

        with self.app.app_context():
            init_db()
            reset_production_operational_data()
            self._seed_test_data()

    def tearDown(self):
        if os.path.exists(self.temp_db_path):
            try:
                os.remove(self.temp_db_path)
            except OSError:
                pass

    def _seed_test_data(self):
        with get_db_connection() as conn:
            # Insert weighings on different dates: 2026-10-01 and 2026-10-02
            # 2026-10-01 TM (08:30)
            conn.execute("""
                INSERT INTO production_weighings 
                (timestamp, sample_date, shift_id, operator_name, sample_point, gross_weight_kg, tare_weight_kg, net_weight_kg, fill_time_seconds, speed_kg_h, proj_8h_kg, proj_24h_kg, line_status)
                VALUES ('2026-10-01 08:30:00', '2026-10-01', 'TM', 'Juan Pérez', 'ingreso_semilla', 15.0, 5.0, 10.0, 36.0, 1000.0, 8000.0, 24000.0, 'operando')
            """)
            conn.execute("""
                INSERT INTO production_weighings 
                (timestamp, sample_date, shift_id, operator_name, sample_point, gross_weight_kg, tare_weight_kg, net_weight_kg, fill_time_seconds, speed_kg_h, proj_8h_kg, proj_24h_kg, line_status)
                VALUES ('2026-10-01 09:00:00', '2026-10-01', 'TM', 'Juan Pérez', 'salida_expeller', 12.0, 5.0, 7.0, 36.0, 700.0, 5600.0, 16800.0, 'operando')
            """)

            # 2026-10-02 TT (15:00)
            conn.execute("""
                INSERT INTO production_weighings 
                (timestamp, sample_date, shift_id, operator_name, sample_point, gross_weight_kg, tare_weight_kg, net_weight_kg, fill_time_seconds, speed_kg_h, proj_8h_kg, proj_24h_kg, line_status)
                VALUES ('2026-10-02 15:00:00', '2026-10-02', 'TT', 'Juan Pérez', 'ingreso_semilla', 17.0, 5.0, 12.0, 36.0, 1200.0, 9600.0, 28800.0, 'operando')
            """)
            conn.execute("""
                INSERT INTO production_weighings 
                (timestamp, sample_date, shift_id, operator_name, sample_point, gross_weight_kg, tare_weight_kg, net_weight_kg, fill_time_seconds, speed_kg_h, proj_8h_kg, proj_24h_kg, line_status)
                VALUES ('2026-10-02 15:30:00', '2026-10-02', 'TT', 'Juan Pérez', 'salida_expeller', 13.4, 5.0, 8.4, 36.0, 840.0, 6720.0, 20160.0, 'operando')
            """)

            # Line stops on 2026-10-01
            conn.execute("""
                INSERT INTO line_stops 
                (shift_id, start_time, duration_minutes, reason, operator_name, comments)
                VALUES ('TM', '2026-10-01 10:00:00', 60.0, 'Mantenimiento preventivo', 'Juan Pérez', 'Limpieza de zaranda')
            """)

            # Lab samples on 2026-10-01 and 2026-10-02
            conn.execute("""
                INSERT INTO lab_analyses 
                (timestamp, sample_date, shift_id, sample_code, product, sampling_point, press_number, operator_name, fat_pct, moisture_pct, acidity_pct)
                VALUES ('2026-10-01 11:00:00', '2026-10-01', 'TM', 'EXP-01', 'expeller', 'Prensa 2', 2, 'Analista', 7.5, 8.0, NULL)
            """)
            conn.execute("""
                INSERT INTO lab_analyses 
                (timestamp, sample_date, shift_id, sample_code, product, sampling_point, press_number, operator_name, fat_pct, moisture_pct, acidity_pct)
                VALUES ('2026-10-02 16:00:00', '2026-10-02', 'TT', 'EXP-02', 'expeller', 'Prensa 2', 2, 'Analista', 8.5, 9.0, NULL)
            """)
            conn.execute("""
                INSERT INTO lab_analyses 
                (timestamp, sample_date, shift_id, sample_code, product, sampling_point, press_number, operator_name, fat_pct, moisture_pct, acidity_pct)
                VALUES ('2026-10-02 16:30:00', '2026-10-02', 'TT', 'ACE-01', 'aceite', 'Tanque 1', NULL, 'Analista', NULL, NULL, 1.2)
            """)

            # Stock measurements in inventory_tanks
            # 2026-10-01 TK-01
            conn.execute("""
                INSERT INTO inventory_tanks 
                (timestamp, tank_id, level_m, volume_m3, liters, oil_kg, density_applied, shift_id, operator_name)
                VALUES ('2026-10-01 18:00:00', 1, 1.5, 10.0, 10000.0, 9200.0, 0.92, 'TT', 'Juan Pérez')
            """)
            # 2026-10-03 TK-01
            conn.execute("""
                INSERT INTO inventory_tanks 
                (timestamp, tank_id, level_m, volume_m3, liters, oil_kg, density_applied, shift_id, operator_name)
                VALUES ('2026-10-03 18:00:00', 1, 2.5, 20.0, 20000.0, 18400.0, 0.92, 'TT', 'Juan Pérez')
            """)
            conn.commit()

    def test_resolve_dashboard_date_range(self):
        # 1. Default (no args)
        res_today = resolve_dashboard_date_range()
        self.assertTrue(res_today['is_single_day'])
        self.assertTrue(res_today['is_today'])
        self.assertEqual(res_today['days_count'], 1)

        # 2. Specific single date
        res_day = resolve_dashboard_date_range(target_date='2026-10-01')
        self.assertTrue(res_day['is_single_day'])
        self.assertEqual(res_day['start_date'], '2026-10-01')
        self.assertEqual(res_day['end_date'], '2026-10-01')
        self.assertEqual(res_day['days_count'], 1)
        self.assertIn('2026-10-01', res_day['scope_date_label'])

        # 3. Date range (start and end)
        res_range = resolve_dashboard_date_range(start_date='2026-10-01', end_date='2026-10-03')
        self.assertFalse(res_range['is_single_day'])
        self.assertEqual(res_range['start_date'], '2026-10-01')
        self.assertEqual(res_range['end_date'], '2026-10-03')
        self.assertEqual(res_range['days_count'], 3)
        self.assertEqual(res_range['scope_mode'], 'range')

        # 4. Inverted dates auto-sort
        res_inv = resolve_dashboard_date_range(start_date='2026-10-05', end_date='2026-10-01')
        self.assertEqual(res_inv['start_date'], '2026-10-01')
        self.assertEqual(res_inv['end_date'], '2026-10-05')
        self.assertEqual(res_inv['days_count'], 5)

        # 5. Month selector
        res_month = resolve_dashboard_date_range(month='2026-10')
        self.assertEqual(res_month['scope_mode'], 'month')
        self.assertEqual(res_month['start_date'], '2026-10-01')
        self.assertEqual(res_month['end_date'], '2026-10-31')
        self.assertEqual(res_month['days_count'], 31)

    def test_multi_day_shift_performance_and_averages(self):
        with self.app.app_context():
            # Query range 2026-10-01 to 2026-10-02 (2 days)
            perf = get_shift_and_daily_performance(start_date='2026-10-01', end_date='2026-10-02')

            self.assertEqual(perf['days_count'], 2)
            self.assertFalse(perf['is_single_day'])

            # Lab averages across the period:
            # Fat P2: 2026-10-01 has 7.5%, 2026-10-02 has 8.5% -> avg = 8.0%
            self.assertEqual(perf['avg_fat_p2'], 8.0)
            # Moisture Expeller: 8.0 and 9.0 -> avg = 8.5%
            self.assertEqual(perf['avg_moist_exp'], 8.5)
            # Acidity: 1.2%
            self.assertEqual(perf['avg_acidity'], 1.2)

            # Speeds:
            # Seed speeds: 1000.0 and 1200.0 -> arithmetic avg = 1100.0 kg/h
            speed = perf['consolidated_speed']
            self.assertEqual(speed['seed_avg_speed'], 1100.0)
            # Expeller speeds: 700.0 and 840.0 -> arithmetic avg = 770.0 kg/h
            self.assertEqual(speed['expeller_avg_speed'], 770.0)
            # Yield pct: 770 / 1100 * 100 = 70.0%
            self.assertEqual(speed['expeller_yield_pct'], 70.0)

            # Budgeted hours: 2 days * 3 shifts * 8h = 48.0h (with 'all' shifts)
            self.assertEqual(speed['total_hours_budget'], 48.0)
            # Stop minutes: 60.0 min (1 hour)
            self.assertEqual(speed['stop_minutes'], 60.0)
            # Effective hours: 48.0 - 1.0 = 47.0h
            self.assertEqual(speed['effective_hours'], 47.0)

    def test_inventory_cutoff_as_of_date(self):
        with self.app.app_context():
            # As of 2026-10-01: TK-01 was measured at 9200 kg
            stocks_oct1 = get_total_plant_stocks(as_of_date='2026-10-01')
            self.assertEqual(stocks_oct1['total_oil_kg'], 9200.0)

            # As of 2026-10-04: TK-01 was measured at 18400 kg
            stocks_oct4 = get_total_plant_stocks(as_of_date='2026-10-04')
            self.assertEqual(stocks_oct4['total_oil_kg'], 18400.0)

    def test_live_dashboard_stock_parity_with_inventory(self):
        with self.app.app_context():
            # In live mode (is_today is True by default), dashboard stocks must match get_total_plant_stocks() exactly
            dash_data = get_executive_dashboard_data()
            inv_stocks = get_total_plant_stocks()
            self.assertEqual(dash_data['stocks']['total_seed_tons'], inv_stocks['total_seed_tons'])
            self.assertEqual(dash_data['stocks']['total_expeller_tons'], inv_stocks['total_expeller_tons'])
            self.assertEqual(dash_data['stocks']['total_oil_kg'], inv_stocks['total_oil_kg'])
            self.assertTrue(dash_data['shift_performance']['is_today'])

    def test_executive_dashboard_chart_multi_day_labels(self):
        with self.app.app_context():
            data = get_executive_dashboard_data(start_date='2026-10-01', end_date='2026-10-02')

            # There are 4 weighings: 2 on Oct 1, 2 on Oct 2
            self.assertEqual(len(data['chart_labels']), 4)
            # For multi-day, labels should include date: DD/MM HH:MM (e.g. '01/10 08:30')
            self.assertIn('01/10 08:30', data['chart_labels'])
            self.assertIn('02/10 15:00', data['chart_labels'])

    def test_dashboard_routes_and_views(self):
        # Log in
        with self.client.session_transaction() as sess:
            sess['user_id'] = 1
            sess['username'] = 'admin'
            sess['role'] = 'admin_sistema'

        # Test index default
        res = self.client.get('/')
        self.assertEqual(res.status_code, 200)

        # Test index single day
        res_day = self.client.get('/?date=2026-10-01')
        self.assertEqual(res_day.status_code, 200)
        self.assertIn(b'2026-10-01', res_day.data)

        # Test index range
        res_range = self.client.get('/?start_date=2026-10-01&end_date=2026-10-02')
        self.assertEqual(res_range.status_code, 200)
        self.assertIn(b'01/10 08:30', res_range.data)

        # Test index month
        res_month = self.client.get('/?month=2026-10')
        self.assertEqual(res_month.status_code, 200)

        # Test API KPIs
        res_api = self.client.get('/api/kpis?start_date=2026-10-01&end_date=2026-10-02')
        self.assertEqual(res_api.status_code, 200)
        json_data = res_api.get_json()
        self.assertIn('shift_performance', json_data)
        self.assertEqual(json_data['shift_performance']['days_count'], 2)
        self.assertIn('stocks', json_data)
        self.assertIn('speed_summary', json_data)

if __name__ == '__main__':
    unittest.main()
