"""
Template Engine for API Payloads

Handles variable substitution and value mappings in payload templates.
"""

import re
from typing import Dict, Any, Optional


class TemplateEngine:
    """
    Template engine for building API payloads from user parameters.
    
    Supports:
    - Variable substitution: {{variable_name}}
    - Value mappings: {{_map_variable}} with mappings dict
    - Nested value extraction
    """
    
    VARIABLE_PATTERN = re.compile(r'\{\{(\w+)\}\}')
    
    def __init__(self, value_mappings: Optional[Dict] = None):
        """
        Args:
            value_mappings: Dict mapping transformed variable names to value maps
                           e.g., {"_map_size": {"1K": "1024x1024", "2K": "1792x1024"}}
        """
        self.value_mappings = value_mappings or {}
    
    def render(self, template: Any, params: Dict) -> Any:
        """
        Render a template with the given parameters.
        
        Args:
            template: Can be a string, dict, list, or primitive
            params: Parameter values to substitute
            
        Returns:
            Rendered template with substituted values
        """
        if isinstance(template, str):
            return self._render_string(template, params)
        elif isinstance(template, dict):
            return self._render_dict(template, params)
        elif isinstance(template, list):
            return self._render_list(template, params)
        else:
            return template
    
    def _render_string(self, template: str, params: Dict) -> Any:
        """Render a string template"""
        # Check if the entire string is a single variable
        match = re.fullmatch(r'\{\{(\w+)\}\}', template)
        if match:
            var_name = match.group(1)
            return self._get_value(var_name, params)
        
        # Otherwise do string substitution
        def replace_var(match):
            var_name = match.group(1)
            value = self._get_value(var_name, params)
            return str(value) if value is not None else ""
        
        return self.VARIABLE_PATTERN.sub(replace_var, template)
    
    def _render_dict(self, template: Dict, params: Dict) -> Dict:
        """Render a dict template"""
        result = {}
        for key, value in template.items():
            rendered_value = self.render(value, params)
            # Skip None values
            if rendered_value is not None:
                result[key] = rendered_value
        return result
    
    def _render_list(self, template: list, params: Dict) -> list:
        """Render a list template"""
        return [self.render(item, params) for item in template]
    
    def _get_value(self, var_name: str, params: Dict) -> Any:
        """
        Get the value for a variable, applying mappings if needed.
        
        Variables starting with _ are treated as special/mapped values:
        - _chat_content: Build Chat API content array with prompt + images
        - _map_size: Look up params['size'] in value_mappings['_map_size']
        - _extract_ratio: Similar extraction with mapping
        """
        # Special variable: _chat_content for Chat API format
        if var_name == "_chat_content":
            return self._build_chat_content(params)
        
        if var_name.startswith('_'):
            return self._get_mapped_value(var_name, params)
        
        return params.get(var_name)
    
    def _build_chat_content(self, params: Dict) -> list:
        """
        Build Chat API content array with text prompt and images.
        
        Returns format compatible with OpenAI Chat API:
        [
            {"type": "text", "text": "prompt text"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}},
            ...
        ]
        """
        content = []
        
        # Add text prompt
        prompt = params.get("prompt", "")
        if prompt:
            content.append({"type": "text", "text": prompt})
        
        # Add images (base64 format prepared by adapter)
        images_base64 = params.get("_images_base64", [])
        for img_data in images_base64:
            content.append({
                "type": "image_url",
                "image_url": {"url": img_data}  # Already in "data:image/png;base64,..." format
            })
        
        return content
    
    def _get_mapped_value(self, mapping_name: str, params: Dict) -> Any:
        """
        Get a mapped value using the value_mappings config.
        
        e.g., _map_size with params={'size': '2K'} and 
              value_mappings={'_map_size': {'2K': '1792x1024'}}
              returns '1792x1024'
        """
        if mapping_name not in self.value_mappings:
            return None
        
        mapping = self.value_mappings[mapping_name]
        
        # Find the source parameter
        # Convention: _map_X looks for param 'X' or similar
        # _extract_ratio looks for 'ratio' or 'aspect_ratio'
        source_param = None
        
        # Try direct match (remove prefix)
        for prefix in ['_map_', '_extract_']:
            if mapping_name.startswith(prefix):
                direct_name = mapping_name[len(prefix):]
                if direct_name in params:
                    source_param = params[direct_name]
                    break
        
        # If no direct match, try to find a param whose value exists in mapping
        if source_param is None:
            for param_value in params.values():
                if isinstance(param_value, str) and param_value in mapping:
                    source_param = param_value
                    break
        
        if source_param is None:
            return None
        
        return mapping.get(source_param, source_param)
    
    @staticmethod
    def extract_variables(template: Any) -> set:
        """Extract all variable names from a template"""
        variables = set()
        
        def _extract(obj):
            if isinstance(obj, str):
                matches = TemplateEngine.VARIABLE_PATTERN.findall(obj)
                variables.update(matches)
            elif isinstance(obj, dict):
                for v in obj.values():
                    _extract(v)
            elif isinstance(obj, list):
                for item in obj:
                    _extract(item)
        
        _extract(template)
        return variables
