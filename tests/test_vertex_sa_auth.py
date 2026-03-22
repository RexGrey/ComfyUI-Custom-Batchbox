"""
Tests for vertex_sa_auth.py
"""

import json
import os
import importlib
from pathlib import Path
from unittest.mock import patch


_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_pkg = os.path.basename(_project_root)
_mod = importlib.import_module(f"{_pkg}.vertex_sa_auth")


class TestGetRandomSAToken:

    def test_service_account_files_extracts_project_id_from_json(self, tmp_path):
        json_path = Path(tmp_path) / "sa.json"
        json_path.write_text(json.dumps({"project_id": "proj-123"}), encoding="utf-8")

        provider = {
            "service_account_files": [
                {"name": "sa-1", "json": str(json_path)},
            ]
        }

        with patch.object(_mod, "get_access_token", return_value="token-abc"):
            token, project_id, sa_name = _mod.get_random_sa_token(provider)

        assert token == "token-abc"
        assert project_id == "proj-123"
        assert sa_name == "sa-1"
