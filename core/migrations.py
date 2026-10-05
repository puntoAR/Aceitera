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
    },
    {
        # Version 17: Normalizacion de fechas de balanza para filtros y estadisticas de pesadas
        'version': 17,
        # Identificador de la migracion
        'name': 'v17_normalize_weighbridge_dates',
        # Descripcion del ajuste
        'description': 'Normaliza fechas de báscula en formato ISO YYYY-MM-DD HH:MM:SS para garantizar filtrado por rangos y KPIs reactivos',
        # Script SQL para actualizar fechas con slash o guiones en SQLite y Turso
        'sql': """
            -- Actualiza weigh_date con formato DD/MM/YYYY a YYYY-MM-DD
            UPDATE truck_scale_weighings
            SET weigh_date = CASE
                WHEN weigh_date LIKE '__/__/____%'
                  THEN substr(weigh_date, 7, 4) || '-' || substr(weigh_date, 4, 2) || '-' || substr(weigh_date, 1, 2) || substr(weigh_date, 11)
                WHEN weigh_date LIKE '_/__/____%'
                  THEN substr(weigh_date, 6, 4) || '-' || substr(weigh_date, 3, 2) || '-0' || substr(weigh_date, 1, 1) || substr(weigh_date, 10)
                WHEN weigh_date LIKE '__-__-____%'
                  THEN substr(weigh_date, 7, 4) || '-' || substr(weigh_date, 4, 2) || '-' || substr(weigh_date, 1, 2) || substr(weigh_date, 11)
                ELSE weigh_date
            END
            WHERE weigh_date LIKE '%/%' OR (weigh_date LIKE '%-%' AND substr(weigh_date, 3, 1) = '-');

            -- Actualiza entry_date con formato DD/MM/YYYY a YYYY-MM-DD
            UPDATE truck_scale_weighings
            SET entry_date = CASE
                WHEN entry_date LIKE '__/__/____%'
                  THEN substr(entry_date, 7, 4) || '-' || substr(entry_date, 4, 2) || '-' || substr(entry_date, 1, 2) || substr(entry_date, 11)
                WHEN entry_date LIKE '_/__/____%'
                  THEN substr(entry_date, 6, 4) || '-' || substr(entry_date, 3, 2) || '-0' || substr(entry_date, 1, 1) || substr(entry_date, 10)
                WHEN entry_date LIKE '__-__-____%'
                  THEN substr(entry_date, 7, 4) || '-' || substr(entry_date, 4, 2) || '-' || substr(entry_date, 1, 2) || substr(entry_date, 11)
                ELSE entry_date
            END
            WHERE entry_date LIKE '%/%' OR (entry_date LIKE '%-%' AND substr(entry_date, 3, 1) = '-');

            -- Actualiza exit_date con formato DD/MM/YYYY a YYYY-MM-DD
            UPDATE truck_scale_weighings
            SET exit_date = CASE
                WHEN exit_date LIKE '__/__/____%'
                  THEN substr(exit_date, 7, 4) || '-' || substr(exit_date, 4, 2) || '-' || substr(exit_date, 1, 2) || substr(exit_date, 11)
                WHEN exit_date LIKE '_/__/____%'
                  THEN substr(exit_date, 6, 4) || '-' || substr(exit_date, 3, 2) || '-0' || substr(exit_date, 1, 1) || substr(exit_date, 10)
                WHEN exit_date LIKE '__-__-____%'
                  THEN substr(exit_date, 7, 4) || '-' || substr(exit_date, 4, 2) || '-' || substr(exit_date, 1, 2) || substr(exit_date, 11)
                ELSE exit_date
            END
            WHERE exit_date LIKE '%/%' OR (exit_date LIKE '%-%' AND substr(exit_date, 3, 1) = '-');
        """,
        # Callback en Python para conversion exhaustiva de fechas y casos especiales
        'callback': lambda conn: backfill_normalize_weighbridge_dates(conn) # Normaliza fechas
    }, # Fin de migracion 17
    { # Definicion de migracion 18
        # Version 18: Indices de ordenamiento numerico y busqueda de tickets de balanza
        'version': 18, # Version 18
        # Identificador de la migracion
        'name': 'v18_weighbridge_ticket_indices', # Nombre
        # Descripcion
        'description': 'Indices de optimizacion para busqueda, ordenamiento numerico de tickets y fechas de pesadas de balanza', # Descripcion
        # Script SQL para indices
        'sql': """
            -- Indice para acelerar busqueda y ordenamiento por numero de ticket
            CREATE INDEX IF NOT EXISTS idx_weighings_ticket ON truck_scale_weighings(ticket_number);
            -- Indice compuesto para fechas de egreso e ingreso de balanza
            CREATE INDEX IF NOT EXISTS idx_weighings_dates ON truck_scale_weighings(weigh_date, exit_date, entry_date);
        """, # Sentencias SQL
        # Callback opcional en Python
        'callback': None # Sin callback
    }, # Fin migracion 18
    { # Definicion de migracion 19
        # Version 19: Reparacion de tickets y consistencia de pesadas historicas de balanza
        'version': 19, # Version 19
        # Identificador de la migracion
        'name': 'v19_repair_weighbridge_legacy_tickets', # Nombre
        # Descripcion del ajuste
        'description': 'Repara numeros de ticket faltantes en pesadas historicas (tickets 1000 a 1012), metadatos de transporte y orden cronologico ascendente', # Descripcion
        # Script SQL para asignar tickets a filas preexistentes sin ticket
        'sql': """
            -- Asigna el numero de ticket secuencial a las pesadas historicas del archivo original
            UPDATE truck_scale_weighings
            SET ticket_number = CAST(1228 - id AS TEXT)
            WHERE (ticket_number IS NULL OR ticket_number = '') AND id BETWEEN 1 AND 228;

            -- Si todavia quedara algun registro sin ticket posterior a la fila 228, asigna su id
            UPDATE truck_scale_weighings
            SET ticket_number = CAST(id AS TEXT)
            WHERE ticket_number IS NULL OR ticket_number = '';
        """, # Sentencias SQL
        # Callback opcional en Python para restaurar metadatos especificos de las filas historicas
        'callback': lambda conn: backfill_repair_weighbridge_tickets(conn) # Callback reparador
    }, # Fin migracion 19
    { # Definicion de migracion 20
        # Version 20: Asegurar silos y tanques activos en planta
        'version': 20, # Version 20
        # Identificador de la migracion
        'name': 'v20_ensure_active_equipment', # Nombre
        # Descripcion del ajuste
        'description': 'Asegura que los 7 silos y 3 tanques oficiales de planta BioBalcarce se encuentren activos',
        # Script SQL para reactivar equipos
        'sql': """
            -- Reactiva los 7 silos oficiales de planta en caso de haber sido desactivados inadvertidamente
            UPDATE equipment_silos
            SET is_active = 1
            WHERE code IN ('SILO-01', 'SILO-02', 'SILO-03', 'SILO-04', 'SILO-05', 'SILO-EXP-V', 'SILO-EXP-R');

            -- Reactiva los 3 tanques oficiales de planta
            UPDATE equipment_tanks
            SET is_active = 1
            WHERE code IN ('TK-01', 'TK-02', 'TK-03');
        """,
        'callback': None
    }, # Fin migracion 20
    {
        # Version 21: Persistencia robusta de fotografias de mantenimiento en base de datos
        'version': 21, # Version 21
        'name': 'v21_maintenance_images_data_persistence', # Nombre
        'description': 'Incorpora columnas image_data (base64) y mime_type a maintenance_images para almacenamiento permanente y resiliente en entornos serverless', # Descripcion
        'sql': """
            -- Agrega columna image_data para almacenar la imagen optimizada en base64
            ALTER TABLE maintenance_images ADD COLUMN image_data TEXT DEFAULT NULL;
            -- Agrega columna mime_type para el tipo de contenido
            ALTER TABLE maintenance_images ADD COLUMN mime_type TEXT DEFAULT 'image/jpeg';
        """, # SQL
        'callback': None # Sin callback
    }, # Fin migracion 21
    { # Abre definicion migracion 22
        # Version 22: Sincronizacion exhaustiva de fotografias de mantenimiento y recuperacion multi-PC
        'version': 22, # Version 22
        # Nombre descriptivo
        'name': 'v22_maintenance_images_backfill_and_sync', # Nombre
        # Detalle de la migracion
        'description': 'Sincroniza y rellena columnas image_data y mime_type escaneando directorios locales y estandarizando persistencia para todas las PCs', # Descripcion
        # Script SQL para asegurar indices
        'sql': """
            -- Crea indice por actividad para acelerar busqueda de fotos
            CREATE INDEX IF NOT EXISTS idx_maint_images_activity ON maintenance_images(activity_id);
        """, # Sentencias SQL
        # Callback para recuperar archivos de disco y poblar image_data
        'callback': lambda conn: backfill_sync_disk_and_cloud_images(conn) # Callback
    }, # Fin migracion 22
    { # Abre definicion migracion 23
        # Version 23: Identificacion fehaciente de usuario en produccion y filtrado de paradas por fecha en curso
        'version': 23, # Version 23
        # Nombre identificador de la migracion
        'name': 'v23_fix_production_operator_and_stops_attribution', # Nombre
        # Detalle de la migracion
        'description': 'Identificacion de usuario real que carga pesadas y paradas en produccion, retro-atribucion de muestras del 2/10 hacia Javier y soporte de filtrado cronologico de paradas por fecha en curso', # Descripcion
        # Sentencias SQL para asegurar indices de fecha en produccion
        'sql': """
            -- Asegura indice por fecha y turno en paradas de linea para agilizar filtrado diario
            CREATE INDEX IF NOT EXISTS idx_line_stops_date ON line_stops(start_time);
            -- Asegura indice por fecha de muestra en pesadas de produccion
            CREATE INDEX IF NOT EXISTS idx_prod_weighings_sample_date ON production_weighings(sample_date);
        """, # Sentencias SQL
        # Callback Python para retro-atribuir muestras de produccion al usuario real
        'callback': lambda conn: backfill_production_operator_attribution(conn) # Callback
    }, # Fin migracion 23
    { # Abre definicion migracion 24
        # Version 24: Calibracion geometrica y de densidad de silos de planta
        'version': 24,
        'name': 'v24_calibrate_silos_geometry_and_expeller_density',
        'description': 'Calibración de altura de cono (2.00m) y copete (2.00m) en Silo 3 y 4, cono Silo Verde (2.50m) y Chapa Rota (1.00m), y ajuste de densidad aparente real de expeller (415 kg/m3)',
        'sql': """
            -- Actualiza Silo 1 con copete maximo de 1.00m
            UPDATE equipment_silos SET copete_max_height_m = 1.00 WHERE code = 'SILO-01' AND (copete_max_height_m IS NULL OR copete_max_height_m = 0.0);
            -- Actualiza Silo 3 con dimensiones tecnicas de fabrica
            UPDATE equipment_silos SET bottom_cone_height_m = 2.00, copete_max_height_m = 2.00 WHERE code = 'SILO-03';
            -- Actualiza Silo 4 con dimensiones tecnicas de fabrica
            UPDATE equipment_silos SET bottom_cone_height_m = 2.00, copete_max_height_m = 2.00 WHERE code = 'SILO-04';
            -- Actualiza Silo Aereo Verde con cono real de 2.50m y densidad de expeller de 415 kg/m3 (PH 41.5)
            UPDATE equipment_silos SET bottom_cone_height_m = 2.50, default_ph = 41.5 WHERE code = 'SILO-EXP-V';
            -- Actualiza Silo Aereo Chapa Rota con cono real de 1.00m y densidad de expeller de 415 kg/m3 (PH 41.5)
            UPDATE equipment_silos SET bottom_cone_height_m = 1.00, default_ph = 41.5 WHERE code = 'SILO-EXP-R';
        """,
        'callback': lambda conn: calibrate_silos_and_backfill_readings(conn)
    } # Fin migracion 24
] # Fin REGISTERED_MIGRATIONS


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

