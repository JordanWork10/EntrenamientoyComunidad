@echo off
setlocal EnableExtensions

REM =========================================================
REM V132.07A - LIMPIEZA DE VIDEOS PROFESIONALES
REM Proyecto: Entrenamiento y Comunidad
REM
REM Modo predeterminado: --dry-run
REM Eliminacion real: requiere --apply
REM =========================================================

set "PROJECT_ROOT=C:\EntrenamientoyComunidadV2"
set "PYTHON_EXE=%PROJECT_ROOT%\.venv\Scripts\python.exe"
set "CLEANUP_MODE=--dry-run"

REM =========================================================
REM VALIDAR ARGUMENTOS
REM =========================================================

if "%~1"=="" goto validate_files

if /I "%~1"=="--dry-run" goto validate_files

if /I "%~1"=="--apply" (
    set "CLEANUP_MODE=--apply"
    goto validate_files
)

echo.
echo ERROR: argumento no reconocido.
echo.
echo Opciones disponibles:
echo   --dry-run   Consulta sin eliminar archivos.
echo   --apply     Ejecuta eliminaciones pendientes.
echo.

exit /b 2

REM =========================================================
REM COMPROBAR ARCHIVOS DEL PROYECTO
REM =========================================================

:validate_files

if not exist "%PROJECT_ROOT%\manage.py" (
    echo.
    echo ERROR: no se encontro manage.py.
    echo.
    exit /b 1
)

if not exist "%PYTHON_EXE%" (
    echo.
    echo ERROR: no se encontro Python del entorno virtual.
    echo.
    exit /b 1
)

REM =========================================================
REM ENTRAR AL DIRECTORIO DEL PROYECTO
REM =========================================================

pushd "%PROJECT_ROOT%"

if errorlevel 1 (
    echo.
    echo ERROR: no se pudo abrir el proyecto.
    echo.
    exit /b 1
)

REM =========================================================
REM EJECUTAR LIMPIEZA
REM =========================================================

echo.
echo ===============================================
echo ENTRENAMIENTO Y COMUNIDAD - V132.07A
echo ===============================================
echo.

echo Modo seleccionado: %CLEANUP_MODE%
echo.

"%PYTHON_EXE%" manage.py retry_professional_video_cleanup %CLEANUP_MODE% --limit 100

set "RETURN_CODE=%ERRORLEVEL%"

REM =========================================================
REM INFORMAR RESULTADO
REM =========================================================

echo.

if "%RETURN_CODE%"=="0" (
    echo EJECUCION FINALIZADA CORRECTAMENTE.
) else (
    echo ATENCION: la ejecucion termino con errores.
    echo Codigo de salida: %RETURN_CODE%
)

echo.

popd

exit /b %RETURN_CODE%