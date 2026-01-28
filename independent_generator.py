"""
Independent Image Generator

Provides generation capability that bypasses ComfyUI's queue system,
enabling true concurrent generation across multiple nodes.
"""

import os
import base64
import json
import uuid
import asyncio
from io import BytesIO
from typing import Dict, List, Optional, Any, Tuple
from PIL import Image

import folder_paths

from .config_manager import config_manager
from .adapters.generic import GenericAPIAdapter
from .adapters.base import APIResponse


class IndependentGenerator:
    """
    Independent image generator that doesn't rely on ComfyUI's execution engine.
    
    This allows multiple BatchBox nodes to generate images concurrently
    without waiting in the ComfyUI queue.
    """
    
    _endpoint_index: Dict[str, int] = {}  # Round-robin counter per model
    
    def __init__(self):
        self.timeout = 600
    
    def _compute_params_hash(self, model: str, prompt: str, batch_count: int, 
                              seed: int, extra_params: Optional[Dict]) -> str:
        """
        Compute a hash of generation parameters.
        Uses the same logic as nodes.py to ensure consistency.
        """
        import hashlib
        
        # Remove seed from extra_params (we use it separately)
        params_for_hash = dict(extra_params) if extra_params else {}
        params_for_hash.pop("seed", None)
        
        # Use separators without spaces to match JavaScript JSON.stringify
        extra_params_normalized = json.dumps(params_for_hash, sort_keys=True, separators=(',', ':'))
        
        params_str = f"{model}|{prompt}|{batch_count}|{seed}|{extra_params_normalized}"
        return hashlib.md5(params_str.encode()).hexdigest()
    
    def get_adapter(self, model_name: str, mode: str = "text2img",
                    endpoint_override: Optional[str] = None) -> Optional[GenericAPIAdapter]:
        """
        Get API adapter for a model.
        
        Args:
            model_name: Name of the model
            mode: API mode ('text2img' or 'img2img')
            endpoint_override: Optional specific endpoint for manual selection
        """
        if endpoint_override:
            endpoint_info = config_manager.get_endpoint_by_name(model_name, endpoint_override, mode)
        else:
            endpoints = config_manager.get_api_endpoints(model_name)
            if not endpoints:
                print(f"[IndependentGenerator] No endpoints for {model_name}")
                return None
            
            current_idx = IndependentGenerator._endpoint_index.get(model_name, 0)
            endpoint_info = config_manager.get_endpoint_by_index(model_name, current_idx, mode)
            
            IndependentGenerator._endpoint_index[model_name] = (current_idx + 1) % len(endpoints)
        
        if not endpoint_info:
            print(f"[IndependentGenerator] No endpoint found for {model_name}/{mode}")
            return None
        
        provider = endpoint_info["provider"]
        mode_config = endpoint_info["config"]
        endpoint_config = endpoint_info["endpoint_config"]
        
        return GenericAPIAdapter(
            provider_config={
                "name": provider.name,
                "base_url": provider.base_url,
                "api_key": provider.api_key
            },
            endpoint_config=endpoint_config,
            mode_config=mode_config
        )
    
    def execute_with_failover(self, model_name: str, params: Dict[str, Any],
                               mode: str = "text2img",
                               endpoint_override: Optional[str] = None) -> APIResponse:
        """Execute API request with automatic failover."""
        settings = config_manager.get_settings()
        auto_failover = settings.get("auto_failover", True)
        
        if endpoint_override:
            auto_failover = False
        
        adapter = self.get_adapter(model_name, mode, endpoint_override)
        if adapter:
            result = adapter.execute(params, mode)
            if result.success:
                return result
            print(f"[IndependentGenerator] Primary failed: {result.error_message}")
        
        if auto_failover:
            alternatives = config_manager.get_alternative_endpoints(
                model_name, mode,
                exclude_provider=adapter.provider.get("name") if adapter else None
            )
            
            for alt in alternatives:
                alt_adapter = GenericAPIAdapter(
                    provider_config={
                        "name": alt["provider"].name,
                        "base_url": alt["provider"].base_url,
                        "api_key": alt["provider"].api_key
                    },
                    endpoint_config=alt["endpoint_config"],
                    mode_config=alt["config"]
                )
                
                print(f"[IndependentGenerator] Trying alternative: {alt['provider'].name}")
                result = alt_adapter.execute(params, mode)
                
                if result.success:
                    return result
                print(f"[IndependentGenerator] Alternative failed: {result.error_message}")
        
        return APIResponse(
            success=False,
            error_message="All providers failed"
        )
    
    async def generate(
        self,
        model: str,
        prompt: str,
        seed: int = 0,
        batch_count: int = 1,
        extra_params: Optional[Dict] = None,
        images_base64: Optional[List[str]] = None,
        endpoint_override: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Generate images independently of ComfyUI's queue.
        
        Args:
            model: Model name
            prompt: Text prompt
            seed: Random seed
            batch_count: Number of images to generate
            extra_params: Additional dynamic parameters
            images_base64: List of base64-encoded input images for img2img
            endpoint_override: Optional specific endpoint
            
        Returns:
            Dict with success status, preview images, and error message if any
        """
        # Determine mode
        mode = "img2img" if images_base64 and len(images_base64) > 0 else "text2img"
        
        # Build parameters
        params = {
            "prompt": prompt,
            "seed": seed,
        }
        
        # Merge extra params
        if extra_params:
            params.update(extra_params)
        
        # Handle image inputs for img2img
        if mode == "img2img" and images_base64:
            upload_files = []
            for i, img_b64 in enumerate(images_base64):
                try:
                    # Remove data URL prefix if present
                    if "," in img_b64:
                        img_b64 = img_b64.split(",", 1)[1]
                    
                    img_bytes = base64.b64decode(img_b64)
                    upload_files.append((f"image{i+1}", (f"image{i+1}.png", img_bytes, "image/png")))
                except Exception as e:
                    print(f"[IndependentGenerator] Failed to decode image {i}: {e}")
            
            if upload_files:
                params["_upload_files"] = upload_files
        
        # Generate images in parallel with immediate saving
        response_log = ""
        
        async def process_single_batch(batch_idx: int) -> Tuple[int, List[Dict], str]:
            """Process a single batch, save immediately, return (index, preview_results, log)."""
            print(f"\n[IndependentGenerator] Batch {batch_idx+1}/{batch_count} - Model: {model}")
            
            current_params = params.copy()
            current_seed = seed + batch_idx if seed > 0 else 0
            if current_seed > 0:
                current_params["seed"] = current_seed
            
            # Run blocking API call in thread pool
            result = await asyncio.to_thread(
                self.execute_with_failover, model, current_params, mode, endpoint_override
            )
            
            batch_previews = []
            batch_log = ""
            
            if result.success:
                for img_bytes in result.images:
                    try:
                        pil_img = Image.open(BytesIO(img_bytes))
                        if pil_img.mode not in ("RGB", "RGBA"):
                            pil_img = pil_img.convert("RGB")
                        
                        # ⚡ IMMEDIATELY SAVE upon receiving image
                        preview = self._save_single_image(pil_img, model, current_params, batch_idx)
                        if preview:
                            batch_previews.append(preview)
                    except Exception as e:
                        batch_log += f"Image decode error: {e}\n"
            else:
                batch_log += f"Batch {batch_idx+1} failed: {result.error_message}\n"
            
            return (batch_idx, batch_previews, batch_log)
        
        # Run all batches in parallel
        tasks = [process_single_batch(i) for i in range(batch_count)]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Collect results in order
        all_previews = []
        for result in sorted(results, key=lambda x: x[0] if isinstance(x, tuple) else 999):
            if isinstance(result, Exception):
                response_log += f"Batch error: {result}\n"
            else:
                _, batch_previews, batch_log = result
                all_previews.extend(batch_previews)
                response_log += batch_log
        
        if not all_previews:
            return {
                "success": False,
                "error": f"Generation failed.\n{response_log}",
                "preview_images": []
            }
        
        # Compute hash using the same logic as nodes.py for consistency
        params_hash = self._compute_params_hash(model, prompt, batch_count, seed, extra_params)
        
        return {
            "success": True,
            "preview_images": all_previews,
            "response_info": response_log if response_log else "Success",
            "params_hash": params_hash  # Backend-computed hash for cache matching
        }
    
    def _save_single_image(self, pil_img: Image.Image, model: str, params: Dict, batch_idx: int) -> Optional[Dict]:
        """Save a single image immediately and return preview info."""
        # Try auto-save first
        try:
            from .save_settings import SaveSettings
            save_cfg = config_manager.get_save_settings()
            saver = SaveSettings(save_cfg)
            
            if saver.enabled:
                context = {
                    "model": model,
                    "seed": params.get("seed", 0),
                    "prompt": params.get("prompt", ""),
                    "batch": batch_idx + 1,
                }
                result = saver.save_image(pil_img, context)
                if result and "preview" in result:
                    return result["preview"]
        except Exception as e:
            print(f"[IndependentGenerator] AutoSave error: {e}")
        
        # Fall back to temp folder
        try:
            temp_dir = folder_paths.get_temp_directory()
            filename = f"batchbox_independent_{uuid.uuid4().hex[:8]}_{batch_idx}.png"
            filepath = os.path.join(temp_dir, filename)
            pil_img.save(filepath, format="PNG")
            
            return {
                "filename": filename,
                "subfolder": "",
                "type": "temp"
            }
        except Exception as e:
            print(f"[IndependentGenerator] Temp save error: {e}")
            return None
