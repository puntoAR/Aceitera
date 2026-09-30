# Modulo de gestion de migraciones incrementales de base de datos SQLite
# Permite actualizar esquemas y tablas sin perder informacion historica

# Importa sqlite3 para ejecutar sentencias de definicion de datos (DDL)
import sqlite3
# Importa datetime para auditoria de tiempo
import datetime
# Importa re para limpieza robusta de comentarios SQL
import re
# Importa la conexion a base de datos
from core.database import get_db_connection
# Importa el registrador de eventos
from core.error_logger import log_info, log_error

# Asegura que la tabla de control de migraciones exista en la base de datos
def ensure_migrations_table():
    # Abre conexion a la base de datos
    with get_db_connection() as conn:
        # Crea la tabla schema_migrations si no existe
        conn.execute("""
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,           -- Numero secuencial de la migracion
                name TEXT NOT NULL,                    -- Nombre identificador de la migracion
                description TEXT,                      -- Detalle de los cambios de esquema aplicados
                applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP -- Fecha y hora de aplicacion
            );
        """)
        # Confirma la transaccion
        conn.commit()

# Obtiene la lista de versiones de migracion ya aplicadas en la base de datos
def get_applied_migration_versions():
    # Asegura la existencia de la tabla de control
    ensure_migrations_table()
    # Abre conexion para consultar
    with get_db_connection() as conn:
        # Consulta las versiones registradas ordenadas ascendente
        rows = conn.execute("SELECT version FROM schema_migrations ORDER BY version ASC;").fetchall()
        # Retorna el conjunto de versiones aplicadas
        return [row['version'] for row in rows]

