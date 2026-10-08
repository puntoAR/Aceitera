# Herramienta autonoma ejecutable de diagnostico de sistema, base de datos y excepciones
# Este script se ejecuta de forma independiente: python diagnostics/system_diagnostics.py

# Importa sys para manipular el codigo de salida del proceso y sys.path
import sys
# Importa os para interactuar con archivos, rutas y permisos del sistema operativo
import os
# Importa sqlite3 para auditoria de bajo nivel de la base de datos
import sqlite3
# Importa socket para verificar la disponibilidad del puerto de red
import socket
# Importa datetime para marcas de tiempo en el reporte
import datetime

# Agrega el directorio raiz del proyecto al path de modulos
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(CURRENT_DIR, '..'))
sys.path.insert(0, PROJECT_ROOT)

# Importa variables de configuracion del sistema
from config import DATABASE_PATH, LOG_FILE_PATH, PORT, HOST
# Importa la lectura de logs recientes
from core.error_logger import get_recent_logs

# Define codigos de color ANSI compatibles con terminales Windows modernas y Linux
COLOR_RESET = "\033[0m"
COLOR_GREEN = "\033[92m"
COLOR_YELLOW = "\033[93m"
COLOR_RED = "\033[91m"
COLOR_CYAN = "\033[96m"
COLOR_BOLD = "\033[1m"

# Imprime encabezado visual para el reporte de diagnostico
def print_header(title):
    # Imprime linea separadora decorativa
    print(f"\n{COLOR_CYAN}{COLOR_BOLD}{'='*70}{COLOR_RESET}")
    # Imprime el titulo de la seccion
    print(f"{COLOR_CYAN}{COLOR_BOLD}  {title}{COLOR_RESET}")
    # Imprime linea separadora inferior
    print(f"{COLOR_CYAN}{COLOR_BOLD}{'='*70}{COLOR_RESET}")

# Imprime un item de verificacion con su estado (OK, ADVERTENCIA, ERROR)
def print_status(check_name, status, details=""):
    # Si el estado es exitoso (OK)
    if status == "OK":
        # Formatea en verde
        badge = f"{COLOR_GREEN}[  OK  ]{COLOR_RESET}"
    elif status == "WARN":
        # Formatea en amarillo
        badge = f"{COLOR_YELLOW}[ ADVERTENCIA ]{COLOR_RESET}"
    else:
        # Formatea en rojo
        badge = f"{COLOR_RED}[ ERROR CRITICO ]{COLOR_RESET}"
    # Imprime la linea de resultado formateada
    print(f" {badge} {check_name}")
    # Si hay detalles adicionales
    if details:
        # Imprime los detalles con sangria
        print(f"        -> {details}")

# Diagnostico 1: Verifica la existencia y permisos de escritura en el sistema de archivos
def check_filesystem():
    # Inicializa estado en OK
    has_error = False
    # Verifica el directorio de base de datos
    db_dir = os.path.dirname(DATABASE_PATH)
    # Comprueba si el directorio existe
    if os.path.exists(db_dir):
        # Comprueba permisos de escritura creando y eliminando un archivo temporal
        try:
            test_file = os.path.join(db_dir, '.write_test')
            with open(test_file, 'w') as f:
                f.write('test')
            os.remove(test_file)
            print_status("Directorio de datos y base de datos accesible con escritura", "OK")
        except Exception as e:
            print_status("Directorio de datos sin permisos de escritura", "ERROR", str(e))
            has_error = True
    else:
        print_status("Directorio de datos no encontrado", "ERROR", f"Ruta esperada: {db_dir}")
        has_error = True

    # Verifica archivo de logs
    log_dir = os.path.dirname(LOG_FILE_PATH)
    if os.path.exists(log_dir):
        print_status("Directorio de logs de auditoria disponible", "OK")
    else:
        print_status("Directorio de logs no encontrado", "WARN", "Sera creado automaticamente al iniciar")
    # Retorna True si todo esta correcto
    return not has_error

