"""
ComfyUI-Custom-Batchbox Nodes

Provides dynamic parameter nodes for AI image generation.
Supports multiple API providers and model-specific parameter schemas.
"""

import os
import io
import json
import time
import base64
import requests
import torch
import numpy as np
import uuid
from PIL import Image
from io import BytesIO
from typing import Dict, List, Optional, Any, Tuple, Union

import folder_paths  # ComfyUI's folder paths helper

from .config_manager import config_manager
from .adapters.generic import GenericAPIAdapter
from .adapters.base import APIResponse
from .image_utils import prepare_for_comfyui, pil_to_tensor_rgba, get_image_info


def save_preview_images(images: List[Image.Image], prefix: str = "batchbox") -> List[Dict]:
    """
    Save images to ComfyUI's temp folder for preview.
    Returns list of image info dicts compatible with ComfyUI's UI format.
    """
    results = []
    temp_dir = folder_paths.get_temp_directory()
    
    for idx, img in enumerate(images):
        # Generate unique filename
        filename = f"{prefix}_{uuid.uuid4().hex[:8]}_{idx}.png"
        filepath = os.path.join(temp_dir, filename)
        
        # Save image
        img.save(filepath, format="PNG")
        
        results.append({
            "filename": filename,
            "subfolder": "",
            "type": "temp"
        })
    
    return results


def pil2tensor(image: Image.Image) -> torch.Tensor:
    """Convert PIL Image to tensor"""
    return torch.from_numpy(np.array(image).astype(np.float32) / 255.0).unsqueeze(0)


def tensor2pil(image: torch.Tensor) -> List[Image.Image]:
    """Convert tensor to PIL Image(s)"""
    return [Image.fromarray(np.clip(255. * image.cpu().numpy().squeeze(), 0, 255).astype(np.uint8))]


def bytes2tensor(img_bytes: bytes) -> torch.Tensor:
    """Convert image bytes to tensor"""
    img = Image.open(BytesIO(img_bytes))
    if img.mode != 'RGB':
        img = img.convert('RGB')
    return pil2tensor(img)


