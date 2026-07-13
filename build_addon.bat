@echo off
setlocal

cd /d "%~dp0"

set "NO_OPEN="
set "NO_PAUSE="

:parse_args
if "%~1"=="" goto args_done
if /I "%~1"=="--no-open" set "NO_OPEN=1"
if /I "%~1"=="--no-pause" set "NO_PAUSE=1"
shift
goto parse_args

:args_done
set "PYTHON_CMD=python"
where py >nul 2>nul
if not errorlevel 1 set "PYTHON_CMD=py -3"

echo.
echo ==========================================
echo   Building Contextual Review for sharing
echo ==========================================
echo.

echo [1/3] Running tests...
%PYTHON_CMD% -m unittest discover -s tests
if errorlevel 1 goto failed

echo.
echo [2/3] Running smoke review...
%PYTHON_CMD% scripts\smoke_review_loop.py
if errorlevel 1 goto failed

echo.
echo [3/3] Creating the Anki add-on...
%PYTHON_CMD% scripts\package_addon.py
if errorlevel 1 goto failed

set "OUTPUT=%CD%\dist\contextual_review_addon.ankiaddon"
if not exist "%OUTPUT%" (
    echo.
    echo Build failed: the expected add-on file was not created.
    goto failed
)

echo.
echo Success. Send this file:
echo %OUTPUT%
echo.

if not defined NO_OPEN explorer.exe /select,"%OUTPUT%"

if not defined NO_PAUSE pause
exit /b 0

:failed
set "BUILD_EXIT=%ERRORLEVEL%"
if "%BUILD_EXIT%"=="0" set "BUILD_EXIT=1"
echo.
echo Build failed. No new add-on should be sent until the error above is fixed.
echo.
if not defined NO_PAUSE pause
exit /b %BUILD_EXIT%
