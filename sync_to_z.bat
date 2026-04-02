@echo off
setlocal

set "SRC=E:\AIGC\ComfyUI-aki-v3\ComfyUI\custom_nodes\ComfyUI-Custom-Batchbox"
set "DIST=%SRC%\dist\ComfyUI-Custom-Batchbox"
set "DST=Z:\ComfyUI_Master\ComfyUI_windows_portable\ComfyUI\custom_nodes\ComfyUI-Custom-Batchbox"
set "TARGET_PY=Z:\ComfyUI_Master\ComfyUI_windows_portable\python_embeded\python.exe"

echo [BatchBox] Syncing plugin to Z drive using secure build pipeline...
echo [BatchBox] Source: %SRC%
echo [BatchBox] Dist:   %DIST%
echo [BatchBox] Target: %DST%
echo [BatchBox] Python: %TARGET_PY%

if not exist "%SRC%" (
  echo [BatchBox] Source workspace not found.
  exit /b 1
)

if not exist "%TARGET_PY%" (
  echo [BatchBox] Target Python not found on Z drive.
  exit /b 2
)

pushd "%SRC%"
"%TARGET_PY%" build_plugin.py
set "BUILD_RC=%ERRORLEVEL%"
popd

if %BUILD_RC% NEQ 0 (
  echo [BatchBox] Build failed with exit code %BUILD_RC%.
  exit /b %BUILD_RC%
)

if not exist "%DIST%" (
  echo [BatchBox] Dist directory was not produced: %DIST%
  exit /b 3
)

if not exist "%DST%" (
  mkdir "%DST%"
  if errorlevel 1 (
    echo [BatchBox] Failed to create target directory.
    exit /b 4
  )
)

echo [BatchBox] Deploying compiled dist package...
robocopy "%DIST%" "%DST%" /MIR /FFT /R:2 /W:2 /XJ ^
  /XD "service_accounts" ".pytest_cache" "build" "__pycache__" ".git" ".worktrees" ".agents" "docs" "tests" ^
  /XF ".auth.json" "_bench_results.json" "secrets.yaml" ".secrets_key" "fix_null_bytes*.pyd" "list_models*.pyd"

set "RC=%ERRORLEVEL%"
echo [BatchBox] robocopy exit code: %RC%

if %RC% GEQ 8 (
  echo [BatchBox] Dist sync failed.
  exit /b %RC%
)

echo [BatchBox] Copying runtime config files...
copy /Y "%SRC%\secrets.yaml.enc" "%DST%\secrets.yaml.enc" >nul
if errorlevel 1 (
  echo [BatchBox] Failed to copy secrets.yaml.enc
  exit /b 6
)

copy /Y "%SRC%\api_config.yaml" "%DST%\api_config.yaml" >nul
if errorlevel 1 (
  echo [BatchBox] Failed to copy api_config.yaml
  exit /b 7
)

echo [BatchBox] Removing unwanted files and folders from deployed target...
powershell -NoProfile -Command ^
  "$ErrorActionPreference='SilentlyContinue';" ^
  "$dst='%DST%';" ^
  "Remove-Item -LiteralPath (Join-Path $dst '.auth.json') -Force -ErrorAction SilentlyContinue;" ^
  "Remove-Item -LiteralPath (Join-Path $dst 'secrets.yaml') -Force -ErrorAction SilentlyContinue;" ^
  "Remove-Item -LiteralPath (Join-Path $dst '.secrets_key') -Force -ErrorAction SilentlyContinue;" ^
  "Remove-Item -LiteralPath (Join-Path $dst '_bench_results.json') -Force -ErrorAction SilentlyContinue;" ^
  "Get-ChildItem -LiteralPath $dst -Filter 'fix_null_bytes*.pyd' -ErrorAction SilentlyContinue | Remove-Item -Force -ErrorAction SilentlyContinue;" ^
  "Get-ChildItem -LiteralPath $dst -Filter 'list_models*.pyd' -ErrorAction SilentlyContinue | Remove-Item -Force -ErrorAction SilentlyContinue;" ^
  "Remove-Item -LiteralPath (Join-Path $dst 'service_accounts') -Recurse -Force -ErrorAction SilentlyContinue;" ^
  "Remove-Item -LiteralPath (Join-Path $dst '.pytest_cache') -Recurse -Force -ErrorAction SilentlyContinue;" ^
  "Remove-Item -LiteralPath (Join-Path $dst 'build') -Recurse -Force -ErrorAction SilentlyContinue;" ^
  "Remove-Item -LiteralPath (Join-Path $dst '__pycache__') -Recurse -Force -ErrorAction SilentlyContinue;" ^
  "Remove-Item -LiteralPath (Join-Path $dst '.git') -Recurse -Force -ErrorAction SilentlyContinue;" ^
  "Remove-Item -LiteralPath (Join-Path $dst '.worktrees') -Recurse -Force -ErrorAction SilentlyContinue;" ^
  "Remove-Item -LiteralPath (Join-Path $dst '.agents') -Recurse -Force -ErrorAction SilentlyContinue;" ^
  "Remove-Item -LiteralPath (Join-Path $dst 'docs') -Recurse -Force -ErrorAction SilentlyContinue;" ^
  "Remove-Item -LiteralPath (Join-Path $dst 'tests') -Recurse -Force -ErrorAction SilentlyContinue;"

echo [BatchBox] Sync completed.
exit /b 0
