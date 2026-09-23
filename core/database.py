# Importa el modulo sqlite3 para gestionar la base de datos relacional integrada
import sqlite3
# Importa json para serializar y deserializar los parametros aplicados en snapshots
import json
# Importa la ruta de la base de datos desde el archivo de configuracion
from config import DATABASE_PATH
# Importa el registrador de eventos para auditar las operaciones sobre la base de datos
from core.error_logger import log_info, log_error

# Importa contextlib para manejar el ciclo de vida y cierre seguro de conexiones
import contextlib

# Obtiene una conexion a la base de datos SQLite con contextmanager para cierre automatico
@contextlib.contextmanager
def get_db_connection():
    # Establece la conexion con el archivo de base de datos en disco
    conn = sqlite3.connect(DATABASE_PATH)
    # Habilita el acceso a columnas por nombre asociativo tipo diccionario
    conn.row_factory = sqlite3.Row
    # Habilita el soporte de claves foraneas para mantener la integridad referencial
    conn.execute("PRAGMA foreign_keys = ON;")
    # Bloque try-finally para garantizar el cierre de conexion
    try:
        # Entrega la conexion activa al bloque with
        yield conn
    finally:
        # Cierra la conexion para liberar descriptores de archivo en disco
        conn.close()

# Inicializa el esquema completo de tablas e inserta los parametros base
def init_db():
    # Registra en el log el inicio del proceso de inicializacion de base de datos
    log_info('DATABASE', 'Iniciando verificacion y creacion de tablas en SQLite')
    # Abre la conexion con la base de datos usando el gestor de contexto
    with get_db_connection() as conn:
        # Crea la tabla de configuracion general de la planta
        conn.execute("""
        CREATE TABLE IF NOT EXISTS system_config (
            key TEXT PRIMARY KEY,           -- Clave identificadora del parametro
            value TEXT NOT NULL,            -- Valor asignado al parametro
            description TEXT,               -- Descripcion explicativa del proposito
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP -- Marca de tiempo de actualizacion
        );
        """)

        # Crea la tabla de turnos de trabajo de la planta
        conn.execute("""
        CREATE TABLE IF NOT EXISTS shifts (
            id TEXT PRIMARY KEY,            -- Codigo del turno (TM, TT, TN, TC)
            name TEXT NOT NULL,             -- Nombre descriptivo (Turno Manana, Tarde, Noche, Central)
            start_hour INTEGER NOT NULL,    -- Hora militar de inicio (ej. 6, 8, 14, 22)
            end_hour INTEGER NOT NULL,      -- Hora militar de finalizacion (ej. 14, 16, 22, 6)
            is_active INTEGER DEFAULT 1,    -- Estado activo o inactivo del turno
            admin_only INTEGER DEFAULT 0    -- 1 si el turno esta restringido exclusivamente para ADMIN
        );
        """)

        # Crea la tabla de usuarios y operarios autorizados
        conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT, -- Identificador unico secuencial
            username TEXT UNIQUE NOT NULL,        -- Nombre de usuario de acceso
            full_name TEXT NOT NULL,              -- Nombre completo del operario
            role TEXT NOT NULL,                   -- Rol: usuario, administrador, admin_sistema
            pin TEXT NOT NULL,                    -- Codigo PIN o contrasena simple
            dni TEXT UNIQUE,                      -- Documento Nacional de Identidad
            phone TEXT,                           -- Numero de telefono para SMS o WhatsApp
            approval_status TEXT DEFAULT 'aprobado', -- Estado: pendiente, aprobado, rechazado
            must_change_password INTEGER DEFAULT 0,  -- Obligacion de cambio de clave al ingresar
            is_active INTEGER DEFAULT 1,          -- Estado de habilitacion en planta
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP -- Fecha de alta
        );
        """)

        # Crea la tabla de codigos OTP para recuperacion de contrasena
        conn.execute("""
        CREATE TABLE IF NOT EXISTS password_reset_codes (
            id INTEGER PRIMARY KEY AUTOINCREMENT, -- Identificador unico del codigo
            user_id INTEGER NOT NULL,             -- Usuario asociado al codigo
            code TEXT NOT NULL,                   -- Codigo de 6 digitos generado
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, -- Fecha y hora de generacion
            expires_at TIMESTAMP NOT NULL,        -- Momento de expiracion del codigo
            used INTEGER DEFAULT 0,               -- Indicador de uso previo
            FOREIGN KEY (user_id) REFERENCES users(id) -- Vinculacion con usuario
        );
        """)

        # Crea la tabla de logs de auditoria de actividades del sistema
        conn.execute("""
        CREATE TABLE IF NOT EXISTS audit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT, -- Identificador del evento auditado
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP, -- Fecha y hora exacta
            user_id INTEGER,                      -- Usuario que realizo la accion
            username TEXT,                        -- Nombre de usuario
            role TEXT,                            -- Rol al momento de la accion
            ip_address TEXT,                      -- Direccion IP del cliente
            category TEXT NOT NULL,               -- Categoria del evento
            action TEXT NOT NULL,                 -- Accion realizada
            details TEXT NOT NULL,                -- Detalle legible de la actividad
            status TEXT DEFAULT 'OK'              -- Estado: OK, ERROR, ADVERTENCIA
        );
        """)

        # Crea la tabla de registro y analisis de errores de ejecucion
        conn.execute("""
        CREATE TABLE IF NOT EXISTS system_errors (
            id INTEGER PRIMARY KEY AUTOINCREMENT, -- Identificador de la excepcion
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP, -- Fecha y hora del error
            user_id INTEGER,                      -- Usuario activo si existia sesion
            username TEXT,                        -- Nombre de usuario activo
            endpoint TEXT,                        -- Ruta o endpoint donde ocurrio
            error_type TEXT NOT NULL,             -- Tipo de excepcion Python
            error_message TEXT NOT NULL,          -- Mensaje de la excepcion
            traceback TEXT,                       -- Traza completa de la pila
            resolved INTEGER DEFAULT 0            -- Indicador de resolucion por admin
        );
        """)

        # Crea la tabla de turnos activos y registro de guardias
        conn.execute("""
        CREATE TABLE IF NOT EXISTS active_shift (
            id INTEGER PRIMARY KEY CHECK (id = 1), -- Registro unico tipo singleton
            shift_id TEXT NOT NULL,                -- Turno actual en ejecucion
            operator_name TEXT NOT NULL,           -- Operario responsable de la guardia
            opened_at TIMESTAMP NOT NULL,          -- Fecha y hora de inicio de guardia
            FOREIGN KEY (shift_id) REFERENCES shifts(id) -- Vinculacion con turnos
        );
        """)

        # Crea la tabla de configuracion geometrica de tanques de aceite
        conn.execute("""
        CREATE TABLE IF NOT EXISTS equipment_tanks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,   -- Identificador unico del tanque
            code TEXT UNIQUE NOT NULL,              -- Codigo de planta (ej. TK-01, TK-02)
            name TEXT NOT NULL,                     -- Nombre descriptivo del tanque
            geometry_type TEXT NOT NULL,            -- horizontal_cylinder o vertical_cylinder
            diameter_m REAL NOT NULL,               -- Diametro interior en metros
            length_m REAL NOT NULL,                 -- Longitud util en metros (para horizontal)
            height_m REAL NOT NULL,                 -- Altura util en metros (para vertical)
            heel_volume_l REAL DEFAULT 0.0,         -- Volumen de talon no bombeable en litros
            default_density REAL DEFAULT 0.92,      -- Densidad de referencia en kg/L
            is_active INTEGER DEFAULT 1,            -- Estado operativo del tanque
            version INTEGER DEFAULT 1,              -- Numero de version de calibracion
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP -- Fecha de ultima actualizacion
        );
        """)

        # Crea la tabla de configuracion geometrica de silos de cereal y expeller
        conn.execute("""
        CREATE TABLE IF NOT EXISTS equipment_silos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,   -- Identificador unico del silo
            code TEXT UNIQUE NOT NULL,              -- Codigo de planta (ej. SILO-01)
            name TEXT NOT NULL,                     -- Nombre del silo
            product_assigned TEXT NOT NULL,         -- Producto: girasol, soja, expeller
            diameter_m REAL NOT NULL,               -- Diametro interior en metros
            sheet_height_m REAL NOT NULL,           -- Altura unitaria de cada chapa en metros
            total_sheets INTEGER NOT NULL,          -- Cantidad total de chapas del silo
            bottom_cone_height_m REAL NOT NULL,     -- Altura del cono inferior en metros
            bottom_cone_type TEXT DEFAULT 'cone',   -- Tipo: cone (completo) o frustum (tronco)
            bottom_cone_min_diam_m REAL DEFAULT 0,  -- Diametro de descarga del cono
            copete_max_height_m REAL NOT NULL,      -- Altura maxima del copete superior
            default_ph REAL DEFAULT 44.0,           -- Peso hectolitrico predeterminado kg/hl
            is_active INTEGER DEFAULT 1,            -- Estado operativo
            version INTEGER DEFAULT 1,              -- Version de calibracion
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP -- Fecha de calibracion
        );
        """)

        # Crea la tabla de pesadas y medicion de velocidad de linea
        conn.execute("""
        CREATE TABLE IF NOT EXISTS production_weighings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,       -- Identificador unico del muestreo
            timestamp TIMESTAMP NOT NULL,               -- Fecha y hora del registro
            shift_id TEXT NOT NULL,                     -- Turno en el que se tomo la muestra
            operator_name TEXT NOT NULL,                -- Nombre del operario que peso
            sample_point TEXT NOT NULL,                 -- ingreso_semilla o salida_expeller
            gross_weight_kg REAL NOT NULL,              -- Peso bruto de la bolsa con material
            tare_weight_kg REAL DEFAULT 0.0,            -- Tara del recipiente o bolsa
            net_weight_kg REAL NOT NULL,                -- Peso neto efectivo descontando tara
            fill_time_seconds REAL NOT NULL,            -- Tiempo de llenado en segundos
            line_status TEXT DEFAULT 'operando',        -- Estado: operando o detenida
            speed_kg_h REAL NOT NULL,                   -- Velocidad calculada en kg/h
            proj_8h_kg REAL NOT NULL,                   -- Proyeccion a turno de 8 horas en kg
            proj_24h_kg REAL NOT NULL,                  -- Proyeccion a 24 horas en kg
            notes TEXT,                                 -- Observaciones operativas
            params_snapshot TEXT                        -- JSON con snapshot de constantes
        );
        """)

        # Crea la tabla de registros de paradas de linea
        conn.execute("""
        CREATE TABLE IF NOT EXISTS line_stops (
            id INTEGER PRIMARY KEY AUTOINCREMENT,   -- Identificador de la parada
            shift_id TEXT NOT NULL,                 -- Turno en el que ocurrio la parada
            start_time TIMESTAMP NOT NULL,          -- Hora de inicio de la detencion
            end_time TIMESTAMP,                     -- Hora de reanudacion de marcha
            duration_minutes REAL,                  -- Duracion total en minutos
            reason TEXT NOT NULL,                   -- Motivo de la detencion
            operator_name TEXT NOT NULL             -- Operario que registro el evento
        );
        """)

        # Crea la tabla de mediciones de nivel y cubicaje de tanques de aceite
        conn.execute("""
        CREATE TABLE IF NOT EXISTS inventory_tanks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,   -- Identificador unico de la medicion
            timestamp TIMESTAMP NOT NULL,           -- Fecha y hora de medicion de nivel
            tank_id INTEGER NOT NULL,               -- Tanque evaluado
            level_m REAL NOT NULL,                  -- Nivel medido en metros
            volume_m3 REAL NOT NULL,                -- Volumen calculado en metros cubicos
            liters REAL NOT NULL,                   -- Volumen calculado en litros
            oil_kg REAL NOT NULL,                   -- Masa calculada en kilogramos
            density_applied REAL NOT NULL,          -- Densidad kg/L utilizada en el calculo
            shift_id TEXT NOT NULL,                 -- Turno operativo
            operator_name TEXT NOT NULL,            -- Operario responsable
            params_snapshot TEXT,                   -- JSON con dimensiones del tanque aplicadas
            FOREIGN KEY (tank_id) REFERENCES equipment_tanks(id) -- Vinculacion con tanque
        );
        """)

        # Crea la tabla de mediciones de cubicaje en silos
        conn.execute("""
        CREATE TABLE IF NOT EXISTS inventory_silos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,   -- Identificador unico de la medicion
            timestamp TIMESTAMP NOT NULL,           -- Fecha y hora de medicion
            silo_id INTEGER NOT NULL,               -- Silo cubicado
            covered_sheets REAL NOT NULL,           -- Chapas cubiertas registradas
            partial_sheet_height_m REAL DEFAULT 0,  -- Altura adicional en chapa parcial
            cone_occupied_status TEXT NOT NULL,     -- lleno, vacio o parcial
            copete_height_m REAL DEFAULT 0,         -- Altura del copete medida
            ph_applied REAL NOT NULL,               -- Peso hectolitrico o densidad aplicada
            volume_m3 REAL NOT NULL,                -- Volumen total calculado en m3
            stock_kg REAL NOT NULL,                 -- Masa total calculada en kg
            shift_id TEXT NOT NULL,                 -- Turno operativo
            operator_name TEXT NOT NULL,            -- Operario responsable
            params_snapshot TEXT,                   -- JSON con parametros geometricos
            FOREIGN KEY (silo_id) REFERENCES equipment_silos(id) -- Vinculacion con silo
        );
        """)

        # Crea la tabla de existencias de expeller en celda o acopio
        conn.execute("""
        CREATE TABLE IF NOT EXISTS inventory_expeller (
            id INTEGER PRIMARY KEY AUTOINCREMENT,   -- Identificador unico del registro
            timestamp TIMESTAMP NOT NULL,           -- Fecha y hora del registro
            volume_m3 REAL NOT NULL,                -- Volumen ocupado en m3
            bulk_density_applied REAL NOT NULL,     -- Densidad aparente aplicada en kg/m3
            stock_kg REAL NOT NULL,                 -- Masa total de expeller en kg
            method_description TEXT,                -- Metodo empleado para medir volumen/densidad
            shift_id TEXT NOT NULL,                 -- Turno operativo
            operator_name TEXT NOT NULL             -- Responsable del registro
        );
        """)

        # Crea la tabla de movimientos de existencias (despachos, ingresos, trasvases)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS inventory_movements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,   -- Identificador unico del movimiento
            timestamp TIMESTAMP NOT NULL,           -- Fecha y hora del movimiento
            product TEXT NOT NULL,                  -- semilla, expeller o aceite
            movement_type TEXT NOT NULL,            -- despacho, ingreso o trasvase
            origin TEXT,                            -- Origen del producto (ej. Silo 1, Tanque 1)
            destination TEXT,                       -- Destino (ej. Camion Patente XXX, Tanque 2)
            quantity_kg REAL NOT NULL,              -- Cantidad neta en kilogramos
            document_ref TEXT,                      -- Numero de remito o ticket de bascula
            shift_id TEXT NOT NULL,                 -- Turno operativo
            operator_name TEXT NOT NULL,            -- Operario responsable
            notes TEXT                              -- Observaciones del despacho o ingreso
        );
        """)

        # Crea la tabla de determinaciones analiticas de laboratorio
        conn.execute("""
        CREATE TABLE IF NOT EXISTS lab_analyses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,   -- Identificador unico del analisis
            timestamp TIMESTAMP NOT NULL,           -- Fecha y hora del ensayo
            sample_code TEXT NOT NULL,              -- Codigo identificador de muestra
            product TEXT NOT NULL,                  -- semilla, expeller o aceite
            sampling_point TEXT NOT NULL,           -- Punto de toma de muestra
            shift_id TEXT NOT NULL,                 -- Turno de produccion
            operator_name TEXT NOT NULL,            -- Analista responsable
            moisture_pct REAL,                      -- Humedad calculada en porcentaje
            fat_pct REAL,                           -- Materia grasa calculada en porcentaje
            foreign_matter_pct REAL,                -- Materia extrana en porcentaje
            acidity_pct REAL,                       -- Acidez libre en porcentaje (para aceite)
            raw_data_json TEXT,                     -- JSON con masas iniciales, secas, crisoles
            notes TEXT                              -- Notas u observaciones analiticas
        );
        """)

        # Crea la tabla de conciliaciones de turno y balance de masa
        conn.execute("""
        CREATE TABLE IF NOT EXISTS shift_reconciliations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,   -- Identificador unico de conciliacion
            date_shift TEXT NOT NULL,               -- Fecha y turno conciliado (ej. 2026-09-21-TM)
            shift_id TEXT NOT NULL,                 -- Turno correspondiente
            seed_processed_kg REAL NOT NULL,        -- Masa total de semilla procesada en kg
            expeller_produced_kg REAL NOT NULL,     -- Masa de expeller producido en kg
            oil_produced_kg REAL NOT NULL,          -- Masa de aceite producido en kg
            seed_fat_pct REAL,                      -- Materia grasa promedio de semilla (%)
            expeller_fat_pct REAL,                  -- Materia grasa residual en expeller (%)
            identified_waste_kg REAL DEFAULT 0.0,   -- Cascarilla y residuos solidos (kg)
            moisture_loss_kg REAL DEFAULT 0.0,      -- Agua evaporada por secado (kg)
            mass_difference_kg REAL NOT NULL,       -- Diferencia no conciliada en kg
            mass_diff_pct REAL NOT NULL,            -- Diferencia respecto a la semilla en %
            oil_yield_pct REAL NOT NULL,            -- Rendimiento masico de aceite (%)
            expeller_yield_pct REAL NOT NULL,       -- Rendimiento masico de expeller (%)
            oil_recovery_pct REAL NOT NULL,         -- Recuperacion de aceite disponible (%)
            residual_fat_kg REAL NOT NULL,          -- Masa de grasa retenida en expeller (kg)
            notes TEXT,                             -- Observaciones tecnicas del turno
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP -- Fecha de grabacion
        );
        """)

        # Crea la tabla de control de carga, precintado y despacho de camiones de aceite
        conn.execute("""
        CREATE TABLE IF NOT EXISTS oil_truck_dispatches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,                 -- Identificador unico del despacho
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,         -- Fecha y hora del despacho
            shift_id TEXT NOT NULL,                                -- Turno en que se realiza la carga
            operator_name TEXT NOT NULL,                           -- Analista/operador que certifica la carga
            truck_plate TEXT NOT NULL,                             -- Patente del chasis o camion
            trailer_plate TEXT,                                    -- Patente del acoplado o cisterna
            driver_name TEXT NOT NULL,                             -- Nombre y apellido del chofer
            driver_dni TEXT,                                       -- DNI del chofer
            transport_company TEXT,                                -- Empresa transportista
            destination TEXT,                                      -- Destino / Cliente del lote
            tank_source_id INTEGER,                                -- Tanque de origen de extraccion (1, 2, 3)
            quantity_kg REAL DEFAULT 0.0,                          -- Kilos netos cargados
            quantity_tons REAL DEFAULT 0.0,                        -- Toneladas netas cargadas
            transport_status TEXT NOT NULL,                        -- Estado del transporte
            seals_numbers TEXT NOT NULL,                           -- Numeracion y detalle de precintos
            sample_delivered TEXT NOT NULL DEFAULT 'NO',           -- Muestra entregada al chofer (SI / NO)
            sample_code TEXT,                                      -- Identificador de muestra
            oil_temperature_c REAL,                                -- Temperatura del aceite
            oil_acidity_pct REAL,                                  -- Acidez del lote despachado
            notes TEXT,                                            -- Observaciones de inspeccion
            FOREIGN KEY (shift_id) REFERENCES shifts(id),
            FOREIGN KEY (tank_source_id) REFERENCES equipment_tanks(id)
        );
        """)

        # Confirma las transacciones de creacion de tablas
        conn.commit()

    # Ejecuta el llenado inicial de datos semilla para turnos y equipos base
    seed_initial_data()
    # Registra en el log la finalizacion exitosa de la inicializacion
    log_info('DATABASE', 'Base de datos y esquemas inicializados correctamente')