# ==========================================
# Base Node Class
# ==========================================
class DynamicImageNodeBase:
    """
    Base class for dynamic image generation nodes.
    
    Provides:
    - Dynamic parameter handling based on model selection
    - Multi-provider support with failover
    - Batch processing
    """
    
    CATEGORY = "ComfyUI-Custom-Batchbox"
    _endpoint_index = {}  # Class-level counter for round-robin: {model_name: index}
    
    def __init__(self):
        self.timeout = 600
    
    @classmethod
    def get_models_for_category(cls, category: str = "image") -> List[str]:
        """
        Get list of model names for a category.
        
        Args:
            category: Model category (e.g., 'image', 'text', 'video')
            
        Returns:
            List of model name strings. Returns ['No Models Found'] if none configured.
        """
        models = config_manager.get_models(category)
        if not models:
            return ["No Models Found"]
        return models
    
    @classmethod
    def get_model_display_names(cls, category: str = "image") -> Dict[str, str]:
        """Get mapping of model names to display names"""
        models_info = config_manager.get_models_by_category(category)
        return {m["name"]: m["display_name"] for m in models_info}
    
    def get_adapter(self, model_name: str, mode: str = "text2img", 
                     endpoint_override: Optional[str] = None) -> Optional[GenericAPIAdapter]:
        """
        Get API adapter for a model.
        
        In auto mode, uses round-robin to distribute requests across endpoints.
        In manual mode (endpoint_override specified), uses the specific endpoint.
        
        Args:
            model_name: Name of the model to get adapter for
            mode: API mode ('text2img' or 'img2img')
            endpoint_override: Optional specific endpoint display_name for manual selection
            
        Returns:
            GenericAPIAdapter instance if successful, None if no endpoint available.
        """
        if endpoint_override:
            # User manually selected a specific endpoint by display_name
            endpoint_info = config_manager.get_endpoint_by_name(model_name, endpoint_override, mode)
        else:
            # Auto mode: round-robin through all available endpoints
            endpoints = config_manager.get_api_endpoints(model_name)
            if not endpoints:
                print(f"[DynamicImageNode] No endpoints for {model_name}")
                return None
            
            # Get current index and rotate
            current_idx = DynamicImageNodeBase._endpoint_index.get(model_name, 0)
            endpoint_info = config_manager.get_endpoint_by_index(model_name, current_idx, mode)
            
            # Update index for next call (rotate)
            DynamicImageNodeBase._endpoint_index[model_name] = (current_idx + 1) % len(endpoints)
        
        if not endpoint_info:
            print(f"[DynamicImageNode] No endpoint found for {model_name}/{mode}")
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
        """
        Execute API request with automatic failover to alternative providers.
        
        If the primary endpoint fails, tries alternative endpoints in priority order.
        Failover is disabled when endpoint_override is specified (manual selection).
        
        Args:
            model_name: Name of the model to use
            params: Request parameters (prompt, size, etc.)
            mode: API mode ('text2img' or 'img2img')
            endpoint_override: Optional specific endpoint for manual selection
            
        Returns:
            APIResponse with success status and images/error message.
        """
        settings = config_manager.get_settings()
        auto_failover = settings.get("auto_failover", True)
        
        # If endpoint manually selected (has value), disable failover
        if endpoint_override:
            auto_failover = False
        
        # Try primary endpoint (or manually selected endpoint)
        adapter = self.get_adapter(model_name, mode, endpoint_override)
        if adapter:
            result = adapter.execute(params, mode)
            if result.success:
                return result
            print(f"[DynamicImageNode] Primary failed: {result.error_message}")
        
        # Try alternatives if failover enabled
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
                
                print(f"[DynamicImageNode] Trying alternative: {alt['provider'].name}")
                result = alt_adapter.execute(params, mode)
                
                if result.success:
                    return result
                print(f"[DynamicImageNode] Alternative failed: {result.error_message}")
        
        return APIResponse(
            success=False,
            error_message="All providers failed"
        )
    
    def process_batch(self, model_name: str, batch_count: int, 
                      params: Dict[str, Any], mode: str = "text2img",
                      endpoint_override: Optional[str] = None) -> Tuple[torch.Tensor, str, str]:
        """
        Process batch of image generation requests.
        
        Generates multiple images sequentially, combining them into a single tensor batch.
        Preserves preview images for the ComfyUI interface.
        
        Args:
            model_name: Name of the model to use
            batch_count: Number of images to generate
            params: Request parameters (prompt, size, etc.)
            mode: API mode ('text2img' or 'img2img')
            endpoint_override: Optional specific endpoint for manual selection
            
        Returns:
            Tuple of (image_tensor, response_log, last_image_url)
        """
        successful_tensors = []
        successful_pil_images = []  # Store PIL images for preview
        response_log = ""
        last_url = ""
        
        # Ensure seed is an integer (may come as string from extra_params)
        seed = params.get("seed", 0)
        try:
            seed = int(seed) if seed else 0
        except (ValueError, TypeError):
            seed = 0
        
        for i in range(batch_count):
            print(f"\n[Batch] {i+1}/{batch_count} - Model: {model_name}")
            
            # Update seed for each batch
            current_params = params.copy()
            if seed > 0:
                current_params["seed"] = seed + i
            
            result = self.execute_with_failover(model_name, current_params, mode, endpoint_override)
            
            if result.success:
                for img_bytes in result.images:
                    try:
                        # Convert bytes to PIL
                        pil_img = Image.open(BytesIO(img_bytes))
                        
                        # Use image_utils to preserve RGBA transparency
                        pil_img, mode = prepare_for_comfyui(pil_img, preserve_alpha=True)
                        
                        successful_pil_images.append(pil_img)
                        
                        # Use RGBA-aware tensor conversion
                        tensor = pil_to_tensor_rgba(pil_img)
                        successful_tensors.append(tensor)
                    except Exception as e:
                        response_log += f"Image decode error: {e}\n"
                
                if result.image_urls:
                    last_url = result.image_urls[-1]
            else:
                response_log += f"Batch {i+1} failed: {result.error_message}\n"
        
        if not successful_tensors:
            # Return black placeholder
            placeholder = Image.new('RGB', (512, 512), color='black')
            return (
                pil2tensor(placeholder),
                f"Generation failed.\n{response_log}",
                "",
                [placeholder]  # Return PIL image too
            )
        
        return (
            torch.cat(successful_tensors, dim=0),
            response_log if response_log else "Success",
            last_url,
            successful_pil_images  # Return PIL images for preview
        )


