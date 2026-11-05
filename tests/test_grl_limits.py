"""Detailed quota and boundary stress tests for GRL."""

import unittest
from genesis.core.arithmetic import FixedPoint
from genesis.core.config import RuntimeConfig
from genesis.core.errors import GRLStructuralValidationError, QuotaExceededError
from genesis.grl.ast import (
    AdjustPropertyNode,
    ForEachNode,
    LiteralNode,
    ProduceResourceNode,
    RuleDefinition,
    TargetSelector,
    UnaryOpNode,
)
from genesis.grl.interpreter import GRLInterpreter
from genesis.grl.validator import GRLValidator
from genesis.substrate.properties import EntityTypeSchema, PropertyDefinition, PropertyType
from genesis.substrate.world_state import WorldState


class TestGRLLimits(unittest.TestCase):

    def test_operations_budget_exact_256_pass_and_257_fail(self):
        """Exact boundary test: 256 operations passes, 257 operations fails.

        Accounting mechanics:
        - TargetSelector is None -> 0 selector candidate check ops.
        - Preconditions is empty -> 0 precondition ops.
        - ProduceResourceNode(LiteralNode) evaluates:
            1 op (ProduceResourceNode) + 1 op (LiteralNode) = 2 ops.
        - ProduceResourceNode(UnaryOpNode(LiteralNode)) evaluates:
            1 op (ProduceResourceNode) + 1 op (UnaryOpNode) + 1 op (LiteralNode) = 3 ops.

        Constructing exact 256 ops:
            128 * ProduceResourceNode(LiteralNode) = 128 * 2 = 256 ops.

        Constructing exact 257 ops:
            127 * ProduceResourceNode(LiteralNode) = 127 * 2 = 254 ops.
            1 * ProduceResourceNode(UnaryOpNode(LiteralNode)) = 3 ops.
            Total = 254 + 3 = 257 ops.
        """
        config = RuntimeConfig(max_operations_per_rule=256)
        interpreter = GRLInterpreter(config)

        world = WorldState(seed=1, config=config)
        world.resources.create_pool("biomass", initial_balance=FixedPoint.from_int(1000))

        # 1. Exactly 256 operations
        effects_256 = [
            ProduceResourceNode("biomass", LiteralNode("INT64", 1)) for _ in range(128)
        ]
        rule_256 = RuleDefinition(
            rule_id="r_exact_256",
            name="Exact 256 ops",
            version="1.0",
            effects=effects_256,
        )
        success_256, msg_256 = interpreter.execute_rule(rule_256, world)
        self.assertTrue(success_256, f"Expected 256 ops to pass, got: {msg_256}")

        # 2. Exactly 257 operations
        effects_257 = [
            ProduceResourceNode("biomass", LiteralNode("INT64", 1)) for _ in range(127)
        ] + [
            ProduceResourceNode("biomass", UnaryOpNode("NEG", LiteralNode("INT64", 1)))
        ]
        rule_257 = RuleDefinition(
            rule_id="r_exact_257",
            name="Exact 257 ops",
            version="1.0",
            effects=effects_257,
        )
        success_257, msg_257 = interpreter.execute_rule(rule_257, world)
        self.assertFalse(success_257)
        self.assertIn("QuotaExceededError", msg_257)
        self.assertIn("exceeded max_operations_per_rule: 256", msg_257)

    def test_operations_budget_candidate_step(self):
        """Test candidate iteration stepping where each candidate consumes 3 ops:
        1 op (target selector candidate inspection) + 1 op (AdjustPropertyNode) + 1 op (LiteralNode).
        85 candidates * 3 ops = 255 ops <= 256 -> Success.
        86 candidates * 3 ops = 258 ops > 256 -> QuotaExceededError.
        """
        config = RuntimeConfig(max_operations_per_rule=256)
        interpreter = GRLInterpreter(config)

        world = WorldState(seed=1, config=config)
        schema = EntityTypeSchema("token")
        schema.add_property(PropertyDefinition("val", PropertyType.INT64, default_value=0))
        world.schema_registry.register_type(schema)

        for _ in range(100):
            world.entities.create_entity("token", 0, {"val": 0}, world.schema_registry)

        rule = RuleDefinition(
            rule_id="r_255",
            name="255 ops candidate step",
            version="1.0",
            target_selector=TargetSelector("token", limit=85),
            effects=[
                AdjustPropertyNode("target", "val", LiteralNode("INT64", 1))
            ]
        )
        success, msg = interpreter.execute_rule(rule, world)
        self.assertTrue(success, f"Expected success at 255 ops, got: {msg}")

        rule_over = RuleDefinition(
            rule_id="r_258",
            name="258 ops candidate step",
            version="1.0",
            target_selector=TargetSelector("token", limit=86),
            effects=[
                AdjustPropertyNode("target", "val", LiteralNode("INT64", 1))
            ]
        )
        success_over, msg_over = interpreter.execute_rule(rule_over, world)
        self.assertFalse(success_over)
        self.assertIn("QuotaExceededError", msg_over)

    def test_entities_touched_exact_boundary(self):
        """Quota: 1000 entities touched."""
        config = RuntimeConfig(max_operations_per_rule=100000, max_entities_touched_per_tick=1000)
        interpreter = GRLInterpreter(config)

        world = WorldState(seed=2, config=config)
        schema = EntityTypeSchema("dot")
        schema.add_property(PropertyDefinition("active", PropertyType.BOOLEAN, default_value=True))
        world.schema_registry.register_type(schema)

        for _ in range(1001):
            world.entities.create_entity("dot", 0, {"active": True}, world.schema_registry)

        rule_1000 = RuleDefinition(
            rule_id="r_1000",
            name="touch 1000",
            version="1.0",
            target_selector=TargetSelector("dot", limit=1000),
            effects=[]
        )
        success, msg = interpreter.execute_rule(rule_1000, world)
        self.assertTrue(success, f"1000 touches should succeed, got: {msg}")

        rule_1001 = RuleDefinition(
            rule_id="r_1001",
            name="touch 1001",
            version="1.0",
            target_selector=TargetSelector("dot", limit=1001),
            effects=[]
        )
        success_over, msg_over = interpreter.execute_rule(rule_1001, world)
        self.assertFalse(success_over)
        self.assertIn("max_entities_touched_per_tick", msg_over)


if __name__ == "__main__":
    unittest.main()