# Diccionario de migraciones registradas del sistema
# Cada entrada tiene el numero de version, nombre, descripcion y funcion ejecutora
REGISTERED_MIGRATIONS = [
    {
        'version': 1,
        'name': 'initial_schema_v1_0',
        'description': 'Esquema base de BioBalcarce con 13 tablas iniciales',
        'sql': '-- Migracion base ya consolidada en init_db'
    },
    {
        'version': 2,
        'name': 'add_energy_cost_columns',
        'description': 'Incorporacion de columnas preparadas para consumo energetico y costos futuros',
        'sql': """
            -- Agrega columnas opcionales a shift_reconciliations si no existen
            ALTER TABLE shift_reconciliations ADD COLUMN kwh_consumed REAL DEFAULT 0.0;
            ALTER TABLE shift_reconciliations ADD COLUMN labor_hours REAL DEFAULT 0.0;
        """
    },
    {
        # Version 3 de migracion para sincronizar silos exactos de la planilla BioBalcarce
        'version': 3,
        # Identificador de la migracion
        'name': 'sync_spreadsheet_silos_and_tanks',
        # Descripcion del ajuste
        'description': 'Ajuste de silos de expeller Aereo Verde y Aereo Chapa Rota segun planilla oficial de planta',
        # Script SQL que da de alta los silos aereos y desactiva el generico
        'sql': """
            INSERT OR IGNORE INTO equipment_silos (code, name, product_assigned, diameter_m, sheet_height_m, total_sheets, bottom_cone_height_m, bottom_cone_type, copete_max_height_m, default_ph)
            VALUES ('SILO-EXP-V', 'Silo Aereo Verde (Expeller)', 'expeller', 4.30, 0.99, 3, 2.40, 'cone', 0.99, 22.0);
            INSERT OR IGNORE INTO equipment_silos (code, name, product_assigned, diameter_m, sheet_height_m, total_sheets, bottom_cone_height_m, bottom_cone_type, copete_max_height_m, default_ph)
            VALUES ('SILO-EXP-R', 'Silo Aereo Chapa Rota (Expeller)', 'expeller', 4.30, 0.99, 3, 2.40, 'cone', 0.99, 22.0);
            UPDATE equipment_silos SET is_active = 0 WHERE code = 'SILO-EXP';
        """
    },
    {
        # Version 4 de migracion para soporte de 3 roles, auto-registro, recuperacion de clave, auditoria y errores
        'version': 4,
        # Identificador de la migracion
        'name': 'security_roles_audit_and_errors_v1_1',
        # Descripcion del ajuste
        'description': 'Incorporacion de columnas DNI, telefono, estado de aprobacion, cambio obligatorio de clave, tabla de codigos de recuperacion, log de auditoria y registro de errores de ejecucion',
        # Script SQL que actualiza la estructura de usuarios y crea las tablas de auditoria
        'sql': """
            -- Agrega columnas DNI, telefono, estado de aprobacion y marca de cambio de clave a users
            ALTER TABLE users ADD COLUMN dni TEXT;
            ALTER TABLE users ADD COLUMN phone TEXT;
            ALTER TABLE users ADD COLUMN approval_status TEXT DEFAULT 'aprobado';
            ALTER TABLE users ADD COLUMN must_change_password INTEGER DEFAULT 0;

            -- Actualiza roles preexistentes a los 3 oficiales
            UPDATE users SET role = 'admin_sistema' WHERE username = 'admin';
            UPDATE users SET role = 'usuario' WHERE username IN ('operario', 'laboratorio');

            -- Inserta usuario director/gerente con rol administrador si no existe
            INSERT OR IGNORE INTO users (username, full_name, role, pin, dni, phone, approval_status, must_change_password, is_active)
            VALUES ('gerente', 'Gerencia General (Administrador)', 'administrador', '3333', '20111222', '5492266123456', 'aprobado', 0, 1);

            -- Crea la tabla de codigos de verificacion OTP para recuperacion de clave
            CREATE TABLE IF NOT EXISTS password_reset_codes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                code TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                expires_at TIMESTAMP NOT NULL,
                used INTEGER DEFAULT 0,
                FOREIGN KEY (user_id) REFERENCES users(id)
            );

            -- Crea la tabla de registro de auditoria de actividades del sistema
            CREATE TABLE IF NOT EXISTS audit_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                user_id INTEGER,
                username TEXT,
                role TEXT,
                ip_address TEXT,
                category TEXT NOT NULL,
                action TEXT NOT NULL,
                details TEXT NOT NULL,
                status TEXT DEFAULT 'OK'
            );

            -- Crea la tabla de registro y analisis de errores y excepciones
            CREATE TABLE IF NOT EXISTS system_errors (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                user_id INTEGER,
                username TEXT,
                endpoint TEXT,
                error_type TEXT NOT NULL,
                error_message TEXT NOT NULL,
                traceback TEXT,
                resolved INTEGER DEFAULT 0
            );
        """
    },
    {
        # Version 5 de migracion para soporte de 4 turnos (con Turno Central exclusivo Admin) y carga de camiones de aceite
        'version': 5,
        # Identificador descriptivo
        'name': 'shifts_central_and_oil_truck_dispatches',
        # Detalle de la actualizacion
        'description': 'Incorporacion de columna admin_only a shifts, creacion de Turno Central 08 a 16 hs y tabla oil_truck_dispatches',
        # Script SQL para modificar esquema
        'sql': """
            -- Agrega columna admin_only a la tabla shifts si no existe
            ALTER TABLE shifts ADD COLUMN admin_only INTEGER DEFAULT 0;

            -- Actualiza nombres y rangos de los turnos base
            UPDATE shifts SET name = 'Turno Mañana (06:00 - 14:00)', start_hour = 6, end_hour = 14, admin_only = 0 WHERE id = 'TM';
            UPDATE shifts SET name = 'Turno Tarde (14:00 - 22:00)', start_hour = 14, end_hour = 22, admin_only = 0 WHERE id = 'TT';
            UPDATE shifts SET name = 'Turno Noche (22:00 - 06:00)', start_hour = 22, end_hour = 6, admin_only = 0 WHERE id = 'TN';

            -- Inserta el Turno Central de 08:00 a 16:00 exclusivo para el usuario Administrador del Sistema
            INSERT OR IGNORE INTO shifts (id, name, start_hour, end_hour, is_active, admin_only)
            VALUES ('TC', 'Turno Central (08:00 - 16:00)', 8, 16, 1, 1);

            -- Crea la tabla de control de carga, precintado y despacho de camiones de aceite
            CREATE TABLE IF NOT EXISTS oil_truck_dispatches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,                 -- Identificador unico del despacho
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,         -- Fecha y hora del despacho
                shift_id TEXT NOT NULL,                                -- Turno en que se realiza la carga
                operator_name TEXT NOT NULL,                           -- Analista/operador que certifica la carga
                truck_plate TEXT NOT NULL,                             -- Patente del chasis o camion
                trailer_plate TEXT,                                    -- Patente del acoplado o semirremolque cisterna
                driver_name TEXT NOT NULL,                             -- Nombre y apellido del chofer
                driver_dni TEXT,                                       -- DNI del chofer
                transport_company TEXT,                                -- Empresa de transporte
                destination TEXT,                                      -- Destino / Cliente del lote
                tank_source_id INTEGER,                                -- Tanque del cual se extrajo el aceite (1, 2, 3)
                quantity_kg REAL DEFAULT 0.0,                          -- Kilos netos cargados
                quantity_tons REAL DEFAULT 0.0,                        -- Toneladas netas cargadas
                transport_status TEXT NOT NULL,                        -- Estado: Apto para Carga, Rechazado, En Carga, Precintado, Despachado
                seals_numbers TEXT NOT NULL,                           -- Numeracion y detalle de precintos colocados
                sample_delivered TEXT NOT NULL DEFAULT 'NO',           -- Muestra entregada al chofer (SI / NO)
                sample_code TEXT,                                      -- Identificador de la muestra testigo
                oil_temperature_c REAL,                                -- Temperatura del aceite al momento de carga
                oil_acidity_pct REAL,                                  -- Acidez del aceite despachado
                notes TEXT,                                            -- Observaciones de inspeccion, olor, aspectos
                FOREIGN KEY (shift_id) REFERENCES shifts(id),          -- Vinculo con el turno
                FOREIGN KEY (tank_source_id) REFERENCES equipment_tanks(id) -- Vinculo con tanque de origen
            );
        """
    },
    {
        # Version 6 de migracion para estandarizar el rol 'gerencia'
        'version': 6,
        'name': 'standardize_gerencia_role',
        'description': 'Actualizacion del identificador de rol administrador a gerencia para el nivel de acceso ejecutivo',
        'sql': """
            -- Actualiza roles preexistentes 'administrador' a 'gerencia'
            UPDATE users SET role = 'gerencia' WHERE role = 'administrador';
        """
    },
    {
        # Version 7 de migracion para el modulo de mantenimiento industrial y pañol de repuestos
        'version': 7,
        # Identificador descriptivo de la version
        'name': 'maintenance_and_spare_parts_v1_2',
        # Detalle de la funcionalidad incorporada
        'description': 'Tablas de actividades de mantenimiento (operativas y planificadas), fotografias de reparaciones, stock de repuestos y movimientos de inventario',
        # Sentencias SQL para crear las nuevas tablas si no existen
        'sql': """
            -- Crea la tabla de actividades de mantenimiento
            CREATE TABLE IF NOT EXISTS maintenance_activities (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                category TEXT NOT NULL,
                equipment_tag TEXT,
                priority TEXT NOT NULL DEFAULT 'media',
                status TEXT NOT NULL DEFAULT 'pendiente',
                description TEXT,
                reported_by TEXT NOT NULL,
                assigned_to TEXT,
                scheduled_date TEXT,
                completed_at TIMESTAMP,
                resolution_notes TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            -- Crea la tabla de imagenes de mantenimiento
            CREATE TABLE IF NOT EXISTS maintenance_images (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                activity_id INTEGER NOT NULL,
                filename TEXT NOT NULL,
                caption TEXT,
                uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (activity_id) REFERENCES maintenance_activities(id) ON DELETE CASCADE
            );

            -- Crea la tabla de stock de repuestos e insumos
            CREATE TABLE IF NOT EXISTS spare_parts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT UNIQUE NOT NULL,
                name TEXT NOT NULL,
                category TEXT NOT NULL,
                equipment_assigned TEXT,
                is_consumable INTEGER DEFAULT 0,
                stock_quantity REAL NOT NULL DEFAULT 0.0,
                min_stock REAL NOT NULL DEFAULT 0.0,
                unit TEXT NOT NULL DEFAULT 'unidades',
                location TEXT,
                notes TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            -- Crea la tabla de movimientos de repuestos
            CREATE TABLE IF NOT EXISTS spare_parts_movements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                spare_part_id INTEGER NOT NULL,
                activity_id INTEGER,
                movement_type TEXT NOT NULL,
                quantity REAL NOT NULL,
                operator_name TEXT NOT NULL,
                reason TEXT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (spare_part_id) REFERENCES spare_parts(id)
            );
        """
    },
    {
        # Version 8 de migracion para diagnostico tecnico de errores y excepciones
        'version': 8,
        # Identificador descriptivo de la version
        'name': 'system_errors_detailed_diagnostics',
        # Detalle de la funcionalidad incorporada
        'description': 'Incorporacion de columnas de diagnostico a system_errors: origin_file, origin_line, origin_func, origin_code, resolved_at',
        # Sentencias SQL para agregar columnas de diagnostico
        'sql': """
            -- Agrega columna para el archivo donde se origino la excepcion
            ALTER TABLE system_errors ADD COLUMN origin_file TEXT;
            -- Agrega columna para el numero de linea exacto del fallo
            ALTER TABLE system_errors ADD COLUMN origin_line INTEGER;
            -- Agrega columna para el metodo o funcion donde ocurrio el error
            ALTER TABLE system_errors ADD COLUMN origin_func TEXT;
            -- Agrega columna para la instruccion de codigo causante
            ALTER TABLE system_errors ADD COLUMN origin_code TEXT;
            -- Agrega columna para registrar la marca de tiempo de resolucion
            ALTER TABLE system_errors ADD COLUMN resolved_at TIMESTAMP;
        """
    },
    {
        # Version 9: Ajuste de marcas temporales grabadas en UTC a horario oficial Balcarce (UTC-3)
        'version': 9,
        'name': 'adjust_legacy_utc_timestamps_to_art',
        'description': 'Ajuste de registros grabados en UTC en servidores en la nube a horario local de planta Balcarce (-3 horas)',
        'sql': """
            -- Corrige pesadas de produccion grabadas con hora de servidor UTC
            UPDATE production_weighings
            SET timestamp = datetime(timestamp, '-3 hours')
            WHERE timestamp >= '2026-09-26 13:00:00' AND timestamp <= '2026-09-26 23:59:59';

            -- Corrige paradas de linea grabadas con hora de servidor UTC
            UPDATE line_stops
            SET start_time = datetime(start_time, '-3 hours')
            WHERE start_time >= '2026-09-26 13:00:00' AND start_time <= '2026-09-26 23:59:59';

            -- Corrige analisis de laboratorio grabados con hora UTC
            UPDATE lab_analyses
            SET timestamp = datetime(timestamp, '-3 hours')
            WHERE timestamp >= '2026-09-26 13:00:00' AND timestamp <= '2026-09-26 23:59:59';

            -- Corrige mediciones de tanques grabadas con hora UTC
            UPDATE inventory_tanks
            SET timestamp = datetime(timestamp, '-3 hours')
            WHERE timestamp >= '2026-09-26 13:00:00' AND timestamp <= '2026-09-26 23:59:59';

            -- Corrige mediciones de silos grabadas con hora UTC
            UPDATE inventory_silos
            SET timestamp = datetime(timestamp, '-3 hours')
            WHERE timestamp >= '2026-09-26 13:00:00' AND timestamp <= '2026-09-26 23:59:59';

            -- Corrige despachos de camiones grabados con hora UTC
            UPDATE oil_truck_dispatches
            SET timestamp = datetime(timestamp, '-3 hours')
            WHERE timestamp >= '2026-09-26 13:00:00' AND timestamp <= '2026-09-26 23:59:59';
        """
    },
    {
        # Version 10: Separacion de Prensa 1 y Prensa 2 en analitica de laboratorio
        'version': 10,
        'name': 'add_press_number_to_lab',
        'description': 'Incorporacion de columna press_number para aislar determinaciones de Prensa 1 (indicativo) y Prensa 2 (producto final relevante)',
        'sql': """
            -- Agrega columna press_number con valor por defecto 2 (Prensa 2 es el producto terminado)
            ALTER TABLE lab_analyses ADD COLUMN press_number INTEGER DEFAULT 2;

            -- Normaliza registros anteriores: si el punto de muestreo menciona 'prensa 1' o 'p1', asigna 1
            UPDATE lab_analyses
            SET press_number = 1
            WHERE product = 'expeller' AND (
                LOWER(sampling_point) LIKE '%prensa 1%'
                OR LOWER(sampling_point) LIKE '%prensa1%'
                OR LOWER(sampling_point) LIKE '%p1%'
            );
        """
    },
    {
        # Version 11: Tablas para Balanza de Camiones y Licenciamiento Programable
        'version': 11,
        'name': 'truck_scale_weighings_and_licensing_system',
        'description': 'Creacion de tablas truck_scale_weighings para importacion/exportacion de balanza y system_licensing_config para control de planes y feature-gating',
        'sql': """
            -- Tabla de pesadas y movimientos de balanza de camiones
            CREATE TABLE IF NOT EXISTS truck_scale_weighings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticket_number TEXT,
                weigh_date TEXT NOT NULL,
                operation_type TEXT NOT NULL,
                product TEXT NOT NULL,
                truck_plate TEXT,
                trailer_plate TEXT,
                transport_company TEXT,
                driver_name TEXT,
                driver_dni TEXT,
                gross_weight_kg REAL DEFAULT 0.0,
                tare_weight_kg REAL DEFAULT 0.0,
                net_weight_kg REAL DEFAULT 0.0,
                net_weight_tons REAL DEFAULT 0.0,
                origin TEXT,
                destination TEXT,
                seals_numbers TEXT,
                notes TEXT,
                operator_name TEXT,
                shift_id TEXT,
                sync_inventory INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            -- Tabla de configuracion de licenciamiento y limitaciones programables
            CREATE TABLE IF NOT EXISTS system_licensing_config (
                id INTEGER PRIMARY KEY,
                license_mode TEXT DEFAULT 'libre_uso',
                plan_name TEXT DEFAULT 'Plan Libre Uso Anual',
                activation_date TEXT,
                expiration_date TEXT,
                max_active_users INTEGER DEFAULT 0,
                block_dashboard INTEGER DEFAULT 0,
                block_data_entry INTEGER DEFAULT 0,
                block_reports INTEGER DEFAULT 0,
                block_updates INTEGER DEFAULT 0,
                custom_notice_message TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_by TEXT
            );

            -- Inserta configuracion inicial de 1 año de libre uso si no existe
            INSERT OR IGNORE INTO system_licensing_config (
                id, license_mode, plan_name, activation_date, expiration_date,
                max_active_users, block_dashboard, block_data_entry, block_reports, block_updates,
                custom_notice_message, updated_by
            ) VALUES (
                1, 'libre_uso', 'Plan Libre Uso por 1 Año (puntoAR)',
                '2026-09-01', '2027-09-01',
                0, 0, 0, 0, 0,
                'Uso autorizado para BioBalcarce provisto por puntoAR.', 'admin_sistema'
            );
        """
    },
    {
        'version': 14,
        'name': 'v14_time_slots_and_maintenance_role',
        'description': 'Incorpora franja horaria oficial (TM, TT, TN) a pesadas y análisis, soporte de módulos permitidos y alta de rol Mantenimiento',
        'sql': """
            -- Agrega columna allowed_modules a usuarios
            ALTER TABLE users ADD COLUMN allowed_modules TEXT DEFAULT NULL;

            -- Agrega columna time_slot a pesadas de produccion
            ALTER TABLE production_weighings ADD COLUMN time_slot TEXT DEFAULT NULL;

            -- Agrega columna time_slot a determinaciones de laboratorio
            ALTER TABLE lab_analyses ADD COLUMN time_slot TEXT DEFAULT NULL;

            -- Inserta usuario tecnico de mantenimiento por defecto si no existe
            INSERT OR IGNORE INTO users (username, full_name, role, pin, dni, phone, approval_status, must_change_password, is_active)
            VALUES ('mantenimiento', 'Técnico de Mantenimiento', 'mantenimiento', '4444', '50000000', '5492266000005', 'aprobado', 0, 1);
        """,
        'callback': lambda conn: backfill_time_slots(conn)
    },
    {
        # Version 15: Independizacion de fecha de muestra respecto a fecha de carga
        'version': 15,
        # Identificador de la migracion
        'name': 'v15_sample_date_and_shift_identification',
        # Descripcion del ajuste estructural
        'description': 'Incorpora sample_date a determinaciones de laboratorio y pesadas de produccion para identificar la fecha y turno real de la muestra',
        # Sentencias SQL para agregar columnas si no existen
        'sql': """
            -- Agrega columna sample_date a determinaciones de laboratorio
            ALTER TABLE lab_analyses ADD COLUMN sample_date TEXT DEFAULT NULL;

            -- Agrega columna sample_date a pesadas de produccion de velocidad de linea
            ALTER TABLE production_weighings ADD COLUMN sample_date TEXT DEFAULT NULL;
        """,
        # Callback para rellenar sample_date en datos historicos existentes
        'callback': lambda conn: backfill_sample_dates(conn)
    },
    {
        # Version 16: Columnas estandar de balanza para compatibilidad y exportacion
        'version': 16,
        # Identificador de la migracion
        'name': 'v16_weighbridge_standard_columns',
        # Descripcion del ajuste
        'description': 'Incorpora 27 columnas estandar de balanza de camiones para total compatibilidad y exportacion Excel',
        # Sentencias SQL para agregar columnas faltantes a truck_scale_weighings
        'sql': """
            -- Agrega fecha de egreso
            ALTER TABLE truck_scale_weighings ADD COLUMN exit_date TEXT DEFAULT NULL;
            -- Agrega fecha de ingreso
            ALTER TABLE truck_scale_weighings ADD COLUMN entry_date TEXT DEFAULT NULL;
            -- Agrega cliente
            ALTER TABLE truck_scale_weighings ADD COLUMN client TEXT DEFAULT NULL;
            -- Agrega destinatario
            ALTER TABLE truck_scale_weighings ADD COLUMN recipient TEXT DEFAULT NULL;
            -- Agrega procedencia o destino
            ALTER TABLE truck_scale_weighings ADD COLUMN origin_destination TEXT DEFAULT NULL;
            -- Agrega ID de usuario
            ALTER TABLE truck_scale_weighings ADD COLUMN user_id_code TEXT DEFAULT NULL;
            -- Agrega peso egreso
            ALTER TABLE truck_scale_weighings ADD COLUMN exit_weight_kg REAL DEFAULT 0.0;
            -- Agrega peso ingreso
            ALTER TABLE truck_scale_weighings ADD COLUMN entry_weight_kg REAL DEFAULT 0.0;
            -- Agrega exportador
            ALTER TABLE truck_scale_weighings ADD COLUMN exporter TEXT DEFAULT NULL;
            -- Agrega tara manual
            ALTER TABLE truck_scale_weighings ADD COLUMN manual_tare TEXT DEFAULT 'NO';
            -- Agrega nacionalidad chofer
            ALTER TABLE truck_scale_weighings ADD COLUMN driver_nationality TEXT DEFAULT 'Argentina';
            -- Agrega bultos
            ALTER TABLE truck_scale_weighings ADD COLUMN packages TEXT DEFAULT NULL;
            -- Agrega aduana
            ALTER TABLE truck_scale_weighings ADD COLUMN customs TEXT DEFAULT NULL;
            -- Agrega LOT
            ALTER TABLE truck_scale_weighings ADD COLUMN lot TEXT DEFAULT NULL;
            -- Agrega pesada unica
            ALTER TABLE truck_scale_weighings ADD COLUMN single_weighing TEXT DEFAULT 'NO';
            -- Agrega destinacion
            ALTER TABLE truck_scale_weighings ADD COLUMN customs_destination TEXT DEFAULT NULL;
        """,
        # Callback para retrocompatibilidad y relleno de filas existentes
        'callback': lambda conn: backfill_weighbridge_standard_columns(conn)
    }
]

