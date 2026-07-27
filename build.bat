@echo off
echo Building CraftMap.exe...
.venv\Scripts\python.exe -m PyInstaller --onedir --noconsole --icon icon.ico --name CraftMap --clean --distpath . --add-data "frontend;frontend" --add-data "game_data_extract\shipwreck_loot.json;game_data_extract" --add-data "game_data_extract\farming.json;game_data_extract" main.py
if %ERRORLEVEL% == 0 (
    REM --onedir always nests the exe as .\CraftMap\CraftMap.exe - move it
    REM (and its _internal support folder) up to the project root so
    REM backend/paths.py's sys.executable-anchored DB_PATH/CONFIG_PATH keep
    REM resolving to the same resources.db/config.json that dev-mode
    REM `python main.py` and every tools/*.py script already use (those
    REM always resolve two levels up from backend/paths.py, i.e. the
    REM project root, regardless of the frozen exe's location - see that
    REM module's own comment). --onefile used to satisfy this for free by
    REM placing the exe directly in the project root; onedir needs this
    REM extra step to preserve the same invariant instead of splitting the
    REM frozen app and the dev/tooling scripts onto two different DBs.
    if exist _internal rmdir /S /Q _internal
    move /Y CraftMap\CraftMap.exe . >nul
    move /Y CraftMap\_internal . >nul
    rmdir /S /Q CraftMap
    echo Done! CraftMap.exe updated.
) else (
    echo Build failed.
)
pause
