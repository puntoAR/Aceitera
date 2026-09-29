# Importa el modulo sqlite3 para gestionar la base de datos relacional integrada
import sqlite3
# Importa json para serializar y deserializar los parametros aplicados en snapshots
import json
# Importa el modulo de configuracion general del sistema
import config
# Exporta DATABASE_PATH para compatibilidad hacia atras
DATABASE_PATH = config.DATABASE_PATH
# Importa base64 y requests para conectividad HTTP con Turso Cloud SQLite
import base64
import requests
# Importa el registrador de eventos para auditar las operaciones sobre la base de datos
from core.error_logger import log_info, log_error

# Importa contextlib para manejar el ciclo de vida y cierre seguro de conexiones
import contextlib

class TursoRow(dict):
    """Representa una fila con acceso por clave de columna o por índice numérico."""
    def __init__(self, cols, values):
        super().__init__()
        self._cols = cols
        self._values = values
        for c, v in zip(cols, values):
            self[c] = v

    def __getitem__(self, item):
        if isinstance(item, int):
            return self._values[item]
        return super().__getitem__(item)

# Cursor compatible con la API de sqlite3 para Turso Cloud
class TursoCursor:
    # Constructor que inicializa columnas, filas transformadas y lastrowid
    def __init__(self, cols, rows, last_insert_rowid=None):
        # Asigna nombres de columnas
        self.cols = cols
        # Instancia filas TursoRow con acceso por clave o indice
        self._rows = [TursoRow(cols, r) for r in rows]
        # Puntero de posicion para fetchone
        self._idx = 0
        # ID autoincremental de la ultima insercion
        self.lastrowid = int(last_insert_rowid) if last_insert_rowid is not None else None

    # Obtiene la siguiente fila del cursor o None si se acabaron
    def fetchone(self):
        # Comprueba si quedan filas por leer
        if self._idx < len(self._rows):
            # Obtiene la fila actual
            r = self._rows[self._idx]
            # Avanza el indice del cursor
            self._idx += 1
            # Retorna la fila
            return r
        # Retorna None si no hay mas filas
        return None

    # Obtiene todas las filas restantes del cursor
    def fetchall(self):
        # Toma el slice de filas restantes
        res = self._rows[self._idx:]
        # Lleva el indice al final
        self._idx = len(self._rows)
        # Retorna la lista de filas
        return res

    # Habilita la iteracion directa sobre las filas del cursor
    def __iter__(self):
        # Retorna un iterador sobre las filas restantes
        return iter(self._rows[self._idx:])

# Cursor intermediario para emular la interfaz de sqlite3.Cursor sobre TursoConnection
class TursoStatementCursor:
    # Metodo constructor que recibe la conexion activa de Turso
    def __init__(self, connection):
        # Almacena la referencia a la conexion de Turso
        self._connection = connection
        # Inicializa el cursor interno de resultados en None
        self._cursor = None
        # Identificador autoincremental de la ultima fila insertada
        self.lastrowid = None

    # Ejecuta una sentencia SQL en Turso y actualiza el estado del cursor
    def execute(self, sql, params=()):
        # Delega la ejecucion HTTP a la conexion de Turso
        self._cursor = self._connection.execute(sql, params)
        # Sincroniza el ultimo rowid insertado
        self.lastrowid = self._cursor.lastrowid
        # Retorna self para permitir encadenamiento de llamadas
        return self

    # Ejecuta una misma sentencia SQL para una secuencia de parametros
    def executemany(self, sql, seq_of_params):
        # Itera secuencialmente sobre la lista de parametros
        for p in seq_of_params:
            # Ejecuta cada tupla de parametros individualmente
            self.execute(sql, p)
        # Retorna el cursor actualizado
        return self

    # Obtiene la siguiente fila del conjunto de resultados
    def fetchone(self):
        # Verifica si existe un conjunto activo de resultados
        if self._cursor is not None:
            # Retorna la siguiente fila disponible
            return self._cursor.fetchone()
        # Retorna None si no hay resultados disponibles
        return None

    # Obtiene todas las filas restantes del conjunto de resultados
    def fetchall(self):
        # Verifica si existe un conjunto activo de resultados
        if self._cursor is not None:
            # Retorna la totalidad de filas restantes
            return self._cursor.fetchall()
        # Retorna lista vacia si no hay cursor
        return []

    # Permite la iteracion directa sobre el cursor (ej: for row in cursor:)
    def __iter__(self):
        # Verifica si existe cursor de resultados disponible
        if self._cursor is not None:
            # Retorna el iterador sobre las filas restantes
            return iter(self._cursor)
        # Retorna iterador vacio en caso contrario
        return iter([])

    # Cierra el cursor liberando referencias a los resultados
    def close(self):
        # Reinicia el cursor a None
        self._cursor = None