# Diagnostico 2: Auditoria de integridad de SQLite y esquemas de tablas
def check_database_integrity():
    # Verifica si el archivo de base de datos existe
    if not os.path.exists(DATABASE_PATH):
        print_status("Archivo de base de datos SQLite", "ERROR", f"No se encontro el archivo de base de datos en {DATABASE_PATH}")
        return False

    # Conecta directamente a SQLite para correr comandos de integridad PRAGMA
    try:
        conn = sqlite3.connect(DATABASE_PATH)
        conn.row_factory = sqlite3.Row
        # Ejecuta la comprobacion exhaustiva de integridad fisica de SQLite
        integrity = conn.execute("PRAGMA integrity_check;").fetchall()
        # Si la respuesta es ok
        if len(integrity) == 1 and integrity[0][0] == "ok":
            print_status("Integridad fisica de bloques SQLite (PRAGMA integrity_check)", "OK")
        else:
            print_status("Corrupcion detectada en base de datos SQLite", "ERROR", str(integrity))
            conn.close()
            return False

        # Verifica integridad de claves foraneas
        fk_errors = conn.execute("PRAGMA foreign_key_check;").fetchall()
        if not fk_errors:
            print_status("Integridad de claves foraneas (PRAGMA foreign_key_check)", "OK")
        else:
            print_status("Inconsistencias de clave foranea", "WARN", f"{len(fk_errors)} registros huerfanos detectados")

        # Lista de tablas requeridas por los modulos del sistema
        required_tables = [
            'system_config', 'shifts', 'users', 'active_shift',
            'equipment_tanks', 'equipment_silos', 'production_weighings',
            'line_stops', 'inventory_tanks', 'inventory_silos',
            'inventory_movements', 'lab_analyses', 'shift_reconciliations'
        ]
        # Consulta las tablas existentes en sqlite_master
        existing_tables_rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table';").fetchall()
        existing_tables = [row['name'] for row in existing_tables_rows]
        # Verifica si falta alguna tabla esencial
        missing_tables = [t for t in required_tables if t not in existing_tables]
        if not missing_tables:
            print_status(f"Esquema relacional ({len(required_tables)} tablas maestras verificadas)", "OK")
        else:
            print_status("Tablas faltantes en la base de datos", "ERROR", f"Faltan: {', '.join(missing_tables)}")
            conn.close()
            return False

        # Cierra la conexion
        conn.close()
        return True
    except Exception as e:
        print_status("Fallo critico al conectar con base de datos", "ERROR", str(e))
        return False

# Diagnostico 3: Validacion fisica y matematica de parametros de equipos
def check_equipment_and_math_sanity():
    # Abre conexion
    try:
        conn = sqlite3.connect(DATABASE_PATH)
        conn.row_factory = sqlite3.Row
        # 1. Tanques de aceite
        tanks = conn.execute("SELECT * FROM equipment_tanks;").fetchall()
        tank_issues = []
        for t in tanks:
            if t['diameter_m'] <= 0:
                tank_issues.append(f"Tanque {t['code']}: Diametro no positivo ({t['diameter_m']} m)")
            if t['height_m'] <= 0 and t['geometry_type'] == 'vertical_cylinder':
                tank_issues.append(f"Tanque {t['code']}: Altura no positiva ({t['height_m']} m)")
            if t['default_density'] <= 0 or t['default_density'] > 1.5:
                tank_issues.append(f"Tanque {t['code']}: Densidad atipica ({t['default_density']} kg/L)")
        if not tank_issues:
            print_status(f"Parametros fisicos de tanques ({len(tanks)} tanques calibrados)", "OK")
        else:
            print_status("Anomalias en calibracion de tanques", "ERROR", "; ".join(tank_issues))

        # 2. Silos
        silos = conn.execute("SELECT * FROM equipment_silos;").fetchall()
        silo_issues = []
        for s in silos:
            if s['diameter_m'] <= 0:
                silo_issues.append(f"Silo {s['code']}: Diametro no positivo ({s['diameter_m']} m)")
            if s['sheet_height_m'] <= 0:
                silo_issues.append(f"Silo {s['code']}: Altura de chapa invalida ({s['sheet_height_m']} m)")
            if s['default_ph'] <= 0 or s['default_ph'] > 100:
                silo_issues.append(f"Silo {s['code']}: Peso hectolitrico atipico ({s['default_ph']} kg/hl)")
        if not silo_issues:
            print_status(f"Parametros fisicos de silos ({len(silos)} silos calibrados)", "OK")
        else:
            print_status("Anomalias en configuracion de silos", "ERROR", "; ".join(silo_issues))

        # 3. Comprobacion de registros anomalos en pesadas
        bad_weighings = conn.execute("""
            SELECT COUNT(*) FROM production_weighings
            WHERE fill_time_seconds <= 0 OR net_weight_kg < 0;
        """).fetchone()[0]
        if bad_weighings == 0:
            print_status("Integridad de pesadas de produccion (sin division por cero)", "OK")
        else:
            print_status("Pesadas con valores imposibles detectadas", "WARN", f"{bad_weighings} registros con tiempo <= 0 o peso < 0")

        conn.close()
        return True
    except Exception as e:
        print_status("Error al auditar consistencia matematica", "ERROR", str(e))
        return False