# Funcion para reparar tickets historicos y restaurar datos de transportista y fechas en filas 216-228
def backfill_repair_weighbridge_tickets(conn): # Funcion reparadora de pesadas historicas
    # Bloque de proteccion ante excepciones
    try: # Inicia bloque protegido
        # Diccionario con los datos completos de las filas historicas 216 a 228 del archivo original
        legacy_rows = { # Diccionario de filas historicas
            216: { # Fila 216 correspondiente al ticket 1012
                'ticket_number': '1012', # Numero de ticket 1012
                'exit_date': '2026-04-28 10:02:27', # Fecha de egreso
                'entry_date': '2026-04-28 11:44:00', # Fecha de ingreso
                'product': 'aceite', # Producto aceite
                'client': 'SEDA', # Cliente SEDA
                'transport_company': 'TRANSPORTI', # Transportista
                'recipient': 'SEDA', # Destinatario
                'truck_plate': 'JJY909', # Patente chasis
                'trailer_plate': 'SWA625', # Patente acoplado
                'driver_name': 'LIEJFLDT JORGE', # Chofer
                'user_id_code': '19', # ID Usuario
                'exit_weight_kg': 41160.0, # Peso egreso kg
                'entry_weight_kg': 17400.0, # Peso ingreso kg
                'net_weight_kg': 23760.0, # Peso neto kg
                'net_weight_tons': 23.76 # Peso neto tons
            }, # Fin fila 216
            217: { # Fila 217 correspondiente al ticket 1011
                'ticket_number': '1011', # Numero de ticket 1011
                'product': 'semilla', # Producto semilla
                'client': 'AGROINDUSTRIAL COSANIC S.R.L.', # Cliente Cosanic
                'transport_company': 'AGROINDUSTRIAL COSANIC S.R.L.', # Transportista
                'recipient': 'AGROINDUSTRIAL COSANIC S.R.L.' # Destinatario
            }, # Fin fila 217
            218: { # Fila 218 correspondiente al ticket 1010
                'ticket_number': '1010', # Numero de ticket 1010
                'exit_date': '2026-04-27 01:12:33', # Fecha de egreso
                'entry_date': '2026-04-27 11:11:00', # Fecha de ingreso
                'product': 'aceite', # Producto aceite
                'client': 'SEDA', # Cliente SEDA
                'transport_company': 'TRANSPORTE EL LOCO', # Transportista
                'recipient': 'JJY909', # Destinatario
                'truck_plate': 'JJY909', # Patente chasis
                'trailer_plate': 'SWA625', # Patente acoplado
                'driver_name': 'JORGE LIEJFLDT', # Chofer
                'user_id_code': '3', # ID Usuario
                'exit_weight_kg': 48920.0, # Peso egreso kg
                'entry_weight_kg': 17740.0, # Peso ingreso kg
                'net_weight_kg': 31180.0, # Peso neto kg
                'net_weight_tons': 31.18 # Peso neto tons
            }, # Fin fila 218
            219: { # Fila 219 correspondiente al ticket 1009
                'ticket_number': '1009', # Numero de ticket 1009
                'product': 'expeller', # Producto expeller
                'client': 'ZARATE MAURICIO', # Cliente Zarate
                'transport_company': 'ZARATE MAURICIO', # Transportista
                'recipient': 'ZARATE MAURICIO' # Destinatario
            }, # Fin fila 219
            220: { # Fila 220 correspondiente al ticket 1008
                'ticket_number': '1008', # Numero de ticket 1008
                'exit_date': '2026-04-25 08:45:31', # Fecha egreso
                'entry_date': '2026-04-25 07:12:00', # Fecha ingreso
                'product': 'aceite', # Producto aceite
                'client': 'COMPANIA ARGENTINA DE ACEITES', # Cliente
                'transport_company': 'TRANSPORTI', # Transportista
                'recipient': 'AGROINDUSTRIAL COSANIC S.R.L.', # Destinatario
                'truck_plate': 'GFI013', # Patente chasis
                'trailer_plate': 'OFF774', # Patente acoplado
                'driver_name': 'roberto dos santos', # Chofer
                'user_id_code': '6', # ID Usuario
                'exit_weight_kg': 43760.0, # Peso egreso kg
                'entry_weight_kg': 15800.0, # Peso ingreso kg
                'net_weight_kg': 27960.0, # Peso neto kg
                'net_weight_tons': 27.96 # Peso neto tons
            }, # Fin fila 220
            221: { # Fila 221 correspondiente al ticket 1007
                'ticket_number': '1007', # Numero de ticket 1007
                'product': 'semilla', # Producto semilla
                'client': 'AGROINDUSTRIAL COSANIC S.R.L.', # Cliente Cosanic
                'transport_company': 'AGROINDUSTRIAL COSANIC S.R.L.', # Transportista
                'recipient': 'AGROINDUSTRIAL COSANIC S.R.L.' # Destinatario
            }, # Fin fila 221
            222: { # Fila 222 correspondiente al ticket 1006
                'ticket_number': '1006', # Numero de ticket 1006
                'product': 'expeller', # Producto expeller
                'client': 'LLADA', # Cliente Llada
                'transport_company': 'LLADA', # Transportista
                'recipient': 'LLADA' # Destinatario
            }, # Fin fila 222
            223: { # Fila 223 correspondiente al ticket 1005
                'ticket_number': '1005', # Numero de ticket 1005
                'product': 'insumos', # Producto insumos
                'client': 'AGROINDUSTRIAL COSANIC S.R.L.', # Cliente Cosanic
                'transport_company': 'AGROINDUSTRIAL COSANIC S.R.L.', # Transportista
                'recipient': 'AGROINDUSTRIAL COSANIC S.R.L.' # Destinatario
            }, # Fin fila 223
            224: { # Fila 224 correspondiente al ticket 1004
                'ticket_number': '1004', # Numero de ticket 1004
                'product': 'expeller', # Producto expeller
                'client': 'TRES ESQUINAS', # Cliente Tres Esquinas
                'transport_company': 'TRES ESQUINAS', # Transportista
                'recipient': 'TRES ESQUINAS' # Destinatario
            }, # Fin fila 224
            225: { # Fila 225 correspondiente al ticket 1003
                'ticket_number': '1003', # Numero de ticket 1003
                'product': 'semilla', # Producto semilla
                'client': 'AGROINDUSTRIAL COSANIC S.R.L.', # Cliente Cosanic
                'transport_company': 'AGROINDUSTRIAL COSANIC S.R.L.', # Transportista
                'recipient': 'AGROINDUSTRIAL COSANIC S.R.L.' # Destinatario
            }, # Fin fila 225
            226: { # Fila 226 correspondiente al ticket 1002
                'ticket_number': '1002', # Numero de ticket 1002
                'product': 'semilla', # Producto semilla
                'client': 'AGROINDUSTRIAL COSANIC S.R.L.', # Cliente Cosanic
                'transport_company': 'AGROINDUSTRIAL COSANIC S.R.L.', # Transportista
                'recipient': 'AGROINDUSTRIAL COSANIC S.R.L.' # Destinatario
            }, # Fin fila 226
            227: { # Fila 227 correspondiente al ticket 1001
                'ticket_number': '1001', # Numero de ticket 1001
                'product': 'semilla', # Producto semilla
                'client': 'AGROINDUSTRIAL COSANIC S.R.L.', # Cliente Cosanic
                'transport_company': 'AGROINDUSTRIAL COSANIC S.R.L.', # Transportista
                'recipient': 'AGROINDUSTRIAL COSANIC S.R.L.' # Destinatario
            }, # Fin fila 227
            228: { # Fila 228 correspondiente al ticket 1000
                'ticket_number': '1000', # Numero de ticket 1000
                'product': 'semilla', # Producto semilla
                'client': 'AGROINDUSTRIAL COSANIC S.R.L.', # Cliente Cosanic
                'transport_company': 'AGROINDUSTRIAL COSANIC S.R.L.', # Transportista
                'recipient': 'AGROINDUSTRIAL COSANIC S.R.L.' # Destinatario
            } # Fin fila 228
        } # Fin diccionario legacy_rows
        # Itera sobre cada registro historico para actualizarlo en la base de datos
        for rid, data in legacy_rows.items(): # Bucle de actualizacion
            # Clausulas SET dinamicas
            set_clauses = [f"{col} = ?" for col in data.keys()] # Ensambla pares columna = ?
            # Valores a inyectar en la consulta
            vals = list(data.values()) + [rid] # Lista de valores mas el id
            # Ejecuta sentencia SQL de actualizacion
            conn.execute(f"UPDATE truck_scale_weighings SET {', '.join(set_clauses)} WHERE id = ?;", tuple(vals)) # Update
    # Captura cualquier error sin abortar la ejecucion global
    except Exception as e: # Manejo de excepcion
        # Registra advertencia en el log del sistema
        log_error('MIGRATIONS', 'Aviso al reparar tickets de balanza en migracion 19', e) # Registro de log

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

