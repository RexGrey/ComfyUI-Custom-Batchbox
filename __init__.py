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
    GaussianBlurUpscaleNode,
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
    "GaussianBlurUpscale": GaussianBlurUpscaleNode,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "NanoBananaPro": "🍌 Nano Banana Pro (Universal)",
    "DynamicImageGeneration": "🎨 Dynamic Image Generation",
    "DynamicTextGeneration": "📝 Dynamic Text Generation",
    "DynamicVideoGeneration": "🎬 Dynamic Video Generation",
    "DynamicAudioGeneration": "🎵 Dynamic Audio Generation (Beta)",
    "DynamicImageEditor": "🔧 Dynamic Image Editor",
    "GaussianBlurUpscale": "🔍 Gaussian Blur Upscale (高斯模糊放大)",
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
        """Save full configuration, providers go to secrets.yaml"""
        try:
            data = await request.json()
            
            # Save providers to secrets.yaml
            if "providers" in data:
                if not config_manager.save_providers(data["providers"]):
                    return web.json_response({"error": "Failed to save providers"}, status=500)
            
            # Save rest of config to api_config.yaml (providers auto-excluded)
            if not config_manager.save_config_data(data):
                return web.json_response({"error": "Failed to save config"}, status=500)
            
            # Reload to merge providers back into memory
            config_manager.force_reload()
            
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
            # Default max_image_inputs based on model category:
            # image/image_editor models commonly accept multiple reference images
            category = model_config.get("category", "") if model_config else ""
            default_max_images = 9 if category in ("image", "image_editor") else 1
            max_image_inputs = model_config.get("max_image_inputs", default_max_images) if model_config else 1
            
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
            success = config_manager.update_provider(provider_name, data)
            if success:
                return web.json_response({"status": "success"})
            return web.json_response({"error": "Failed to update provider"}, status=500)
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

    # --- Upscale Settings ---
    @server.PromptServer.instance.routes.get("/api/batchbox/upscale-settings")
    async def get_upscale_settings(request):
        """Get upscale settings (model for blur upscale node)"""
        try:
            settings = config_manager.get_upscale_settings()
            return web.json_response({"upscale_settings": settings})
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    @server.PromptServer.instance.routes.post("/api/batchbox/upscale-settings")
    async def update_upscale_settings(request):
        """Update upscale settings"""
        try:
            data = await request.json()
            print(f"[BatchBox] Saving upscale settings: {data}")
            success = config_manager.update_upscale_settings(data)
            if success:
                return web.json_response({"success": True, "upscale_settings": config_manager.get_upscale_settings()})
            else:
                return web.json_response({"error": "Failed to save settings"}, status=500)
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    # --- Style Presets ---
    @server.PromptServer.instance.routes.get("/api/batchbox/style-presets")
    async def get_style_presets(request):
        try:
            presets = config_manager.get_style_presets()
            return web.json_response({"style_presets": presets})
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    @server.PromptServer.instance.routes.post("/api/batchbox/style-presets")
    async def update_style_presets(request):
        try:
            data = await request.json()
            presets = data.get("style_presets", {})
            success = config_manager.update_style_presets(presets)
            if success:
                return web.json_response({"success": True, "style_presets": config_manager.get_style_presets()})
            else:
                return web.json_response({"error": "Failed to save"}, status=500)
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    # --- Blur Preview ---
    @server.PromptServer.instance.routes.post("/api/batchbox/blur-preview")
    async def blur_preview(request):
        """Generate a blurred preview image for the upscale node UI"""
        try:
            from .image_utils import generate_blur_preview_base64
            data = await request.json()
            image_base64 = data.get("image_base64", "")
            sigma = float(data.get("sigma", 2.0))
            
            if not image_base64:
                return web.json_response({"error": "image_base64 is required"}, status=400)
            
            preview = generate_blur_preview_base64(image_base64, sigma)
            return web.json_response({"preview_base64": preview})
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    @server.PromptServer.instance.routes.post("/api/batchbox/generate-independent")
    async def generate_independent(request):
        """
        Independent generation API - bypasses ComfyUI queue for concurrent execution.
        
        Expects JSON body:
        {
            "model": str,           # Model name
            "prompt": str,          # Text prompt
            "seed": int,            # Random seed (optional)
            "batch_count": int,     # Number of images (optional, default 1)
            "extra_params": dict,   # Dynamic parameters (optional)
            "images_base64": list,  # Base64 images for img2img (optional)
            "endpoint_override": str  # Manual endpoint selection (optional)
        }
        """
        try:
            from .independent_generator import IndependentGenerator
            import json
            
            # Read full body using chunked reading to ensure complete body is received
            chunks = []
            async for chunk in request.content.iter_any():
                chunks.append(chunk)
            
            body = b''.join(chunks)
            data = json.loads(body)
            
            model = data.get("model")
            prompt = data.get("prompt", "")
            
            if not model:
                return web.json_response({"success": False, "error": "Model is required"}, status=400)
            if not prompt:
                return web.json_response({"success": False, "error": "Prompt is required"}, status=400)
            
            generator = IndependentGenerator()
        
            # Progress callback: send WebSocket event per batch for progressive preview
            node_id = data.get("node_id", "")
            completed_count = 0
            
            async def on_batch_complete(batch_idx, total, batch_previews):
                nonlocal completed_count
                completed_count += 1
                preview = batch_previews[0] if batch_previews else None
                server.PromptServer.instance.send_sync("batchbox:progress", {
                    "node_id": node_id,
                    "batch_index": batch_idx,
                    "completed": completed_count,
                    "total": total,
                    "preview": preview,
                })
            
            result = await generator.generate(
                model=model,
                prompt=prompt,
                seed=data.get("seed", 0),
                batch_count=data.get("batch_count", 1),
                extra_params=data.get("extra_params"),
                images_base64=data.get("images_base64"),
                endpoint_override=data.get("endpoint_override"),
                on_batch_complete=on_batch_complete
            )
            
            # Send websocket "executed" event so ComfyUI's image viewer displays the result
            if result.get("success") and result.get("preview_images"):
                import uuid as _uuid
                # node_id is already defined above
                if node_id:
                    prompt_id = "independent_" + _uuid.uuid4().hex[:8]
                    last_images_json = json.dumps(result["preview_images"])
                    output_ui = {
                        "images": result["preview_images"],
                        "_last_images": [last_images_json],
                        "_cached_hash": [result.get("params_hash", "")],
                    }
                    
                    # 1. Send websocket event for real-time viewer update
                    server.PromptServer.instance.send_sync("executed", {
                        "node": node_id,
                        "display_node": node_id,
                        "output": output_ui,
                        "prompt_id": prompt_id
                    })
                    
                    # 2. Write history entry so "已生成" panel shows the images
                    #    The /history API reads from prompt_queue.history
                    prompt_queue = server.PromptServer.instance.prompt_queue
                    with prompt_queue.mutex:
                        if len(prompt_queue.history) > 10000:
                            prompt_queue.history.pop(next(iter(prompt_queue.history)))
                        prompt_queue.history[prompt_id] = {
                            "prompt": (0, prompt_id, {node_id: {"class_type": "DynamicImageGeneration", "inputs": {}}}, {}, []),
                            "outputs": {
                                node_id: output_ui
                            },
                            "status": {
                                "status_str": "success",
                                "completed": True,
                                "messages": []
                            }
                        }
            
            return web.json_response(result)
            
        except Exception as e:
            import traceback
            traceback.print_exc()
            return web.json_response({"success": False, "error": str(e)}, status=500)

    # ==========================================
    # 5. Account System API Endpoints
    # ==========================================
    
    # Initialize Account system
    try:
        import os
        import yaml as _yaml
        from .account import Account
        
        _plugin_dir = os.path.dirname(os.path.abspath(__file__))
        _account = Account.get_instance()
        
        # Load account config from secrets.yaml directly
        _account_config = {}
        _secrets_path = os.path.join(_plugin_dir, "secrets.yaml")
        if os.path.exists(_secrets_path):
            try:
                with open(_secrets_path, 'r', encoding='utf-8') as _f:
                    _secrets_data = _yaml.safe_load(_f) or {}
                if "account" in _secrets_data:
                    _account_config = _secrets_data["account"]
            except Exception as _e:
                print(f"[ComfyUI-Custom-Batchbox] Warning reading secrets.yaml account section: {_e}")
        
        _account.configure(_plugin_dir, _account_config)
        
        print("[ComfyUI-Custom-Batchbox] Account system initialized")
    except Exception as e:
        print(f"[ComfyUI-Custom-Batchbox] Account system init warning: {e}")
        _account = None

    @server.PromptServer.instance.routes.post("/api/batchbox/account/login")
    async def account_login(request):
        """Trigger WebSocket login flow - opens browser to acggit.com"""
        try:
            from .account import Account
            account = Account.get_instance()
            result = account.login()
            return web.json_response(result)
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    @server.PromptServer.instance.routes.post("/api/batchbox/account/logout")
    async def account_logout(request):
        """Logout and clear token"""
        try:
            from .account import Account
            account = Account.get_instance()
            result = account.logout()
            return web.json_response(result)
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    @server.PromptServer.instance.routes.get("/api/batchbox/account/status")
    async def account_status(request):
        """Get login status, nickname, credits"""
        try:
            from .account import Account
            account = Account.get_instance()
            return web.json_response(account.get_status())
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    @server.PromptServer.instance.routes.post("/api/batchbox/account/credits")
    async def account_refresh_credits(request):
        """Refresh credit balance"""
        try:
            from .account import Account
            account = Account.get_instance()
            account.fetch_credits()
            # Return current status (credits will update async)
            return web.json_response(account.get_status())
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    @server.PromptServer.instance.routes.post("/api/batchbox/account/redeem")
    async def account_redeem(request):
        """Redeem a credit code"""
        try:
            from .account import Account
            data = await request.json()
            code = data.get("code", "").strip()
            if not code:
                return web.json_response({"error": "Code is required"}, status=400)
            
            account = Account.get_instance()
            result = account.redeem_credits(code)
            return web.json_response(result)
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    @server.PromptServer.instance.routes.get("/api/batchbox/account/pricing")
    async def account_pricing(request):
        """Get model pricing table"""
        try:
            from .account import Account
            account = Account.get_instance()
            if not account.price_table:
                account.fetch_credits_price()
                # Wait a moment for async fetch
                import asyncio
                await asyncio.sleep(1.5)
            return web.json_response({
                "success": True,
                "price_table": account.price_table or []
            })
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    print("[ComfyUI-Custom-Batchbox] API endpoints registered (with Account system)")

except Exception as e:
    print(f"[ComfyUI-Custom-Batchbox] Warning: Could not register API endpoints: {e}")
