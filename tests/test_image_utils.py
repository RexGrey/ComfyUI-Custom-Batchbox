"""
Tests for image_utils.py

Covers: detect_image_format, has_transparency, prepare_for_comfyui,
        pil_to_tensor_rgba, encode_image, validate_for_api,
        apply_gaussian_blur, apply_gaussian_blur_tensor,
        generate_blur_preview_base64, get_image_info.
"""

import io
import base64

import pytest
from PIL import Image

from image_utils import (
    detect_image_format,
    has_transparency,
    prepare_for_comfyui,
    pil_to_tensor_rgba,
    encode_image,
    get_image_info,
    validate_for_api,
    apply_gaussian_blur,
    apply_gaussian_blur_tensor,
    generate_blur_preview_base64,
)

# Check if torch is available
try:
    import torch
    HAS_TORCH = True
except ImportError:
    HAS_TORCH = False

needs_torch = pytest.mark.skipif(not HAS_TORCH, reason="torch not installed")


# ──────────────────────────────────────────────────────────────────────────────
# detect_image_format
# ──────────────────────────────────────────────────────────────────────────────

class TestDetectImageFormat:

    def test_png_magic_bytes(self):
        data = b'\x89PNG\r\n\x1a\n' + b'\x00' * 16
        assert detect_image_format(data) == 'PNG'

    def test_jpeg_magic_bytes(self):
        data = b'\xff\xd8\xff\xe0' + b'\x00' * 16
        assert detect_image_format(data) == 'JPEG'

    def test_webp_magic_bytes(self):
        data = b'RIFF' + b'\x00' * 4 + b'WEBP' + b'\x00' * 8
        assert detect_image_format(data) == 'WEBP'

    def test_gif87a(self):
        data = b'GIF87a' + b'\x00' * 16
        assert detect_image_format(data) == 'GIF'

    def test_gif89a(self):
        data = b'GIF89a' + b'\x00' * 16
        assert detect_image_format(data) == 'GIF'

    def test_too_short_bytes(self):
        assert detect_image_format(b'\x89PNG') is None

    def test_unknown_format(self):
        assert detect_image_format(b'\x00' * 20) is None

    def test_real_png_bytes(self, sample_image_bytes_png):
        assert detect_image_format(sample_image_bytes_png) == 'PNG'

    def test_real_jpeg_bytes(self, sample_image_bytes_jpeg):
        assert detect_image_format(sample_image_bytes_jpeg) == 'JPEG'


# ──────────────────────────────────────────────────────────────────────────────
# has_transparency
# ──────────────────────────────────────────────────────────────────────────────

class TestHasTransparency:

    def test_rgba_with_transparency(self, pil_rgba_image):
        assert has_transparency(pil_rgba_image) is True

    def test_rgba_fully_opaque(self):
        img = Image.new("RGBA", (4, 4), (255, 0, 0, 255))
        assert has_transparency(img) is False

    def test_rgb_no_transparency(self, pil_rgb_image):
        assert has_transparency(pil_rgb_image) is False

    def test_palette_with_transparency(self):
        img = Image.new("P", (4, 4))
        img.info["transparency"] = 0
        assert has_transparency(img) is True

    def test_la_mode(self):
        img = Image.new("LA", (4, 4), (128, 200))
        assert has_transparency(img) is True


# ──────────────────────────────────────────────────────────────────────────────
# prepare_for_comfyui
# ──────────────────────────────────────────────────────────────────────────────

