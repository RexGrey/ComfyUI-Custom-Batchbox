# Encrypted Compilation Security Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the manual Z-drive castration deployment with a single codebase that dynamically hides keys via `is_encrypted_mode()` and compiles Python to `.pyd` binaries.

**Architecture:** We will build a Cython compile chain (`build_plugin.py`) and enhance `config_manager`, `__init__`, and `api_manager.js` to self-truncate sensitive info when only `.enc` keys are present.

**Tech Stack:** Python 3.11, Cython, JavaScript

---

### Task 1: Add `is_encrypted_mode` to `config_manager`

**Files:**
- Modify: `config_manager.py`
- Modify: `tests/test_api_endpoints.py` (Add mock test for mode check)

- [x] **Step 1: Write the failing test**
```python
def test_is_encrypted_mode(self):
    from unittest.mock import patch
    import os
    with patch('os.path.exists') as mock_exists:
        # If secrets.yaml exists -> False
        mock_exists.side_effect = lambda p: True if p.endswith('secrets.yaml') else False
        self.assertFalse(self.config_manager.is_encrypted_mode())
        
        # If only secrets.yaml.enc exists -> True
        mock_exists.side_effect = lambda p: p.endswith('.enc')
        self.assertTrue(self.config_manager.is_encrypted_mode())
```

- [x] **Step 2: Run test to verify it fails**
Run: `pytest tests/test_api_endpoints.py::TestAPIEndpoints::test_is_encrypted_mode`
Expected: FAIL (AttributeError)

- [x] **Step 3: Write minimal implementation**
```python
def is_encrypted_mode(self) -> bool:
    """Check if plugin is running in strictly encrypted mode (Z-drive)."""
    import os
    return (not os.path.exists(self.secrets_path) 
            and os.path.exists(self.secrets_enc_path))
```

- [x] **Step 4: Run test to verify it passes**
Run: `pytest tests/test_api_endpoints.py::TestAPIEndpoints`
Expected: PASS

- [x] **Step 5: Commit**
```bash
git add config_manager.py tests/test_api_endpoints.py
git commit -m "feat(security): add is_encrypted_mode to config detection"
```

---

### Task 2: Backend API Masking and Protect Endpoints

**Files:**
- Modify: `__init__.py`

- [x] **Step 1: Write minimal implementation for GET /api/batchbox/mode**
Add the new `/api/batchbox/mode` endpoint.

- [x] **Step 2: Write minimal implementation for masking API configs**
Add `_mask_secrets(config: dict) -> dict` and use it inside `get_config`. 

- [x] **Step 3: Add `save_config` POST protection**
Return 403 if `is_encrypted_mode()`.

- [x] **Step 4: Commit**
```bash
git add __init__.py tests/test_api_endpoints.py
git commit -m "feat(security): mask secrets and lock endpoints in encrypted mode"
```

---

### Task 3: Frontend Adaptive UI (Read-Only Mode)

**Files:**
- Modify: `web/api_manager.js`

- [x] **Step 1: Write minimal implementation**
Modify `web/api_manager.js` to fetch `/api/batchbox/mode` and set a `this.isReadOnly` flag. Hide "+ 添加" buttons, actions columns, and the Save button when true.

- [x] **Step 2: Testing**
Refresh ComfyUI interface to ensure JS catches the backend state without console errors.

- [x] **Step 3: Commit**
```bash
git add web/api_manager.js
git commit -m "feat(ui): implement adaptive read-only mode"
```

---

### Task 4: Cython Build Toolchain (.pyd Compiler)

**Files:**
- Create: `build_plugin.py`
- Create: `setup_build.py`

- [x] **Step 1: Write Cython Build Scripts**
Create `setup_build.py` using `Cython.Build.cythonize`. 
Create `build_plugin.py` to copy all Python files, compile them to `.pyd`, and package `dist/ComfyUI-Custom-Batchbox`.

- [x] **Step 2: Execute Trial Build**
Run: `python build_plugin.py`
Expected: Complete generation of `dist/` without any sensitive `.py` leaking.
*Status: Successfully generated `.pyd` binaries in `dist/ComfyUI-Custom-Batchbox` via MSVC C++ Build Tools.*

- [x] **Step 3: Commit**
```bash
git add build_plugin.py setup_build.py
git commit -m "build(compile): create Cython CI pipeline to build protected .pyd binaries"
```
