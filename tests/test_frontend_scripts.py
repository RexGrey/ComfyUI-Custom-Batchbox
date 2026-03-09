"""
Lightweight guardrails for frontend performance-sensitive script paths.
"""

import re
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class TestBlurUpscaleProgressRefresh:
    def test_progress_handler_uses_coalesced_canvas_refresh(self):
        script = (PROJECT_ROOT / "web" / "blur_upscale.js").read_text(encoding="utf-8")

        assert "function requestNodeCanvasRefresh(node)" in script

        match = re.search(
            r"const progressHandler = \(event\) => \{(?P<body>.*?)\n\s*\};\n\s*api\.addEventListener\(\"batchbox:progress\"",
            script,
            re.DOTALL,
        )

        assert match, "progress handler not found"
        body = match.group("body")
        assert "requestNodeCanvasRefresh(node);" in body
        assert "node.setDirtyCanvas(true, true);" not in body