# Funcion de normalizacion de fechas historicas en pesadas de balanza
def backfill_normalize_weighbridge_dates(conn):
    # Importa funcion utilitaria de normalizacion de fechas
    from core.utils import normalize_date_str
    # Intenta la normalizacion exhaustiva
    try:
        # Consulta todas las pesadas de balanza existentes
        rows = conn.execute("SELECT id, weigh_date, entry_date, exit_date FROM truck_scale_weighings;").fetchall()
        # Itera por cada registro de pesada
        for r in rows:
            # Obtiene ID de fila
            rid = r['id'] if isinstance(r, dict) else r[0]
            # Obtiene fecha de pesada
            wd = r['weigh_date'] if isinstance(r, dict) else r[1]
            # Obtiene fecha de ingreso
            ed = r['entry_date'] if isinstance(r, dict) else r[2]
            # Obtiene fecha de egreso
            xd = r['exit_date'] if isinstance(r, dict) else r[3]
            # Normaliza fecha de pesada
            norm_wd = normalize_date_str(wd)
            # Normaliza fecha de ingreso
            norm_ed = normalize_date_str(ed)
            # Normaliza fecha de egreso
            norm_xd = normalize_date_str(xd)
            # Si weigh_date quedo vacio, asigna fallback a exit_date o entry_date
            norm_wd = norm_wd or norm_xd or norm_ed
            # Si hubo cambios en alguna fecha
            if norm_wd != wd or norm_ed != ed or norm_xd != xd:
                # Actualiza el registro con las fechas estandarizadas
                conn.execute("""
                    UPDATE truck_scale_weighings
                    SET weigh_date = ?, entry_date = ?, exit_date = ?
                    WHERE id = ?;
                """, (norm_wd, norm_ed, norm_xd, rid))
    # Captura errores en caso de fallo
    except Exception as e:
        # Registra advertencia en bitacora
        log_error('MIGRATIONS', 'Aviso al normalizar fechas en truck_scale_weighings', e)

