"""GENESIS Phase 3 Agent Loader.

Loads declarative JSON agent entity schemas and GRL rules into the runtime
substrate without any agent-specific Python classes.
"""

from __future__ import annotations
import json
from pathlib import Path

from genesis.core.arithmetic import FixedPoint
from genesis.grl.parser import GRLParser
from genesis.grl.registry import RuleRegistry
from genesis.substrate.properties import EntityTypeSchema, PropertyDefinition, PropertyType, SchemaRegistry
from genesis.substrate.world_state import WorldState

DATA_DIR = Path(__file__).resolve().parent / "data"


def load_agent_schemas(registry: SchemaRegistry) -> None:
    """Load and register the agent entity schema from JSON declaration."""
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


def load_agent_rules(
    rule_registry: RuleRegistry,
    world: WorldState,
    mutation_rate_per_thousand: int = 10,
) -> None:
    """Parse and register agent behavior GRL rules."""
    rules_dir = DATA_DIR / "rules"
    rule_files = sorted(rules_dir.glob("*.json"))
    parser = GRLParser()
    for file_path in rule_files:
        with open(file_path, "r", encoding="utf-8") as f:
            rule_dict = json.load(f)
        if rule_dict.get("rule_id") == "AR_05_REPRODUCE" and mutation_rate_per_thousand != 10:
            rule_str = json.dumps(rule_dict)
            rule_str = rule_str.replace('"value": "10"', f'"value": "{mutation_rate_per_thousand}"')
            rule_dict = json.loads(rule_str)
        rule = parser.parse_rule(rule_dict)
        rule_registry.register_rule(rule, world=world)


def load_agents(world: WorldState, mutation_rate_per_thousand: int = 10) -> None:
    """Initialize world with full agent definitions: schema and behavior rules."""
    load_agent_schemas(world.schema_registry)
    if world.rule_registry is None:
        world.rule_registry = RuleRegistry(world.config)
    load_agent_rules(world.rule_registry, world, mutation_rate_per_thousand=mutation_rate_per_thousand)
