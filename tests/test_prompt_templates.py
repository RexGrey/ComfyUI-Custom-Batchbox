"""
Tests for prompt_templates.py

Covers: get_template(), template registries, template content validation.
"""

from prompt_templates import (
    get_template,
    GEMINI_TEMPLATES,
    SEEDREAM_TEMPLATES,
    ALL_TEMPLATES,
)


class TestGetTemplate:

    def test_gemini_depth_map_with_ref(self):
        t = get_template("gemini", "depth_map_with_ref")
        assert len(t) > 0
        assert "Depth Map" in t

    def test_seedream_smart_repair(self):
        t = get_template("seedream", "smart_repair")
        assert len(t) > 0
        # Contains Chinese content
        assert "场景" in t

    def test_unknown_model_type(self):
        assert get_template("unknown_type", "depth_map_with_ref") == ""

    def test_unknown_template_key(self):
        assert get_template("gemini", "nonexistent_key") == ""


class TestTemplateRegistry:

    def test_all_templates_has_gemini_and_seedream(self):
        assert set(ALL_TEMPLATES.keys()) == {"gemini", "seedream"}

    def test_gemini_templates_count(self):
        assert len(GEMINI_TEMPLATES) == 9

    def test_seedream_templates_count(self):
        assert len(SEEDREAM_TEMPLATES) == 9

    def test_matching_keys(self):
        assert set(GEMINI_TEMPLATES.keys()) == set(SEEDREAM_TEMPLATES.keys())

    def test_all_templates_are_nonempty_strings(self):
        for model_type, templates in ALL_TEMPLATES.items():
            for key, value in templates.items():
                assert isinstance(value, str), f"{model_type}.{key} is not a string"
                assert len(value) > 0, f"{model_type}.{key} is empty"