# Sincroniza fotografias de mantenimiento desde disco local a columnas image_data y mime_type
def backfill_sync_disk_and_cloud_images(conn): # Define funcion backfill
    # Captura segura para evitar que fallos de disco interrumpan el arranque
    try: # Bloque try
        # Importa os para rutas de archivos
        import os # Importa os
        # Importa base64 para codificar imagenes
        import base64 # Importa base64
        # Importa modulo de configuracion para obtener directorios
        import config # Importa config
        # Intenta importar Pillow para optimizar fotografias encontradas en disco
        try: # Bloque try Pillow
            # Importa Image de PIL
            from PIL import Image # Importa Image
            # Importa ImageOps para corregir EXIF
            from PIL import ImageOps # Importa ImageOps
            # Importa io para buffers en memoria
            import io # Importa io
        except ImportError: # Si Pillow no esta instalado
            # Asigna Image a None
            Image = None # Image None
            # Asigna ImageOps a None
            ImageOps = None # ImageOps None
            # Asigna io a None
            io = None # io None
        # Comprueba si la tabla maintenance_images existe en la base de datos
        t_exists = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='maintenance_images';").fetchone() # Comprueba tabla
        # Si la tabla no existe todavia, concluye la ejecucion
        if not t_exists: # Si no existe tabla
            # Retorna temprano
            return # Retorna
        # Consulta todas las filas de fotografias que no tengan image_data cargado
        rows = conn.execute("""
            SELECT id, activity_id, filename
            FROM maintenance_images
            WHERE image_data IS NULL OR image_data = '';
        """).fetchall() # Obtiene filas
        # Si no hay imagenes pendientes de sincronizar
        if not rows: # Si no hay filas
            # Retorna temprano
            return # Retorna
        # Directorios potenciales donde pueden residir los archivos fisicos
        potential_dirs = [ # Lista de carpetas
            config.MAINTENANCE_UPLOADS_DIR, # Carpeta configurada
            os.path.join(str(config.BASE_DIR), 'static', 'uploads', 'maintenance'), # Carpeta estatica oficial
            os.path.join(str(config.BASE_DIR), 'static', 'uploads'), # Carpeta subida general
        ] # Fin de lista de carpetas
        # Contador de imagenes sincronizadas exitosamente
        synced_count = 0 # Inicializa contador
        # Itera sobre cada registro sin datos binarios persistidos
        for r in rows: # Itera registros
            # Extrae identificador numerico
            img_id = r['id'] if isinstance(r, dict) else r[0] # Extrae ID
            # Extrae identificador de actividad
            act_id = r['activity_id'] if isinstance(r, dict) else r[1] # Extrae activity_id
            # Extrae nombre de archivo
            fn = r['filename'] if isinstance(r, dict) else r[2] # Extrae filename
            # Si no hay nombre de archivo asignado, salta la iteracion
            if not fn: # Si filename vacio
                # Continua con siguiente fila
                continue # Continua
            # Variable para almacenar ruta encontrada
            found_path = None # Inicializa ruta
            # Busca el archivo en cada directorio potencial
            for pdir in potential_dirs: # Itera carpetas
                # Si el directorio no existe fisicamente, salta
                if not os.path.isdir(pdir): # Verifica si existe directorio
                    # Siguiente directorio
                    continue # Siguiente
                # Construye ruta candidata directa
                candidate = os.path.join(pdir, fn) # Ruta directa
                # Si el archivo exacto existe en disco
                if os.path.isfile(candidate): # Verifica existencia
                    # Asigna la ruta encontrada
                    found_path = candidate # Asigna ruta
                    # Corta la busqueda en carpetas
                    break # Rompe ciclo
                # Si no encontro coincidencia exacta, busca por patron maint_{act_id}_
                prefix = f"maint_{act_id}_" # Prefijo esperado
                # Lista archivos en la carpeta
                try: # Bloque try listdir
                    # Obtiene nombres en el directorio
                    for fname in os.listdir(pdir): # Itera archivos
                        # Si el archivo comienza con el prefijo de la actividad
                        if fname.startswith(prefix): # Comprueba prefijo
                            # Construye ruta
                            alt_cand = os.path.join(pdir, fname) # Ruta alternativa
                            # Si es un archivo regular valido
                            if os.path.isfile(alt_cand): # Comprueba archivo
                                # Asigna la ruta encontrada
                                found_path = alt_cand # Asigna ruta
                                # Actualiza el nombre de archivo si era diferente
                                fn = fname # Actualiza filename
                                # Corta la busqueda
                                break # Rompe ciclo
                except Exception: # Captura error al listar
                    # Ignora fallo de lectura de directorio
                    pass # Pasa
                # Si ya encontro ruta, corta busqueda
                if found_path: # Si encontro
                    # Rompe ciclo exterior
                    break # Rompe ciclo
            # Si encontro el archivo fisico en disco
            if found_path and os.path.isfile(found_path): # Comprueba archivo hallado
                # Lee los bytes del archivo fisico
                with open(found_path, 'rb') as f: # Abre archivo
                    # Lee contenido completo
                    raw_bytes = f.read() # Lee bytes
                # Si el archivo tiene contenido util
                if raw_bytes: # Si hay bytes
                    # Tipo MIME por defecto
                    mime = 'image/jpeg' # Mime por defecto
                    # Datos procesados binarios
                    processed = raw_bytes # Bytes procesados
                    # Si Pillow esta disponible, optimiza la imagen
                    if Image is not None and io is not None: # Si Pillow disponible
                        # Bloque protegido para procesamiento de imagen
                        try: # Bloque try Pillow
                            # Abre imagen desde buffer en memoria
                            with Image.open(io.BytesIO(raw_bytes)) as img: # Abre imagen
                                # Si ImageOps esta disponible, corrige orientacion EXIF
                                if ImageOps is not None: # Si ImageOps disponible
                                    # Corrige rotacion de fotos tomadas con celulares
                                    try: # Bloque try EXIF
                                        # Aplica correccion de metadatos EXIF
                                        img = ImageOps.exif_transpose(img) # Corrige EXIF
                                    except Exception: # Captura fallo EXIF
                                        # Ignora error de metadatos
                                        pass # Pasa
                                # Si la imagen tiene transparencia o paleta indexada
                                if img.mode in ('RGBA', 'LA', 'P'): # Comprueba modo con canal alfa
                                    # Crea lienzo blanco de fondo
                                    bg = Image.new('RGB', img.size, (255, 255, 255)) # Fondo blanco
                                    # Si es modo paleta P, convierte a RGBA
                                    if img.mode == 'P': # Modo paleta
                                        # Convierte a RGBA
                                        img = img.convert('RGBA') # Convierte RGBA
                                    # Pega sobre el fondo usando canal alfa como mascara
                                    bg.paste(img, mask=img.split()[-1] if len(img.split()) == 4 else None) # Pega fondo
                                    # Asigna imagen combinada
                                    img = bg # Reemplaza por RGB
                                # Si no es RGB, convierte a RGB
                                elif img.mode != 'RGB': # Si no es RGB
                                    # Convierte modo a RGB
                                    img = img.convert('RGB') # Convierte RGB
                                # Redimensiona proporcionalmente a maximo 1280px
                                resample_f = getattr(getattr(Image, 'Resampling', Image), 'LANCZOS', Image.BICUBIC) # Filtro de muestreo
                                # Aplica thumbnail proporcional
                                img.thumbnail((1280, 1280), resample=resample_f) # Redimensiona
                                # Buffer en memoria para compilar JPEG optimizado
                                buf = io.BytesIO() # Crea buffer
                                # Guarda JPEG con calidad 80 y compresion optimizada
                                img.save(buf, format='JPEG', quality=80, optimize=True) # Guarda buffer
                                # Asigna bytes procesados
                                processed = buf.getvalue() # Obtiene bytes JPEG
                                # Asigna mime JPEG
                                mime = 'image/jpeg' # Mime JPEG
                        except Exception: # En caso de que Pillow falle al parsear
                            # Mantiene bytes originales
                            processed = raw_bytes # Fallback raw
                    # Codifica en Base64
                    b64_str = base64.b64encode(processed).decode('ascii') # Codifica base64
                    # Construye URI de datos completa
                    data_uri = f"data:{mime};base64,{b64_str}" # Data URI
                    # Actualiza la fila en la base de datos
                    conn.execute("""
                        UPDATE maintenance_images
                        SET image_data = ?, mime_type = ?, filename = ?
                        WHERE id = ?;
                    """, (data_uri, mime, fn, img_id)) # Actualiza registro
                    # Incrementa contador de imagenes recuperadas
                    synced_count += 1 # Suma 1
        # Si se sincronizaron fotografias, registra en el log
        if synced_count > 0: # Si hubo sincronizaciones
            # Registra aviso informativo de recuperacion
            log_info('MIGRATIONS', f'Migracion v22: {synced_count} fotografias de mantenimiento sincronizadas desde disco a base de datos.') # Log
    # Captura cualquier error no previsto
    except Exception as e: # Captura general
        # Registra en el log de errores
        log_error('MIGRATIONS', f'Aviso en callback de migracion v22 (backfill_sync_disk_and_cloud_images): {e}') # Error log

