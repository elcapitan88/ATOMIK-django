"""
Strategy Template System

This module provides a comprehensive template system for creating, customizing,
and managing trading strategy templates. Templates are defined in YAML format
and can be converted to ASR (Abstract Strategy Representation) for code generation.
"""

import yaml
import json
from typing import Dict, List, Any, Optional, Union
from enum import Enum
from dataclasses import dataclass, field
from datetime import datetime
import uuid
from pathlib import Path

from app.core.asr.asr_schema import (
    ASRStrategy, IndicatorConfig, EntryCondition, ExitCondition,
    RiskManagement, PositionSizing, TimeRestrictions, StrategyMetadata,
    IndicatorType, ComparisonOperator, LogicalOperator, PositionSizingMethod
)


class TemplateCategory(str, Enum):
    """Strategy template categories."""
    MOMENTUM = "momentum"
    MEAN_REVERSION = "mean_reversion"
    TREND_FOLLOWING = "trend_following"
    GENERIC = "generic"
    CUSTOM = "custom"


class TemplateDifficulty(str, Enum):
    """Template difficulty levels."""
    BEGINNER = "beginner"
    INTERMEDIATE = "intermediate"
    ADVANCED = "advanced"
    EXPERT = "expert"


class ParameterType(str, Enum):
    """Parameter types for template customization."""
    INTEGER = "integer"
    FLOAT = "float"
    STRING = "string"
    BOOLEAN = "boolean"
    CHOICE = "choice"
    PERCENTAGE = "percentage"
    PRICE = "price"


@dataclass
class ParameterDefinition:
    """Definition of a customizable template parameter."""
    name: str
    type: ParameterType
    default: Any
    description: str
    min_value: Optional[Union[int, float]] = None
    max_value: Optional[Union[int, float]] = None
    choices: Optional[List[str]] = None
    required: bool = True
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "name": self.name,
            "type": self.type.value,
            "default": self.default,
            "description": self.description,
            "min_value": self.min_value,
            "max_value": self.max_value,
            "choices": self.choices,
            "required": self.required
        }


@dataclass
class TemplateMetadata:
    """Template metadata information."""
    id: str
    name: str
    category: TemplateCategory
    difficulty: TemplateDifficulty
    description: str
    version: str = "1.0"
    author: str = "System"
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    tags: List[str] = field(default_factory=list)
    market_types: List[str] = field(default_factory=lambda: ["stocks", "forex", "crypto"])
    timeframes: List[str] = field(default_factory=lambda: ["5m", "15m", "1h", "4h", "1d"])
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "name": self.name,
            "category": self.category.value,
            "difficulty": self.difficulty.value,
            "description": self.description,
            "version": self.version,
            "author": self.author,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "tags": self.tags,
            "market_types": self.market_types,
            "timeframes": self.timeframes
        }


@dataclass
class StrategyTemplate:
    """Complete strategy template definition."""
    metadata: TemplateMetadata
    parameters: List[ParameterDefinition]
    template_config: Dict[str, Any]  # The YAML template structure
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "metadata": self.metadata.to_dict(),
            "parameters": [p.to_dict() for p in self.parameters],
            "template_config": self.template_config
        }
    
    def to_yaml(self) -> str:
        """Convert to YAML string."""
        return yaml.dump(self.to_dict(), default_flow_style=False, sort_keys=False)
    
    @classmethod
    def from_yaml(cls, yaml_content: str) -> 'StrategyTemplate':
        """Create template from YAML content."""
        data = yaml.safe_load(yaml_content)
        
        # Parse metadata
        metadata_data = data["metadata"]
        metadata = TemplateMetadata(
            id=metadata_data["id"],
            name=metadata_data["name"],
            category=TemplateCategory(metadata_data["category"]),
            difficulty=TemplateDifficulty(metadata_data["difficulty"]),
            description=metadata_data["description"],
            version=metadata_data.get("version", "1.0"),
            author=metadata_data.get("author", "System"),
            created_at=datetime.fromisoformat(metadata_data.get("created_at", datetime.utcnow().isoformat())),
            updated_at=datetime.fromisoformat(metadata_data.get("updated_at", datetime.utcnow().isoformat())),
            tags=metadata_data.get("tags", []),
            market_types=metadata_data.get("market_types", ["stocks", "forex", "crypto"]),
            timeframes=metadata_data.get("timeframes", ["5m", "15m", "1h", "4h", "1d"])
        )
        
        # Parse parameters
        parameters = []
        for param_data in data["parameters"]:
            param = ParameterDefinition(
                name=param_data["name"],
                type=ParameterType(param_data["type"]),
                default=param_data["default"],
                description=param_data["description"],
                min_value=param_data.get("min_value"),
                max_value=param_data.get("max_value"),
                choices=param_data.get("choices"),
                required=param_data.get("required", True)
            )
            parameters.append(param)
        
        return cls(
            metadata=metadata,
            parameters=parameters,
            template_config=data["template_config"]
        )