class TestPrepareForComfyui:

    def test_rgba_preserve_alpha(self, pil_rgba_image):
        result, mode = prepare_for_comfyui(pil_rgba_image, preserve_alpha=True)
        assert mode == 'RGBA'
        assert result.mode == 'RGBA'

    def test_rgba_no_preserve(self, pil_rgba_image):
        # When preserve_alpha=False, RGBA skips the first branch (line 94)
        # and falls through to the RGBA catch-all (line 119), returning RGBA.
        # This is the current behavior — RGBA without explicit conversion path.
        result, mode = prepare_for_comfyui(pil_rgba_image, preserve_alpha=False)
        assert mode == 'RGBA'
        assert result.mode == 'RGBA'

    def test_rgb_passthrough(self, pil_rgb_image):
        result, mode = prepare_for_comfyui(pil_rgb_image)
        assert mode == 'RGB'
        assert result is pil_rgb_image

    def test_grayscale_to_rgb(self):
        img = Image.new("L", (4, 4), 128)
        result, mode = prepare_for_comfyui(img)
        assert mode == 'RGB'
        assert result.mode == 'RGB'

    def test_palette_with_transparency_preserved(self):
        img = Image.new("P", (4, 4))
        img.info["transparency"] = 0
        result, mode = prepare_for_comfyui(img, preserve_alpha=True)
        assert mode == 'RGBA'
        assert result.mode == 'RGBA'

    def test_palette_no_transparency(self):
        img = Image.new("P", (4, 4))
        result, mode = prepare_for_comfyui(img)
        assert mode == 'RGB'
        assert result.mode == 'RGB'

    def test_la_preserve_alpha(self):
        img = Image.new("LA", (4, 4), (128, 200))
        result, mode = prepare_for_comfyui(img, preserve_alpha=True)
        assert mode == 'RGBA'
        assert result.mode == 'RGBA'


# ──────────────────────────────────────────────────────────────────────────────
# pil_to_tensor_rgba
# ──────────────────────────────────────────────────────────────────────────────

@needs_torch
class TestPilToTensorRgba:

    def test_rgb_shape(self, pil_rgb_image):
        t = pil_to_tensor_rgba(pil_rgb_image)
        assert t.shape == (1, 64, 64, 3)

    def test_rgba_shape(self, pil_rgba_image):
        t = pil_to_tensor_rgba(pil_rgba_image)
        assert t.shape == (1, 64, 64, 4)

    def test_values_normalized(self, pil_rgb_image):
        t = pil_to_tensor_rgba(pil_rgb_image)
        assert t.min() >= 0.0
        assert t.max() <= 1.0

    def test_grayscale_to_tensor(self):
        img = Image.new("L", (8, 8), 128)
        t = pil_to_tensor_rgba(img)
        assert t.shape == (1, 8, 8, 3)


# ──────────────────────────────────────────────────────────────────────────────
# encode_image
# ──────────────────────────────────────────────────────────────────────────────

class TestEncodeImage:

    def test_encode_png(self, pil_rgb_image):
        data = encode_image(pil_rgb_image, format='PNG')
        assert data[:8] == b'\x89PNG\r\n\x1a\n'

    def test_encode_webp(self, pil_rgb_image):
        data = encode_image(pil_rgb_image, format='WEBP', lossless=True)
        assert data[:4] == b'RIFF'
        assert data[8:12] == b'WEBP'

    def test_encode_jpeg(self, pil_rgb_image):
        data = encode_image(pil_rgb_image, format='JPEG', quality=90)
        assert data[:2] == b'\xff\xd8'

    def test_encode_jpeg_from_rgba(self, pil_rgba_image):
        data = encode_image(pil_rgba_image, format='JPEG')
        # Should succeed (composited on white)
        assert data[:2] == b'\xff\xd8'
        # Should be decodable
        img = Image.open(io.BytesIO(data))
        assert img.mode == 'RGB'


# ──────────────────────────────────────────────────────────────────────────────
# get_image_info
# ──────────────────────────────────────────────────────────────────────────────

class TestGetImageInfo:

    def test_rgb_image_info(self, pil_rgb_image):
        info = get_image_info(pil_rgb_image)
        assert info['size'] == (64, 64)
        assert info['mode'] == 'RGB'
        assert info['has_alpha'] is False
        assert info['has_transparency'] is False

    def test_rgba_image_info(self, pil_rgba_image):
        info = get_image_info(pil_rgba_image)
        assert info['mode'] == 'RGBA'
        assert info['has_alpha'] is True
        assert info['has_transparency'] is True


# ──────────────────────────────────────────────────────────────────────────────
# validate_for_api
# ──────────────────────────────────────────────────────────────────────────────

