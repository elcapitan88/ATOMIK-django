"""
Template Versioning System

This module handles versioning, migration, and backward compatibility
for strategy templates.
"""

import semver
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
import json

from app.services.strategy_templates import StrategyTemplate, TemplateCustomization


class VersionChangeType(str, Enum):
    """Types of version changes."""
    MAJOR = "major"       # Breaking changes
    MINOR = "minor"       # New features, backward compatible
    PATCH = "patch"       # Bug fixes, backward compatible


@dataclass
class VersionChange:
    """Represents a change between template versions."""
    change_type: VersionChangeType
    description: str
    breaking_change: bool
    migration_required: bool
    affected_parameters: List[str]


@dataclass
class TemplateVersion:
    """Represents a specific version of a template."""
    template_id: str
    version: str
    created_at: datetime
    changelog: List[VersionChange]
    deprecated: bool = False
    deprecation_reason: Optional[str] = None
    successor_version: Optional[str] = None


class TemplateMigrator:
    """Handles migration of templates and customizations between versions."""
    
    def __init__(self):
        self.migration_rules: Dict[str, Dict[str, callable]] = {}
    
    def register_migration_rule(
        self,
        template_id: str,
        from_version: str,
        to_version: str,
        migration_function: callable
    ):
        """Register a migration rule for a specific version transition."""
        if template_id not in self.migration_rules:
            self.migration_rules[template_id] = {}
        
        key = f"{from_version}->{to_version}"
        self.migration_rules[template_id][key] = migration_function
    
    def can_migrate(self, template_id: str, from_version: str, to_version: str) -> bool:
        """Check if migration is possible between versions."""
        if template_id not in self.migration_rules:
            return False
        
        # Check direct migration
        direct_key = f"{from_version}->{to_version}"
        if direct_key in self.migration_rules[template_id]:
            return True
        
        # Check if we can find a migration path
        return self._find_migration_path(template_id, from_version, to_version) is not None
    
    def migrate_template(
        self,
        template: StrategyTemplate,
        target_version: str
    ) -> StrategyTemplate:
        """Migrate template to target version."""
        current_version = template.metadata.version
        
        if current_version == target_version:
            return template
        
        migration_path = self._find_migration_path(
            template.metadata.id, current_version, target_version
        )
        
        if not migration_path:
            raise ValueError(f"No migration path found from {current_version} to {target_version}")
        
        migrated_template = template
        
        for from_ver, to_ver in migration_path:
            migration_key = f"{from_ver}->{to_ver}"
            migration_func = self.migration_rules[template.metadata.id][migration_key]
            migrated_template = migration_func(migrated_template)
        
        return migrated_template
    
    def migrate_customization(
        self,
        customization: TemplateCustomization,
        old_template: StrategyTemplate,
        new_template: StrategyTemplate
    ) -> TemplateCustomization:
        """Migrate customization to work with new template version."""
        # Create mapping of old parameters to new parameters
        old_params = {p.name: p for p in old_template.parameters}
        new_params = {p.name: p for p in new_template.parameters}
        
        migrated_values = {}
        migration_notes = []
        
        for param_name, value in customization.parameter_values.items():
            if param_name in new_params:
                # Parameter exists in new version
                old_param = old_params.get(param_name)
                new_param = new_params[param_name]
                
                # Check if parameter type or constraints changed
                if old_param and old_param.type != new_param.type:
                    # Type changed - attempt conversion
                    try:
                        converted_value = self._convert_parameter_value(
                            value, old_param.type, new_param.type
                        )
                        migrated_values[param_name] = converted_value
                        migration_notes.append(f"Converted {param_name} from {old_param.type} to {new_param.type}")
                    except:
                        # Use default value if conversion fails
                        migrated_values[param_name] = new_param.default
                        migration_notes.append(f"Reset {param_name} to default due to type change")
                else:
                    # Validate constraints
                    if self._validate_parameter_constraints(value, new_param):
                        migrated_values[param_name] = value
                    else:
                        migrated_values[param_name] = new_param.default
                        migration_notes.append(f"Reset {param_name} to default due to constraint violation")
            else:
                # Parameter removed in new version
                migration_notes.append(f"Removed parameter {param_name} (no longer exists)")
        
        # Add default values for new required parameters
        for param_name, param in new_params.items():
            if param_name not in migrated_values and param.required:
                migrated_values[param_name] = param.default
                migration_notes.append(f"Added new required parameter {param_name}")
        
        # Create migrated customization
        migrated_customization = TemplateCustomization(
            template_id=new_template.metadata.id,
            user_id=customization.user_id,
            parameter_values=migrated_values,
            custom_name=customization.custom_name
        )
        
        # Store migration notes in metadata (if we had a metadata field)
        # For now, we'll just return the migrated customization
        
        return migrated_customization
    
    def _find_migration_path(
        self,
        template_id: str,
        from_version: str,
        to_version: str
    ) -> Optional[List[Tuple[str, str]]]:
        """Find migration path between versions using graph traversal."""
        if template_id not in self.migration_rules:
            return None
        
        # Simple BFS to find path
        from collections import deque
        
        queue = deque([(from_version, [])])
        visited = {from_version}
        
        while queue:
            current_version, path = queue.popleft()
            
            if current_version == to_version:
                return path
            
            # Find all possible next versions
            for migration_key in self.migration_rules[template_id]:
                from_ver, to_ver = migration_key.split('->')
                
                if from_ver == current_version and to_ver not in visited:
                    visited.add(to_ver)
                    new_path = path + [(from_ver, to_ver)]
                    queue.append((to_ver, new_path))
        
        return None
    
    def _convert_parameter_value(self, value: Any, old_type, new_type) -> Any:
        """Convert parameter value between types."""
        # Simple type conversion logic
        if old_type == new_type:
            return value
        
        if new_type.value == "string":
            return str(value)
        elif new_type.value == "integer":
            return int(float(value))
        elif new_type.value == "float":
            return float(value)
        elif new_type.value == "boolean":
            if isinstance(value, str):
                return value.lower() in ['true', '1', 'yes', 'on']
            return bool(value)
        
        raise ValueError(f"Cannot convert from {old_type} to {new_type}")
    
    def _validate_parameter_constraints(self, value: Any, param) -> bool:
        """Validate value against parameter constraints."""
        if param.min_value is not None and value < param.min_value:
            return False
        if param.max_value is not None and value > param.max_value:
            return False
        if param.choices and value not in param.choices:
            return False
        
        return True


