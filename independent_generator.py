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
        
        # Generate images
        successful_pil_images = []
        response_log = ""
        
        for i in range(batch_count):
            print(f"\n[IndependentGenerator] Batch {i+1}/{batch_count} - Model: {model}")
            
            current_params = params.copy()
            if seed > 0:
                current_params["seed"] = seed + i
            
            # Run blocking API call in thread pool to avoid blocking event loop
            result = await asyncio.to_thread(
                self.execute_with_failover, model, current_params, mode, endpoint_override
            )
            
            if result.success:
                for img_bytes in result.images:
                    try:
                        pil_img = Image.open(BytesIO(img_bytes))
                        if pil_img.mode not in ("RGB", "RGBA"):
                            pil_img = pil_img.convert("RGB")
                        successful_pil_images.append(pil_img)
                    except Exception as e:
                        response_log += f"Image decode error: {e}\n"
            else:
                response_log += f"Batch {i+1} failed: {result.error_message}\n"
        
        if not successful_pil_images:
            return {
                "success": False,
                "error": f"Generation failed.\n{response_log}",
                "preview_images": []
            }
        
        # Save images and get preview info
        preview_results = self._save_images(successful_pil_images, model, params)
        
        return {
            "success": True,
            "preview_images": preview_results,
            "response_info": response_log if response_log else "Success"
        }
    
    def _save_images(self, pil_images: List[Image.Image], model: str, params: Dict) -> List[Dict]:
        """Save images and return preview info."""
        preview_results = []
        
        # Try auto-save first
        try:
            from .save_settings import SaveSettings
            save_cfg = config_manager.get_save_settings()
            saver = SaveSettings(save_cfg)
            
            if saver.enabled:
                for i, img in enumerate(pil_images):
                    context = {
                        "model": model,
                        "seed": params.get("seed", 0),
                        "prompt": params.get("prompt", ""),
                        "batch": i + 1,
                    }
                    result = saver.save_image(img, context)
                    if result and "preview" in result:
                        preview_results.append(result["preview"])
        except Exception as e:
            print(f"[IndependentGenerator] AutoSave error: {e}")
        
        # Fall back to temp folder
        if not preview_results:
            temp_dir = folder_paths.get_temp_directory()
            
            for idx, img in enumerate(pil_images):
                filename = f"batchbox_independent_{uuid.uuid4().hex[:8]}_{idx}.png"
                filepath = os.path.join(temp_dir, filename)
                img.save(filepath, format="PNG")
                
                preview_results.append({
                    "filename": filename,
                    "subfolder": "",
                    "type": "temp"
                })
        
        return preview_results
