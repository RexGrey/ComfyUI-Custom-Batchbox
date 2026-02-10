"""
Image Utilities for Batchbox
=============================

Provides high-quality image processing utilities:
- Format detection and preservation
- RGBA transparency support
- Lossless encoding options
- WebP optimization
"""

import io
from typing import Optional, Tuple, Literal
from PIL import Image
import numpy as np

# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 1: FORMAT DETECTION
# ═══════════════════════════════════════════════════════════════════════════════

def detect_image_format(img_bytes: bytes) -> Optional[str]:
    """
    Detect image format from raw bytes.
    
    Args:
        img_bytes: Raw image data
        
    Returns:
        Format string ('PNG', 'JPEG', 'WEBP', 'GIF') or None if unknown
    """
    if len(img_bytes) < 8:
        return None
    
    # Check magic bytes
    if img_bytes[:8] == b'\x89PNG\r\n\x1a\n':
        return 'PNG'
    elif img_bytes[:2] == b'\xff\xd8':
        return 'JPEG'
    elif img_bytes[:4] == b'RIFF' and img_bytes[8:12] == b'WEBP':
        return 'WEBP'
    elif img_bytes[:6] in (b'GIF87a', b'GIF89a'):
        return 'GIF'
    
    return None


def has_transparency(pil_image: Image.Image) -> bool:
    """
    Check if image has actual transparency (not just an alpha channel).
    
    Args:
        pil_image: PIL Image object
        
    Returns:
        True if image has non-opaque pixels
    """
    if pil_image.mode == 'RGBA':
        # Check if any pixel has alpha < 255
        alpha = pil_image.split()[-1]
        return alpha.getextrema()[0] < 255
    elif pil_image.mode == 'P':
        # Palette with transparency
        return 'transparency' in pil_image.info
    elif pil_image.mode == 'LA':
        return True
    
    return False


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 2: FORMAT CONVERSION
# ═══════════════════════════════════════════════════════════════════════════════

def prepare_for_comfyui(
    pil_image: Image.Image,
    preserve_alpha: bool = True
) -> Tuple[Image.Image, str]:
    """
    Prepare image for ComfyUI tensor conversion.
    
    ComfyUI supports both RGB and RGBA tensors. This function preserves
    transparency when possible.
    
    Args:
        pil_image: Source PIL Image
        preserve_alpha: If True, preserve RGBA for transparent images
        
    Returns:
        Tuple of (converted_image, mode_string)
    """
    if pil_image.mode == 'RGBA' and preserve_alpha:
        # Keep RGBA for transparent images
        return pil_image, 'RGBA'
    
    if pil_image.mode in ('LA', 'PA'):
        # Grayscale with alpha or Palette with alpha
        if preserve_alpha:
            return pil_image.convert('RGBA'), 'RGBA'
        else:
            return pil_image.convert('RGB'), 'RGB'
    
    if pil_image.mode == 'P':
        # Palette mode - check for transparency
        if 'transparency' in pil_image.info and preserve_alpha:
            return pil_image.convert('RGBA'), 'RGBA'
        else:
            return pil_image.convert('RGB'), 'RGB'
    
    if pil_image.mode == 'L':
        # Grayscale to RGB
        return pil_image.convert('RGB'), 'RGB'
    
    if pil_image.mode == 'RGB':
        return pil_image, 'RGB'
    
    if pil_image.mode == 'RGBA':
        return pil_image, 'RGBA'
    
    # Fallback: convert to RGB
    return pil_image.convert('RGB'), 'RGB'


def pil_to_tensor_rgba(pil_image: Image.Image) -> 'torch.Tensor':
    """
    Convert PIL image to tensor, preserving RGBA if present.
    
    Args:
        pil_image: PIL Image (RGB or RGBA)
        
    Returns:
        Tensor of shape [1, H, W, C] where C is 3 or 4
    """
    import torch
    
    img_array = np.array(pil_image).astype(np.float32) / 255.0
    
    if len(img_array.shape) == 2:
        # Grayscale - expand to RGB
        img_array = np.stack([img_array, img_array, img_array], axis=-1)
    
    # Add batch dimension [H, W, C] -> [1, H, W, C]
    return torch.from_numpy(img_array).unsqueeze(0)


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 3: ENCODING OPTIONS
# ═══════════════════════════════════════════════════════════════════════════════

ImageFormat = Literal['PNG', 'WEBP', 'JPEG']

def encode_image(
    pil_image: Image.Image,
    format: ImageFormat = 'PNG',
    quality: int = 100,
    lossless: bool = True
) -> bytes:
    """
    Encode PIL image to bytes with quality control.
    
    Args:
        pil_image: Source image
        format: Output format ('PNG', 'WEBP', 'JPEG')
        quality: Quality level (1-100, used by WEBP/JPEG)
        lossless: If True, use lossless compression for WebP
        
    Returns:
        Encoded image bytes
    """
    buffer = io.BytesIO()
    
    if format == 'PNG':
        # PNG is always lossless
        # Use compression level 6 (balanced) for reasonable file size
        pil_image.save(buffer, format='PNG', compress_level=6)
    
    elif format == 'WEBP':
        if lossless:
            pil_image.save(buffer, format='WEBP', lossless=True)
        else:
            pil_image.save(buffer, format='WEBP', quality=quality)
    
    elif format == 'JPEG':
        # JPEG doesn't support transparency
        if pil_image.mode == 'RGBA':
            # Composite on white background
            background = Image.new('RGB', pil_image.size, (255, 255, 255))
            background.paste(pil_image, mask=pil_image.split()[3])
            pil_image = background
        elif pil_image.mode != 'RGB':
            pil_image = pil_image.convert('RGB')
        
        pil_image.save(buffer, format='JPEG', quality=quality, subsampling=0)
    
    return buffer.getvalue()


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 4: VALIDATION & INFO
# ═══════════════════════════════════════════════════════════════════════════════

