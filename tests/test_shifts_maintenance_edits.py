import unittest
import json
import datetime
from run import app
from core.database import get_db_connection, init_db
from core.timezone import determine_time_slot, get_current_time_slot, get_plant_now
from core.security import register_user, authenticate_user, has_module_access, get_user_allowed_modules
from modules.admin.service import admin_update_user, approve_user
from modules.production.service import (
    record_weighing, update_weighing, delete_weighing,
    record_line_stop, update_line_stop, delete_line_stop, get_shift_stops
)
from modules.laboratory.service import record_analysis, update_analysis, delete_analysis
from modules.inventory.service import (
    record_tank_level, update_tank_reading, delete_tank_reading,
    record_silo_measurement, update_silo_reading, delete_silo_reading, get_total_plant_stocks
)
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

    def test_line_stop_custom_date_shift_and_fallback(self):
        """Valida que record_line_stop permita shift_id y stop_date custom, y fallback automático."""
        # 1. Con fecha y turno explícitos
        stop1 = record_line_stop(
            shift_id='TN',
            duration_minutes=45.0,
            reason='Mantenimiento Programado',
            operator_name='Carlos Operario',
            stop_date='2026-10-10'
        )
        self.assertEqual(stop1['shift_id'], 'TN')
        self.assertTrue(stop1['start_time'].startswith('2026-10-10'))
        self.assertEqual(stop1['duration_minutes'], 45.0)

        # 2. Con fallback automático (sin shift_id ni stop_date)
        now_slot = determine_time_slot(get_plant_now())
        stop2 = record_line_stop(
            duration_minutes=20.0,
            reason='Despeje tolva'
        )
        self.assertEqual(stop2['shift_id'], now_slot['shift_id'])
        self.assertTrue(stop2['start_time'].startswith(now_slot['operational_date']) or stop2['start_time'].startswith(now_slot['calendar_date']))

    def test_line_stop_update_and_delete_with_audit(self):
        """Valida la edición y eliminación de paradas de planta con trazabilidad en auditoría."""
        stop = record_line_stop(shift_id='TM', duration_minutes=30.0, reason='Atasco')
        stop_id = stop['id']

        # Edición
        update_line_stop(
            stop_id=stop_id,
            duration_minutes=40.0,
            reason='Atasco y Limpieza',
            edit_reason='Ajuste de duración real',
            operator_name='Supervisor',
            shift_id='TT'
        )
        with get_db_connection() as conn:
            row = conn.execute("SELECT * FROM line_stops WHERE id = ?;", (stop_id,)).fetchone()
            self.assertEqual(row['duration_minutes'], 40.0)
            self.assertEqual(row['reason'], 'Atasco y Limpieza')
            self.assertEqual(row['shift_id'], 'TT')

            audit = conn.execute("SELECT * FROM audit_logs WHERE action = 'EDICION_PARADA' ORDER BY id DESC LIMIT 1;").fetchone()
            self.assertIsNotNone(audit)
            self.assertIn('Ajuste de duración real', audit['details'])

        # Eliminación
        delete_line_stop(stop_id=stop_id, delete_reason='Cargado por error en turno incorrecto', operator_name='Supervisor')
        with get_db_connection() as conn:
            row_del = conn.execute("SELECT * FROM line_stops WHERE id = ?;", (stop_id,)).fetchone()
            self.assertIsNone(row_del)

            audit_del = conn.execute("SELECT * FROM audit_logs WHERE action = 'ELIMINACION_PARADA' ORDER BY id DESC LIMIT 1;").fetchone()
            self.assertIsNotNone(audit_del)
            self.assertIn('Cargado por error', audit_del['details'])

    def test_weighing_delete_with_audit(self):
        """Valida la eliminación de pesadas de producción con registro en bitácora de auditoría."""
        w = record_weighing(shift_id='TM', operator_name='Op', sample_point='salida_expeller',
                            gross_weight_kg=15.0, tare_weight_kg=2.0, fill_time_seconds=30.0)
        w_id = w['id']

        delete_weighing(weighing_id=w_id, delete_reason='Muestra duplicada cargada sin tara', operator_name='Jefe Turno')
        with get_db_connection() as conn:
            row = conn.execute("SELECT * FROM production_weighings WHERE id = ?;", (w_id,)).fetchone()
            self.assertIsNone(row)

            audit = conn.execute("SELECT * FROM audit_logs WHERE action = 'ELIMINACION_PESADA' ORDER BY id DESC LIMIT 1;").fetchone()
            self.assertIsNotNone(audit)
            self.assertIn('Muestra duplicada', audit['details'])

    def test_tank_reading_edit_delete_and_stock_recalculation(self):
        """Valida edición y eliminación de cubicaje de tanques de aceite y su recálculo de existencias."""
        # Registra medición en tanque 1 (diámetro 2.5m)
        r = record_tank_level(tank_id=1, level_m=1.0, shift_id='TM', operator_name='Op Tanque')
        r_id = r['id']
        stocks1 = get_total_plant_stocks()

        # Edición a nivel más alto (2.2m < 2.5m)
        update_tank_reading(reading_id=r_id, level_m=2.2, edit_reason='Error de regla de medición', operator_name='Supervisor')
        stocks2 = get_total_plant_stocks()
        self.assertGreater(stocks2['total_oil_kg'], stocks1['total_oil_kg'])

        with get_db_connection() as conn:
            audit = conn.execute("SELECT * FROM audit_logs WHERE action = 'EDICION_CUBICAJE_TANQUE' ORDER BY id DESC LIMIT 1;").fetchone()
            self.assertIsNotNone(audit)
            self.assertIn('Error de regla', audit['details'])

        # Eliminación
        delete_tank_reading(reading_id=r_id, delete_reason='Medición inválida por movimiento de carga', operator_name='Supervisor')
        stocks3 = get_total_plant_stocks()

        with get_db_connection() as conn:
            row = conn.execute("SELECT * FROM inventory_tanks WHERE id = ?;", (r_id,)).fetchone()
            self.assertIsNone(row)
            audit_del = conn.execute("SELECT * FROM audit_logs WHERE action = 'ELIMINACION_CUBICAJE_TANQUE' ORDER BY id DESC LIMIT 1;").fetchone()
            self.assertIsNotNone(audit_del)
            self.assertIn('Medición inválida', audit_del['details'])

    def test_silo_reading_edit_delete_and_stock_recalculation(self):
        """Valida edición y eliminación de cubicaje de silos (semilla/expeller) y su recálculo de existencias."""
        s = record_silo_measurement(silo_id=1, covered_sheets=2.0, partial_sheet_height_m=0.0,
                                    cone_status='lleno', copete_height_m=0.0, shift_id='TM', operator_name='Op Silo')
        s_id = s['id']
        stocks1 = get_total_plant_stocks()

        # Edición
        update_silo_reading(reading_id=s_id, covered_sheets=4.0, partial_sheet_height_m=0.2,
                            cone_occupied_status='lleno', copete_height_m=0.5, edit_reason='Corrección de chapas vista superior', operator_name='Supervisor')
        stocks2 = get_total_plant_stocks()
        # El stock debe haber aumentado
        self.assertGreater(stocks2['total_seed_kg'] + stocks2['total_expeller_kg'],
                           stocks1['total_seed_kg'] + stocks1['total_expeller_kg'])

        with get_db_connection() as conn:
            audit = conn.execute("SELECT * FROM audit_logs WHERE action = 'EDICION_CUBICAJE_SILO' ORDER BY id DESC LIMIT 1;").fetchone()
            self.assertIsNotNone(audit)
            self.assertIn('Corrección de chapas', audit['details'])

        # Eliminación
        delete_silo_reading(reading_id=s_id, delete_reason='Cubicaje erróneo', operator_name='Supervisor')
        with get_db_connection() as conn:
            row = conn.execute("SELECT * FROM inventory_silos WHERE id = ?;", (s_id,)).fetchone()
            self.assertIsNone(row)
            audit_del = conn.execute("SELECT * FROM audit_logs WHERE action = 'ELIMINACION_CUBICAJE_SILO' ORDER BY id DESC LIMIT 1;").fetchone()
            self.assertIsNotNone(audit_del)
            self.assertIn('Cubicaje erróneo', audit_del['details'])

    def test_laboratory_analysis_delete_with_audit(self):
        """Valida la eliminación de análisis de laboratorio con registro en auditoría."""
        a = record_analysis(sample_code='DEL-LAB-01', product='semilla', sampling_point='Tolva',
                            shift_id='TM', operator_name='Analista', raw_data={'direct_moisture_pct': 9.5})
        a_id = a['id']

        delete_analysis(analysis_id=a_id, delete_reason='Muestra contaminada descartada', operator_name='Jefe Lab')
        with get_db_connection() as conn:
            row = conn.execute("SELECT * FROM lab_analyses WHERE id = ?;", (a_id,)).fetchone()
            self.assertIsNone(row)
            audit = conn.execute("SELECT * FROM audit_logs WHERE action = 'ELIMINACION_ANALISIS' ORDER BY id DESC LIMIT 1;").fetchone()
            self.assertIsNotNone(audit)
            self.assertIn('Muestra contaminada', audit['details'])

    def test_http_routes_for_deletions_and_edits(self):
        """Valida los endpoints HTTP para eliminación y edición de paradas, pesadas, tanques, silos y análisis."""
        with self.app.session_transaction() as sess:
            sess['user_id'] = 1
            sess['username'] = 'admin'
            sess['role'] = 'admin_sistema'
            sess['full_name'] = 'Administrador del Sistema'

        # 1. Registrar parada HTTP con turno y fecha
        res_stop = self.app.post('/production/stop', data={
            'duration_minutes': '25',
            'reason': 'Corte Eléctrico',
            'shift_id': 'TT',
            'stop_date': '2026-10-12'
        }, follow_redirects=False)
        self.assertEqual(res_stop.status_code, 302)

        with get_db_connection() as conn:
            stop_row = conn.execute("SELECT id FROM line_stops WHERE reason = 'Corte Eléctrico' ORDER BY id DESC LIMIT 1;").fetchone()
            st_id = stop_row['id']

        # 2. Editar parada HTTP
        res_edit_st = self.app.post(f'/production/stop/edit/{st_id}', data={
            'duration_minutes': '35',
            'reason': 'Corte Eléctrico General',
            'shift_id': 'TT',
            'stop_date': '2026-10-12',
            'edit_reason': 'Ajuste de tiempo por informe de EDEN'
        }, follow_redirects=False)
        self.assertEqual(res_edit_st.status_code, 302)

        # 3. Eliminar parada HTTP
        res_del_st = self.app.post(f'/production/stop/delete/{st_id}', data={
            'delete_reason': 'Prueba HTTP eliminación'
        }, follow_redirects=False)
        self.assertEqual(res_del_st.status_code, 302)

        # 4. Eliminar pesada HTTP
        w = record_weighing(shift_id='TM', operator_name='Op', sample_point='salida_expeller',
                            gross_weight_kg=12.0, tare_weight_kg=1.0, fill_time_seconds=30.0)
        res_del_w = self.app.post(f'/production/weighing/delete/{w["id"]}', data={
            'delete_reason': 'Prueba HTTP pesada delete'
        }, follow_redirects=False)
        self.assertEqual(res_del_w.status_code, 302)

        # 5. Editar y Eliminar tanque HTTP
        tr = record_tank_level(tank_id=1, level_m=1.5, shift_id='TM', operator_name='Op')
        res_edit_tr = self.app.post(f'/inventory/tank-reading/edit/{tr["id"]}', data={
            'level_m': '2.1',
            'density_override': '0.922',
            'edit_reason': 'Prueba HTTP tanque edit'
        }, follow_redirects=False)
        self.assertEqual(res_edit_tr.status_code, 302)

        res_del_tr = self.app.post(f'/inventory/tank-reading/delete/{tr["id"]}', data={
            'delete_reason': 'Prueba HTTP tanque delete'
        }, follow_redirects=False)
        self.assertEqual(res_del_tr.status_code, 302)

        # 6. Editar y Eliminar silo HTTP
        sr = record_silo_measurement(silo_id=1, covered_sheets=1.0, partial_sheet_height_m=0.0,
                                     cone_status='lleno', copete_height_m=0.0, shift_id='TM', operator_name='Op')
        res_edit_sr = self.app.post(f'/inventory/silo-reading/edit/{sr["id"]}', data={
            'covered_sheets': '2.5',
            'partial_sheet_height_m': '0.1',
            'cone_occupied_status': 'lleno',
            'copete_height_m': '0.2',
            'ph_override': '',
            'edit_reason': 'Prueba HTTP silo edit'
        }, follow_redirects=False)
        self.assertEqual(res_edit_sr.status_code, 302)

        res_del_sr = self.app.post(f'/inventory/silo-reading/delete/{sr["id"]}', data={
            'delete_reason': 'Prueba HTTP silo delete'
        }, follow_redirects=False)
        self.assertEqual(res_del_sr.status_code, 302)

        # 7. Eliminar análisis lab HTTP
        la = record_analysis(sample_code='HTTP-DEL-01', product='aceite', sampling_point='Salida Prensa',
                             shift_id='TM', operator_name='Analista', raw_data={'direct_moisture_pct': 0.1})
        res_del_la = self.app.post(f'/laboratory/analysis/delete/{la["id"]}', data={
            'delete_reason': 'Prueba HTTP lab delete'
        }, follow_redirects=False)
        self.assertEqual(res_del_la.status_code, 302)

if __name__ == '__main__':
    unittest.main()

