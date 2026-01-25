"""
Unit tests for the ComfyUI-Custom-Batchbox package

This module contains comprehensive tests for:
- ConfigManager (api_config.yaml parsing and management)
- Adapters (API adapter functionality)
- TemplateEngine (payload template rendering)
"""

import unittest
import os
import sys
import tempfile
import yaml

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config_manager import ConfigManager, ProviderConfig


class TestConfigManager(unittest.TestCase):
    """Tests for ConfigManager class"""
    
    def setUp(self):
        """Set up test fixtures"""
        # Create a temporary config file for testing
        self.temp_dir = tempfile.mkdtemp()
        self.temp_config_path = os.path.join(self.temp_dir, "api_config.yaml")
        
        self.sample_config = {
            "providers": {
                "test_provider": {
                    "base_url": "https://api.test.com",
                    "api_key": "test-key-123"
                }
            },
            "node_categories": {
                "image": {
                    "display_name": "图片",
                    "icon": "🖼️",
                    "enabled": True
                }
            },
            "models": {
                "test_model": {
                    "display_name": "Test Model",
                    "category": "image",
                    "description": "A test model",
                    "parameter_schema": {
                        "basic": {
                            "prompt": {"type": "string", "default": ""},
                            "style": {"type": "select", "default": "realistic", 
                                     "options": [{"value": "realistic", "label": "写实风格"}]}
                        },
                        "advanced": {
                            "upscale": {"type": "select", "default": "1x", 
                                       "options": [{"value": "1x", "label": "1x"}]}
                        }
                    },
                    "api_endpoints": [
                        {
                            "provider": "test_provider",
                            "priority": 1,
                            "modes": {
                                "text2img": {
                                    "endpoint": "/v1/images/generations",
                                    "method": "POST",
                                    "content_type": "application/json"
                                },
                                "img2img": {
                                    "endpoint": "/v1/images/edits",
                                    "method": "POST",
                                    "content_type": "multipart/form-data"
                                }
                            }
                        }
                    ]
                }
            },
            "settings": {
                "default_timeout": 600,
                "max_retries": 3,
                "auto_failover": True
            }
        }
        
        with open(self.temp_config_path, 'w', encoding='utf-8') as f:
            yaml.dump(self.sample_config, f)
    
    def tearDown(self):
        """Clean up temporary files"""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def test_load_config(self):
        """Test that config loads correctly"""
        manager = ConfigManager(self.temp_config_path)
        manager.load_config()
        self.assertIsNotNone(manager._config)
    
    def test_get_providers(self):
        """Test retrieving providers"""
        manager = ConfigManager(self.temp_config_path)
        providers = manager.get_providers()
        self.assertIn("test_provider", providers)
    
    def test_get_provider_config(self):
        """Test getting a specific provider config"""
        manager = ConfigManager(self.temp_config_path)
        provider = manager.get_provider_config("test_provider")
        
        self.assertIsNotNone(provider)
        self.assertEqual(provider.name, "test_provider")
        self.assertEqual(provider.base_url, "https://api.test.com")
        self.assertEqual(provider.api_key, "test-key-123")
    
    def test_get_models(self):
        """Test retrieving models list"""
        manager = ConfigManager(self.temp_config_path)
        models = manager.get_models()
        self.assertIn("test_model", models)
    
    def test_get_models_by_category(self):
        """Test filtering models by category"""
        manager = ConfigManager(self.temp_config_path)
        image_models = manager.get_models("image")
        self.assertIn("test_model", image_models)
        
        video_models = manager.get_models("video")
        self.assertEqual(len(video_models), 0)
    
    def test_get_model_config(self):
        """Test getting full model config"""
        manager = ConfigManager(self.temp_config_path)
        config = manager.get_model_config("test_model")
        
        self.assertIsNotNone(config)
        self.assertEqual(config["display_name"], "Test Model")
        self.assertEqual(config["category"], "image")
    
    def test_get_parameter_schema(self):
        """Test getting parameter schema"""
        manager = ConfigManager(self.temp_config_path)
        schema = manager.get_parameter_schema("test_model")
        
        self.assertIn("basic", schema)
        self.assertIn("advanced", schema)
        self.assertIn("prompt", schema["basic"])
    
    def test_get_parameter_schema_flat(self):
        """Test getting flattened parameter schema"""
        manager = ConfigManager(self.temp_config_path)
        flat_schema = manager.get_parameter_schema_flat("test_model")
        
        self.assertIsInstance(flat_schema, list)
        param_names = [p["name"] for p in flat_schema]
        self.assertIn("prompt", param_names)
        self.assertIn("style", param_names)
    
    def test_get_best_endpoint(self):
        """Test getting best endpoint for a mode"""
        manager = ConfigManager(self.temp_config_path)
        
        endpoint = manager.get_best_endpoint("test_model", "text2img")
        self.assertIsNotNone(endpoint)
        self.assertEqual(endpoint["config"]["endpoint"], "/v1/images/generations")
    
    def test_get_best_endpoint_fallback(self):
        """Test endpoint fallback when mode not directly available"""
        # Create config with only text2img endpoint
        config_with_one_mode = self.sample_config.copy()
        config_with_one_mode["models"]["test_model"]["api_endpoints"][0]["modes"] = {
            "text2img": {
                "endpoint": "/v1/images/generations",
                "method": "POST"
            }
        }
        
        with open(self.temp_config_path, 'w', encoding='utf-8') as f:
            yaml.dump(config_with_one_mode, f)
        
        manager = ConfigManager(self.temp_config_path)
        manager._config = None  # Force reload
        
        # Request img2img should fallback to text2img
        endpoint = manager.get_best_endpoint("test_model", "img2img")
        self.assertIsNotNone(endpoint)
        self.assertEqual(endpoint["config"]["endpoint"], "/v1/images/generations")
    
    def test_get_settings(self):
        """Test getting global settings"""
        manager = ConfigManager(self.temp_config_path)
        settings = manager.get_settings()
        
        self.assertEqual(settings["default_timeout"], 600)
        self.assertEqual(settings["max_retries"], 3)
        self.assertTrue(settings["auto_failover"])
    
    def test_nonexistent_model(self):
        """Test handling of nonexistent model"""
        manager = ConfigManager(self.temp_config_path)
        config = manager.get_model_config("nonexistent")
        self.assertIsNone(config)
    
    def test_nonexistent_provider(self):
        """Test handling of nonexistent provider"""
        manager = ConfigManager(self.temp_config_path)
        provider = manager.get_provider_config("nonexistent")
        self.assertIsNone(provider)