# Diagnostico 4: Verificacion de red y puerto de escucha
def check_network_port():
    # Intenta abrir un socket en el puerto configurado
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    # Permite reutilizar direccion
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        # Intenta enlazar al puerto de la aplicacion
        s.bind((HOST, PORT))
        # Si se pudo enlazar, el puerto esta libre para iniciar el servidor
        s.close()
        print_status(f"Puerto de red {PORT} disponible para iniciar servidor web", "OK")
        return True
    except socket.error as e:
        # Si no se pudo enlazar, probablemente otra instancia ya esta corriendo
        print_status(f"Puerto {PORT} ocupado o no disponible", "WARN", f"Puede que el servidor ya este en ejecucion o este bloqueado ({e})")
        return True

# Diagnostico 5: Analizador de errores y trazas recientes del log
def analyze_error_logs():
    # Lee las lineas recientes del log
    lines = get_recent_logs(max_lines=60)
    # Filtra lineas con nivel ERROR o CRITICAL
    error_lines = [l for l in lines if '[ERROR]' in l or '[CRITICAL]' in l]
    # Si no hay errores recientes
    if not error_lines:
        print_status("Registro de errores recientes de la aplicacion", "OK", "0 errores criticos registrados en el log")
        return True
    else:
        # Muestra la advertencia y resume el ultimo error encontrado
        print_status(f"Se encontraron {len(error_lines)} eventos de error en el log", "WARN")
        print(f"\n{COLOR_YELLOW}{COLOR_BOLD}  --- ULTIMO ERROR REGISTRADO EN EL SISTEMA ---{COLOR_RESET}")
        # Muestra las ultimas 10 lineas para observar la traza
        last_chunk = "".join(lines[-15:])
        print(f"{COLOR_YELLOW}{last_chunk}{COLOR_RESET}")
        # Ofrece una recomendacion segun palabras clave detectadas en el error
        print(f"{COLOR_CYAN}{COLOR_BOLD}  RECOMENDACION DE REPARACION INDUSTRIAL:{COLOR_RESET}")
        if "OperationalError: no such table" in last_chunk:
            print("  -> Causa probable: Tablas no creadas. Solucion: Ejecute 'python run.py' para inicializar la base de datos.")
        elif "Permission denied" in last_chunk:
            print("  -> Causa probable: Permisos de archivo bloqueados en disco. Solucion: Verifique que no haya otro programa abriendo el archivo de base de datos.")
        elif "ZeroDivisionError" in last_chunk:
            print("  -> Causa probable: Muestra ingresada con tiempo de llenado igual a cero. Solucion: Asegure tiempos positivos en la pesada.")
        elif "Address already in use" in last_chunk:
            print(f"  -> Causa probable: El puerto {PORT} ya esta en uso. Solucion: Cierre el proceso previo o cambie el puerto en config.py.")
        else:
            print("  -> Revise la traza del error anterior para ubicar el archivo y linea exactos del fallo.")
        return True

# Punto de entrada principal del diagnosticador
def main():
    # Limpia la pantalla o imprime salto
    print(f"\n{COLOR_BOLD}======================================================================{COLOR_RESET}")
    print(f"{COLOR_BOLD}   ACEITERA - HERRAMIENTA INDEPENDIENTE DE DIAGNOSTICO DE PLANTA   {COLOR_RESET}")
    print(f"{COLOR_BOLD}   Fecha y Hora de Auditoria: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}   {COLOR_RESET}")
    print(f"{COLOR_BOLD}======================================================================{COLOR_RESET}")

    # Ejecuta cada bateria de diagnostico
    print_header("1. AUDITORIA DEL SISTEMA DE ARCHIVOS")
    fs_ok = check_filesystem()

    print_header("2. AUDITORIA DE INTEGRIDAD DE BASE DE DATOS SQLITE")
    db_ok = check_database_integrity()

    print_header("3. AUDITORIA DE LIMITES FISICOS Y CALIBRACION DE EQUIPOS")
    math_ok = check_equipment_and_math_sanity()

    print_header("4. AUDITORIA DE CONECTIVIDAD DE RED Y PUERTOS")
    net_ok = check_network_port()

    print_header("5. ANALISIS DE REGISTRO DE EXCEPCIONES Y LOGS")
    log_ok = analyze_error_logs()

    # Evaluacion global del sistema
    print_header("RESUMEN GENERAL DEL DIAGNOSTICO")
    if fs_ok and db_ok and math_ok:
        print(f"\n{COLOR_GREEN}{COLOR_BOLD} [ESTADO SALUDABLE] Todos los sistemas criticos operan correctamente.{COLOR_RESET}")
        print(" La aplicacion esta lista para operar con total normalidad.\n")
        sys.exit(0)
    else:
        print(f"\n{COLOR_RED}{COLOR_BOLD} [ATENCION REQUERIDA] Se detectaron anomalias en uno o mas subsistemas.{COLOR_RESET}")
        print(" Por favor resuelva los errores detallados arriba antes de reiniciar el servicio web.\n")
        sys.exit(1)

# Ejecuta la funcion main si el script es invocado directamente desde terminal
if __name__ == '__main__':
    main()