# Conexion cliente HTTP a Turso Cloud SQLite compatible con sqlite3
class TursoConnection:
    # Constructor que configura URL del pipeline y encabezados de autorizacion
    def __init__(self, url, token):
        # Limpia y normaliza el protocolo libsql:// a https://
        cleaned_url = url.replace('libsql://', 'https://').rstrip('/')
        # Asegura la ruta del pipeline v2 de Turso
        if not cleaned_url.endswith('/v2/pipeline'):
            # Concatena el sufijo de pipeline v2
            cleaned_url += '/v2/pipeline'
        # Almacena la URL final de la API
        self.pipeline_url = cleaned_url
        # Almacena el token de autorizacion
        self.token = token
        # Configura encabezados HTTP obligatorios
        self.headers = {
            # Cabecera Bearer con el token de Turso
            "Authorization": f"Bearer {self.token}",
            # Especifica payload JSON
            "Content-Type": "application/json"
        }
        # Inicializa atributo row_factory compatible con sqlite3
        self.row_factory = None

    def _to_turso_arg(self, val):
        if val is None:
            return {"type": "null"}
        elif isinstance(val, bool):
            return {"type": "integer", "value": "1" if val else "0"}
        elif isinstance(val, int):
            return {"type": "integer", "value": str(val)}
        elif isinstance(val, float):
            return {"type": "float", "value": val}
        elif isinstance(val, (bytes, bytearray)):
            return {"type": "blob", "base64": base64.b64encode(val).decode('ascii')}
        else:
            return {"type": "text", "value": str(val)}

    def _from_turso_value(self, val_obj):
        if not isinstance(val_obj, dict):
            return val_obj
        t = val_obj.get("type")
        if t == "null":
            return None
        elif t == "integer":
            return int(val_obj.get("value", 0))
        elif t == "float":
            return float(val_obj.get("value", 0.0))
        elif t == "text":
            return val_obj.get("value", "")
        elif t == "blob":
            return base64.b64decode(val_obj.get("base64", ""))
        return val_obj.get("value")

    def execute(self, sql, params=()):
        clean_sql = str(sql).strip()
        args = [self._to_turso_arg(p) for p in params]
        payload = {
            "requests": [
                {
                    "type": "execute",
                    "stmt": {
                        "sql": clean_sql,
                        "args": args
                    }
                },
                {
                    "type": "close"
                }
            ]
        }
        resp = requests.post(self.pipeline_url, headers=self.headers, json=payload, timeout=15)
        if resp.status_code != 200:
            raise sqlite3.OperationalError(f"Error HTTP Turso ({resp.status_code}): {resp.text}")
        
        data = resp.json()
        results = data.get("results", [])
        if not results:
            raise sqlite3.OperationalError("Respuesta vacía de Turso")
        
        first = results[0]
        if first.get("type") == "error":
            err_msg = first.get("error", {}).get("message", "Error desconocido en Turso")
            raise sqlite3.OperationalError(f"Error Turso: {err_msg}")
        
        exec_res = first.get("response", {}).get("result", {})
        col_names = [c.get("name") for c in exec_res.get("cols", [])]
        raw_rows = exec_res.get("rows", [])
        parsed_rows = [[self._from_turso_value(v) for v in r] for r in raw_rows]
        last_rowid = exec_res.get("last_insert_rowid")

        return TursoCursor(col_names, parsed_rows, last_rowid)

    # Retorna un cursor compatible con sqlite3.Cursor
    def cursor(self):
        # Crea y entrega una instancia de TursoStatementCursor vinculada a esta conexion
        return TursoStatementCursor(self)

    # Ejecuta una misma sentencia SQL sobre una lista de parametros
    def executemany(self, sql, seq_of_params):
        # Itera sobre cada grupo de parametros suministrado
        for p in seq_of_params:
            # Ejecuta la sentencia para el parametro actual
            self.execute(sql, p)

    # Ejecuta multiples sentencias SQL separadas por punto y coma
    def executescript(self, sql_script):
        # Divide el script en declaraciones individuales
        for stmt in str(sql_script).split(';'):
            # Limpia espacios en blanco de cada sentencia
            clean_stmt = stmt.strip()
            # Si la sentencia no esta vacia la ejecuta
            if clean_stmt:
                # Ejecuta la instruccion individual en Turso
                self.execute(clean_stmt)

    # Confirma transaccion en Turso (auto-commit en pipeline HTTP)
    def commit(self):
        # No requiere accion adicional al operar en modo auto-commit
        pass

    # Revierte transaccion en Turso
    def rollback(self):
        # No requiere accion adicional al operar en modo auto-commit
        pass

    # Cierra conexion de Turso
    def close(self):
        # No requiere cierre de socket persistente al ser HTTP stateless
        pass