# ==========================================
# Image Generation Node
# ==========================================
class DynamicImageGenerationNode(DynamicImageNodeBase):
    """
    Dynamic Image Generation Node
    
    Features:
    - Model selection with dynamic parameter updates
    - Multi-provider support
    - Automatic failover
    - Batch processing
    """
    
    @classmethod
    def INPUT_TYPES(cls):
        models = cls.get_models_for_category("image")
        
        return {
            "required": {
                "model": (models, {"default": models[0] if models else None}),
                "prompt": ("STRING", {"multiline": True}),
                "batch_count": ("INT", {"default": 1, "min": 1, "max": 100}),
            },
            "optional": {
                # Parameters are now fully dynamic from YAML schema
                # Only keep essential static params
                "seed": ("INT", {"default": 0, "min": 0, "max": 2147483647}),
                "image1": ("IMAGE",),
            },
            "hidden": {
                # Extra dynamic parameters passed from frontend
                # Includes endpoint_override if manual selection enabled
                "extra_params": ("STRING", {"default": "{}"}),
            }
        }
    
    RETURN_TYPES = ("IMAGE", "STRING", "STRING")
    RETURN_NAMES = ("images", "response_info", "last_image_url")
    FUNCTION = "generate"
    CATEGORY = "ComfyUI-Custom-Batchbox"
    OUTPUT_NODE = True  # Enable preview in node
    
    def generate(self, model: str, prompt: str, batch_count: int, **kwargs) -> Dict:
        """Generate images using selected model"""
        
        # Determine mode
        has_image = any(
            k.startswith("image") and isinstance(v, torch.Tensor) 
            for k, v in kwargs.items() if v is not None
        )
        mode = "img2img" if has_image else "text2img"
        
        # Build base parameters (dynamic params will be merged from extra_params)
        params = {
            "prompt": prompt,
            "seed": kwargs.get("seed", 0),
        }
        
        # Parse extra dynamic parameters from frontend
        extra_params_str = kwargs.get("extra_params", "{}")
        print(f"[DEBUG] kwargs: {kwargs}")
        print(f"[DEBUG] extra_params_str: {extra_params_str}")
        try:
            extra_params = json.loads(extra_params_str)
            print(f"[DEBUG] extra_params parsed: {extra_params}")
            params.update(extra_params)
        except:
            pass
        
        # Ensure numeric fields are correct type (seed should be int, not string)
        if "seed" in params:
            try:
                params["seed"] = int(params["seed"])
            except (ValueError, TypeError):
                params["seed"] = 0
        
        print(f"[DEBUG] Final params: {params}")
        
        # Handle image inputs for img2img
        if mode == "img2img":
            upload_files = []
            for key, value in kwargs.items():
                if key.startswith("image") and isinstance(value, torch.Tensor):
                    pil_img = tensor2pil(value)[0]
                    buffered = BytesIO()
                    pil_img.save(buffered, format="PNG")
                    upload_files.append((key, (f'{key}.png', buffered.getvalue(), 'image/png')))
            params["_upload_files"] = upload_files
        
        # Get manual endpoint selection from extra_params (if enabled)
        endpoint_override = extra_params.get("endpoint_override", "")
        
        # Process batch and get results including PIL images
        images_tensor, response_info, last_url, pil_images = self.process_batch(
            model, batch_count, params, mode, endpoint_override
        )
        
        # Save preview images to temp folder
        preview_results = save_preview_images(pil_images, prefix="batchbox")
        
        # Auto-save images to output directory
        try:
            from .save_settings import SaveSettings
            from .config_manager import config_manager
            save_cfg = config_manager.get_save_settings()
            saver = SaveSettings(save_cfg)
            
            if saver.enabled and pil_images:
                for i, img in enumerate(pil_images):
                    context = {
                        "model": model,
                        "seed": params.get("seed", 0),
                        "prompt": params.get("prompt", ""),
                        "batch": i + 1,
                    }
                    saver.save_image(img, context)
        except Exception as e:
            print(f"[AutoSave] Error: {e}")
        
        # Return dict with both result tuple and UI data
        return {
            "ui": {"images": preview_results},
            "result": (images_tensor, response_info, last_url)
        }


