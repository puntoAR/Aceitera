# Rutas web del modulo de Balanza de Camiones e Importacion/Exportacion de Pesadas
import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash, send_file, Response, g
from core.security import roles_required
from modules.configuration.service import get_active_shift
from modules.weighbridge.service import (
    record_weighing, get_recent_weighings, get_weighing_summary_stats,
    import_weighings_from_file, export_weighings_to_excel,
    export_weighings_to_csv, delete_weighing
)
from core.error_logger import log_error
from core.timezone import get_plant_now_str
from core.utils import safe_float

# Define el Blueprint de balanza
weighbridge_bp = Blueprint('weighbridge', __name__, url_prefix='/weighbridge')

# Vista principal del modulo de balanza (exclusivo Gerencia y Administracion)
@weighbridge_bp.route('/', methods=['GET'])
@roles_required('gerencia', 'administrador', 'admin_sistema')
def index():
    # Parametros de filtrado
    product = request.args.get('product', 'todos')
    operation_type = request.args.get('operation_type', 'todos')
    search = request.args.get('search', '').strip()
    start_date = request.args.get('start_date', '')
    end_date = request.args.get('end_date', '')

    # Obtiene listado de pesadas
    weighings = get_recent_weighings(
        limit=200, product=product, operation_type=operation_type,
        search=search, start_date=start_date, end_date=end_date
    )

    # Metricas resumen de balanza
    stats = get_weighing_summary_stats(start_date=start_date, end_date=end_date)
    active_shift = get_active_shift()

    return render_template(
        'weighbridge.html',
        weighings=weighings,
        stats=stats,
        active_shift=active_shift,
        current_product=product,
        current_operation=operation_type,
        current_search=search,
        current_start_date=start_date,
        current_end_date=end_date
    )

# Endpoint para registrar una pesada manual
@weighbridge_bp.route('/add', methods=['POST'])
@roles_required('gerencia', 'administrador', 'admin_sistema')
def add_weighing():
    try:
        ticket_number = request.form.get('ticket_number')
        weigh_date = request.form.get('weigh_date') or get_plant_now_str()
        operation_type = request.form.get('operation_type', 'ingreso')
        product = request.form.get('product', 'semilla')
        truck_plate = request.form.get('truck_plate')
        trailer_plate = request.form.get('trailer_plate')
        transport_company = request.form.get('transport_company')
        driver_name = request.form.get('driver_name')
        driver_dni = request.form.get('driver_dni')
        gross_weight = safe_float(request.form.get('gross_weight_kg'), 0.0)
        tare_weight = safe_float(request.form.get('tare_weight_kg'), 0.0)
        net_weight = safe_float(request.form.get('net_weight_kg'), default=None)
        origin = request.form.get('origin')
        destination = request.form.get('destination')
        seals_numbers = request.form.get('seals_numbers')
        notes = request.form.get('notes')
        sync_inv = bool(request.form.get('sync_inventory'))
        operator_name = g.user.get('full_name') if g.user else 'Balanza'
        shift_id = request.form.get('shift_id', 'TC')

        w_id = record_weighing(
            ticket_number=ticket_number,
            weigh_date=weigh_date,
            operation_type=operation_type,
            product=product,
            truck_plate=truck_plate,
            trailer_plate=trailer_plate,
            transport_company=transport_company,
            driver_name=driver_name,
            driver_dni=driver_dni,
            gross_weight_kg=gross_weight,
            tare_weight_kg=tare_weight,
            net_weight_kg=net_weight,
            origin=origin,
            destination=destination,
            seals_numbers=seals_numbers,
            notes=notes,
            operator_name=operator_name,
            shift_id=shift_id,
            sync_inventory=sync_inv
        )
        flash(f'Pesada de balanza registrada con éxito (Ticket #{ticket_number or w_id}).', 'success')
    except Exception as e:
        log_error('WEIGHBRIDGE_ROUTE', 'Error al registrar pesada manual', e)
        flash(f'Error al registrar pesada: {str(e)}', 'danger')

    return redirect(url_for('weighbridge.index'))

