"""GENESIS Dynamic Property Substrate.

Provides runtime schema registration, type checking, bounds validation,
and decimal string serialization for dynamic entity properties.
"""

from __future__ import annotations
from enum import Enum
from typing import Any, Dict, List, Optional, Union

from genesis.core.arithmetic import FixedPoint, check_int64
from genesis.core.errors import PropertySchemaValidationError, PropertyValueOutOfBoundsError


class PropertyType(str, Enum):
    """Supported property data types."""
    INT64 = "INT64"
    FIXED_POINT = "FIXED_POINT"
    BOOLEAN = "BOOLEAN"
    STRING = "STRING"
    ENUM = "ENUM"


class PropertyDefinition:
    """Definition and constraints for a single dynamic property."""

    __slots__ = (
        "name",
        "prop_type",
        "default_value",
        "min_value",
        "max_value",
        "allowed_variants",
        "read_only",
    )

    def __init__(
        self,
        name: str,
        prop_type: Union[PropertyType, str],
        default_value: Any = None,
        min_value: Optional[Union[int, FixedPoint]] = None,
        max_value: Optional[Union[int, FixedPoint]] = None,
        allowed_variants: Optional[List[str]] = None,
        read_only: bool = False,
    ) -> None:
        self.name = name
        self.prop_type = PropertyType(prop_type) if isinstance(prop_type, str) else prop_type
        self.default_value = default_value
        self.min_value = min_value
        self.max_value = max_value
        self.allowed_variants = allowed_variants
        self.read_only = read_only

    def validate_and_coerce(self, value: Any) -> Any:
        """Validate input value against schema constraints and return coerced value."""
        if self.prop_type == PropertyType.INT64:
            if isinstance(value, str):
                try:
                    val_int = int(value)
                except ValueError:
                    raise PropertySchemaValidationError(
                        f"Property '{self.name}' expected INT64 decimal string, got '{value}'"
                    )
            elif isinstance(value, int) and not isinstance(value, bool):
                val_int = value
            else:
                raise PropertySchemaValidationError(
                    f"Property '{self.name}' expected INT64, got {type(value).__name__}"
                )
            check_int64(val_int)
            if self.min_value is not None and val_int < int(self.min_value):
                raise PropertyValueOutOfBoundsError(
                    f"Property '{self.name}' value {val_int} < min {self.min_value}"
                )
            if self.max_value is not None and val_int > int(self.max_value):
                raise PropertyValueOutOfBoundsError(
                    f"Property '{self.name}' value {val_int} > max {self.max_value}"
                )
            return val_int

        elif self.prop_type == PropertyType.FIXED_POINT:
            if isinstance(value, FixedPoint):
                val_fp = value
            elif isinstance(value, str):
                try:
                    if "." in value:
                        val_fp = FixedPoint.from_decimal_string(value)
                    else:
                        val_fp = FixedPoint.from_raw(int(value))
                except Exception as e:
                    raise PropertySchemaValidationError(
                        f"Property '{self.name}' cannot parse FIXED_POINT from '{value}': {e}"
                    )
            elif isinstance(value, int) and not isinstance(value, bool):
                val_fp = FixedPoint.from_int(value)
            else:
                raise PropertySchemaValidationError(
                    f"Property '{self.name}' expected FIXED_POINT, got {type(value).__name__}"
                )
            if self.min_value is not None:
                min_fp = self.min_value if isinstance(self.min_value, FixedPoint) else FixedPoint.from_int(int(self.min_value))
                if val_fp < min_fp:
                    raise PropertyValueOutOfBoundsError(
                        f"Property '{self.name}' value {val_fp} < min {min_fp}"
                    )
            if self.max_value is not None:
                max_fp = self.max_value if isinstance(self.max_value, FixedPoint) else FixedPoint.from_int(int(self.max_value))
                if val_fp > max_fp:
                    raise PropertyValueOutOfBoundsError(
                        f"Property '{self.name}' value {val_fp} > max {max_fp}"
                    )
            return val_fp

        elif self.prop_type == PropertyType.BOOLEAN:
            if isinstance(value, bool):
                return value
            if isinstance(value, str):
                if value.lower() == "true":
                    return True
                if value.lower() == "false":
                    return False
            raise PropertySchemaValidationError(
                f"Property '{self.name}' expected BOOLEAN, got {type(value).__name__}"
            )

        elif self.prop_type == PropertyType.STRING:
            if not isinstance(value, str):
                raise PropertySchemaValidationError(
                    f"Property '{self.name}' expected STRING, got {type(value).__name__}"
                )
            if len(value.encode("utf-8")) > 256:
                raise PropertySchemaValidationError(
                    f"Property '{self.name}' STRING exceeds 256 bytes limit"
                )
            # Security sanitization: block path delimiters and control characters
            if any(c in value for c in ("/", "\\", "..", "\x00")):
                raise PropertySchemaValidationError(
                    f"Property '{self.name}' contains forbidden path traversal characters"
                )
            return value

        elif self.prop_type == PropertyType.ENUM:
            if not isinstance(value, str):
                raise PropertySchemaValidationError(
                    f"Property '{self.name}' expected ENUM string, got {type(value).__name__}"
                )
            if self.allowed_variants and value not in self.allowed_variants:
                raise PropertySchemaValidationError(
                    f"Property '{self.name}' value '{value}' not in variants {self.allowed_variants}"
                )
            return value

        raise PropertySchemaValidationError(f"Unknown property type {self.prop_type}")

    def to_dict(self) -> Dict[str, Any]:
        """Serialize property definition."""
        d: Dict[str, Any] = {
            "name": self.name,
            "prop_type": self.prop_type.value,
            "read_only": self.read_only,
        }
        if self.default_value is not None:
            if isinstance(self.default_value, FixedPoint):
                d["default_value"] = self.default_value.to_raw_string()
            elif isinstance(self.default_value, int):
                d["default_value"] = str(self.default_value)
            else:
                d["default_value"] = self.default_value
        if self.min_value is not None:
            d["min_value"] = self.min_value.to_raw_string() if isinstance(self.min_value, FixedPoint) else str(self.min_value)
        if self.max_value is not None:
            d["max_value"] = self.max_value.to_raw_string() if isinstance(self.max_value, FixedPoint) else str(self.max_value)
        if self.allowed_variants is not None:
            d["allowed_variants"] = list(self.allowed_variants)
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> PropertyDefinition:
        prop_type = PropertyType(data["prop_type"])
        default_val = data.get("default_value")
        if default_val is not None:
            if prop_type == PropertyType.FIXED_POINT:
                default_val = FixedPoint.from_raw(int(default_val))
            elif prop_type == PropertyType.INT64:
                default_val = int(default_val)
        min_v = data.get("min_value")
        if min_v is not None:
            min_v = FixedPoint.from_raw(int(min_v)) if prop_type == PropertyType.FIXED_POINT else int(min_v)
        max_v = data.get("max_value")
        if max_v is not None:
            max_v = FixedPoint.from_raw(int(max_v)) if prop_type == PropertyType.FIXED_POINT else int(max_v)
        return cls(
            name=data["name"],
            prop_type=prop_type,
            default_value=default_val,
            min_value=min_v,
            max_value=max_v,
            allowed_variants=data.get("allowed_variants"),
            read_only=data.get("read_only", False),
        )


