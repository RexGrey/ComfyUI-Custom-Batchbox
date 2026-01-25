"""
ComfyUI-Custom-Batchbox

A ComfyUI custom node package for dynamic AI image generation 
with multi-provider support.
"""

from .nodes import (
    NanoBananaPro,
    DynamicImageGenerationNode,
    DynamicTextGenerationNode,
    DynamicVideoGenerationNode,
    DynamicAudioGenerationNode,
    DynamicImageEditorNode,
    create_dynamic_node
)
from .config_manager import config_manager

# ==========================================
# 1. Base Node Mappings
# ==========================================
NODE_CLASS_MAPPINGS = {
    # Legacy/Universal
    "NanoBananaPro": NanoBananaPro,
    # Category-specific dynamic nodes
    "DynamicImageGeneration": DynamicImageGenerationNode,
    "DynamicTextGeneration": DynamicTextGenerationNode,
    "DynamicVideoGeneration": DynamicVideoGenerationNode,
    "DynamicAudioGeneration": DynamicAudioGenerationNode,
    "DynamicImageEditor": DynamicImageEditorNode,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "NanoBananaPro": "🍌 Nano Banana Pro (Universal)",
    "DynamicImageGeneration": "🎨 Dynamic Image Generation",
    "DynamicTextGeneration": "📝 Dynamic Text Generation",
    "DynamicVideoGeneration": "🎬 Dynamic Video Generation",
    "DynamicAudioGeneration": "🎵 Dynamic Audio Generation (Beta)",
    "DynamicImageEditor": "🔧 Dynamic Image Editor",
}

# ==========================================
# 2. Dynamic Node Registration
# ==========================================
try:
    config_manager.load_config()
    
    # Register dynamic nodes from config
    models = config_manager.get_models()
    raw_config = config_manager.get_raw_config()
    
    for model_name in models:
        model_config = raw_config.get("models", {}).get(model_name, {})
        
        # Check if model has dynamic_node definition (legacy support)
        if "dynamic_node" in model_config:
            cls_name, disp_name, cls_obj = create_dynamic_node(
                model_name, 
                model_config["dynamic_node"]
            )
            NODE_CLASS_MAPPINGS[cls_name] = cls_obj
            NODE_DISPLAY_NAME_MAPPINGS[cls_name] = disp_name
            print(f"[ComfyUI-Custom-Batchbox] Registered dynamic node: {disp_name}")

except Exception as e:
    print(f"[ComfyUI-Custom-Batchbox] Error loading dynamic nodes: {e}")

# ==========================================
# 3. Web Directory for Frontend Extensions
# ==========================================
WEB_DIRECTORY = "./web"

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "WEB_DIRECTORY"]

