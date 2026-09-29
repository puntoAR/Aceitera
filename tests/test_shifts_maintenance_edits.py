import unittest
import json
import datetime
from run import app
from core.database import get_db_connection, init_db
from core.timezone import determine_time_slot, get_current_time_slot, get_plant_now
from core.security import register_user, authenticate_user, has_module_access, get_user_allowed_modules
from modules.admin.service import admin_update_user, approve_user
from modules.production.service import record_weighing, update_weighing
from modules.laboratory.service import record_analysis, update_analysis
from modules.dashboard.service import get_shift_and_daily_performance, get_executive_dashboard_data

class TestShiftsMaintenanceEdits(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()

    def setUp(self):
        self.app = app.test_client()
        self.app.testing = True

    def test_determine_time_slot_boundaries(self):
        """Valida la clasificación precisa de franjas horarias y días operativos."""
        # Turno Mañana: 06:00 a 13:59:59
        tm_start = determine_time_slot("2026-10-15 06:00:00")
        self.assertEqual(tm_start['shift_id'], 'TM')
        self.assertEqual(tm_start['time_slot'], '06:00 - 14:00')
        self.assertEqual(tm_start['operational_date'], '2026-10-15')

        tm_end = determine_time_slot("2026-10-15 13:59:59")
        self.assertEqual(tm_end['shift_id'], 'TM')

        # Turno Tarde: 14:00 a 21:59:59
        tt_start = determine_time_slot("2026-10-15 14:00:00")
        self.assertEqual(tt_start['shift_id'], 'TT')
        self.assertEqual(tt_start['time_slot'], '14:00 - 22:00')
        self.assertEqual(tt_start['operational_date'], '2026-10-15')

        tt_end = determine_time_slot("2026-10-15 21:59:59")
        self.assertEqual(tt_end['shift_id'], 'TT')

        # Turno Noche (antes de medianoche): 22:00 a 23:59:59
        tn_night = determine_time_slot("2026-10-15 22:00:00")
        self.assertEqual(tn_night['shift_id'], 'TN')
        self.assertEqual(tn_night['time_slot'], '22:00 - 06:00')
        self.assertEqual(tn_night['operational_date'], '2026-10-15')

        # Turno Noche (madrugada post-medianoche): 00:00 a 05:59:59
        # Debe corresponder a la jornada iniciada el día anterior (2026-10-15)
        tn_dawn = determine_time_slot("2026-10-16 03:30:00")
        self.assertEqual(tn_dawn['shift_id'], 'TN')
        self.assertEqual(tn_dawn['time_slot'], '22:00 - 06:00')
        self.assertEqual(tn_dawn['operational_date'], '2026-10-15')
        self.assertEqual(tn_dawn['calendar_date'], '2026-10-16')

    def test_maintenance_role_default_and_custom_permissions(self):
        """Valida que el rol mantenimiento solo acceda a su módulo por defecto y admita módulos adicionales."""
        # Usuario de mantenimiento por defecto (seed en DB)
        with get_db_connection() as conn:
            maint_user = conn.execute("SELECT * FROM users WHERE username = 'mantenimiento';").fetchone()
            self.assertIsNotNone(maint_user)
            self.assertEqual(maint_user['role'], 'mantenimiento')

        # Por defecto solo tiene acceso a 'maintenance'
        allowed = get_user_allowed_modules(maint_user)
        self.assertEqual(allowed, ['maintenance'])
        self.assertTrue(has_module_access(maint_user, 'maintenance'))
        self.assertFalse(has_module_access(maint_user, 'production'))
        self.assertFalse(has_module_access(maint_user, 'inventory'))

        # Actualiza permisos modulares para otorgar 'production' y 'inventory'
        admin_update_user(
            user_id=maint_user['id'],
            username=maint_user['username'],
            full_name=maint_user['full_name'],
            dni=maint_user['dni'],
            phone=maint_user['phone'],
            role='mantenimiento',
            allowed_modules=['maintenance', 'production', 'inventory']
        )

        with get_db_connection() as conn:
            updated_user = conn.execute("SELECT * FROM users WHERE id = ?;", (maint_user['id'],)).fetchone()
        
        self.assertTrue(has_module_access(updated_user, 'maintenance'))
        self.assertTrue(has_module_access(updated_user, 'production'))
        self.assertTrue(has_module_access(updated_user, 'inventory'))
        self.assertFalse(has_module_access(updated_user, 'laboratory'))

    def test_weighing_edit_and_audit_logging(self):
        """Valida que la edición de una pesada recalcule fórmulas y guarde el cambio en audit_logs."""
        # Registra una pesada inicial
        weighing = record_weighing(
            shift_id='TM',
            operator_name='Test Operario',
            sample_point='ingreso_semilla',
            gross_weight_kg=10.0,
            tare_weight_kg=1.0,
            fill_time_seconds=30.0,
            line_status='operando',
            notes='Pesada inicial de prueba'
        )
        w_id = weighing['id']
        self.assertEqual(weighing['net_weight_kg'], 9.0)
        # Velocidad esperada: (9 / 30) * 3600 = 1080 kg/h
        self.assertEqual(weighing['speed_kg_h'], 1080.0)

        # Edita la pesada ajustando la tara a 0.5 kg (neto: 9.5 kg -> velocidad: 1140 kg/h)
        update_weighing(
            weighing_id=w_id,
            sample_point='ingreso_semilla',
            gross_weight_kg=10.0,
            tare_weight_kg=0.5,
            fill_time_seconds=30.0,
            line_status='operando',
            notes='Pesada ajustada',
            edit_reason='Corrección de tara de balanza',
            operator_name='Admin Calidad'
        )

        # Verifica los nuevos valores en la base de datos
        with get_db_connection() as conn:
            edited_row = conn.execute("SELECT * FROM production_weighings WHERE id = ?;", (w_id,)).fetchone()
            self.assertEqual(edited_row['net_weight_kg'], 9.5)
            self.assertEqual(edited_row['speed_kg_h'], 1140.0)
            self.assertEqual(edited_row['tare_weight_kg'], 0.5)

            # Verifica el registro de auditoría
            log_entry = conn.execute("""
                SELECT * FROM audit_logs
                WHERE category = 'PRODUCCION' AND action = 'EDICION_PESADA'
                ORDER BY id DESC LIMIT 1;
            """).fetchone()
            self.assertIsNotNone(log_entry)
            self.assertIn(f"Pesada #{w_id}", log_entry['details'])
            self.assertIn("Corrección de tara de balanza", log_entry['details'])

    def test_laboratory_edit_and_audit_logging(self):
        """Valida que la edición de un análisis analítico guarde el cambio en audit_logs."""
        # Registra un análisis inicial
        analysis = record_analysis(
            sample_code='EXP-TEST-001',
            product='expeller',
            sampling_point='Prensa 2 Salida',
            shift_id='TM',
            operator_name='Analista Test',
            raw_data={'direct_moisture_pct': 7.5, 'direct_fat_pct': 8.8},
            press_number=2
        )
        a_id = analysis['id']

        # Edita el análisis
        update_analysis(
            analysis_id=a_id,
            sample_code='EXP-TEST-001',
            product='expeller',
            sampling_point='Prensa 2 Salida',
            press_number=2,
            moisture_pct=7.1,
            fat_pct=8.2,
            acidity_pct=None,
            foreign_matter_pct=None,
            notes='Repetición de titulación',
            edit_reason='Ajuste por verificación en duplicado',
            operator_name='Jefe de Laboratorio'
        )

        # Verifica los nuevos valores en base de datos
        with get_db_connection() as conn:
            edited_row = conn.execute("SELECT * FROM lab_analyses WHERE id = ?;", (a_id,)).fetchone()
            self.assertEqual(edited_row['moisture_pct'], 7.1)
            self.assertEqual(edited_row['fat_pct'], 8.2)

            # Verifica el registro de auditoría
            log_entry = conn.execute("""
                SELECT * FROM audit_logs
                WHERE category = 'LABORATORIO' AND action = 'EDICION_ANALISIS'
                ORDER BY id DESC LIMIT 1;
            """).fetchone()
            self.assertIsNotNone(log_entry)
            self.assertIn(f"Análisis #{a_id}", log_entry['details'])
            self.assertIn("Ajuste por verificación en duplicado", log_entry['details'])

    def test_shift_and_daily_performance_dashboard(self):
        """Valida que el dashboard genere promedios parciales y comparativo multi-turno."""
        perf = get_shift_and_daily_performance(selected_shifts='all')
        self.assertIn('current_shift', perf)
        self.assertIn('shifts_comparison', perf)
        self.assertIn('consolidated_speed', perf)
        self.assertEqual(len(perf['shifts_comparison']), 3)

        # Verifica que los 3 turnos estén presentes
        shift_ids = [s['shift_id'] for s in perf['shifts_comparison']]
        self.assertIn('TM', shift_ids)
        self.assertIn('TT', shift_ids)
        self.assertIn('TN', shift_ids)

        # Verifica filtrado por un solo turno
        perf_tm = get_shift_and_daily_performance(selected_shifts='TM')
        self.assertEqual(perf_tm['selected_shifts'], ['TM'])
        self.assertFalse(perf_tm['is_all_selected'])

        # Verifica get_executive_dashboard_data
        exec_data = get_executive_dashboard_data(selected_shifts='TM')
        self.assertIn('shift_performance', exec_data)
        self.assertIn('speed_summary', exec_data)

    def test_dashboard_http_routes_with_shifts(self):
        """Valida que la vista del Dashboard responda correctamente con el parámetro shifts."""
        with self.app.session_transaction() as sess:
            sess['user_id'] = 1
            sess['username'] = 'admin'
            sess['role'] = 'admin_sistema'
            sess['full_name'] = 'Administrador del Sistema'

        res_all = self.app.get('/?shifts=all')
        self.assertEqual(res_all.status_code, 200)
        self.assertIn(b"Comparativo de Performance por Turno", res_all.data)
        self.assertIn(b"Turno Ma", res_all.data)

        res_tm = self.app.get('/?shifts=TM')
        self.assertEqual(res_tm.status_code, 200)

    def test_maintenance_http_access_control(self):
        """Valida el control de acceso HTTP del usuario con rol mantenimiento."""
        with get_db_connection() as conn:
            m_user = conn.execute("SELECT id FROM users WHERE username = 'mantenimiento';").fetchone()

        with self.app.session_transaction() as sess:
            sess['user_id'] = m_user['id']
            sess['username'] = 'mantenimiento'
            sess['role'] = 'mantenimiento'
            sess['full_name'] = 'Operador de Mantenimiento'

        # Acceso permitido a su propio módulo
        res_maint = self.app.get('/maintenance/')
        self.assertIn(res_maint.status_code, (200, 302))

        # Intento de acceso no autorizado a producción: debe redirigir a mantenimiento
        res_prod = self.app.get('/production/')
        self.assertEqual(res_prod.status_code, 302)
        self.assertIn('/maintenance', res_prod.headers.get('Location', ''))

    def test_production_weighing_edit_http_route(self):
        """Valida la ruta HTTP POST de edición de pesadas."""
        w = record_weighing(
            shift_id='TM',
            operator_name='Test Operario',
            sample_point='ingreso_semilla',
            gross_weight_kg=12.0,
            tare_weight_kg=2.0,
            fill_time_seconds=30.0
        )
        w_id = w['id']

        with self.app.session_transaction() as sess:
            sess['user_id'] = 1
            sess['username'] = 'admin'
            sess['role'] = 'admin_sistema'
            sess['full_name'] = 'Administrador del Sistema'

        res = self.app.post(f'/production/weighing/edit/{w_id}', data={
            'sample_point': 'ingreso_semilla',
            'gross_weight_kg': '14.0',
            'tare_weight_kg': '2.0',
            'fill_time_seconds': '30.0',
            'line_status': 'operando',
            'notes': 'Ajuste HTTP',
            'edit_reason': 'Prueba HTTP de auditoría'
        }, follow_redirects=False)

        self.assertEqual(res.status_code, 302)
        with get_db_connection() as conn:
            row = conn.execute("SELECT net_weight_kg, speed_kg_h FROM production_weighings WHERE id = ?;", (w_id,)).fetchone()
            self.assertEqual(row['net_weight_kg'], 12.0)
            self.assertEqual(row['speed_kg_h'], 1440.0)

    def test_laboratory_analysis_edit_http_route(self):
        """Valida la ruta HTTP POST de edición de determinaciones de laboratorio."""
        a = record_analysis(
            sample_code='EXP-HTTP-01',
            product='expeller',
            sampling_point='Prensa 2',
            shift_id='TM',
            operator_name='Analista',
            raw_data={'direct_moisture_pct': 8.0, 'direct_fat_pct': 9.0}
        )
        a_id = a['id']

        with self.app.session_transaction() as sess:
            sess['user_id'] = 1
            sess['username'] = 'admin'
            sess['role'] = 'admin_sistema'
            sess['full_name'] = 'Administrador del Sistema'

        res = self.app.post(f'/laboratory/analysis/edit/{a_id}', data={
            'sampling_point': 'Prensa 2 Ajustada',
            'press_number': '2',
            'moisture_pct': '7.2',
            'fat_pct': '8.1',
            'acidity_pct': '',
            'foreign_matter_pct': '',
            'notes': 'Ajuste HTTP lab',
            'edit_reason': 'Prueba HTTP auditoría laboratorio'
        }, follow_redirects=False)

        self.assertEqual(res.status_code, 302)
        with get_db_connection() as conn:
            row = conn.execute("SELECT moisture_pct, fat_pct FROM lab_analyses WHERE id = ?;", (a_id,)).fetchone()
            self.assertEqual(row['moisture_pct'], 7.2)
            self.assertEqual(row['fat_pct'], 8.1)

if __name__ == '__main__':
    unittest.main()
