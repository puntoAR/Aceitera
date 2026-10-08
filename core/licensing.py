# Motor central de gestion de licenciamiento y control de politicas de uso (puntoAR)
# Provee control de periodos de prueba (trial), suscripciones, bloqueos y restricciones modulares
import os
import hashlib
from datetime import datetime, date
# Importa conexion a base de datos relacional
from core.database import get_db_connection
# Importa logger del sistema
from core.error_logger import log_error, log_info

# Genera una clave o firma de activacion criptografica para el cliente
def generate_license_token(client_name, expiration_date, mode):
    """
    Genera un token de activacion con formato profesional PUNTOAR-XXXX-XXXX-XXXX
    """
    raw = f"PUNTOAR_ACEITERA_{client_name.strip()}_{expiration_date.strip()}_{mode.strip()}_SECRET_2026"
    digest = hashlib.sha256(raw.encode('utf-8')).hexdigest().upper()
    return f"PTAR-{digest[:4]}-{digest[4:8]}-{digest[8:12]}"

# Obtiene el estado actual de licenciamiento y calcula vencimiento y restricciones
def get_licensing_status():
    """
    Retorna un diccionario completo con la configuracion de licencia,
    dias restantes, estado de expiracion y restricciones efectivas.
    """
    default_status = {
        'client_name': 'Aceitera S.A.',
        'license_mode': 'libre_uso',
        'license_key': 'PTAR-ACTV-2026-OK',
        'start_date': '2026-09-01',
        'expiration_date': '2027-09-01',
        'is_active': 1,
        'max_users': 50,
        'block_dashboard': 0,
        'block_data_entry': 0,
        'block_reports': 0,
        'block_updates': 0,
        'status_notes': 'Licencia inicial de despliegue de planta',
        'is_expired': False,
        'days_remaining': None,
        'is_restricted': False,
        'status_label': 'Licencia Activa (Libre Uso)',
        'status_color': '#15803d',
        'restrictions': {
            'block_dashboard': False,
            'block_data_entry': False,
            'block_reports': False,
            'block_updates': False
        }
    }

    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT client_name, license_mode, license_key, start_date, expiration_date,
                       is_active, max_users, block_dashboard, block_data_entry,
                       block_reports, block_updates, status_notes, updated_at, updated_by
                FROM system_licensing_config
                WHERE id = 1
            """)
            row = cursor.fetchone()

        if not row:
            return default_status

        data = dict(row)
        mode = data.get('license_mode') or 'libre_uso'
        is_active = bool(data.get('is_active', 1))
        exp_str = data.get('expiration_date')

        is_expired = False
        days_remaining = None

        if exp_str:
            try:
                # Intenta parsear fecha de expiracion (YYYY-MM-DD)
                exp_date = datetime.strptime(exp_str[:10], '%Y-%m-%d').date()
                today = date.today()
                diff = (exp_date - today).days
                days_remaining = diff
                # Si el modo esta sujeto a expiracion
                if mode in ('trial', 'suscripcion') and diff < 0:
                    is_expired = True
            except Exception:
                pass

        # Determina si el sistema esta bajo restriccion
        is_restricted = False
        if not is_active:
            is_restricted = True
            status_label = 'Licencia Inactiva / Suspendida'
            status_color = '#b91c1c'
        elif mode == 'bloqueado':
            is_restricted = True
            status_label = 'Sistema Bloqueado por Administración'
            status_color = '#b91c1c'
        elif is_expired:
            is_restricted = True
            status_label = f'Período Expirado ({abs(days_remaining)} días vencido)'
            status_color = '#dc2626'
        elif mode == 'trial':
            status_label = f'Período de Prueba Activo ({days_remaining} días restantes)'
            status_color = '#2563eb' if (days_remaining and days_remaining > 30) else '#b45309'
        elif mode == 'suscripcion':
            status_label = f'Suscripción Comercial Vigente ({days_remaining} días restantes)'
            status_color = '#15803d'
        else:
            status_label = 'Licencia Plena (Libre Uso)'
            status_color = '#15803d'

        # Calcula las restricciones efectivas
        restrictions = {
            'block_dashboard': bool(is_restricted and data.get('block_dashboard', 0)),
            'block_data_entry': bool(is_restricted and data.get('block_data_entry', 0)),
            'block_reports': bool(is_restricted and data.get('block_reports', 0)),
            'block_updates': bool(is_restricted and data.get('block_updates', 0))
        }

        data.update({
            'is_expired': is_expired,
            'days_remaining': days_remaining,
            'is_restricted': is_restricted,
            'status_label': status_label,
            'status_color': status_color,
            'restrictions': restrictions
        })
        return data

    except Exception as e:
        log_error('LICENSING', 'Error al consultar estado de licenciamiento', e)
        return default_status

# Actualiza los parametros de la licencia en base de datos
def update_licensing_config(client_name, license_mode, expiration_date, start_date=None,
                            license_key=None, block_dashboard=0, block_data_entry=0,
                            block_reports=0, block_updates=0, max_users=50,
                            is_active=1, status_notes=None, updated_by='admin_sistema'):
    """
    Actualiza la fila unica (id=1) en system_licensing_config.
    """
    now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    # Si no se envio clave o es nula, autogenera una coherente
    if not license_key or not license_key.strip():
        license_key = generate_license_token(client_name, expiration_date, license_mode)

    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE system_licensing_config
            SET client_name = ?,
                license_mode = ?,
                license_key = ?,
                start_date = COALESCE(?, start_date),
                expiration_date = ?,
                is_active = ?,
                max_users = ?,
                block_dashboard = ?,
                block_data_entry = ?,
                block_reports = ?,
                block_updates = ?,
                status_notes = ?,
                updated_at = ?,
                updated_by = ?
            WHERE id = 1
        """, (
            client_name.strip(),
            license_mode.strip(),
            license_key.strip(),
            start_date,
            expiration_date.strip() if expiration_date else None,
            1 if is_active else 0,
            int(max_users or 50),
            1 if block_dashboard else 0,
            1 if block_data_entry else 0,
            1 if block_reports else 0,
            1 if block_updates else 0,
            status_notes,
            now_str,
            updated_by
        ))
        conn.commit()

    log_info('LICENSING', f'Configuración de licencia actualizada por {updated_by}: modo={license_mode}, expira={expiration_date}')
    return get_licensing_status()

# Evalua si una funcionalidad especifica esta habilitada
def check_feature_permission(feature_key):
    """
    Verifica si una funcionalidad ('dashboard', 'data_entry', 'reports', 'updates')
    esta permitida segun las politicas de licenciamiento vigentes.
    Retorna (permitido: bool, mensaje: str).
    """
    status = get_licensing_status()
    restriction_key = f"block_{feature_key}"
    if status['restrictions'].get(restriction_key, False):
        msg = (
            f"La función solicitada ({feature_key}) se encuentra temporalmente restringida "
            f"por políticas de licenciamiento ({status['status_label']}). "
            "Por favor contacte a soporte de puntoAR para renovar o regularizar su licencia."
        )
        return False, msg
    return True, "Permitido"