# Funcion de retro-atribucion de pesadas y paradas de produccion para migracion 23
def backfill_production_operator_attribution(conn): # Define funcion de retro-atribucion
    try: # Bloque de proteccion
        target_name = 'JAVIER' # Nombre objetivo por defecto
        try: # Bloque de busqueda de usuario
            user_row = conn.execute("SELECT username, full_name FROM users WHERE LOWER(username) = 'javier' OR LOWER(full_name) LIKE '%javier%' LIMIT 1;").fetchone() # Busca usuario javier
            if user_row: # Si existe
                u_name = user_row['full_name'] if isinstance(user_row, dict) else (user_row[1] if user_row[1] else user_row[0]) # Toma nombre
                if u_name and str(u_name).strip(): # Si no esta vacio
                    target_name = str(u_name).strip() # Asigna nombre real
        except Exception as u_err: # Captura error en busqueda de usuario
            log_error('MIGRATION_23', 'Fallo al buscar usuario javier en base de datos', u_err) # Registra log

        # 1. Actualiza pesadas cargadas el 2/10 con placeholder hacia el usuario real
        conn.execute("""
            UPDATE production_weighings
            SET operator_name = ?
            WHERE (operator_name IS NULL OR operator_name IN ('Operario de Linea 1', 'Operario', ''))
              AND (sample_date = '2026-10-02' OR timestamp LIKE '2026-10-02%');
        """, (target_name,)) # Ejecuta update de pesadas

        # 2. Actualiza paradas cargadas el 2/10 con placeholder hacia el usuario real
        conn.execute("""
            UPDATE line_stops
            SET operator_name = ?
            WHERE (operator_name IS NULL OR operator_name IN ('Operario de Linea 1', 'Operario', ''))
              AND (start_time LIKE '2026-10-02%');
        """, (target_name,)) # Ejecuta update de paradas

        # 3. Cruce con auditoria para asignar username autenticado en caso de existir registros historicos
        try: # Bloque de cruce con auditoria
            audit_rows = conn.execute("""
                SELECT username, timestamp FROM audit_logs
                WHERE category = 'PRODUCCION' AND action = 'PESADA_REGISTRADA'
                  AND username NOT IN ('SISTEMA', 'DESCONOCIDO', 'anónimo', '')
                ORDER BY timestamp DESC;
            """).fetchall() # Consulta auditoria
            for ar in audit_rows: # Recorre eventos
                a_user = ar['username'] if isinstance(ar, dict) else ar[0] # Obtiene username
                a_time = ar['timestamp'] if isinstance(ar, dict) else ar[1] # Obtiene timestamp
                if a_user and a_time: # Si son validos
                    time_prefix = a_time[:16] # Prefijo hasta minuto YYYY-MM-DD HH:MM
                    conn.execute("""
                        UPDATE production_weighings
                        SET operator_name = ?
                        WHERE (operator_name IS NULL OR operator_name IN ('Operario de Linea 1', 'Operario', ''))
                          AND timestamp LIKE ?;
                    """, (a_user, f"{time_prefix}%")) # Actualiza pesada coincidente
        except Exception as a_err: # Captura fallo en auditoria
            log_error('MIGRATION_23', 'Fallo en cruce de auditoria', a_err) # Registra log

        conn.commit() # Confirma cambios
        log_info('MIGRATIONS', f'Migracion v23: Muestras y paradas retro-atribuidas exitosamente a {target_name}.') # Informa exito
    except Exception as e: # Captura general
        log_error('MIGRATIONS', f'Error en backfill_production_operator_attribution: {e}') # Registra error

