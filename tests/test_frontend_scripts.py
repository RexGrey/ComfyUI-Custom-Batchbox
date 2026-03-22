"""
Lightweight guardrails for frontend performance-sensitive script paths.
"""

import re
import unittest
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


class TestBlurUpscaleInputPreviewSource(unittest.TestCase):
    def test_custom_preview_uses_linked_input_source_only(self):
        script = (PROJECT_ROOT / "web" / "blur_upscale.js").read_text(encoding="utf-8")

        assert "function getLinkedInputImageUrl(node)" in script

        get_src_match = re.search(
            r"function getInputImageSrc\(node\) \{(?P<body>.*?)\n\}",
            script,
            re.DOTALL,
        )
        assert get_src_match, "getInputImageSrc not found"
        get_src_body = get_src_match.group("body")
        assert "return getLinkedInputImageUrl(node);" in get_src_body
        assert "node.imgs?.length" not in get_src_body

        get_b64_match = re.search(
            r"async function getInputImageBase64\(node\) \{(?P<body>.*?)\n\}",
            script,
            re.DOTALL,
        )
        assert get_b64_match, "getInputImageBase64 not found"
        get_b64_body = get_b64_match.group("body")
        assert "const imageUrl = getLinkedInputImageUrl(node);" in get_b64_body
        assert "node.imgs?.length" not in get_b64_body


class TestQueuePromptBypassPersistence(unittest.TestCase):
    def test_queue_prompt_injects_hard_bypass_for_button_nodes(self):
        script = (PROJECT_ROOT / "web" / "dynamic_params.js").read_text(encoding="utf-8")

        assert "function markButtonTriggeredExecution()" in script
        assert "function isBatchboxButtonNode(node)" in script
        assert 'nodeData.inputs._bypass_queue_prompt = shouldBypassNode ? "true" : "false";' in script
        assert "window.batchboxAPI = {" in script
        assert "markButtonTriggeredExecution," in script

    def test_blur_queue_fallback_marks_button_triggered_execution(self):
        script = (PROJECT_ROOT / "web" / "blur_upscale.js").read_text(encoding="utf-8")

        assert "window.batchboxAPI?.markButtonTriggeredExecution?.();" in script