# Funcion de retro-compatibilidad para rellenar columnas estandar de balanza en registros preexistentes
def backfill_weighbridge_standard_columns(conn):
    # Bloque de captura segura
    try:
        # Consulta pesadas existentes
        rows = conn.execute("SELECT id, weigh_date, operation_type, gross_weight_kg, tare_weight_kg, net_weight_kg, origin, destination, operator_name FROM truck_scale_weighings;").fetchall()
        # Itera sobre cada registro
        for r in rows:
            # Obtiene id
            rid = r['id'] if isinstance(r, dict) else r[0]
            # Obtiene fecha operativa
            w_date = r['weigh_date'] if isinstance(r, dict) else r[1]
            # Obtiene operacion
            op = r['operation_type'] if isinstance(r, dict) else r[2]
            # Obtiene peso bruto
            gross = float((r['gross_weight_kg'] if isinstance(r, dict) else r[3]) or 0.0)
            # Obtiene peso tara
            tare = float((r['tare_weight_kg'] if isinstance(r, dict) else r[4]) or 0.0)
            # Obtiene peso neto
            net = float((r['net_weight_kg'] if isinstance(r, dict) else r[5]) or 0.0)
            # Obtiene origen
            orig = (r['origin'] if isinstance(r, dict) else r[6]) or ''
            # Obtiene destino
            dest = (r['destination'] if isinstance(r, dict) else r[7]) or ''
            # Procedencia o destino consolidado
            orig_dest = dest or orig or 'Planta BioBalcarce'
            # En egreso: entra vacio (tara) y sale cargado (bruto)
            if op == 'egreso':
                # Peso al ingreso fue la tara
                p_in = tare if tare > 0 else (gross - net if gross > net else 0.0)
                # Peso al egreso fue el bruto
                p_out = gross if gross > 0 else (p_in + net)
                # Fecha de egreso es weigh_date
                f_out = w_date
                # Fecha de ingreso se asigna weigh_date
                f_in = w_date
            # En ingreso: entra cargado (bruto) y sale vacio (tara)
            else:
                # Peso al ingreso fue el bruto
                p_in = gross if gross > 0 else net
                # Peso al egreso fue la tara
                p_out = tare if tare > 0 else (p_in - net if p_in > net else 0.0)
                # Fecha de ingreso es weigh_date
                f_in = w_date
                # Fecha de egreso es weigh_date
                f_out = w_date
            # Actualiza fila con valores calculados
            conn.execute("""
                UPDATE truck_scale_weighings
                SET entry_date = COALESCE(entry_date, ?),
                    exit_date = COALESCE(exit_date, ?),
                    entry_weight_kg = CASE WHEN entry_weight_kg IS NULL OR entry_weight_kg = 0 THEN ? ELSE entry_weight_kg END,
                    exit_weight_kg = CASE WHEN exit_weight_kg IS NULL OR exit_weight_kg = 0 THEN ? ELSE exit_weight_kg END,
                    client = COALESCE(client, ?),
                    recipient = COALESCE(recipient, ?),
                    origin_destination = COALESCE(origin_destination, ?),
                    user_id_code = COALESCE(user_id_code, '1'),
                    manual_tare = COALESCE(manual_tare, 'NO'),
                    driver_nationality = COALESCE(driver_nationality, 'Argentina'),
                    single_weighing = COALESCE(single_weighing, 'NO')
                WHERE id = ?;
            """, (f_in, f_out, p_in, p_out, dest, dest, orig_dest, rid))
    # Captura errores
    except Exception as e:
        # Registra advertencia en bitacora
        log_error('MIGRATIONS', 'Aviso al rellenar columnas estandar de balanza', e)

