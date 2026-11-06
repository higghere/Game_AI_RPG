"""GENESIS Rule Language Sandboxed Interpreter.

Evaluates declarative GRL rules against simulation state with strict
operation metering (<= 256 ops), entity touch tracking (<= 1000 entities),
and atomic single-rule rollback on failure or quota overflow.
"""

from __future__ import annotations
from typing import Any, Dict, List, Optional, Set, Tuple

from genesis.core.arithmetic import FixedPoint
from genesis.core.config import DEFAULT_CONFIG, RuntimeConfig
from genesis.core.errors import GRLExecutionError, QuotaExceededError
from genesis.grl.ast import (
    AddRelationshipNode,
    AdjustPropertyNode,
    BinaryOpNode,
    ConsumeResourceNode,
    ForEachNode,
    GetPropertyNode,
    GetResourceNode,
    GRLNode,
    HasRelationshipNode,
    IfNode,
    LiteralNode,
    ProduceResourceNode,
    RemoveRelationshipNode,
    RuleDefinition,
    ScheduleEventNode,
    SetPropertyNode,
    TransferResourceNode,
    UnaryOpNode,
)
from genesis.substrate.entities import Entity
from genesis.substrate.events import EventRecord, PHASE_GRL_RULES, PHASE_PERCEPTION_EVENTS
from genesis.substrate.relationships import RelationshipEdge
from genesis.substrate.world_state import WorldState


class ExecutionContext:
    """Isolated execution context tracking operational gas, entity touches, and staged mutations."""

    __slots__ = (
        "rule_id",
        "operations_count",
        "max_operations",
        "touched_entities",
        "max_touched_entities",
        "variables",
        "staged_properties",
        "staged_resources",
        "staged_added_edges",
        "staged_removed_edges",
        "staged_events",
    )

    def __init__(self, rule_id: str, config: RuntimeConfig = DEFAULT_CONFIG) -> None:
        self.rule_id = rule_id
        self.operations_count = 0
        self.max_operations = config.max_operations_per_rule
        self.touched_entities: Set[int] = set()
        self.max_touched_entities = config.max_entities_touched_per_tick
        self.variables: Dict[str, Any] = {}

        # Transactional staging buffers (single-rule rollback)
        self.staged_properties: Dict[Tuple[int, str], Any] = {}
        self.staged_resources: Dict[str, FixedPoint] = {}
        self.staged_added_edges: List[RelationshipEdge] = []
        self.staged_removed_edges: List[Tuple[int, int, str]] = []
        self.staged_events: List[EventRecord] = []

    def consume_op(self) -> None:
        """Consume 1 operation budget credit."""
        self.operations_count += 1
        if self.operations_count > self.max_operations:
            raise QuotaExceededError(
                f"Rule '{self.rule_id}' exceeded max_operations_per_rule: {self.max_operations}"
            )

    def touch_entity(self, entity_id: int) -> None:
        """Record an entity touched by read or write."""
        self.touched_entities.add(entity_id)
        if len(self.touched_entities) > self.max_touched_entities:
            raise QuotaExceededError(
                f"Rule '{self.rule_id}' exceeded max_entities_touched_per_tick: {self.max_touched_entities}"
            )