# Llena la base de datos con los equipos y parametros reales de BioBalcarce
def seed_initial_data():
    # Abre conexion para verificar e insertar datos iniciales
    with get_db_connection() as conn:
        # Inserta los turnos tipicos de trabajo si la tabla esta vacia
        shift_count = conn.execute("SELECT COUNT(*) FROM shifts;").fetchone()[0]
        # Si no hay turnos registrados, inserta los 4 turnos oficiales de planta
        if shift_count == 0:
            # Inserta Turno Manana de 06:00 a 14:00 (admin_only = 0)
            conn.execute("INSERT INTO shifts (id, name, start_hour, end_hour, admin_only) VALUES ('TM', 'Turno Mañana (06:00 - 14:00)', 6, 14, 0);")
            # Inserta Turno Tarde de 14:00 a 22:00 (admin_only = 0)
            conn.execute("INSERT INTO shifts (id, name, start_hour, end_hour, admin_only) VALUES ('TT', 'Turno Tarde (14:00 - 22:00)', 14, 22, 0);")
            # Inserta Turno Noche de 22:00 a 06:00 (admin_only = 0)
            conn.execute("INSERT INTO shifts (id, name, start_hour, end_hour, admin_only) VALUES ('TN', 'Turno Noche (22:00 - 06:00)', 22, 6, 0);")
            # Inserta Turno Central de 08:00 a 16:00 (admin_only = 1, exclusivo Admin)
            conn.execute("INSERT INTO shifts (id, name, start_hour, end_hour, admin_only) VALUES ('TC', 'Turno Central (08:00 - 16:00)', 8, 16, 1);")
            # Confirma la insercion de los turnos en la base
            conn.commit()

        # Inserta usuarios y perfiles predeterminados si no existen
        user_count = conn.execute("SELECT COUNT(*) FROM users;").fetchone()[0]
        # Si no hay usuarios creados en el sistema
        if user_count == 0:
            # Inserta usuario Administrador del Sistema (acceso total a todos los modulos)
            conn.execute("INSERT INTO users (username, full_name, role, pin, dni, phone, approval_status) VALUES ('admin', 'Administrador del Sistema', 'admin_sistema', '1234', '10000000', '5492266000001', 'aprobado');")
            # Inserta usuario Administrador / Gerencia (acceso exclusivo a Dashboard)
            conn.execute("INSERT INTO users (username, full_name, role, pin, dni, phone, approval_status) VALUES ('gerente', 'Gerencia General (Administrador)', 'administrador', '3333', '20000000', '5492266000002', 'aprobado');")
            # Inserta usuario Operario de Planta (acceso a produccion y cubicaje)
            conn.execute("INSERT INTO users (username, full_name, role, pin, dni, phone, approval_status) VALUES ('operario', 'Operario de Planta', 'usuario', '1111', '30000000', '5492266000003', 'aprobado');")
            # Inserta usuario Analista de Laboratorio (acceso a laboratorio y cubicaje)
            conn.execute("INSERT INTO users (username, full_name, role, pin, dni, phone, approval_status) VALUES ('laboratorio', 'Analista de Calidad', 'usuario', '2222', '40000000', '5492266000004', 'aprobado');")
            # Confirma los usuarios creados
            conn.commit()

        # Inicializa el turno activo si no hay ninguno seleccionado
        active_shift_count = conn.execute("SELECT COUNT(*) FROM active_shift;").fetchone()[0]
        # Si la tabla esta vacia, coloca Turno Manana como activo inicial
        if active_shift_count == 0:
            # Inserta el registro de guardia actual
            conn.execute("INSERT INTO active_shift (id, shift_id, operator_name, opened_at) VALUES (1, 'TM', 'Operario de Linea 1', CURRENT_TIMESTAMP);")
            # Confirma la operacion en disco
            conn.commit()

        # Inserta los tanques de aceite reales de BioBalcarce segun el documento tecnico
        tank_count = conn.execute("SELECT COUNT(*) FROM equipment_tanks;").fetchone()[0]
        # Si no hay tanques cargados previamente
        if tank_count == 0:
            # Tanque 1: Cilindrico horizontal D=2.50m, L=6.50m
            conn.execute("""
            INSERT INTO equipment_tanks (code, name, geometry_type, diameter_m, length_m, height_m, heel_volume_l, default_density)
            VALUES ('TK-01', 'Tanque 1 (Cilindrico Horizontal)', 'horizontal_cylinder', 2.50, 6.50, 2.50, 100.0, 0.92);
            """)
            # Tanque 2: Cilindrico vertical de chapa D=2.00m, H=4.60m
            conn.execute("""
            INSERT INTO equipment_tanks (code, name, geometry_type, diameter_m, length_m, height_m, heel_volume_l, default_density)
            VALUES ('TK-02', 'Tanque 2 (Cilindrico Vertical Chapa)', 'vertical_cylinder', 2.00, 0.0, 4.60, 50.0, 0.92);
            """)
            # Tanque 3: Cilindrico vertical de plastico D=3.00m, H=4.00m
            conn.execute("""
            INSERT INTO equipment_tanks (code, name, geometry_type, diameter_m, length_m, height_m, heel_volume_l, default_density)
            VALUES ('TK-03', 'Tanque 3 (Cilindrico Vertical Plastico)', 'vertical_cylinder', 3.00, 0.0, 4.00, 50.0, 0.92);
            """)
            # Confirma la insercion de tanques
            conn.commit()

        # Inserta los silos de cereal y expeller segun los datos de fabrica de la planilla
        silo_count = conn.execute("SELECT COUNT(*) FROM equipment_silos;").fetchone()[0]
        # Si no hay silos registrados en la tabla
        if silo_count == 0:
            # Silo 1: Radio 2.05m (D=4.10m), Hchapa 0.99m, Cono H=1.9m, Copete H=1.0m, Chapas 4
            conn.execute("""
            INSERT INTO equipment_silos (code, name, product_assigned, diameter_m, sheet_height_m, total_sheets, bottom_cone_height_m, bottom_cone_type, copete_max_height_m, default_ph)
            VALUES ('SILO-01', 'Silo 1 Semilla Girasol', 'girasol', 4.10, 0.99, 4, 1.90, 'cone', 1.00, 40.0);
            """)
            # Silo 2: Radio 2.50m (D=5.00m), Hchapa 0.99m, Cono H=1.75m, Copete H=0.99m, Chapas 6
            conn.execute("""
            INSERT INTO equipment_silos (code, name, product_assigned, diameter_m, sheet_height_m, total_sheets, bottom_cone_height_m, bottom_cone_type, copete_max_height_m, default_ph)
            VALUES ('SILO-02', 'Silo 2 Semilla Girasol', 'girasol', 5.00, 0.99, 6, 1.75, 'cone', 0.99, 40.0);
            """)
            # Silo 3: Radio 3.70m (D=7.40m), Hchapa 0.99m, Cono H=0.50m, Copete H=0.99m, Chapas 6
            conn.execute("""
            INSERT INTO equipment_silos (code, name, product_assigned, diameter_m, sheet_height_m, total_sheets, bottom_cone_height_m, bottom_cone_type, copete_max_height_m, default_ph)
            VALUES ('SILO-03', 'Silo 3 Semilla Girasol', 'girasol', 7.40, 0.99, 6, 0.50, 'cone', 0.99, 40.0);
            """)
            # Silo 4: Radio 3.70m (D=7.40m), Hchapa 0.99m, Cono H=4.00m, Copete H=0.99m, Chapas 6
            conn.execute("""
            INSERT INTO equipment_silos (code, name, product_assigned, diameter_m, sheet_height_m, total_sheets, bottom_cone_height_m, bottom_cone_type, copete_max_height_m, default_ph)
            VALUES ('SILO-04', 'Silo 4 Semilla Girasol', 'girasol', 7.40, 0.99, 6, 4.00, 'cone', 0.99, 40.0);
            """)
            # Silo 5: Radio 5.75m (D=11.50m), Hchapa 0.99m, Cono H=1.00m, Copete H=3.00m, Chapas 8
            conn.execute("""
            INSERT INTO equipment_silos (code, name, product_assigned, diameter_m, sheet_height_m, total_sheets, bottom_cone_height_m, bottom_cone_type, copete_max_height_m, default_ph)
            VALUES ('SILO-05', 'Silo 5 Semilla Girasol', 'girasol', 11.50, 0.99, 8, 1.00, 'cone', 3.00, 40.0);
            """)
            # Silo Aereo Verde: Dedicado para expeller D=4.30m, 3 chapas
            conn.execute("""
            INSERT INTO equipment_silos (code, name, product_assigned, diameter_m, sheet_height_m, total_sheets, bottom_cone_height_m, bottom_cone_type, copete_max_height_m, default_ph)
            VALUES ('SILO-EXP-V', 'Silo Aereo Verde (Expeller)', 'expeller', 4.30, 0.99, 3, 2.40, 'cone', 0.99, 22.0);
            """)
            # Silo Aereo Chapa Rota: Dedicado para expeller D=4.30m, 3 chapas
            conn.execute("""
            INSERT INTO equipment_silos (code, name, product_assigned, diameter_m, sheet_height_m, total_sheets, bottom_cone_height_m, bottom_cone_type, copete_max_height_m, default_ph)
            VALUES ('SILO-EXP-R', 'Silo Aereo Chapa Rota (Expeller)', 'expeller', 4.30, 0.99, 3, 2.40, 'cone', 0.99, 22.0);
            """)
            # Confirma la insercion de los silos
            conn.commit()
