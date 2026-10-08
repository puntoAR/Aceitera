# Importa unittest para ejecutar pruebas unitarias automatizadas
import unittest
# Importa math para comparaciones con tolerancia de punto flotante
import math
# Importa sys y os para incorporar la raiz del proyecto al path de modulos
import sys, os
# Inserta el directorio raiz del proyecto en sys.path para importar modulos locales
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Importa las funciones del motor de velocidad
from modules.calculations.speed_calc import (
    calculate_net_weight, calculate_instant_speed, project_shift_production,
    project_daily_production, calculate_arithmetic_average_speed, calculate_aggregated_speed
)
# Importa las funciones del motor de tanques
from modules.calculations.tank_calc import (
    calculate_vertical_tank_volume, calculate_horizontal_tank_volume,
    convert_volume_to_mass, calculate_net_oil_production
)
# Importa las funciones del motor de silos
from modules.calculations.silo_calc import (
    calculate_cylinder_volume, calculate_bottom_cone_volume, calculate_copete_volume,
    calculate_silo_total_volume, convert_silo_volume_to_seed_mass, calculate_bulk_density_from_container
)
# Importa las funciones del motor de laboratorio
from modules.calculations.lab_calc import (
    calculate_moisture_pct, calculate_fat_pct, calculate_foreign_matter_pct, calculate_oil_acidity_pct
)
# Importa las funciones del motor de rendimiento y balance
from modules.calculations.yield_calc import (
    calculate_mass_yield_pct, calculate_available_oil, calculate_oil_recovery_pct,
    calculate_residual_fat_in_expeller, calculate_classified_mass_balance,
    calculate_line_yield_and_oil_efficiency
)

# Clase de pruebas para el motor de calculo de velocidad
class TestSpeedCalculations(unittest.TestCase):
    # Prueba del ejemplo exacto de la especificacion: bolsa de 30 kg en 60 segundos
    def test_example_speed_specification(self):
        # Calcula la velocidad instantanea: 30 kg / 60 s * 3600 = 1800 kg/h
        speed = calculate_instant_speed(30.0, 60.0)
        # Verifica que la velocidad sea exactamente 1800.0 kg/h
        self.assertEqual(speed, 1800.0)
        # Verifica proyeccion de 8 horas: 1800 * 8 = 14400 kg
        self.assertEqual(project_shift_production(speed), 14400.0)
        # Verifica proyeccion de 24 horas: 1800 * 24 = 43200 kg
        self.assertEqual(project_daily_production(speed), 43200.0)

    # Prueba de validacion de tiempo de muestreo igual a cero
    def test_zero_time_raises_error(self):
        # Verifica que se lance un ValueError al pasar tiempo 0
        with self.assertRaises(ValueError):
            calculate_instant_speed(30.0, 0.0)

    # Prueba del promedio aritmetico y de la velocidad agregada
    def test_speed_averages(self):
        # Lista de velocidades de muestra en kg/h
        speeds = [1800.0, 1900.0, 2000.0]
        # Promedio aritmetico esperado: 1900.0
        self.assertEqual(calculate_arithmetic_average_speed(speeds), 1900.0)
        # Muestras con pesos y tiempos para velocidad agregada
        samples = [
            {'net_weight_kg': 30.0, 'fill_time_seconds': 60.0},
            {'net_weight_kg': 32.0, 'fill_time_seconds': 60.0}
        ]
        # Peso total 62 kg / 120 s * 3600 = 1860 kg/h
        self.assertEqual(calculate_aggregated_speed(samples), 1860.0)

    # Prueba de muestreo estandarizado en 30 segundos segun planilla de planta
    def test_standardized_30s_sampling(self):
        # Muestra de 15.0 kg en 30 segundos estandar
        # Caudal (kg/h) = (15.0 / 30) * 3600 = 1800.0 kg/h
        speed_30s = calculate_instant_speed(net_weight_kg=15.0, fill_time_seconds=30.0)
        self.assertEqual(speed_30s, 1800.0)