# ==========================================
# Text Generation Node
# ==========================================
class DynamicTextGenerationNode(DynamicImageNodeBase):
    """
    Dynamic Text Generation Node
    
    Generates text content using LLM models.
    Supports streaming and various output formats.
    """
    
    CATEGORY = "ComfyUI-Custom-Batchbox"
    
    @classmethod
    def INPUT_TYPES(cls):
        models = cls.get_models_for_category("text")
        
        return {
            "required": {
                "model": (models, {"default": models[0] if models else None}),
                "prompt": ("STRING", {"multiline": True}),
            },
            "optional": {
                "system_prompt": ("STRING", {"multiline": True, "default": ""}),
                "max_tokens": ("INT", {"default": 2048, "min": 1, "max": 128000}),
                "temperature": ("FLOAT", {"default": 0.7, "min": 0.0, "max": 2.0, "step": 0.1}),
                "top_p": ("FLOAT", {"default": 0.9, "min": 0.0, "max": 1.0, "step": 0.05}),
            },
            "hidden": {
                "extra_params": ("STRING", {"default": "{}"}),
            }
        }
    
    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("text_output", "response_info")
    FUNCTION = "generate"
    
    def generate(self, model: str, prompt: str, **kwargs) -> Tuple:
        """Generate text using selected LLM model"""
        
        params = {
            "prompt": prompt,
            "system_prompt": kwargs.get("system_prompt", ""),
            "max_tokens": kwargs.get("max_tokens", 2048),
            "temperature": kwargs.get("temperature", 0.7),
            "top_p": kwargs.get("top_p", 0.9),
        }
        
        # Parse extra dynamic parameters
        extra_params_str = kwargs.get("extra_params", "{}")
        try:
            extra_params = json.loads(extra_params_str)
            params.update(extra_params)
        except:
            pass
        
        result = self.execute_with_failover(model, params, "text2text")
        
        if result.success:
            text_output = result.raw_response.get("choices", [{}])[0].get("message", {}).get("content", "")
            return (text_output, "Success")
        else:
            return ("", f"Generation failed: {result.error_message}")