# Endpoint para importar archivo Excel (.xlsx / .xls) o CSV
@weighbridge_bp.route('/import', methods=['POST'])
@roles_required('gerencia', 'administrador', 'admin_sistema')
def import_excel():
    try:
        if 'excel_file' not in request.files:
            flash('No se seleccionó ningún archivo para importar.', 'warning')
            return redirect(url_for('weighbridge.index'))

        file = request.files['excel_file']
        if file.filename == '':
            flash('Nombre de archivo vacío.', 'warning')
            return redirect(url_for('weighbridge.index'))

        operator_name = g.user.get('full_name') if g.user else 'Importador Balanza'
        shift_id = request.form.get('shift_id', 'TC')
        sync_inv = bool(request.form.get('sync_inventory'))

        result = import_weighings_from_file(
            file, operator_name=operator_name, shift_id=shift_id, sync_inventory=sync_inv
        )

        msg = f"Importación completada: {result['imported_count']} pesadas registradas correctamente."
        if result['skipped_count'] > 0:
            msg += f" ({result['skipped_count']} filas omitidas o vacías)."
        flash(msg, 'success')

        if result['errors']:
            flash(f"Observaciones: {'; '.join(result['errors'][:3])}", 'info')

    except Exception as e:
        log_error('WEIGHBRIDGE_ROUTE', 'Error al importar archivo de balanza', e)
        flash(f'Error al procesar el archivo Excel: {str(e)}', 'danger')

    return redirect(url_for('weighbridge.index'))

# Endpoint para exportar listado filtrado a Excel (.xlsx)
@weighbridge_bp.route('/export/excel', methods=['GET'])
@roles_required('gerencia', 'administrador', 'admin_sistema')
def export_excel():
    try:
        product = request.args.get('product', 'todos')
        operation_type = request.args.get('operation_type', 'todos')
        search = request.args.get('search', '').strip()
        start_date = request.args.get('start_date', '')
        end_date = request.args.get('end_date', '')

        weighings = get_recent_weighings(
            limit=5000, product=product, operation_type=operation_type,
            search=search, start_date=start_date, end_date=end_date
        )

        excel_stream = export_weighings_to_excel(weighings, as_stream=True)
        date_str = datetime.datetime.now().strftime('%Y%m%d_%H%M')
        filename = f"BioBalcarce_Balanza_{date_str}.xlsx"

        return send_file(
            excel_stream,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            as_attachment=True,
            download_name=filename
        )
    except Exception as e:
        log_error('WEIGHBRIDGE_ROUTE', 'Error al exportar pesadas a Excel', e)
        flash(f'Error al generar archivo Excel: {str(e)}', 'danger')
        return redirect(url_for('weighbridge.index'))

# Endpoint para exportar listado filtrado a CSV
@weighbridge_bp.route('/export/csv', methods=['GET'])
@roles_required('gerencia', 'administrador', 'admin_sistema')
def export_csv():
    try:
        product = request.args.get('product', 'todos')
        operation_type = request.args.get('operation_type', 'todos')
        search = request.args.get('search', '').strip()
        start_date = request.args.get('start_date', '')
        end_date = request.args.get('end_date', '')

        weighings = get_recent_weighings(
            limit=5000, product=product, operation_type=operation_type,
            search=search, start_date=start_date, end_date=end_date
        )

        csv_content = export_weighings_to_csv(weighings)
        date_str = datetime.datetime.now().strftime('%Y%m%d_%H%M')
        filename = f"BioBalcarce_Balanza_{date_str}.csv"

        return Response(
            csv_content,
            mimetype="text/csv",
            headers={"Content-disposition": f"attachment; filename={filename}"}
        )
    except Exception as e:
        log_error('WEIGHBRIDGE_ROUTE', 'Error al exportar pesadas a CSV', e)
        flash(f'Error al generar archivo CSV: {str(e)}', 'danger')
        return redirect(url_for('weighbridge.index'))

# Endpoint para eliminar una pesada (solo admin_sistema)
@weighbridge_bp.route('/delete/<int:weighing_id>', methods=['POST'])
@roles_required('admin_sistema')
def delete_item(weighing_id):
    try:
        admin_user = g.user.get('username') if g.user else 'admin'
        delete_weighing(weighing_id, admin_user)
        flash(f'Pesada #{weighing_id} eliminada correctamente.', 'info')
    except Exception as e:
        log_error('WEIGHBRIDGE_ROUTE', f'Error al eliminar pesada #{weighing_id}', e)
        flash(f'Error al eliminar registro: {str(e)}', 'danger')
    return redirect(url_for('weighbridge.index'))
