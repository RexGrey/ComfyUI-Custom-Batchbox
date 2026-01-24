import os
import io
import json
import time
import base64
import requests
import torch
import numpy as np
from PIL import Image
from io import BytesIO
import concurrent.futures
from .config_manager import config_manager

def pil2tensor(image):
    return torch.from_numpy(np.array(image).astype(np.float32) / 255.0).unsqueeze(0)

def tensor2pil(image):
    return [Image.fromarray(np.clip(255. * image.cpu().numpy().squeeze(), 0, 255).astype(np.uint8))]

# ==========================================
# 1. Base Class (Core Logic)
# ==========================================
class ComflyBatchGenerationBase:
    """Base class containing the core logic for API communication."""
    
    def __init__(self):
        self.timeout = 600

    def get_headers(self, api_key):
        return {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json" 
        }

    def _download_image_content(self, url):
        try:
            resp = requests.get(url, timeout=self.timeout)
            resp.raise_for_status()
            return resp.content, url, None
        except Exception as e:
            return None, url, str(e)

    def _execute_single_request(self, preset_config, prompt, mode="text2img", **kwargs):
        """Standardizes request execution for any preset."""
        
        base_url = preset_config.get("base_url", "").rstrip('/')
        api_key = preset_config.get("api_key", "")
        modes = preset_config.get("modes", {})
        if mode in modes:
            mode_config = modes[mode]
        elif "default" in modes:
            mode_config = modes["default"]
        elif len(modes) == 1:
            # Smart Fallback: If only one mode is configured, assume it applies to both (common URL case)
            mode_config = list(modes.values())[0]
            # Optional: Warning print
            # print(f"  [Warn] Mode '{mode}' not explicitly set. Using available config.")
        else:
            raise ValueError(f"Mode '{mode}' is not configured and no single fallback found.")
        endpoint = mode_config.get("endpoint", "")
        response_type = mode_config.get("response_type", "sync")
        model_name = preset_config.get("model_name", "")
        
        create_url = f"{base_url}{endpoint}"
        query_params = {"async": "true"} if response_type == "async" else {}
        if "webhook" in kwargs and kwargs["webhook"]:
            query_params["webhook"] = kwargs["webhook"]

        # Build payload dynamically from kwargs
        payload = {
            "prompt": prompt,
            "model": model_name,
        }
        
        # Inject known parameters if present in kwargs
        for key in ["aspect_ratio", "image_size", "width", "height", "response_format"]:
            if key in kwargs and kwargs[key] is not None:
                payload[key] = kwargs[key]

        if "seed" in kwargs and kwargs["seed"] > 0:
            payload["seed"] = kwargs["seed"] if mode == "text2img" else str(kwargs["seed"])

        headers = {"Authorization": f"Bearer {api_key}"}
        
        try:
            if mode == "text2img":
                headers["Content-Type"] = "application/json"
                response = requests.post(create_url, headers=headers, json=payload, params=query_params, timeout=self.timeout)
            else:
                # img2img handling
                files_to_send = []
                if "upload_files" in kwargs and kwargs["upload_files"]:
                    for fname, fcontent, ftype in kwargs["upload_files"]:
                         files_to_send.append(('image', (fname, fcontent, ftype)))
                
                response = requests.post(create_url, headers=headers, data=payload, files=files_to_send, params=query_params, timeout=self.timeout)
            
            return response, response_type, base_url, api_key
            
        except Exception as e:
            raise e

    def _process_batch(self, preset_name, auto_switch_provider, batch_count, prompt, **kwargs):
        """Reusable batch processing loop."""
        
        # Determine Mode
        mode = kwargs.pop("mode", "auto")
        
        if mode == "auto":
            # Auto-detect: if any image input is present, use img2img, else text2img
            has_image = False
            for k, v in kwargs.items():
                if k.startswith("image") and isinstance(v, torch.Tensor):
                    has_image = True
                    break
            mode = "img2img" if has_image else "text2img"
            print(f"  > Auto-detected mode: {mode}")
        
        # Pre-process images for img2img if needed
        upload_files = []
        if mode == "img2img":
             # Collect image tensors from kwargs
             # Convention: image1, image2... or a list passed in kwargs
             # For simpler logic, we assume the caller gathers them if possible, or we gather known keys
             images_to_process = []
             for k, v in kwargs.items():
                 if k.startswith("image") and isinstance(v, torch.Tensor):
                     images_to_process.append(v)
             
             idx = 0
             for img in images_to_process:
                 pil_img = tensor2pil(img)[0]
                 buffered = BytesIO()
                 pil_img.save(buffered, format="PNG")
                 upload_files.append((f'image_{idx}.png', buffered.getvalue(), 'image/png'))
                 idx += 1
             kwargs["upload_files"] = upload_files

        successful_tensors = []
        full_response_log = ""
        last_url = ""
        
        seed = kwargs.get("seed", 0)

        for i in range(batch_count):
            print(f"\n[Batch] Starting batch {i+1}/{batch_count} using preset: {preset_name}")
            
            # Load Balancing
            attempt_presets = [preset_name]
            if auto_switch_provider:
                alternatives = config_manager.get_alternatives(preset_name)
                attempt_presets.extend(alternatives)
            
            batch_success = False
            
            for p_name in attempt_presets:
                try:
                    active_config = config_manager.get_preset_config(p_name)
                    if not active_config: continue
                    
                    current_seed = seed + i if seed > 0 else 0
                    kwargs["seed"] = current_seed
                    
                    print(f"  > Attempting Provider: {active_config.get('provider')} (Preset: {p_name})")
                    
                    response, _, base_url, api_key = self._execute_single_request(
                        active_config, prompt, mode, **kwargs
                    )

                    if response.status_code != 200:
                        err = f"Provider {p_name} failed: {response.status_code} - {response.text}"
                        print(err)
                        full_response_log += err + "\n"
                        continue 
                    
                    result = response.json()
                    
                    # 1. Sync check
                    found_sync = False
                    if "data" in result and isinstance(result["data"], list) and len(result["data"]) > 0:
                         image_list = result["data"]
                         if "url" in image_list[0] or "b64_json" in image_list[0]:
                            for img_item in image_list:
                                img_tensor = None
                                if "b64_json" in img_item:
                                    try:
                                        img_bytes = base64.b64decode(img_item["b64_json"])
                                        img_tensor = pil2tensor(Image.open(BytesIO(img_bytes)))
                                    except Exception as e:
                                        full_response_log += f"B64 Error: {e}\n"
                                elif "url" in img_item:
                                    cnt, url, err = self._download_image_content(img_item["url"])
                                    if cnt:
                                        img_tensor = pil2tensor(Image.open(BytesIO(cnt)))
                                        last_url = url
                                
                                if img_tensor is not None:
                                    successful_tensors.append(img_tensor)
                                    found_sync = True
                    
                    if found_sync:
                        batch_success = True
                        break

                    # 2. Async Polling
                    if "task_id" in result:
                        task_id = result["task_id"]
                        print(f"    Task ID: {task_id}, Polling...")
                        
                        polling_config = active_config.get("polling", {})
                        poll_template = polling_config.get("endpoint_template", "/v1/images/tasks/{task_id}")
                        poll_url = f"{base_url}{poll_template.format(task_id=task_id)}"
                        poll_timeout = polling_config.get("timeout", 600)
                        
                        start_time = time.time()
                        poll_success = False
                        
                        while time.time() - start_time < poll_timeout:
                            time.sleep(2)
                            try:
                                poll_resp = requests.get(poll_url, headers={"Authorization": f"Bearer {api_key}"}, timeout=30)
                                if poll_resp.status_code != 200: continue
                                
                                poll_data = poll_resp.json()
                                outer_status = poll_data.get("data", {}).get("status", "")
                                
                                if outer_status == "SUCCESS":
                                    inner_imgs = poll_data.get("data", {}).get("data", {}).get("data", [])
                                    for img_item in inner_imgs:
                                         img_tensor = None
                                         if "b64_json" in img_item:
                                             img_bytes = base64.b64decode(img_item["b64_json"])
                                             img_tensor = pil2tensor(Image.open(BytesIO(img_bytes)))
                                         elif "url" in img_item:
                                             cnt, url, _ = self._download_image_content(img_item["url"])
                                             if cnt:
                                                 img_tensor = pil2tensor(Image.open(BytesIO(cnt)))
                                                 last_url = url
                                         
                                         if img_tensor is not None:
                                             successful_tensors.append(img_tensor)
                                    poll_success = True
                                    break
                                elif outer_status == "FAILURE":
                                    print(f"    Task Failed: {poll_data}")
                                    break
                            except Exception as e:
                                pass
                        
                        if poll_success:
                            batch_success = True
                            break
                    
                    print(f"  > Provider {p_name} failed/timeout.")

                except Exception as e:
                    print(f"  > Exception {p_name}: {e}")
                    full_response_log += f"Ex: {e}\n"

        if not successful_tensors:
            return (pil2tensor(Image.new('RGB', (512, 512), color='black')), "Failed.\n" + full_response_log, "")
            
        return (torch.cat(successful_tensors, dim=0), full_response_log, last_url)