# Clase de pruebas para el motor geometrico de tanques
class TestTankCalculations(unittest.TestCase):
    # Prueba del ejemplo exacto del tanque vertical de chapa (D=2.00m, h=2.50m)
    def test_vertical_tank_specification_example(self):
        # Calcula volumen en m3 para D=2.00m (r=1.0m) y h=2.50m: pi * 1.0^2 * 2.50 = 7.854 m3
        vol_m3 = calculate_vertical_tank_volume(diameter_m=2.0, height_m=4.60, level_m=2.50)
        # Comprueba que el volumen sea aproximadamente 7.854 m3
        self.assertAlmostEqual(vol_m3, 7.854, places=2)
        # Convierte el volumen a masa con densidad 0.92 kg/L
        mass_data = convert_volume_to_mass(vol_m3, density_kg_l=0.92)
        # Comprueba litros aproximados: 7854 L
        self.assertAlmostEqual(mass_data['total_liters'], 7854.0, delta=1.0)
        # Comprueba masa aproximada: 7226 kg
        self.assertAlmostEqual(mass_data['total_mass_kg'], 7226.0, delta=1.0)

    # Prueba del tanque cilindrico horizontal en diferentes niveles
    def test_horizontal_tank_geometry(self):
        # Tanque 1 de Aceitera: D=2.50m, L=6.50m
        diam = 2.50
        length = 6.50
        # Nivel cero debe dar volumen cero
        self.assertEqual(calculate_horizontal_tank_volume(diam, length, 0.0), 0.0)
        # Nivel a medio tanque (h = r = 1.25m): debe ser la mitad del volumen cilindrico total
        vol_half = calculate_horizontal_tank_volume(diam, length, 1.25)
        expected_half = (math.pi * (1.25 ** 2) * 6.50) / 2.0
        self.assertAlmostEqual(vol_half, expected_half, places=3)
        # Nivel lleno (h = D = 2.50m)
        vol_full = calculate_horizontal_tank_volume(diam, length, 2.50)
        expected_full = math.pi * (1.25 ** 2) * 6.50
        self.assertAlmostEqual(vol_full, expected_full, places=3)

    # Prueba de validacion por nivel superior a la altura o diametro
    def test_tank_overflow_error(self):
        # Nivel mayor a la altura debe generar excepcion controlada
        with self.assertRaises(ValueError):
            calculate_vertical_tank_volume(diameter_m=2.0, height_m=4.60, level_m=5.0)

# Clase de pruebas para el motor de cubicaje de silos
class TestSiloCalculations(unittest.TestCase):
    # Prueba del ejemplo de la especificacion: Silo D=4m, 3 chapas de 0.99m (H=2.97m)
    def test_silo_cylinder_specification_example(self):
        # Volumen cilindrico para D=4m (r=2m) y 3 chapas de 0.99m
        v_cyl = calculate_cylinder_volume(diameter_m=4.0, sheet_height_m=0.99, covered_sheets=3)
        # Verifica que el volumen sea aproximadamente 37.32 m3
        self.assertAlmostEqual(v_cyl, 37.32, places=1)
        # Con peso hectolitrico 44 kg/hl (440 kg/m3)
        mass_data = convert_silo_volume_to_seed_mass(v_cyl, hectolitric_weight_kg_hl=44.0)
        # Masa aproximada en kg: 37.32 * 440 = 16420.8 kg
        self.assertAlmostEqual(mass_data['total_mass_kg'], 16420.8, delta=10.0)

    # Prueba de conversion de peso hectolitrico a densidad aparente (PH * 10)
    def test_ph_to_density_conversion(self):
        # 44 kg/hl debe convertirse a 440 kg/m3
        data = convert_silo_volume_to_seed_mass(volume_m3=100.0, hectolitric_weight_kg_hl=44.0)
        self.assertEqual(data['bulk_density_kg_m3'], 440.0)
        # 100 m3 * 440 kg/m3 = 44000 kg
        self.assertEqual(data['total_mass_kg'], 44000.0)

# Clase de pruebas para el motor de laboratorio
class TestLaboratoryCalculations(unittest.TestCase):
    # Prueba de determinacion de humedad
    def test_moisture_calculation(self):
        # Muestra inicial 10.0g, seca 9.2g -> 8.0% humedad
        moist = calculate_moisture_pct(10.0, 9.2)
        self.assertEqual(moist, 8.0)

    # Prueba de determinacion de materia grasa
    def test_fat_calculation(self):
        # Muestra 2.0g, tara matraz 120.0g, final 120.9g -> extracto 0.9g -> 45.0%
        fat = calculate_fat_pct(sample_mass_g=2.0, final_flask_mass_g=120.9, tare_flask_mass_g=120.0)
        self.assertEqual(fat, 45.0)

    # Prueba de determinacion de acidez en aceite
    def test_acidity_calculation(self):
        # Muestra 10.0g, NaOH 3.0ml, N=0.0997, Ft=0.282
        # (3.0 * 0.0997 * 0.282 * 100) / 10.0 = 0.843%
        acidity = calculate_oil_acidity_pct(10.0, 3.0, 0.0997, 0.282)
        self.assertEqual(acidity, 0.84)

