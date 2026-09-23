# Importa datetime para estampas de tiempo de medicion
import datetime
# Importa json para serializar snapshots de parametros
import json
# Importa conexion a base de datos
from core.database import get_db_connection
# Importa funciones de calculo de tanques
from modules.calculations.tank_calc import (
    calculate_vertical_tank_volume, calculate_horizontal_tank_volume, convert_volume_to_mass,
    calculate_vertical_tank_max_volume, calculate_horizontal_tank_max_volume
)
# Importa funciones de calculo de silos
from modules.calculations.silo_calc import (
    calculate_silo_total_volume, convert_silo_volume_to_seed_mass, convert_silo_volume_to_expeller_mass
)
# Importa el registrador de eventos
from core.error_logger import log_info, log_error

# Registra una medicion de nivel de aceite en un tanque con calculo de litros y kg
def record_tank_level(tank_id, level_m, shift_id, operator_name, density_override=None):
    # Abre conexion para leer los parametros geometricos del tanque
    with get_db_connection() as conn:
        # Busca el tanque en la base de datos
        tank = conn.execute("SELECT * FROM equipment_tanks WHERE id = ?;", (tank_id,)).fetchone()
    # Si el tanque no existe
    if not tank:
        # Lanza excepcion indicando que el tanque es inexistente
        raise ValueError(f"Tanque con ID {tank_id} no encontrado en planta.")
    # Extrae parametros del tanque
    geom_type = tank['geometry_type']
    diameter_m = tank['diameter_m']
    length_m = tank['length_m']
    height_m = tank['height_m']
    heel_l = tank['heel_volume_l']
    # Utiliza la densidad personalizada o la predeterminada del tanque
    density = density_override if density_override and density_override > 0 else tank['default_density']
    # Calcula el volumen segun la geometria del tanque
    if geom_type == 'horizontal_cylinder':
        # Aplica la formula horizontal no lineal con arccos
        volume_m3 = calculate_horizontal_tank_volume(diameter_m, length_m, level_m)
    else:
        # Aplica la formula cilindrica vertical plana
        volume_m3 = calculate_vertical_tank_volume(diameter_m, height_m, level_m)
    # Convierte el volumen calculado a litros y masa
    conversion = convert_volume_to_mass(volume_m3, density, heel_l)
    # Crea el snapshot de trazabilidad con las dimensiones usadas
    params_snapshot = json.dumps({
        'tank_code': tank['code'],
        'tank_name': tank['name'],
        'geometry_type': geom_type,
        'diameter_m': diameter_m,
        'length_m': length_m,
        'height_m': height_m,
        'heel_volume_l': heel_l,
        'density_applied': density,
        'version': tank['version']
    })
    # Estampa de tiempo actual
    now_str = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    # Guarda la medicion en la tabla de inventario de tanques
    with get_db_connection() as conn:
        cursor = conn.execute("""
            INSERT INTO inventory_tanks (
                timestamp, tank_id, level_m, volume_m3, liters, oil_kg,
                density_applied, shift_id, operator_name, params_snapshot
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """, (now_str, tank_id, level_m, conversion['volume_m3'],
              conversion['total_liters'], conversion['total_mass_kg'],
              density, shift_id, operator_name, params_snapshot))
        conn.commit()
        reading_id = cursor.lastrowid
    # Registra en log el cubicaje del tanque
    log_info('INVENTORY', f'Nivel de {tank["code"]} medido: {level_m} m -> {conversion["total_mass_kg"]} kg de aceite.')
    # Retorna la informacion consolidada
    return {
        'id': reading_id,
        'tank_code': tank['code'],
        'level_m': level_m,
        'volume_m3': conversion['volume_m3'],
        'liters': conversion['total_liters'],
        'oil_kg': conversion['total_mass_kg'],
        'density_applied': density
    }

