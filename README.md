# Sistema Industrial Modular de Control de Proceso, Existencias y Rendimiento — BioBalcarce v1.1.7

Solución tecnológica integral a medida, sin licencias propietarias ni costos recurrentes, desarrollada para la planta de extracción y prensado de oleaginosas de **BioBalcarce** (extrusión de semilla de girasol para la obtención de expeller y aceite crudo filtrado).

**Repositorio oficial en GitHub:** [https://github.com/puntoAR/Bio-Balcarce](https://github.com/puntoAR/Bio-Balcarce)

---

## Novedades y Capacidades en la Versión 1.1.7

1. **Centro de Diagnóstico Interactivo de Errores y Excepciones (`/admin/errors`):**
   - **Tarjetas de incidentes cliqueables:** Al hacer clic en cualquier error registrado, se despliega de inmediato el panel de diagnóstico técnico profundo.
   - **Localización exacta en código fuente:** Identificación automática del **archivo** (ej. `modules/inventory/service.py`), la **línea exacta** (ej. `Línea 166`), la **función/ámbito** y la **instrucción de código** que originó la falla.
   - **Inspección técnica y traza completa (Stack Trace):** Visualización en bloque terminal oscuro con botón para **Copiar Traza** al portapapeles en un solo clic para soporte técnico.
   - **Filtros rápidos y buscador dinámico:** Filtrado instantáneo por estado (`Todos`, `⚠️ Solo Pendientes`, `✓ Solo Resueltos`) y búsqueda en tiempo real por palabra clave, usuario, ruta o archivo.
   - **Compatibilidad histórica y retroactiva:** Análisis automático de trazas anteriores para deducir el archivo y línea de origen incluso en incidentes registrados previamente.

2. **Corrección Integral del Registro de Movimientos de Inventario:**
   - Corrección de la instrucción de inserción en `inventory_movements`, garantizando el registro fluido de ingresos de cereal, despachos de aceite/expeller y trasvases de planta.

3. **Cockpit Ejecutivo con Integración Lateral de Mantenimiento (v1.1.2 - v1.1.5):**
   - Paneles e indicadores clave de Mantenimiento Preventivo y Operativo integrados en el Dashboard principal al costado de Eficiencia y Rendimiento.
   - Disposición flex responsiva adaptada tanto para monitores de planta como para visualización en teléfonos celulares.

4. **Persistencia en la Nube Serverless (Vercel + Turso Cloud SQLite) (v1.1.1):**
   - Integración nativa con **Turso (libSQL)** vía HTTP: permite que todas las altas de usuarios, mediciones de silos/tanques, mantenimiento y registros de pesadas se guarden de forma permanente en la nube y **nunca se borren ni desaparezcan** cuando Vercel apaga contenedores inactivos.
   - Diagnóstico automático en el panel administrativo y visor de incidentes alertando si la aplicación está en modo efímero o con persistencia cloud activa.

5. **Módulo de Mantenimiento Industrial (v1.1.0):**
   - **Registro de actividades en 3 categorías operativas oficiales:**
     - **Operativa:** urgencias y desperfectos que surgen en el momento durante la marcha de la planta.
     - **Planificada (Requiere Parada de Planta):** intervenciones mayores que exigen detener la molienda o la línea de prensado.
     - **Planificada (Sin Parada de Planta):** tareas programables en paralelo mientras la planta continúa en plena operación.
   - **Histórico Visual de Reparaciones:** Subida directa y visualización cronológica en galería de fotografías de intervenciones mecánicas y reemplazo de componentes.

3. **Pañol y Stock de Repuestos:**
   - **Control de existencias y tipificación de consumibles:** Diferenciación entre repuestos durables y consumibles de recambio periódico (grasas, lubricantes, precintos, filtros).
   - **Alertas automáticas de stock mínimo:** Detección visual en tiempo real cuando la existencia actual cae por debajo del umbral crítico configurado.
   - **Reporte Oficial de Pañol y Repuestos:** Formato imprimible optimizado con membrete institucional, firmas de responsables y exportación directa a formato CSV / Excel.

4. **Puesta a Cero Segura para Inicio de Producción Real:**
   - Herramienta administrativa para reiniciar a cero los datos operativos de prueba (pesadas, paradas, mediciones de silos y tanques, muestras de laboratorio y despachos de prueba).
   - **Garantía estricta de preservación de datos:** En todas las actualizaciones presentes y futuras, los datos estructurales (usuarios, calibraciones de silos y tanques, catálogo de repuestos y registros de auditoría) se preservan intactos sin riesgo de borrado o sobreescritura accidental.

5. **Cálculos de Planta Estandarizados (Caudales Horarios y Rendimiento de Expeller):**
   - **Muestreo físico en 30 segundos:** Formulario de pesadas optimizado con selector rápido `[⚡ 30 seg (Estándar)]` y `[60 seg]`, calculando en tiempo real:
     $$\text{Caudal (kg/h)} = \left(\frac{\text{Peso Neto (kg)}}{\text{Tiempo (seg)}}\right) \times 3600$$
   - **Promedio de Turno por Materia Prima:** Cálculo independiente del caudal horario promedio de Semilla y Expeller para las muestras de la guardia.
   - **Rendimiento de Expeller en Línea:**
     $$\text{Rendimiento Expeller (\%)} = \left(\frac{\text{Promedio Caudal Expeller}}{\text{Promedio Caudal Semilla}}\right) \times 100$$
   - **Cruce con Analítica de Laboratorio:** Estimación instantánea del caudal de aceite crudo y de la eficiencia de extracción de grasa comparando el % Materia Grasa en semilla vs. % Grasa Residual en expeller.
   - **Persistencia Cronológica de Ensayos:** Si un turno operativo (ej. noche) no posee análisis directos cargados, el sistema recupera automáticamente el ensayo válido más reciente de la planta.

2. **Nivel de Acceso Gerencia:**
   - Formalización del rol oficial **Gerencia** en todas las vistas, formularios de asignación, insignias de usuario y base de datos relacional.

3. **Optimización Responsiva para Celulares:**
   - En pantallas móviles se priorizan los indicadores directos (KPIs), ocultando automáticamente fórmulas extensas y campos secundarios para una lectura limpia e inmediata.

1. **PWA (Progressive Web App) para Celulares (Android e iOS):**
   - Instalación directa en dispositivos móviles mediante **Web App Manifest** y **Service Worker**.
   - Acceso con un solo toque desde la pantalla de inicio con los iconos oficiales en alta resolución (192x192 y 512x512 px) y soporte adaptativo *maskable*.
   - **Enmascaramiento de URL en móviles:** Al abrirse desde el icono del celular, la aplicación se ejecuta en modo *standalone* (a pantalla completa), eliminando la barra de navegación del navegador web para brindar una experiencia 100% idéntica a una aplicación nativa.
   - Banner de instalación inteligente en pantalla (*"📲 Instalar BioBalcarce"*).

2. **Creación Directa de Perfiles de Usuario por el Administrador:**
   - El Administrador del Sistema puede crear usuarios directamente desde el panel sin depender de solicitudes de registro previas.
   - **Nombres de usuario comunes y personalizados:** Se puede asignar cualquier identificador (`jmartinez`, `carlos_gomez`, `supervisor1`, etc.), sin quedar restringido a las cuentas de prueba iniciales (`admin`, `gerente`, `operario`).
   - **Asignación inmediata de los 3 niveles de acceso de planta:**
     1. **Administrador del Sistema (`admin_sistema`):** Control irrestricto de todos los paneles, calibración de silos/tanques, gestión de usuarios, Turno Central y bitácora de auditoría.
     2. **Gerencia (`gerencia`):** Monitoreo y solo lectura del Dashboard Ejecutivo y reportes de rendimiento. Sin carga de datos.
     3. **Operario / Usuario Común (`usuario`):** Carga operativa de producción (pesadas y paradas), cubicaje de silos y tanques, determinaciones de laboratorio y despacho de camiones cisterna.
   - Generador asistido de contraseñas seguras y casilla para exigir cambio obligatorio de clave en el primer ingreso.

3. **Despliegue Serverless en Vercel:**
   - Archivo de configuración [vercel.json](file:///E:/PROYECTOS/biobalcarce-control-planta/vercel.json) y punto de entrada WSGI [api/index.py](file:///E:/PROYECTOS/biobalcarce-control-planta/api/index.py).
   - Detección automática del entorno Vercel (`VERCEL=1`) redirigiendo la persistencia a `/tmp/data` y logs a `/tmp/logs`.
   - Inicialización automática de esquema relacional y migraciones en caliente en cada despliegue.

4. **Privacidad del Repositorio y Enmascaramiento de URL:**
   - **Ocultamiento del código fuente:** El repositorio en GitHub puede configurarse como **Privado** (*Private*). Vercel soporta de forma nativa repositorios privados sin costos ni configuraciones adicionales.
   - **Dominio propio:** En Vercel (*Project Settings -> Domains*) es posible configurar un subdominio institucional (ej. `planta.biobalcarce.com.ar` o `app.puntoar.com.ar`) para enmascarar la URL por defecto de Vercel.

---

## Cómo Activar Persistencia Permanente en Vercel con Turso (2 minutos)

Por diseño de las plataformas Serverless (como Vercel o AWS Lambda), el disco local `/tmp` es temporal y se reinicia cuando la aplicación queda inactiva. Para que los usuarios creados y las pesadas se guarden permanentemente en la nube de forma 100% gratuita:

1. **Crear base de datos gratuita en Turso:**
   - Ingresa a [https://turso.tech](https://turso.tech) e inicia sesión con tu cuenta de GitHub.
   - Haz clic en **Create Database**, ingresa el nombre `biobalcarce` y selecciona la región más cercana (ej. `gru` San Pablo o `iad` Washington).
2. **Copiar URL y Token de Acceso:**
   - En el panel de Turso obtendrás la URL: `https://biobalcarce-[tu-usuario].turso.io`.
   - Haz clic en **Create Token** para generar un token de autenticación.
3. **Cargar las Variables en Vercel:**
   - En tu proyecto de Vercel, ve a **Settings** &rarr; **Environment Variables**.
   - Agrega:
     - `TURSO_DATABASE_URL` = `https://biobalcarce-[tu-usuario].turso.io`
     - `TURSO_AUTH_TOKEN` = `[tu-token-de-turso]`
   - Haz un nuevo despliegue o pulsa **Redeploy**.
   - ¡Listo! A partir de ese momento todos los datos se sincronizan y persisten para siempre en la nube sin importar los reinicios de Vercel.

---

## Cómo Instalar la App en el Celular (PWA)

### En Teléfonos Android (Google Chrome / Edge):
1. Ingrese a la URL de la aplicación desde el navegador del celular.
2. Aparecerá automáticamente un aviso en la parte inferior: **"Instalar BioBalcarce - Acceso directo en tu celular"**.
3. Presione el botón **📲 Instalar** y confirme.
4. El icono de BioBalcarce se agregará a la pantalla de inicio de su teléfono. Al abrirlo, se iniciará a pantalla completa sin barra de direcciones URL.

### En Teléfonos Apple iPhone / iPad (Safari):
1. Abra la URL de la aplicación en **Safari**.
2. Toque el botón **Compartir** (icono de cuadrado con flecha hacia arriba ⎋ en la barra inferior).
3. Seleccione la opción **"Agregar a la pantalla de inicio"** (o *"Add to Home Screen"* ➕).
4. Confirme el nombre **BioBalcarce** y pulse **Agregar**.

---

## Instalación Rápida en PC (Windows)

### Método Automatizado con Turnkey Batch (Recomendado)

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

---

## Estructura del Código

```
biobalcarce-control-planta/
│
├── run.py                           # Servidor web Flask, ruteo y endpoints PWA (/manifest.json, /sw.js)
├── config.py                        # Configuración física, rutas locales y soporte serverless Vercel (/tmp)
├── vercel.json                      # Configuración de despliegue y reescritura para Vercel
├── api/
│   └── index.py                     # Punto de entrada WSGI para Vercel Serverless
├── version.json                     # Manifiesto de versión (v1.0.6) y notas de release
├── requirements.txt                 # Dependencias Python
├── iniciar_sistema.bat              # Lanzador rápido del servidor en Windows
├── instalar_aplicacion.bat          # Instalador llave en mano para nuevos clones
├── crear_acceso_directo.bat         # Creador de acceso directo con icono en Windows
├── generate_pwa_icons.py            # Generador asistido de iconos PWA de alta resolución
├── diagnostico.bat                  # Auditor de salud y consistencia física
├── actualizar_sistema.bat           # Actualizador in-place desde repositorio
├── revertir_actualizacion.bat       # Restaurador automático ante contingencias
│
├── core/                            # Núcleo del sistema
│   ├── database.py                  # Conexión SQLite, esquemas y tablas
│   ├── migrations.py                # Motor de migraciones incrementales
│   ├── security.py                  # Roles, sesiones, autenticación y OTP
│   ├── backup_manager.py            # Copias de seguridad atómicas con SQLite Backup API
│   └── error_logger.py              # Auditoría estructurada y logging
│
├── modules/                         # Módulos de negocio desacoplados
│   ├── admin/                       # Alta y aprobación de usuarios, asignación de roles, auditoría
│   ├── calculations/                # MOTOR FÍSICO-MATEMÁTICO PURO (desacoplado)
│   ├── configuration/               # Calibración de parámetros y dimensiones
│   ├── dashboard/                   # Vista ejecutiva para gerencia
│   ├── inventory/                   # Mediciones y cubicajes periódicos
│   ├── laboratory/                  # Análisis de muestras y despacho de camiones de aceite
│   ├── production/                  # Registro horario de pesadas y paradas
│   ├── updater/                     # Módulo de actualizaciones automáticas
│   └── yield_balance/               # Conciliación y balance de turnos
│
├── diagnostics/                     # Módulo de auditoría y diagnóstico autónomo
│   └── system_diagnostics.py        # Comprobación de integridad, DB y red
│
├── static/                          # Recursos visuales y PWA
│   ├── manifest.json                # Manifiesto PWA (nombre, colores, iconos, display standalone)
│   ├── js/sw.js                     # Service Worker PWA para soporte offline y cacheo
│   ├── css/styles.css               # Estilos industriales mobile-first
│   ├── js/app.js                    # Interactividad, asistente de cálculo y detector de instalación PWA
│   └── images/                      # Logotipos, fondos e iconos
│       ├── biobalcarce.ico          # Icono multirresolución de Windows
│       ├── pwa_icon_192.png         # Icono PWA estándar 192x192 px
│       ├── pwa_icon_512.png         # Icono PWA estándar 512x512 px
│       ├── pwa_icon_maskable_192.png # Icono PWA maskable 192x192 px para Android
│       ├── pwa_icon_maskable_512.png # Icono PWA maskable 512x512 px para Android
│       ├── logo_simple.png          # Logo de girasol y gota para navbar
│       ├── logo_full.png            # Logo completo para pantallas de acceso
│       └── oil_plant_bg.jpg         # Fondo industrial fotorrealista
│
├── templates/                       # Plantillas HTML modulares
│   ├── base.html                    # Layout maestro con etiquetas PWA y banner de instalación
│   ├── admin_users.html             # Gestión, aprobación y alta directa de perfiles de usuario
│   ├── login.html                   # Pantalla de acceso industrial estilo AssistencIA
│   ├── register.html                # Formulario de solicitud de acceso
│   ├── reset_password.html          # Solicitud de código OTP
│   ├── verify_code.html             # Verificación de código OTP
│   ├── dashboard.html               # Tablero general ejecutivo
│   └── ...
│
└── tests/                           # Batería de pruebas automatizadas (43 tests)
    ├── test_roles_security.py       # Pruebas de roles, alta de usuarios personalizados y rutas PWA
    ├── test_calculations.py         # Validación del motor matemático
    ├── test_integration.py          # Pruebas integrales de flujo web
    ├── test_shifts_and_laboratory.py # Pruebas de turnos, laboratorio y despacho de camiones
    ├── test_remote_updater.py       # Pruebas de actualización remota
    └── test_updater.py              # Pruebas de respaldos y restauración
```

---

## Verificación y Pruebas Automatizadas

Para validar que todo el sistema matemático, las reglas de negocio, los flujos de seguridad y los endpoints de PWA funcionen al 100%:

```bash
.venv\Scripts\python -m unittest discover -s tests -v
```

---

Desarrollado para **BioBalcarce** por **puntoAR** — *El valor de estar presentes*.
