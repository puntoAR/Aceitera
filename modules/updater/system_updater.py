# Script autonomo ejecutable por terminal para actualizar el sistema sin navegador
# Uso: python modules/updater/system_updater.py <ruta_a_paquete_zip_o_carpeta>

# Importa sys y os
import sys
import os

# Agrega la raiz del proyecto al path
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(CURRENT_DIR, '..', '..'))
sys.path.insert(0, PROJECT_ROOT)

# Importa el servicio de actualizacion
from modules.updater.service import apply_update_package, get_current_version_info

# Punto de entrada por terminal
def main():
    print("======================================================================")
    print("      ACTUALIZADOR EN CALIENTE DE BIOBALCARCE (IN-PLACE UPDATER)      ")
    print("======================================================================")

    current = get_current_version_info()
    print(f" Version actual instalada: v{current.get('version', '1.0.0')}")

    # Verifica si se paso la ruta del paquete como argumento
    if len(sys.argv) < 2:
        print("\nUso incorrecto. Debe indicar la ruta del archivo .zip o carpeta con la actualizacion.")
        print("Ejemplo: python modules/updater/system_updater.py C:\\parches\\actualizacion_v1_1.zip\n")
        sys.exit(1)

    package_path = sys.argv[1]
    print(f"\nProcesando paquete de actualizacion desde: {package_path}")

    try:
        # Aplica la actualizacion con respaldo y diagnostico automatico
        res = apply_update_package(package_path)
        print("\n======================================================================")
        print(f" [ACTUALIZACION EXITOSA] Sistema actualizado a version v{res['version']}.")
        print(f" Respaldo de seguridad creado en: {res['backup_created']}")
        print(f" Migraciones de base de datos ejecutadas: {res['migrations_applied']}")
        print(" Todos los datos historicos y configuraciones han sido preservados.")
        print("======================================================================\n")
        sys.exit(0)
    except Exception as e:
        print("\n======================================================================")
        print(" [FALLO EN LA ACTUALIZACION] Ocurrio un error al aplicar el paquete.")
        print(f" Detalle: {e}")
        print(" El sistema ejecuto un Rollback preventivo y se encuentra en su estado original.")
        print("======================================================================\n")
        sys.exit(1)

if __name__ == '__main__':
    main()
