"""
Tests for adapters/template_engine.py

Covers: TemplateEngine.render() with string/dict/list,
        _build_chat_content, _get_mapped_value, extract_variables.
"""

from adapters.template_engine import TemplateEngine


# ──────────────────────────────────────────────────────────────────────────────
# render
# ──────────────────────────────────────────────────────────────────────────────

class TestRender:

    def test_string_simple_substitution(self):
        e = TemplateEngine()
        result = e.render("Hello {{name}}", {"name": "World"})
        assert result == "Hello World"

    def test_string_full_variable_preserves_type(self):
        e = TemplateEngine()
        result = e.render("{{count}}", {"count": 42})
        assert result == 42
        assert isinstance(result, int)

    def test_string_full_variable_list(self):
        e = TemplateEngine()
        data = [1, 2, 3]
        result = e.render("{{items}}", {"items": data})
        assert result == data

    def test_string_mixed_keeps_string(self):
        e = TemplateEngine()
        result = e.render("val={{count}}", {"count": 42})
        assert result == "val=42"
        assert isinstance(result, str)

    def test_dict_rendering(self):
        e = TemplateEngine()
        template = {
            "prompt": "{{prompt}}",
            "settings": {"size": "{{size}}"},
        }
        result = e.render(template, {"prompt": "Test", "size": "1024x1024"})
        assert result["prompt"] == "Test"
        assert result["settings"]["size"] == "1024x1024"

    def test_list_rendering(self):
        e = TemplateEngine()
        template = ["{{a}}", "{{b}}"]
        result = e.render(template, {"a": "x", "b": "y"})
        assert result == ["x", "y"]

    def test_primitive_passthrough(self):
        e = TemplateEngine()
        assert e.render(42, {}) == 42
        assert e.render(True, {}) is True
        assert e.render(None, {}) is None

    def test_missing_variable_full(self):
        e = TemplateEngine()
        result = e.render("{{missing}}", {})
        assert result == ""

    def test_missing_variable_in_string(self):
        e = TemplateEngine()
        result = e.render("Hello {{missing}} world", {})
        assert result == "Hello  world"


# ──────────────────────────────────────────────────────────────────────────────
# _build_chat_content
# ──────────────────────────────────────────────────────────────────────────────

class TestBuildChatContent:

    def test_with_prompt_only(self):
        e = TemplateEngine()
        result = e.render("{{_chat_content}}", {"prompt": "hello"})
        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["type"] == "text"
        assert result[0]["text"] == "hello"

    def test_with_prompt_and_images(self):
        e = TemplateEngine()
        params = {
            "prompt": "describe",
            "_images_base64": ["data:image/png;base64,abc"],
        }
        result = e.render("{{_chat_content}}", params)
        assert len(result) == 2
        assert result[0]["type"] == "text"
        assert result[1]["type"] == "image_url"
        assert result[1]["image_url"]["url"] == "data:image/png;base64,abc"

    def test_empty_prompt_no_text_entry(self):
        e = TemplateEngine()
        params = {"prompt": "", "_images_base64": ["data:image/png;base64,abc"]}
        result = e.render("{{_chat_content}}", params)
        # Empty prompt → no text entry
        assert len(result) == 1
        assert result[0]["type"] == "image_url"

    def test_no_images(self):
        e = TemplateEngine()
        result = e.render("{{_chat_content}}", {"prompt": "hi"})
        assert len(result) == 1


# ──────────────────────────────────────────────────────────────────────────────
# _get_mapped_value
# ──────────────────────────────────────────────────────────────────────────────

class TestGetMappedValue:

    def test_map_size(self):
        e = TemplateEngine(value_mappings={
            "_map_size": {"2K": "1792x1024", "1K": "1024x1024"}
        })
        result = e.render("{{_map_size}}", {"size": "2K"})
        assert result == "1792x1024"

    def test_extract_ratio(self):
        e = TemplateEngine(value_mappings={
            "_extract_ratio": {"16:9": "1792x1024", "1:1": "1024x1024"}
        })
        result = e.render("{{_extract_ratio}}", {"ratio": "16:9"})
        assert result == "1792x1024"

    def test_unmapped_value_returns_source(self):
        e = TemplateEngine(value_mappings={
            "_map_size": {"2K": "1792x1024"}
        })
        result = e.render("{{_map_size}}", {"size": "4K"})
        # 4K not in mapping → returns the source value "4K"
        assert result == "4K"

    def test_no_matching_mapping(self):
        e = TemplateEngine()
        # _get_mapped_value returns None, but _render_string converts None → ""
        result = e.render("{{_map_unknown}}", {"size": "2K"})
        assert result == ""


# ──────────────────────────────────────────────────────────────────────────────
# extract_variables
# ──────────────────────────────────────────────────────────────────────────────

class TestExtractVariables:

    def test_from_string(self):
        v = TemplateEngine.extract_variables("{{prompt}} at {{size}}")
        assert v == {"prompt", "size"}

    def test_from_nested_dict(self):
        template = {
            "body": {"text": "{{prompt}}"},
            "model": "{{model_name}}",
        }
        v = TemplateEngine.extract_variables(template)
        assert v == {"prompt", "model_name"}

    def test_from_list(self):
        v = TemplateEngine.extract_variables(["{{a}}", "static", "{{b}}"])
        assert v == {"a", "b"}

    def test_no_variables(self):
        v = TemplateEngine.extract_variables("no variables here")
        assert v == set()

    def test_primitive_returns_empty(self):
        assert TemplateEngine.extract_variables(42) == set()
