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
from typing import Optional, Tuple, Literal, TYPE_CHECKING
from PIL import Image
import numpy as np

if TYPE_CHECKING:
    import torch

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
# SECTION 5: ASPECT RATIO DETECTION
# ═══════════════════════════════════════════════════════════════════════════════

# Standard aspect ratios ordered by value (width/height)
_STANDARD_RATIOS = [
    ("9:16", 9 / 16),
    ("2:3",  2 / 3),
    ("3:4",  3 / 4),
    ("4:5",  4 / 5),
    ("1:1",  1.0),
    ("5:4",  5 / 4),
    ("4:3",  4 / 3),
    ("3:2",  3 / 2),
    ("16:9", 16 / 9),
    ("21:9", 21 / 9),
]


def detect_aspect_ratio(width: int, height: int) -> str:
    """
    Detect the closest standard aspect ratio from image dimensions.

    Returns a string like "16:9", "1:1", "3:4", etc.
    """
    if width <= 0 or height <= 0:
        return "1:1"
    ratio = width / height
    best_label = "1:1"
    best_diff = float("inf")
    for label, std_ratio in _STANDARD_RATIOS:
        diff = abs(ratio - std_ratio)
        if diff < best_diff:
            best_diff = diff
            best_label = label
    return best_label


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 6: GAUSSIAN BLUR PROCESSING
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


def apply_selection_boxes_blur(pil_image: Image.Image, boxes: list) -> Image.Image:
    """
    Apply independent Gaussian blur to multiple rectangular regions.
    Each box has: x, y, w, h (pixels), sigma.
    Overlapping regions use the largest sigma (sorted ascending, last paste wins).
    """
    from PIL import ImageFilter
    
    result = pil_image.copy()
    # Sort by sigma ascending so larger sigma overwrites overlaps
    for box in sorted(boxes, key=lambda b: b.get('sigma', 0)):
        sigma = box.get('sigma', 0)
        if sigma <= 0:
            continue
        x, y, w, h = int(box['x']), int(box['y']), int(box['w']), int(box['h'])
        # Clamp target paste bounds
        x = max(0, x)
        y = max(0, y)
        x2 = min(pil_image.width, x + w)
        y2 = min(pil_image.height, y + h)
        if x2 <= x or y2 <= y:
            continue
            
        # Add padding to crop area so edges blur correctly with surrounding pixels
        # A margin of 3*sigma is usually enough to capture 99.7% of the Gaussian kernel
        margin = int(sigma * 3)
        crop_x = max(0, x - margin)
        crop_y = max(0, y - margin)
        crop_x2 = min(pil_image.width, x2 + margin)
        crop_y2 = min(pil_image.height, y2 + margin)
        
        region = pil_image.crop((crop_x, crop_y, crop_x2, crop_y2))
        blurred_region = region.filter(ImageFilter.GaussianBlur(radius=sigma))
        
        # Crop the blurred padded region back to the exact target bounds
        # Use relative coordinates inside the padded 'blurred_region'
        rel_x = x - crop_x
        rel_y = y - crop_y
        rel_x2 = rel_x + (x2 - x)
        rel_y2 = rel_y + (y2 - y)
        
        blurred_exact = blurred_region.crop((rel_x, rel_y, rel_x2, rel_y2))
        result.paste(blurred_exact, (x, y))
        
    return result


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


def apply_masked_gaussian_blur(pil_image: Image.Image, mask_image: Image.Image, sigma: float) -> Image.Image:
    """
    Apply Gaussian blur only to mask-selected regions.
    
    Args:
        pil_image: Source PIL Image (RGB)
        mask_image: Grayscale mask — white = blur, black = keep original
        sigma: Gaussian blur radius
        
    Returns:
        Image with selective blur applied
    """
    from PIL import ImageFilter
    
    if sigma <= 0:
        return pil_image
    
    # Ensure mask matches image size
    if mask_image.size != pil_image.size:
        mask_image = mask_image.resize(pil_image.size, Image.Resampling.LANCZOS)
    
    # Convert mask to 'L' mode (grayscale)
    if mask_image.mode != 'L':
        mask_image = mask_image.convert('L')
    
    # Blur the entire image
    blurred = pil_image.filter(ImageFilter.GaussianBlur(radius=sigma))
    
    # Composite: mask white → blurred, mask black → original
    return Image.composite(blurred, pil_image, mask_image)


