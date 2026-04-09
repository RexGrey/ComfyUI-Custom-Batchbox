"""
ComfyUI-Custom-Batchbox

A ComfyUI custom node package for dynamic AI image generation 
with multi-provider support.
"""

_PACKAGE_BOOTSTRAP_AVAILABLE = True

try:
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
except ImportError:
    if __package__:
        raise

    # Pytest may import this file directly as a standalone module during
    # collection, where package-relative imports are unavailable.
    _PACKAGE_BOOTSTRAP_AVAILABLE = False
    NanoBananaPro = None
    DynamicImageGenerationNode = None
    DynamicTextGenerationNode = None
    DynamicVideoGenerationNode = None
    DynamicAudioGenerationNode = None
    DynamicImageEditorNode = None
    GaussianBlurUpscaleNode = None
    create_dynamic_node = None
    config_manager = None

# ==========================================
# 1. Base Node Mappings
# ==========================================
NODE_CLASS_MAPPINGS = {}

NODE_DISPLAY_NAME_MAPPINGS = {}

if _PACKAGE_BOOTSTRAP_AVAILABLE:
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
if _PACKAGE_BOOTSTRAP_AVAILABLE:
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
    import json as _json
    import server
    import os
    from aiohttp import web

    # Detect admin environment using Git existence (Z-drive sync specifically excludes .git)
    _ext_path = os.path.dirname(os.path.abspath(__file__))
    IS_ADMIN = os.path.exists(os.path.join(_ext_path, ".git"))

    # Auto-increase ComfyUI body size limit for multi-image requests
    # Default is 100MB which is too small for 14 base64-encoded images
    _BATCHBOX_MAX_BODY = 500 * 1024 * 1024  # 500MB
    _APPLY_BLUR_MAX_BODY = 200 * 1024 * 1024  # 200MB
    _app = server.PromptServer.instance.app
    if _app._client_max_size < _BATCHBOX_MAX_BODY:
        _app._client_max_size = _BATCHBOX_MAX_BODY
        print(f"[ComfyUI-Custom-Batchbox] Increased max upload size to 500MB")

    async def _read_request_json_limited(request, max_size):
        """
        Read a JSON request body while enforcing a hard byte limit.
        Falls back to request.json() for lightweight tests/mocks that do not
        provide a streaming body implementation.
        """
        chunks = []
        total_size = 0
        content = getattr(request, "content", None)
        if content is not None and hasattr(content, "iter_any"):
            async for chunk in content.iter_any():
                total_size += len(chunk)
                if total_size > max_size:
                    return None, web.json_response(
                        {
                            "success": False,
                            "error": f"Request body too large, exceeds {max_size // (1024 * 1024)}MB limit",
                        },
                        status=413,
                    )
                chunks.append(chunk)

        if chunks:
            try:
                return _json.loads(b"".join(chunks).decode("utf-8")), None
            except (_json.JSONDecodeError, UnicodeDecodeError):
                return None, web.json_response({"success": False, "error": "Invalid JSON body"}, status=400)

        try:
            return await request.json(), None
        except Exception:
            return None, web.json_response({"success": False, "error": "Invalid JSON body"}, status=400)

    @server.PromptServer.instance.routes.get("/api/batchbox/is-admin")
    async def check_admin(request):
        """Frontend check for administrator privileges"""
        return web.json_response({"is_admin": IS_ADMIN})

    @server.PromptServer.instance.routes.get("/api/batchbox/mode")
    async def get_mode(request):
        """Frontend check for current operational mode (Admin vs Encrypted)"""
        try:
            return web.json_response({"is_encrypted_mode": config_manager.is_encrypted_mode()})
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    def _mask_secrets(config: dict) -> dict:
        """Deep copy and mask sensitive API keys and secrets in the config payload."""
        import copy
        masked = copy.deepcopy(config)
        providers = masked.get("providers", {})
        for name, p_data in providers.items():
            for key in ["api_key", "secret_key", "access_key"]:
                if p_data.get(key):
                    val = str(p_data[key])
                    p_data[key] = f"***{val[-4:]}" if len(val) > 4 else "***"
        return masked

    @server.PromptServer.instance.routes.get("/api/batchbox/config")
    async def get_config(request):
        """Get full configuration (Masked if encrypted)"""
        if not IS_ADMIN and not config_manager.is_encrypted_mode():
            return web.json_response({"error": "Admin access required. Student-Node is restricted."}, status=403)
        try:
            data = config_manager.get_raw_config()
            if config_manager.is_encrypted_mode():
                data = _mask_secrets(data)
            return web.json_response(data)
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    @server.PromptServer.instance.routes.post("/api/batchbox/config")
    async def save_config(request):
        """Save full configuration, providers go to secrets.yaml"""
        if not IS_ADMIN and not config_manager.is_encrypted_mode():
            return web.json_response({"error": "Admin access required. Student-Node is restricted."}, status=403)
        if config_manager.is_encrypted_mode():
            return web.json_response({"error": "Admin access required. Student-Node is restricted (Encrypted Mode)."}, status=403)
            
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
            default_max_images = 14 if category in ("image", "image_editor") else 1
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
            
            import asyncio
            preview = await asyncio.to_thread(generate_blur_preview_base64, image_base64, sigma)
            return web.json_response({"preview_base64": preview})
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    @server.PromptServer.instance.routes.post("/api/batchbox/apply-blur")
    async def apply_blur(request):
        """
        Apply Gaussian blur to input image(s) and cache the result.
        Called by frontend "应用设置" button — makes blurred_image output
        immediately available without running the full upscale pipeline.
        """
        try:
            data, error_response = await _read_request_json_limited(request, _APPLY_BLUR_MAX_BODY)
            if error_response is not None:
                return error_response

            from .image_utils import apply_gaussian_blur, apply_masked_gaussian_blur
            from .nodes import save_preview_images, GaussianBlurUpscaleNode
            import json, base64, torch, numpy as np
            from io import BytesIO
            from PIL import Image

            node_id = data.get("node_id", "")
            sigma = float(data.get("sigma", 2.0))
            blur_mask_b64 = data.get("blur_mask") or ""
            selection_boxes = data.get("selection_boxes") or []
            blur_mode = data.get("blur_mode") or ""
            images_base64 = data.get("images_base64") or []
            selected_index = data.get("selected_index", 0)

            if not images_base64:
                return web.json_response({"success": False, "error": "images_base64 required"}, status=400)

            # Decode mask if present
            mask_pil = None
            if blur_mask_b64:
                mask_data = blur_mask_b64
                if "," in mask_data:
                    mask_data = mask_data.split(",", 1)[1]
                mask_pil = Image.open(BytesIO(base64.b64decode(mask_data))).convert("L")

            # Apply blur to each image (in background thread to prevent UI freezing)
            def _process_images():
                _blurred_pil_list = []
                _blurred_tensors = []
                _full_tensors = None  # Only set for selection mode
                for img_b64 in images_base64:
                    if "," in img_b64:
                        img_b64 = img_b64.split(",", 1)[1]
                    pil_img = Image.open(BytesIO(base64.b64decode(img_b64))).convert("RGB")

                    if blur_mode == "selection" and selection_boxes:
                        from .image_utils import crop_and_blur_selection_boxes, apply_selection_boxes_blur
                        cropped_list = crop_and_blur_selection_boxes(pil_img, selection_boxes)
                        for cropped_pil, box_info in cropped_list:
                            _blurred_pil_list.append(cropped_pil)
                            blurred_np = np.array(cropped_pil).astype(np.float32) / 255.0
                            _blurred_tensors.append(torch.from_numpy(blurred_np).unsqueeze(0))
                        # Cache full-image tensor for node's blurred_image output
                        full_blurred = apply_selection_boxes_blur(pil_img, selection_boxes)
                        full_np = np.array(full_blurred).astype(np.float32) / 255.0
                        _full_tensors = [torch.from_numpy(full_np).unsqueeze(0)]
                    elif mask_pil:
                        blurred = apply_masked_gaussian_blur(pil_img, mask_pil, sigma)
                        _blurred_pil_list.append(blurred)
                        blurred_np = np.array(blurred).astype(np.float32) / 255.0
                        _blurred_tensors.append(torch.from_numpy(blurred_np).unsqueeze(0))
                    else:
                        blurred = apply_gaussian_blur(pil_img, sigma)
                        _blurred_pil_list.append(blurred)
                        blurred_np = np.array(blurred).astype(np.float32) / 255.0
                        _blurred_tensors.append(torch.from_numpy(blurred_np).unsqueeze(0))
                
                return _blurred_pil_list, _blurred_tensors, _full_tensors

            import asyncio
            blurred_pil_list, blurred_tensors, full_tensors = await asyncio.to_thread(_process_images)

            # Cache the blurred tensor for the node's upscale() to pick up
            # For selection mode, cache the full-image tensor (not the cropped previews)
            cache_tensors = full_tensors if full_tensors else blurred_tensors
            if cache_tensors and node_id:
                # Handle different-sized images by padding to max dimensions
                if len(cache_tensors) > 1:
                    max_h = max(t.shape[1] for t in cache_tensors)
                    max_w = max(t.shape[2] for t in cache_tensors)
                    padded = []
                    for t in cache_tensors:
                        if t.shape[1] != max_h or t.shape[2] != max_w:
                            p = torch.zeros(1, max_h, max_w, t.shape[3])
                            p[:, :t.shape[1], :t.shape[2], :] = t
                            padded.append(p)
                        else:
                            padded.append(t)
                    combined = torch.cat(padded, dim=0)
                else:
                    combined = cache_tensors[0]
                GaussianBlurUpscaleNode._cached_blur_data[node_id] = {
                    "tensor": combined,
                    "sigma": sigma,
                    "has_mask": bool(blur_mask_b64) or (blur_mode == "selection" and bool(selection_boxes)),
                    "selection_boxes": selection_boxes if blur_mode == "selection" else [],
                    "blur_mode": blur_mode,
                }
                print(f"[ApplyBlur] Cached blurred tensor for node {node_id}: {combined.shape}, σ={sigma}")

            # Save as temp preview images
            preview_results = save_preview_images(blurred_pil_list, prefix="blur_applied")

            # Filter preview to only the selected image for UI display
            # Selection mode: show all cropped previews
            if blur_mode == "selection" and selection_boxes:
                display_preview = preview_results
            else:
                try:
                    selected_idx = max(0, min(int(selected_index), len(preview_results) - 1))
                    display_preview = [preview_results[selected_idx]] if preview_results else []
                except (ValueError, TypeError):
                    display_preview = [preview_results[0]] if preview_results else []

            # Send WebSocket "executed" event so ComfyUI recognizes the output
            if node_id and display_preview:
                import uuid as _uuid
                prompt_id = "apply_blur_" + _uuid.uuid4().hex[:8]
                preview_json = json.dumps(display_preview)
                output_ui = {
                    "images": display_preview,
                    "_blur_preview_images": [preview_json],
                }
                server.PromptServer.instance.send_sync("executed", {
                    "node": node_id,
                    "display_node": node_id,
                    "output": output_ui,
                    "prompt_id": prompt_id,
                })
                # Write history entry
                prompt_queue = server.PromptServer.instance.prompt_queue
                with prompt_queue.mutex:
                    if len(prompt_queue.history) > 10000:
                        prompt_queue.history.pop(next(iter(prompt_queue.history)))
                    prompt_queue.history[prompt_id] = {
                        "prompt": (0, prompt_id, {node_id: {"class_type": "GaussianBlurUpscale", "inputs": {}}}, {}, []),
                        "outputs": {node_id: output_ui},
                        "status": {"status_str": "success", "completed": True, "messages": []},
                    }

            return web.json_response({
                "success": True,
                "preview_images": preview_results,
                "sigma": sigma,
                "has_mask": bool(blur_mask_b64) or (blur_mode == "selection" and bool(selection_boxes)),
                "blur_mode": blur_mode,
            })

        except Exception as e:
            import traceback
            traceback.print_exc()
            return web.json_response({"success": False, "error": str(e)}, status=500)

    @server.PromptServer.instance.routes.post("/api/batchbox/generate-blur-upscale")
    async def generate_blur_upscale(request):
        """
        Independent generation for GaussianBlurUpscale — bypasses ComfyUI queue.
        
        Handles Gaussian blur preprocessing, model/prompt resolution, and delegates
        to IndependentGenerator for true concurrent multi-node execution.
        """
        try:
            from .independent_generator import IndependentGenerator
            from .image_utils import apply_gaussian_blur, apply_masked_gaussian_blur
            import json, base64
            import hashlib
            from io import BytesIO
            from PIL import Image

            chunks = []
            total_size = 0
            MAX_SIZE = 200 * 1024 * 1024  # 200MB max limit to prevent OOM
            async for chunk in request.content.iter_any():
                total_size += len(chunk)
                if total_size > MAX_SIZE:
                    print(f"[BlurUpscale] Rejected huge payload: {total_size/(1024*1024):.2f}MB")
                    return web.json_response({"success": False, "error": "Request body too large, exceeds 200MB limit"}, status=413)
                chunks.append(chunk)
            body = b''.join(chunks)
            body_size_mb = len(body) / (1024 * 1024)
            print(f"[BlurUpscale] Request body size: {body_size_mb:.2f}MB ({len(body)} bytes)")
            data = json.loads(body)

            node_id = data.get("node_id", "")
            generation_token = data.get("generation_token", "")
            blur_intensity = data.get("blur_intensity", "轻 (σ1-3)")
            custom_sigma = float(data.get("custom_sigma", 0.0))
            repair_mode = data.get("repair_mode", "直出")
            style_prompt = data.get("style_prompt", "")
            seed = int(data.get("seed", 0))
            batch_count = min(int(data.get("batch_count", 1)), 10)  # 安全上限
            aspect_ratio_widget = data.get("aspect_ratio") or "auto"
            endpoint_override_param = data.get("endpoint_override")
            blur_mask_b64 = data.get("blur_mask") or ""
            selection_boxes = data.get("selection_boxes") or []
            blur_mode = data.get("blur_mode") or ""
            
            # Support both new multi-image format and legacy single-image format
            images_base64 = data.get("images_base64") or []
            if not images_base64:
                legacy = data.get("image_base64", "")
                if legacy:
                    images_base64 = [legacy]

            # Reference face images (not blurred, passed directly to AI model)
            reference_images_base64 = data.get("reference_images_base64") or []
            # Selection mode: per-box reference mapping, e.g. {"0": [0,1,2], "1": [3,4]}
            # Keys are box indices (str), values are reference image indices (0-based into reference_images_base64)
            selection_ref_mapping = data.get("selection_ref_mapping") or {}
            if reference_images_base64:
                print(f"[BlurUpscale] {len(reference_images_base64)} reference image(s) received")

            if not images_base64:
                return web.json_response({"success": False, "error": "images_base64 is required"}, status=400)

            # --- Step 1: Resolve model from upscale_settings ---
            settings = config_manager.get_upscale_settings()
            model = settings.get("model", "")
            saved_endpoint = settings.get("endpoint", "")
            default_params = settings.get("default_params", {})

            if not model:
                # Fallback: first available image model
                raw_cfg = config_manager.get_raw_config()
                for m_name, m_cfg in raw_cfg.get("models", {}).items():
                    if m_cfg.get("category") == "image":
                        model = m_name
                        break

            if not model:
                return web.json_response({"success": False, "error": "未配置放大模型，请在 API Manager 中设置"}, status=400)

            # --- Step 2: Build prompt ---
            REPAIR_PROMPTS = {
                "直出": "把这张模糊的照片变高清",
                "降噪": "把这张模糊的照片变高清，让画面变得干净整洁",
                "风格": "把这张模糊的照片变高清。按照如下风格要求处理：",
            }
            BLUR_PRESETS = {
                "轻 (σ1-3)": 2.0,
                "中 (σ3-6)": 4.0,
                "重 (σ6-10)": 7.0,
            }

            base_prompt = REPAIR_PROMPTS.get(repair_mode, REPAIR_PROMPTS["直出"])
            if repair_mode == "风格" and style_prompt:
                prompt = f"{base_prompt}{style_prompt}"
            else:
                prompt = base_prompt

            # Auto face-swap: when reference images exist, face replacement is the PRIMARY task
            if reference_images_base64:
                n_refs = len(reference_images_base64)
                ref_nums = "、".join([f"图{i+2}" for i in range(n_refs)])
                if style_prompt:
                    prompt = style_prompt
                    print(f"[BlurUpscale] Face-swap CUSTOM prompt: {prompt[:120]}...")
                else:
                    prompt = (
                        f"将图1中模糊的人物变清晰，人物的角色特征参考{ref_nums}"
                    )
                    print(f"[BlurUpscale] Face-swap DEFAULT prompt: {prompt[:120]}...")

            # --- Step 3: Compute sigma ---
            sigma = custom_sigma if custom_sigma > 0 else BLUR_PRESETS.get(blur_intensity, 2.0)

            # --- Step 4: Decode images, apply Gaussian blur, re-encode ---
            # Decode mask if present
            mask_pil = None
            if blur_mask_b64:
                mask_data = blur_mask_b64
                if "," in mask_data:
                    mask_data = mask_data.split(",", 1)[1]
                mask_pil = Image.open(BytesIO(base64.b64decode(mask_data))).convert("L")

            # Use background thread for heavy Gaussian blur processing to avoid blocking the event loop
            def _process_images():
                _blurred_b64_list = []
                for idx, img_b64 in enumerate(images_base64):
                    if "," in img_b64:
                        img_b64 = img_b64.split(",", 1)[1]
                    img_bytes = base64.b64decode(img_b64)
                    pil_img = Image.open(BytesIO(img_bytes))
                    if pil_img.mode not in ("RGB", "RGBA"):
                        pil_img = pil_img.convert("RGB")

                    if blur_mode == "selection" and selection_boxes:
                        # Crop each selection box and blur independently
                        from .image_utils import crop_and_blur_selection_boxes
                        print(f"[BlurUpscale-Independent] SELECTION mode: cropping {len(selection_boxes)} boxes from image {idx+1}/{len(images_base64)}")
                        cropped_list = crop_and_blur_selection_boxes(pil_img, selection_boxes)
                        for box_idx, (cropped_pil, box_info) in enumerate(cropped_list):
                            buf = BytesIO()
                            cropped_pil.save(buf, format="PNG")
                            _blurred_b64_list.append(base64.b64encode(buf.getvalue()).decode("utf-8"))
                            print(f"[BlurUpscale-Independent]   Box {box_idx+1}: {cropped_pil.size}")
                    elif mask_pil:
                        print(f"[BlurUpscale-Independent] Applying MASKED blur σ={sigma} to image {idx+1}/{len(images_base64)} {pil_img.size}")
                        blurred_pil = apply_masked_gaussian_blur(pil_img, mask_pil, sigma)
                        buf = BytesIO()
                        blurred_pil.save(buf, format="PNG")
                        _blurred_b64_list.append(base64.b64encode(buf.getvalue()).decode("utf-8"))
                    else:
                        print(f"[BlurUpscale-Independent] Applying Gaussian blur σ={sigma} to image {idx+1}/{len(images_base64)} {pil_img.size}")
                        blurred_pil = apply_gaussian_blur(pil_img, sigma)
                        buf = BytesIO()
                        blurred_pil.save(buf, format="PNG")
                        _blurred_b64_list.append(base64.b64encode(buf.getvalue()).decode("utf-8"))
                return _blurred_b64_list

            import asyncio
            blurred_b64_list = await asyncio.to_thread(_process_images)

            # --- Step 5: Build extra_params with default_params ---
            extra_params = dict(default_params) if default_params else {}

            # Apply widget aspect_ratio (overrides default_params)
            if aspect_ratio_widget and aspect_ratio_widget != "auto":
                extra_params["aspect_ratio"] = aspect_ratio_widget

            # Resolve aspect_ratio='auto' from first input image dimensions
            if extra_params.get("aspect_ratio") in (None, "auto") and images_base64:
                from .image_utils import detect_aspect_ratio
                # Use the first decoded PIL image (before blur) to get dimensions
                first_b64 = images_base64[0]
                if "," in first_b64:
                    first_b64 = first_b64.split(",", 1)[1]
                first_img = Image.open(BytesIO(base64.b64decode(first_b64)))
                extra_params["aspect_ratio"] = detect_aspect_ratio(first_img.width, first_img.height)
                print(f"[BlurUpscale-Independent] Auto aspect_ratio: {first_img.size} → {extra_params['aspect_ratio']}")

            # Endpoint override: manual selection > saved in settings
            final_endpoint = endpoint_override_param or saved_endpoint or None

            # --- Step 6: Call IndependentGenerator ---
            generator = IndependentGenerator()
            
            import time as _time
            _usage_t0 = _time.time()

            completed_count = 0
            # For selection mode, override total to reflect all boxes × batch_count
            _progress_total_override = None

            async def on_batch_complete(batch_idx, total, batch_previews):
                nonlocal completed_count
                completed_count += 1
                actual_total = _progress_total_override if _progress_total_override else total
                preview = batch_previews[0] if batch_previews else None
                server.PromptServer.instance.send_sync("batchbox:progress", {
                    "node_id": node_id,
                    "generation_token": generation_token,
                    "batch_index": batch_idx,
                    "completed": completed_count,
                    "total": actual_total,
                    "preview": preview,
                })

            # Selection mode: call generator per cropped box for independent aspect_ratios
            if blur_mode == "selection" and selection_boxes:
                from .image_utils import detect_aspect_ratio as _dar
                all_preview_images = []
                all_params_hashes = []
                total_boxes = len(blurred_b64_list)
                total_calls = total_boxes * batch_count
                _progress_total_override = total_calls
                
                # Pre-initialize result in case blurred_b64_list is empty (no valid boxes cropped)
                result = {
                    "success": False,
                    "error": "未能截取到任何有效的选区框，请重新框选",
                    "preview_images": [],
                }
                
                for box_idx, box_b64 in enumerate(blurred_b64_list):
                    # Decode to get dimensions for aspect_ratio
                    box_img = Image.open(BytesIO(base64.b64decode(box_b64)))
                    box_extra = dict(extra_params)
                    box_extra["aspect_ratio"] = _dar(box_img.width, box_img.height)
                    print(f"[BlurUpscale-Independent] Generating box {box_idx+1}/{total_boxes}: {box_img.size} → {box_extra['aspect_ratio']}")
                    
                    # Merge: blurred crop + this box's reference images
                    # Read refRange directly from the box object (e.g. "2,3" or "2-4")
                    box_images = [box_b64]
                    box_data = selection_boxes[box_idx] if box_idx < len(selection_boxes) else {}
                    ref_range_str = str(box_data.get("refRange", "")).strip()
                    parsed_indices = []
                    if ref_range_str and reference_images_base64:
                        # Parse refRange: "2-4" (range) or "2,3,4" (comma list)
                        # Numbers are slot numbers starting from 2 → index 0 in reference_images_base64
                        if "-" in ref_range_str:
                            parts = ref_range_str.split("-")
                            try:
                                start, end = int(parts[0].strip()), int(parts[1].strip())
                                parsed_indices = [n - 2 for n in range(start, end + 1)]
                            except (ValueError, IndexError):
                                pass
                        else:
                            for s in ref_range_str.replace("，", ",").split(","):
                                try:
                                    parsed_indices.append(int(s.strip()) - 2)
                                except ValueError:
                                    pass
                        
                        for ri in parsed_indices:
                            if 0 <= ri < len(reference_images_base64):
                                box_images.append(reference_images_base64[ri])
                        print(f"[BlurUpscale-Independent]   Box {box_idx}: refRange='{ref_range_str}' → {len(box_images)-1} reference(s)")
                    elif reference_images_base64:
                        # No refRange specified: send all references (single-person fallback)
                        parsed_indices = list(range(len(reference_images_base64)))
                        box_images.extend(reference_images_base64)
                        print(f"[BlurUpscale-Independent]   Box {box_idx}: all {len(reference_images_base64)} reference(s) (no refRange)")

                    # Generate per-box prompt: only reference images actually sent with THIS box
                    box_n_refs = len(box_images) - 1  # minus the blurred crop itself
                    if box_n_refs > 0:
                        # For the API prompt, we must use local indices (图2, 图3...) since that is what the API receives
                        api_ref_nums = "、".join([f"图{i+2}" for i in range(box_n_refs)])
                        
                        # For the console print, we use the original mapped slot names to avoid confusing the user
                        user_ref_slots = "、".join([f"输入槽图{r+2}" for r in parsed_indices])
                        
                        if style_prompt:
                            box_prompt = style_prompt
                            print(f"[BlurUpscale-Independent]   Box {box_idx} CUSTOM prompt (using refs {user_ref_slots}): {box_prompt[:200]}...")
                        else:
                            box_prompt = (
                                f"将图1中模糊的人物变清晰，人物的角色特征参考{api_ref_nums}"
                            )
                            print(f"[BlurUpscale-Independent]   Box {box_idx} DEFAULT prompt (using refs {user_ref_slots}): {box_prompt[:200]}...")
                    else:
                        box_prompt = prompt  # No refs for this box, use global prompt

                    box_result = await generator.generate(
                        model=model,
                        prompt=box_prompt,
                        seed=seed + box_idx,
                        batch_count=batch_count,
                        extra_params=box_extra,
                        images_base64=box_images,
                        endpoint_override=final_endpoint,
                        on_batch_complete=on_batch_complete,
                        hash_extras={
                            "blur_intensity": blur_intensity,
                            "custom_sigma": custom_sigma,
                            "repair_mode": repair_mode,
                            "style_prompt": style_prompt,
                            "endpoint_override": final_endpoint or "",
                            "blur_mode": blur_mode,
                            "box_index": str(box_idx),
                            "selection_boxes": str(selection_boxes) if selection_boxes else "",
                        },
                        hash_images_base64=[box_b64],
                    )
                    if box_result.get("success") and box_result.get("preview_images"):
                        all_preview_images.extend(box_result["preview_images"])
                    elif "error" in box_result:
                        result["error"] = box_result["error"]
                        
                    if box_result.get("params_hash"):
                        all_params_hashes.append(box_result["params_hash"])
                
                # Update combined result, preserving any existing error messages
                result["success"] = bool(all_preview_images)
                result["preview_images"] = all_preview_images
                result["params_hash"] = "_".join(all_params_hashes) if all_params_hashes else ""
            else:
                # Merge: blurred image(s) + all reference images
                merged_images = blurred_b64_list + reference_images_base64
                if reference_images_base64:
                    print(f"[BlurUpscale-Independent] Merged {len(blurred_b64_list)} blurred + {len(reference_images_base64)} reference = {len(merged_images)} total images")

                result = await generator.generate(
                    model=model,
                    prompt=prompt,
                    seed=seed,
                    batch_count=batch_count,
                    extra_params=extra_params,
                    images_base64=merged_images,
                    endpoint_override=final_endpoint,
                    on_batch_complete=on_batch_complete,
                    hash_extras={
                        "blur_intensity": blur_intensity,
                        "custom_sigma": custom_sigma,
                        "repair_mode": repair_mode,
                        "style_prompt": style_prompt,
                        "endpoint_override": final_endpoint or "",
                        "blur_mask": hashlib.md5(blur_mask_b64.encode('utf-8')).hexdigest() if blur_mask_b64 else "",
                        "blur_mode": blur_mode,
                        "selection_boxes": str(selection_boxes) if selection_boxes else "",
                    },
                    hash_images_base64=images_base64,
                )

            # --- Step 7: Send websocket events for UI update ---
            _usage_duration = _time.time() - _usage_t0
            
            # --- Usage Tracking ---
            try:
                from .usage_tracker import get_tracker
                _preview_images = result.get("preview_images", [])
                _saved_count = sum(1 for p in _preview_images if p.get("type") == "output")
                get_tracker().record(
                    node_type="blur_upscale",
                    model=model,
                    batch_count=batch_count,
                    images_generated=len(_preview_images),
                    images_saved=_saved_count,
                    success=result.get("success", False),
                    providers_tried=[],
                    error_message=result.get("error", ""),
                    duration_seconds=_usage_duration,
                )
            except Exception as _e:
                print(f"[UsageTracker] Error: {_e}")
            
            if result.get("success") and result.get("preview_images"):
                import uuid as _uuid
                if node_id:
                    prompt_id = "blur_upscale_" + _uuid.uuid4().hex[:8]
                    last_images_json = json.dumps(result["preview_images"])
                    output_ui = {
                        "images": result["preview_images"],
                        "_last_images": [last_images_json],
                        "_cached_hash": [result.get("params_hash", "")],
                        "_batchbox_generation_token": [generation_token],
                    }
                    server.PromptServer.instance.send_sync("executed", {
                        "node": node_id,
                        "display_node": node_id,
                        "output": output_ui,
                        "prompt_id": prompt_id
                    })
                    # Write history entry
                    prompt_queue = server.PromptServer.instance.prompt_queue
                    with prompt_queue.mutex:
                        if len(prompt_queue.history) > 10000:
                            prompt_queue.history.pop(next(iter(prompt_queue.history)))
                        prompt_queue.history[prompt_id] = {
                            "prompt": (0, prompt_id, {node_id: {"class_type": "GaussianBlurUpscale", "inputs": {}}}, {}, []),
                            "outputs": {node_id: output_ui},
                            "status": {"status_str": "success", "completed": True, "messages": []}
                        }

            return web.json_response(result)

        except Exception as e:
            import traceback
            traceback.print_exc()
            return web.json_response({"success": False, "error": str(e)}, status=500)

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
            body_size_mb = len(body) / (1024 * 1024)
            print(f"[Independent] Request body size: {body_size_mb:.2f}MB ({len(body)} bytes)")
            data = json.loads(body)
            
            model = data.get("model")
            prompt = data.get("prompt", "")
            generation_token = data.get("generation_token", "")
            
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
                    "generation_token": generation_token,
                    "batch_index": batch_idx,
                    "completed": completed_count,
                    "total": total,
                    "preview": preview,
                })
            
            import time as _time
            _usage_t0 = _time.time()
            _batch_count = min(int(data.get("batch_count", 1)), 20)
            
            result = await generator.generate(
                model=model,
                prompt=prompt,
                seed=data.get("seed", 0),
                batch_count=_batch_count,
                extra_params=data.get("extra_params"),
                images_base64=data.get("images_base64"),
                endpoint_override=data.get("endpoint_override"),
                on_batch_complete=on_batch_complete
            )
            
            _usage_duration = _time.time() - _usage_t0
            
            # --- Usage Tracking ---
            try:
                from .usage_tracker import get_tracker
                _preview_images = result.get("preview_images", [])
                _saved_count = sum(1 for p in _preview_images if p.get("type") == "output")
                get_tracker().record(
                    node_type="independent",
                    model=model,
                    batch_count=_batch_count,
                    images_generated=len(_preview_images),
                    images_saved=_saved_count,
                    success=result.get("success", False),
                    providers_tried=[],  # Aggregated per-batch, not available in result dict
                    error_message=result.get("error", ""),
                    duration_seconds=_usage_duration,
                )
            except Exception as _e:
                print(f"[UsageTracker] Error: {_e}")
            
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
                        "_batchbox_generation_token": [generation_token],
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