def get_image_info(pil_image: Image.Image) -> dict:
    """
    Get detailed image information.
    
    Args:
        pil_image: PIL Image object
        
    Returns:
        Dict with size, mode, has_alpha, format, etc.
    """
    return {
        'size': pil_image.size,
        'mode': pil_image.mode,
        'has_alpha': pil_image.mode in ('RGBA', 'LA', 'PA'),
        'has_transparency': has_transparency(pil_image),
        'format': pil_image.format,
        'info': pil_image.info
    }


def validate_for_api(
    pil_image: Image.Image,
    max_size: Optional[Tuple[int, int]] = None,
    allowed_formats: Optional[list] = None
) -> Tuple[bool, Optional[str]]:
    """
    Validate image for API upload.
    
    Args:
        pil_image: Image to validate
        max_size: Optional (max_width, max_height) tuple
        allowed_formats: Optional list of allowed format strings
        
    Returns:
        Tuple of (is_valid, error_message)
    """
    if max_size:
        if pil_image.width > max_size[0] or pil_image.height > max_size[1]:
            return False, f"Image too large: {pil_image.size}, max allowed: {max_size}"
    
    if allowed_formats:
        if pil_image.format and pil_image.format not in allowed_formats:
            return False, f"Format {pil_image.format} not in allowed: {allowed_formats}"
    
    return True, None


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 5: GAUSSIAN BLUR PROCESSING
# ═══════════════════════════════════════════════════════════════════════════════

def apply_gaussian_blur(pil_image: Image.Image, sigma: float) -> Image.Image:
    """
    Apply Gaussian blur to a PIL image.
    
    Used as preprocessing before AI upscaling to convert non-standard
    degradation (VAE compression artifacts, fake textures) into standard
    degradation (natural blur) that models are trained to handle.
    
    Args:
        pil_image: Source PIL Image
        sigma: Gaussian blur radius in pixels (1-15)
        
    Returns:
        Blurred PIL Image
    """
    from PIL import ImageFilter
    
    if sigma <= 0:
        return pil_image
    
    return pil_image.filter(ImageFilter.GaussianBlur(radius=sigma))


def apply_gaussian_blur_tensor(image_tensor, sigma: float):
    """
    Apply Gaussian blur to a ComfyUI tensor.
    
    Args:
        image_tensor: Tensor of shape [B, H, W, C] (ComfyUI IMAGE format)
        sigma: Gaussian blur radius in pixels
        
    Returns:
        Blurred tensor of same shape
    """
    import torch
    
    if sigma <= 0:
        return image_tensor
    
    # Process each image in the batch
    results = []
    for i in range(image_tensor.shape[0]):
        # Tensor [H, W, C] -> PIL
        img_np = (image_tensor[i].cpu().numpy() * 255).astype(np.uint8)
        pil_img = Image.fromarray(img_np)
        
        # Apply blur
        blurred = apply_gaussian_blur(pil_img, sigma)
        
        # PIL -> Tensor
        blurred_np = np.array(blurred).astype(np.float32) / 255.0
        results.append(torch.from_numpy(blurred_np))
    
    return torch.stack(results)


def generate_blur_preview_base64(image_base64: str, sigma: float, max_preview_size: int = 512) -> str:
    """
    Generate a blurred preview image as base64 for frontend display.
    
    Resizes large images to max_preview_size for fast network transfer,
    then applies Gaussian blur.
    
    Args:
        image_base64: Base64-encoded source image (data URL or raw base64)
        sigma: Gaussian blur radius
        max_preview_size: Max dimension for the preview (default 512px)
        
    Returns:
        Base64-encoded blurred preview image (data URL format)
    """
    import base64
    
    # Strip data URL prefix if present
    if ',' in image_base64:
        image_base64 = image_base64.split(',', 1)[1]
    
    # Decode base64 to PIL
    img_bytes = base64.b64decode(image_base64)
    pil_img = Image.open(io.BytesIO(img_bytes))
    
    # Convert to RGB if needed
    if pil_img.mode not in ('RGB', 'RGBA'):
        pil_img = pil_img.convert('RGB')
    
    # Apply Gaussian blur on original resolution first
    # so the preview accurately reflects the blur effect on the full image
    blurred = apply_gaussian_blur(pil_img, sigma)

    # Then resize for preview display (keep aspect ratio)
    w, h = blurred.size
    if max(w, h) > max_preview_size:
        ratio = max_preview_size / max(w, h)
        new_w = int(w * ratio)
        new_h = int(h * ratio)
        blurred = blurred.resize((new_w, new_h), Image.Resampling.LANCZOS)

    # Encode to base64
    buffer = io.BytesIO()
    blurred.save(buffer, format='JPEG', quality=85)
    b64 = base64.b64encode(buffer.getvalue()).decode('utf-8')
    
    return f"data:image/jpeg;base64,{b64}"