# ==========================================
# Video Generation Node
# ==========================================
class DynamicVideoGenerationNode(DynamicImageNodeBase):
    """
    Dynamic Video Generation Node
    
    Supports text-to-video and image-to-video generation.
    """
    
    CATEGORY = "ComfyUI-Custom-Batchbox"
    
    @classmethod
    def INPUT_TYPES(cls):
        models = cls.get_models_for_category("video")
        
        return {
            "required": {
                "model": (models, {"default": models[0] if models else None}),
                "prompt": ("STRING", {"multiline": True}),
            },
            "optional": {
                "duration": ("FLOAT", {"default": 5.0, "min": 1.0, "max": 60.0, "step": 0.5}),
                "fps": ("INT", {"default": 24, "min": 8, "max": 60}),
                "resolution": (["720p", "1080p", "4K"], {"default": "1080p"}),
                "aspect_ratio": (["16:9", "9:16", "1:1", "4:3"], {"default": "16:9"}),
                "seed": ("INT", {"default": 0, "min": 0, "max": 2147483647}),
                "image1": ("IMAGE",),  # For image-to-video
            },
            "hidden": {
                "extra_params": ("STRING", {"default": "{}"}),
            }
        }
    
    RETURN_TYPES = ("STRING", "STRING", "STRING")
    RETURN_NAMES = ("video_url", "response_info", "task_id")
    FUNCTION = "generate"
    
    def generate(self, model: str, prompt: str, **kwargs) -> Tuple:
        """Generate video using selected model"""
        
        has_image = any(
            k.startswith("image") and isinstance(v, torch.Tensor)
            for k, v in kwargs.items() if v is not None
        )
        mode = "img2video" if has_image else "text2video"
        
        params = {
            "prompt": prompt,
            "duration": kwargs.get("duration", 5.0),
            "fps": kwargs.get("fps", 24),
            "resolution": kwargs.get("resolution", "1080p"),
            "aspect_ratio": kwargs.get("aspect_ratio", "16:9"),
            "seed": kwargs.get("seed", 0),
        }
        
        # Parse extra dynamic parameters
        extra_params_str = kwargs.get("extra_params", "{}")
        try:
            extra_params = json.loads(extra_params_str)
            params.update(extra_params)
        except:
            pass
        
        # Handle image inputs
        if mode == "img2video":
            upload_files = []
            for key, value in kwargs.items():
                if key.startswith("image") and isinstance(value, torch.Tensor):
                    pil_img = tensor2pil(value)[0]
                    buffered = BytesIO()
                    pil_img.save(buffered, format="PNG")
                    upload_files.append((key, (f'{key}.png', buffered.getvalue(), 'image/png')))
            params["_upload_files"] = upload_files
        
        result = self.execute_with_failover(model, params, mode)
        
        if result.success:
            video_url = result.image_urls[0] if result.image_urls else ""
            task_id = result.raw_response.get("task_id", "")
            return (video_url, "Success", str(task_id))
        else:
            return ("", f"Generation failed: {result.error_message}", "")


# ==========================================
# Audio Generation Node
# ==========================================
class DynamicAudioGenerationNode(DynamicImageNodeBase):
    """
    Dynamic Audio Generation Node (Beta)
    
    Supports text-to-speech, music generation, and voice cloning.
    """
    
    CATEGORY = "ComfyUI-Custom-Batchbox"
    
    @classmethod
    def INPUT_TYPES(cls):
        models = cls.get_models_for_category("audio")
        
        return {
            "required": {
                "model": (models, {"default": models[0] if models else None}),
                "prompt": ("STRING", {"multiline": True}),
            },
            "optional": {
                "voice": (["alloy", "echo", "fable", "onyx", "nova", "shimmer"], {"default": "alloy"}),
                "speed": ("FLOAT", {"default": 1.0, "min": 0.25, "max": 4.0, "step": 0.05}),
                "format": (["mp3", "wav", "flac", "aac"], {"default": "mp3"}),
                "duration": ("FLOAT", {"default": 30.0, "min": 1.0, "max": 300.0, "step": 1.0}),
            },
            "hidden": {
                "extra_params": ("STRING", {"default": "{}"}),
            }
        }
    
    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("audio_url", "response_info")
    FUNCTION = "generate"
    
    def generate(self, model: str, prompt: str, **kwargs) -> Tuple:
        """Generate audio using selected model"""
        
        params = {
            "prompt": prompt,
            "voice": kwargs.get("voice", "alloy"),
            "speed": kwargs.get("speed", 1.0),
            "format": kwargs.get("format", "mp3"),
            "duration": kwargs.get("duration", 30.0),
        }
        
        # Parse extra dynamic parameters
        extra_params_str = kwargs.get("extra_params", "{}")
        try:
            extra_params = json.loads(extra_params_str)
            params.update(extra_params)
        except:
            pass
        
        result = self.execute_with_failover(model, params, "text2audio")
        
        if result.success:
            audio_url = result.image_urls[0] if result.image_urls else ""
            return (audio_url, "Success")
        else:
            return ("", f"Generation failed: {result.error_message}")


