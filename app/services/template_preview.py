"""
Template Preview Generator

This module generates previews, summaries, and visual representations
of strategy templates for user interface display.
"""

from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass
from enum import Enum
import json

from app.services.strategy_templates import StrategyTemplate, TemplateCustomization
from app.services.template_manager import TemplateCustomizationManager
from app.services.code_generation import CodeLanguage, code_generation_engine
from app.core.asr.asr_schema import ASRStrategy


class PreviewType(str, Enum):
    """Types of template previews."""
    SUMMARY = "summary"
    LOGIC_FLOW = "logic_flow"
    CODE_PREVIEW = "code_preview"
    PARAMETER_OVERVIEW = "parameter_overview"
    RISK_ANALYSIS = "risk_analysis"
    PERFORMANCE_ESTIMATE = "performance_estimate"


@dataclass
class TemplatePreview:
    """Complete template preview information."""
    template_id: str
    preview_type: PreviewType
    title: str
    description: str
    content: Dict[str, Any]
    warnings: List[str]
    suggestions: List[str]
    metadata: Dict[str, Any]


@dataclass
class LogicFlowNode:
    """Node in logic flow diagram."""
    id: str
    type: str  # indicator, condition, action, filter
    label: str
    description: str
    connections: List[str]  # IDs of connected nodes
    properties: Dict[str, Any]


@dataclass
class LogicFlowDiagram:
    """Complete logic flow diagram."""
    nodes: List[LogicFlowNode]
    connections: List[Tuple[str, str]]  # (from_id, to_id)
    entry_points: List[str]  # Node IDs that are entry points
    exit_points: List[str]   # Node IDs that are exit points


