# Student Deployment Scripts

This directory stores the student-side deployment scripts that are copied to the NAS root:

- `Start_Client.bat`: launcher used by student desktop shortcuts. It checks the NAS, self-updates from the NAS root, verifies `ComfyUI-Custom-Batchbox` against the NAS copy, mirrors the plugin when needed, then starts ComfyUI.
- `Deploy_Install.bat`: first-time or repair install script. It copies the portable ComfyUI bundle from NAS to `C:\ComfyUI_Portable`, installs the local launcher, and creates the desktop shortcut.
- `Uninstall.bat`: local cleanup script for removing `C:\ComfyUI_Portable` and the desktop shortcut before a reinstall.

## NAS Placement

Copy these files to:

```text
Z:\ComfyUI_Master\Start_Client.bat
Z:\ComfyUI_Master\Deploy_Install.bat
Z:\ComfyUI_Master\Uninstall.bat
```

Student machines may map the same NAS as another drive letter, such as `P:`. Both scripts auto-detect mapped drives by checking for:

```text
ComfyUI_Master\ComfyUI_windows_portable
```

## BatchBox Sync Policy

`Start_Client.bat` does not try to kill running Python or ComfyUI processes. It compares the local BatchBox plugin against the NAS copy first:

- If every file matches by relative path, size, and modified time, it starts ComfyUI immediately.
- If anything differs, it runs `robocopy /MIR` for `ComfyUI-Custom-Batchbox`, which also removes local extra files.
- If `.pyd` files are locked and cannot be mirrored, startup stops and the user should reboot, then run the launcher again.