# Funcion de retro-compatibilidad para calcular y rellenar time_slots en registros historicos
def backfill_time_slots(conn):
    from core.timezone import determine_time_slot
    # Backfill pesadas de produccion
    try:
        rows = conn.execute("SELECT id, timestamp FROM production_weighings WHERE time_slot IS NULL OR time_slot = '';").fetchall()
        for r in rows:
            ts = r['timestamp'] if isinstance(r, dict) else r[1]
            rid = r['id'] if isinstance(r, dict) else r[0]
            slot = determine_time_slot(ts)['time_slot']
            conn.execute("UPDATE production_weighings SET time_slot = ? WHERE id = ?;", (slot, rid))
    except Exception as e:
        log_error('MIGRATIONS', 'Aviso al backfillear time_slot en production_weighings', e)

    # Backfill analisis de laboratorio
    try:
        rows = conn.execute("SELECT id, timestamp FROM lab_analyses WHERE time_slot IS NULL OR time_slot = '';").fetchall()
        for r in rows:
            ts = r['timestamp'] if isinstance(r, dict) else r[1]
            rid = r['id'] if isinstance(r, dict) else r[0]
            slot = determine_time_slot(ts)['time_slot']
            conn.execute("UPDATE lab_analyses SET time_slot = ? WHERE id = ?;", (slot, rid))
    except Exception as e:
        log_error('MIGRATIONS', 'Aviso al backfillear time_slot en lab_analyses', e)

