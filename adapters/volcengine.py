"""
Volcengine (火山引擎) API Adapter

Implements the specific adapter for Volcengine's Visual Generation API,
which is used by 即梦 (Jimeng/Seedream) image editing capabilities.

Key differences from OpenAI/Gemini adapters:
- Uses HMAC-SHA256 Signature V4 authentication (AccessKey + SecretKey)
- Async task model: submit task → poll for result
- Request routing via Action query parameter + req_key in body
- Images/masks transmitted as base64 arrays
"""

import time
import json
import hmac
import hashlib
import base64
import datetime
import requests
from typing import Dict, List, Optional, Any
from urllib.parse import urlencode, quote

from .base import APIAdapter, APIResponse, APIError
from ..batchbox_logger import (
    logger, log_request, log_response, log_error,
    RequestTimer
)


class VolcengineAdapter(APIAdapter):
    """
    Adapter for Volcengine Visual Generation API.
    
    Handles:
    - Signature V4 authentication
    - Async task submission and polling
    - Base64 image/mask encoding
    - Three req_keys: i2i_inpainting_edit, i2i_inpainting, i2i_outpainting
    """
    
    # Constants for Volcengine API
    SERVICE = "cv"
    REGION = "cn-north-1"
    API_VERSION = "2022-08-31"
    HOST = "visual.volcengineapi.com"
    
    def __init__(self, provider_config: Dict, endpoint_config: Dict, mode_config: Dict):
        """
        Args:
            provider_config: Provider settings (base_url, access_key, secret_key)
            endpoint_config: Full endpoint config from model
            mode_config: Specific mode config (inpaint, outpaint, etc.)
        """
        super().__init__(provider_config, endpoint_config)
        self.mode_config = mode_config
        self.access_key = provider_config.get("access_key", "")
        self.secret_key = provider_config.get("secret_key", "")
    
    # ========================================
    # Signature V4 Implementation
    # ========================================
    
    def _sign(self, key: bytes, msg: str) -> bytes:
        """HMAC-SHA256 signing helper"""
        return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()
    
    def _get_signature_key(self, secret_key: str, date_stamp: str, 
                           region: str, service: str) -> bytes:
        """Derive the signing key following Volcengine's V4 spec"""
        k_date = self._sign(secret_key.encode("utf-8"), date_stamp)
        k_region = self._sign(k_date, region)
        k_service = self._sign(k_region, service)
        k_signing = self._sign(k_service, "request")
        return k_signing
    
    def _build_auth_headers(self, method: str, uri: str, query_string: str,
                            payload: str, headers: Dict) -> Dict:
        """
        Build Volcengine Signature V4 authorization headers.
        
        IMPORTANT: X-Date and X-Content-Sha256 must be set BEFORE computing
        canonical headers, as they are part of the signed headers.
        """
        now = datetime.datetime.utcnow()
        date_stamp = now.strftime("%Y%m%d")
        amz_date = now.strftime("%Y%m%dT%H%M%SZ")
        
        # Compute payload hash
        payload_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        
        # Add required headers BEFORE signing (they must be in signed headers)
        headers["X-Date"] = amz_date
        headers["X-Content-Sha256"] = payload_hash
        
        # Step 1: Create canonical request (now includes X-Date and X-Content-Sha256)
        signed_header_keys = sorted(headers.keys(), key=str.lower)
        canonical_headers = ""
        for key in signed_header_keys:
            canonical_headers += f"{key.lower()}:{headers[key].strip()}\n"
        signed_headers = ";".join(k.lower() for k in signed_header_keys)
        
        canonical_request = "\n".join([
            method,
            uri,
            query_string,
            canonical_headers,
            signed_headers,
            payload_hash
        ])
        
        # Step 2: Create string to sign
        credential_scope = f"{date_stamp}/{self.REGION}/{self.SERVICE}/request"
        string_to_sign = "\n".join([
            "HMAC-SHA256",
            amz_date,
            credential_scope,
            hashlib.sha256(canonical_request.encode("utf-8")).hexdigest()
        ])
        
        # Step 3: Calculate signature
        signing_key = self._get_signature_key(
            self.secret_key, date_stamp, self.REGION, self.SERVICE
        )
        signature = hmac.new(
            signing_key, string_to_sign.encode("utf-8"), hashlib.sha256
        ).hexdigest()
        
        # Step 4: Build Authorization header
        authorization = (
            f"HMAC-SHA256 "
            f"Credential={self.access_key}/{credential_scope}, "
            f"SignedHeaders={signed_headers}, "
            f"Signature={signature}"
        )
        
        headers["Authorization"] = authorization
        
        return headers
    
    # ========================================
    # Request Building
    # ========================================
    
    def build_request(self, params: Dict, mode: str = "inpaint") -> Dict:
        """
        Build Volcengine API request.
        
        Constructs the payload with req_key, base64 images, and operation-specific
        parameters, then signs it with Signature V4.
        """
        req_key = self.endpoint.get("req_key", "")
        
        if not req_key:
            raise ValueError("Volcengine adapter requires 'req_key' in endpoint config")
        
        # Check if this is a text-to-image (t2i) or image-to-image (i2i) operation
        is_t2i = req_key.startswith("jimeng_t2i")
        
        # Build the request body based on operation type
        body = {"req_key": req_key}
        
        # Convert images to base64 (if provided)
        binary_data = []
        upload_files = params.get("_upload_files", [])
        for field_name, file_tuple in upload_files:
            file_bytes = file_tuple[1]
            b64_data = base64.b64encode(file_bytes).decode("utf-8")
            binary_data.append(b64_data)
        
        if binary_data:
            # Validate image sizes (Volcengine limit: 4.7MB per image)
            for i, b64 in enumerate(binary_data):
                size_mb = len(b64) / (1024 * 1024)
                if size_mb > 4.7:
                    logger.warning(f"[Volcengine] ⚠️ Image {i+1} is {size_mb:.1f}MB (limit 4.7MB), may be rejected")
            body["binary_data_base64"] = binary_data
        elif not is_t2i:
            # Image editing (i2i) requires at least one input image
            logger.warning(f"[Volcengine] ⚠️ No images provided for {req_key}! "
                          "Use the standard Queue Prompt button (not 开始生成) for image editing.")
            return {
                "url": "",
                "method": "POST", 
                "headers": {},
                "json": body,
                "_payload_str": "",
                "_error": f"即梦{req_key}需要输入图片。请使用 ComfyUI 的 Queue Prompt 按钮执行。"
            }
        
        # Add operation-specific parameters (only documented ones)
        if is_t2i:
            # 文生图 - supports prompt and seed
            prompt = params.get("prompt", "")
            if prompt:
                body["prompt"] = prompt
            seed = int(params.get("seed", -1))
            if seed >= 0:
                body["seed"] = seed
        elif req_key == "jimeng_image2image_dream_inpaint":
            # 即梦AI交互编辑 (新版) — supports prompt and seed
            # prompt: natural language for editing, "删除" for removal
            prompt = params.get("prompt", "")
            if prompt:
                body["prompt"] = prompt
            else:
                body["prompt"] = "删除"  # Default to removal if no prompt
            seed = int(params.get("seed", -1))
            if seed >= 0:
                body["seed"] = seed
        
        payload_str = json.dumps(body)
        
        # Build query string
        query_params = {
            "Action": "CVSync2AsyncSubmitTask",
            "Version": self.API_VERSION
        }
        query_string = urlencode(sorted(query_params.items()))
        
        # Build headers for signing
        headers = {
            "Content-Type": "application/json",
            "Host": self.HOST,
        }
        
        # Sign the request
        headers = self._build_auth_headers(
            method="POST",
            uri="/",
            query_string=query_string,
            payload=payload_str,
            headers=headers
        )
        
        url = f"{self.base_url}/?{query_string}"
        
        return {
            "url": url,
            "method": "POST",
            "headers": headers,
            "json": body,
            "_payload_str": payload_str  # Keep for debugging
        }
    
    # ========================================
    # Response Parsing
    # ========================================
    
    def parse_response(self, response: requests.Response) -> APIResponse:
        """Parse Volcengine submit task response to extract task_id."""
        try:
            data = response.json()
        except Exception:
            return APIResponse(
                success=False,
                error_message=f"Invalid JSON response: {response.text[:200]}",
                raw_response={"text": response.text}
            )
        
        # Check for API-level error
        code = data.get("code", -1)
        if code != 10000 and code != 0:
            msg = data.get("message", "Unknown error")
            return APIResponse(
                success=False,
                error_message=f"Volcengine API error (code={code}): {msg}",
                raw_response=data
            )
        
        # Extract task_id from response
        resp_data = data.get("data", {})
        task_id = resp_data.get("task_id", "")
        
        if task_id:
            return APIResponse(
                success=True,
                task_id=str(task_id),
                status="pending",
                raw_response=data
            )
        
        # Some responses may return result directly (rare for async)
        binary_data = resp_data.get("binary_data_base64", [])
        if binary_data:
            images = []
            for b64 in binary_data:
                try:
                    images.append(base64.b64decode(b64))
                except Exception as e:
                    logger.warning(f"Failed to decode base64 image: {e}")
            
            if images:
                return APIResponse(
                    success=True,
                    images=images,
                    raw_response=data
                )
        
        image_urls = resp_data.get("image_urls", [])
        if image_urls:
            return APIResponse(
                success=True,
                image_urls=image_urls,
                raw_response=data
            )
        
        return APIResponse(
            success=False,
            error_message="No task_id or images in Volcengine response",
            raw_response=data
        )
    
    # ========================================
    # Execution
    # ========================================
    
    def submit_task(self, params: Dict, mode: str = "inpaint") -> APIResponse:
        """
        Submit task only (step 1 of async flow). Returns task_id without polling.
        Used for batch generation: stagger submissions, then poll in parallel.
        """
        request_info = self.build_request(params, mode)
        
        if request_info.get("_error"):
            return APIResponse(success=False, error_message=request_info["_error"])
        
        url = request_info["url"]
        req_key = self.endpoint.get('req_key', '')
        binary_count = len(request_info.get("json", {}).get("binary_data_base64", []))
        payload_size = len(request_info.get("_payload_str", ""))
        logger.info(f"[Volcengine] 📡 {req_key} | Images: {binary_count}, Payload: {payload_size/1024:.0f}KB")
        
        log_request(
            method="POST", url=url,
            headers=request_info.get("headers"),
            payload={"req_key": request_info.get("json", {}).get("req_key", ""),
                     "binary_count": binary_count}
        )
        
        try:
            with RequestTimer("Volcengine submit") as timer:
                response = requests.post(
                    url,
                    headers=request_info["headers"],
                    data=request_info["_payload_str"].encode("utf-8"),
                    timeout=self.timeout
                )
            
            is_success = response.status_code == 200
            log_response(
                status_code=response.status_code,
                elapsed=timer.elapsed,
                response_text=response.text[:500] if not is_success else None,
                success=is_success
            )
            
            if response.status_code != 200:
                return APIResponse(
                    success=False,
                    error_message=f"HTTP {response.status_code}: {response.text[:500]}",
                    raw_response={"status_code": response.status_code}
                )
            
            return self.parse_response(response)
            
        except Exception as e:
            log_error(f"Volcengine submit failed", e)
            return APIResponse(success=False, error_message=f"Submit failed: {str(e)}")
    
    def poll_and_download(self, task_id: str) -> APIResponse:
        """
        Poll for result and download images (step 2 of async flow).
        Can be called in parallel for multiple task_ids.
        """
        result = self._poll_for_result(task_id)
        
        # Download images from URLs if needed
        if result.success and result.image_urls and not result.images:
            for img_url in result.image_urls:
                img_bytes = self._download_image(img_url)
                if img_bytes:
                    result.images.append(img_bytes)
        
        return result
    
    def execute(self, params: Dict, mode: str = "inpaint") -> APIResponse:
        """
        Execute the full Volcengine request cycle:
        1. Submit task
        2. Poll for result
        3. Return images
        """
        # Step 1: Submit
        result = self.submit_task(params, mode)
        
        if not result.success:
            return result
        
        # Step 2: Poll (if we got a task_id)
        if result.task_id and result.status == "pending":
            result = self.poll_and_download(result.task_id)
        elif result.success and result.image_urls and not result.images:
            # Direct result (rare) — download images
            for img_url in result.image_urls:
                img_bytes = self._download_image(img_url)
                if img_bytes:
                    result.images.append(img_bytes)
        
        return result
    
    def _poll_for_result(self, task_id: str, timeout: int = 120) -> APIResponse:
        """
        Poll for async task completion via CVSync2AsyncGetResult.
        
        Volcengine async tasks typically complete within 5-10 seconds.
        NOTE: req_key is REQUIRED in the poll request body alongside task_id.
        """
        req_key = self.endpoint.get("req_key", "")
        
        query_params = {
            "Action": "CVSync2AsyncGetResult",
            "Version": self.API_VERSION
        }
        query_string = urlencode(sorted(query_params.items()))
        
        start_time = time.time()
        poll_count = 0
        
        while time.time() - start_time < timeout:
            time.sleep(1.5)  # Poll every 1.5 seconds
            poll_count += 1
            
            try:
                # Build poll request body (req_key is REQUIRED by Volcengine API)
                poll_body = {
                    "req_key": req_key,
                    "task_id": task_id
                }
                payload_str = json.dumps(poll_body)
                
                # Sign the poll request
                headers = {
                    "Content-Type": "application/json",
                    "Host": self.HOST,
                }
                headers = self._build_auth_headers(
                    method="POST",
                    uri="/",
                    query_string=query_string,
                    payload=payload_str,
                    headers=headers
                )
                
                poll_url = f"{self.base_url}/?{query_string}"
                
                resp = requests.post(
                    poll_url,
                    headers=headers,
                    data=payload_str.encode("utf-8"),
                    timeout=30
                )
                
                if resp.status_code != 200:
                    # Try to parse error body for terminal errors
                    try:
                        err_data = resp.json()
                        err_code = err_data.get("code", 0)
                        err_msg = err_data.get("message", "Unknown error")
                        
                        # Terminal errors - stop polling immediately
                        # 50511 = content safety rejection ("Post Img Risk Not Pass")
                        # 50500+ = server-side task failures
                        if err_code >= 50000:
                            logger.error(f"[Volcengine] ❌ Task failed (code={err_code}): {err_msg}")
                            return APIResponse(
                                success=False,
                                error_message=f"火山引擎任务失败 (code={err_code}): {err_msg}",
                                raw_response=err_data
                            )
                    except Exception:
                        err_msg = resp.text[:200]
                    
                    # Transient errors - keep polling
                    if poll_count <= 5:
                        logger.warning(f"[Volcengine] Poll #{poll_count} HTTP {resp.status_code}: {resp.text[:300]}")
                    elif poll_count % 10 == 0:
                        logger.warning(f"[Volcengine] Poll #{poll_count} HTTP {resp.status_code} (still failing)")
                    continue
                
                data = resp.json()
                code = data.get("code", -1)
                
                # code 10000 = success (standard Volcengine success code)
                if code == 10000:
                    resp_data = data.get("data", {})
                    status = resp_data.get("status", "")
                    
                    logger.debug(f"[Volcengine] Poll #{poll_count} status: {status}")
                    
                    if status in ("done", "Done", "SUCCESS"):
                        # Extract result images
                        images = []
                        
                        # Try binary_data_base64 first
                        binary_data = resp_data.get("binary_data_base64", [])
                        for b64 in binary_data:
                            try:
                                images.append(base64.b64decode(b64))
                            except Exception as e:
                                logger.warning(f"Failed to decode result image: {e}")
                        
                        # Try image_urls as fallback
                        image_urls = resp_data.get("image_urls", [])
                        
                        if images or image_urls:
                            return APIResponse(
                                success=True,
                                images=images,
                                image_urls=image_urls,
                                raw_response=data
                            )
                        
                        return APIResponse(
                            success=False,
                            error_message="Task completed but no images found",
                            raw_response=data
                        )
                    
                    elif status in ("failed", "Failed", "FAILURE"):
                        error_msg = resp_data.get("status_msg", "Task failed")
                        return APIResponse(
                            success=False,
                            error_message=f"Volcengine task failed: {error_msg}",
                            raw_response=data
                        )
                    
                    # Still processing, continue polling
                    
                elif code == 10001:
                    # Task still processing
                    logger.debug(f"[Volcengine] Poll #{poll_count}: still processing")
                    continue
                else:
                    msg = data.get("message", "Unknown error")
                    logger.warning(f"[Volcengine] Poll #{poll_count} error: code={code} {msg}")
                    
            except Exception as e:
                logger.warning(f"[Volcengine] Poll #{poll_count} error: {e}")
        
        return APIResponse(
            success=False,
            error_message=f"Volcengine polling timeout after {timeout}s ({poll_count} polls)"
        )
