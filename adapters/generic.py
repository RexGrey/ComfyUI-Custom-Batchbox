"""
Generic API Adapter

A flexible adapter that uses configuration-driven request building.
Works with any API that follows common REST patterns.
"""

import time
import json
import requests
from typing import Dict, List, Optional, Any
from io import BytesIO
from PIL import Image

from .base import APIAdapter, APIResponse, APIError
from .template_engine import TemplateEngine
from ..batchbox_logger import (
    logger, log_request, log_response, log_error,
    RequestTimer, RetryConfig, calculate_delay, RETRYABLE_STATUS_CODES
)


class GenericAPIAdapter(APIAdapter):
    """
    Configuration-driven API adapter.
    
    Uses payload templates and value mappings from config to build requests.
    Supports both sync and async (polling) response types.
    """
    
    def __init__(self, provider_config: Dict, endpoint_config: Dict, mode_config: Dict):
        """
        Args:
            provider_config: Provider settings (base_url, api_key)
            endpoint_config: Full endpoint config from model
            mode_config: Specific mode config (text2img, img2img, etc.)
        """
        super().__init__(provider_config, endpoint_config)
        self.mode_config = mode_config
        
        # Initialize template engine with value mappings
        value_mappings = mode_config.get("value_mappings", {})
        self.template_engine = TemplateEngine(value_mappings)
    
    def build_request(self, params: Dict, mode: str = "text2img") -> Dict:
        """
        Build HTTP request from parameters using config template.
        Supports both OpenAI and Gemini API formats.
        """
        # Get API format from endpoint config (default: openai)
        api_format = self.endpoint.get("api_format", "openai")
        
        # Apply prompt_prefix from endpoint config (e.g., "生成一张图片：")
        prompt_prefix = self.endpoint.get("prompt_prefix", "")
        if prompt_prefix and "prompt" in params:
            original_prompt = params.get("prompt", "")
            params = params.copy()  # Don't modify original
            params["prompt"] = f"{prompt_prefix}{original_prompt}"
            logger.debug(f"Applied prompt_prefix: {prompt_prefix}")
        
        # Route to appropriate builder based on API format
        if api_format == "gemini":
            return self._build_gemini_request(params, mode)
        else:
            return self._build_openai_request(params, mode)
    
    def _build_openai_request(self, params: Dict, mode: str = "text2img") -> Dict:
        """Build request for OpenAI-compatible APIs."""
        endpoint_path = self.mode_config.get("endpoint", "")
        method = self.mode_config.get("method", "POST")
        content_type = self.mode_config.get("content_type", "application/json")
        payload_template = self.mode_config.get("payload_template", {})
        url = f"{self.base_url}{endpoint_path}"
        
        # Build headers
        headers = {"Authorization": f"Bearer {self.api_key}"}
        
        # Prepare base64 images for Chat API format (if using _chat_content template variable)
        # This converts _upload_files to _images_base64 data URLs
        if "_chat_content" in str(payload_template):
            params = self._prepare_images_base64(params)
        
        # Build payload using template engine
        payload = self.template_engine.render(payload_template, params)
        
        # Auto-add model_name from endpoint config if not already in payload
        model_name = self.endpoint.get("model_name", "")
        if model_name and "model" not in payload:
            payload["model"] = model_name
        
        # If no payload_template defined, auto-add common parameters from params
        # Frontend now handles api_name mapping, so params already have correct keys
        auto_params = ["prompt", "n", "size", "quality", "style", "resolution", 
                      "aspect_ratio", "seed", "response_format", "upscale", "image_size"]
        
        for param_name in auto_params:
            if param_name in params and param_name not in payload:
                value = params[param_name]
                # Skip empty/None values
                if value is not None and value != "":
                    payload[param_name] = value
        
        # Merge extra_params from endpoint config (e.g., response_modalities)
        extra_params = self.endpoint.get("extra_params", {})
        if extra_params and isinstance(extra_params, dict):
            for key, value in extra_params.items():
                if key not in payload:  # Don't override existing values
                    payload[key] = value
            logger.debug(f"Merged extra_params: {extra_params}")
        
        request_info = {
            "url": url,
            "method": method,
            "headers": headers,
        }
        
        if content_type == "application/json":
            headers["Content-Type"] = "application/json"
            request_info["json"] = payload
        elif content_type == "multipart/form-data":
            # Don't set Content-Type, let requests handle it
            request_info["data"] = {k: v for k, v in payload.items() 
                                   if not k.startswith("image")}
            
            # Get file format configuration (endpoint > provider > default)
            file_format = (
                self.mode_config.get("file_format") or
                self.endpoint.get("file_format") or
                self.provider.get("file_format") or
                "same_name"  # System default
            )
            file_field = (
                self.mode_config.get("file_field") or
                self.endpoint.get("file_field") or
                self.provider.get("file_field") or
                "image"  # Default field name
            )
            
            # Format files according to configuration
            upload_files = params.get("_upload_files", [])
            renamed_files = []
            for i, (original_name, file_tuple) in enumerate(upload_files):
                # Extract only first 3 elements for multipart (ignore cached base64 if present)
                # file_tuple may be 3-tuple (filename, bytes, mime) or 4-tuple (+ cached_b64)
                multipart_tuple = file_tuple[:3] if len(file_tuple) > 3 else file_tuple
                
                if file_format == "same_name":
                    # ('image', f1), ('image', f2)
                    renamed_files.append((file_field, multipart_tuple))
                elif file_format == "indexed":
                    # ('image[0]', f1), ('image[1]', f2)
                    renamed_files.append((f"{file_field}[{i}]", multipart_tuple))
                elif file_format == "array":
                    # ('images[]', f1), ('images[]', f2)
                    renamed_files.append((f"{file_field}[]", multipart_tuple))
                elif file_format == "numbered":
                    # ('image1', f1), ('image2', f2)
                    renamed_files.append((f"{file_field}{i+1}", multipart_tuple))
                else:
                    # Fallback to same_name
                    renamed_files.append((file_field, multipart_tuple))
            
            request_info["files"] = renamed_files
            logger.debug(f"Multipart: {len(renamed_files)} file(s), format={file_format}, field={file_field}")
        else:
            headers["Content-Type"] = content_type
            request_info["data"] = payload
        
        return request_info
    
    def _build_gemini_request(self, params: Dict, mode: str = "text2img") -> Dict:
        """
        Build request for Gemini native API format.
        
        Gemini API uses:
        - Endpoint: /v1beta/models/{model}:generateContent
        - Payload: {contents: [...], generationConfig: {...}}
        - Supports responseModalities for image-only output
        """
        import base64
        
        endpoint_path = self.mode_config.get("endpoint", "")
        model_name = self.endpoint.get("model_name", "")
        
        # Support {{model}} placeholder in endpoint path
        if "{{model}}" in endpoint_path:
            endpoint_path = endpoint_path.replace("{{model}}", model_name)
        
        url = f"{self.base_url}{endpoint_path}"
        
        # Build headers (Gemini uses same Bearer token format)
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        # Build contents array
        prompt = params.get("prompt", "")
        parts = [{"text": prompt}]
        
        # Add images if present (for img2img mode)
        upload_files = params.get("_upload_files", [])
        for field_name, file_tuple in upload_files:
            # file_tuple can be 3-element (filename, bytes, mime) or 4-element (+ cached base64)
            if len(file_tuple) >= 4:
                # Use pre-cached base64 to avoid re-encoding per request
                filename, file_bytes, mime_type, cached_b64 = file_tuple
                b64_data = cached_b64
            else:
                # Fallback: encode on the fly
                filename, file_bytes, mime_type = file_tuple
                b64_data = base64.b64encode(file_bytes).decode('utf-8')
            
            parts.append({
                "inline_data": {
                    "mime_type": mime_type,
                    "data": b64_data
                }
            })
        
        contents = [{"parts": parts}]
        
        # Build generationConfig from mode_config or endpoint config
        generation_config = self.mode_config.get("generation_config", {}).copy()
        
        # Also check extra_params for generation config items
        extra_params = self.endpoint.get("extra_params", {})
        if "responseModalities" in extra_params and "responseModalities" not in generation_config:
            generation_config["responseModalities"] = extra_params["responseModalities"]
        
        # Add common params to generation_config if not already present
        if "seed" in params and params["seed"] and "seed" not in generation_config:
            generation_config["seed"] = int(params["seed"])
        
        # Build imageConfig for Gemini image generation (nested under generationConfig)
        # Valid Gemini imageSize values: unknown, need to test
        # Valid Gemini aspectRatio values: "1:1", "16:9", "9:16", "4:3", "3:4" (not "auto")
        image_config = {}
        logger.debug(f"[Gemini] params keys: {list(params.keys())}")
        logger.debug(f"[Gemini] image_size={params.get('image_size')}, aspect_ratio={params.get('aspect_ratio')}")
        
        # Skip invalid imageSize values (1K, 2K, 4K, auto are not valid Gemini values)
        image_size = params.get("image_size", "")
        if image_size and image_size.lower() not in ("auto", "1k", "2k", "4k"):
            image_config["imageSize"] = image_size
            logger.info(f"[Gemini] Added imageConfig.imageSize: {image_size}")
        
        # Skip "auto" for aspectRatio - Gemini requires specific ratio like "1:1"
        aspect_ratio = params.get("aspect_ratio", "")
        if aspect_ratio and aspect_ratio.lower() != "auto":
            image_config["aspectRatio"] = aspect_ratio
            logger.info(f"[Gemini] Added imageConfig.aspectRatio: {aspect_ratio}")
        
        # Add imageConfig to generationConfig if not empty
        if image_config:
            generation_config["imageConfig"] = image_config
        
        if "maxOutputTokens" not in generation_config:
            generation_config["maxOutputTokens"] = 4096
        
        # Build payload
        payload = {
            "contents": contents,
            "generationConfig": generation_config
        }
        
        return {
            "url": url,
            "method": "POST",
            "headers": headers,
            "json": payload
        }

    
    def _prepare_images_base64(self, params: Dict) -> Dict:
        """
        Convert uploaded files to base64 data URLs for Chat API format.
        
        Reads _upload_files and creates _images_base64 list with data URLs:
        ["data:image/png;base64,iVBORw0...", ...]
        """
        import base64
        
        params = params.copy()
        images_base64 = []
        
        upload_files = params.get("_upload_files", [])
        for field_name, file_tuple in upload_files:
            # file_tuple can be 3-element or 4-element (with cached base64)
            if len(file_tuple) >= 4:
                filename, file_bytes, mime_type, cached_b64 = file_tuple
                b64_data = cached_b64
            else:
                filename, file_bytes, mime_type = file_tuple
                b64_data = base64.b64encode(file_bytes).decode('utf-8')
            
            data_url = f"data:{mime_type};base64,{b64_data}"
            images_base64.append(data_url)
        
        params["_images_base64"] = images_base64
        return params
    
    def parse_response(self, response: requests.Response) -> APIResponse:
        """
        Parse HTTP response using config-defined paths.
        Supports both OpenAI and Gemini response formats.
        """
        try:
            data = response.json()
        except:
            return APIResponse(
                success=False,
                error_message=f"Invalid JSON response: {response.text[:200]}",
                raw_response={"text": response.text}
            )
        
        # Check if this is a Gemini response format
        api_format = self.endpoint.get("api_format", "openai")
        if api_format == "gemini" or "candidates" in data:
            return self._parse_gemini_response(data)
        
        response_type = self.mode_config.get("response_type", "sync")
        
        # Handle async response (returns task_id)
        if response_type == "async":
            task_id_path = self.mode_config.get("task_id_path", "task_id")
            task_id = self._get_nested_value(data, task_id_path)
            
            if task_id:
                return APIResponse(
                    success=True,
                    task_id=str(task_id),
                    status="pending",
                    raw_response=data
                )
        
        # Handle sync response (returns images directly)
        response_path = self.mode_config.get("response_path", "data[0].url")
        
        # Parse response path to extract images
        images_data = self._extract_images_from_path(data, response_path)
        
        if not images_data:
            return APIResponse(
                success=False,
                error_message="No images found in response",
                raw_response=data
            )
        
        return APIResponse(
            success=True,
            image_urls=images_data.get("urls", []),
            images=images_data.get("bytes", []),
            raw_response=data
        )
    
    def _parse_gemini_response(self, data: Dict) -> APIResponse:
        """
        Parse Gemini API response format.
        
        Gemini returns images as base64 in:
        candidates[0].content.parts[].inline_data.data
        """
        import base64
        
        images = []
        image_urls = []
        
        candidates = data.get("candidates", [])
        if not candidates:
            return APIResponse(
                success=False,
                error_message="No candidates in Gemini response",
                raw_response=data
            )
        
        # Check finish reason
        finish_reason = candidates[0].get("finishReason", "")
        if finish_reason == "OTHER":
            return APIResponse(
                success=False,
                error_message="Gemini could not generate image for this prompt (try a more descriptive image prompt)",
                raw_response=data
            )
        
        content = candidates[0].get("content", {})
        parts = content.get("parts", [])
        
        for part in parts:
            # Check for inline image data (both camelCase and snake_case)
            inline_data = part.get("inlineData") or part.get("inline_data")
            if inline_data:
                b64_data = inline_data.get("data", "")
                if b64_data:
                    try:
                        img_bytes = base64.b64decode(b64_data)
                        images.append(img_bytes)
                    except Exception as e:
                        print(f"[GenericAdapter] Failed to decode Gemini image: {e}")
            
            # Check for file data (URL reference, both camelCase and snake_case)
            file_data = part.get("fileData") or part.get("file_data")
            if file_data:
                file_uri = file_data.get("fileUri") or file_data.get("file_uri")
                if file_uri:
                    image_urls.append(file_uri)
        
        if not images and not image_urls:
            return APIResponse(
                success=False,
                error_message="No images found in Gemini response",
                raw_response=data
            )
        
        logger.debug(f"Extracted {len(images)} images from Gemini response")
        
        return APIResponse(
            success=True,
            images=images,
            image_urls=image_urls,
            raw_response=data
        )
    
    def _extract_images_from_path(self, data: Dict, path: str) -> Optional[Dict]:
        """
        Extract image URLs or base64 data from response using path.
        
        Supports paths like:
        - data[0].url
        - data[*].url  (all items)
        - data.data.data[*].url
        """
        result = {"urls": [], "bytes": []}
        
        # Split path into parts
        parts = []
        current = ""
        for char in path:
            if char == '.':
                if current:
                    parts.append(current)
                    current = ""
            elif char == '[':
                if current:
                    parts.append(current)
                    current = ""
                current = "["
            elif char == ']':
                current += "]"
                parts.append(current)
                current = ""
            else:
                current += char
        if current:
            parts.append(current)
        
        # Navigate the data structure
        current_data = data
        
        for i, part in enumerate(parts):
            if current_data is None:
                break
            
            if part.startswith('['):
                # Array access
                index_str = part[1:-1]
                
                if index_str == '*':
                    # Wildcard - process all items
                    if isinstance(current_data, list):
                        remaining_path = '.'.join(parts[i+1:])
                        for item in current_data:
                            if remaining_path:
                                extracted = self._extract_images_from_path(item, remaining_path)
                                if extracted:
                                    result["urls"].extend(extracted.get("urls", []))
                                    result["bytes"].extend(extracted.get("bytes", []))
                            else:
                                self._add_image_to_result(item, result)
                        return result if result["urls"] or result["bytes"] else None
                else:
                    # Specific index
                    try:
                        index = int(index_str)
                        current_data = current_data[index] if isinstance(current_data, list) else None
                    except (ValueError, IndexError):
                        current_data = None
            else:
                # Dict key access
                current_data = current_data.get(part) if isinstance(current_data, dict) else None
        
        # Final value should be image URL or base64
        if current_data:
            self._add_image_to_result(current_data, result)
        
        return result if result["urls"] or result["bytes"] else None
    
    def _add_image_to_result(self, value: Any, result: Dict):
        """Add image URL or base64 to result. Supports multiple formats."""
        if isinstance(value, str):
            # Check for Markdown image format: ![...](URL) or ![...](URL "title")
            import re
            md_pattern = r'!\[[^\]]*\]\(([^)\s]+)(?:\s+"[^"]*")?\)'
            md_matches = re.findall(md_pattern, value)
            if md_matches:
                for url in md_matches:
                    if url.startswith(('http://', 'https://')):
                        result["urls"].append(url)
                return
            
            # Check for direct URL
            if value.startswith(('http://', 'https://')):
                result["urls"].append(value)
            elif len(value) > 100:  # Likely base64
                try:
                    import base64
                    img_bytes = base64.b64decode(value)
                    result["bytes"].append(img_bytes)
                except:
                    pass
        elif isinstance(value, dict):
            if "url" in value:
                result["urls"].append(value["url"])
            elif "b64_json" in value:
                try:
                    import base64
                    img_bytes = base64.b64decode(value["b64_json"])
                    result["bytes"].append(img_bytes)
                except:
                    pass
    
    def execute(self, params: Dict, mode: str = "text2img", 
                retry_config: Optional[RetryConfig] = None) -> APIResponse:
        """
        Execute the full request cycle with logging and retry support.
        
        Args:
            params: Request parameters
            mode: API mode (text2img, img2img)
            retry_config: Optional retry configuration
        """
        provider_name = self.provider.get("name", "unknown")
        
        # Use default retry config if not provided
        if retry_config is None:
            retry_config = RetryConfig(max_retries=3, initial_delay=1.0)
        
        # Build request
        request_info = self.build_request(params, mode)
        url = request_info["url"]
        
        # Log request
        log_request(
            method=request_info.get("method", "POST"),
            url=url,
            headers=request_info.get("headers"),
            payload=request_info.get("json") or request_info.get("data"),
            files=request_info.get("files")
        )
        
        last_error = None
        
        for attempt in range(retry_config.max_retries + 1):
            try:
                with RequestTimer(f"API call to {provider_name}") as timer:
                    # Execute request
                    if "json" in request_info:
                        response = requests.post(
                            url,
                            headers=request_info["headers"],
                            json=request_info["json"],
                            timeout=self.timeout
                        )
                    elif "files" in request_info:
                        response = requests.post(
                            url,
                            headers=request_info["headers"],
                            data=request_info.get("data", {}),
                            files=request_info["files"],
                            timeout=self.timeout
                        )
                    else:
                        response = requests.request(
                            request_info["method"],
                            url,
                            headers=request_info["headers"],
                            data=request_info.get("data"),
                            timeout=self.timeout
                        )
                
                # Log response
                is_success = response.status_code == 200
                log_response(
                    status_code=response.status_code,
                    elapsed=timer.elapsed,
                    response_text=response.text[:500] if not is_success else None,
                    success=is_success
                )
                
                # Check if we should retry
                if response.status_code in RETRYABLE_STATUS_CODES:
                    if attempt < retry_config.max_retries:
                        delay = calculate_delay(attempt, retry_config)
                        logger.warning(
                            f"🔄 Retry {attempt + 1}/{retry_config.max_retries} "
                            f"for {provider_name} (HTTP {response.status_code}), "
                            f"waiting {delay:.1f}s"
                        )
                        time.sleep(delay)
                        continue
                    else:
                        log_error(f"Max retries exceeded for {provider_name}")
                
                # Check HTTP status
                if response.status_code != 200:
                    return APIResponse(
                        success=False,
                        error_message=f"HTTP {response.status_code}: {response.text[:200]}",
                        raw_response={"status_code": response.status_code, "text": response.text}
                    )
                
                # Parse response
                result = self.parse_response(response)
                
                # Handle async polling if needed
                if result.task_id and result.status == "pending":
                    logger.info(f"📋 Task ID: {result.task_id}, starting polling...")
                    result = self._poll_for_result(result.task_id)
                
                # Download images from URLs if needed
                if result.success and result.image_urls and not result.images:
                    for img_url in result.image_urls:
                        img_bytes = self._download_image(img_url)
                        if img_bytes:
                            result.images.append(img_bytes)
                
                return result
                
            except requests.Timeout:
                last_error = f"Request timeout after {self.timeout}s"
                if attempt < retry_config.max_retries:
                    delay = calculate_delay(attempt, retry_config)
                    logger.warning(
                        f"🔄 Retry {attempt + 1}/{retry_config.max_retries} "
                        f"for {provider_name} (Timeout), waiting {delay:.1f}s"
                    )
                    time.sleep(delay)
                    continue
                log_error(last_error)
                return APIResponse(success=False, error_message=last_error)
                
            except requests.ConnectionError as e:
                last_error = f"Connection error: {str(e)}"
                if attempt < retry_config.max_retries:
                    delay = calculate_delay(attempt, retry_config)
                    logger.warning(
                        f"🔄 Retry {attempt + 1}/{retry_config.max_retries} "
                        f"for {provider_name} (ConnectionError), waiting {delay:.1f}s"
                    )
                    time.sleep(delay)
                    continue
                log_error(last_error)
                return APIResponse(success=False, error_message=last_error)
                
            except Exception as e:
                log_error(f"Request failed for {provider_name}", e)
                return APIResponse(
                    success=False,
                    error_message=f"Request failed: {str(e)}"
                )
        
        # Should not reach here, but just in case
        return APIResponse(success=False, error_message=last_error or "Unknown error")
    
    def _poll_for_result(self, task_id: str, timeout: int = 600) -> APIResponse:
        """Poll for async task completion"""
        polling_endpoint = self.mode_config.get("polling_endpoint", "/v1/tasks/{task_id}")
        status_path = self.mode_config.get("status_path", "data.status")
        success_value = self.mode_config.get("success_value", "SUCCESS")
        response_path = self.mode_config.get("response_path", "data.data.data[*].url")
        
        poll_url = f"{self.base_url}{polling_endpoint.format(task_id=task_id)}"
        
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            time.sleep(2)
            
            try:
                resp = requests.get(
                    poll_url,
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    timeout=30
                )
                
                if resp.status_code != 200:
                    continue
                
                data = resp.json()
                status = self._get_nested_value(data, status_path)
                
                print(f"[GenericAdapter] Poll status: {status}")
                
                if status == success_value:
                    # Extract images from response
                    images_data = self._extract_images_from_path(data, response_path)
                    
                    if images_data:
                        return APIResponse(
                            success=True,
                            image_urls=images_data.get("urls", []),
                            images=images_data.get("bytes", []),
                            raw_response=data
                        )
                    
                    return APIResponse(
                        success=False,
                        error_message="No images in completed task",
                        raw_response=data
                    )
                    
                elif status in ["FAILURE", "FAILED", "ERROR"]:
                    return APIResponse(
                        success=False,
                        error_message=f"Task failed: {data}",
                        raw_response=data
                    )
                    
            except Exception as e:
                print(f"[GenericAdapter] Polling error: {e}")
        
        return APIResponse(
            success=False,
            error_message=f"Polling timeout after {timeout}s"
        )
