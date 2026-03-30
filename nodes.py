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
import logging
import requests
import torch
import numpy as np
import uuid
import hashlib
from PIL import Image
from io import BytesIO
from typing import Dict, List, Optional, Any, Tuple, Union
from .adapters.base import APIResponse

import folder_paths  # ComfyUI's folder paths helper

from .config_manager import config_manager
from .adapters.generic import GenericAPIAdapter
from .adapters.base import APIResponse
from .image_utils import prepare_for_comfyui, pil_to_tensor_rgba, get_image_info

logger = logging.getLogger("batchbox")


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


def _safe_join_under(base_dir: str, *parts: str) -> Optional[str]:
    """Resolve a path under base_dir and reject traversal/escape attempts."""
    try:
        base_path = os.path.abspath(base_dir)
        resolved = os.path.abspath(os.path.join(base_path, *[str(p or "") for p in parts]))
        if os.path.commonpath([base_path, resolved]) != base_path:
            return None
        return resolved
    except ValueError:
        return None


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
    _image_cache = {}  # Class-level cache for loaded images: {cache_key: (tensor, preview_infos)}
    
    def __init__(self):
        self.timeout = 600

    @staticmethod
    def _parse_extra_params(extra_params_raw: Any) :
        """Parse dynamic params payload safely, returning a dict."""
        if isinstance(extra_params_raw, dict):
            return dict(extra_params_raw)
        if not extra_params_raw:
            return {}
        if not isinstance(extra_params_raw, str):
            return {}
        try:
            parsed = json.loads(extra_params_raw)
        except (json.JSONDecodeError, TypeError):
            return {}
        return parsed if isinstance(parsed, dict) else {}

    @staticmethod
    def _compute_image_inputs_hash(kwargs: Dict[str, Any]) -> str:
        """
        Compute a deterministic hash for IMAGE inputs in kwargs.
        This prevents smart-cache false hits when image content changes.
        """
        import hashlib

        image_keys = sorted(
            k for k, v in kwargs.items()
            if k.startswith("image") and isinstance(v, torch.Tensor) and v is not None
        )
        if not image_keys:
            return ""

        hasher = hashlib.md5()
        for key in image_keys:
            tensor = kwargs[key]
            hasher.update(key.encode("utf-8"))
            hasher.update(str(tuple(tensor.shape)).encode("utf-8"))
            try:
                tensor_uint8 = (
                    tensor.detach()
                    .cpu()
                    .clamp(0, 1)
                    .mul(255)
                    .to(torch.uint8)
                    .contiguous()
                )
                hasher.update(memoryview(tensor_uint8.numpy()))
            except Exception as e:
                # Keep hash deterministic even if conversion fails.
                hasher.update(f"tensor_error:{e}".encode("utf-8"))

        return hasher.hexdigest()
    
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
    def get_model_display_names(cls, category: str = "image") :
        """Get mapping of model names to display names"""
        models_info = config_manager.get_models_by_category(category)
        return {m["name"]: m["display_name"] for m in models_info}
    
    def _build_adapter_from_endpoint_info(self, endpoint_info: Optional[Dict[str, Any]]) -> Optional[GenericAPIAdapter]:
        """Create the correct adapter class for a resolved endpoint."""
        if not endpoint_info:
            return None

        provider = endpoint_info["provider"]
        mode_config = endpoint_info["config"]
        endpoint_config = endpoint_info["endpoint_config"]

        api_format = endpoint_config.get("api_format", "")
        if api_format == "volcengine":
            from .adapters.volcengine import VolcengineAdapter
            return VolcengineAdapter(
                provider_config={
                    "name": provider.name,
                    "base_url": provider.base_url,
                    "access_key": provider.access_key,
                    "secret_key": provider.secret_key
                },
                endpoint_config=endpoint_config,
                mode_config=mode_config
            )

        return GenericAPIAdapter(
            provider_config={
                "name": provider.name,
                "base_url": provider.base_url,
                "api_key": provider.api_key,
                "api_keys": provider.api_keys or [],
                "project_id": provider.project_id or "",
            },
            endpoint_config=endpoint_config,
            mode_config=mode_config
        )

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
            # Auto mode: check setting for strategy
            node_settings = config_manager.get_node_settings()
            auto_mode = node_settings.get("auto_endpoint_mode", "random")
            
            if auto_mode == "round_robin":
                # Round-robin: rotate through all available endpoints
                endpoints = config_manager.get_api_endpoints(model_name)
                if not endpoints:
                    print(f"[DynamicImageNode] No endpoints for {model_name}")
                    return None
                current_idx = DynamicImageNodeBase._endpoint_index.get(model_name, 0)
                endpoint_info = config_manager.get_endpoint_by_index(model_name, current_idx, mode)
                DynamicImageNodeBase._endpoint_index[model_name] = (current_idx + 1) % len(endpoints)
            elif auto_mode == "random":
                # Random: randomly pick an endpoint for even distribution across machines
                import random
                endpoints = config_manager.get_api_endpoints(model_name)
                if not endpoints:
                    print(f"[DynamicImageNode] No endpoints for {model_name}")
                    return None
                random_idx = random.randrange(len(endpoints))
                endpoint_info = config_manager.get_endpoint_by_index(model_name, random_idx, mode)
            else:
                # Priority mode: always use highest priority endpoint
                endpoint_info = config_manager.get_best_endpoint(model_name, mode)
        
        if not endpoint_info:
            print(f"[DynamicImageNode] No endpoint found for {model_name}/{mode}")
            return None
        
        provider = endpoint_info["provider"]
        mode_config = endpoint_info["config"]
        endpoint_config = endpoint_info["endpoint_config"]
        ep_display = endpoint_config.get("display_name") or provider.name
        print(f"[DynamicImageNode] 🎯 Using endpoint: {ep_display} ({'manual' if endpoint_override else 'auto'})")
        
        return self._build_adapter_from_endpoint_info(endpoint_info)
    
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
        
        # Inject model display name for Account model ID resolution
        params["_model_display_name"] = model_name
        
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
                alt_adapter = self._build_adapter_from_endpoint_info(alt)
                
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
                      endpoint_override: Optional[str] = None) :
        """
        Process batch of image generation requests in parallel.
        
        Generates multiple images concurrently using ThreadPoolExecutor,
        combining them into a single tensor batch.
        
        Args:
            model_name: Name of the model to use
            batch_count: Number of images to generate
            params: Request parameters (prompt, size, etc.)
            mode: API mode ('text2img' or 'img2img')
            endpoint_override: Optional specific endpoint for manual selection
            
        Returns:
            Tuple of (image_tensor, response_log, last_image_url, pil_images)
        """
        from concurrent.futures import ThreadPoolExecutor, as_completed
        
        successful_results = []  # Store (batch_idx, tensors, pil_images, url, log)
        
        # Security Hardening: Clamp batch_count to prevent thread pool exhaustion 
        # (e.g., if bypassed via primitive inputs or direct API)
        batch_count = max(1, min(int(batch_count), 20))
        
        # Ensure seed is an integer (may come as string from extra_params)
        seed = params.get("seed", 0)
        try:
            seed = int(seed) if seed else 0
        except (ValueError, TypeError):
            seed = 0
        
        def process_single_batch(batch_idx: int):
            """Process a single batch request and return decoded results."""
            print(f"\n[Batch] {batch_idx+1}/{batch_count} - Model: {model_name}")
            
            current_params = params.copy()
            current_seed = seed + batch_idx if seed > 0 else 0
            if current_seed > 0:
                current_params["seed"] = current_seed
            
            result = self.execute_with_failover(model_name, current_params, mode, endpoint_override)
            
            batch_tensors = []
            batch_pil_images = []
            batch_log = ""
            batch_url = ""
            
            if result.success:
                for img_bytes in result.images:
                    try:
                        pil_img = Image.open(BytesIO(img_bytes))
                        pil_img, _ = prepare_for_comfyui(pil_img, preserve_alpha=True)
                        batch_pil_images.append(pil_img)
                        tensor = pil_to_tensor_rgba(pil_img)
                        batch_tensors.append(tensor)
                    except Exception as e:
                        batch_log += f"Image decode error: {e}\n"
                
                if result.image_urls:
                    batch_url = result.image_urls[-1]
            else:
                batch_log += f"Batch {batch_idx+1} failed: {result.error_message}\n"
            
            return (batch_idx, batch_tensors, batch_pil_images, batch_url, batch_log)
        
        # Run all batches in parallel
        with ThreadPoolExecutor(max_workers=batch_count) as executor:
            futures = [executor.submit(process_single_batch, i) for i in range(batch_count)]
            for future in as_completed(futures):
                try:
                    successful_results.append(future.result())
                except Exception as e:
                    print(f"[Batch] Thread error: {e}")
        
        # Sort by batch index to maintain order
        successful_results.sort(key=lambda x: x[0])
        
        # Combine results
        all_tensors = []
        all_pil_images = []
        response_log = ""
        last_url = ""
        
        for batch_idx, tensors, pil_images, url, log in successful_results:
            all_tensors.extend(tensors)
            all_pil_images.extend(pil_images)
            response_log += log
            if url:
                last_url = url
        
        if not all_tensors:
            # Return black placeholder
            placeholder = Image.new('RGB', (512, 512), color='black')
            return (
                pil2tensor(placeholder),
                f"Generation failed.\n{response_log}",
                "",
                [placeholder]
            )
        
        # Normalize tensor dimensions before concatenation
        # All tensors must have same H,W dimensions to concatenate on dim=0
        # Use the LARGEST dimensions in the batch to avoid quality loss
        if len(all_tensors) > 1:
            max_h = max(t.shape[1] for t in all_tensors)
            max_w = max(t.shape[2] for t in all_tensors)
            
            normalized_tensors = []
            for i, tensor in enumerate(all_tensors):
                if tensor.shape[1] != max_h or tensor.shape[2] != max_w:
                    # Resize tensor to match max dimensions
                    print(f"[Batch] Resizing image {i} from {tensor.shape[1]}x{tensor.shape[2]} to {max_h}x{max_w}")
                    img_np = (tensor.squeeze(0).cpu().numpy() * 255).astype(np.uint8)
                    pil_img = Image.fromarray(img_np)
                    pil_img = pil_img.resize((max_w, max_h), Image.Resampling.LANCZOS)
                    normalized_tensors.append(pil_to_tensor_rgba(pil_img))
                else:
                    normalized_tensors.append(tensor)
            all_tensors = normalized_tensors
        
        return (
            torch.cat(all_tensors, dim=0),
            response_log if response_log else "Success",
            last_url,
            all_pil_images
        )
    
    def _compute_params_hash(self, model: str, prompt: str, batch_count: int, kwargs: Dict) -> str:
        """
        Compute a hash of generation parameters to detect changes.
        Used to skip API call when parameters haven't changed.
        """
        import hashlib
        import json
        
        # Get extra_params (dynamic parameters from frontend)
        extra_params_str = kwargs.get("extra_params", "{}")
        seed = kwargs.get("seed", 0)
        
        # Parse extra_params and remove seed (we use kwargs.seed separately)
        # This ensures consistent hashing between frontend and backend
        extra_params = self._parse_extra_params(extra_params_str)
        hash_extras = kwargs.get("_hash_extras")
        if isinstance(hash_extras, dict):
            extra_params.update(hash_extras)
        extra_params.pop("seed", None)  # Remove seed from extra_params
        # Use separators without spaces to match JavaScript JSON.stringify
        extra_params_normalized = json.dumps(extra_params, sort_keys=True, separators=(',', ':'))
        image_inputs_hash = self._compute_image_inputs_hash(kwargs)

        # Build hash string from all relevant parameters
        # Note: Seed is handled separately, not from extra_params.
        # Include image_inputs_hash to avoid cache reuse across different input images.
        params_str = f"{model}|{prompt}|{batch_count}|{seed}|{extra_params_normalized}|{image_inputs_hash}"
        result_hash = hashlib.md5(params_str.encode()).hexdigest()
        logger.debug("[Hash] input=%s", params_str)
        logger.debug("[Hash] computed=%s", result_hash)
        return result_hash
    
    def _load_persisted_images(self, last_images_json: str, selected_index: int = 0, load_all: bool = False) :
        """
        Load images from persisted file paths based on connection status.
        
        Memory optimization: Only loads all images if all_images output is connected.
        For 4K images (2688x6336), each takes ~195MB as float32 tensor.
        
        Args:
            last_images_json: JSON string of image info list
            selected_index: Index of the image to load (0-based)
            load_all: If True, load all images (when all_images output is connected)
            
        Returns:
            Tuple of (selected_tensor, all_tensors, preview_infos) or (None, None, []) if fails
        """
        if not last_images_json:
            return None, None, []
        
        try:
            image_infos = json.loads(last_images_json)
            if not image_infos or not isinstance(image_infos, list):
                return None, None, []
            
            # Clamp index to valid range
            selected_index = max(0, min(selected_index, len(image_infos) - 1))
            
            def load_single_image(info):
                """Helper to load a single image from info dict"""
                img_type = info.get("type", "output")
                subfolder = info.get("subfolder", "")
                filename = info.get("filename", "")
                
                if not filename:
                    return None
                
                if img_type == "output":
                    base_dir = folder_paths.get_output_directory()
                elif img_type == "temp":
                    base_dir = folder_paths.get_temp_directory()
                else:
                    base_dir = folder_paths.get_input_directory()
                
                filepath = _safe_join_under(base_dir, subfolder, filename)
                if not filepath:
                    logger.warning(
                        "[SmartCache] Rejected cached image path outside base dir: type=%s subfolder=%r filename=%r",
                        img_type,
                        subfolder,
                        filename,
                    )
                    return None
                
                if not os.path.exists(filepath):
                    print(f"[SmartCache] File not found: {filepath}")
                    return None
                
                try:
                    img = Image.open(filepath)
                    img, _ = prepare_for_comfyui(img, preserve_alpha=True)
                    return pil_to_tensor_rgba(img)
                except Exception as e:
                    print(f"[SmartCache] Failed to load {filepath}: {e}")
                    return None
            
            if load_all:
                # Load all images (all_images output is connected)
                tensors = []
                for i, info in enumerate(image_infos):
                    tensor = load_single_image(info)
                    if tensor is not None:
                        tensors.append(tensor)

                if not tensors:
                    return None, None, []

                # Normalize cached tensor sizes before concatenation.
                # Mixed-size outputs can happen across providers or model settings.
                if len(tensors) > 1:
                    import torch.nn.functional as F

                    max_h = max(t.shape[1] for t in tensors)
                    max_w = max(t.shape[2] for t in tensors)
                    normalized_tensors = []
                    for i, tensor in enumerate(tensors):
                        if tensor.shape[1] != max_h or tensor.shape[2] != max_w:
                            print(
                                f"[SmartCache] Resizing cached image {i} from "
                                f"{tensor.shape[1]}x{tensor.shape[2]} to {max_h}x{max_w}"
                            )
                            tensor_nchw = tensor.movedim(-1, 1)  # NHWC -> NCHW
                            resized_nchw = F.interpolate(
                                tensor_nchw,
                                size=(max_h, max_w),
                                mode="bilinear",
                                align_corners=False,
                            )
                            tensor = resized_nchw.movedim(1, -1)  # NCHW -> NHWC
                        normalized_tensors.append(tensor)
                    tensors = normalized_tensors

                all_tensor = torch.cat(tensors, dim=0)
                selected_tensor = tensors[selected_index] if selected_index < len(tensors) else tensors[0]
                print(f"[SmartCache] Loaded all {len(tensors)} images (all_images connected)")
                return selected_tensor, all_tensor, image_infos
            else:
                # Load only selected image (memory optimization)
                tensor = load_single_image(image_infos[selected_index])
                if tensor is None:
                    return None, None, []
                
                print(f"[SmartCache] Loaded image {selected_index+1}/{len(image_infos)} (memory optimized)")
                return tensor, tensor, image_infos  # Same tensor for both outputs
            
        except json.JSONDecodeError as e:
            print(f"[SmartCache] JSON parse error: {e}")
            return None, None, []
        except Exception as e:
            print(f"[SmartCache] Unexpected error: {e}")
            return None, None, []


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
                "batch_count": ("INT", {"default": 1, "min": 1, "max": 20}),
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
                # Last generated images for preview persistence
                "_last_images": ("STRING", {"default": ""}),
                # Hash of parameters when last generated (for smart skip)
                "_cached_hash": ("STRING", {"default": ""}),
                # Force generation flag (set by button trigger)
                "_force_generate": ("STRING", {"default": "false"}),
                # Skip hash check flag (based on setting)
                "_skip_hash_check": ("STRING", {"default": "false"}),
                # Hard bypass for global Queue Prompt on button-driven nodes
                "_bypass_queue_prompt": ("STRING", {"default": "false"}),
                # Selected image index for batch output (0-based)
                "_selected_image_index": ("INT", {"default": 0}),
                # Whether all_images output is connected (for lazy loading)
                "_all_images_connected": ("STRING", {"default": "false"}),
            }
        }
    
    RETURN_TYPES = ("IMAGE", "IMAGE", "STRING", "STRING")
    RETURN_NAMES = ("selected_image", "all_images", "response_info", "last_image_url")
    FUNCTION = "generate"
    CATEGORY = "ComfyUI-Custom-Batchbox"
    OUTPUT_NODE = True  # Required for standalone execution
    
    def generate(self, model: str, prompt: str, batch_count: int, **kwargs) :
        """Generate images using selected model"""
        
        # ==========================================
        # SMART CACHE: Check if API call is needed
        # ==========================================
        last_images_json = kwargs.get("_last_images", "")
        force_generate = kwargs.get("_force_generate", "false") == "true"
        cached_hash = kwargs.get("_cached_hash", "")
        extra_params_str = kwargs.get("extra_params", "{}")
        skip_hash_check = kwargs.get("_skip_hash_check", "false") == "true"
        bypass_queue_prompt = kwargs.get("_bypass_queue_prompt", "false") == "true"
        current_hash = cached_hash
        extra_params = self._parse_extra_params(extra_params_str)
        if extra_params_str and not extra_params:
            print("[SmartCache] Failed to parse extra_params, using empty dict")
        
        # Edge case: If extra_params is empty "{}" but we have cache,
        # it means dynamic params aren't loaded yet after restart.
        # Trust the cache in this case - don't try to compute/compare hash.
        params_not_loaded = (extra_params_str == "{}" and last_images_json and cached_hash)
        
        if bypass_queue_prompt and last_images_json and not force_generate:
            need_api_call = False
            print("[SmartCache] Queue Prompt bypass active with persisted cache")
        elif params_not_loaded or skip_hash_check:
            # Either params not loaded yet OR hash check disabled in settings
            # Just check if we have cache and not forced
            need_api_call = force_generate or not last_images_json
            reason = "params not loaded" if params_not_loaded else "hash check disabled"
            print(f"[SmartCache] {reason}, has_cache={bool(last_images_json)}, force={force_generate}")
        else:
            # Normal case: compute hash and compare
            current_hash = self._compute_params_hash(model, prompt, batch_count, kwargs)
            need_api_call = (
                force_generate or
                not last_images_json or
                (cached_hash and current_hash != cached_hash)
            )
            print(f"[SmartCache] force={force_generate}, has_cache={bool(last_images_json)}, hash_match={current_hash == cached_hash if cached_hash else 'N/A'}")
        
        print(f"[SmartCache] need_api_call={need_api_call}")
        
        if not need_api_call:
            # Parse selected index and connection status BEFORE loading
            selected_index = kwargs.get("_selected_image_index", 0)
            all_images_connected = kwargs.get("_all_images_connected", "false") == "true"
            print(f"[SmartCache] _selected_image_index={selected_index}, _all_images_connected={all_images_connected}")
            try:
                selected_index = int(selected_index)
            except (ValueError, TypeError):
                selected_index = 0
            
            # Dynamic loading: load all only if all_images output is connected
            selected_tensor, all_tensor, preview_results = self._load_persisted_images(
                last_images_json, selected_index, load_all=all_images_connected
            )
            if selected_tensor is not None:
                print(f"[SmartCache] Returning image(s) from cache")
                
                return {
                    "ui": {
                        "images": preview_results,
                        "_last_images": [last_images_json],
                        "_cached_hash": [cached_hash],  # Preserve the cached hash
                    },
                    "result": (selected_tensor, all_tensor, "Loaded from cache (no API call)", "")
                }
            # If loading failed, fall through to API call
            print(f"[SmartCache] Cache file not found, falling back to API")
        
        # ==========================================
        # NORMAL GENERATION: Call API
        # ==========================================
        
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
        logger.debug("[Generate] kwargs=%s", kwargs)
        logger.debug("[Generate] extra_params_str=%s", extra_params_str)
        logger.debug("[Generate] extra_params=%s", extra_params)
        params.update(extra_params)
        
        # Ensure numeric fields are correct type (seed should be int, not string)
        if "seed" in params:
            try:
                params["seed"] = int(params["seed"])
            except (ValueError, TypeError):
                params["seed"] = 0
        
        logger.debug("[Generate] final_params=%s", params)
        
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
        
        # Try auto-save first and use saved paths for preview (persists after restart)
        preview_results = []
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
                    result = saver.save_image(img, context)
                    if result and "preview" in result:
                        preview_results.append(result["preview"])
        except Exception as e:
            print(f"[AutoSave] Error: {e}")
        
        # Fall back to temp folder if auto-save disabled or failed
        if not preview_results and pil_images:
            preview_results = save_preview_images(pil_images, prefix="batchbox")
        
        # Serialize preview info for persistence (frontend will save to widget)
        last_images_json = json.dumps(preview_results) if preview_results else ""
        
        # Slice tensor based on selected image index (default to 0 for new generation)
        selected_index = kwargs.get("_selected_image_index", 0)
        try:
            selected_index = int(selected_index)
        except (ValueError, TypeError):
            selected_index = 0
        
        if images_tensor.shape[0] > 1:
            selected_index = max(0, min(selected_index, images_tensor.shape[0] - 1))
            selected_tensor = images_tensor[selected_index:selected_index+1]
        else:
            selected_tensor = images_tensor
        
        print(f"[Generate] Returning selected image {selected_index} of {images_tensor.shape[0]}")
        
        # Persist a stable hash for subsequent smart-cache comparison.
        current_hash = self._compute_params_hash(model, prompt, batch_count, kwargs)
        
        # Return dict with both result tuple and UI data
        return {
            "ui": {
                "images": preview_results,
                "_last_images": [last_images_json],  # Will be saved to widget by frontend
                "_cached_hash": [current_hash],  # Save hash for smart cache comparison
            },
            "result": (selected_tensor, images_tensor, response_info, last_url)
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
    
    def generate(self, model: str, prompt: str, **kwargs) :
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
        params.update(self._parse_extra_params(extra_params_str))
        
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
    
    def generate(self, model: str, prompt: str, **kwargs) :
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
        params.update(self._parse_extra_params(extra_params_str))
        
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
    
    def generate(self, model: str, prompt: str, **kwargs) :
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
        params.update(self._parse_extra_params(extra_params_str))
        
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
                "image1": ("IMAGE",),
                "mask": ("MASK",),
            },
            "optional": {
                "prompt": ("STRING", {"multiline": True, "default": ""}),
                "batch_count": ("INT", {"default": 1, "min": 1, "max": 20, "step": 1}),
            },
            "hidden": {
                "extra_params": ("STRING", {"default": "{}"}),
            }
        }
    
    RETURN_TYPES = ("IMAGE", "STRING", "STRING")
    RETURN_NAMES = ("edited_image", "response_info", "image_url")
    FUNCTION = "edit"
    OUTPUT_NODE = True  # Show preview inline like DynamicImageGeneration
    
    def edit(self, model: str, image1, mask=None, **kwargs) :
        """Edit image using selected model — supports 1 image + 1 mask"""
        operation = "inpaint"
        
        # Volcengine limits: max 4.7MB per image, max 4096x4096 resolution
        MAX_DIMENSION = 4096
        MAX_FILE_SIZE = int(4.7 * 1024 * 1024)  # 4.7MB
        
        def resize_if_needed(pil_img, max_dim=MAX_DIMENSION):
            """Resize image if any dimension exceeds max_dim"""
            w, h = pil_img.size
            if w > max_dim or h > max_dim:
                ratio = min(max_dim / w, max_dim / h)
                new_w, new_h = int(w * ratio), int(h * ratio)
                pil_img = pil_img.resize((new_w, new_h), Image.LANCZOS)
            return pil_img
        
        def compress_image(pil_img, max_size=MAX_FILE_SIZE):
            """Compress image: try PNG first (lossless), fall back to JPEG if over max_size"""
            buf = BytesIO()
            pil_img.save(buf, format="PNG")
            if buf.tell() <= max_size:
                return buf.getvalue(), "png"
            for quality in [95, 85, 70, 55]:
                buf = BytesIO()
                pil_img.save(buf, format="JPEG", quality=quality)
                if buf.tell() <= max_size:
                    return buf.getvalue(), "jpg"
            buf = BytesIO()
            pil_img.save(buf, format="JPEG", quality=55)
            return buf.getvalue(), "jpg"
        
        # Process the single input image
        pil_img = tensor2pil(image1)[0]
        pil_img = resize_if_needed(pil_img)
        img_bytes, fmt = compress_image(pil_img)
        mime = "image/png" if fmt == "png" else "image/jpeg"
        upload_files = [("image1", (f"image1.{fmt}", img_bytes, mime))]
        
        params = {
            "prompt": kwargs.get("prompt", ""),
            "operation": operation,
            "_upload_files": upload_files,
        }
        
        # Handle mask — MUST be after image in _upload_files for Volcengine
        # Volcengine expects binary_data_base64 = [image, mask]
        # Mask format per docs: 8-bit grayscale PNG, no ICC profile
        if mask is not None:
            if mask.dim() == 3:
                mask_2d = mask[0]
            else:
                mask_2d = mask
            # Volcengine: white (255) = edit area, black (0) = keep area
            # ComfyUI: 1.0 = masked/edit, 0.0 = visible/keep → same direction ✓
            # CRITICAL: Threshold to pure black/white to prevent API from modifying non-masked areas
            mask_np = mask_2d.cpu().numpy()
            mask_np = ((mask_np > 0.5) * 255).astype("uint8")  # Binary threshold
            mask_img = Image.fromarray(mask_np, mode="L")
            
            # Resize mask to match image dimensions
            if upload_files:
                img_bytes = upload_files[0][1][1]
                ref_img = Image.open(BytesIO(img_bytes))
                if mask_img.size != ref_img.size:
                    mask_img = mask_img.resize(ref_img.size, Image.NEAREST)
            
            # Save as 8-bit grayscale PNG without ICC profile
            mask_buffered = BytesIO()
            mask_img.save(mask_buffered, format="PNG", icc_profile=None)
            params["_upload_files"].append(("mask", ("mask.png", mask_buffered.getvalue(), "image/png")))
        
        # Parse extra dynamic parameters
        extra_params_str = kwargs.get("extra_params", "{}")
        params.update(self._parse_extra_params(extra_params_str))
        
        # All editor operations use img2img mode
        mode = "img2img"
        batch_count = kwargs.get("batch_count", 1)
        
        # Prepare mask compositing data once (shared across all batch items)
        original_pil = tensor2pil(image1)[0].convert("RGB")
        mask_binary = None
        if mask is not None:
            if mask.dim() == 3:
                mask_float = mask[0].cpu().numpy()
            else:
                mask_float = mask.cpu().numpy()
            mask_binary = (mask_float > 0.5).astype(np.float32)
        
        def composite_result(result_pil, orig_pil, m_binary):
            """Composite original + edited using mask to prevent color shift"""
            if m_binary is None:
                return result_pil
            result_w, result_h = result_pil.size
            mb = m_binary.copy()
            if mb.shape[0] != result_h or mb.shape[1] != result_w:
                mp = Image.fromarray((mb * 255).astype("uint8"), mode="L")
                mp = mp.resize((result_w, result_h), Image.NEAREST)
                mb = np.array(mp).astype(np.float32) / 255.0
            op = orig_pil
            if op.size != result_pil.size:
                op = op.resize(result_pil.size, Image.LANCZOS)
            orig_np = np.array(op).astype(np.float32)
            edit_np = np.array(result_pil).astype(np.float32)
            mask_3d = mb[:, :, np.newaxis]
            composited = (orig_np * (1 - mask_3d) + edit_np * mask_3d).clip(0, 255).astype("uint8")
            return Image.fromarray(composited)
        
        # Execute batch sequentially (API concurrent limit = 1, entire lifecycle)
        # With 429 auto-retry: if rate limited, wait and retry automatically
        import time
        
        def execute_with_retry(attempt_num):
            """Execute with automatic 429 retry"""
            max_retries = 3
            for retry in range(max_retries + 1):
                result = self.execute_with_failover(model, params, mode)
                if result.success:
                    return result
                # Check for 429 rate limit
                if "429" in str(result.error_message) and retry < max_retries:
                    wait = 3 * (2 ** retry)  # 3s, 6s, 12s
                    print(f"[Editor] Rate limited, retrying in {wait}s... ({retry+1}/{max_retries})")
                    time.sleep(wait)
                    continue
                return result
            return result
        
        results = []
        for i in range(batch_count):
            print(f"[Editor] Generating {i+1}/{batch_count}...")
            results.append(execute_with_retry(i))
        
        # Process all results
        output_tensors = []
        all_previews = []
        all_urls = []
        success_count = 0
        
        for i, result in enumerate(results):
            if result.success and result.images:
                result_pil = Image.open(BytesIO(result.images[0])).convert("RGB")
                result_pil = composite_result(result_pil, original_pil, mask_binary)
                output_tensors.append(pil2tensor(result_pil))
                all_urls.append(result.image_urls[0] if result.image_urls else "")
                success_count += 1
                
                # Auto-save
                try:
                    from .save_settings import SaveSettings
                    from .config_manager import config_manager
                    save_cfg = config_manager.get_save_settings()
                    saver = SaveSettings(save_cfg)
                    if saver.enabled:
                        context = {"model": model, "seed": i, "prompt": kwargs.get("prompt", ""), "batch": batch_count}
                        save_result = saver.save_image(result_pil, context)
                        if save_result and "preview" in save_result:
                            all_previews.append(save_result["preview"])
                            continue
                except Exception as e:
                    print(f"[Editor AutoSave] Error: {e}")
                all_previews.extend(save_preview_images([result_pil], prefix="editor_result"))
            else:
                print(f"[Editor] Batch {i+1}/{batch_count} failed: {result.error_message}")
        
        if output_tensors:
            # Concatenate all results into batch tensor
            batch_tensor = torch.cat(output_tensors, dim=0)
            url_str = " | ".join(all_urls) if all_urls else ""
            info = f"Success: {success_count}/{batch_count}"
            
            return {
                "ui": {"images": all_previews},
                "result": (batch_tensor, info, url_str)
            }
        else:
            error_msgs = [r.error_message for r in results if not r.success]
            return {
                "ui": {"images": []},
                "result": (image1, f"All {batch_count} edits failed: {'; '.join(error_msgs)}", "")
            }


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
                "batch_count": ("INT", {"default": 1, "min": 1, "max": 20}),
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
    OUTPUT_NODE = True  # Required for standalone execution
    
    def generate(self, preset: str, auto_switch_provider: bool, batch_count: int,
                 prompt: str, mode: str, aspect_ratio: str, image_size: str, **kwargs) :
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
        
        # Try auto-save first and use saved paths for preview (persists after restart)
        preview_results = []
        try:
            from .save_settings import SaveSettings
            from .config_manager import config_manager
            save_cfg = config_manager.get_save_settings()
            saver = SaveSettings(save_cfg)
            
            if saver.enabled and pil_images:
                for i, img in enumerate(pil_images):
                    context = {
                        "model": preset,
                        "seed": params.get("seed", 0),
                        "prompt": params.get("prompt", ""),
                        "batch": i + 1,
                    }
                    result = saver.save_image(img, context)
                    if result and "preview" in result:
                        preview_results.append(result["preview"])
        except Exception as e:
            print(f"[AutoSave] Error: {e}")
        
        # Fall back to temp folder if auto-save disabled or failed
        if not preview_results and pil_images:
            preview_results = save_preview_images(pil_images, prefix="batchbox")
        
        # Serialize preview info for persistence
        last_images_json = json.dumps(preview_results) if preview_results else ""
        
        # Return dict with both result tuple and UI data
        return {
            "ui": {
                "images": preview_results,
                "_last_images": [last_images_json]
            },
            "result": (images_tensor, response_info, last_url)
        }


