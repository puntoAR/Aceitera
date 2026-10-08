# Script utilitario para cargar datos realistas de simulacion de turno en planta
# Importa sys y os para configurar rutas
import sys, os
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

# Importa datetime para estampas de tiempo realistas
import datetime
# Importa la conexion a base de datos
from core.database import init_db, get_db_connection
# Importa servicios de cada modulo
from modules.production.service import record_weighing, record_line_stop
from modules.inventory.service import record_tank_level, record_silo_measurement
from modules.laboratory.service import record_analysis
from modules.yield_balance.service import reconcile_shift

# Funcion para sembrar una jornada completa de operacion representativa
def seed_realistic_shift():
    # Inicializa las tablas si no existen
    init_db()
    print("Cargando datos de prueba de planta...")

    # 1. Cubicaje inicial de tanques de aceite
    with get_db_connection() as conn:
        tk1 = conn.execute("SELECT id FROM equipment_tanks WHERE code = 'TK-01';").fetchone()['id']
        tk2 = conn.execute("SELECT id FROM equipment_tanks WHERE code = 'TK-02';").fetchone()['id']
        tk3 = conn.execute("SELECT id FROM equipment_tanks WHERE code = 'TK-03';").fetchone()['id']
        s1 = conn.execute("SELECT id FROM equipment_silos WHERE code = 'SILO-01';").fetchone()['id']
        s2 = conn.execute("SELECT id FROM equipment_silos WHERE code = 'SILO-02';").fetchone()['id']
        # Busca el silo aereo verde de expeller
        sev_row = conn.execute("SELECT id FROM equipment_silos WHERE code = 'SILO-EXP-V';").fetchone()
        # Si no existe busca el generico previo
        se_id = sev_row['id'] if sev_row else conn.execute("SELECT id FROM equipment_silos WHERE code = 'SILO-EXP';").fetchone()['id']

    # Registra nivel en Tanque 1 horizontal (2.10 metros sobre 2.50m - 88.5% util)
    record_tank_level(tk1, 2.10, 'TM', 'Operario de Linea 1')
    # Registra nivel en Tanque 2 vertical (3.20 metros sobre 4.60m - 69.6% util)
    record_tank_level(tk2, 3.20, 'TM', 'Operario de Linea 1')
    # Registra nivel en Tanque 3 vertical plastico (1.80 metros sobre 4.00m - 45.0% util)
    record_tank_level(tk3, 1.80, 'TM', 'Operario de Linea 1')

    # Registra cubicaje en Silo 1 de semilla (3 chapas, cono lleno, copete 0.5m)
    record_silo_measurement(s1, 3.0, 0.0, 'lleno', 0.5, 'TM', 'Operario de Linea 1', ph_override=40.0)
    # Registra cubicaje en Silo 2 de semilla (4 chapas, cono lleno, copete 0m)
    record_silo_measurement(s2, 4.0, 0.0, 'lleno', 0.0, 'TM', 'Operario de Linea 1', ph_override=40.0)
    # Registra cubicaje en Silo Aereo Verde de expeller (2.0 chapas, cono lleno)
    record_silo_measurement(se_id, 2.0, 0.0, 'lleno', 0.0, 'TM', 'Operario de Linea 1', ph_override=22.0)

    # 2. Pesadas horarias del turno manana (8 horas)
    hourly_samples = [
        ('06:30', 'ingreso_semilla', 30.2, 60.0),
        ('06:35', 'salida_expeller', 15.5, 60.0),
        ('07:30', 'ingreso_semilla', 31.0, 60.0),
        ('07:35', 'salida_expeller', 16.0, 60.0),
        ('08:30', 'ingreso_semilla', 29.8, 60.0),
        ('08:35', 'salida_expeller', 15.2, 60.0),
        ('09:30', 'ingreso_semilla', 32.5, 60.0),
        ('09:35', 'salida_expeller', 16.8, 60.0),
        ('10:30', 'ingreso_semilla', 30.5, 60.0),
        ('10:35', 'salida_expeller', 15.6, 60.0),
        ('11:30', 'ingreso_semilla', 31.2, 60.0),
        ('11:35', 'salida_expeller', 16.1, 60.0),
        ('12:30', 'ingreso_semilla', 30.0, 60.0),
        ('12:35', 'salida_expeller', 15.4, 60.0),
        ('13:30', 'ingreso_semilla', 31.5, 60.0),
        ('13:35', 'salida_expeller', 16.2, 60.0),
    ]

    # Itera sobre las muestras para insertarlas con su marca temporal
    for time_str, point, gross, fill_t in hourly_samples:
        today_date = datetime.date.today().isoformat()
        custom_ts = f"{today_date} {time_str}:00"
        # Registra la pesada
        w = record_weighing('TM', 'Operario de Linea 1', point, gross, 0.0, fill_t, 'operando')
        # Ajusta la marca temporal para que refleje la hora horaria
        with get_db_connection() as conn:
            conn.execute("UPDATE production_weighings SET timestamp = ? WHERE id = ?;", (custom_ts, w['id']))
            conn.commit()

    # 3. Parada de linea de 25 minutos por limpieza de zaranda
    record_line_stop('TM', 25.0, 'Limpieza de zaranda y despeje', 'Operario de Linea 1')

    # 4. Analisis de laboratorio del turno
    record_analysis('M-SEM-01', 'semilla', 'Tolva Recepcion', 'TM', 'Analista de Calidad', {
        'moisture_initial_g': 10.015, 'moisture_dry_g': 9.150,
        'fat_sample_g': 2.050, 'fat_final_flask_g': 122.950, 'fat_tare_flask_g': 121.950,
        'fm_sample_g': 50.0, 'fm_impurities_g': 0.85
    }, 'Muestra representativa ingreso')

    record_analysis('M-EXP-01', 'expeller', 'Prensa 1', 'TM', 'Analista de Calidad', {
        'moisture_initial_g': 10.020, 'moisture_dry_g': 9.300,
        'fat_sample_g': 2.010, 'fat_final_flask_g': 122.210, 'fat_tare_flask_g': 122.000,
    }, 'Expeller caliente recien prensado')

    record_analysis('M-OIL-01', 'aceite', 'Tanque 1', 'TM', 'Analista de Calidad', {
        'acidity_sample_g': 10.000, 'acidity_naoh_ml': 2.95,
        'acidity_naoh_normality': 0.0997, 'acidity_ft_factor': 0.282
    }, 'Aceite crudo decantado')

    # 5. Conciliacion de turno
    reconcile_shift(
        shift_id='TM',
        seed_processed_kg=14100.0,
        expeller_produced_kg=7250.0,
        oil_produced_kg=5640.0,
        seed_fat_pct=48.78,
        expeller_fat_pct=10.45,
        identified_waste_kg=250.0,
        moisture_loss_kg=850.0,
        notes='Turno TM completado con excelente rendimiento de extraccion.'
    )

    print("Datos de prueba cargados exitosamente.")

# Ejecucion directa
if __name__ == '__main__':
    seed_realistic_shift()
