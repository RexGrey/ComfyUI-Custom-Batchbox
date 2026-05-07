@echo off

echo ======================================
echo    ComfyUI Portable - Deployment
echo ======================================
echo.

rem ===== Auto-detect NAS Drive =====
echo Searching for NAS drive...

set NAS_FOLDER=ComfyUI_Master\ComfyUI_windows_portable
set NAS_DRIVE=

for %%d in (Z P N M L K J I H G F E D X W) do (
    if exist "%%d:\%NAS_FOLDER%\" (
        set NAS_DRIVE=%%d:
        goto :found
    )
)

echo ERROR: Cannot find NAS!
echo Searched for: %NAS_FOLDER%
echo Please ensure NAS is mapped and contains the ComfyUI_Master folder.
pause
goto :eof

:found
echo Found NAS at: %NAS_DRIVE%

rem ===== Path Configuration =====
set NAS_SOURCE=%NAS_DRIVE%\ComfyUI_Master\ComfyUI_windows_portable
set NAS_SCRIPTS=%NAS_DRIVE%\ComfyUI_Master
set LOCAL_DIR=C:\ComfyUI_Portable

rem ===== Copy Files =====
echo.
echo Copying ComfyUI to local drive...
echo This may take a few minutes...
echo.

robocopy "%NAS_SOURCE%" "%LOCAL_DIR%" /E /XO /FFT /R:3 /W:1 /NJH /NJS /XD "output" "temp"

if %ERRORLEVEL% GEQ 8 (
    echo ERROR: Copy failed!
    pause
    goto :eof
)
echo Copy complete!

rem ===== Copy Start Script =====
echo.
echo Setting up launcher script...
copy /Y "%NAS_SCRIPTS%\Start_Client.bat" "%LOCAL_DIR%\Start_Client.bat" >nul

rem ===== Create Desktop Shortcut =====
echo Creating desktop shortcut...

set DESKTOP_LNK=%USERPROFILE%\Desktop\ComfyUI.lnk
set TARGET_BAT=%LOCAL_DIR%\Start_Client.bat
set ICON_EXE=%LOCAL_DIR%\ComfyUI.exe

if exist "%ICON_EXE%" (
    powershell -Command "$s=(New-Object -COM WScript.Shell).CreateShortcut('%DESKTOP_LNK%');$s.TargetPath='%TARGET_BAT%';$s.WorkingDirectory='%LOCAL_DIR%';$s.IconLocation='%ICON_EXE%,0';$s.Save()"
) else (
    powershell -Command "$s=(New-Object -COM WScript.Shell).CreateShortcut('%DESKTOP_LNK%');$s.TargetPath='%TARGET_BAT%';$s.WorkingDirectory='%LOCAL_DIR%';$s.Save()"
)

echo.
echo ======================================
echo    Deployment Complete!
echo ======================================
echo.
echo NAS Drive: %NAS_DRIVE%
echo Local folder: %LOCAL_DIR%
echo.
pause