# ==========================================
# Image Editor Node
# ==========================================
class DynamicImageEditorNode(DynamicImageNodeBase):
    """
    Dynamic Image Editor Node
    
    Supports inpainting, outpainting, upscaling, background removal, etc.
    """
    
    CATEGORY = "ComfyUI-Custom-Batchbox"
    
    @classmethod
    def INPUT_TYPES(cls):
        models = cls.get_models_for_category("image_editor")
        
        return {
            "required": {
                "model": (models, {"default": models[0] if models else None}),
                "image": ("IMAGE",),
                "operation": (["upscale", "inpaint", "outpaint", "remove_bg", "enhance", "restore"], {"default": "upscale"}),
            },
            "optional": {
                "prompt": ("STRING", {"multiline": True, "default": ""}),
                "scale": ("INT", {"default": 2, "min": 1, "max": 8}),
                "mask": ("MASK",),
                "strength": ("FLOAT", {"default": 0.75, "min": 0.0, "max": 1.0, "step": 0.05}),
            },
            "hidden": {
                "extra_params": ("STRING", {"default": "{}"}),
            }
        }
    
    RETURN_TYPES = ("IMAGE", "STRING", "STRING")
    RETURN_NAMES = ("edited_image", "response_info", "image_url")
    FUNCTION = "edit"
    
    def edit(self, model: str, image: torch.Tensor, operation: str, **kwargs) -> Tuple:
        """Edit image using selected model and operation"""
        
        # Prepare image for upload
        pil_img = tensor2pil(image)[0]
        buffered = BytesIO()
        pil_img.save(buffered, format="PNG")
        
        params = {
            "prompt": kwargs.get("prompt", ""),
            "operation": operation,
            "scale": kwargs.get("scale", 2),
            "strength": kwargs.get("strength", 0.75),
            "_upload_files": [("image", ("input.png", buffered.getvalue(), "image/png"))],
        }
        
        # Handle mask if provided
        mask = kwargs.get("mask")
        if mask is not None:
            mask_img = tensor2pil(mask.unsqueeze(-1).expand(-1, -1, -1, 3))[0]
            mask_buffered = BytesIO()
            mask_img.save(mask_buffered, format="PNG")
            params["_upload_files"].append(("mask", ("mask.png", mask_buffered.getvalue(), "image/png")))
        
        # Parse extra dynamic parameters
        extra_params_str = kwargs.get("extra_params", "{}")
        try:
            extra_params = json.loads(extra_params_str)
            params.update(extra_params)
        except:
            pass
        
        # Select mode based on operation
        mode = operation  # upscale, inpaint, outpaint, etc.
        
        result = self.execute_with_failover(model, params, mode)
        
        if result.success and result.images:
            output_tensor = bytes2tensor(result.images[0])
            url = result.image_urls[0] if result.image_urls else ""
            return (output_tensor, "Success", url)
        else:
            # Return original image on failure
            return (image, f"Edit failed: {result.error_message}", "")


