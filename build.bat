@echo off
echo Building CraftMapWeb.exe...
.venv\Scripts\python.exe -m PyInstaller --onefile --noconsole --icon icon.ico --name CraftMapWeb --clean --distpath . --add-data "frontend;frontend" main.py
if %ERRORLEVEL% == 0 (
    echo Done! CraftMapWeb.exe updated.
) else (
    echo Build failed.
)
pause
