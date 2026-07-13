@echo off
setlocal

cd /d "%~dp0"
python scripts\install_dev_loader.py %*
set "SYNC_EXIT=%ERRORLEVEL%"

echo.
if "%SYNC_EXIT%"=="0" (
    echo Done. Restart Anki to run the add-on from this folder.
) else (
    echo Setup failed with exit code %SYNC_EXIT%.
)
echo.
pause
exit /b %SYNC_EXIT%