# ==========================================
# Legacy Universal Node (Backward Compatibility)
# ==========================================
class NanoBananaPro(DynamicImageNodeBase):
    """
    Legacy universal node for backward compatibility.
    Maps to new dynamic system under the hood.
    """
    
    @classmethod
    def INPUT_TYPES(cls):
        # Use legacy preset-based approach
        presets = config_manager.get_presets()
        if not presets:
            presets = ["No Presets Found"]
        
        return {
            "required": {
                "preset": (presets, {"default": presets[0] if presets else None}),
                "auto_switch_provider": ("BOOLEAN", {"default": False, "label_on": "Enabled", "label_off": "Disabled"}),
                "batch_count": ("INT", {"default": 1, "min": 1, "max": 100}),
                "prompt": ("STRING", {"multiline": True}),
                "mode": (["auto", "text2img", "img2img"], {"default": "auto"}),
                "aspect_ratio": (["auto", "16:9", "4:3", "4:5", "3:2", "1:1", "2:3", "3:4", "5:4", "9:16", "21:9"], {"default": "auto"}),
                "image_size": (["1K", "2K", "4K"], {"default": "2K"}),
            },
            "optional": {
                "response_format": (["url", "b64_json"], {"default": "url"}),
                "seed": ("INT", {"default": 0, "min": 0, "max": 2147483647}),
                "webhook": ("STRING", {"default": ""}),
                "image1": ("IMAGE",),
            }
        }
    
    RETURN_TYPES = ("IMAGE", "STRING", "STRING")
    RETURN_NAMES = ("images", "response_info", "last_image_url")
    FUNCTION = "generate"
    CATEGORY = "ComfyUI-Custom-Batchbox"
    OUTPUT_NODE = True  # Enable preview in node
    
    def generate(self, preset: str, auto_switch_provider: bool, batch_count: int,
                 prompt: str, mode: str, aspect_ratio: str, image_size: str, **kwargs) -> Dict:
        """Generate using legacy preset interface"""
        
        # Determine actual mode
        if mode == "auto":
            has_image = any(
                k.startswith("image") and isinstance(v, torch.Tensor)
                for k, v in kwargs.items() if v is not None
            )
            mode = "img2img" if has_image else "text2img"
        
        # Build parameters
        params = {
            "prompt": prompt,
            "aspect_ratio": aspect_ratio,
            "resolution": image_size,
            "seed": kwargs.get("seed", 0),
            "response_format": kwargs.get("response_format", "url"),
        }
        
        # Handle image inputs
        if mode == "img2img":
            upload_files = []
            for key, value in kwargs.items():
                if key.startswith("image") and isinstance(value, torch.Tensor):
                    pil_img = tensor2pil(value)[0]
                    buffered = BytesIO()
                    pil_img.save(buffered, format="PNG")
                    upload_files.append((key, (f'{key}.png', buffered.getvalue(), 'image/png')))
            params["_upload_files"] = upload_files
        
        # Process batch and get results including PIL images
        images_tensor, response_info, last_url, pil_images = self.process_batch(preset, batch_count, params, mode)
        
        # Save preview images to temp folder
        preview_results = save_preview_images(pil_images, prefix="batchbox")
        
        # Return dict with both result tuple and UI data
        return {
            "ui": {"images": preview_results},
            "result": (images_tensor, response_info, last_url)
        }


# ==========================================
# Dynamic Node Factory
# ==========================================
def create_dynamic_node(preset_name: str, node_def: Dict):
    """Creates a node class dynamically from YAML definition"""
    
    class_name = node_def.get("class_name", f"DynamicNode_{preset_name}")
    display_name = node_def.get("display_name", class_name)
    params = node_def.get("parameters", {})
    
    # Process required parameters
    processed_required = {}
    if "required" in params:
        for k, v in params["required"].items():
            val_type = v.get("type", "STRING")
            opts = {key: val for key, val in v.items() if key != "type"}
            processed_required[k] = (val_type, opts)
    
    # Ensure batch_count exists
    if "batch_count" not in processed_required:
        processed_required["batch_count"] = ("INT", {"default": 1, "min": 1, "max": 100})
    
    # Process optional parameters
    processed_optional = {}
    if "optional" in params:
        for k, v in params["optional"].items():
            val_type = v.get("type", "STRING")
            opts = {key: val for key, val in v.items() if key != "type"}
            processed_optional[k] = (val_type, opts)
    
    class DynamicNodeClass(DynamicImageNodeBase):
        @classmethod
        def INPUT_TYPES(cls):
            return {
                "required": processed_required,
                "optional": processed_optional
            }
        
        RETURN_TYPES = ("IMAGE", "STRING", "STRING")
        RETURN_NAMES = ("images", "response_info", "last_image_url")
        FUNCTION = "execute_dynamic"
        CATEGORY = "ComfyUI-Custom-Batchbox/Dynamic"
        
        def execute_dynamic(self, **kwargs):
            batch_count = kwargs.pop("batch_count", 1)
            prompt = kwargs.pop("prompt", "")
            
            # Determine mode
            has_image = any(
                k.startswith("image") and isinstance(v, torch.Tensor)
                for k, v in kwargs.items() if v is not None
            )
            mode = "img2img" if has_image else "text2img"
            
            params = {"prompt": prompt, **kwargs}
            return self.process_batch(preset_name, batch_count, params, mode)
    
    DynamicNodeClass.__name__ = class_name
    return class_name, display_name, DynamicNodeClass
