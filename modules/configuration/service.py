# Importa json para serializar configuraciones y parametros
import json
# Importa la conexion a base de datos
from core.database import get_db_connection
# Importa el registrador de eventos para auditar cambios de configuracion
from core.error_logger import log_info, log_error
# Importa la funcion horaria oficial de planta BioBalcarce (Argentina UTC-3)
from core.timezone import get_plant_now_str

# Obtiene la lista completa de tanques de aceite configurados en planta
def get_all_tanks(only_active=True):
    # Abre la conexion a la base de datos
    with get_db_connection() as conn:
        # Condicion para filtrar solo tanques activos o todos
        where_clause = "WHERE is_active = 1" if only_active else ""
        # Ejecuta la consulta ordenada por codigo de tanque
        cursor = conn.execute(f"SELECT * FROM equipment_tanks {where_clause} ORDER BY code ASC;")
        rows = [dict(row) for row in cursor.fetchall()]
        if only_active and not rows:
            conn.execute("UPDATE equipment_tanks SET is_active = 1 WHERE code IN ('TK-01', 'TK-02', 'TK-03');")
            conn.commit()
            cursor = conn.execute("SELECT * FROM equipment_tanks WHERE is_active = 1 ORDER BY code ASC;")
            rows = [dict(row) for row in cursor.fetchall()]
        return rows

# Obtiene un tanque especifico por su identificador unico
def get_tank_by_id(tank_id):
    # Abre conexion con base de datos
    with get_db_connection() as conn:
        # Busca el tanque por su ID
        row = conn.execute("SELECT * FROM equipment_tanks WHERE id = ?;", (tank_id,)).fetchone()
        # Retorna el diccionario o None si no existe
        return dict(row) if row else None

# Actualiza las dimensiones geometricas y parametros de un tanque
def update_tank_config(tank_id, name, geometry_type, diameter_m, length_m, height_m, heel_volume_l, default_density, is_active=1):
    # Abre conexion para modificar el registro
    with get_db_connection() as conn:
        # Incrementa la version de calibracion y actualiza los valores
        conn.execute("""
            UPDATE equipment_tanks
            SET name = ?, geometry_type = ?, diameter_m = ?, length_m = ?,
                height_m = ?, heel_volume_l = ?, default_density = ?,
                is_active = ?, version = version + 1, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?;
        """, (name, geometry_type, diameter_m, length_m, height_m, heel_volume_l, default_density, is_active, tank_id))
        # Confirma los cambios en la base de datos
        conn.commit()
    # Registra en log el cambio de configuracion para trazabilidad
    log_info('CONFIG', f'Tanque ID {tank_id} actualizado con nueva version de parametros.')

# Obtiene la lista completa de silos configurados en planta
def get_all_silos(only_active=True):
    # Abre conexion a la base de datos
    with get_db_connection() as conn:
        # Condicion de filtro de estado activo
        where_clause = "WHERE is_active = 1" if only_active else ""
        # Ejecuta la consulta de silos ordenada por codigo
        cursor = conn.execute(f"SELECT * FROM equipment_silos {where_clause} ORDER BY code ASC;")
        rows = [dict(row) for row in cursor.fetchall()]
        if only_active and not rows:
            conn.execute("""
                UPDATE equipment_silos
                SET is_active = 1
                WHERE code IN ('SILO-01', 'SILO-02', 'SILO-03', 'SILO-04', 'SILO-05', 'SILO-EXP-V', 'SILO-EXP-R');
            """)
            conn.commit()
            cursor = conn.execute("SELECT * FROM equipment_silos WHERE is_active = 1 ORDER BY code ASC;")
            rows = [dict(row) for row in cursor.fetchall()]
        return rows

# Obtiene un silo especifico por su identificador
def get_silo_by_id(silo_id):
    # Abre conexion a base de datos
    with get_db_connection() as conn:
        # Consulta el silo por su ID
        row = conn.execute("SELECT * FROM equipment_silos WHERE id = ?;", (silo_id,)).fetchone()
        # Retorna el registro como diccionario o None
        return dict(row) if row else None