# Obtiene una conexion a la base de datos (SQLite local o Turso Cloud)
@contextlib.contextmanager
def get_db_connection():
    # Si se han configurado credenciales de Turso Cloud SQLite, usa persistencia en la nube
    if getattr(config, 'USE_TURSO', False):
        conn = TursoConnection(config.TURSO_DATABASE_URL, config.TURSO_AUTH_TOKEN)
        yield conn
    else:
        # Establece la conexion con el archivo de base de datos en disco local usando la ruta dinamica
        conn = sqlite3.connect(config.DATABASE_PATH)
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
            allowed_modules TEXT DEFAULT NULL,    -- Modulos autorizados adicionales para mantenimiento
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
            origin_file TEXT,                     -- Archivo exacto donde se origino
            origin_line INTEGER,                  -- Numero de linea de codigo causante
            origin_func TEXT,                     -- Funcion o metodo donde fallo
            origin_code TEXT,                     -- Renglon de codigo que disparo la excepcion
            resolved INTEGER DEFAULT 0,           -- Indicador de resolucion por admin
            resolved_at TIMESTAMP                 -- Fecha y hora en que fue resuelto
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
            params_snapshot TEXT,                       -- JSON con snapshot de constantes
            time_slot TEXT                              -- Franja horaria oficial (TM: 06-14, TT: 14-22, TN: 22-06)
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
            press_number INTEGER DEFAULT 2,         -- 1=Prensa 1 (indicativo), 2=Prensa 2 (producto final relevante)
            shift_id TEXT NOT NULL,                 -- Turno de produccion
            operator_name TEXT NOT NULL,            -- Analista responsable
            moisture_pct REAL,                      -- Humedad calculada en porcentaje
            fat_pct REAL,                           -- Materia grasa calculada en porcentaje
            foreign_matter_pct REAL,                -- Materia extrana en porcentaje
            acidity_pct REAL,                       -- Acidez libre en porcentaje (para aceite)
            raw_data_json TEXT,                     -- JSON con masas iniciales, secas, crisoles
            notes TEXT,                             -- Notas u observaciones analiticas
            time_slot TEXT                          -- Franja horaria oficial (TM: 06-14, TT: 14-22, TN: 22-06)
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

        # Crea la tabla de actividades de mantenimiento (operativas y planificadas)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS maintenance_activities (
            id INTEGER PRIMARY KEY AUTOINCREMENT,         -- Identificador unico de la tarea
            title TEXT NOT NULL,                          -- Titulo o sintesis de la intervencion
            category TEXT NOT NULL,                       -- operativa, planificada_con_parada, planificada_sin_parada
            equipment_tag TEXT,                           -- Equipo, sector o maquina intervenida
            priority TEXT NOT NULL DEFAULT 'media',       -- baja, media, alta, critica
            status TEXT NOT NULL DEFAULT 'pendiente',     -- pendiente, en_progreso, completada, cancelada
            description TEXT,                             -- Descripcion tecnica del trabajo o falla
            reported_by TEXT NOT NULL,                    -- Nombre del usuario u operario que reporto
            assigned_to TEXT,                             -- Tecnico o responsable asignado
            scheduled_date TEXT,                          -- Fecha programada para la realizacion
            completed_at TIMESTAMP,                       -- Fecha y hora real de finalizacion
            resolution_notes TEXT,                        -- Informe tecnico de la resolucion
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP -- Fecha de creacion del registro
        );
        """)

        # Crea la tabla de fotografias y registros visuales de reparaciones
        conn.execute("""
        CREATE TABLE IF NOT EXISTS maintenance_images (
            id INTEGER PRIMARY KEY AUTOINCREMENT,         -- Identificador unico de la imagen
            activity_id INTEGER NOT NULL,                 -- Tarea de mantenimiento asociada
            filename TEXT NOT NULL,                       -- Nombre del archivo almacenado en disco
            caption TEXT,                                 -- Epigrafe explicativo (antes, durante, repuesto, final)
            uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, -- Fecha y hora de subida
            FOREIGN KEY (activity_id) REFERENCES maintenance_activities(id) ON DELETE CASCADE
        );
        """)

        # Crea la tabla de pañol y stock de repuestos e insumos industriales
        conn.execute("""
        CREATE TABLE IF NOT EXISTS spare_parts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,         -- Identificador unico del repuesto
            code TEXT UNIQUE NOT NULL,                    -- Codigo interno o de fabricante (ej. ROD-6205)
            name TEXT NOT NULL,                           -- Denominacion descriptiva del repuesto
            category TEXT NOT NULL,                       -- Rodamientos, Correas, Retenes, Filtros, Lubricantes, etc.
            equipment_assigned TEXT,                      -- Equipo o linea donde se utiliza
            is_consumable INTEGER DEFAULT 0,              -- 1 si es consumible, 0 si es repuesto mecanico
            stock_quantity REAL NOT NULL DEFAULT 0.0,     -- Existencia fisica actual en stock
            min_stock REAL NOT NULL DEFAULT 0.0,          -- Stock minimo de seguridad para alerta
            unit TEXT NOT NULL DEFAULT 'unidades',        -- Unidad de medida: unidades, litros, metros, kg
            location TEXT,                                -- Ubicacion fisica en pañol o estanteria
            notes TEXT,                                   -- Observaciones, proveedor o especificaciones
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP -- Ultima modificacion del registro
        );
        """)

        # Crea la tabla de movimientos de inventario de repuestos
        conn.execute("""
        CREATE TABLE IF NOT EXISTS spare_parts_movements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,         -- Identificador unico del movimiento
            spare_part_id INTEGER NOT NULL,               -- Repuesto afectado
            activity_id INTEGER,                          -- Tarea de mantenimiento donde se aplico (opcional)
            movement_type TEXT NOT NULL,                  -- ingreso, egreso_mantenimiento, ajuste
            quantity REAL NOT NULL,                       -- Cantidad involucrada
            operator_name TEXT NOT NULL,                  -- Responsable del movimiento
            reason TEXT,                                  -- Motivo o justificacion del movimiento
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP, -- Momento del registro
            FOREIGN KEY (spare_part_id) REFERENCES spare_parts(id)
        );
        """)

        # Crea la tabla de pesadas y movimientos de balanza de camiones
        conn.execute("""
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
        """)

        # Crea la tabla de configuracion de licenciamiento y limitaciones programables
        conn.execute("""
        CREATE TABLE IF NOT EXISTS system_licensing_config (
            id INTEGER PRIMARY KEY,
            client_name TEXT DEFAULT 'BioBalcarce S.A.',
            plan_name TEXT DEFAULT 'Plan Libre Uso Anual (puntoAR)',
            license_mode TEXT DEFAULT 'libre_uso',
            license_key TEXT DEFAULT 'PTAR-ACTV-2026-OK',
            start_date TEXT DEFAULT '2026-09-01',
            activation_date TEXT DEFAULT '2026-09-01',
            expiration_date TEXT DEFAULT '2027-09-01',
            is_active INTEGER DEFAULT 1,
            max_active_users INTEGER DEFAULT 0,
            max_users INTEGER DEFAULT 50,
            block_dashboard INTEGER DEFAULT 0,
            block_data_entry INTEGER DEFAULT 0,
            block_reports INTEGER DEFAULT 0,
            block_updates INTEGER DEFAULT 0,
            status_notes TEXT DEFAULT 'Licencia inicial de planta',
            custom_notice_message TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_by TEXT
        );
        """)

        # Confirma las transacciones de creacion de tablas
        conn.commit()

    # Asegura columnas y fila unica de licenciamiento
    with get_db_connection() as conn:
        ensure_licensing_schema(conn)

    # Ejecuta el llenado inicial de datos semilla para turnos y equipos base
    seed_initial_data()
    # Registra en el log la finalizacion exitosa de la inicializacion
    log_info('DATABASE', 'Base de datos y esquemas inicializados correctamente')

# Asegura que la tabla system_licensing_config posea todas las columnas requeridas
def ensure_licensing_schema(conn):
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(system_licensing_config);")
    cols = {row[1] for row in cursor.fetchall()}
    needed = [
        ("client_name", "TEXT DEFAULT 'BioBalcarce S.A.'"),
        ("license_key", "TEXT DEFAULT 'PTAR-ACTV-2026-OK'"),
        ("start_date", "TEXT DEFAULT '2026-09-01'"),
        ("is_active", "INTEGER DEFAULT 1"),
        ("max_users", "INTEGER DEFAULT 50"),
        ("status_notes", "TEXT DEFAULT 'Licencia inicial de planta'")
    ]
    for cname, cdef in needed:
        if cname not in cols:
            try:
                cursor.execute(f"ALTER TABLE system_licensing_config ADD COLUMN {cname} {cdef};")
            except Exception:
                pass
    # Asegura la existencia de la fila 1
    cursor.execute("SELECT id FROM system_licensing_config WHERE id = 1;")
    if not cursor.fetchone():
        cursor.execute("""
            INSERT OR IGNORE INTO system_licensing_config (id, client_name, license_mode, license_key, start_date, expiration_date, is_active, max_users)
            VALUES (1, 'BioBalcarce S.A.', 'libre_uso', 'PTAR-ACTV-2026-OK', '2026-09-01', '2027-09-01', 1, 50);
        """)
    conn.commit()

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

        # Inserta usuarios y perfiles predeterminados si no existen en el sistema
        # Inserta usuario Administrador del Sistema si no existe
        conn.execute("INSERT OR IGNORE INTO users (username, full_name, role, pin, dni, phone, approval_status) VALUES ('admin', 'Administrador del Sistema', 'admin_sistema', '1234', '10000000', '5492266000001', 'aprobado');")
        # Inserta usuario Gerencia si no existe
        conn.execute("INSERT OR IGNORE INTO users (username, full_name, role, pin, dni, phone, approval_status) VALUES ('gerente', 'Gerencia General', 'gerencia', '3333', '20000000', '5492266000002', 'aprobado');")
        # Inserta usuario Operario de Planta si no existe
        conn.execute("INSERT OR IGNORE INTO users (username, full_name, role, pin, dni, phone, approval_status) VALUES ('operario', 'Operario de Planta', 'usuario', '1111', '30000000', '5492266000003', 'aprobado');")
        # Inserta usuario Analista de Laboratorio si no existe
        conn.execute("INSERT OR IGNORE INTO users (username, full_name, role, pin, dni, phone, approval_status) VALUES ('laboratorio', 'Analista de Calidad', 'usuario', '2222', '40000000', '5492266000004', 'aprobado');")
        # Inserta usuario Mantenimiento si no existe
        conn.execute("INSERT OR IGNORE INTO users (username, full_name, role, pin, dni, phone, approval_status) VALUES ('mantenimiento', 'Técnico de Mantenimiento', 'mantenimiento', '4444', '50000000', '5492266000005', 'aprobado');")
        # Confirma los usuarios creados
        conn.commit();

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

        # Inserta catalogo inicial de repuestos y consumibles base de planta si la tabla esta vacia
        parts_count = conn.execute("SELECT COUNT(*) FROM spare_parts;").fetchone()[0]
        # Si no existen repuestos cargados previamente
        if parts_count == 0:
            # Inserta rodamiento SKF de prensa principal
            conn.execute("""
            INSERT INTO spare_parts (code, name, category, equipment_assigned, is_consumable, stock_quantity, min_stock, unit, location)
            VALUES ('ROD-SKF-22218', 'Rodamiento Oscilante de Rodillos SKF 22218', 'Rodamientos', 'Prensa de Extracción 1', 0, 4.0, 2.0, 'unidades', 'Estante A1');
            """)
            # Inserta correa trapezoidal seccion B
            conn.execute("""
            INSERT INTO spare_parts (code, name, category, equipment_assigned, is_consumable, stock_quantity, min_stock, unit, location)
            VALUES ('CORR-B-75', 'Correa en V Sección B-75 Industrial', 'Correas', 'Molino Quebrador', 0, 8.0, 4.0, 'unidades', 'Estante B2');
            """)
            # Inserta grasa de alta temperatura para prensas (consumible)
            conn.execute("""
            INSERT INTO spare_parts (code, name, category, equipment_assigned, is_consumable, stock_quantity, min_stock, unit, location)
            VALUES ('LUB-GRASA-EP2', 'Grasa Litio Complejo EP2 Alta Temperatura', 'Lubricantes', 'Prensas y Reductores', 1, 35.0, 15.0, 'kg', 'Pañol Lubricantes');
            """)
            # Inserta tela filtrante para filtro prensa (consumible)
            conn.execute("""
            INSERT INTO spare_parts (code, name, category, equipment_assigned, is_consumable, stock_quantity, min_stock, unit, location)
            VALUES ('FILT-TELA-PP', 'Tela Filtrante Polipropileno 800x800mm', 'Filtros', 'Filtro Prensa de Aceite', 1, 24.0, 10.0, 'unidades', 'Estante C3');
            """)
            # Inserta reten de aceite para eje reductor
            conn.execute("""
            INSERT INTO spare_parts (code, name, category, equipment_assigned, is_consumable, stock_quantity, min_stock, unit, location)
            VALUES ('RET-65-90-10', 'Retén Doble Labio NBR 65x90x10 mm', 'Retenes', 'Reductor Principal', 0, 6.0, 2.0, 'unidades', 'Cajón R1');
            """)
            # Confirma la carga inicial de repuestos
            conn.commit()

# Limpia los datos operativos de prueba a cero para preparar la planta para produccion real
def reset_production_operational_data():
    # Registra inicio del proceso de limpieza en el log
    log_info('DATABASE', 'Iniciando limpieza a cero de datos operativos para produccion')
    # Abre conexion para ejecutar las sentencias de limpieza
    with get_db_connection() as conn:
        # Vacia pesadas de linea
        conn.execute("DELETE FROM production_weighings;")
        # Vacia paradas de linea
        conn.execute("DELETE FROM line_stops;")
        # Vacia cubicajes de tanques
        conn.execute("DELETE FROM inventory_tanks;")
        # Vacia cubicajes de silos
        conn.execute("DELETE FROM inventory_silos;")
        # Vacia existencias de expeller
        conn.execute("DELETE FROM inventory_expeller;")
        # Vacia movimientos de granos y aceite
        conn.execute("DELETE FROM inventory_movements;")
        # Vacia determinaciones de laboratorio
        conn.execute("DELETE FROM lab_analyses;")
        # Vacia conciliaciones de balance de masa
        conn.execute("DELETE FROM shift_reconciliations;")
        # Vacia despachos de camiones de aceite
        conn.execute("DELETE FROM oil_truck_dispatches;")
        # Vacia codigos de recuperacion de clave ya vencidos
        conn.execute("DELETE FROM password_reset_codes;")
        # Vacia errores historicos de prueba
        conn.execute("DELETE FROM system_errors;")
        # Vacia logs de auditoria anteriores
        conn.execute("DELETE FROM audit_logs;")
        # Inserta registro de auditoria documentando la puesta a cero oficial
        conn.execute("""
        INSERT INTO audit_logs (category, action, details, status)
        VALUES ('SISTEMA', 'RESET_PRODUCCION', 'Limpieza general de datos operativos a cero completada para produccion.', 'OK');
        """)
        # Reinicia los contadores autoincrementales de las tablas operativas
        conn.execute("DELETE FROM sqlite_sequence WHERE name IN ('production_weighings', 'line_stops', 'inventory_tanks', 'inventory_silos', 'inventory_expeller', 'inventory_movements', 'lab_analyses', 'shift_reconciliations', 'oil_truck_dispatches', 'password_reset_codes', 'system_errors');")
        # Confirma la operacion de limpieza en disco
        conn.commit()
    # Registra en log la finalizacion de la limpieza
    log_info('DATABASE', 'Datos operativos reiniciados exitosamente. Parametros maestros preservados.')
