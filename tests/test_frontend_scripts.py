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
            r"progressHandler = \(event\) => \{(?P<body>.*?)\n\s*\};\n\s*api\.addEventListener\(\"batchbox:progress\"",
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
        assert "function supportsQueuePromptBypass(node)" in script
        assert 'nodeType !== "GaussianBlurUpscale"' in script
        assert 'nodeData.inputs._bypass_queue_prompt = shouldBypassNode ? "true" : "false";' in script
        assert "window.batchboxAPI = {" in script
        assert "markButtonTriggeredExecution," in script

    def test_blur_queue_fallback_marks_button_triggered_execution(self):
        script = (PROJECT_ROOT / "web" / "blur_upscale.js").read_text(encoding="utf-8")

        assert "window.batchboxAPI?.markButtonTriggeredExecution?.();" in script

    def test_blur_apply_stores_preview_separately_from_final_result_cache(self):
        script = (PROJECT_ROOT / "web" / "blur_upscale.js").read_text(encoding="utf-8")

        assert 'node.properties._blur_preview_images = JSON.stringify(result.preview_images);' in script


class TestQueuePromptExtraParamsSync(unittest.TestCase):
    def test_queue_prompt_syncs_extra_params_for_button_nodes(self):
        script = (PROJECT_ROOT / "web" / "dynamic_params.js").read_text(encoding="utf-8")

        assert 'const extraParamsWidget = node.widgets?.find(w => w.name === "extra_params");' in script
        assert 'nodeData.inputs.extra_params = extraParamsWidget.value || "{}";' in script


class TestGlobalLightboxDomWidgetGuard(unittest.TestCase):
    def test_global_lightbox_ignores_dom_widget_double_clicks(self):
        script = (PROJECT_ROOT / "web" / "dynamic_params.js").read_text(encoding="utf-8")

        assert "function shouldIgnoreGlobalLightboxDblclick" in script
        assert 'const graphSurfaceEl = lgCanvas?.canvas || canvasEl?.querySelector?.("canvas");' in script
        assert "if (shouldIgnoreGlobalLightboxDblclick(e, graphSurfaceEl)) return;" in script
        assert '".p-inputnumber-button"' in script
        assert '".p-inputnumber-input"' in script
        assert '"[role=\'spinbutton\']"' in script

    def test_global_lightbox_uses_canvas_graph_coordinates(self):
        script = (PROJECT_ROOT / "web" / "dynamic_params.js").read_text(encoding="utf-8")

        assert "graphX = canvasX / scale - offsetX;" in script
        assert "graphY = canvasY / scale - offsetY;" in script
        assert "const activeGraph = lgCanvas.graph || app.graph;" in script
        assert "const activeNodes = lgCanvas.visible_nodes || activeGraph?._nodes;" in script
        assert "const node = activeGraph?.getNodeOnPos(graphX, graphY, activeNodes);" in script


class TestBlurUpscaleProgressCleanup(unittest.TestCase):
    def test_progress_listener_removed_in_finally(self):
        script = (PROJECT_ROOT / "web" / "blur_upscale.js").read_text(encoding="utf-8")

        match = re.search(
            r"finally \{(?P<body>.*?)\n\s*\}",
            script,
            re.DOTALL,
        )
        assert match, "finally block not found"
        assert 'api.removeEventListener("batchbox:progress", progressHandler);' in match.group("body")


class TestImageDropDedup(unittest.TestCase):
    def test_image_drop_uses_hash_based_name_resolution_without_overwrite(self):
        script = (PROJECT_ROOT / "web" / "image_drop.js").read_text(encoding="utf-8")

        assert 'formData.append("overwrite", "false");' in script
        assert 'crypto.subtle.digest("SHA-256"' in script
        assert "new File(" in script
        assert "/view?filename=" in script