@dataclass
class TemplateCustomization:
    """User customization of a template."""
    template_id: str
    user_id: int
    customization_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    parameter_values: Dict[str, Any] = field(default_factory=dict)
    custom_name: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "template_id": self.template_id,
            "user_id": self.user_id,
            "customization_id": self.customization_id,
            "parameter_values": self.parameter_values,
            "custom_name": self.custom_name,
            "created_at": self.created_at.isoformat()
        }


class TemplateValidator:
    """Validates template definitions and customizations."""
    
    @staticmethod
    def validate_template(template: StrategyTemplate) -> List[str]:
        """Validate template definition."""
        errors = []
        
        # Validate metadata
        if not template.metadata.name:
            errors.append("Template name is required")
        
        if not template.metadata.description:
            errors.append("Template description is required")
        
        # Validate parameters
        parameter_names = set()
        for param in template.parameters:
            if param.name in parameter_names:
                errors.append(f"Duplicate parameter name: {param.name}")
            parameter_names.add(param.name)
            
            # Validate parameter constraints
            if param.type == ParameterType.INTEGER:
                if not isinstance(param.default, int):
                    errors.append(f"Parameter {param.name} default must be integer")
            elif param.type == ParameterType.FLOAT:
                if not isinstance(param.default, (int, float)):
                    errors.append(f"Parameter {param.name} default must be numeric")
            elif param.type == ParameterType.CHOICE:
                if not param.choices:
                    errors.append(f"Parameter {param.name} must have choices defined")
                elif param.default not in param.choices:
                    errors.append(f"Parameter {param.name} default must be in choices")
        
        # Validate template config structure
        config = template.template_config
        required_sections = ["indicators", "entry_conditions", "exit_conditions"]
        for section in required_sections:
            if section not in config:
                errors.append(f"Template config missing required section: {section}")
        
        return errors
    
    @staticmethod
    def validate_customization(
        template: StrategyTemplate, 
        customization: TemplateCustomization
    ) -> List[str]:
        """Validate user customization against template."""
        errors = []
        
        # Check all required parameters are provided
        required_params = {p.name for p in template.parameters if p.required}
        provided_params = set(customization.parameter_values.keys())
        
        missing_params = required_params - provided_params
        if missing_params:
            errors.append(f"Missing required parameters: {', '.join(missing_params)}")
        
        # Validate parameter values
        param_dict = {p.name: p for p in template.parameters}
        
        for param_name, value in customization.parameter_values.items():
            if param_name not in param_dict:
                errors.append(f"Unknown parameter: {param_name}")
                continue
            
            param = param_dict[param_name]
            
            # Type validation
            if param.type == ParameterType.INTEGER and not isinstance(value, int):
                errors.append(f"Parameter {param_name} must be integer")
            elif param.type == ParameterType.FLOAT and not isinstance(value, (int, float)):
                errors.append(f"Parameter {param_name} must be numeric")
            elif param.type == ParameterType.BOOLEAN and not isinstance(value, bool):
                errors.append(f"Parameter {param_name} must be boolean")
            elif param.type == ParameterType.CHOICE and value not in param.choices:
                errors.append(f"Parameter {param_name} must be one of: {param.choices}")
            
            # Range validation
            if param.min_value is not None and value < param.min_value:
                errors.append(f"Parameter {param_name} must be >= {param.min_value}")
            if param.max_value is not None and value > param.max_value:
                errors.append(f"Parameter {param_name} must be <= {param.max_value}")
        
        return errors


