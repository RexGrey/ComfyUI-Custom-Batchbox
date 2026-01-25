"""
API Adapter Module

Provides a unified interface for communicating with different API providers.
Each adapter handles the specific request/response format for its provider.
"""

from .base import APIAdapter, APIResponse, APIError
from .generic import GenericAPIAdapter
from .template_engine import TemplateEngine

__all__ = [
    'APIAdapter',
    'APIResponse', 
    'APIError',
    'GenericAPIAdapter',
    'TemplateEngine'
]
