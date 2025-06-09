"""
Template Management System

This module provides comprehensive template management including loading, 
customization, validation, and conversion to ASR format.
"""

import os
import yaml
import json
from typing import Dict, List, Any, Optional, Union
from pathlib import Path
import uuid
from datetime import datetime

from app.services.strategy_templates import (
    StrategyTemplate, TemplateCustomization, TemplateValidator, 
    TemplateEngine, TemplateCategory, TemplateDifficulty
)
from app.core.asr.asr_schema import ASRStrategy


class TemplateLoader:
    """Loads and manages strategy templates from the filesystem."""
    
    def __init__(self, templates_directory: str = None):
        if templates_directory is None:
            # Default to app/templates directory
            current_dir = Path(__file__).parent.parent
            self.templates_directory = current_dir / "templates"
        else:
            self.templates_directory = Path(templates_directory)
        
        self.loaded_templates: Dict[str, StrategyTemplate] = {}
        self.template_index: Dict[str, Dict[str, Any]] = {}
        
    def load_all_templates(self) -> Dict[str, StrategyTemplate]:
        """Load all templates from the templates directory."""
        self.loaded_templates.clear()
        self.template_index.clear()
        
        # Load templates from each category directory
        for category_dir in self.templates_directory.iterdir():
            if category_dir.is_dir() and category_dir.name in [cat.value for cat in TemplateCategory]:
                self._load_category_templates(category_dir)
        
        self._build_template_index()
        return self.loaded_templates
    
    def _load_category_templates(self, category_dir: Path):
        """Load templates from a specific category directory."""
        for template_file in category_dir.glob("*.yaml"):
            try:
                with open(template_file, 'r', encoding='utf-8') as f:
                    yaml_content = f.read()
                
                template = StrategyTemplate.from_yaml(yaml_content)
                self.loaded_templates[template.metadata.id] = template
                
            except Exception as e:
                print(f"Error loading template {template_file}: {e}")
    
    def _build_template_index(self):
        """Build searchable index of templates."""
        for template_id, template in self.loaded_templates.items():
            self.template_index[template_id] = {
                "name": template.metadata.name,
                "category": template.metadata.category.value,
                "difficulty": template.metadata.difficulty.value,
                "description": template.metadata.description,
                "tags": template.metadata.tags,
                "market_types": template.metadata.market_types,
                "timeframes": template.metadata.timeframes,
                "parameter_count": len(template.parameters)
            }
    
    def get_template(self, template_id: str) -> Optional[StrategyTemplate]:
        """Get a specific template by ID."""
        return self.loaded_templates.get(template_id)
    
    def search_templates(
        self, 
        category: Optional[TemplateCategory] = None,
        difficulty: Optional[TemplateDifficulty] = None,
        tags: Optional[List[str]] = None,
        market_type: Optional[str] = None,
        search_text: Optional[str] = None
    ) -> List[StrategyTemplate]:
        """Search templates based on criteria."""
        results = []
        
        for template_id, template in self.loaded_templates.items():
            # Category filter
            if category and template.metadata.category != category:
                continue
            
            # Difficulty filter
            if difficulty and template.metadata.difficulty != difficulty:
                continue
            
            # Tags filter
            if tags:
                if not any(tag in template.metadata.tags for tag in tags):
                    continue
            
            # Market type filter
            if market_type:
                if market_type not in template.metadata.market_types:
                    continue
            
            # Text search
            if search_text:
                search_text_lower = search_text.lower()
                searchable_text = (
                    template.metadata.name + " " +
                    template.metadata.description + " " +
                    " ".join(template.metadata.tags)
                ).lower()
                
                if search_text_lower not in searchable_text:
                    continue
            
            results.append(template)
        
        return results
    
    def get_template_categories(self) -> Dict[str, List[Dict[str, Any]]]:
        """Get templates organized by category."""
        categories = {}
        
        for template in self.loaded_templates.values():
            category = template.metadata.category.value
            if category not in categories:
                categories[category] = []
            
            categories[category].append({
                "id": template.metadata.id,
                "name": template.metadata.name,
                "difficulty": template.metadata.difficulty.value,
                "description": template.metadata.description,
                "tags": template.metadata.tags
            })
        
        return categories


