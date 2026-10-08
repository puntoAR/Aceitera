@echo off
REM Desactiva el eco de comandos en la consola para una presentacion limpia
title Aceitera - Actualizador de Sistema
REM Imprime encabezado visual para el operador de planta
echo ======================================================
echo    ACTUALIZADOR DEL SISTEMA ACEITERA (IN-PLACE)
echo ======================================================
REM Cambia el directorio de trabajo a la unidad y carpeta donde reside este script
cd /d "%~dp0"
REM Solicita al usuario ingresar o arrastrar la ruta del paquete de actualizacion
set /p UPDATE_PATH="Arrastre o ingrese la ruta del archivo ZIP o carpeta de actualizacion: "
REM Si el usuario no proporciono ninguna ruta, advierte y sale
if "%UPDATE_PATH%"=="" (
    REM Informa que no se indico ruta
    echo No se especifico ninguna ruta de actualizacion.
    REM Pausa para lectura
    pause
    REM Sale con codigo de error
    exit /b 1
)
REM Inicializa la variable de interprete de Python como vacia
set PYTHON_BIN=
REM Verifica si existe el interprete dentro del entorno virtual local
if exist ".venv\Scripts\python.exe" (
    REM Ejecuta una prueba silenciosa para comprobar que el entorno virtual no este roto
    ".venv\Scripts\python.exe" -c "exit(0)" >nul 2>nul
    REM Si la prueba fue exitosa, asigna el interprete del venv
    if not errorlevel 1 (
        REM Asigna el interprete verificado del entorno virtual local
        set PYTHON_BIN=".venv\Scripts\python.exe"
    )
)
REM Si el entorno virtual no respondio, busca Python en el sistema
if "%PYTHON_BIN%"=="" (
    REM Comprueba si python esta disponible en el PATH del sistema
    python -c "exit(0)" >nul 2>nul
    REM Si python global funciona correctamente
    if not errorlevel 1 (
        REM Asigna python global como interprete a utilizar
        set PYTHON_BIN=python
    ) else (
        REM Comprueba el lanzador py de Windows
        py -3 -c "exit(0)" >nul 2>nul
        REM Si py funciona correctamente
        if not errorlevel 1 (
            REM Asigna py -3 como comando ejecutor
            set PYTHON_BIN=py -3
        )
    )
)
REM Si no se encontro ningun interprete funcional de Python
if "%PYTHON_BIN%"=="" (
    REM Muestra mensaje de advertencia clara
    echo [ERROR CRITICO] No se detecto un interprete funcional de Python en este equipo.
    REM Informa los pasos para corregir la situacion
    echo Asegurese de tener instalado Python 3.10 o superior con PATH habilitado.
    REM Pausa la consola para visualizacion del error
    pause
    REM Sale del proceso con codigo de error
    exit /b 1
)
REM Ejecuta el actualizador seguro pasando la ruta del paquete
%PYTHON_BIN% modules\updater\system_updater.py %UPDATE_PATH%
REM Pausa la consola para que el usuario pueda leer los resultados
pause
