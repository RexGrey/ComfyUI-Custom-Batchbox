"""
Save Settings Module

Manages auto-save configuration and image saving functionality.
"""

import os
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, Any
from PIL import Image

# Get ComfyUI root directory
import folder_paths


class SaveSettings:
    """
    Manages auto-save settings and provides image saving functionality.
    
    Settings can be loaded from api_config.yaml and updated via API Manager UI.
    """
    
    # Default settings
    DEFAULTS = {
        "enabled": True,
        "output_dir": "output/batchbox",
        "format": "original",  # Keep original format by default
        "fallback_format": "png",  # Default when original format unknown
        "quality": 95,
        "naming_pattern": "{model}_{timestamp}_{seed}",
        "create_date_subfolder": True,
        "include_prompt": False,
        "prompt_max_length": 50,
    }
    
    # Supported file formats
    FORMATS = {
        "png": {"extension": ".png", "save_kwargs": {}},
        "jpg": {"extension": ".jpg", "save_kwargs": {"quality": 95}},
        "jpeg": {"extension": ".jpg", "save_kwargs": {"quality": 95}},
        "webp": {"extension": ".webp", "save_kwargs": {"quality": 95, "lossless": False}},
    }
    
    def __init__(self, settings: Optional[Dict] = None):
        """
        Initialize SaveSettings with optional settings dict.
        
        Args:
            settings: Settings dict from api_config.yaml, or None for defaults
        """
        self._settings = self.DEFAULTS.copy()
        if settings:
            self._settings.update(settings)
    
    @property
    def enabled(self) -> bool:
        return self._settings.get("enabled", True)
    
    @property
    def output_dir(self) -> str:
        return self._settings.get("output_dir", "output/batchbox")
    
    @property
    def format(self) -> str:
        return self._settings.get("format", "png").lower()
    
    @property
    def quality(self) -> int:
        return self._settings.get("quality", 95)
    
    @property
    def naming_pattern(self) -> str:
        return self._settings.get("naming_pattern", "{model}_{timestamp}_{seed}")
    
    @property
    def create_date_subfolder(self) -> bool:
        return self._settings.get("create_date_subfolder", True)
    
    @property
    def include_prompt(self) -> bool:
        return self._settings.get("include_prompt", False)
    
    @property
    def prompt_max_length(self) -> int:
        return self._settings.get("prompt_max_length", 50)
    
    @property
    def fallback_format(self) -> str:
        return self._settings.get("fallback_format", "png").lower()
    
    def update(self, settings: Dict) -> None:
        """Update settings with new values."""
        self._settings.update(settings)
    
    def to_dict(self) -> Dict:
        """Return settings as dict."""
        return self._settings.copy()
    
    def generate_filename(self, context: Dict) -> str:
        """
        Generate filename from naming pattern and context.
        
        Args:
            context: Dict with keys like model, seed, prompt, batch, etc.
            
        Returns:
            Generated filename (without extension)
        """
        pattern = self.naming_pattern
        now = datetime.now()
        
        # Build variable replacements
        replacements = {
            "model": self._sanitize_filename(context.get("model", "unknown")),
            "timestamp": now.strftime("%Y%m%d_%H%M%S"),
            "date": now.strftime("%Y-%m-%d"),
            "time": now.strftime("%H-%M-%S"),
            "seed": str(context.get("seed", 0)),
            "batch": str(context.get("batch", 1)),
            "uuid": str(uuid.uuid4())[:8],
        }
        
        # Handle prompt (optional, truncated)
        if self.include_prompt and context.get("prompt"):
            prompt = context["prompt"][:self.prompt_max_length]
            prompt = self._sanitize_filename(prompt)
            replacements["prompt"] = prompt
        else:
            replacements["prompt"] = ""
        
        # Apply replacements
        filename = pattern
        for key, value in replacements.items():
            filename = filename.replace(f"{{{key}}}", value)
        
        # Remove any remaining empty placeholders
        filename = re.sub(r'\{[^}]+\}', '', filename)
        # Clean up multiple underscores
        filename = re.sub(r'_+', '_', filename)
        filename = filename.strip('_')
        
        return filename
    
    def _sanitize_filename(self, text: str) -> str:
        """
        Sanitize text for use in filename.
        
        Removes/replaces characters that are not allowed in filenames.
        """
        # Replace spaces with underscores
        text = text.replace(' ', '_')
        # Remove characters that are not alphanumeric, underscore, or hyphen
        text = re.sub(r'[^\w\-]', '', text, flags=re.UNICODE)
        # Limit length
        return text[:100]
    
    def get_save_path(self, context: Dict) -> Path:
        """
        Get full save path for an image.
        
        Args:
            context: Context dict for filename generation
            
        Returns:
            Full Path object for the image file
        """
        # Get ComfyUI output directory as base
        try:
            base_dir = folder_paths.get_output_directory()
        except:
            base_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "output")
        
        # Build output directory
        output_dir = os.path.join(base_dir, self.output_dir.lstrip("output/").lstrip("output\\"))
        
        # Add date subfolder if enabled
        if self.create_date_subfolder:
            date_folder = datetime.now().strftime("%Y-%m-%d")
            output_dir = os.path.join(output_dir, date_folder)
        
        # Ensure directory exists
        os.makedirs(output_dir, exist_ok=True)
        
        # Generate filename
        filename = self.generate_filename(context)
        
        # Get extension from format
        format_info = self.FORMATS.get(self.format, self.FORMATS["png"])
        extension = format_info["extension"]
        
        # Handle duplicate filenames
        filepath = Path(output_dir) / f"{filename}{extension}"
        counter = 1
        while filepath.exists():
            filepath = Path(output_dir) / f"{filename}_{counter}{extension}"
            counter += 1
        
        return filepath
    
    def save_image(self, image: Image.Image, context: Dict, original_format: str = None) -> Optional[str]:
        """
        Save a PIL Image with current settings.
        
        Args:
            image: PIL Image to save
            context: Context dict with model, seed, prompt, batch, etc.
            original_format: Original format of image (e.g., 'png', 'jpg'), used when format='original'
            
        Returns:
            Saved file path as string, or None if save disabled/failed
        """
        if not self.enabled:
            return None
        
        try:
            # Determine actual format to use
            use_format = self.format
            if use_format == "original" and original_format:
                use_format = original_format.lower().replace("jpeg", "jpg")
            elif use_format == "original":
                # Use fallback format when original unknown
                use_format = self.fallback_format
            
            # Get format info
            format_info = self.FORMATS.get(use_format, self.FORMATS["png"])
            extension = format_info["extension"]
            save_kwargs = format_info["save_kwargs"].copy()
            
            # Override quality if specified
            if "quality" in save_kwargs:
                save_kwargs["quality"] = self.quality
            
            # Get save path (with correct extension)
            filepath = self._get_save_path_with_ext(context, extension)
            
            # Handle RGBA for JPEG (convert to RGB)
            if use_format in ("jpg", "jpeg") and image.mode == "RGBA":
                # Create white background
                background = Image.new("RGB", image.size, (255, 255, 255))
                background.paste(image, mask=image.split()[3])
                image = background
            
            # Save image
            image.save(str(filepath), **save_kwargs)
            
            print(f"[AutoSave] Saved: {filepath}")
            return str(filepath)
            
        except Exception as e:
            print(f"[AutoSave] Error saving image: {e}")
            return None
    
    def _get_save_path_with_ext(self, context: Dict, extension: str) -> Path:
        """Get save path with specific extension."""
        # Get ComfyUI output directory as base
        try:
            base_dir = folder_paths.get_output_directory()
        except:
            base_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "output")
        
        # Build output directory
        output_dir = os.path.join(base_dir, self.output_dir.lstrip("output/").lstrip("output\\"))
        
        # Add date subfolder if enabled
        if self.create_date_subfolder:
            date_folder = datetime.now().strftime("%Y-%m-%d")
            output_dir = os.path.join(output_dir, date_folder)
        
        # Ensure directory exists
        os.makedirs(output_dir, exist_ok=True)
        
        # Generate filename
        filename = self.generate_filename(context)
        
        # Handle duplicate filenames
        filepath = Path(output_dir) / f"{filename}{extension}"
        counter = 1
        while filepath.exists():
            filepath = Path(output_dir) / f"{filename}_{counter}{extension}"
            counter += 1
        
        return filepath
    
    def preview_filename(self, context: Optional[Dict] = None) -> str:
        """
        Generate a preview filename for UI display.
        
        Args:
            context: Optional context dict, or None for sample values
            
        Returns:
            Preview filename string
        """
        if context is None:
            context = {
                "model": "nano_banana_pro",
                "seed": 1234567890,
                "prompt": "a beautiful sunset over mountains",
                "batch": 1,
            }
        
        filename = self.generate_filename(context)
        format_info = self.FORMATS.get(self.format, self.FORMATS["png"])
        return f"{filename}{format_info['extension']}"


# Global instance (will be initialized by ConfigManager)
_save_settings: Optional[SaveSettings] = None


def get_save_settings() -> SaveSettings:
    """Get the global SaveSettings instance."""
    global _save_settings
    if _save_settings is None:
        _save_settings = SaveSettings()
    return _save_settings


def init_save_settings(settings: Dict) -> SaveSettings:
    """Initialize global SaveSettings with config."""
    global _save_settings
    _save_settings = SaveSettings(settings)
    return _save_settings