class TemplateCustomizationManager:
    """Manages template customizations and user preferences."""
    
    def __init__(self, template_loader: TemplateLoader):
        self.template_loader = template_loader
        self.template_engine = TemplateEngine()
        self.validator = TemplateValidator()
        
        # In-memory storage for customizations (in production, this would be database)
        self.user_customizations: Dict[int, Dict[str, TemplateCustomization]] = {}
    
    def create_customization(
        self,
        user_id: int,
        template_id: str,
        parameter_values: Dict[str, Any],
        custom_name: Optional[str] = None
    ) -> TemplateCustomization:
        """Create a new template customization."""
        template = self.template_loader.get_template(template_id)
        if not template:
            raise ValueError(f"Template {template_id} not found")
        
        customization = TemplateCustomization(
            template_id=template_id,
            user_id=user_id,
            parameter_values=parameter_values,
            custom_name=custom_name
        )
        
        # Validate customization
        errors = self.validator.validate_customization(template, customization)
        if errors:
            raise ValueError(f"Customization validation failed: {'; '.join(errors)}")
        
        # Store customization
        if user_id not in self.user_customizations:
            self.user_customizations[user_id] = {}
        
        self.user_customizations[user_id][customization.customization_id] = customization
        
        return customization
    
    def update_customization(
        self,
        user_id: int,
        customization_id: str,
        parameter_values: Dict[str, Any],
        custom_name: Optional[str] = None
    ) -> TemplateCustomization:
        """Update an existing customization."""
        if user_id not in self.user_customizations:
            raise ValueError("User has no customizations")
        
        if customization_id not in self.user_customizations[user_id]:
            raise ValueError("Customization not found")
        
        customization = self.user_customizations[user_id][customization_id]
        template = self.template_loader.get_template(customization.template_id)
        
        # Update values
        customization.parameter_values = parameter_values
        if custom_name is not None:
            customization.custom_name = custom_name
        
        # Validate updated customization
        errors = self.validator.validate_customization(template, customization)
        if errors:
            raise ValueError(f"Customization validation failed: {'; '.join(errors)}")
        
        return customization
    
    def get_user_customizations(self, user_id: int) -> List[TemplateCustomization]:
        """Get all customizations for a user."""
        if user_id not in self.user_customizations:
            return []
        
        return list(self.user_customizations[user_id].values())
    
    def get_customization(self, user_id: int, customization_id: str) -> Optional[TemplateCustomization]:
        """Get a specific customization."""
        if user_id not in self.user_customizations:
            return None
        
        return self.user_customizations[user_id].get(customization_id)
    
    def delete_customization(self, user_id: int, customization_id: str) -> bool:
        """Delete a customization."""
        if user_id not in self.user_customizations:
            return False
        
        if customization_id not in self.user_customizations[user_id]:
            return False
        
        del self.user_customizations[user_id][customization_id]
        return True
    
    def apply_customization(
        self,
        user_id: int,
        customization_id: str
    ) -> Dict[str, Any]:
        """Apply customization to template and return configured template."""
        customization = self.get_customization(user_id, customization_id)
        if not customization:
            raise ValueError("Customization not found")
        
        template = self.template_loader.get_template(customization.template_id)
        if not template:
            raise ValueError("Template not found")
        
        return self.template_engine.apply_customization(template, customization)
    
    def generate_asr_from_customization(
        self,
        user_id: int,
        customization_id: str
    ) -> ASRStrategy:
        """Generate ASR strategy from customization."""
        customization = self.get_customization(user_id, customization_id)
        if not customization:
            raise ValueError("Customization not found")
        
        template = self.template_loader.get_template(customization.template_id)
        if not template:
            raise ValueError("Template not found")
        
        return self.template_engine.template_to_asr(template, customization)
    
    def clone_customization(
        self,
        user_id: int,
        customization_id: str,
        new_name: Optional[str] = None
    ) -> TemplateCustomization:
        """Clone an existing customization."""
        original = self.get_customization(user_id, customization_id)
        if not original:
            raise ValueError("Customization not found")
        
        cloned = TemplateCustomization(
            template_id=original.template_id,
            user_id=user_id,
            parameter_values=original.parameter_values.copy(),
            custom_name=new_name or f"{original.custom_name or 'Strategy'} (Copy)"
        )
        
        self.user_customizations[user_id][cloned.customization_id] = cloned
        return cloned