# ==========================================
# Gaussian Blur Upscale Node
# ==========================================
class GaussianBlurUpscaleNode(DynamicImageNodeBase):
    """
    高斯模糊预处理 + AI 放大节点
    
    工作流程:
    1. 接收输入图片
    2. 根据 blur_intensity 或 custom_sigma 应用高斯模糊
    3. 构建提示词（模糊修复 prompt + 风格 prompt）
    4. 将模糊后的图片 + 提示词发送给 AI 模型放大
    5. 返回放大结果 + 中间模糊图（调试用）
    
    模型从 upscale_settings.model 读取（在 API Manager 中配置）。
    """
    
    CATEGORY = "ComfyUI-Custom-Batchbox"
    
    # σ 值映射
    BLUR_PRESETS = {
        "轻 (σ1-3)": 2.0,
        "中 (σ3-6)": 4.0,
        "重 (σ6-10)": 7.0,
    }
    
    # 修复模式提示词
    REPAIR_PROMPTS = {
        "直出": "把这张模糊的照片变高清",
        "降噪": "把这张模糊的照片变高清，让画面变得干净整洁",
        "风格": "把这张模糊的照片变高清。按照如下风格要求处理：",
    }
    
    # 风格预设
    STYLE_PRESETS = {
        "电影写实": "以电影级写实风格处理，保持自然光影和真实质感",
        "复古油画": "以古典油画风格处理，带有厚重的笔触感和温暖的色调",
        "现代数字艺术": "以现代数字艺术风格处理，色彩鲜艳，细节丰富",
        "日式动漫": "以日式动漫风格处理，线条清晰，色彩明快",
        "水墨国风": "以中国传统水墨画风格处理，注重意境和留白",
    }
    
    # Class-level cache for pre-applied blur (populated by /api/batchbox/apply-blur)
    # Maps node_id -> {"tensor": Tensor, "sigma": float, "has_mask": bool}
    # Security Hardening: Bounded to max 20 entries to prevent OOM memory leaks on node deletion.
    from collections import OrderedDict
    class BoundedCache(OrderedDict):
        def __setitem__(self, key, value):
            if key in self:
                self.move_to_end(key)
            super().__setitem__(key, value)
            if len(self) > 20:
                self.popitem(last=False)
        def __getitem__(self, key):
            val = super().__getitem__(key)
            self.move_to_end(key)
            return val
            
    _cached_blur_data = BoundedCache()
    
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "blur_intensity": (list(cls.BLUR_PRESETS.keys()), {"default": "轻 (σ1-3)"}),
                "repair_mode": (list(cls.REPAIR_PROMPTS.keys()), {"default": "直出"}),
                "custom_sigma": ("FLOAT", {"default": 0.0, "min": 0.0, "max": 15.0, "step": 0.5}),
                "aspect_ratio": (["auto", "1:1", "4:3", "3:4", "16:9", "9:16", "3:2", "2:3", "4:5", "5:4", "21:9"], {"default": "auto"}),
                "style_prompt": ("STRING", {"multiline": True, "default": ""}),
                "batch_count": ("INT", {"default": 1, "min": 1, "max": 10}),
                "seed": ("INT", {"default": 0, "min": 0, "max": 2147483647}),
            },
            "optional": {
                "image1": ("IMAGE",),
            },
            "hidden": {
                "unique_id": ("UNIQUE_ID",),
                "extra_params": ("STRING", {"default": "{}"}),
                "_last_images": ("STRING", {"default": ""}),
                "_cached_hash": ("STRING", {"default": ""}),
                "_force_generate": ("STRING", {"default": "false"}),
                "_skip_hash_check": ("STRING", {"default": "false"}),
                "_bypass_queue_prompt": ("STRING", {"default": "false"}),
                "_blur_mask": ("STRING", {"default": ""}),
                "_selected_image_index": ("INT", {"default": 0}),
                "_all_images_connected": ("STRING", {"default": "false"}),
            }
        }
    
    RETURN_TYPES = ("IMAGE", "IMAGE", "IMAGE", "STRING")
    RETURN_NAMES = ("selected_image", "blurred_image", "all_images", "response_info")
    FUNCTION = "upscale"
    OUTPUT_NODE = True
    
    def _get_upscale_model(self):
        """Get the model and endpoint configured for upscaling from upscale_settings."""
        settings = config_manager.get_upscale_settings()
        model = settings.get("model", "")
        endpoint = settings.get("endpoint", "")
        if not model:
            # Fallback: use first available image model
            models = self.get_models_for_category("image")
            model = models[0] if models and models[0] != "No Models Found" else ""
        return model, endpoint
    
    def _build_prompt(self, repair_mode: str, style_prompt: str) -> str:
        """Build the full prompt based on repair mode and style."""
        base_prompt = self.REPAIR_PROMPTS.get(repair_mode, self.REPAIR_PROMPTS["直出"])
        
        if repair_mode == "风格" and style_prompt:
            return f"{base_prompt}{style_prompt}"
        
        return base_prompt
    
    def _get_sigma(self, blur_intensity: str, custom_sigma: float) -> float:
        """Get the σ value from preset or custom setting."""
        if custom_sigma > 0:
            return custom_sigma
        return self.BLUR_PRESETS.get(blur_intensity, 2.0)
    
    def upscale(self, blur_intensity: str, repair_mode: str, **kwargs) :
        """Apply Gaussian blur preprocessing and upscale via AI model."""
        from .image_utils import apply_gaussian_blur_tensor, apply_masked_gaussian_blur_tensor

        # Collect all connected image inputs (image1, image2, ...)
        image_tensors = []
        for key in sorted(kwargs.keys()):
            if key.startswith("image") and isinstance(kwargs[key], torch.Tensor):
                image_tensors.append(kwargs[key])

        # Use first image as primary (for blur preview output and cache hash)
        image = image_tensors[0] if image_tensors else None
        if image is None:
            empty = torch.zeros(1, 64, 64, 3)
            return {
                "ui": {"images": []},
                "result": (empty, empty, empty, "错误：未连接输入图片")
            }

        custom_sigma = kwargs.get("custom_sigma", 0.0)
        style_prompt = kwargs.get("style_prompt", "")
        batch_count = min(int(kwargs.get("batch_count", 1)), 10)  # 安全上限

        # Save first input image as node preview (show input, not generated output)
        input_preview = save_preview_images(tensor2pil(image[:1]), prefix="blur_input")
        input_preview_json = json.dumps(input_preview) if input_preview else ""
        
        # Get model and endpoint from global upscale_settings
        model, saved_endpoint = self._get_upscale_model()
        if not model:
            return {
                "ui": {"images": []},
                "result": (image, image, image, "错误：未配置放大模型，请在 API Manager 中设置")
            }
        
        # Build prompt
        prompt = self._build_prompt(repair_mode, style_prompt)
        
        # Compute sigma
        sigma = self._get_sigma(blur_intensity, custom_sigma)
        
        # ==========================================
        # SMART CACHE: Check if API call is needed
        # ==========================================
        last_images_json = kwargs.get("_last_images", "")
        force_generate = kwargs.get("_force_generate", "false") == "true"
        cached_hash = kwargs.get("_cached_hash", "")
        extra_params_str = kwargs.get("extra_params", "{}")
        skip_hash_check = kwargs.get("_skip_hash_check", "false") == "true"
        bypass_queue_prompt = kwargs.get("_bypass_queue_prompt", "false") == "true"
        aspect_ratio = kwargs.get("aspect_ratio") or "auto"
        blur_mask_b64 = kwargs.get("_blur_mask") or ""
        
        # ==========================================
        # TILED MODE: Process inline
        # ==========================================
        extra_p = self._parse_extra_params(extra_params_str)
        
        # ==========================================
        # Extract blur_mode and selection_boxes from extra properties
        # ==========================================
        blur_mode = extra_p.get("_blur_mode") or "global"
        selection_boxes = extra_p.get("_selection_boxes") or []
        
        # ==========================================
        # TILED MODE: Process inline
        # ==========================================
        if extra_p.get("_blur_mode") == "tiled":
            print("[GaussianBlurUpscale] Detected tiled mode, processing tiles inline...")
            from .image_utils import split_image_tiles, merge_image_tiles, apply_gaussian_blur
            import copy
            
            tile_mode = extra_p.get("_tile_mode", "2x2")
            tile_overlap_x = int(extra_p.get("_tile_overlap_x", extra_p.get("_tile_overlap", 16)))
            tile_overlap_y = int(extra_p.get("_tile_overlap_y", extra_p.get("_tile_overlap", 16)))
            selected_tiles = extra_p.get("_selected_tiles", None)
            
            # Get model
            model, saved_endpoint = self._get_upscale_model()
            endpoint_override = saved_endpoint
            if extra_p.get("endpoint_override"):
                endpoint_override = extra_p.get("endpoint_override")
            
            if not model:
                return {
                    "ui": {"images": []},
                    "result": (image, image, image, "错误：未配置放大模型")
                }
            
            prompt = self._build_prompt(repair_mode, style_prompt)
            
            # Split image into tiles
            pil_images = tensor2pil(image[:1])
            tiles = split_image_tiles(pil_images[0], tile_mode,
                                      overlap_x=tile_overlap_x, overlap_y=tile_overlap_y)
            print(f"[GaussianBlurUpscale-Tiled] Split into {len(tiles)} tiles, mode={tile_mode}, ovX={tile_overlap_x}, ovY={tile_overlap_y}")
            
            # Filter by selection
            if selected_tiles and isinstance(selected_tiles, list) and len(selected_tiles) > 0:
                selected_set = set(selected_tiles)
                tiles = [t for t in tiles if f"{t['col']}_{t['row']}" in selected_set]
                print(f"[GaussianBlurUpscale-Tiled] Filtered to {len(tiles)} selected tiles: {selected_tiles}")
            
            # Process each tile
            total_tiles = len(tiles)
            from comfy.utils import ProgressBar
            pbar = ProgressBar(total_tiles)
            
            processed_tiles = []
            for tile_idx, tile_info in enumerate(tiles):
                try:
                    tile_pil = tile_info["image"]
                    blurred_tile = apply_gaussian_blur(tile_pil, sigma)
                    
                    # Upload blurred tile for AI upscaling
                    buffered = BytesIO()
                    blurred_tile.save(buffered, format="PNG")
                    upload_files = [("image", ("tile.png", buffered.getvalue(), "image/png"))]
                    
                    tile_params = {
                        "prompt": prompt,
                        "seed": kwargs.get("seed", 0) + tile_idx,
                        "_upload_files": upload_files,
                    }
                    
                    # Add aspect ratio
                    tw, th = tile_pil.size
                    from .image_utils import detect_aspect_ratio
                    tile_params["aspect_ratio"] = detect_aspect_ratio(tw, th)
                    
                    # Merge default params from upscale_settings
                    settings = config_manager.get_upscale_settings()
                    default_params = settings.get("default_params", {})
                    if default_params:
                        for key, val in default_params.items():
                            if key not in tile_params:
                                tile_params[key] = val
                    
                    result_tensor, resp_info, _, result_pils = self.process_batch(
                        model, 1, tile_params, "img2img", endpoint_override
                    )
                    
                    result_pil = result_pils[0] if result_pils else blurred_tile
                    tile_copy = copy.deepcopy(tile_info)
                    tile_copy["image"] = result_pil
                    processed_tiles.append(tile_copy)
                    
                except Exception as e:
                    print(f"[GaussianBlurUpscale-Tiled] Tile {tile_idx} error: {e}")
                    tile_copy = copy.deepcopy(tile_info)
                    tile_copy["image"] = apply_gaussian_blur(tile_info["image"], sigma)
                    processed_tiles.append(tile_copy)
                
                pbar.update_absolute(tile_idx + 1, total_tiles)
            
            # Output each tile as a separate batch image
            processed_tiles.sort(key=lambda t: (t['row'], t['col']))
            
            if not processed_tiles:
                return {
                    "ui": {"images": []},
                    "result": (image, image, image, "分块生成失败：无处理结果")
                }
            
            import numpy as np
            
            # Normalize all tiles to same size for batch stacking
            first_img = processed_tiles[0]["image"]
            target_size = first_img.size
            
            batch_tensors = []
            tile_pils = []
            for pt in processed_tiles:
                img = pt["image"]
                if img.size != target_size:
                    img = img.resize(target_size, Image.LANCZOS)
                tile_pils.append(img)
                img_np = np.array(img).astype(np.float32) / 255.0
                batch_tensors.append(torch.from_numpy(img_np))
            
            all_tiles_tensor = torch.stack(batch_tensors, dim=0)
            
            # Blurred image for output
            blurred_pil = apply_gaussian_blur(pil_images[0], sigma)
            blurred_np = np.array(blurred_pil).astype(np.float32) / 255.0
            blurred_tensor = torch.from_numpy(blurred_np).unsqueeze(0)
            
            # Selected image
            selected_index = kwargs.get("_selected_image_index", 0)
            try: selected_index = int(selected_index)
            except: selected_index = 0
            selected_index = max(0, min(selected_index, all_tiles_tensor.shape[0] - 1))
            selected_tensor = all_tiles_tensor[selected_index:selected_index+1]
            
            # Save preview
            preview_results = save_preview_images(tile_pils, prefix="tiled_upscale")
            last_images_json = json.dumps(preview_results) if preview_results else ""
            
            info = f"Model: {model} | σ={sigma} | Tiled: {tile_mode} ({len(processed_tiles)} tiles)"
            
            return {
                "ui": {
                    "images": preview_results,
                    "_last_images": [last_images_json],
                },
                "result": (selected_tensor, blurred_tensor, all_tiles_tensor, info)
            }
        
        # Build kwargs dict for hash computation (include upscale-specific params)
        hash_kwargs = {
            "extra_params": extra_params_str,
            "seed": kwargs.get("seed", 0),
            "image": image,
            "_hash_extras": {
                "blur_intensity": blur_intensity,
                "custom_sigma": custom_sigma,
                "repair_mode": repair_mode,
                "style_prompt": style_prompt,
                "aspect_ratio": aspect_ratio,
                "blur_mask": hashlib.md5(blur_mask_b64.encode('utf-8')).hexdigest() if blur_mask_b64 else "",
            },
        }

        if bypass_queue_prompt and last_images_json and not force_generate:
            need_api_call = False
            print("[SmartCache] GaussianBlurUpscale Queue Prompt bypass active with persisted cache")
        elif skip_hash_check:
            need_api_call = force_generate or not last_images_json
        else:
            current_hash = self._compute_params_hash(model, prompt, batch_count, hash_kwargs)
            need_api_call = (
                force_generate or
                not last_images_json or
                (cached_hash and current_hash != cached_hash)
            )
        
        if not need_api_call:
            selected_index = kwargs.get("_selected_image_index", 0)
            all_images_connected = kwargs.get("_all_images_connected", "false") == "true"
            try:
                selected_index = int(selected_index)
            except (ValueError, TypeError):
                selected_index = 0
            
            selected_tensor, all_tensor, preview_results = self._load_persisted_images(
                last_images_json, selected_index, load_all=all_images_connected
            )
            if selected_tensor is not None:
                # Also compute blurred image for the blurred_image output
                if blur_mode == "selection" and selection_boxes:
                    from .image_utils import apply_selection_boxes_blur
                    blurred_pil = apply_selection_boxes_blur(tensor2pil(image[:1])[0], selection_boxes)
                    blurred_tensor = pil2tensor(blurred_pil)
                elif blur_mask_b64:
                    blurred_tensor = apply_masked_gaussian_blur_tensor(image, blur_mask_b64, sigma)
                else:
                    blurred_tensor = apply_gaussian_blur_tensor(image, sigma)
                return {
                    "ui": {
                        "images": input_preview,
                        "_last_images": [last_images_json],
                        "_cached_hash": [cached_hash],
                    },
                    "result": (selected_tensor, blurred_tensor, all_tensor, "Loaded from cache")
                }
        
        # ==========================================
        # STEP 1: Apply Gaussian Blur
        # ==========================================
        # Check class-level cache first (set by /api/batchbox/apply-blur)
        node_id_for_cache = kwargs.get("unique_id", "")
        cached_blur = GaussianBlurUpscaleNode._cached_blur_data.get(node_id_for_cache)
        if cached_blur and abs(cached_blur.get("sigma", -1) - sigma) < 0.01:
            print(f"[GaussianBlurUpscale] Using pre-cached blurred tensor for node {node_id_for_cache}")
            blurred_tensor = cached_blur["tensor"]
            # Clear cache after use
            del GaussianBlurUpscaleNode._cached_blur_data[node_id_for_cache]
        elif blur_mode == "selection" and selection_boxes:
            # ==========================================
            # SELECTION MODE: crop each box → separate API call per box
            # ==========================================
            print(f"[GaussianBlurUpscale] SELECTION mode: cropping {len(selection_boxes)} boxes for independent API calls")
            from .image_utils import crop_and_blur_selection_boxes, apply_selection_boxes_blur, detect_aspect_ratio
            
            # 1. Crop + blur each selection box
            source_pil = tensor2pil(image[:1])[0]
            cropped_list = crop_and_blur_selection_boxes(source_pil, selection_boxes)
            
            if not cropped_list:
                raise ValueError("选区模式: 没有有效的选区框，请至少框选一个区域")
            
            # 2. Full-image blurred tensor for the blurred_image output
            blurred_pil_full = apply_selection_boxes_blur(source_pil, selection_boxes)
            blurred_tensor = pil2tensor(blurred_pil_full)
            
            # 3. Call API for each cropped box
            all_pil_images = []
            all_tensors = []
            all_response_info = []
            
            for box_idx, (cropped_pil, box_info) in enumerate(cropped_list):
                box_w, box_h = cropped_pil.size
                box_ratio = detect_aspect_ratio(box_w, box_h)
                print(f"[GaussianBlurUpscale] Box {box_idx+1}/{len(cropped_list)}: {box_w}x{box_h} → aspect_ratio={box_ratio}")
                
                buffered = BytesIO()
                cropped_pil.save(buffered, format="PNG")
                box_upload_files = [("image", (f"blurred_box_{box_idx}.png", buffered.getvalue(), "image/png"))]
                
                box_params = {
                    "prompt": prompt,
                    "seed": kwargs.get("seed", 0) + box_idx,
                    "_upload_files": box_upload_files,
                    "aspect_ratio": box_ratio,
                }
                
                settings = config_manager.get_upscale_settings()
                default_params = settings.get("default_params", {})
                if default_params:
                    for key, val in default_params.items():
                        if key not in box_params:
                            box_params[key] = val
                box_params["aspect_ratio"] = box_ratio
                
                extra_params_parsed = self._parse_extra_params(extra_params_str)
                for key, val in extra_params_parsed.items():
                    if key != "aspect_ratio":
                        box_params[key] = val
                
                endpoint_override = saved_endpoint
                if extra_params_parsed.get("endpoint_override"):
                    endpoint_override = extra_params_parsed.get("endpoint_override")
                
                box_images_tensor, box_resp_info, _, box_pil_images = self.process_batch(
                    model, batch_count, box_params, "img2img", endpoint_override
                )
                
                all_pil_images.extend(box_pil_images or [])
                all_response_info.append(box_resp_info or "")
                if box_images_tensor is not None:
                    for bi in range(box_images_tensor.shape[0]):
                        all_tensors.append(box_images_tensor[bi:bi+1])
            
            # 4. Save and return
            preview_results = []
            try:
                from .save_settings import SaveSettings
                save_cfg = config_manager.get_save_settings()
                saver = SaveSettings(save_cfg)
                if saver.enabled and all_pil_images:
                    for i, img in enumerate(all_pil_images):
                        context = {"model": model, "seed": kwargs.get("seed", 0) + i, "prompt": prompt, "batch": i + 1}
                        result = saver.save_image(img, context)
                        if result and "preview" in result:
                            preview_results.append(result["preview"])
            except Exception as e:
                print(f"[GaussianBlurUpscale] AutoSave error: {e}")
            
            if not preview_results and all_pil_images:
                preview_results = save_preview_images(all_pil_images, prefix="blur_upscale")
            
            last_images_json = json.dumps(preview_results) if preview_results else ""
            current_hash = self._compute_params_hash(model, prompt, batch_count, hash_kwargs)
            
            selected_index = kwargs.get("_selected_image_index", 0)
            try:
                selected_index = int(selected_index)
            except (ValueError, TypeError):
                selected_index = 0
            selected_index = max(0, min(selected_index, len(all_tensors) - 1)) if all_tensors else 0
            selected_tensor = all_tensors[selected_index] if all_tensors else blurred_tensor
            
            if all_tensors:
                try:
                    images_tensor_out = torch.cat(all_tensors, dim=0)
                except RuntimeError:
                    images_tensor_out = selected_tensor
            else:
                images_tensor_out = blurred_tensor
            
            info = f"Model: {model} | σ={sigma} | Mode: selection | {len(cropped_list)} boxes × {batch_count}"
            combined_info = " | ".join(filter(None, all_response_info))
            if combined_info and combined_info != "Success":
                info += f"\n{combined_info}"
            
            return {
                "ui": {
                    "images": input_preview,
                    "_last_images": [last_images_json],
                    "_cached_hash": [current_hash],
                },
                "result": (selected_tensor, blurred_tensor, images_tensor_out, info)
            }
        elif blur_mask_b64:
            print(f"[GaussianBlurUpscale] Applying MASKED Gaussian blur with σ={sigma}")
            blurred_tensor = apply_masked_gaussian_blur_tensor(image, blur_mask_b64, sigma)
        else:
            print(f"[GaussianBlurUpscale] Applying Gaussian blur with σ={sigma}")
            blurred_tensor = apply_gaussian_blur_tensor(image, sigma)
        
        # ==========================================
        # STEP 2: Prepare blurred images for API upload
        # ==========================================
        upload_files = []
        for i, img_tensor in enumerate(image_tensors):
            if i == 0:
                blurred_t = blurred_tensor
            elif blur_mask_b64:
                blurred_t = apply_masked_gaussian_blur_tensor(img_tensor, blur_mask_b64, sigma)
            else:
                blurred_t = apply_gaussian_blur_tensor(img_tensor, sigma)
            blurred_pil = tensor2pil(blurred_t)[0]
            buffered = BytesIO()
            blurred_pil.save(buffered, format="PNG")
            field_name = "image" if i == 0 else f"image{i + 1}"
            upload_files.append((field_name, (f"blurred_input_{i}.png", buffered.getvalue(), "image/png")))

        params = {
            "prompt": prompt,
            "seed": kwargs.get("seed", 0),
            "_upload_files": upload_files,
        }

        # Merge default params from upscale_settings (lower priority than existing params)
        settings = config_manager.get_upscale_settings()
        default_params = settings.get("default_params", {})
        print(f"[GaussianBlurUpscale] upscale_settings: {settings}")
        print(f"[GaussianBlurUpscale] default_params: {default_params}")
        if default_params:
            for key, val in default_params.items():
                if key not in params:
                    params[key] = val

        # Apply aspect_ratio from widget (overrides default_params)
        widget_ratio = kwargs.get("aspect_ratio", "auto")
        if widget_ratio and widget_ratio != "auto":
            params["aspect_ratio"] = widget_ratio

        # Parse extra dynamic parameters (highest priority, overrides defaults)
        extra_params = self._parse_extra_params(extra_params_str)
        params.update(extra_params)

        # Resolve aspect_ratio='auto' from input image dimensions
        if params.get("aspect_ratio") in (None, "auto"):
            from .image_utils import detect_aspect_ratio
            h, w = image.shape[1], image.shape[2]
            params["aspect_ratio"] = detect_aspect_ratio(w, h)
            print(f"[GaussianBlurUpscale] Auto aspect_ratio: {w}x{h} → {params['aspect_ratio']}")

        # Ensure seed is int
        if "seed" in params:
            try:
                params["seed"] = int(params["seed"])
            except (ValueError, TypeError):
                params["seed"] = 0
        
        # Get endpoint override: saved endpoint from settings, or extra_params override
        endpoint_override = saved_endpoint
        if extra_params.get("endpoint_override"):
            endpoint_override = extra_params.get("endpoint_override")
        
        # ==========================================
        # STEP 3: Call AI model for upscaling
        # ==========================================
        print(f"[GaussianBlurUpscale] Sending to model: {model}, prompt: {prompt[:50]}...")
        images_tensor, response_info, last_url, pil_images = self.process_batch(
            model, batch_count, params, "img2img", endpoint_override
        )
        
        # ==========================================
        # STEP 4: Save and return results
        # ==========================================
        preview_results = []
        try:
            from .save_settings import SaveSettings
            save_cfg = config_manager.get_save_settings()
            saver = SaveSettings(save_cfg)
            
            if saver.enabled and pil_images:
                for i, img in enumerate(pil_images):
                    context = {
                        "model": model,
                        "seed": params.get("seed", 0),
                        "prompt": prompt,
                        "batch": i + 1,
                    }
                    result = saver.save_image(img, context)
                    if result and "preview" in result:
                        preview_results.append(result["preview"])
        except Exception as e:
            print(f"[GaussianBlurUpscale] AutoSave error: {e}")
        
        if not preview_results and pil_images:
            preview_results = save_preview_images(pil_images, prefix="blur_upscale")
        
        last_images_json = json.dumps(preview_results) if preview_results else ""
        
        # Compute hash for smart cache
        current_hash = self._compute_params_hash(model, prompt, batch_count, hash_kwargs)
        
        # Select image
        selected_index = kwargs.get("_selected_image_index", 0)
        try:
            selected_index = int(selected_index)
        except (ValueError, TypeError):
            selected_index = 0
        
        if images_tensor.shape[0] > 1:
            selected_index = max(0, min(selected_index, images_tensor.shape[0] - 1))
            selected_tensor = images_tensor[selected_index:selected_index+1]
        else:
            selected_tensor = images_tensor
        
        info = f"Model: {model} | σ={sigma} | Mode: {repair_mode}"
        if response_info and response_info != "Success":
            info += f"\n{response_info}"
        
        return {
            "ui": {
                "images": input_preview,
                "_last_images": [last_images_json],
                "_cached_hash": [current_hash],
            },
            "result": (selected_tensor, blurred_tensor, images_tensor, info)
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
        processed_required["batch_count"] = ("INT", {"default": 1, "min": 1, "max": 20})
    
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