# ==========================================
# 4. API Endpoints for Configuration Management
# ==========================================
try:
    import server
    from aiohttp import web

    @server.PromptServer.instance.routes.get("/api/batchbox/config")
    async def get_config(request):
        """Get full configuration"""
        try:
            data = config_manager.get_raw_config()
            return web.json_response(data)
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    @server.PromptServer.instance.routes.post("/api/batchbox/config")
    async def save_config(request):
        """Save full configuration"""
        try:
            data = await request.json()
            config_manager.save_config_data(data)
            return web.json_response({"status": "success"})
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    @server.PromptServer.instance.routes.get("/api/batchbox/models")
    async def get_models(request):
        """Get all available models"""
        try:
            category = request.query.get("category")
            if category:
                models = config_manager.get_models_by_category(category)
            else:
                models = []
                for model_name in config_manager.get_models():
                    model_config = config_manager.get_model_config(model_name)
                    if model_config:
                        models.append({
                            "name": model_name,
                            "display_name": model_config.get("display_name", model_name),
                            "category": model_config.get("category", "unknown"),
                            "description": model_config.get("description", "")
                        })
            return web.json_response({"models": models})
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    @server.PromptServer.instance.routes.get("/api/batchbox/schema/{model_name}")
    async def get_model_schema(request):
        """Get parameter schema for a specific model"""
        try:
            model_name = request.match_info["model_name"]
            schema = config_manager.get_parameter_schema(model_name)
            
            if schema is None:
                return web.json_response(
                    {"error": f"Model '{model_name}' not found"}, 
                    status=404
                )
            
            # Get model config for additional settings
            model_config = config_manager.get_model_config(model_name)
            
            # Support both new format (dynamic_inputs) and legacy (max_image_inputs)
            dynamic_inputs = model_config.get("dynamic_inputs") if model_config else None
            max_image_inputs = model_config.get("max_image_inputs", 1) if model_config else 1
            
            # Also return flattened version for easier frontend processing
            flat_schema = config_manager.get_parameter_schema_flat(model_name)
            
            # Get show_seed_widget setting (default to True if not set)
            show_seed_widget = model_config.get("show_seed_widget", True) if model_config else True
            
            # Get api_endpoints for manual endpoint selection
            api_endpoints = model_config.get("api_endpoints", []) if model_config else []
            # Build endpoint options with display names
            endpoint_options = []
            for ep in api_endpoints:
                name = ep.get("display_name") or ep.get("provider", f"端点{len(endpoint_options)+1}")
                endpoint_options.append({
                    "name": name,
                    "provider": ep.get("provider"),
                    "priority": ep.get("priority", 1)
                })
            
            return web.json_response({
                "model": model_name,
                "schema": schema,
                "flat_schema": flat_schema,
                "dynamic_inputs": dynamic_inputs,
                "max_image_inputs": max_image_inputs,  # Legacy support
                "show_seed_widget": show_seed_widget,
                "endpoint_options": endpoint_options
            })
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    @server.PromptServer.instance.routes.get("/api/batchbox/providers")
    async def get_providers(request):
        """Get all configured providers"""
        try:
            providers = []
            for name in config_manager.get_providers():
                provider = config_manager.get_provider_config(name)
                if provider:
                    providers.append({
                        "name": provider.name,
                        "display_name": provider.display_name,
                        "base_url": provider.base_url,
                        "has_api_key": bool(provider.api_key),
                        "rate_limit": provider.rate_limit
                    })
            return web.json_response({"providers": providers})
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    @server.PromptServer.instance.routes.post("/api/batchbox/providers/{provider_name}")
    async def update_provider(request):
        """Update a provider's configuration"""
        try:
            provider_name = request.match_info["provider_name"]
            data = await request.json()
            config_manager.update_provider(provider_name, data)
            return web.json_response({"status": "success"})
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    @server.PromptServer.instance.routes.get("/api/batchbox/categories")
    async def get_categories(request):
        """Get all node categories"""
        try:
            categories = config_manager.get_categories()
            return web.json_response({"categories": categories})
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    @server.PromptServer.instance.routes.post("/api/batchbox/reload")
    async def reload_config(request):
        """Force reload configuration from disk"""
        try:
            success = config_manager.force_reload()
            return web.json_response({
                "success": success,
                "mtime": config_manager.get_config_mtime()
            })
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    @server.PromptServer.instance.routes.get("/api/batchbox/config/mtime")
    async def get_config_mtime(request):
        """Get config file modification time for hot reload check"""
        try:
            since = request.rel_url.query.get("since")
            mtime = config_manager.get_config_mtime()
            
            result = {"mtime": mtime}
            if since:
                try:
                    result["changed"] = config_manager.config_changed_since(float(since))
                except ValueError:
                    pass
            
            return web.json_response(result)
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    @server.PromptServer.instance.routes.get("/api/batchbox/save-settings")
    async def get_save_settings(request):
        """Get save settings for auto-save feature"""
        try:
            settings = config_manager.get_save_settings()
            return web.json_response({"save_settings": settings})
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    @server.PromptServer.instance.routes.post("/api/batchbox/save-settings")
    async def update_save_settings(request):
        """Update save settings"""
        try:
            data = await request.json()
            success = config_manager.update_save_settings(data)
            if success:
                return web.json_response({"status": "success", "save_settings": config_manager.get_save_settings()})
            else:
                return web.json_response({"error": "Failed to save settings"}, status=500)
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    @server.PromptServer.instance.routes.post("/api/batchbox/save-settings/preview")
    async def preview_save_filename(request):
        """Preview generated filename based on current settings and sample context"""
        try:
            from .save_settings import SaveSettings
            data = await request.json()
            settings = data.get("settings", config_manager.get_save_settings())
            context = data.get("context", None)
            
            saver = SaveSettings(settings)
            preview = saver.preview_filename(context)
            
            return web.json_response({"preview": preview})
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    @server.PromptServer.instance.routes.get("/api/batchbox/model-order/{category}")
    async def get_model_order(request):
        """Get the configured order of models for a category"""
        try:
            category = request.match_info["category"]
            order = config_manager.get_model_order(category)
            return web.json_response({"order": order})
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    @server.PromptServer.instance.routes.post("/api/batchbox/model-order/{category}")
    async def set_model_order(request):
        """Set the order of models for a category"""
        try:
            category = request.match_info["category"]
            data = await request.json()
            order = data.get("order", [])
            config_manager.set_model_order(category, order)
            return web.json_response({"success": True})
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    @server.PromptServer.instance.routes.get("/api/batchbox/node-settings")
    async def get_node_settings(request):
        """Get node display settings (e.g., default_width)"""
        try:
            settings = config_manager.get_node_settings()
            return web.json_response({"node_settings": settings})
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    @server.PromptServer.instance.routes.post("/api/batchbox/node-settings")
    async def update_node_settings(request):
        """Update node display settings"""
        try:
            data = await request.json()
            success = config_manager.update_node_settings(data)
            if success:
                return web.json_response({"success": True, "node_settings": config_manager.get_node_settings()})
            else:
                return web.json_response({"error": "Failed to save settings"}, status=500)
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    print("[ComfyUI-Custom-Batchbox] API endpoints registered")

except Exception as e:
    print(f"[ComfyUI-Custom-Batchbox] Warning: Could not register API endpoints: {e}")
