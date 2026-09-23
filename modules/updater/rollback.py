# Script autonomo ejecutable por terminal para restaurar un respaldo (Rollback)
# Importa sys y os para manejar argumentos y rutas
import sys
# Importa os para verificar rutas del sistema
import os

# Agrega la raiz del proyecto al path de busqueda de modulos
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
# Resuelve la ruta raiz del proyecto dos niveles arriba
PROJECT_ROOT = os.path.abspath(os.path.join(CURRENT_DIR, '..', '..'))
# Inserta la raiz en la primera posicion de sys.path
sys.path.insert(0, PROJECT_ROOT)

# Importa las funciones de listado y restauracion de copias de seguridad
from core.backup_manager import list_backups, restore_backup

# Funcion principal del menu de rollback
def main():
    # Imprime encabezado visual
    print("======================================================================")
    print("        RESTAURACION DE RESPALDO ANTERIOR (ROLLBACK MANUAL)          ")
    print("======================================================================")
    
    # Obtiene la lista de respaldos disponibles ordenados del mas reciente al mas antiguo
    backups = list_backups()
    # Si no existen respaldos
    if not backups:
        # Informa al operador
        print("\nNo se encontraron copias de seguridad en la carpeta backups.")
        # Finaliza con codigo 1
        sys.exit(1)
        
    # Muestra los respaldos encontrados
    print("\nCopias de seguridad disponibles:")
    # Itera hasta 5 copias recientes
    for i, b in enumerate(backups[:5]):
        # Imprime cada opcion con su version y estampa de fecha
        print(f" [{i+1}] {b['folder_name']} (v{b['version']}) - Creado: {b['created_at']}")
        
    # Solicita la eleccion al usuario
    try:
        # Pide el numero de indice
        choice = input("\nIngrese el numero de la copia que desea restaurar [1]: ").strip()
    except (EOFError, KeyboardInterrupt):
        # Maneja cancelacion por teclado
        print("\nOperacion cancelada por el usuario.")
        # Sale con codigo 0
        sys.exit(0)
        
    # Determina el indice elegido por el operador
    idx = int(choice) - 1 if choice.isdigit() and int(choice) > 0 else 0
    # Verifica que el indice este dentro del rango de respaldos
    if 0 <= idx < len(backups):
        # Obtiene la ruta del respaldo seleccionado
        target = backups[idx]['path']
        # Muestra mensaje informativo
        print(f"\nRestaurando copia: {backups[idx]['folder_name']}...")
        # Ejecuta la restauracion fisica
        restore_backup(target)
        # Informa el exito
        print("\n======================================================================")
        print(" [RESTAURACION EXITOSA] El sistema ha vuelto al estado anterior.")
        print("======================================================================\n")
    else:
        # Informa opcion no valida
        print("\nOpcion invalida seleccionada.")
        # Sale con codigo 1
        sys.exit(1)

# Punto de entrada si se ejecuta directamente
if __name__ == '__main__':
    # Invoca la funcion principal
    main()