class TemplateParameterHelper:
    """Helper for working with template parameters."""
    
    @staticmethod
    def get_parameter_suggestions(
        template: StrategyTemplate,
        parameter_name: str,
        current_values: Dict[str, Any]
    ) -> List[Any]:
        """Get suggested values for a parameter based on context."""
        param = next((p for p in template.parameters if p.name == parameter_name), None)
        if not param:
            return []
        
        suggestions = []
        
        if param.type.value == "integer":
            # Suggest common values within range
            min_val = param.min_value or 1
            max_val = param.max_value or 100
            
            if "period" in parameter_name.lower():
                # Common period values
                common_periods = [5, 10, 14, 20, 21, 50, 100, 200]
                suggestions = [p for p in common_periods if min_val <= p <= max_val]
            else:
                # Generate range suggestions
                step = max(1, (max_val - min_val) // 10)
                suggestions = list(range(min_val, max_val + 1, step))
        
        elif param.type.value == "float":
            min_val = param.min_value or 0.1
            max_val = param.max_value or 10.0
            
            if "multiplier" in parameter_name.lower():
                suggestions = [1.0, 1.5, 2.0, 2.5, 3.0]
            elif "percentage" in parameter_name.lower():
                suggestions = [1.0, 2.0, 3.0, 5.0, 10.0]
            else:
                step = (max_val - min_val) / 10
                suggestions = [round(min_val + i * step, 2) for i in range(11)]
        
        elif param.type.value == "choice":
            suggestions = param.choices or []
        
        # Filter suggestions based on constraints
        filtered_suggestions = []
        for suggestion in suggestions:
            if param.min_value is not None and suggestion < param.min_value:
                continue
            if param.max_value is not None and suggestion > param.max_value:
                continue
            filtered_suggestions.append(suggestion)
        
        return filtered_suggestions[:10]  # Limit to 10 suggestions
    
    @staticmethod
    def validate_parameter_value(
        template: StrategyTemplate,
        parameter_name: str,
        value: Any
    ) -> List[str]:
        """Validate a single parameter value."""
        param = next((p for p in template.parameters if p.name == parameter_name), None)
        if not param:
            return [f"Parameter {parameter_name} not found in template"]
        
        errors = []
        
        # Type validation
        if param.type.value == "integer" and not isinstance(value, int):
            errors.append(f"Parameter {parameter_name} must be an integer")
        elif param.type.value == "float" and not isinstance(value, (int, float)):
            errors.append(f"Parameter {parameter_name} must be a number")
        elif param.type.value == "boolean" and not isinstance(value, bool):
            errors.append(f"Parameter {parameter_name} must be true or false")
        elif param.type.value == "string" and not isinstance(value, str):
            errors.append(f"Parameter {parameter_name} must be a string")
        
        # Range validation
        if param.min_value is not None and value < param.min_value:
            errors.append(f"Parameter {parameter_name} must be >= {param.min_value}")
        if param.max_value is not None and value > param.max_value:
            errors.append(f"Parameter {parameter_name} must be <= {param.max_value}")
        
        # Choice validation
        if param.type.value == "choice" and value not in (param.choices or []):
            errors.append(f"Parameter {parameter_name} must be one of: {param.choices}")
        
        return errors
    
    @staticmethod
    def get_parameter_dependencies(
        template: StrategyTemplate,
        parameter_name: str
    ) -> List[str]:
        """Get parameters that depend on the given parameter."""
        dependencies = []
        
        # Simple dependency detection based on naming patterns
        if "period" in parameter_name.lower():
            # Look for related parameters
            for param in template.parameters:
                if param.name != parameter_name and "period" in param.name.lower():
                    if any(word in param.name.lower() for word in parameter_name.lower().split("_")):
                        dependencies.append(param.name)
        
        return dependencies


# Global instances
template_loader = TemplateLoader()
template_customization_manager = TemplateCustomizationManager(template_loader)