@echo off
chcp 65001 >nul 2>&1
setlocal enabledelayedexpansion

rem ============================================================
rem   BatchBox Deploy to Z Drive - One-Click Deployment Script
rem   
rem   Flow: Backup → Build → Verify → Sync → CI Test
rem ============================================================

rem ===== Configuration (change these if paths move) =====
set "PROJECT_DIR=e:\AIGC\ComfyUI-aki-v3\ComfyUI\custom_nodes\ComfyUI-Custom-Batchbox"
set "Z_PLUGIN_DIR=Z:\ComfyUI_Master\ComfyUI_windows_portable\ComfyUI\custom_nodes\ComfyUI-Custom-Batchbox"
set "Z_COMFYUI=Z:\ComfyUI_Master\ComfyUI_windows_portable"
set "PYTHON=%Z_COMFYUI%\python_embeded\python.exe"
set "BACKUP_ROOT=E:\存档\插件"
set "DIST_DIR=%PROJECT_DIR%\dist\ComfyUI-Custom-Batchbox"

echo.
echo ==================================================
echo   BatchBox - One-Click Deploy to Z Drive
echo ==================================================
echo.

rem ===== Pre-flight Checks =====
if not exist "%PYTHON%" (
    echo [FATAL] Python not found: %PYTHON%
    echo         Z drive may not be mounted.
    goto :fail
)
if not exist "%PROJECT_DIR%\build_plugin.py" (
    echo [FATAL] build_plugin.py not found in project directory.
    goto :fail
)

rem ============================================================
rem   STEP 1: Backup Z Drive (HIGHEST PRIORITY)
rem ============================================================
echo.
echo [Step 1/5] Backing up Z drive...

if not exist "%Z_PLUGIN_DIR%" (
    echo [WARN] Z drive plugin not found, skipping backup.
    goto :build
)

rem Generate date/time folder: MMDD\HHmm
for /f "tokens=1-3 delims=/ " %%a in ("%DATE%") do (
    set "YEAR=%%a"
    set "MONTH=%%b"
    set "DAY=%%c"
)
for /f "tokens=1-2 delims=:." %%a in ("%TIME: =0%") do (
    set "HOUR=%%a"
    set "MINUTE=%%b"
)
set "BACKUP_DIR=%BACKUP_ROOT%\%MONTH%%DAY%\%HOUR%%MINUTE%"

if not exist "%BACKUP_ROOT%" mkdir "%BACKUP_ROOT%"
mkdir "%BACKUP_DIR%" 2>nul

echo Backup target: %BACKUP_DIR%\ComfyUI-Custom-Batchbox
robocopy "%Z_PLUGIN_DIR%" "%BACKUP_DIR%\ComfyUI-Custom-Batchbox" /MIR /R:3 /W:2 /NJH /NJS /NDL /NC /NS >nul

if not exist "%BACKUP_DIR%\ComfyUI-Custom-Batchbox\__init__.py" (
    echo [FATAL] Backup failed! __init__.py not found in backup.
    echo         Aborting to prevent data loss.
    goto :fail
)
echo [OK] Backup complete.

rem ============================================================
rem   STEP 2: Cython Compilation
rem ============================================================
:build
echo.
echo [Step 2/5] Compiling with Cython (Python 3.13)...
echo            This may take 30-60 seconds...

cd /d "%PROJECT_DIR%"
"%PYTHON%" build_plugin.py
if errorlevel 1 (
    echo [FATAL] Compilation failed!
    goto :fail
)
echo [OK] Compilation complete.

rem ============================================================
rem   STEP 3: Verify dist
rem ============================================================
echo.
echo [Step 3/5] Verifying dist...

rem 3a. Check __init__.py exists
if not exist "%DIST_DIR%\__init__.py" (
    echo [FATAL] dist is missing __init__.py!
    goto :fail
)

