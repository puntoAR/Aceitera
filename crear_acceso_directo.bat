@echo off
REM Desactiva el eco de comandos para una ejecucion limpia
title Crear Acceso Directo - Control de Planta Aceitera
REM Titulo informativo en la consola
echo ======================================================
REM Encabezado visual
echo    CREANDO ACCESO DIRECTO CON ICONO OFICIAL
REM Nombre del sistema
echo ======================================================
REM Separador visual
setlocal enabledelayedexpansion
REM Habilita expansion de variables retardada
cd /d "%~dp0"
REM Se posiciona en la carpeta raiz del proyecto
set "DIR_APP=%~dp0"
REM Guarda la ruta absoluta del proyecto con barra final
set "TARGET=%DIR_APP%iniciar_sistema.bat"
REM Define la ruta completa al script lanzador
set "ICON=%DIR_APP%static\images\favicon.ico"
REM Define la ruta del icono oficial de girasol y gota de aceite
set "DESKTOP_DIR=%USERPROFILE%\Desktop"
REM Obtiene el directorio del escritorio del usuario actual
set "LNK_FILE=%DESKTOP_DIR%\Aceitera - Control de Planta.lnk"
REM Nombre del archivo de acceso directo en el escritorio

echo Directorio de instalacion: %DIR_APP%
REM Informa la ruta detectada
echo Icono asignado: %ICON%
REM Informa el archivo de icono
echo Destino: %LNK_FILE%
REM Informa la ubicacion de destino

powershell -NoProfile -ExecutionPolicy Bypass -Command "$ws = New-Object -ComObject WScript.Shell; $s = $ws.CreateShortcut('%LNK_FILE%'); $s.TargetPath = '%TARGET%'; $s.WorkingDirectory = '%DIR_APP%'; $s.IconLocation = '%ICON%,0'; $s.Description = 'Aceitera - Sistema Industrial Modular de Control de Planta'; $s.Save()"
REM Invoca PowerShell para generar el archivo .lnk nativo con su icono oficial

if exist "%LNK_FILE%" (
    REM Verifica que el archivo de acceso directo haya sido creado
    echo.
    REM Salto de linea
    echo [EXITO] Acceso directo creado exitosamente en su Escritorio de Windows:
    REM Mensaje de exito
    echo         "%LNK_FILE%"
    REM Muestra la ruta del acceso directo
    echo.
    REM Salto de linea
    echo Ya puede hacer doble clic en el icono "Aceitera - Control de Planta"
    REM Instruccion de inicio
    echo en su escritorio para abrir el sistema industrial.
    REM Descripcion de uso
) else (
    REM Si no se pudo crear el archivo
    echo [ERROR] No se pudo generar el acceso directo en el escritorio.
    REM Mensaje de advertencia
)
REM Fin de la comprobacion

pause
REM Pausa para que el usuario pueda leer la confirmacion