class TestValidateForApi:

    def test_valid_image_no_constraints(self, pil_rgb_image):
        valid, err = validate_for_api(pil_rgb_image)
        assert valid is True
        assert err is None

    def test_image_too_large(self, pil_rgb_image):
        valid, err = validate_for_api(pil_rgb_image, max_size=(32, 32))
        assert valid is False
        assert "too large" in err

    def test_image_within_size(self, pil_rgb_image):
        valid, err = validate_for_api(pil_rgb_image, max_size=(128, 128))
        assert valid is True

    def test_format_not_allowed(self):
        buf = io.BytesIO()
        img = Image.new("RGB", (4, 4))
        img.save(buf, format="PNG")
        buf.seek(0)
        img = Image.open(buf)  # now img.format == 'PNG'
        valid, err = validate_for_api(img, allowed_formats=["JPEG"])
        assert valid is False
        assert "not in allowed" in err

    def test_format_allowed(self):
        buf = io.BytesIO()
        img = Image.new("RGB", (4, 4))
        img.save(buf, format="PNG")
        buf.seek(0)
        img = Image.open(buf)
        valid, err = validate_for_api(img, allowed_formats=["PNG"])
        assert valid is True


# ──────────────────────────────────────────────────────────────────────────────
# Gaussian Blur
# ──────────────────────────────────────────────────────────────────────────────

class TestGaussianBlur:

    def test_zero_sigma_returns_same(self, pil_rgb_image):
        result = apply_gaussian_blur(pil_rgb_image, sigma=0)
        assert result is pil_rgb_image

    def test_positive_sigma_blurs(self, pil_rgb_image):
        result = apply_gaussian_blur(pil_rgb_image, sigma=3)
        # Blurred image should differ from original
        assert result.size == pil_rgb_image.size
        orig_pixels = list(pil_rgb_image.getdata())
        blur_pixels = list(result.getdata())
        assert orig_pixels != blur_pixels

    def test_negative_sigma_returns_same(self, pil_rgb_image):
        result = apply_gaussian_blur(pil_rgb_image, sigma=-1)
        assert result is pil_rgb_image


@needs_torch
class TestGaussianBlurTensor:

    def test_zero_sigma_returns_same(self):
        t = torch.rand(2, 8, 8, 3)
        result = apply_gaussian_blur_tensor(t, sigma=0)
        assert torch.equal(result, t)

    def test_positive_sigma_preserves_shape(self):
        t = torch.rand(2, 16, 16, 3)
        result = apply_gaussian_blur_tensor(t, sigma=2)
        assert result.shape == t.shape

    def test_positive_sigma_changes_values(self):
        t = torch.rand(1, 16, 16, 3)
        result = apply_gaussian_blur_tensor(t, sigma=3)
        assert not torch.equal(result, t)


# ──────────────────────────────────────────────────────────────────────────────
# generate_blur_preview_base64
# ──────────────────────────────────────────────────────────────────────────────

class TestGenerateBlurPreviewBase64:

    def _make_b64(self, pil_image):
        buf = io.BytesIO()
        pil_image.save(buf, format="PNG")
        return base64.b64encode(buf.getvalue()).decode()

    def test_returns_data_url(self, pil_rgb_image):
        b64 = self._make_b64(pil_rgb_image)
        result = generate_blur_preview_base64(b64, sigma=2)
        assert result.startswith("data:image/jpeg;base64,")

    def test_handles_data_url_input(self, pil_rgb_image):
        b64 = self._make_b64(pil_rgb_image)
        data_url = f"data:image/png;base64,{b64}"
        result = generate_blur_preview_base64(data_url, sigma=2)
        assert result.startswith("data:image/jpeg;base64,")

    def test_resizes_large_image(self):
        img = Image.new("RGB", (1024, 1024), (128, 128, 128))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        b64 = base64.b64encode(buf.getvalue()).decode()

        result = generate_blur_preview_base64(b64, sigma=1, max_preview_size=256)
        # Decode and check the output is smaller
        result_b64 = result.split(",", 1)[1]
        result_bytes = base64.b64decode(result_b64)
        result_img = Image.open(io.BytesIO(result_bytes))
        assert max(result_img.size) <= 256

    def test_zero_sigma_still_works(self, pil_rgb_image):
        b64 = self._make_b64(pil_rgb_image)
        result = generate_blur_preview_base64(b64, sigma=0)
        assert result.startswith("data:image/jpeg;base64,")