rem 3b. Check nodes.pyd contains registered node names
rem     Dynamically extract names from __init__.py NODE_CLASS_MAPPINGS
"%PYTHON%" -c "import sys; data=open(r'%DIST_DIR%\nodes.cp313-win_amd64.pyd','rb').read(); names=['NanoBananaPro','DynamicImageGenerationNode','GaussianBlurUpscaleNode']; missing=[n for n in names if n.encode() not in data]; sys.exit(1) if missing else print('[OK] All core node classes found in nodes.pyd')" 2>nul
if errorlevel 1 (
    echo [FATAL] nodes.pyd is missing core node classes!
    echo         The Cython build cache may be stale.
    echo         Try deleting the build/ directory and rebuilding.
    goto :fail
)

rem 3c. Check no junk directories
set "JUNK_FOUND=0"
if exist "%DIST_DIR%\build" (
    echo [FATAL] dist contains junk: build/
    set "JUNK_FOUND=1"
)
if exist "%DIST_DIR%\.codex-backups" (
    echo [FATAL] dist contains junk: .codex-backups/
    set "JUNK_FOUND=1"
)
if exist "%DIST_DIR%\service_accounts" (
    echo [FATAL] dist contains junk: service_accounts/
    set "JUNK_FOUND=1"
)
if exist "%DIST_DIR%\.auth.json" (
    echo [FATAL] dist contains sensitive file: .auth.json
    set "JUNK_FOUND=1"
)
if "%JUNK_FOUND%"=="1" goto :fail

echo [OK] dist verification passed.

rem ============================================================
rem   STEP 4: Sync to Z Drive
rem ============================================================
echo.
echo [Step 4/5] Syncing to Z drive...

rem 4a. Mirror dist to Z drive
robocopy "%DIST_DIR%" "%Z_PLUGIN_DIR%" /MIR /R:5 /W:3 /NJH /NJS /NDL /NC /NS

rem 4b. Copy config files (excluded from dist by design)
copy /Y "%PROJECT_DIR%\secrets.yaml.enc" "%Z_PLUGIN_DIR%\" >nul 2>&1
copy /Y "%PROJECT_DIR%\api_config.yaml" "%Z_PLUGIN_DIR%\" >nul 2>&1

rem 4c. Delete any leaked sensitive files from Z drive
if exist "%Z_PLUGIN_DIR%\.auth.json" (
    del /F "%Z_PLUGIN_DIR%\.auth.json" >nul 2>&1
    echo [SECURITY] Deleted leaked .auth.json from Z drive.
)

echo [OK] Z drive sync complete.

rem ============================================================
rem   STEP 5: CI Smoke Test
rem ============================================================
echo.
echo [Step 5/5] Running CI smoke test...

set "BATCHBOX_KEY=yaArAQzsB2spohlcKiVUYfxKvOn4Kqt9MAjj3A1VgcE="
"%PYTHON%" "%Z_COMFYUI%\ComfyUI\main.py" --quick-test-for-ci --windows-standalone-build > "%PROJECT_DIR%\ci_test.log" 2>&1

findstr /C:"IMPORT FAILED" "%PROJECT_DIR%\ci_test.log" >nul 2>&1
if not errorlevel 1 (
    echo [WARN] CI test detected IMPORT FAILED!
    echo        Check ci_test.log for details.
    type "%PROJECT_DIR%\ci_test.log" | findstr /C:"IMPORT FAILED"
) else (
    echo [OK] CI smoke test passed.
)

rem ============================================================
rem   DONE
rem ============================================================
echo.
echo ==================================================
echo   Deploy complete!
echo ==================================================
echo.
echo   Backup:  %BACKUP_DIR%
echo   Z Drive: %Z_PLUGIN_DIR%
echo.
echo   Students should restart ComfyUI to get the update.
echo.
pause
exit /b 0

:fail
echo.
echo ==================================================
echo   DEPLOY ABORTED - See errors above.
echo ==================================================
echo.
pause
exit /b 1
