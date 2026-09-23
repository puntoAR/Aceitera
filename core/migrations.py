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
    }
]

# Ejecuta una migracion especifica de forma segura
def apply_single_migration(migration):
    # Version de la migracion
    version = migration['version']
    # Nombre descriptivo
    name = migration['name']
    # SQL a ejecutar
    sql_script = migration['sql'].strip()
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
                    except sqlite3.OperationalError as op_err:
                        # Si la columna ya fue agregada previamente, ignora el error de duplicado
                        if "duplicate column name" in str(op_err).lower():
                            pass
                        else:
                            # Propaga cualquier otro error de base de datos
                            raise op_err
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
