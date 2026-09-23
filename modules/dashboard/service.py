# Importa los servicios de inventario, produccion, laboratorio y rendimiento
from modules.inventory.service import get_total_plant_stocks
from modules.production.service import get_shift_speed_summary, get_recent_weighings
from modules.configuration.service import get_active_shift
# Importa get_latest_reconciliation y get_recent_reconciliations para el historial de balances
from modules.yield_balance.service import get_latest_reconciliation, get_recent_reconciliations

# Genera el resumen consolidado ejecutivo de la planta en un golpe de vista
def get_executive_dashboard_data():
    # Obtiene existencias totales de los 3 stocks clave
    stocks = get_total_plant_stocks()
    # Obtiene datos del turno activo y guardia en marcha
    active_shift = get_active_shift()
    # Obtiene el resumen de velocidad y proyecciones del turno
    speed_summary = get_shift_speed_summary(active_shift['shift_id'])
    # Obtiene las ultimas pesadas para la curva cronologica del grafico
    recent_weighings = get_recent_weighings(shift_id=active_shift['shift_id'], limit=12)
    # Invierte la lista para orden cronologico ascendente en el grafico
    chronological_weighings = list(reversed(recent_weighings))
    # Prepara listas de etiquetas de tiempo y valores para Chart.js
    chart_labels = []
    # Lista de datos de velocidad para semilla
    seed_chart_data = []
    # Lista de datos de velocidad para expeller
    expeller_chart_data = []
    # Itera sobre las pesadas cronologicas
    for w in chronological_weighings:
        # Extrae hora y minutos de la estampa temporal
        time_part = w['timestamp'].split(' ')[-1][:5]
        # Agrega la etiqueta si no esta repetida
        if time_part not in chart_labels:
            # Registra la nueva etiqueta horaria
            chart_labels.append(time_part)
        # Asigna el valor segun el punto de medicion
        if w['sample_point'] == 'ingreso_semilla':
            # Guarda la medicion de semilla
            seed_chart_data.append({'time': time_part, 'speed': w['speed_kg_h']})
        else:
            # Guarda la medicion de expeller
            expeller_chart_data.append({'time': time_part, 'speed': w['speed_kg_h']})
    # Obtiene la ultima conciliacion de rendimiento registrada
    latest_yield = get_latest_reconciliation()
    # Obtiene el historial completo de conciliaciones de rendimiento y balance de masa
    yield_history = get_recent_reconciliations(limit=50)
    # Obtiene el historial global extendido de pesadas de velocidad
    all_recent_weighings = get_recent_weighings(limit=50)
    # Retorna el paquete consolidado para el dashboard
    return {
        # Existencias de tanques y silos
        'stocks': stocks,
        # Turno y guardia en curso
        'active_shift': active_shift,
        # Resumen agregado de velocidad
        'speed_summary': speed_summary,
        # Etiquetas temporales del grafico
        'chart_labels': chart_labels,
        # Curva de velocidad de semilla
        'seed_chart_data': seed_chart_data,
        # Curva de velocidad de expeller
        'expeller_chart_data': expeller_chart_data,
        # Ultimas pesadas para la vista compacta
        'recent_weighings': recent_weighings[:8],
        # Ultima conciliacion de turno
        'latest_yield': latest_yield,
        # Historial de balances de masa y rendimiento
        'yield_history': yield_history,
        # Historial de pesadas y velocidades para modal de evolucion horaria
        'all_recent_weighings': all_recent_weighings
    }
