# Sync Z Drive

When the user asks to sync the Z drive, treat it as the secure release workflow used by this repository, not as a plain source mirror.

## Default Meaning

Source workspace:
`E:\AIGC\ComfyUI-aki-v3\ComfyUI\custom_nodes\ComfyUI-Custom-Batchbox`

Target runtime directory:
`Z:\ComfyUI_Master\ComfyUI_windows_portable\ComfyUI\custom_nodes\ComfyUI-Custom-Batchbox`

Target Python used for build:
`Z:\ComfyUI_Master\ComfyUI_windows_portable\python_embeded\python.exe`

Default script:
`sync_to_z.bat`

## Default Workflow

Syncing the Z drive means:

1. Run `build_plugin.py` with the Z-drive embedded Python so the generated `.pyd` files match the target runtime ABI.
2. Sync `dist\ComfyUI-Custom-Batchbox` to the Z-drive plugin directory with `robocopy /MIR`.
3. Copy `secrets.yaml.enc` and `api_config.yaml` from the source workspace to the Z-drive plugin directory.
4. Remove files and folders that must not remain in the Z-drive student runtime.

## Files That Must Not Remain On Z Drive

- `secrets.yaml`
- `.secrets_key`
- `.auth.json`
- `_bench_results.json`

## Directories That Must Not Remain On Z Drive

- `service_accounts`
- `.pytest_cache`
- `build`
- `__pycache__`
- `.git`
- `.worktrees`
- `.agents`
- `docs`
- `tests`

## Operational Notes

- Do not mirror the raw source tree to Z by default.
- The current repository history shows that Z-drive sync was upgraded to use the Cython build pipeline and `dist` deployment.
- `build_plugin.py` currently packages some extra `.json` content into `dist`, so the sync script must explicitly clean sensitive leftovers after deployment.
- If `Z:` is not mounted or the embedded Python is missing, stop and report the failure instead of falling back to a different deployment mode.

## Expected Behavior For Future Requests

If the user only asks to sync the Z drive, do this:

1. Run `sync_to_z.bat`.
2. Report the build result.
3. Report the `robocopy` summary.
4. Report whether cleanup removed any protected files from the Z-drive target.
