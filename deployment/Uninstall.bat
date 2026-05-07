@echo off

echo ======================================
echo    ComfyUI Portable - Uninstall
echo ======================================
echo.

set LOCAL_DIR=C:\ComfyUI_Portable
set DESKTOP_LNK=%USERPROFILE%\Desktop\ComfyUI.lnk

echo WARNING: This will delete the following:
echo   - Folder: %LOCAL_DIR%
echo   - Shortcut: %DESKTOP_LNK%
echo.
echo Press any key to continue, or close this window to cancel...
pause >nul

echo.
echo Removing desktop shortcut...
if exist "%DESKTOP_LNK%" (
    del "%DESKTOP_LNK%"
    echo Shortcut removed.
) else (
    echo Shortcut not found, skipping.
)

echo.
echo Removing ComfyUI folder...
if exist "%LOCAL_DIR%" (
    rmdir /s /q "%LOCAL_DIR%"
    echo Folder removed.
) else (
    echo Folder not found, skipping.
)

echo.
echo ======================================
echo    Uninstall Complete!
echo ======================================
echo.
echo You can now run Deploy_Install.bat to reinstall.
echo.
pause