def apply_masked_gaussian_blur_tensor(image_tensor, mask_b64: str, sigma: float):
    """
    Apply masked Gaussian blur to a ComfyUI tensor.
    
    Args:
        image_tensor: Tensor of shape [B, H, W, C] (ComfyUI IMAGE format)
        mask_b64: Base64-encoded mask PNG (white = blur region)
        sigma: Gaussian blur radius
        
    Returns:
        Blurred tensor of same shape (only masked regions blurred)
    """
    import torch
    import base64
    
    if sigma <= 0 or not mask_b64:
        return image_tensor
    
    # Decode mask from base64
    if ',' in mask_b64:
        mask_b64 = mask_b64.split(',', 1)[1]
    mask_bytes = base64.b64decode(mask_b64)
    mask_pil = Image.open(io.BytesIO(mask_bytes)).convert('L')
    
    results = []
    for i in range(image_tensor.shape[0]):
        img_np = (image_tensor[i].cpu().numpy() * 255).astype(np.uint8)
        pil_img = Image.fromarray(img_np)
        
        blurred = apply_masked_gaussian_blur(pil_img, mask_pil, sigma)
        
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

# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 5: IMAGE TILING AND BLENDING
# ═══════════════════════════════════════════════════════════════════════════════

def get_grid_from_mode(tile_mode: str) -> Tuple[int, int]:
    """Parse tile_mode string into (cols, rows)."""
    if tile_mode == "竖切3块": return (3, 1)
    if tile_mode == "竖切4块": return (4, 1)
    if tile_mode == "竖切5块": return (5, 1)
    if tile_mode == "横切3块": return (1, 3)
    if tile_mode == "横切4块": return (1, 4)
    if tile_mode == "横切5块": return (1, 5)
    if tile_mode == "2×2 四等分": return (2, 2)
    if tile_mode == "3×3 九宫格": return (3, 3)
    # Support "NxM" format from auto mode (e.g. "2x1", "3x2")
    import re
    m = re.match(r'^(\d+)x(\d+)$', tile_mode)
    if m:
        return (int(m.group(1)), int(m.group(2)))
    return (2, 2)

def split_image_tiles(image: Image.Image, tile_mode: str, overlap: int = 16,
                      overlap_x: int = None, overlap_y: int = None) -> list:
    """
    Split an image into overlapping tiles based on the mode.
    overlap_x/overlap_y allow per-axis overlap for ratio correction.
    If not provided, falls back to uniform `overlap`.
    """
    cols, rows = get_grid_from_mode(tile_mode)
    w, h = image.size
    ovx = overlap_x if overlap_x is not None else overlap
    ovy = overlap_y if overlap_y is not None else overlap
    
    # Calculate base step size (without overlap)
    step_x = w // cols
    step_y = h // rows
    
    tiles = []
    for row in range(rows):
        for col in range(cols):
            x_start = col * step_x
            y_start = row * step_y
            
            x_end = w if col == cols - 1 else (col + 1) * step_x + ovx
            y_end = h if row == rows - 1 else (row + 1) * step_y + ovy
            
            if col > 0:
                x_start -= ovx
            if row > 0:
                y_start -= ovy
                
            x_start = max(0, x_start)
            y_start = max(0, y_start)
            x_end = min(w, x_end)
            y_end = min(h, y_end)
            
            tile_img = image.crop((x_start, y_start, x_end, y_end))
            
            tiles.append({
                "image": tile_img,
                "x": x_start,
                "y": y_start,
                "w": x_end - x_start,
                "h": y_end - y_start,
                "col": col,
                "row": row,
                "grid_cols": cols,
                "grid_rows": rows
            })
            
    return tiles