class TemplatePreviewGenerator:
    """Generates various types of template previews."""
    
    def __init__(self, customization_manager: TemplateCustomizationManager):
        self.customization_manager = customization_manager
    
    def generate_preview(
        self,
        template: StrategyTemplate,
        preview_type: PreviewType,
        customization: Optional[TemplateCustomization] = None
    ) -> TemplatePreview:
        """Generate a specific type of preview."""
        
        if preview_type == PreviewType.SUMMARY:
            return self._generate_summary_preview(template, customization)
        elif preview_type == PreviewType.LOGIC_FLOW:
            return self._generate_logic_flow_preview(template, customization)
        elif preview_type == PreviewType.CODE_PREVIEW:
            return self._generate_code_preview(template, customization)
        elif preview_type == PreviewType.PARAMETER_OVERVIEW:
            return self._generate_parameter_overview(template, customization)
        elif preview_type == PreviewType.RISK_ANALYSIS:
            return self._generate_risk_analysis(template, customization)
        elif preview_type == PreviewType.PERFORMANCE_ESTIMATE:
            return self._generate_performance_estimate(template, customization)
        else:
            raise ValueError(f"Unknown preview type: {preview_type}")
    
    def _generate_summary_preview(
        self, 
        template: StrategyTemplate, 
        customization: Optional[TemplateCustomization]
    ) -> TemplatePreview:
        """Generate high-level strategy summary."""
        config = template.template_config
        if customization:
            config = self.customization_manager.template_engine.apply_customization(
                template, customization
            )
        
        # Count components
        indicator_count = len([i for i in config.get("indicators", []) if i.get("enabled", True)])
        entry_condition_count = len([c for c in config.get("entry_conditions", []) if c.get("enabled", True)])
        exit_condition_count = len([c for c in config.get("exit_conditions", []) if c.get("enabled", True)])
        
        # Analyze strategy characteristics
        has_stop_loss = config.get("risk_management", {}).get("stop_loss", {}).get("enabled", False)
        has_take_profit = config.get("risk_management", {}).get("take_profit", {}).get("enabled", False)
        max_positions = config.get("risk_management", {}).get("max_open_positions", 1)
        
        # Determine complexity
        total_components = indicator_count + entry_condition_count + exit_condition_count
        if total_components <= 5:
            complexity = "Simple"
        elif total_components <= 10:
            complexity = "Moderate"
        else:
            complexity = "Complex"
        
        # Generate warnings and suggestions
        warnings = []
        suggestions = []
        
        if not has_stop_loss:
            warnings.append("No stop loss detected - consider adding risk protection")
        
        if entry_condition_count > 5:
            warnings.append("Many entry conditions may lead to few trading opportunities")
        
        if indicator_count > 7:
            suggestions.append("Consider reducing number of indicators to avoid over-optimization")
        
        content = {
            "overview": {
                "strategy_type": template.metadata.category.value,
                "difficulty": template.metadata.difficulty.value,
                "complexity": complexity,
                "estimated_signals_per_week": self._estimate_signal_frequency(config),
                "risk_level": self._assess_risk_level(config)
            },
            "components": {
                "indicators": indicator_count,
                "entry_conditions": entry_condition_count,
                "exit_conditions": exit_condition_count,
                "filters": len(config.get("additional_filters", []))
            },
            "risk_management": {
                "has_stop_loss": has_stop_loss,
                "has_take_profit": has_take_profit,
                "max_positions": max_positions,
                "position_sizing": config.get("position_sizing", {}).get("method", "unknown")
            },
            "market_compatibility": {
                "recommended_markets": template.metadata.market_types,
                "recommended_timeframes": template.metadata.timeframes,
                "avoid_conditions": self._identify_avoid_conditions(config)
            }
        }
        
        return TemplatePreview(
            template_id=template.metadata.id,
            preview_type=PreviewType.SUMMARY,
            title=f"{template.metadata.name} - Strategy Summary",
            description=template.metadata.description,
            content=content,
            warnings=warnings,
            suggestions=suggestions,
            metadata={"complexity": complexity, "component_count": total_components}
        )
    
    def _generate_logic_flow_preview(
        self, 
        template: StrategyTemplate, 
        customization: Optional[TemplateCustomization]
    ) -> TemplatePreview:
        """Generate visual logic flow diagram."""
        config = template.template_config
        if customization:
            config = self.customization_manager.template_engine.apply_customization(
                template, customization
            )
        
        nodes = []
        connections = []
        
        # Create indicator nodes
        for i, indicator in enumerate(config.get("indicators", [])):
            if not indicator.get("enabled", True):
                continue
                
            node_id = f"indicator_{i}"
            nodes.append(LogicFlowNode(
                id=node_id,
                type="indicator",
                label=indicator["type"],
                description=indicator.get("description", ""),
                connections=[],
                properties=indicator.get("parameters", {})
            ))
        
        # Create entry condition nodes
        entry_node_ids = []
        for i, condition in enumerate(config.get("entry_conditions", [])):
            if not condition.get("enabled", True):
                continue
                
            node_id = f"entry_{i}"
            entry_node_ids.append(node_id)
            nodes.append(LogicFlowNode(
                id=node_id,
                type="condition",
                label=f"Entry: {condition.get('description', 'Condition')}",
                description=condition.get("description", ""),
                connections=[],
                properties={"operator": condition.get("operator", ""), "value": condition.get("value", "")}
            ))
        
        # Create exit condition nodes
        exit_node_ids = []
        for i, condition in enumerate(config.get("exit_conditions", [])):
            if not condition.get("enabled", True):
                continue
                
            node_id = f"exit_{i}"
            exit_node_ids.append(node_id)
            nodes.append(LogicFlowNode(
                id=node_id,
                type="condition",
                label=f"Exit: {condition.get('description', 'Condition')}",
                description=condition.get("description", ""),
                connections=[],
                properties={"operator": condition.get("operator", ""), "value": condition.get("value", "")}
            ))
        
        # Create action nodes
        buy_node = LogicFlowNode(
            id="action_buy",
            type="action",
            label="Buy Signal",
            description="Execute buy order",
            connections=[],
            properties={}
        )
        nodes.append(buy_node)
        
        sell_node = LogicFlowNode(
            id="action_sell",
            type="action", 
            label="Sell Signal",
            description="Execute sell order",
            connections=[],
            properties={}
        )
        nodes.append(sell_node)
        
        # Create connections
        for entry_id in entry_node_ids:
            connections.append((entry_id, "action_buy"))
        
        for exit_id in exit_node_ids:
            connections.append((exit_id, "action_sell"))
        
        diagram = LogicFlowDiagram(
            nodes=nodes,
            connections=connections,
            entry_points=entry_node_ids,
            exit_points=exit_node_ids
        )
        
        content = {
            "diagram": {
                "nodes": [node.__dict__ for node in diagram.nodes],
                "connections": diagram.connections,
                "entry_points": diagram.entry_points,
                "exit_points": diagram.exit_points
            },
            "flow_description": self._generate_flow_description(diagram),
            "complexity_metrics": {
                "total_nodes": len(nodes),
                "decision_points": len(entry_node_ids) + len(exit_node_ids),
                "branching_factor": len(connections) / max(len(nodes), 1)
            }
        }
        
        return TemplatePreview(
            template_id=template.metadata.id,
            preview_type=PreviewType.LOGIC_FLOW,
            title=f"{template.metadata.name} - Logic Flow",
            description="Visual representation of strategy logic",
            content=content,
            warnings=[],
            suggestions=[],
            metadata={"node_count": len(nodes)}
        )
    
    def _generate_code_preview(
        self, 
        template: StrategyTemplate, 
        customization: Optional[TemplateCustomization]
    ) -> TemplatePreview:
        """Generate code preview in multiple languages."""
        try:
            # Convert to ASR first
            asr_strategy = self.customization_manager.template_engine.template_to_asr(
                template, customization
            )
            
            # Generate code in multiple languages
            languages = [CodeLanguage.PYTHON, CodeLanguage.NINJASCRIPT]
            code_results = code_generation_engine.generate_code(
                asr_strategy, languages, validate=True, add_comments=True
            )
            
            previews = {}
            warnings = []
            suggestions = []
            
            for language, generated_code in code_results.items():
                # Get first 50 lines for preview
                code_lines = generated_code.code.split('\n')
                preview_lines = code_lines[:50]
                
                if len(code_lines) > 50:
                    preview_lines.append("... (truncated)")
                
                previews[language.value] = {
                    "preview": "\n".join(preview_lines),
                    "total_lines": len(code_lines),
                    "entry_point": generated_code.entry_point,
                    "dependencies": generated_code.dependencies,
                    "platform_notes": generated_code.platform_notes,
                    "is_valid": generated_code.validation_result.is_valid if generated_code.validation_result else True
                }
                
                # Collect warnings and suggestions
                if generated_code.validation_result:
                    warnings.extend(generated_code.validation_result.errors)
                    suggestions.extend(generated_code.validation_result.suggestions)
            
            content = {
                "code_previews": previews,
                "generation_summary": {
                    "languages_generated": len(previews),
                    "total_lines": sum(p["total_lines"] for p in previews.values()),
                    "all_valid": all(p["is_valid"] for p in previews.values())
                }
            }
            
        except Exception as e:
            content = {
                "error": str(e),
                "code_previews": {},
                "generation_summary": {"error": "Failed to generate code preview"}
            }
            warnings = [f"Code generation failed: {str(e)}"]
        
        return TemplatePreview(
            template_id=template.metadata.id,
            preview_type=PreviewType.CODE_PREVIEW,
            title=f"{template.metadata.name} - Code Preview",
            description="Generated code preview in multiple languages",
            content=content,
            warnings=warnings,
            suggestions=suggestions,
            metadata={}
        )
    
    def _generate_parameter_overview(
        self, 
        template: StrategyTemplate, 
        customization: Optional[TemplateCustomization]
    ) -> TemplatePreview:
        """Generate parameter overview and customization guide."""
        parameter_groups = {}
        current_values = {}
        
        if customization:
            current_values = customization.parameter_values
        
        # Group parameters by category
        for param in template.parameters:
            category = self._categorize_parameter(param.name)
            if category not in parameter_groups:
                parameter_groups[category] = []
            
            param_info = {
                "name": param.name,
                "type": param.type.value,
                "default": param.default,
                "current": current_values.get(param.name, param.default),
                "description": param.description,
                "constraints": {
                    "min": param.min_value,
                    "max": param.max_value,
                    "choices": param.choices
                },
                "required": param.required,
                "impact": self._assess_parameter_impact(param.name)
            }
            parameter_groups[category].append(param_info)
        
        # Generate customization recommendations
        recommendations = self._generate_parameter_recommendations(template, current_values)
        
        content = {
            "parameter_groups": parameter_groups,
            "total_parameters": len(template.parameters),
            "customizable_parameters": len([p for p in template.parameters if not p.required]),
            "current_customization": {
                "is_customized": customization is not None,
                "customized_count": len(current_values) if current_values else 0,
                "custom_name": customization.custom_name if customization else None
            },
            "recommendations": recommendations
        }
        
        warnings = []
        suggestions = []
        
        # Analyze parameter values for warnings
        for param in template.parameters:
            current_val = current_values.get(param.name, param.default)
            
            if param.min_value is not None and current_val == param.min_value:
                warnings.append(f"Parameter '{param.name}' is at minimum value - consider if this is appropriate")
            
            if param.max_value is not None and current_val == param.max_value:
                warnings.append(f"Parameter '{param.name}' is at maximum value - consider if this is appropriate")
        
        return TemplatePreview(
            template_id=template.metadata.id,
            preview_type=PreviewType.PARAMETER_OVERVIEW,
            title=f"{template.metadata.name} - Parameters",
            description="Detailed parameter overview and customization guide",
            content=content,
            warnings=warnings,
            suggestions=suggestions,
            metadata={"parameter_count": len(template.parameters)}
        )
    
    def _estimate_signal_frequency(self, config: Dict[str, Any]) -> str:
        """Estimate signal frequency based on strategy configuration."""
        condition_count = len(config.get("entry_conditions", []))
        
        if condition_count <= 2:
            return "High (10-20 signals)"
        elif condition_count <= 4:
            return "Medium (5-10 signals)"
        else:
            return "Low (1-5 signals)"
    
    def _assess_risk_level(self, config: Dict[str, Any]) -> str:
        """Assess overall risk level of strategy."""
        risk_factors = 0
        
        if not config.get("risk_management", {}).get("stop_loss"):
            risk_factors += 2
        
        if config.get("risk_management", {}).get("max_open_positions", 1) > 5:
            risk_factors += 1
        
        if len(config.get("entry_conditions", [])) < 2:
            risk_factors += 1
        
        if risk_factors >= 3:
            return "High"
        elif risk_factors >= 1:
            return "Medium"
        else:
            return "Low"
    
    def _identify_avoid_conditions(self, config: Dict[str, Any]) -> List[str]:
        """Identify conditions to avoid based on strategy."""
        avoid_conditions = []
        
        # Check for news/earnings filters
        filters = config.get("additional_filters", [])
        for filter_config in filters:
            if "news" in filter_config.get("name", "").lower():
                avoid_conditions.append("Major news events")
            if "earnings" in filter_config.get("name", "").lower():
                avoid_conditions.append("Earnings announcements")
        
        # Check time restrictions
        time_restrictions = config.get("time_restrictions", {})
        if "avoid_first_15_minutes" in time_restrictions:
            avoid_conditions.append("Market open volatility")
        
        return avoid_conditions
    
    def _generate_flow_description(self, diagram: LogicFlowDiagram) -> str:
        """Generate natural language description of logic flow."""
        entry_count = len(diagram.entry_points)
        exit_count = len(diagram.exit_points)
        
        description = f"This strategy uses {entry_count} entry condition(s) and {exit_count} exit condition(s). "
        
        if entry_count > 1:
            description += "All entry conditions must be met simultaneously for a signal. "
        
        if exit_count > 1:
            description += "Any exit condition can trigger position closure. "
        
        indicator_nodes = [n for n in diagram.nodes if n.type == "indicator"]
        if indicator_nodes:
            description += f"The strategy relies on {len(indicator_nodes)} technical indicator(s) for decision making."
        
        return description
    
    def _categorize_parameter(self, param_name: str) -> str:
        """Categorize parameter into logical groups."""
        name_lower = param_name.lower()
        
        if any(word in name_lower for word in ["period", "length", "window"]):
            return "Indicator Settings"
        elif any(word in name_lower for word in ["stop", "loss", "profit", "risk"]):
            return "Risk Management"
        elif any(word in name_lower for word in ["size", "position", "amount"]):
            return "Position Sizing"
        elif any(word in name_lower for word in ["time", "hour", "day", "session"]):
            return "Time Filters"
        elif any(word in name_lower for word in ["volume", "threshold", "filter"]):
            return "Market Filters"
        else:
            return "Strategy Logic"
    
    def _assess_parameter_impact(self, param_name: str) -> str:
        """Assess the impact level of a parameter."""
        high_impact_keywords = ["stop_loss", "take_profit", "position_size", "risk"]
        medium_impact_keywords = ["period", "threshold", "multiplier"]
        
        name_lower = param_name.lower()
        
        if any(keyword in name_lower for keyword in high_impact_keywords):
            return "High"
        elif any(keyword in name_lower for keyword in medium_impact_keywords):
            return "Medium"
        else:
            return "Low"
    
    def _generate_parameter_recommendations(
        self, 
        template: StrategyTemplate, 
        current_values: Dict[str, Any]
    ) -> List[Dict[str, str]]:
        """Generate parameter customization recommendations."""
        recommendations = []
        
        # Strategy-specific recommendations
        if template.metadata.category.value == "momentum":
            recommendations.append({
                "category": "Momentum Strategy Tip",
                "suggestion": "Consider shorter indicator periods (5-20) for faster signals",
                "reason": "Momentum strategies benefit from responsive indicators"
            })
        elif template.metadata.category.value == "mean_reversion":
            recommendations.append({
                "category": "Mean Reversion Tip", 
                "suggestion": "Use longer indicator periods (20-50) for stable signals",
                "reason": "Mean reversion works better with smoothed indicators"
            })
        
        # Risk management recommendations
        stop_loss_params = [p for p in template.parameters if "stop" in p.name.lower()]
        if stop_loss_params:
            recommendations.append({
                "category": "Risk Management",
                "suggestion": "Start with conservative stop loss values (2-3%)",
                "reason": "Protect capital while learning strategy behavior"
            })
        
        return recommendations
    
    def _generate_risk_analysis(
        self, 
        template: StrategyTemplate, 
        customization: Optional[TemplateCustomization]
    ) -> TemplatePreview:
        """Generate risk analysis preview."""
        # This would contain risk metrics analysis
        content = {
            "risk_summary": "Risk analysis not yet implemented",
            "estimated_metrics": {
                "max_drawdown": "TBD",
                "sharpe_ratio": "TBD",
                "win_rate": "TBD"
            }
        }
        
        return TemplatePreview(
            template_id=template.metadata.id,
            preview_type=PreviewType.RISK_ANALYSIS,
            title=f"{template.metadata.name} - Risk Analysis",
            description="Risk characteristics and estimated metrics",
            content=content,
            warnings=[],
            suggestions=[],
            metadata={}
        )
    
    def _generate_performance_estimate(
        self, 
        template: StrategyTemplate, 
        customization: Optional[TemplateCustomization]
    ) -> TemplatePreview:
        """Generate performance estimate preview."""
        # This would contain performance projections
        content = {
            "performance_summary": "Performance estimation not yet implemented",
            "estimated_returns": {
                "annual_return": "TBD",
                "monthly_return": "TBD",
                "volatility": "TBD"
            }
        }
        
        return TemplatePreview(
            template_id=template.metadata.id,
            preview_type=PreviewType.PERFORMANCE_ESTIMATE,
            title=f"{template.metadata.name} - Performance Estimate",
            description="Estimated performance characteristics",
            content=content,
            warnings=[],
            suggestions=[],
            metadata={}
        )


# Global instance
template_preview_generator = None  # Will be initialized with customization manager