# Funcion de retro-compatibilidad para calcular y rellenar sample_date en registros historicos existentes
def backfill_sample_dates(conn):
    # Importa funcion de determinacion de jornada operativa de planta
    from core.timezone import determine_time_slot
    # Intento de backfill en determinaciones de laboratorio
    try:
        # Consulta analisis que no tengan sample_date cargado
        rows = conn.execute("SELECT id, timestamp FROM lab_analyses WHERE sample_date IS NULL OR sample_date = '';").fetchall()
        # Itera sobre cada registro sin fecha de muestra
        for r in rows:
            # Obtiene timestamp
            ts = r['timestamp'] if isinstance(r, dict) else r[1]
            # Obtiene id del registro
            rid = r['id'] if isinstance(r, dict) else r[0]
            # Extrae la fecha operativa correspondiente a la estampa
            op_date = determine_time_slot(ts)['operational_date']
            # Actualiza el registro con la fecha calculada
            conn.execute("UPDATE lab_analyses SET sample_date = ? WHERE id = ?;", (op_date, rid))
    # Captura posibles excepciones sin interrumpir la migracion
    except Exception as e:
        # Registra advertencia en bitacora de errores
        log_error('MIGRATIONS', 'Aviso al backfillear sample_date en lab_analyses', e)

    # Intento de backfill en pesadas de produccion
    try:
        # Consulta pesadas que no posean sample_date cargado
        rows = conn.execute("SELECT id, timestamp FROM production_weighings WHERE sample_date IS NULL OR sample_date = '';").fetchall()
        # Itera sobre cada pesada historica
        for r in rows:
            # Obtiene timestamp
            ts = r['timestamp'] if isinstance(r, dict) else r[1]
            # Obtiene id
            rid = r['id'] if isinstance(r, dict) else r[0]
            # Extrae la fecha operativa correspondiente
            op_date = determine_time_slot(ts)['operational_date']
            # Actualiza el registro con la fecha operativa
            conn.execute("UPDATE production_weighings SET sample_date = ? WHERE id = ?;", (op_date, rid))
    # Captura posibles errores en pesadas
    except Exception as e:
        # Registra advertencia en bitacora
        log_error('MIGRATIONS', 'Aviso al backfillear sample_date en production_weighings', e)