class TemplateVersionManager:
    """Manages template versions and provides version control functionality."""
    
    def __init__(self):
        self.versions: Dict[str, List[TemplateVersion]] = {}
        self.migrator = TemplateMigrator()
        self._register_default_migrations()
    
    def register_template_version(
        self,
        template: StrategyTemplate,
        changelog: List[VersionChange]
    ) -> TemplateVersion:
        """Register a new version of a template."""
        template_id = template.metadata.id
        version = template.metadata.version
        
        if template_id not in self.versions:
            self.versions[template_id] = []
        
        # Validate version format
        try:
            semver.VersionInfo.parse(version)
        except ValueError:
            raise ValueError(f"Invalid version format: {version}")
        
        # Check if version already exists
        existing_versions = [v.version for v in self.versions[template_id]]
        if version in existing_versions:
            raise ValueError(f"Version {version} already exists for template {template_id}")
        
        template_version = TemplateVersion(
            template_id=template_id,
            version=version,
            created_at=datetime.utcnow(),
            changelog=changelog
        )
        
        self.versions[template_id].append(template_version)
        
        # Sort versions
        self.versions[template_id].sort(
            key=lambda v: semver.VersionInfo.parse(v.version)
        )
        
        return template_version
    
    def get_template_versions(self, template_id: str) -> List[TemplateVersion]:
        """Get all versions of a template."""
        return self.versions.get(template_id, [])
    
    def get_latest_version(self, template_id: str) -> Optional[TemplateVersion]:
        """Get the latest version of a template."""
        versions = self.get_template_versions(template_id)
        return versions[-1] if versions else None
    
    def is_version_deprecated(self, template_id: str, version: str) -> bool:
        """Check if a template version is deprecated."""
        template_versions = self.get_template_versions(template_id)
        
        for tv in template_versions:
            if tv.version == version:
                return tv.deprecated
        
        return False
    
    def deprecate_version(
        self,
        template_id: str,
        version: str,
        reason: str,
        successor_version: Optional[str] = None
    ):
        """Mark a template version as deprecated."""
        template_versions = self.get_template_versions(template_id)
        
        for tv in template_versions:
            if tv.version == version:
                tv.deprecated = True
                tv.deprecation_reason = reason
                tv.successor_version = successor_version
                break
    
    def compare_versions(
        self,
        template_id: str,
        version1: str,
        version2: str
    ) -> Dict[str, Any]:
        """Compare two versions of a template."""
        v1_info = semver.VersionInfo.parse(version1)
        v2_info = semver.VersionInfo.parse(version2)
        
        comparison = {
            "version1": version1,
            "version2": version2,
            "comparison": "equal" if v1_info == v2_info else (
                "newer" if v1_info > v2_info else "older"
            ),
            "major_diff": abs(v1_info.major - v2_info.major),
            "minor_diff": abs(v1_info.minor - v2_info.minor),
            "patch_diff": abs(v1_info.patch - v2_info.patch),
            "migration_available": self.migrator.can_migrate(template_id, version1, version2)
        }
        
        return comparison
    
    def get_upgrade_path(
        self,
        template_id: str,
        current_version: str
    ) -> Dict[str, Any]:
        """Get recommended upgrade path for a template version."""
        latest = self.get_latest_version(template_id)
        if not latest:
            return {"error": "No versions found for template"}
        
        latest_version = latest.version
        
        if current_version == latest_version:
            return {
                "current_version": current_version,
                "latest_version": latest_version,
                "upgrade_needed": False,
                "message": "Already on latest version"
            }
        
        comparison = self.compare_versions(template_id, current_version, latest_version)
        
        upgrade_info = {
            "current_version": current_version,
            "latest_version": latest_version,
            "upgrade_needed": True,
            "migration_available": comparison["migration_available"],
            "version_gap": {
                "major": comparison["major_diff"],
                "minor": comparison["minor_diff"],
                "patch": comparison["patch_diff"]
            }
        }
        
        # Add breaking changes warning
        if comparison["major_diff"] > 0:
            upgrade_info["breaking_changes"] = True
            upgrade_info["warning"] = "Major version upgrade may contain breaking changes"
        
        # Check if current version is deprecated
        if self.is_version_deprecated(template_id, current_version):
            upgrade_info["deprecated"] = True
            upgrade_info["urgency"] = "high"
        
        return upgrade_info
    
    def _register_default_migrations(self):
        """Register default migration rules for template updates."""
        # Example migration rules (would be expanded based on actual template changes)
        
        def migrate_1_0_to_1_1(template: StrategyTemplate) -> StrategyTemplate:
            """Example migration from version 1.0 to 1.1."""
            # Update version
            template.metadata.version = "1.1"
            template.metadata.updated_at = datetime.utcnow()
            
            # Add any new parameters or modify existing ones
            # This is just an example - real migrations would be more complex
            
            return template
        
        # Register example migration (this would be done for actual template versions)
        # self.migrator.register_migration_rule(
        #     "template_id",
        #     "1.0",
        #     "1.1", 
        #     migrate_1_0_to_1_1
        # )