class TestTemplateEngine(unittest.TestCase):
    """Tests for TemplateEngine class"""
    
    def setUp(self):
        """Set up test fixtures"""
        from adapters.template_engine import TemplateEngine
        self.engine = TemplateEngine()
    
    def test_simple_substitution(self):
        """Test simple variable substitution"""
        template = {"prompt": "{{prompt}}", "model": "{{model_name}}"}
        params = {"prompt": "A beautiful sunset", "model_name": "test-model"}
        
        result = self.engine.render(template, params)
        
        self.assertEqual(result["prompt"], "A beautiful sunset")
        self.assertEqual(result["model"], "test-model")
    
    def test_nested_template(self):
        """Test nested dictionary template"""
        template = {
            "request": {
                "prompt": "{{prompt}}",
                "settings": {
                    "size": "{{size}}"
                }
            }
        }
        params = {"prompt": "Test", "size": "1024x1024"}
        
        result = self.engine.render(template, params)
        
        self.assertEqual(result["request"]["prompt"], "Test")
        self.assertEqual(result["request"]["settings"]["size"], "1024x1024")
    
    def test_missing_variable(self):
        """Test handling of missing variables"""
        template = {"prompt": "{{prompt}}", "style": "{{style}}"}
        params = {"prompt": "Test"}
        
        result = self.engine.render(template, params)
        
        self.assertEqual(result["prompt"], "Test")
        # Missing variable should be empty string or unchanged
        self.assertIn("style", result)


class TestProviderConfig(unittest.TestCase):
    """Tests for ProviderConfig dataclass"""
    
    def test_provider_config_creation(self):
        """Test creating a ProviderConfig"""
        provider = ProviderConfig(
            name="test",
            base_url="https://api.test.com",
            api_key="sk-test"
        )
        
        self.assertEqual(provider.name, "test")
        self.assertEqual(provider.base_url, "https://api.test.com")
        self.assertEqual(provider.api_key, "sk-test")
    
    def test_provider_config_optional_fields(self):
        """Test ProviderConfig with optional fields"""
        provider = ProviderConfig(
            name="test",
            base_url="https://api.test.com"
        )
        
        self.assertIsNone(provider.api_key)


if __name__ == "__main__":
    # Run tests
    unittest.main(verbosity=2)
