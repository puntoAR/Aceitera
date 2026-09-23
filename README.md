# Sistema Industrial Modular de Control de Proceso, Existencias y Rendimiento — BioBalcarce v1.0.5

Solución tecnológica integral a medida, sin licencias propietarias ni costos recurrentes, desarrollada para la planta de extracción y prensado de oleaginosas de **BioBalcarce** (extrusión de semilla de girasol para la obtención de expeller y aceite crudo filtrado).

**Repositorio oficial en GitHub:** [https://github.com/puntoAR/Bio-Balcarce](https://github.com/puntoAR/Bio-Balcarce)

---

## Novedades y Capacidades en la Versión 1.0.5

1. **Control de Acceso de 3 Niveles:**
   - **Operario (`usuario`):** Carga de datos operativos de planta (pesadas por hora, paradas de línea), cubicaje de silos y tanques.
   - **Administrador / Gerente (`administrador`):** Acceso exclusivo de solo lectura al **Dashboard Ejecutivo**, auditoría y métricas de rendimiento (sin carga de datos).
   - **Administrador del Sistema (`admin_sistema`):** Acceso total a todos los módulos: calibración geométrica de equipos, administración y aprobación de usuarios, asignación de roles, gestión de turnos, diagnóstico del sistema y registros de auditoría.

2. **Registro de Usuarios y Flujo de Aprobación:**
   - Nuevos usuarios completan registro con Nombre y Apellido, DNI, Teléfono móvil y PIN/contraseña.
   - Estado pendiente hasta su aprobación por el Administrador del Sistema.

3. **Recuperación Automática de Contraseña (OTP):**
   - Sistema de generación de token numérico seguro temporal (15 minutos).
   - Envío simulado por WhatsApp / SMS para restablecimiento en planta.
   - Obligatoriedad de cambio de contraseña en el primer inicio de sesión.

4. **Gestión de Turnos Industriales (4 Franjas Horarias):**
   - **Turno Mañana (TM):** 06:00 a 14:00 (Operarios y Planta).
   - **Turno Tarde (TT):** 14:00 a 22:00 (Operarios y Planta).
   - **Turno Noche (TN):** 22:00 a 06:00 (Operarios y Planta).
   - **Turno Central (TC):** 08:00 a 16:00 (Exclusivo para perfil Administrador).

5. **Módulo de Laboratorio y Despacho de Camiones de Aceite:**
   - Determinaciones de laboratorio: Humedad y Materia Grasa en semilla y expeller, Acidez libre en aceite, impurezas y notas.
   - Control de carga de cisternas: inspección de estado del transporte, precintos colocados y su numeración, datos del chofer (nombre, DNI, patente chasis/acoplado), temperatura del lote y certificación de entrega de muestra testigo (SI/NO).

6. **Instalador Automatizado y Acceso Directo de Escritorio:**
   - Script de instalación desatendida (`instalar_aplicacion.bat`) para configurar el entorno en cualquier PC Windows con un solo clic.
   - Acceso directo en el Escritorio con icono oficial multirresolución (`biobalcarce.ico`).

7. **Interfaz Visual Industrial Inmersiva:**
   - Pantalla de ingreso con fondo fotográfico alusivo a planta aceitera moderna, destellos dorados, emblema oficial de girasol y gota dorada, y sello de calidad *powered by puntoAR*.

---

## Instalación Rápida desde GitHub

### Método 1: Instalación Automatizada con Turnkey Batch (Recomendado)

1. Clone o descargue el repositorio desde GitHub:
   ```bash
   git clone https://github.com/puntoAR/Bio-Balcarce.git
   cd Bio-Balcarce
   ```
2. Ejecute con doble clic el archivo **`instalar_aplicacion.bat`**.
   Este script automáticamente:
   - Verifica la disponibilidad de Python 3.10+ en el equipo.
   - Crea el entorno virtual aislado `.venv`.
   - Instala todas las dependencias requeridas (`Flask`, `Pillow`, `requests`, etc.).
   - Inicializa el esquema relacional de SQLite y aplica las migraciones automáticas.
   - Genera el acceso directo **"BioBalcarce - Control de Planta"** en el Escritorio de Windows con el icono oficial.

### Método 2: Instalación Manual

```bash
# 1. Crear entorno virtual
python -m venv .venv

# 2. Instalar dependencias
.venv\Scripts\pip install -r requirements.txt

# 3. Inicializar base de datos y esquema
.venv\Scripts\python -c "from core.database import init_db, apply_pending_migrations; init_db(); apply_pending_migrations()"

# 4. Crear acceso directo con icono oficial en el Escritorio
crear_acceso_directo.bat
```

---

## Cómo Iniciar la Aplicación

- **Desde el Escritorio de Windows:**
  Haga doble clic en el acceso directo **"BioBalcarce - Control de Planta"**.
- **Desde la carpeta del proyecto:**
  Haga doble clic en **`iniciar_sistema.bat`**.
- **Desde la línea de comandos:**
  ```bash
  .venv\Scripts\python run.py
  ```

### Acceso Web:
- **En la computadora de planta:** [http://localhost:5000](http://localhost:5000)
- **Desde teléfonos móviles o tablets en la red Wi-Fi de la planta:** `http://<IP-DE-LA-PC>:5000` (ejemplo: `http://192.168.0.112:5000`).

---

## Usuarios y Credenciales Iniciales

El sistema se inicializa con los siguientes usuarios de demostración y puesta en marcha:

| Usuario | Contraseña / PIN | Rol | Permisos y Alcance |
| :--- | :--- | :--- | :--- |
| `admin` | `1234` | Administrador del Sistema (`admin_sistema`) | Acceso irrestricto a todos los paneles, usuarios, calibración de silos/tanques, auditoría y diagnóstico |
| `gerente` | `3333` | Administrador / Gerente (`administrador`) | Acceso exclusivo al Dashboard Ejecutivo y reportes gerenciales |
| `operario` | `1111` | Operario de Planta (`usuario`) | Carga de pesadas horarias, paradas de línea y cubicaje de tanques/silos |
| `laboratorio` | `2222` | Analista de Calidad (`usuario`) | Carga de análisis de laboratorio y despacho de camiones de aceite |

---

## Estructura del Código

```
biobalcarce-control-planta/
│
├── run.py                           # Servidor web industrial Flask y ruteo
├── config.py                        # Configuración física, rutas y red
├── version.json                     # Manifiesto de versión y notas de release
├── requirements.txt                 # Dependencias Python
├── iniciar_sistema.bat              # Lanzador rápido del servidor
├── instalar_aplicacion.bat          # Instalador llave en mano para nuevos clones
├── crear_acceso_directo.bat         # Creador de acceso directo con icono en Windows
├── diagnostico.bat                  # Auditor de salud y consistencia física
├── actualizar_sistema.bat           # Actualizador in-place desde repositorio
├── revertir_actualizacion.bat       # Restaurador automático ante contingencias
│
├── core/                            # Núcleo del sistema
│   ├── database.py                  # Conexión SQLite, esquemas y tablas
│   ├── migrations.py                # Motor de migraciones incrementales
│   ├── security.py                  # Roles, sesiones, autenticación y OTP
│   ├── backup_manager.py            # Copias de seguridad atómicas
│   └── error_logger.py              # Auditoría estructurada y logging
│
├── modules/                         # Módulos de negocio desacoplados
│   ├── admin/                       # Aprobación de usuarios, auditoría y panel admin
│   ├── calculations/                # MOTOR FÍSICO-MATEMÁTICO PURO
│   │   ├── speed_calc.py            # Fórmulas de bolsas, ritmos y velocidades
│   │   ├── tank_calc.py             # Geometría vertical y horizontal (arccos)
│   │   ├── silo_calc.py             # Cubicaje de silos, conos y copetes
│   │   ├── lab_calc.py              # Cálculos analíticos de laboratorio
│   │   └── yield_calc.py            # Rendimiento y balance de materia
│   ├── configuration/               # Calibración de parámetros y dimensiones
│   ├── dashboard/                   # Vista ejecutiva para gerencia
│   ├── inventory/                   # Mediciones y cubicajes periódicos
│   ├── laboratory/                  # Análisis de muestras y despacho de camiones
│   ├── production/                  # Registro horario de pesadas y paradas
│   ├── updater/                     # Módulo de actualizaciones automáticas
│   └── yield_balance/               # Conciliación y balance de turnos
│
├── diagnostics/                     # Módulo de auditoría y diagnóstico autónomo
│   └── system_diagnostics.py        # Comprobación de integridad, DB y red
│
├── static/                          # Recursos visuales
│   ├── css/styles.css               # Estilos industriales mobile-first
│   ├── js/app.js                    # Interactividad y asistentes de cálculo
│   └── images/                      # Logotipos, fondos e iconos (.ico, .png)
│       ├── biobalcarce.ico          # Icono multirresolución de Windows
│       ├── logo_simple.png          # Logo de girasol y gota para navbar
│       ├── logo_full.png            # Logo completo para pantallas de acceso
│       └── oil_plant_bg.jpg         # Fondo industrial fotorrealista
│
├── templates/                       # Plantillas HTML modulares
│   ├── base.html                    # Layout principal con navbar e icono
│   ├── login.html                   # Pantalla de acceso estilo AssistencIA
│   ├── register.html                # Formulario de solicitud de acceso
│   ├── reset_password.html          # Solicitud de código OTP
│   ├── verify_reset_code.html       # Verificación de código OTP
│   ├── change_password.html         # Cambio obligatorio / voluntario de clave
│   ├── admin_users.html             # Gestión y aprobación de usuarios
│   ├── dashboard.html               # Tablero general ejecutivo
│   ├── production.html              # Muestreo de línea de prensado
│   ├── inventory.html               # Cubicaje de tanques y silos
│   ├── laboratory.html              # Registro analítico y despacho de camiones
│   ├── yield.html                   # Balances de masa
│   ├── config.html                  # Dimensiones y calibración
│   └── error.html                   # Pantalla de error con guía de soporte
│
└── tests/                           # Batería de pruebas automatizadas (41 tests)
    ├── test_calculations.py         # Validación del motor matemático
    ├── test_integration.py          # Pruebas integrales de flujo web
    ├── test_auth.py                 # Pruebas de roles, recuperación y permisos
    ├── test_truck_dispatch.py       # Pruebas de precintos y despacho de aceite
    ├── test_shifts.py               # Pruebas de los 4 turnos operativos
    └── test_updater.py              # Pruebas de actualización y respaldos
```

---

## Verificación y Pruebas Automatizadas

Para validar que todo el sistema matemático, las reglas de negocio y los flujos de seguridad funcionen al 100%:

```bash
.venv\Scripts\python -m unittest discover -s tests -v
```

Las 41 pruebas cubren:
- Fórmulas geométricas exactas de cilindros horizontales con tapas toriesféricas y arcos de círculo.
- Cubicaje de silos cónicos y copetes superiores.
- Balances de masa y rendimiento extractivo.
- Matriz de permisos de los 3 niveles de usuario.
- Flujos de registro, aprobación y reseteo por código OTP.
- Control de precintos y despacho de camiones de aceite.

---

Desarrollado para **BioBalcarce** por **puntoAR** — *El valor de estar presentes*.