# ==========================================
# 2. Universal Node (The "Option A")
# ==========================================
class NanoBananaPro(ComflyBatchGenerationBase):
    """
    支持动态图像输入的节点。
    初始只显示1个图像输入，连接后自动添加新的输入接口，最多20个。
    """
    
    @classmethod
    def INPUT_TYPES(cls):
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
                "image1": ("IMAGE",),  # 初始只有1个图像输入，其余由前端动态添加
            }
        }
    
    RETURN_TYPES = ("IMAGE", "STRING", "STRING")
    RETURN_NAMES = ("images", "response_info", "last_image_url")
    FUNCTION = "generate"
    CATEGORY = "ComfyUI-Custom-Batchbox"

    def generate(self, preset, auto_switch_provider, batch_count, prompt, **kwargs):
        # 过滤掉未连接的图像输入
        filtered_kwargs = {k: v for k, v in kwargs.items() if v is not None}
        return self._process_batch(preset, auto_switch_provider, batch_count, prompt, **filtered_kwargs)


# ==========================================
# 3. Dynamic Node Factory (The "Option B")
# ==========================================
def create_dynamic_node(preset_name, node_def):
    """Creates a class dynamically based on YAML definition."""
    
    class_name = node_def.get("class_name", f"DynamicNode_{preset_name}")
    display_name = node_def.get("display_name", class_name)
    params = node_def.get("parameters", {})
    
    # 1. Expand inputs from simple YAML to ComfyUI tuple format
    # YAML:  image_size: { type: ["1K", "2K"], default: "2K" }
    # Comfy: "image_size": (["1K", "2K"], {"default": "2K"})
    
    processed_required = {}
    if "required" in params:
        for k, v in params["required"].items():
            val_type = v.get("type", "STRING")
            opts = v.copy()
            if "type" in opts: del opts["type"]
            processed_required[k] = (val_type, opts)
            
    # Always ensure batch_count and auto_switch are present if not defined?
    # Or maybe dynamic nodes are strict. Let's force adding batch/auto_switch for consistency.
    if "batch_count" not in processed_required:
        processed_required["batch_count"] = ("INT", {"default": 1, "min": 1, "max": 100})
    if "auto_switch_provider" not in processed_required:
        processed_required["auto_switch_provider"] = ("BOOLEAN", {"default": False})

    processed_optional = {}
    if "optional" in params:
        for k, v in params["optional"].items():
            val_type = v.get("type", "STRING")
            opts = v.copy()
            if "type" in opts: del opts["type"]
            processed_optional[k] = (val_type, opts)
    
    # Define the class
    class DynamicNodeClass(ComflyBatchGenerationBase):
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
            # Extract system params
            batch_c = kwargs.pop("batch_count", 1)
            auto_sw = kwargs.pop("auto_switch_provider", False)
            prompt_txt = kwargs.pop("prompt", "")
            
            # The rest in kwargs are strict parameters for this model
            # pass them along to process_batch
            return self._process_batch(preset_name, auto_sw, batch_c, prompt_txt, **kwargs)

    # Set name
    DynamicNodeClass.__name__ = class_name
    return class_name, display_name, DynamicNodeClass