# Clase de pruebas para rendimiento industrial y balance de masa
class TestYieldAndBalanceCalculations(unittest.TestCase):
    # Prueba del ejemplo exacto de la seccion 7.4 de la especificacion
    def test_yield_and_recovery_specification_example(self):
        # Semilla procesada: 20000 kg al 45% de materia grasa
        seed_kg = 20000.0
        seed_fat = 45.0
        oil_obtained = 8000.0
        # Aceite disponible teorico: 9000 kg
        avail_oil = calculate_available_oil(seed_kg, seed_fat)
        self.assertEqual(avail_oil, 9000.0)
        # Rendimiento masico de aceite: 8000 / 20000 * 100 = 40.0%
        oil_yield = calculate_mass_yield_pct(oil_obtained, seed_kg)
        self.assertEqual(oil_yield, 40.0)
        # Recuperacion del aceite disponible: 8000 / 9000 * 100 = 88.89%
        oil_recov = calculate_oil_recovery_pct(oil_obtained, seed_kg, seed_fat)
        self.assertEqual(oil_recov, 88.89)

    # Prueba de grasa residual en expeller segun ejemplo de seccion 7.5
    def test_residual_fat_expeller_specification_example(self):
        # 11200 kg de expeller con 10% de materia grasa -> 1120 kg de grasa residual
        res_fat = calculate_residual_fat_in_expeller(11200.0, 10.0)
        self.assertEqual(res_fat, 1120.0)

    # Prueba de balance de masa clasificado
    def test_classified_mass_balance(self):
        # Balance con 20000 kg semilla, 8000 kg aceite, 11200 kg expeller, 400 kg agua, 200 kg cascarilla
        # Total salidas: 8000 + 11200 + 400 + 200 = 19800 kg. Diferencia: 200 kg
        balance = calculate_classified_mass_balance(
            seed_processed_kg=20000.0,
            oil_obtained_kg=8000.0,
            expeller_obtained_kg=11200.0,
            moisture_removed_kg=400.0,
            solid_waste_kg=200.0
        )
        self.assertEqual(balance['unreconciled_diff_kg'], 200.0)
        self.assertEqual(balance['unreconciled_diff_pct'], 1.0)

    # Prueba de rendimiento de linea y cruce de caudales con analitica de laboratorio
    def test_line_yield_and_oil_efficiency(self):
        # Caudal semilla = 2000 kg/h, Caudal expeller = 1400 kg/h
        # Rendimiento Expeller = 1400 / 2000 * 100 = 70.0%
        # Aceite estimado = 2000 - 1400 = 600 kg/h
        # Grasa semilla (45%) = 2000 * 0.45 = 900 kg/h
        # Grasa expeller (10%) = 1400 * 0.10 = 140 kg/h
        # Grasa extraida = 900 - 140 = 760 kg/h
        # Eficiencia extraccion = 760 / 900 * 100 = 84.44%
        res = calculate_line_yield_and_oil_efficiency(
            seed_speed_kg_h=2000.0,
            expeller_speed_kg_h=1400.0,
            seed_fat_pct=45.0,
            expeller_fat_pct=10.0
        )
        self.assertEqual(res['expeller_yield_pct'], 70.0)
        self.assertEqual(res['theoretical_oil_speed_kg_h'], 600.0)
        self.assertEqual(res['fat_in_seed_kg_h'], 900.0)
        self.assertEqual(res['fat_in_expeller_kg_h'], 140.0)
        self.assertEqual(res['extracted_oil_fat_kg_h'], 760.0)
        self.assertEqual(res['oil_extraction_efficiency_pct'], 84.44)

    # Prueba con caudal cero para evitar division por cero
    def test_line_yield_zero_speed(self):
        res = calculate_line_yield_and_oil_efficiency(0.0, 0.0)
        self.assertEqual(res['expeller_yield_pct'], 0.0)
        self.assertEqual(res['oil_extraction_efficiency_pct'], 0.0)

# Ejecucion directa de las pruebas unitarias
if __name__ == '__main__':
    unittest.main()