# Registra un cubicaje de silo de semilla o expeller
def record_silo_measurement(silo_id, covered_sheets, partial_sheet_height_m,
                             cone_status, copete_height_m, shift_id, operator_name, ph_override=None):
    # Consulta la configuracion del silo
    with get_db_connection() as conn:
        silo = conn.execute("SELECT * FROM equipment_silos WHERE id = ?;", (silo_id,)).fetchone()
    # Si el silo no existe
    if not silo:
        # Lanza excepcion descriptiva
        raise ValueError(f"Silo con ID {silo_id} no encontrado en planta.")
    # Extrae dimensiones del silo
    diameter_m = silo['diameter_m']
    sheet_h = silo['sheet_height_m']
    cone_h = silo['bottom_cone_height_m']
    cone_type = silo['bottom_cone_type']
    min_diam = silo['bottom_cone_min_diam_m']
    product = silo['product_assigned']
    # Determina el peso hectolitrico o densidad a aplicar
    ph_applied = ph_override if ph_override and ph_override > 0 else silo['default_ph']
    # Calcula el volumen total del silo (cilindro + cono + copete)
    vol_breakdown = calculate_silo_total_volume(
        diameter_m, sheet_h, covered_sheets, partial_sheet_height_m,
        cone_h, cone_type, min_diam, cone_status, copete_height_m
    )
    total_volume_m3 = vol_breakdown['total_volume_m3']
    # Convierte a masa segun el producto asignado al silo
    if product == 'expeller':
        # Expeller utiliza densidad aparente kg/m3 (ph_applied actua como kg/hl * 10 o densidad directa)
        mass_info = convert_silo_volume_to_expeller_mass(total_volume_m3, ph_applied * 10.0)
    else:
        # Semilla utiliza peso hectolitrico kg/hl
        mass_info = convert_silo_volume_to_seed_mass(total_volume_m3, ph_applied)
    # Crea el snapshot de parametros aplicados
    params_snapshot = json.dumps({
        'silo_code': silo['code'],
        'silo_name': silo['name'],
        'product': product,
        'diameter_m': diameter_m,
        'sheet_height_m': sheet_h,
        'cone_height_m': cone_h,
        'ph_applied': ph_applied,
        'vol_breakdown': vol_breakdown,
        'version': silo['version']
    })
    # Estampa de tiempo
    now_str = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    # Guarda en la base de datos
    with get_db_connection() as conn:
        cursor = conn.execute("""
            INSERT INTO inventory_silos (
                timestamp, silo_id, covered_sheets, partial_sheet_height_m,
                cone_occupied_status, copete_height_m, ph_applied, volume_m3,
                stock_kg, shift_id, operator_name, params_snapshot
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """, (now_str, silo_id, covered_sheets, partial_sheet_height_m,
              cone_status, copete_height_m, ph_applied, total_volume_m3,
              mass_info['total_mass_kg'], shift_id, operator_name, params_snapshot))
        conn.commit()
        reading_id = cursor.lastrowid
    # Registra en log el cubicaje
    log_info('INVENTORY', f'Cubicaje {silo["code"]}: {covered_sheets} chapas -> {mass_info["total_mass_kg"]} kg.')
    # Retorna informacion consolidada
    return {
        'id': reading_id,
        'silo_code': silo['code'],
        'volume_m3': total_volume_m3,
        'stock_kg': mass_info['total_mass_kg'],
        'stock_tons': mass_info['total_tons']
    }

# Registra un movimiento externo de producto (despacho, ingreso de cereal, trasvase)
def record_inventory_movement(product, movement_type, origin, destination, quantity_kg,
                              document_ref, shift_id, operator_name, notes=''):
    # Estampa de tiempo actual
    now_str = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    # Guarda en la tabla de movimientos
    with get_db_connection() as conn:
        conn.execute("""
            INSERT INTO inventory_movements (
                timestamp, product, movement_type, origin, destination,
                quantity_kg, document_ref, shift_id, operator_name, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
        """, (now_str, product, movement_type, origin, destination,
              quantity_kg, document_ref, shift_id, operator_name, notes))
        conn.commit()
    # Registra en log el movimiento
    log_info('INVENTORY', f'Movimiento registrado: {movement_type} de {quantity_kg} kg de {product}.')