# Actualiza las dimensiones y parametros de calibracion de un silo
def update_silo_config(silo_id, name, product_assigned, diameter_m, sheet_height_m, total_sheets,
                       bottom_cone_height_m, bottom_cone_type, min_diam_m, copete_max_height_m, default_ph, is_active=1):
    # Abre conexion a base de datos
    with get_db_connection() as conn:
        # Actualiza parametros e incrementa version
        conn.execute("""
            UPDATE equipment_silos
            SET name = ?, product_assigned = ?, diameter_m = ?, sheet_height_m = ?,
                total_sheets = ?, bottom_cone_height_m = ?, bottom_cone_type = ?,
                bottom_cone_min_diam_m = ?, copete_max_height_m = ?, default_ph = ?,
                is_active = ?, version = version + 1, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?;
        """, (name, product_assigned, diameter_m, sheet_height_m, total_sheets,
              bottom_cone_height_m, bottom_cone_type, min_diam_m, copete_max_height_m, default_ph, is_active, silo_id))
        # Confirma la actualizacion
        conn.commit()
    # Registra en log el cambio en la configuracion del silo
    log_info('CONFIG', f'Silo ID {silo_id} actualizado con nueva version de calibracion.')

# Obtiene el turno activo y operario en guardia
def get_active_shift():
    # Abre conexion a base de datos
    with get_db_connection() as conn:
        # Consulta el registro de turno activo vinculando datos de turnos
        row = conn.execute("""
            SELECT a.shift_id, a.operator_name, a.opened_at, s.name as shift_name
            FROM active_shift a
            JOIN shifts s ON a.shift_id = s.id
            WHERE a.id = 1;
        """).fetchone()
        # Retorna el diccionario con la informacion del turno
        return dict(row) if row else {'shift_id': 'TM', 'operator_name': 'Operario', 'shift_name': 'Turno Manana'}

# Obtiene la lista de turnos de trabajo disponibles segun el rol del usuario autenticado
def get_available_shifts(user_role=None):
    # Abre conexion a la base de datos
    with get_db_connection() as conn:
        # Si el usuario es Administrador del Sistema, tiene acceso a todos los turnos (incluido Turno Central)
        if user_role == 'admin_sistema':
            rows = conn.execute("SELECT * FROM shifts WHERE is_active = 1 ORDER BY start_hour ASC;").fetchall()
        else:
            # Para operarios y otros usuarios, solo se muestran los tres turnos rotativos estandar
            rows = conn.execute("SELECT * FROM shifts WHERE is_active = 1 AND admin_only = 0 ORDER BY start_hour ASC;").fetchall()
        # Retorna la lista convertida a diccionarios
        return [dict(row) for row in rows]

# Actualiza o abre un nuevo turno activo con su operario responsable validando permisos de rol
def set_active_shift(shift_id, operator_name, user_role=None):
    # Si se intenta seleccionar el Turno Central y el usuario no es Administrador del Sistema
    if shift_id == 'TC' and user_role != 'admin_sistema':
        # Lanza error de permisos explicitos para rechazar la operacion
        raise PermissionError("El Turno Central (08:00 a 16:00) está reservado exclusivamente para el usuario Administrador del Sistema.")

    # Abre conexion a base de datos
    with get_db_connection() as conn:
        # Reemplaza el registro del turno en ejecucion con estampa horaria oficial de planta
        conn.execute("""
            INSERT OR REPLACE INTO active_shift (id, shift_id, operator_name, opened_at)
            VALUES (1, ?, ?, ?);
        """, (shift_id, operator_name, get_plant_now_str()))
        # Confirma el cambio de guardia
        conn.commit()
    # Registra en log el cambio de turno
    log_info('CONFIG', f'Cambio de guardia: Turno {shift_id}, Operario: {operator_name}')

# Obtiene un diccionario consolidado de todos los equipos y sectores de planta
def get_all_equipment():
    # Obtiene lista de tanques de aceite
    tanks = get_all_tanks()
    # Obtiene lista de silos de cereal y expeller
    silos = get_all_silos()
    # Retorna diccionario consolidado para selectores
    return {'tanks': tanks, 'silos': silos}
