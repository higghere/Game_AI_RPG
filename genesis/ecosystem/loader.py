"""GENESIS Ecosystem Loader.

Loads declarative JSON entity schemas, resource pools, and bootstrap GRL rules
into the runtime substrate without any organism-specific Python classes.
"""

from __future__ import annotations
import glob
import json
from pathlib import Path
from typing import Any, Dict, Optional

from genesis.core.arithmetic import FixedPoint
from genesis.grl.parser import GRLParser
from genesis.grl.registry import RuleRegistry
from genesis.substrate.properties import EntityTypeSchema, PropertyDefinition, PropertyType, SchemaRegistry
from genesis.substrate.resources import ResourceRegistry
from genesis.substrate.world_state import WorldState

DATA_DIR = Path(__file__).resolve().parent / "data"


def load_ecosystem_schemas(registry: SchemaRegistry) -> None:
    """Load and register organism entity schemas from JSON declarations."""
    schemas_dir = DATA_DIR / "schemas"
    schema_files = sorted(schemas_dir.glob("*.json"))
    for file_path in schema_files:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        type_name = data["entity_type"]
        schema = EntityTypeSchema(type_name)
        props_data = data.get("properties", {})
        for p_name in sorted(props_data.keys()):
            p_info = props_data[p_name]
            p_type = PropertyType(p_info["type"])
            min_v = p_info.get("min")
            max_v = p_info.get("max")
            def_v = p_info.get("default")

            if p_type == PropertyType.FIXED_POINT:
                min_v = FixedPoint.from_decimal_string(str(min_v)) if min_v is not None else None
                max_v = FixedPoint.from_decimal_string(str(max_v)) if max_v is not None else None
                def_v = FixedPoint.from_decimal_string(str(def_v)) if def_v is not None else None
            elif p_type == PropertyType.INT64:
                min_v = int(min_v) if min_v is not None else None
                max_v = int(max_v) if max_v is not None else None
                def_v = int(def_v) if def_v is not None else None

            prop_def = PropertyDefinition(
                name=p_name,
                prop_type=p_type,
                default_value=def_v,
                min_value=min_v,
                max_value=max_v,
            )
            schema.add_property(prop_def)
        registry.register_type(schema)


def load_ecosystem_resources(registry: ResourceRegistry) -> None:
    """Load and configure environmental resource reservoirs from JSON."""
    resources_file = DATA_DIR / "resources.json"
    with open(resources_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    for pool_name in sorted(data.keys()):
        pool_info = data[pool_name]
        init_bal = FixedPoint.from_decimal_string(str(pool_info["initial_balance"]))
        min_cap = FixedPoint.from_decimal_string(str(pool_info["min_capacity"]))
        max_cap = FixedPoint.from_decimal_string(str(pool_info["max_capacity"]))
        if registry.has_pool(pool_name):
            pool = registry.get_pool(pool_name)
            if pool:
                pool.set_balance(init_bal)
        else:
            registry.create_pool(
                name=pool_name,
                initial_balance=init_bal,
                min_capacity=min_cap,
                max_capacity=max_cap,
            )


def load_ecosystem_rules(rule_registry: RuleRegistry, world: WorldState) -> None:
    """Parse and prospectively register human bootstrap rules."""
    rules_dir = DATA_DIR / "rules"
    rule_files = sorted(rules_dir.glob("*.json"))
    parser = GRLParser()
    for file_path in rule_files:
        with open(file_path, "r", encoding="utf-8") as f:
            rule_dict = json.load(f)
        rule = parser.parse_rule(rule_dict)
        rule_registry.register_rule(rule, world=world)


def load_ecosystem(world: WorldState) -> None:
    """Initialize world with full ecosystem ontology: schemas, resources, and bootstrap rules."""
    load_ecosystem_schemas(world.schema_registry)
    load_ecosystem_resources(world.resources)
    if world.rule_registry is None:
        world.rule_registry = RuleRegistry(world.config)
    load_ecosystem_rules(world.rule_registry, world)