# Obtiene los 3 stocks clave actuales de la planta en un golpe de vista
def get_total_plant_stocks():
    # Inicializa los acumuladores de existencias
    total_oil_kg = 0.0
    total_oil_liters = 0.0
    total_seed_kg = 0.0
    total_expeller_kg = 0.0
    tanks_summary = []
    silos_summary = []
    # Abre conexion para consultar las ultimas mediciones de cada equipo activo
    with get_db_connection() as conn:
        # Consulta el ultimo registro de cada tanque de aceite activo
        tanks = conn.execute("SELECT * FROM equipment_tanks WHERE is_active = 1 ORDER BY code ASC;").fetchall()
        for t in tanks:
            geom_type = t['geometry_type']
            diameter_m = float(t['diameter_m'])
            length_m = float(t['length_m'])
            height_m = float(t['height_m'])
            density = float(t['default_density'] or 0.92)

            if geom_type == 'horizontal_cylinder':
                max_level_m = diameter_m
                max_vol_m3 = calculate_horizontal_tank_max_volume(diameter_m, length_m)
                type_label = 'Cilíndrico Horizontal'
                dims_label = f"Ø {diameter_m:.2f} m × L {length_m:.2f} m"
            else:
                max_level_m = height_m
                max_vol_m3 = calculate_vertical_tank_max_volume(diameter_m, height_m)
                type_label = 'Cilíndrico Vertical'
                dims_label = f"Ø {diameter_m:.2f} m × H {height_m:.2f} m"

            max_liters = round(max_vol_m3 * 1000.0, 1)
            max_oil_kg = round(max_liters * density, 1)

            # Obtiene la ultima medicion de este tanque
            last_reading = conn.execute("""
                SELECT level_m, volume_m3, liters, oil_kg, timestamp
                FROM inventory_tanks
                WHERE tank_id = ?
                ORDER BY timestamp DESC
                LIMIT 1;
            """, (t['id'],)).fetchone()

            # Si tiene medicion registrada
            if last_reading:
                oil_kg = round(float(last_reading['oil_kg']), 1)
                liters = round(float(last_reading['liters']), 1)
                level_m = round(float(last_reading['level_m']), 2)
                total_oil_kg += oil_kg
                total_oil_liters += liters
                pct_fill = round((liters / max_liters) * 100.0, 1) if max_liters > 0 else 0.0
                pct_height = round((level_m / max_level_m) * 100.0, 1) if max_level_m > 0 else 0.0
                pct_fill = max(0.0, min(100.0, pct_fill))
                pct_height = max(0.0, min(100.0, pct_height))
                tanks_summary.append({
                    'id': t['id'],
                    'code': t['code'],
                    'name': t['name'],
                    'geometry_type': geom_type,
                    'is_horizontal': (geom_type == 'horizontal_cylinder'),
                    'vertical_profile': 'narrow' if (geom_type != 'horizontal_cylinder' and diameter_m <= 2.2) else 'wide',
                    'type_label': type_label,
                    'dims_label': dims_label,
                    'diameter_m': diameter_m,
                    'length_m': length_m,
                    'height_m': height_m,
                    'max_level_m': max_level_m,
                    'max_liters': max_liters,
                    'max_oil_kg': max_oil_kg,
                    'level_m': level_m,
                    'liters': liters,
                    'oil_kg': oil_kg,
                    'pct_fill': pct_fill,
                    'pct_height': pct_height,
                    'timestamp': last_reading['timestamp']
                })
            else:
                tanks_summary.append({
                    'id': t['id'],
                    'code': t['code'],
                    'name': t['name'],
                    'geometry_type': geom_type,
                    'is_horizontal': (geom_type == 'horizontal_cylinder'),
                    'vertical_profile': 'narrow' if (geom_type != 'horizontal_cylinder' and diameter_m <= 2.2) else 'wide',
                    'type_label': type_label,
                    'dims_label': dims_label,
                    'diameter_m': diameter_m,
                    'length_m': length_m,
                    'height_m': height_m,
                    'max_level_m': max_level_m,
                    'max_liters': max_liters,
                    'max_oil_kg': max_oil_kg,
                    'level_m': 0.0,
                    'liters': 0.0,
                    'oil_kg': 0.0,
                    'pct_fill': 0.0,
                    'pct_height': 0.0,
                    'timestamp': 'Sin medición'
                })

        # Consulta las ultimas mediciones de cada silo activo con todas sus dimensiones
        silos = conn.execute("SELECT * FROM equipment_silos WHERE is_active = 1 ORDER BY code ASC;").fetchall()
        for s in silos:
            d_m = float(s['diameter_m'])
            sh_h_m = float(s['sheet_height_m'] or 0.99)
            tot_sheets = int(s['total_sheets'])
            cyl_h_m = round(tot_sheets * sh_h_m, 2)
            cone_h_m = float(s['bottom_cone_height_m'] or 0.0)
            cone_type = s['bottom_cone_type'] or 'cone'
            min_d_m = float(s['bottom_cone_min_diam_m'] or 0.0)
            cop_max_h_m = float(s['copete_max_height_m'] or 0.0)
            def_ph = float(s['default_ph'] or (40.0 if s['product_assigned'] == 'girasol' else 25.0))

            # Calcula la capacidad maxima del silo (cono lleno + todas las chapas + copete maximo)
            max_vol_calc = calculate_silo_total_volume(
                d_m, sh_h_m, tot_sheets, 0.0,
                cone_h_m, cone_type, min_d_m, 'lleno',
                cop_max_h_m
            )
            max_v_m3 = max_vol_calc['total_volume_m3']
            if s['product_assigned'] == 'expeller':
                exp_density = def_ph * 10.0 if def_ph < 100.0 else def_ph
                max_mass_calc = convert_silo_volume_to_expeller_mass(max_v_m3, bulk_density_kg_m3=exp_density)
                product_label = 'Expeller'
            else:
                max_mass_calc = convert_silo_volume_to_seed_mass(max_v_m3, hectolitric_weight_kg_hl=def_ph)
                product_label = 'Semilla Girasol'

            max_stock_kg = round(max_mass_calc['total_mass_kg'], 1)
            max_stock_tons = round(max_mass_calc['total_tons'], 2)

            # Obtiene la ultima lectura de este silo
            last_silo = conn.execute("""
                SELECT covered_sheets, partial_sheet_height_m, cone_occupied_status,
                       copete_height_m, volume_m3, stock_kg, timestamp
                FROM inventory_silos
                WHERE silo_id = ?
                ORDER BY timestamp DESC
                LIMIT 1;
            """, (s['id'],)).fetchone()

            # Si existe medicion previa
            if last_silo:
                kg = round(float(last_silo['stock_kg']), 1)
                cov_sheets = round(float(last_silo['covered_sheets']), 1)
                v_m3 = round(float(last_silo['volume_m3']), 2)
                cone_st = last_silo['cone_occupied_status'] or 'lleno'
                cop_h = round(float(last_silo['copete_height_m'] or 0.0), 2)
                if s['product_assigned'] == 'expeller':
                    total_expeller_kg += kg
                else:
                    total_seed_kg += kg
                pct_fill = round((kg / max_stock_kg) * 100.0, 1) if max_stock_kg > 0 else 0.0
                pct_fill = max(0.0, min(100.0, pct_fill))
                pct_sheets = round((cov_sheets / tot_sheets) * 100.0, 1) if tot_sheets > 0 else 0.0
                pct_sheets = max(0.0, min(100.0, pct_sheets))

                silos_summary.append({
                    'id': s['id'],
                    'code': s['code'],
                    'name': s['name'],
                    'product': s['product_assigned'],
                    'product_label': product_label,
                    'diameter_m': d_m,
                    'd_m': d_m,
                    'sheet_height_m': sh_h_m,
                    'total_sheets': tot_sheets,
                    'cylinder_height_m': cyl_h_m,
                    'bottom_cone_height_m': cone_h_m,
                    'copete_max_height_m': cop_max_h_m,
                    'max_volume_m3': max_v_m3,
                    'max_stock_kg': max_stock_kg,
                    'max_stock_tons': max_stock_tons,
                    'covered_sheets': cov_sheets,
                    'cone_status': cone_st,
                    'copete_height_m': cop_h,
                    'volume_m3': v_m3,
                    'stock_kg': kg,
                    'stock_tons': round(kg / 1000.0, 2),
                    'pct_fill': pct_fill,
                    'pct_sheets': pct_sheets,
                    'timestamp': last_silo['timestamp']
                })
            else:
                silos_summary.append({
                    'id': s['id'],
                    'code': s['code'],
                    'name': s['name'],
                    'product': s['product_assigned'],
                    'product_label': product_label,
                    'diameter_m': d_m,
                    'd_m': d_m,
                    'sheet_height_m': sh_h_m,
                    'total_sheets': tot_sheets,
                    'cylinder_height_m': cyl_h_m,
                    'bottom_cone_height_m': cone_h_m,
                    'copete_max_height_m': cop_max_h_m,
                    'max_volume_m3': max_v_m3,
                    'max_stock_kg': max_stock_kg,
                    'max_stock_tons': max_stock_tons,
                    'covered_sheets': 0.0,
                    'cone_status': 'vacio',
                    'copete_height_m': 0.0,
                    'volume_m3': 0.0,
                    'stock_kg': 0.0,
                    'stock_tons': 0.0,
                    'pct_fill': 0.0,
                    'pct_sheets': 0.0,
                    'timestamp': 'Sin medición'
                })

    # Capacidades globales de planta
    total_oil_capacity_liters = sum(t['max_liters'] for t in tanks_summary)
    total_oil_capacity_kg = sum(t['max_oil_kg'] for t in tanks_summary)
    total_oil_pct_fill = round((total_oil_liters / total_oil_capacity_liters) * 100.0, 1) if total_oil_capacity_liters > 0 else 0.0

    total_seed_capacity_kg = sum(s['max_stock_kg'] for s in silos_summary if s['product'] != 'expeller')
    total_seed_capacity_tons = round(total_seed_capacity_kg / 1000.0, 1)
    total_seed_pct_fill = round((total_seed_kg / total_seed_capacity_kg) * 100.0, 1) if total_seed_capacity_kg > 0 else 0.0

    total_expeller_capacity_kg = sum(s['max_stock_kg'] for s in silos_summary if s['product'] == 'expeller')
    total_expeller_capacity_tons = round(total_expeller_capacity_kg / 1000.0, 1)
    total_expeller_pct_fill = round((total_expeller_kg / total_expeller_capacity_kg) * 100.0, 1) if total_expeller_capacity_kg > 0 else 0.0

    # Retorna las existencias consolidadas de planta
    return {
        'total_oil_kg': round(total_oil_kg, 2),
        'total_oil_liters': round(total_oil_liters, 2),
        'total_oil_capacity_liters': round(total_oil_capacity_liters, 1),
        'total_oil_capacity_kg': round(total_oil_capacity_kg, 1),
        'total_oil_pct_fill': total_oil_pct_fill,
        'total_seed_kg': round(total_seed_kg, 2),
        'total_seed_tons': round(total_seed_kg / 1000.0, 2),
        'total_seed_capacity_kg': total_seed_capacity_kg,
        'total_seed_capacity_tons': total_seed_capacity_tons,
        'total_seed_pct_fill': total_seed_pct_fill,
        'total_expeller_kg': round(total_expeller_kg, 2),
        'total_expeller_tons': round(total_expeller_kg / 1000.0, 2),
        'total_expeller_capacity_kg': total_expeller_capacity_kg,
        'total_expeller_capacity_tons': total_expeller_capacity_tons,
        'total_expeller_pct_fill': total_expeller_pct_fill,
        'tanks': tanks_summary,
        'silos': silos_summary
    }