class TemplateEngine:
    """Template processing and conversion engine."""
    
    def __init__(self):
        self.validator = TemplateValidator()
    
    def apply_customization(
        self, 
        template: StrategyTemplate, 
        customization: TemplateCustomization
    ) -> Dict[str, Any]:
        """Apply user customization to template configuration."""
        # Validate first
        errors = self.validator.validate_customization(template, customization)
        if errors:
            raise ValueError(f"Customization validation failed: {'; '.join(errors)}")
        
        # Deep copy template config
        config = json.loads(json.dumps(template.template_config))
        
        # Apply parameter substitutions
        param_values = {}
        for param in template.parameters:
            if param.name in customization.parameter_values:
                param_values[param.name] = customization.parameter_values[param.name]
            else:
                param_values[param.name] = param.default
        
        # Recursively substitute parameters in config
        def substitute_params(obj):
            if isinstance(obj, str):
                # Replace {{param_name}} with actual values
                for param_name, param_value in param_values.items():
                    placeholder = f"{{{{{param_name}}}}}"
                    if placeholder in obj:
                        obj = obj.replace(placeholder, str(param_value))
                return obj
            elif isinstance(obj, dict):
                return {k: substitute_params(v) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [substitute_params(item) for item in obj]
            else:
                return obj
        
        customized_config = substitute_params(config)
        
        # Add customization metadata
        customized_config["customization"] = {
            "template_id": template.metadata.id,
            "customization_id": customization.customization_id,
            "user_id": customization.user_id,
            "applied_at": datetime.utcnow().isoformat(),
            "parameter_values": param_values
        }
        
        return customized_config
    
    def template_to_asr(
        self, 
        template: StrategyTemplate, 
        customization: Optional[TemplateCustomization] = None
    ) -> ASRStrategy:
        """Convert template (with optional customization) to ASR format."""
        # Apply customization if provided
        if customization:
            config = self.apply_customization(template, customization)
        else:
            # Use default parameter values
            default_customization = TemplateCustomization(
                template_id=template.metadata.id,
                user_id=0,  # System user
                parameter_values={p.name: p.default for p in template.parameters}
            )
            config = self.apply_customization(template, default_customization)
        
        # Create ASR metadata
        asr_metadata = StrategyMetadata(
            name=customization.custom_name if customization and customization.custom_name else template.metadata.name,
            description=template.metadata.description,
            version=template.metadata.version,
            author=template.metadata.author,
            created_at=template.metadata.created_at,
            tags=template.metadata.tags
        )
        
        # Convert indicators
        indicators = []
        for indicator_config in config.get("indicators", []):
            indicator = IndicatorConfig(
                id=str(uuid.uuid4()),
                type=IndicatorType(indicator_config["type"]),
                parameters=indicator_config.get("parameters", {}),
                description=indicator_config.get("description", "")
            )
            indicators.append(indicator)
        
        # Convert entry conditions
        entry_conditions = []
        for condition_config in config.get("entry_conditions", []):
            condition = EntryCondition(
                id=str(uuid.uuid4()),
                description=condition_config.get("description", ""),
                indicator_id=condition_config.get("indicator_id", ""),
                comparison_operator=ComparisonOperator(condition_config.get("operator", "GREATER_THAN")),
                value=condition_config.get("value", 0),
                logical_operator=LogicalOperator(condition_config.get("logical_operator", "AND"))
            )
            entry_conditions.append(condition)
        
        # Convert exit conditions
        exit_conditions = []
        for condition_config in config.get("exit_conditions", []):
            condition = ExitCondition(
                id=str(uuid.uuid4()),
                description=condition_config.get("description", ""),
                indicator_id=condition_config.get("indicator_id", ""),
                comparison_operator=ComparisonOperator(condition_config.get("operator", "LESS_THAN")),
                value=condition_config.get("value", 0),
                logical_operator=LogicalOperator(condition_config.get("logical_operator", "OR"))
            )
            exit_conditions.append(condition)
        
        # Convert risk management
        risk_management = None
        if "risk_management" in config:
            risk_config = config["risk_management"]
            risk_management = RiskManagement(
                stop_loss=risk_config.get("stop_loss"),
                take_profit=risk_config.get("take_profit"),
                trailing_stop=risk_config.get("trailing_stop"),
                max_daily_loss=risk_config.get("max_daily_loss"),
                max_open_positions=risk_config.get("max_open_positions", 1)
            )
        
        # Convert position sizing
        position_sizing = None
        if "position_sizing" in config:
            sizing_config = config["position_sizing"]
            position_sizing = PositionSizing(
                method=PositionSizingMethod(sizing_config.get("method", "FIXED_SHARES")),
                parameters=sizing_config.get("parameters", {})
            )
        
        # Convert time restrictions
        time_restrictions = None
        if "time_restrictions" in config:
            time_config = config["time_restrictions"]
            time_restrictions = TimeRestrictions(
                trading_sessions=time_config.get("trading_sessions", []),
                days_of_week=time_config.get("days_of_week", []),
                start_time=time_config.get("start_time"),
                end_time=time_config.get("end_time")
            )
        
        return ASRStrategy(
            metadata=asr_metadata,
            indicators=indicators,
            entry_conditions=entry_conditions,
            exit_conditions=exit_conditions,
            risk_management=risk_management,
            position_sizing=position_sizing,
            time_restrictions=time_restrictions
        )


# Global template engine instance
template_engine = TemplateEngine()