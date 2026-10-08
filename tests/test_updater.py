# Suite de pruebas automatizadas del motor de actualizacion in-place y respaldos
# Importa unittest para organizar y ejecutar pruebas
import unittest
# Importa sys y os para configurar rutas
import sys, os
import shutil
import zipfile
import json
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Importa componentes del actualizador y respaldos
from core.database import init_db, get_db_connection
from core.backup_manager import create_backup, list_backups, restore_backup, BACKUPS_DIR
from core.migrations import apply_pending_migrations, get_applied_migration_versions
from modules.updater.service import apply_update_package, get_current_version_info
from config import BASE_DIR, DATABASE_PATH

# Clase de prueba para el sistema de actualizacion sin reinstalar
class TestInPlaceUpdater(unittest.TestCase):
    # Configuracion previa a cada prueba
    def setUp(self):
        init_db()
        self.test_staging = os.path.join(BASE_DIR, 'test_staging_pkg')
        if os.path.exists(self.test_staging):
            shutil.rmtree(self.test_staging)
        os.makedirs(self.test_staging, exist_ok=True)

    # Limpieza posterior
    def tearDown(self):
        if os.path.exists(self.test_staging):
            shutil.rmtree(self.test_staging)

    # Prueba 1: Creacion y listado de copias de seguridad (Backups)
    def test_backup_and_restore(self):
        # Inserta un dato de prueba en la base de datos
        with get_db_connection() as conn:
            conn.execute("INSERT OR REPLACE INTO system_config (key, value) VALUES ('test_key', 'val_1');")
            conn.commit()

        # Crea un respaldo
        backup_path = create_backup(label="unit_test")
        self.assertTrue(os.path.exists(backup_path))
        self.assertTrue(os.path.exists(os.path.join(backup_path, os.path.basename(DATABASE_PATH))))

        # Lista respaldos y comprueba que figure
        backups = list_backups()
        self.assertGreater(len(backups), 0)
        # Extrae las etiquetas de los respaldos disponibles
        labels = [b['label'] for b in backups]
        # Comprueba que la etiqueta de la prueba figure en los respaldos
        self.assertIn('unit_test', labels)

        # Modifica el dato en la base activa
        with get_db_connection() as conn:
            conn.execute("UPDATE system_config SET value = 'val_modificado' WHERE key = 'test_key';")
            conn.commit()

        # Ejecuta rollback / restauracion desde el respaldo
        restore_backup(backup_path)

        # Comprueba que el valor original haya sido restaurado
        with get_db_connection() as conn:
            val = conn.execute("SELECT value FROM system_config WHERE key = 'test_key';").fetchone()['value']
            self.assertEqual(val, 'val_1')

        # Limpia el respaldo de prueba para no acumular archivos temporales
        if os.path.exists(backup_path):
            # Remueve la carpeta de respaldo generada por el test
            shutil.rmtree(backup_path, ignore_errors=True)

    # Prueba 2: Migraciones incrementales sin perdida de datos
    def test_migrations_incremental(self):
        # Ejecuta migraciones
        applied_count = apply_pending_migrations()
        # Consulta versiones aplicadas
        applied_versions = get_applied_migration_versions()
        self.assertIn(1, applied_versions)
        self.assertIn(2, applied_versions)

    # Prueba 3: Aplicacion exitosa de un paquete ZIP de actualizacion
    def test_successful_zip_update(self):
        # Prepara un paquete ZIP simulando una version v1.0.5
        pkg_dir = os.path.join(self.test_staging, 'pkg_content')
        os.makedirs(pkg_dir, exist_ok=True)
        # Manifiesto con nueva version
        with open(os.path.join(pkg_dir, 'version.json'), 'w', encoding='utf-8') as f:
            json.dump({
                'version': '1.0.5',
                'release_date': '2026-09-22',
                'app_name': 'Aceitera Control Industrial',
                'changelog': ['v1.0.5 - Parche de optimizacion']
            }, f)

        # Empaqueta en ZIP
        zip_path = os.path.join(self.test_staging, 'patch_v1_0_5.zip')
        with zipfile.ZipFile(zip_path, 'w') as z:
            z.write(os.path.join(pkg_dir, 'version.json'), 'version.json')

        # Guarda el contenido original de version.json para restaurarlo
        version_file = os.path.join(BASE_DIR, 'version.json')
        original_version_content = None
        if os.path.exists(version_file):
            with open(version_file, 'r', encoding='utf-8') as f:
                original_version_content = f.read()

        try:
            # Aplica la actualizacion
            result = apply_update_package(zip_path)
            self.assertTrue(result['success'])
            self.assertEqual(result['version'], '1.0.5')

            # Verifica que version.json en el proyecto ahora sea 1.0.5
            curr_ver = get_current_version_info()
            self.assertEqual(curr_ver['version'], '1.0.5')
        finally:
            # Restaura el contenido original de version.json
            if original_version_content is not None:
                with open(version_file, 'w', encoding='utf-8') as f:
                    f.write(original_version_content)

# Ejecucion de pruebas
if __name__ == '__main__':
    unittest.main()
