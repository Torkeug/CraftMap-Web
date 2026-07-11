@echo off
echo Building CraftMap.exe...
.venv\Scripts\python.exe -m PyInstaller --onefile --noconsole --icon icon.ico --name CraftMap --clean --distpath . --add-data "frontend;frontend" --add-data "game_data_extract\shipwreck_loot.json;game_data_extract" main.py
if %ERRORLEVEL% == 0 (
    echo Done! CraftMap.exe updated.
) else (
    echo Build failed.
)
pause
