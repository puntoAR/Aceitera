# Importa datetime para estampa de fecha
import datetime
# Importa conexion a base de datos
from core.database import get_db_connection
# Importa funciones de calculo de rendimiento
from modules.calculations.yield_calc import (
    calculate_mass_yield_pct, calculate_available_oil, calculate_oil_recovery_pct,
    calculate_residual_fat_in_expeller, calculate_classified_mass_balance
)
# Importa logger de eventos
from core.error_logger import log_info, log_error
# Importa funciones horarias oficiales de planta BioBalcarce (Argentina UTC-3)
from core.timezone import get_plant_now_str, get_plant_today_str

# Realiza la conciliacion de turno y guarda el balance de masa en base de datos
def reconcile_shift(shift_id, seed_processed_kg, expeller_produced_kg, oil_produced_kg,
                    seed_fat_pct=45.0, expeller_fat_pct=10.0, identified_waste_kg=0.0,
                    moisture_loss_kg=0.0, notes=''):
    # Calcula el rendimiento masico de aceite (% de la semilla)
    oil_yield_pct = calculate_mass_yield_pct(oil_produced_kg, seed_processed_kg)
    # Calcula el rendimiento masico de expeller (% de la semilla)
    expeller_yield_pct = calculate_mass_yield_pct(expeller_produced_kg, seed_processed_kg)
    # Calcula la eficiencia de recuperacion del aceite disponible contenido en la semilla
    oil_recovery_pct = calculate_oil_recovery_pct(oil_produced_kg, seed_processed_kg, seed_fat_pct)
    # Calcula la masa de grasa residual no extraida en el expeller
    residual_fat_kg = calculate_residual_fat_in_expeller(expeller_produced_kg, expeller_fat_pct)
    # Realiza el balance de masa clasificado
    balance = calculate_classified_mass_balance(
        seed_processed_kg=seed_processed_kg,
        oil_obtained_kg=oil_produced_kg,
        expeller_obtained_kg=expeller_produced_kg,
        solid_waste_kg=identified_waste_kg,
        moisture_removed_kg=moisture_loss_kg
    )
    # Identificador de turno con fecha oficial de planta (ej. 2026-09-26-TM)
    today_str = get_plant_today_str()
    date_shift = f"{today_str}-{shift_id}"
    now_str = get_plant_now_str()
    # Abre conexion para guardar la conciliacion
    with get_db_connection() as conn:
        cursor = conn.execute("""
            INSERT INTO shift_reconciliations (
                date_shift, shift_id, seed_processed_kg, expeller_produced_kg,
                oil_produced_kg, seed_fat_pct, expeller_fat_pct, identified_waste_kg,
                moisture_loss_kg, mass_difference_kg, mass_diff_pct, oil_yield_pct,
                expeller_yield_pct, oil_recovery_pct, residual_fat_kg, notes, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """, (date_shift, shift_id, seed_processed_kg, expeller_produced_kg,
              oil_produced_kg, seed_fat_pct, expeller_fat_pct, identified_waste_kg,
              moisture_loss_kg, balance['unreconciled_diff_kg'], balance['unreconciled_diff_pct'],
              oil_yield_pct, expeller_yield_pct, oil_recovery_pct, residual_fat_kg, notes, now_str))
        conn.commit()
        rec_id = cursor.lastrowid
    # Registra en log la conciliacion
    log_info('YIELD', f'Conciliacion de {date_shift} guardada: Rend Aceite {oil_yield_pct}%, Recup {oil_recovery_pct}%.')
    # Retorna el informe de rendimiento
    return {
        'id': rec_id,
        'date_shift': date_shift,
        'oil_yield_pct': oil_yield_pct,
        'expeller_yield_pct': expeller_yield_pct,
        'oil_recovery_pct': oil_recovery_pct,
        'residual_fat_kg': residual_fat_kg,
        'mass_diff_kg': balance['unreconciled_diff_kg'],
        'mass_diff_pct': balance['unreconciled_diff_pct']
    }

# Obtiene las conciliaciones de turno recientes
def get_recent_reconciliations(limit=20):
    # Abre conexion a base de datos
    with get_db_connection() as conn:
        rows = conn.execute("""
            SELECT * FROM shift_reconciliations
            ORDER BY created_at DESC
            LIMIT ?;
        """, (limit,)).fetchall()
        # Retorna lista de diccionarios
        return [dict(row) for row in rows]

# Obtiene la ultima conciliacion registrada para el dashboard
def get_latest_reconciliation():
    # Abre conexion a base de datos
    with get_db_connection() as conn:
        row = conn.execute("""
            SELECT * FROM shift_reconciliations
            ORDER BY created_at DESC
            LIMIT 1;
        """).fetchone()
        # Retorna diccionario o None si no hay registros
        return dict(row) if row else None
