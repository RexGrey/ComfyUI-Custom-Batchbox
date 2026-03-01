"""
API Adapter Module

Provides a unified interface for communicating with different API providers.
Each adapter handles the specific request/response format for its provider.
"""

from .base import APIAdapter, APIResponse, APIError
from .template_engine import TemplateEngine

# Keep package import resilient in standalone script/test contexts where
# parent package relative imports may not be available.
try:
    from .generic import GenericAPIAdapter
except Exception:  # pragma: no cover - fallback for non-package imports
    GenericAPIAdapter = None

__all__ = [
    'APIAdapter',
    'APIResponse', 
    'APIError',
    'GenericAPIAdapter',
    'TemplateEngine'
]