# Ejecuta una migracion especifica de forma segura
def apply_single_migration(migration):
    # Version de la migracion
    version = migration['version']
    # Nombre descriptivo
    name = migration['name']
    # SQL a ejecutar
    sql_script = migration['sql'].strip()
    # Callback opcional en Python
    callback = migration.get('callback')
    # Registra inicio en log
    log_info('MIGRATIONS', f'Aplicando migracion v{version}: {name}...')
    # Abre conexion para ejecutar los cambios
    with get_db_connection() as conn:
        # Si la migracion contiene texto SQL para procesar
        if sql_script:
            # Divide el script en sentencias individuales delimitadas por punto y coma
            for statement in sql_script.split(';'):
                # Filtra comentarios en linea y de cabecera usando expresiones regulares
                active_lines = []
                # Itera sobre cada renglon de la sentencia
                for line in statement.splitlines():
                    # Elimina cualquier comentario iniciado con doble guion hasta el fin de linea
                    clean_line = re.sub(r'--.*$', '', line).strip()
                    # Si el renglon contiene codigo SQL util
                    if clean_line:
                        # Agrega a la lista de lineas activas
                        active_lines.append(clean_line)
                # Si la sentencia contiene codigo SQL efectivo
                if active_lines:
                    # Une las lineas SQL filtradas en una sola instruccion
                    statement_clean = ' '.join(active_lines)
                    try:
                        # Ejecuta la sentencia en SQLite
                        conn.execute(statement_clean)
                    except Exception as op_err:
                        # Si la columna ya fue agregada previamente, ignora el error de duplicado
                        if "duplicate column" in str(op_err).lower():
                            pass
                        else:
                            # Propaga cualquier otro error de base de datos
                            raise op_err
        # Ejecuta callback Python si fue especificado
        if callback and callable(callback):
            callback(conn)

        # Registra la migracion como aplicada en la tabla schema_migrations
        conn.execute("""
            INSERT OR REPLACE INTO schema_migrations (version, name, description)
            VALUES (?, ?, ?);
        """, (version, name, migration.get('description', '')))
        # Confirma los cambios
        conn.commit()
    # Registra en log la finalizacion exitosa
    log_info('MIGRATIONS', f'Migracion v{version} ({name}) aplicada exitosamente.')

# Ejecuta todas las migraciones pendientes que no hayan sido aplicadas aun
def apply_pending_migrations():
    # Asegura que la tabla de control exista
    ensure_migrations_table()
    # Obtiene las versiones ya aplicadas
    applied = get_applied_migration_versions()
    # Contador de migraciones ejecutadas
    applied_count = 0
    # Itera sobre las migraciones registradas
    for mig in REGISTERED_MIGRATIONS:
        # Si la migracion actual no ha sido aplicada
        if mig['version'] not in applied:
            # Aplica la migracion
            apply_single_migration(mig)
            # Incrementa el contador
            applied_count += 1
    # Retorna la cantidad de migraciones aplicadas
    return applied_count

# Obtiene el historial completo de migraciones para la interfaz web
def get_migration_history():
    # Asegura la existencia de la tabla
    ensure_migrations_table()
    # Abre conexion
    with get_db_connection() as conn:
        rows = conn.execute("SELECT * FROM schema_migrations ORDER BY version DESC;").fetchall()
        return [dict(row) for row in rows]
