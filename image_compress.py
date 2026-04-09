"""
Image Compression for API Upload
==================================

Compresses large images (PNG/BMP) before uploading to Gemini API.
Prevents timeout failures caused by 18-22MB+ raw PNG images.

Strategy:
1. PNG → JPEG conversion (quality=90): typically 22MB → 3-5MB
2. If still over limit, reduce JPEG quality stepwise (85 → 80 → 70)
3. If still over limit, downscale resolution (keep aspect ratio)
"""

import io
from typing import Tuple

from PIL import Image

from .batchbox_logger import logger

# Default max size: 10MB (safe for both Files API upload and inline_data)
DEFAULT_MAX_SIZE_MB = 10
QUALITY_STEPS = [90, 85, 80, 70, 60]
MIN_DIMENSION = 512  # Never shrink below this


def compress_for_upload(
    image_bytes: bytes,
    max_size_mb: float = DEFAULT_MAX_SIZE_MB,
    mime_type: str = "image/png",
) -> Tuple[bytes, str]:
    """
    Compress image bytes if they exceed max_size_mb.

    Args:
        image_bytes: Raw image bytes (PNG, JPEG, BMP, etc.)
        max_size_mb: Maximum allowed size in MB
        mime_type: Original MIME type

    Returns:
        Tuple of (compressed_bytes, new_mime_type)
        If no compression needed, returns original bytes and mime_type unchanged.
    """
    max_size = int(max_size_mb * 1024 * 1024)
    original_size = len(image_bytes)

    # Skip if already small enough
    if original_size <= max_size:
        return image_bytes, mime_type

    original_mb = original_size / 1024 / 1024
    logger.info(f"[Compress] 📦 Image too large ({original_mb:.1f}MB > {max_size_mb}MB), compressing...")

    try:
        img = Image.open(io.BytesIO(image_bytes))

        # Convert RGBA/P to RGB for JPEG
        if img.mode in ("RGBA", "P", "LA"):
            background = Image.new("RGB", img.size, (255, 255, 255))
            if img.mode == "P":
                img = img.convert("RGBA")
            background.paste(img, mask=img.split()[-1] if "A" in img.mode else None)
            img = background
        elif img.mode != "RGB":
            img = img.convert("RGB")

        # Step 1: Try JPEG at various quality levels
        for quality in QUALITY_STEPS:
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=quality, optimize=True)
            compressed = buf.getvalue()

            if len(compressed) <= max_size:
                compressed_mb = len(compressed) / 1024 / 1024
                logger.info(
                    f"[Compress] ✅ {original_mb:.1f}MB → {compressed_mb:.1f}MB "
                    f"(JPEG q={quality})"
                )
                return compressed, "image/jpeg"

        # Step 2: Downscale resolution until it fits
        scale = 0.8
        while scale >= 0.3:
            new_w = max(int(img.width * scale), MIN_DIMENSION)
            new_h = max(int(img.height * scale), MIN_DIMENSION)
            resized = img.resize((new_w, new_h), Image.LANCZOS)

            buf = io.BytesIO()
            resized.save(buf, format="JPEG", quality=70, optimize=True)
            compressed = buf.getvalue()

            if len(compressed) <= max_size:
                compressed_mb = len(compressed) / 1024 / 1024
                logger.info(
                    f"[Compress] ✅ {original_mb:.1f}MB → {compressed_mb:.1f}MB "
                    f"(JPEG q=70, {new_w}x{new_h}, scale={scale:.0%})"
                )
                return compressed, "image/jpeg"

            scale -= 0.1

        # Last resort: return best effort (smallest we got)
        compressed_mb = len(compressed) / 1024 / 1024
        logger.warning(
            f"[Compress] ⚠️ Could not compress below {max_size_mb}MB, "
            f"best: {compressed_mb:.1f}MB"
        )
        return compressed, "image/jpeg"

    except Exception as e:
        logger.error(f"[Compress] ❌ Compression failed: {e}, using original")
        return image_bytes, mime_type
