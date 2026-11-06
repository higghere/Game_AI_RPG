"""Detailed quota and boundary stress tests for GRL."""

import unittest
from genesis.core.arithmetic import FixedPoint
from genesis.core.config import RuntimeConfig
from genesis.core.errors import GRLStructuralValidationError, QuotaExceededError
from genesis.grl.ast import (
    AdjustPropertyNode,
    BinaryOpNode,
    ForEachNode,
    GetPropertyNode,
    GetResourceNode,
    LiteralNode,
    ProduceResourceNode,
    RuleDefinition,
    TargetSelector,
    UnaryOpNode,
)
from genesis.grl.interpreter import GRLInterpreter
from genesis.grl.registry import RuleRegistry
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

    def test_catch_only_genesis_errors_and_report_internal_error(self):
        """Verify execute_rule catches GenesisError gracefully but re-raises unexpected exceptions as InternalRuntimeError."""
        from genesis.core.errors import InternalRuntimeError
        from genesis.grl.ast import GRLNode

        config = RuntimeConfig()
        interpreter = GRLInterpreter(config)
        world = WorldState(seed=3, config=config)

        class UnexpectedHostFailureNode(GRLNode):
            pass

        original_eval_effect = interpreter.eval_effect

        def broken_eval_effect(node, ctx, w):
            if isinstance(node, UnexpectedHostFailureNode):
                raise TypeError("Simulated unexpected host error")
            return original_eval_effect(node, ctx, w)

        interpreter.eval_effect = broken_eval_effect

        rule = RuleDefinition(
            rule_id="r_unexpected",
            name="Unexpected Bug Rule",
            version="1.0",
            effects=[UnexpectedHostFailureNode()]
        )

        with self.assertRaises(InternalRuntimeError) as ctx:
            interpreter.execute_rule(rule, world)

        self.assertIn("Internal runtime engine error", str(ctx.exception))
        # Verify an internal_runtime_error event was recorded
        last_event = world.event_journal.records[-1]
        self.assertEqual(last_event.event_type, "internal_runtime_error")

    def test_global_preconditions_gate_multi_target_without_touching_entities(self):
        """Verify global preconditions evaluate before target selection, touching 0 entities if false."""
        config = RuntimeConfig()
        interpreter = GRLInterpreter(config)
        world = WorldState(seed=4, config=config)
        world.resources.create_pool("sunlight", initial_balance=FixedPoint.from_int(0))

        schema = EntityTypeSchema("tree")
        schema.add_property(PropertyDefinition("sap", PropertyType.INT64, default_value=10))
        world.schema_registry.register_type(schema)

        for _ in range(50):
            world.entities.create_entity("tree", 0, {"sap": 10}, world.schema_registry)

        rule = RuleDefinition(
            rule_id="r_photosynthesis_gate",
            name="Photosynthesis Gate",
            version="1.0",
            target_selector=TargetSelector("tree", limit=50),
            preconditions=[
                # Global condition: sunlight must be >= 10.0 (currently 0)
                BinaryOpNode("GREATER_THAN_OR_EQUAL", GetResourceNode("sunlight"), LiteralNode("FIXED_POINT", FixedPoint.from_int(10)))
            ],
            effects=[
                AdjustPropertyNode("target", "sap", LiteralNode("INT64", 5))
            ]
        )

        success, msg = interpreter.execute_rule(rule, world)
        self.assertTrue(success)
        self.assertEqual(msg, "Preconditions not satisfied")

        # Verify no tree was mutated
        for t in world.entities.get_entities_by_type("tree"):
            self.assertEqual(t.get_property("sap"), 10)

    def test_full_canonical_rule_body_hashing_and_installation_event(self):
        """Verify full AST body hashing (any effect change alters hash) and rule_installed event."""
        world = WorldState(seed=5)
        world.resources.create_pool("biomass", initial_balance=FixedPoint.from_int(100))

        rule_A = RuleDefinition(
            rule_id="r_growth",
            name="Growth Rule",
            version="1.0.0",
            priority=10,
            effects=[ProduceResourceNode("biomass", LiteralNode("INT64", 10))]
        )
        rule_B = RuleDefinition(
            rule_id="r_growth",
            name="Growth Rule",
            version="1.0.0",
            priority=10,
            effects=[ProduceResourceNode("biomass", LiteralNode("INT64", 20))] # Different effect!
        )

        reg = RuleRegistry()
        hash_A = reg.register_rule(rule_A, world=world)
        reg_B = RuleRegistry()
        world_B = WorldState(seed=2)
        hash_B = reg_B.register_rule(rule_B, world=world_B)

        # Full body hash must detect the difference in effects
        self.assertNotEqual(hash_A, hash_B, "Changing rule effect body must produce different hash")

        # Calling register_rule without world must raise TypeError
        with self.assertRaises(TypeError):
            reg.register_rule(rule_A)  # missing required argument 'world'

        # Verify rule_installed event was appended to journal
        install_events = [e for e in world.event_journal.records if e.event_type == "rule_installed"]
        self.assertEqual(len(install_events), 1)
        self.assertEqual(install_events[0].payload["rule_id"], "r_growth")
        self.assertEqual(install_events[0].payload["rule_hash"], hash_A)
        self.assertEqual(install_events[0].payload["active_from_tick"], "1")

    def test_entity_touch_limit_aggregate_across_multiple_rules_in_tick(self):
        """Verify the 1000 entity touch limit is aggregated across all rules in a tick."""
        config = RuntimeConfig(max_operations_per_rule=100000, max_entities_touched_per_tick=1000)
        interpreter = GRLInterpreter(config)
        world = WorldState(seed=6, config=config)

        schema = EntityTypeSchema("node")
        schema.add_property(PropertyDefinition("val", PropertyType.INT64, default_value=0))
        world.schema_registry.register_type(schema)

        # Create 1100 distinct entities
        for _ in range(1100):
            world.entities.create_entity("node", 0, {"val": 0}, world.schema_registry)

        # Rule 1 touches entities 1 to 600
        rule_1 = RuleDefinition(
            rule_id="r1_touch_600",
            name="Touch 600",
            version="1.0",
            target_selector=TargetSelector("node", limit=600),
            effects=[]
        )
        ok1, msg1 = interpreter.execute_rule(rule_1, world)
        self.assertTrue(ok1, f"Rule 1 should succeed touching 600: {msg1}")
        self.assertEqual(len(world.entities_touched_this_tick), 600)

        # Rule 2 targets all nodes but with a non-matching filter over remaining nodes
        # If it touches 401 additional entities (600 + 401 = 1001 > 1000), it must fail!
        # Create a second entity type "node_b" for 500 distinct entities
        schema_b = EntityTypeSchema("node_b")
        schema_b.add_property(PropertyDefinition("tag", PropertyType.INT64, default_value=0))
        world.schema_registry.register_type(schema_b)
        for _ in range(500):
            world.entities.create_entity("node_b", 0, {"tag": 0}, world.schema_registry)

        rule_2 = RuleDefinition(
            rule_id="r2_touch_b",
            name="Touch B",
            version="1.0",
            target_selector=TargetSelector("node_b", limit=401),
            effects=[]
        )
        ok2, msg2 = interpreter.execute_rule(rule_2, world)
        self.assertFalse(ok2, "Rule 2 must fail when tick aggregate touches exceed 1000")
        self.assertIn("max_entities_touched_per_tick", msg2)

        # Advance tick: aggregate touch counter resets to 0
        world.advance_tick()
        self.assertEqual(len(world.entities_touched_this_tick), 0)

        # Rule 2 now runs in the new tick and succeeds
        ok2_new, msg2_new = interpreter.execute_rule(rule_2, world)
        self.assertTrue(ok2_new, "Rule 2 must succeed in new tick with fresh 1000 budget")
        self.assertEqual(len(world.entities_touched_this_tick), 401)


if __name__ == "__main__":
    unittest.main()