def merge_image_tiles(tiles: list, original_size: Tuple[int, int], overlap: int, upscale_factor: float = None) -> Image.Image:
    """
    Merge processed (upscaled) tiles back together.
    Uses linear alpha blending on the overlap regions to eliminate seams.
    """
    if not tiles:
        return Image.new("RGB", original_size)
        
    # Determine scale factor
    if upscale_factor is not None and upscale_factor > 0:
        scale_x = scale_y = float(upscale_factor)
    else:
        # Calculate theoretical scale factor from the first tile if not explicitly provided
        t0 = tiles[0]
        scale_x = t0['image'].width / t0['w']
        scale_y = t0['image'].height / t0['h']
    
    # Create final canvas
    out_w = int(original_size[0] * scale_x)
    out_h = int(original_size[1] * scale_y)
    
    # Use a Float32 numpy array for high-precision blending accumulation
    canvas_arr = np.zeros((out_h, out_w, 3), dtype=np.float32)
    weight_arr = np.zeros((out_h, out_w, 1), dtype=np.float32)
    
    for t in tiles:
        # EXACT mathematical positioning on the canvas
        tx = int(t['x'] * scale_x)
        ty = int(t['y'] * scale_y)
        tw = int(t['w'] * scale_x)
        th = int(t['h'] * scale_y)
        
        # Calculate exactly how many pixels the overlap regions should be for this specific tile
        overlap_left = int(overlap * scale_x) if t['col'] > 0 else 0
        overlap_top = int(overlap * scale_y) if t['row'] > 0 else 0
        overlap_right = int(overlap * scale_x) if t['col'] < t['grid_cols'] - 1 else 0
        overlap_bottom = int(overlap * scale_y) if t['row'] < t['grid_rows'] - 1 else 0
        
        img = t['image'].convert("RGB")
        # FORCE the AI output to rigidly match the geometric math size
        if img.width != tw or img.height != th:
            img = img.resize((tw, th), Image.Resampling.LANCZOS)
        
        # In rare cases of rounding errors at the extreme canvas edge, clip
        if tx + tw > out_w: tw = out_w - tx; img = img.crop((0, 0, tw, th))
        if ty + th > out_h: th = out_h - ty; img = img.crop((0, 0, tw, th))
        
        tile_rgb = np.array(img, dtype=np.float32)
        
        # Create an alpha mask (weight) for this tile (1.0 = solid)
        alpha = np.ones((th, tw, 1), dtype=np.float32)
        
        # Fade IN from left edge
        if overlap_left > 0:
            fade_w = min(overlap_left * 2, tw)  # overlap is the overlap region, we fade across it
            gradient = np.linspace(0.0, 1.0, fade_w).reshape(1, fade_w, 1)
            alpha[:, :fade_w, :] *= gradient
            
        # Fade IN from top edge
        if overlap_top > 0:
            fade_h = min(overlap_top * 2, th)
            gradient = np.linspace(0.0, 1.0, fade_h).reshape(fade_h, 1, 1)
            alpha[:fade_h, :, :] *= gradient
            
        # Fade OUT to right edge
        if overlap_right > 0:
            fade_w = min(overlap_right * 2, tw)
            gradient = np.linspace(1.0, 0.0, fade_w).reshape(1, fade_w, 1)
            alpha[:, -fade_w:, :] *= gradient
            
        # Fade OUT to bottom edge
        if overlap_bottom > 0:
            fade_h = min(overlap_bottom * 2, th)
            gradient = np.linspace(1.0, 0.0, fade_h).reshape(fade_h, 1, 1)
            alpha[-fade_h:, :, :] *= gradient

        # Additively accumulate weighted RGB and weights
        target_rgb = canvas_arr[ty:ty+th, tx:tx+tw]
        target_w = weight_arr[ty:ty+th, tx:tx+tw]
        
        target_rgb += tile_rgb * alpha
        target_w += alpha
        
        canvas_arr[ty:ty+th, tx:tx+tw] = target_rgb
        weight_arr[ty:ty+th, tx:tx+tw] = target_w

    # Normalize by accumulated weights to get final colors
    # Avoid division by zero
    weight_safe = np.where(weight_arr == 0, 1.0, weight_arr)
    final_arr = canvas_arr / weight_safe
    
    final_arr = np.clip(final_arr, 0, 255).astype(np.uint8)
    return Image.fromarray(final_arr, mode="RGB")
