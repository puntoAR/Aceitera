@echo off
REM Desactiva la repeticion de comandos en consola
title Instalador Aceitera - Control de Planta
REM Establece el titulo de la consola de instalacion
echo ======================================================
REM Encabezado visual de inicio
echo    INSTALADOR OFICIAL ACEITERA - CONTROL DE PLANTA
REM Nombre del sistema
echo ======================================================
REM Separador visual
setlocal enabledelayedexpansion
REM Habilita la expansion retardada de variables
cd /d "%~dp0"
REM Posiciona la consola en la carpeta de la aplicacion

echo [PASO 1/4] Verificando interprete de Python...
REM Notifica la verificacion de Python
set PYTHON_CMD=
REM Inicializa la variable de Python
if exist ".venv\Scripts\python.exe" (
    REM Comprueba si ya existe el entorno virtual
    set PYTHON_CMD=".venv\Scripts\python.exe"
    REM Asigna el interprete local del venv
) else (
    REM Si no existe el venv, busca en el sistema
    python -c "exit(0)" >nul 2>nul
    REM Prueba python global
    if not errorlevel 1 (
        REM Asigna python global
        set PYTHON_CMD=python
    ) else (
        REM Prueba lanzador py
        py -3 -c "exit(0)" >nul 2>nul
        REM Verifica py -3
        if not errorlevel 1 (
            REM Asigna py -3
            set PYTHON_CMD=py -3
        )
    )
)
REM Fin de deteccion de Python

if "%PYTHON_CMD%"=="" (
    REM Si no se encontro ningun Python
    echo [ERROR CRITICO] No se encontro Python 3 instalado en este equipo.
    REM Informa error
    echo Instale Python 3.10 o superior marcando "Add Python to PATH".
    REM Brinda sugerencia
    pause
    REM Pausa antes de salir
    exit /b 1
    REM Salida con error
)
REM Fin de control critico

if not exist ".venv\Scripts\python.exe" (
    REM Si no existe el entorno virtual local
    echo [PASO 2/4] Creando entorno virtual local (.venv)...
    REM Informa creacion de venv
    %PYTHON_CMD% -m venv .venv
    REM Genera la carpeta .venv aislada
    set PYTHON_CMD=".venv\Scripts\python.exe"
    REM Actualiza el comando hacia el nuevo venv
) else (
    REM Si ya existia
    echo [PASO 2/4] Entorno virtual (.venv) verificado.
    REM Mensaje de confirmacion
)
REM Fin de paso 2

echo [PASO 3/4] Instalando dependencias del sistema...
REM Notifica instalacion de librerias
.venv\Scripts\python.exe -m pip install -r requirements.txt --quiet
REM Instala silenciosamente las dependencias de requirements.txt
echo [OK] Dependencias instaladas correctamente.
REM Confirma instalacion

echo [PASO 4/4] Inicializando base de datos y creando acceso directo con icono...
REM Notifica configuracion final
.venv\Scripts\python.exe -c "from core.database import init_db; from core.migrations import apply_pending_migrations; init_db(); apply_pending_migrations(); print('Base de datos inicializada.')"
REM Inicializa el esquema SQLite y aplica migraciones de esquema

call crear_acceso_directo.bat
REM Invoca el creador del acceso directo con icono en el escritorio

echo ======================================================
REM Encabezado de finalizacion
echo    INSTALACION COMPLETADA EXITOSAMENTE
REM Mensaje de exito
echo ======================================================
REM Separador visual
echo El sistema esta listo para su uso.
REM Indicacion al usuario
echo Inicie la aplicacion desde el icono en su Escritorio o ejecutando iniciar_sistema.bat
REM Instruccion final
pause
REM Pausa para visualizacion