class EntityTypeSchema:
    """Schema governing an entity type and its allowable properties."""

    def __init__(self, type_name: str, properties: Optional[Dict[str, PropertyDefinition]] = None) -> None:
        self.type_name = type_name
        self.properties: Dict[str, PropertyDefinition] = properties or {}

    def add_property(self, prop_def: PropertyDefinition) -> None:
        self.properties[prop_def.name] = prop_def

    def validate_property(self, prop_name: str, value: Any) -> Any:
        if prop_name not in self.properties:
            raise PropertySchemaValidationError(
                f"Unknown property '{prop_name}' on entity type '{self.type_name}'"
            )
        return self.properties[prop_name].validate_and_coerce(value)

    def to_dict(self) -> Dict[str, Any]:
        sorted_props = {k: self.properties[k].to_dict() for k in sorted(self.properties.keys())}
        return {
            "type_name": self.type_name,
            "properties": sorted_props,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> EntityTypeSchema:
        schema = cls(type_name=data["type_name"])
        for p_name, p_data in data.get("properties", {}).items():
            schema.add_property(PropertyDefinition.from_dict(p_data))
        return schema


class SchemaRegistry:
    """Registry of entity type schemas."""

    def __init__(self) -> None:
        self._schemas: Dict[str, EntityTypeSchema] = {}

    def register_type(self, schema: EntityTypeSchema) -> None:
        self._schemas[schema.type_name] = schema

    def get_schema(self, type_name: str) -> Optional[EntityTypeSchema]:
        return self._schemas.get(type_name)

    def has_type(self, type_name: str) -> bool:
        return type_name in self._schemas

    def all_schemas(self) -> List[EntityTypeSchema]:
        return [self._schemas[k] for k in sorted(self._schemas.keys())]

    def to_dict(self) -> Dict[str, Any]:
        return {k: self._schemas[k].to_dict() for k in sorted(self._schemas.keys())}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> SchemaRegistry:
        reg = cls()
        for t_name, s_data in data.items():
            reg.register_type(EntityTypeSchema.from_dict(s_data))
        return reg