# Funcion de calibracion geometrica y recalculacion de stock de silos para migracion 24
def calibrate_silos_and_backfill_readings(conn):
    try:
        from modules.calculations.silo_calc import (
            calculate_silo_total_volume, convert_silo_volume_to_seed_mass, convert_silo_volume_to_expeller_mass
        )
        import json

        # 1. Asegura que los parametros maestros esten fijados
        conn.execute("UPDATE equipment_silos SET bottom_cone_height_m = 2.00, copete_max_height_m = 2.00 WHERE code = 'SILO-03';")
        conn.execute("UPDATE equipment_silos SET bottom_cone_height_m = 2.00, copete_max_height_m = 2.00 WHERE code = 'SILO-04';")
        conn.execute("UPDATE equipment_silos SET bottom_cone_height_m = 2.50, default_ph = 41.5 WHERE code = 'SILO-EXP-V';")
        conn.execute("UPDATE equipment_silos SET bottom_cone_height_m = 1.00, default_ph = 41.5 WHERE code = 'SILO-EXP-R';")

        # 2. Recalcula las mediciones en inventory_silos para los silos calibrados
        target_codes = ('SILO-03', 'SILO-04', 'SILO-EXP-V', 'SILO-EXP-R')
        for code in target_codes:
            silo = conn.execute("SELECT * FROM equipment_silos WHERE code = ?;", (code,)).fetchone()
            if not silo:
                continue
            silo_dict = dict(silo)
            d_m = float(silo_dict['diameter_m'])
            sh_h = float(silo_dict['sheet_height_m'] or 0.99)
            cone_h = float(silo_dict['bottom_cone_height_m'] or 0.0)
            cone_type = silo_dict.get('bottom_cone_type') or 'cone'
            min_diam = float(silo_dict.get('bottom_cone_min_diam_m') or 0.0)
            product = silo_dict.get('product_assigned', 'girasol')
            ph_val = float(silo_dict.get('default_ph') or (40.0 if product == 'girasol' else 41.5))

            # Busca la ultima medicion de este silo
            last_meas = conn.execute("""
                SELECT * FROM inventory_silos
                WHERE silo_id = ?
                ORDER BY timestamp DESC, id DESC
                LIMIT 1;
            """, (silo_dict['id'],)).fetchone()

            if last_meas:
                m_dict = dict(last_meas)
                cov_sheets = float(m_dict.get('covered_sheets') or 0.0)
                part_h = float(m_dict.get('partial_sheet_height_m') or 0.0)
                cone_st = m_dict.get('cone_occupied_status') or 'lleno'
                cop_h = float(m_dict.get('copete_height_m') or 0.0)

                vol_breakdown = calculate_silo_total_volume(
                    d_m, sh_h, cov_sheets, part_h,
                    cone_h, cone_type, min_diam, cone_st, cop_h
                )
                tot_vol = vol_breakdown['total_volume_m3']

                if product == 'expeller':
                    mass_info = convert_silo_volume_to_expeller_mass(tot_vol, bulk_density_kg_m3=ph_val * 10.0)
                else:
                    mass_info = convert_silo_volume_to_seed_mass(tot_vol, hectolitric_weight_kg_hl=ph_val)

                new_snapshot = json.dumps({
                    'silo_code': silo_dict['code'],
                    'silo_name': silo_dict['name'],
                    'diameter_m': d_m,
                    'sheet_height_m': sh_h,
                    'cone_height_m': cone_h,
                    'ph_applied': ph_val,
                    'vol_breakdown': vol_breakdown,
                    'recalculated_by_migration': 'v24'
                })

                conn.execute("""
                    UPDATE inventory_silos
                    SET volume_m3 = ?, stock_kg = ?, ph_applied = ?, params_snapshot = ?
                    WHERE id = ?;
                """, (tot_vol, mass_info['total_mass_kg'], ph_val, new_snapshot, m_dict['id']))

        conn.commit()
        log_info('MIGRATIONS', 'Migracion v24: Parametros geometricos y cubicajes de silos actualizados exitosamente.')
    except Exception as e:
        log_error('MIGRATIONS', f'Error en calibrate_silos_and_backfill_readings: {e}')

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