class TemplateChangelogGenerator:
    """Generates changelogs for template versions."""
    
    @staticmethod
    def generate_changelog(
        old_template: StrategyTemplate,
        new_template: StrategyTemplate
    ) -> List[VersionChange]:
        """Generate changelog between two template versions."""
        changes = []
        
        # Compare parameters
        old_params = {p.name: p for p in old_template.parameters}
        new_params = {p.name: p for p in new_template.parameters}
        
        # Find added parameters
        for param_name in new_params:
            if param_name not in old_params:
                changes.append(VersionChange(
                    change_type=VersionChangeType.MINOR,
                    description=f"Added parameter: {param_name}",
                    breaking_change=False,
                    migration_required=False,
                    affected_parameters=[param_name]
                ))
        
        # Find removed parameters
        for param_name in old_params:
            if param_name not in new_params:
                changes.append(VersionChange(
                    change_type=VersionChangeType.MAJOR,
                    description=f"Removed parameter: {param_name}",
                    breaking_change=True,
                    migration_required=True,
                    affected_parameters=[param_name]
                ))
        
        # Find modified parameters
        for param_name in old_params:
            if param_name in new_params:
                old_param = old_params[param_name]
                new_param = new_params[param_name]
                
                if old_param.type != new_param.type:
                    changes.append(VersionChange(
                        change_type=VersionChangeType.MAJOR,
                        description=f"Changed parameter type: {param_name} ({old_param.type} -> {new_param.type})",
                        breaking_change=True,
                        migration_required=True,
                        affected_parameters=[param_name]
                    ))
                
                if old_param.default != new_param.default:
                    changes.append(VersionChange(
                        change_type=VersionChangeType.PATCH,
                        description=f"Changed default value: {param_name} ({old_param.default} -> {new_param.default})",
                        breaking_change=False,
                        migration_required=False,
                        affected_parameters=[param_name]
                    ))
        
        return changes


# Global instance
template_version_manager = TemplateVersionManager()