class GRLInterpreter:
    """Sandboxed, deterministic evaluator for GRL rules."""

    def __init__(self, config: RuntimeConfig = DEFAULT_CONFIG) -> None:
        self.config = config

    def execute_rule(self, rule: RuleDefinition, world: WorldState) -> Tuple[bool, str]:
        """Execute a rule against world state with single-rule rollback on error."""
        ctx = ExecutionContext(rule.rule_id, self.config)

        try:
            # 1. Target Selector
            candidate_entities: List[Entity] = []
            if rule.target_selector:
                sel = rule.target_selector
                all_of_type = world.entities.get_entities_by_type(sel.entity_type)
                for ent in all_of_type:
                    # Reading an entity during selection counts as a touch
                    ctx.touch_entity(ent.id)
                    ctx.consume_op()

                    if sel.filter_expr:
                        ctx.variables["target"] = ent
                        is_match = self.eval_expression(sel.filter_expr, ctx, world)
                        if is_match:
                            candidate_entities.append(ent)
                    else:
                        candidate_entities.append(ent)

                    if len(candidate_entities) >= sel.limit:
                        break
            else:
                # Rule applies to world globally without target entity
                candidate_entities = [None]

            # 2. Preconditions (evaluated once globally or per candidate)
            # Evaluate global preconditions
            for pre in rule.preconditions:
                ctx.consume_op()
                ctx.variables.setdefault("target", candidate_entities[0] if candidate_entities else None)
                if not self.eval_expression(pre, ctx, world):
                    # Precondition failed; clean exit with no mutations applied
                    return True, "Preconditions not satisfied"

            # 3. Apply Effects for each target candidate
            for target_ent in candidate_entities:
                if target_ent is not None:
                    ctx.variables["target"] = target_ent

                for effect in rule.effects:
                    self.eval_effect(effect, ctx, world)

            # 4. Commit staged transactions atomically
            self._commit_transactions(ctx, world)

            # Record success event in journal
            success_event = EventRecord(
                tick=world.clock.current_tick,
                phase=PHASE_GRL_RULES,
                priority=rule.priority,
                sequence_id=world.next_sequence_id(),
                event_type="rule_executed_success",
                payload={
                    "rule_id": rule.rule_id,
                    "operations_consumed": str(ctx.operations_count),
                    "entities_touched": str(len(ctx.touched_entities)),
                },
            )
            world.event_journal.append(success_event)
            return True, "Executed successfully"

        except Exception as exc:
            # Single-rule rollback: discard staging buffers entirely
            failure_event = EventRecord(
                tick=world.clock.current_tick,
                phase=PHASE_GRL_RULES,
                priority=rule.priority,
                sequence_id=world.next_sequence_id(),
                event_type="rule_execution_failed",
                payload={
                    "rule_id": rule.rule_id,
                    "error_type": type(exc).__name__,
                    "error_message": str(exc),
                    "operations_consumed": str(ctx.operations_count),
                    "entities_touched": str(len(ctx.touched_entities)),
                },
            )
            world.event_journal.append(failure_event)
            return False, f"{type(exc).__name__}: {str(exc)}"

    def eval_expression(self, node: GRLNode, ctx: ExecutionContext, world: WorldState) -> Any:
        """Evaluate an expression node."""
        ctx.consume_op()

        if isinstance(node, LiteralNode):
            return node.value

        elif isinstance(node, GetPropertyNode):
            ent = ctx.variables.get(node.entity_var)
            if not isinstance(ent, Entity):
                raise GRLExecutionError(f"Variable '{node.entity_var}' is not an Entity")
            ctx.touch_entity(ent.id)

            # Check staged properties first
            staged_key = (ent.id, node.property_name)
            if staged_key in ctx.staged_properties:
                return ctx.staged_properties[staged_key]
            return ent.get_property(node.property_name)

        elif isinstance(node, GetResourceNode):
            pool = world.resources.get_pool(node.pool_name)
            if not pool:
                raise GRLExecutionError(f"Resource pool '{node.pool_name}' does not exist")
            staged_delta = ctx.staged_resources.get(node.pool_name, FixedPoint.from_int(0))
            return pool.balance + staged_delta

        elif isinstance(node, HasRelationshipNode):
            src = ctx.variables.get(node.source_var)
            tgt = ctx.variables.get(node.target_var)
            src_id = src.id if isinstance(src, Entity) else int(src)
            tgt_id = tgt.id if isinstance(tgt, Entity) else int(tgt)
            ctx.touch_entity(src_id)
            ctx.touch_entity(tgt_id)
            return world.relationships.has_edge(src_id, tgt_id, node.rel_type)

        elif isinstance(node, BinaryOpNode):
            left_val = self.eval_expression(node.left, ctx, world)
            right_val = self.eval_expression(node.right, ctx, world)

            if node.op == "ADD":
                return left_val + right_val
            elif node.op == "SUBTRACT":
                return left_val - right_val
            elif node.op == "MULTIPLY":
                return left_val * right_val
            elif node.op == "DIVIDE":
                return left_val / right_val
            elif node.op == "MODULO":
                return left_val % right_val
            elif node.op == "EQUALS":
                return left_val == right_val
            elif node.op == "NOT_EQUALS":
                return left_val != right_val
            elif node.op == "LESS_THAN":
                return left_val < right_val
            elif node.op == "LESS_THAN_OR_EQUAL":
                return left_val <= right_val
            elif node.op == "GREATER_THAN":
                return left_val > right_val
            elif node.op == "GREATER_THAN_OR_EQUAL":
                return left_val >= right_val
            elif node.op == "AND":
                return bool(left_val) and bool(right_val)
            elif node.op == "OR":
                return bool(left_val) or bool(right_val)
            raise GRLExecutionError(f"Unsupported binary operator: {node.op}")

        elif isinstance(node, UnaryOpNode):
            operand_val = self.eval_expression(node.operand, ctx, world)
            if node.op == "NOT":
                return not bool(operand_val)
            elif node.op == "NEG":
                return -operand_val
            raise GRLExecutionError(f"Unsupported unary operator: {node.op}")

        raise GRLExecutionError(f"Unknown expression node: {type(node).__name__}")

    def eval_effect(self, node: GRLNode, ctx: ExecutionContext, world: WorldState) -> None:
        """Evaluate an effect/action node, staging mutations in ctx."""
        ctx.consume_op()

        if isinstance(node, SetPropertyNode):
            ent = ctx.variables.get(node.entity_var)
            if not isinstance(ent, Entity):
                raise GRLExecutionError(f"Cannot set property on non-entity '{node.entity_var}'")
            ctx.touch_entity(ent.id)
            new_val = self.eval_expression(node.value_expr, ctx, world)
            # Schema validation
            schema = world.schema_registry.get_schema(ent.entity_type)
            if schema:
                new_val = schema.validate_property(node.property_name, new_val)
            ctx.staged_properties[(ent.id, node.property_name)] = new_val

        elif isinstance(node, AdjustPropertyNode):
            ent = ctx.variables.get(node.entity_var)
            if not isinstance(ent, Entity):
                raise GRLExecutionError(f"Cannot adjust property on non-entity '{node.entity_var}'")
            ctx.touch_entity(ent.id)
            delta = self.eval_expression(node.delta_expr, ctx, world)
            staged_key = (ent.id, node.property_name)
            current_val = ctx.staged_properties.get(staged_key, ent.get_property(node.property_name))
            if current_val is None:
                current_val = FixedPoint.from_int(0) if isinstance(delta, FixedPoint) else 0
            new_val = current_val + delta
            schema = world.schema_registry.get_schema(ent.entity_type)
            if schema:
                new_val = schema.validate_property(node.property_name, new_val)
            ctx.staged_properties[staged_key] = new_val

        elif isinstance(node, ConsumeResourceNode):
            amount = self.eval_expression(node.amount_expr, ctx, world)
            if not isinstance(amount, FixedPoint):
                amount = FixedPoint.from_int(int(amount))
            pool = world.resources.get_pool(node.pool_name)
            if not pool:
                raise GRLExecutionError(f"Resource pool '{node.pool_name}' does not exist")
            current_delta = ctx.staged_resources.get(node.pool_name, FixedPoint.from_int(0))
            new_delta = current_delta - amount
            # Validate underflow against staged balance
            if pool.balance + new_delta < pool.min_capacity:
                raise GRLExecutionError(f"Resource underflow on '{node.pool_name}'")
            ctx.staged_resources[node.pool_name] = new_delta

        elif isinstance(node, ProduceResourceNode):
            amount = self.eval_expression(node.amount_expr, ctx, world)
            if not isinstance(amount, FixedPoint):
                amount = FixedPoint.from_int(int(amount))
            pool = world.resources.get_pool(node.pool_name)
            if not pool:
                raise GRLExecutionError(f"Resource pool '{node.pool_name}' does not exist")
            current_delta = ctx.staged_resources.get(node.pool_name, FixedPoint.from_int(0))
            new_delta = current_delta + amount
            if pool.balance + new_delta > pool.max_capacity:
                raise GRLExecutionError(f"Resource overflow on '{node.pool_name}'")
            ctx.staged_resources[node.pool_name] = new_delta

        elif isinstance(node, TransferResourceNode):
            amount = self.eval_expression(node.amount_expr, ctx, world)
            if not isinstance(amount, FixedPoint):
                amount = FixedPoint.from_int(int(amount))
            from_pool = world.resources.get_pool(node.from_pool)
            to_pool = world.resources.get_pool(node.to_pool)
            if not from_pool or not to_pool:
                raise GRLExecutionError(f"Invalid pool transfer: '{node.from_pool}' -> '{node.to_pool}'")
            # Deduct from source
            f_delta = ctx.staged_resources.get(node.from_pool, FixedPoint.from_int(0)) - amount
            if from_pool.balance + f_delta < from_pool.min_capacity:
                raise GRLExecutionError(f"Transfer underflow on '{node.from_pool}'")
            ctx.staged_resources[node.from_pool] = f_delta
            # Add to target
            t_delta = ctx.staged_resources.get(node.to_pool, FixedPoint.from_int(0)) + amount
            if to_pool.balance + t_delta > to_pool.max_capacity:
                raise GRLExecutionError(f"Transfer overflow on '{node.to_pool}'")
            ctx.staged_resources[node.to_pool] = t_delta

        elif isinstance(node, AddRelationshipNode):
            src = ctx.variables.get(node.source_var)
            tgt = ctx.variables.get(node.target_var)
            src_id = src.id if isinstance(src, Entity) else int(src)
            tgt_id = tgt.id if isinstance(tgt, Entity) else int(tgt)
            ctx.touch_entity(src_id)
            ctx.touch_entity(tgt_id)
            weight = self.eval_expression(node.weight_expr, ctx, world) if node.weight_expr else FixedPoint.from_int(1)
            ctx.staged_added_edges.append(RelationshipEdge(src_id, tgt_id, node.rel_type, weight))

        elif isinstance(node, RemoveRelationshipNode):
            src = ctx.variables.get(node.source_var)
            tgt = ctx.variables.get(node.target_var)
            src_id = src.id if isinstance(src, Entity) else int(src)
            tgt_id = tgt.id if isinstance(tgt, Entity) else int(tgt)
            ctx.touch_entity(src_id)
            ctx.touch_entity(tgt_id)
            ctx.staged_removed_edges.append((src_id, tgt_id, node.rel_type))

        elif isinstance(node, ScheduleEventNode):
            target_tick = world.clock.current_tick + node.delay_ticks
            payload: Dict[str, Any] = {}
            if node.payload_expr:
                for k, vexpr in node.payload_expr.items():
                    payload[k] = self.eval_expression(vexpr, ctx, world)
            ev = EventRecord(
                tick=target_tick,
                phase=PHASE_PERCEPTION_EVENTS,
                priority=0,
                sequence_id=world.next_sequence_id(),
                event_type=node.event_type,
                payload=payload,
            )
            ctx.staged_events.append(ev)

        elif isinstance(node, IfNode):
            cond_res = self.eval_expression(node.condition, ctx, world)
            if cond_res:
                for child in node.then_effects:
                    self.eval_effect(child, ctx, world)
            else:
                for child in node.else_effects:
                    self.eval_effect(child, ctx, world)

        elif isinstance(node, ForEachNode):
            # Deterministic iteration over edges
            parent_ent = ctx.variables.get("target")
            if not isinstance(parent_ent, Entity):
                return
            edges = world.relationships.get_outgoing(parent_ent.id, node.rel_type)
            for edge in edges:
                ctx.consume_op()
                tgt_ent = world.entities.get_entity(edge.target_id)
                if tgt_ent:
                    ctx.touch_entity(tgt_ent.id)
                    ctx.variables[node.iterator_var] = tgt_ent
                    for child in node.body:
                        self.eval_effect(child, ctx, world)

        else:
            raise GRLExecutionError(f"Unsupported effect node: {type(node).__name__}")

    def _commit_transactions(self, ctx: ExecutionContext, world: WorldState) -> None:
        """Apply all staged mutations to WorldState."""
        # 1. Properties
        for (ent_id, prop_name), val in ctx.staged_properties.items():
            ent = world.entities.get_entity(ent_id)
            if ent:
                ent.set_property(prop_name, val)

        # 2. Resources
        for pool_name, delta in ctx.staged_resources.items():
            pool = world.resources.get_pool(pool_name)
            if pool:
                pool.set_balance(pool.balance + delta)

        # 3. Relationships
        for edge in ctx.staged_added_edges:
            world.relationships.add_edge(
                edge.source_id, edge.target_id, edge.rel_type, edge.weight, edge.properties
            )
        for (s_id, t_id, r_type) in ctx.staged_removed_edges:
            world.relationships.remove_edge(s_id, t_id, r_type)

        # 4. Events
        for ev in ctx.staged_events:
            world.event_queue._events.append(ev)
        world.event_queue._events.sort(key=lambda e: e.sort_key)
