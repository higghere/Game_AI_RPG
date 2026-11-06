"""GENESIS Rule Language Sandboxed Interpreter.

Evaluates declarative GRL rules against simulation state with strict
operation metering (<= 256 ops), entity touch tracking (<= 1000 entities),
and atomic single-rule rollback on failure or quota overflow.
"""

from __future__ import annotations
from typing import Any, Dict, List, Optional, Set, Tuple, Union

from genesis.core.arithmetic import FixedPoint, check_int64, half_even_div, half_even_mod
from genesis.core.config import DEFAULT_CONFIG, RuntimeConfig
from genesis.core.errors import (
    ArithmeticRangeError,
    DivisionByZeroError,
    GenesisError,
    GRLExecutionError,
    InternalRuntimeError,
    QuotaExceededError,
)
from genesis.core.rng import GenesisRNG, derive_rule_stream
from genesis.grl.ast import (
    AddRelationshipNode,
    AdjustPropertyNode,
    AggregateNode,
    BinaryOpNode,
    ConsumeResourceNode,
    CreateEntityNode,
    DestroyEntityNode,
    FindEntityNode,
    ForEachNode,
    GetPropertyNode,
    GetResourceNode,
    GRLNode,
    HasRelationshipNode,
    IfNode,
    LiteralNode,
    ProduceResourceNode,
    RandomFixedNode,
    RandomIntNode,
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
        "new_world_touches",
        "max_touched_entities",
        "variables",
        "staged_properties",
        "staged_resources",
        "staged_added_edges",
        "staged_removed_edges",
        "staged_events",
        "staged_created_entities",
        "staged_destroyed_entities",
        "rng",
        "initial_entities_next_id",
    )

    def __init__(
        self,
        rule_id: str,
        world_or_config: Optional[Union[WorldState, RuntimeConfig]] = None,
        config: Optional[RuntimeConfig] = None,
        rule_rng: Optional[GenesisRNG] = None,
    ) -> None:
        self.rule_id = rule_id
        self.operations_count = 0

        world: Optional[WorldState] = None
        cfg: RuntimeConfig = DEFAULT_CONFIG

        if isinstance(world_or_config, WorldState):
            world = world_or_config
            cfg = config or DEFAULT_CONFIG
        elif isinstance(world_or_config, RuntimeConfig):
            cfg = world_or_config
        elif config is not None:
            cfg = config

        self.max_operations = cfg.max_operations_per_rule
        self.touched_entities: Set[int] = set()
        self.new_world_touches: int = 0
        self.max_touched_entities = cfg.max_entities_touched_per_tick
        self.variables: Dict[str, Any] = {}

        # Transactional staging buffers (single-rule rollback)
        self.staged_properties: Dict[Tuple[int, str], Any] = {}
        self.staged_resources: Dict[str, FixedPoint] = {}
        self.staged_added_edges: List[RelationshipEdge] = []
        self.staged_removed_edges: List[Tuple[int, int, str]] = []
        self.staged_events: List[EventRecord] = []
        self.staged_created_entities: List[Entity] = []
        self.staged_destroyed_entities: List[int] = []

        # Substrate snapshots for rollback atomicity
        if world is not None:
            self.initial_entities_next_id = world.entities._next_id
        else:
            self.initial_entities_next_id = 1

        if rule_rng is not None:
            self.rng: Optional[GenesisRNG] = rule_rng
        elif world is not None:
            self.rng = derive_rule_stream(world.world_seed, world.clock.current_tick, rule_id, None, 0)
        else:
            self.rng = None

    def consume_op(self) -> None:
        """Consume 1 operation budget credit."""
        self.operations_count += 1
        if self.operations_count > self.max_operations:
            raise QuotaExceededError(
                f"Rule '{self.rule_id}' exceeded max_operations_per_rule: {self.max_operations}"
            )

    def touch_entity(self, entity_id: int, world: WorldState) -> None:
        """Record an entity touched by read or write, enforcing tick-wide aggregate limit with O(1) incremental accounting."""
        if entity_id not in self.touched_entities:
            self.touched_entities.add(entity_id)
            if entity_id not in world.entities_touched_this_tick:
                self.new_world_touches += 1
                total_touched = len(world.entities_touched_this_tick) + self.new_world_touches
                if total_touched > self.max_touched_entities:
                    world.entities_touched_this_tick.update(self.touched_entities)
                    raise QuotaExceededError(
                        f"Rule '{self.rule_id}' exceeded max_entities_touched_per_tick: {self.max_touched_entities} across tick {world.clock.current_tick} (attempted {total_touched})"
                    )


class GRLInterpreter:
    """Sandboxed, deterministic evaluator for GRL rules."""

    def __init__(self, config: RuntimeConfig = DEFAULT_CONFIG) -> None:
        self.config = config

    def execute_rule(
        self,
        rule: RuleDefinition,
        world: WorldState,
        cell: Optional[Tuple[int, int]] = None,
        defer_spatial_sync: bool = False,
        invocation_index: Optional[int] = None,
    ) -> Tuple[bool, str]:
        """Execute a rule against world state with single-rule rollback on error.

        If cell is specified, the rule executes scoped to entities in that spatial cell,
        with a fresh per-cell operation budget.
        """
        invocation_id = f"{rule.rule_id}@{cell[0]},{cell[1]}" if cell is not None else rule.rule_id
        if invocation_index is None:
            invocation_index = world.get_and_increment_rule_invocation_count(rule.rule_id, cell)
        rule_rng = derive_rule_stream(
            world.world_seed, world.clock.current_tick, rule.rule_id, cell, invocation_index
        )
        ctx = ExecutionContext(invocation_id, world, self.config, rule_rng=rule_rng)
        if cell is not None:
            ctx.variables["current_cell_x"] = cell[0]
            ctx.variables["current_cell_y"] = cell[1]

        try:
            # 1. Global Preconditions Gate
            for pre in rule.preconditions:
                ctx.consume_op()
                if not self.eval_expression(pre, ctx, world):
                    return True, "Preconditions not satisfied"

            # 2. Target Candidate Selection & Filtering
            candidate_entities: List[Optional[Entity]] = []
            if rule.target_selector:
                sel = rule.target_selector
                target_cell = cell if cell is not None else sel.spatial_cell

                if target_cell is not None:
                    # Spatial lookup through substrate: O(1) cell lookup
                    cell_entity_ids = world.spatial_index.get_entities_in_cell(target_cell[0], target_cell[1])
                    entities_to_evaluate: List[Entity] = []
                    for eid in cell_entity_ids:
                        ent = world.entities.get_entity(eid)
                        if ent and ent.is_active and ent.entity_type == sel.entity_type:
                            entities_to_evaluate.append(ent)
                else:
                    # Global lookup across entire world
                    entities_to_evaluate = world.entities.get_entities_by_type(sel.entity_type)

                for ent in entities_to_evaluate:
                    # Reading an entity during selection counts as a touch
                    ctx.touch_entity(ent.id, world)
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

            # 3. Apply Effects for each matching target candidate
            for target_ent in candidate_entities:
                if target_ent is not None:
                    ctx.variables["target"] = target_ent

                for effect in rule.effects:
                    self.eval_effect(effect, ctx, world)

            # 4. Commit staged transactions atomically
            self._commit_transactions(ctx, world, defer_spatial_sync=defer_spatial_sync, rule_priority=rule.priority)
            world.entities_touched_this_tick.update(ctx.touched_entities)

            # Record success event in journal
            if world.audit_level == "TRACE":
                success_event = EventRecord(
                    tick=world.clock.current_tick,
                    phase=PHASE_GRL_RULES,
                    priority=rule.priority,
                    sequence_id=world.next_sequence_id(),
                    event_type="rule_executed_success",
                    payload={
                        "rule_id": invocation_id,
                        "operations_consumed": str(ctx.operations_count),
                        "entities_touched": str(len(ctx.touched_entities)),
                    },
                )
                world.event_journal.append(success_event)
            else:
                world.record_routine_rule_success(ctx.operations_count, len(ctx.touched_entities))

            return True, "Executed successfully"

        except GenesisError as exc:
            # Single-rule rollback for domain errors (quota exceeded, schema violation, etc.)
            world.entities._next_id = ctx.initial_entities_next_id

            # Restore any entities marked inactive during this rule
            for eid in ctx.staged_destroyed_entities:
                ent = world.entities.get_entity(eid)
                if ent:
                    ent.is_active = True

            world.entities_touched_this_tick.update(ctx.touched_entities)
            failure_event = EventRecord(
                tick=world.clock.current_tick,
                phase=PHASE_GRL_RULES,
                priority=rule.priority,
                sequence_id=world.next_sequence_id(),
                event_type="rule_execution_failed",
                payload={
                    "rule_id": invocation_id,
                    "error_type": type(exc).__name__,
                    "error_message": str(exc),
                    "operations_consumed": str(ctx.operations_count),
                    "entities_touched": str(len(ctx.touched_entities)),
                },
            )
            world.event_journal.append(failure_event)
            return False, f"{type(exc).__name__}: {str(exc)}"

        except Exception as exc:
            # Unexpected system / host / programming error
            world.entities._next_id = ctx.initial_entities_next_id
            for eid in ctx.staged_destroyed_entities:
                ent = world.entities.get_entity(eid)
                if ent:
                    ent.is_active = True

            internal_event = EventRecord(
                tick=world.clock.current_tick,
                phase=PHASE_GRL_RULES,
                priority=rule.priority,
                sequence_id=world.next_sequence_id(),
                event_type="internal_runtime_error",
                payload={
                    "rule_id": rule.rule_id,
                    "error_type": "InternalRuntimeError",
                    "original_error": type(exc).__name__,
                    "error_message": str(exc),
                },
            )
            world.event_journal.append(internal_event)
            raise InternalRuntimeError(
                f"Internal runtime engine error in rule '{rule.rule_id}': {type(exc).__name__}: {str(exc)}"
            ) from exc

    def eval_expression(self, node: GRLNode, ctx: ExecutionContext, world: WorldState) -> Any:
        """Evaluate an expression node."""
        ctx.consume_op()

        if isinstance(node, LiteralNode):
            return node.value

        elif isinstance(node, GetPropertyNode):
            ent = ctx.variables.get(node.entity_var)
            if ent is None:
                if node.property_name == "id":
                    return 0
                return None
            if not isinstance(ent, Entity):
                raise GRLExecutionError(f"Variable '{node.entity_var}' is not an Entity")
            if not ent.is_active:
                raise GRLExecutionError(f"Cannot access property '{node.property_name}' on inactive/destroyed entity {ent.id}")
            ctx.touch_entity(ent.id, world)

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
            ctx.touch_entity(src_id, world)
            ctx.touch_entity(tgt_id, world)
            return world.relationships.has_edge(src_id, tgt_id, node.rel_type)

        elif isinstance(node, RandomIntNode):
            rng = ctx.rng if (ctx is not None and ctx.rng is not None) else world.rng
            return rng.next_int_range(node.min_val, node.max_val)

        elif isinstance(node, RandomFixedNode):
            rng = ctx.rng if (ctx is not None and ctx.rng is not None) else world.rng
            min_raw = node.min_val.raw_value
            max_raw = node.max_val.raw_value
            range_raw = max_raw - min_raw
            if range_raw == 0:
                return node.min_val
            draw = rng.next_int_range(0, range_raw)
            return FixedPoint.from_raw(min_raw + draw)

        elif isinstance(node, AggregateNode):
            return self._eval_aggregate(node, ctx, world)

        elif isinstance(node, BinaryOpNode):
            left_val = self.eval_expression(node.left, ctx, world)
            right_val = self.eval_expression(node.right, ctx, world)

            if node.op == "ADD":
                if isinstance(left_val, int) and isinstance(right_val, int) and not isinstance(left_val, bool) and not isinstance(right_val, bool):
                    return check_int64(left_val + right_val)
                return left_val + right_val
            elif node.op == "SUBTRACT":
                if isinstance(left_val, int) and isinstance(right_val, int) and not isinstance(left_val, bool) and not isinstance(right_val, bool):
                    return check_int64(left_val - right_val)
                return left_val - right_val
            elif node.op == "MULTIPLY":
                if isinstance(left_val, int) and isinstance(right_val, int) and not isinstance(left_val, bool) and not isinstance(right_val, bool):
                    return check_int64(left_val * right_val)
                return left_val * right_val
            elif node.op == "DIVIDE":
                if isinstance(left_val, int) and isinstance(right_val, int) and not isinstance(left_val, bool) and not isinstance(right_val, bool):
                    if right_val == 0:
                        raise DivisionByZeroError("Division by zero in integer arithmetic")
                    return half_even_div(left_val, right_val)
                elif isinstance(left_val, FixedPoint) or isinstance(right_val, FixedPoint):
                    if isinstance(right_val, FixedPoint) and right_val.raw_value == 0:
                        raise DivisionByZeroError("Division by zero in FixedPoint arithmetic")
                    if isinstance(right_val, int) and right_val == 0:
                        raise DivisionByZeroError("Division by zero in FixedPoint arithmetic")
                    return left_val / right_val
                raise GRLExecutionError(f"Unsupported types for DIVIDE: {type(left_val).__name__} / {type(right_val).__name__}")
            elif node.op == "MODULO":
                if isinstance(left_val, int) and isinstance(right_val, int) and not isinstance(left_val, bool) and not isinstance(right_val, bool):
                    if right_val == 0:
                        raise DivisionByZeroError("Modulo by zero in integer arithmetic")
                    return half_even_mod(left_val, right_val)
                elif isinstance(left_val, FixedPoint) and isinstance(right_val, FixedPoint):
                    if right_val.raw_value == 0:
                        raise DivisionByZeroError("Modulo by zero in FixedPoint arithmetic")
                    return left_val % right_val
                raise GRLExecutionError(f"Unsupported types for MODULO: {type(left_val).__name__} % {type(right_val).__name__}")
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
            if not ent.is_active:
                raise GRLExecutionError(f"Cannot set property on inactive/destroyed entity {ent.id}")
            ctx.touch_entity(ent.id, world)
            new_val = self.eval_expression(node.value_expr, ctx, world)
            schema = world.schema_registry.get_schema(ent.entity_type)
            if schema:
                new_val = schema.validate_property(node.property_name, new_val)
            ctx.staged_properties[(ent.id, node.property_name)] = new_val

        elif isinstance(node, AdjustPropertyNode):
            ent = ctx.variables.get(node.entity_var)
            if not isinstance(ent, Entity):
                raise GRLExecutionError(f"Cannot adjust property on non-entity '{node.entity_var}'")
            if not ent.is_active:
                raise GRLExecutionError(f"Cannot adjust property on inactive/destroyed entity {ent.id}")
            ctx.touch_entity(ent.id, world)
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
            f_delta = ctx.staged_resources.get(node.from_pool, FixedPoint.from_int(0)) - amount
            if from_pool.balance + f_delta < from_pool.min_capacity:
                raise GRLExecutionError(f"Transfer underflow on '{node.from_pool}'")
            ctx.staged_resources[node.from_pool] = f_delta
            t_delta = ctx.staged_resources.get(node.to_pool, FixedPoint.from_int(0)) + amount
            if to_pool.balance + t_delta > to_pool.max_capacity:
                raise GRLExecutionError(f"Transfer overflow on '{node.to_pool}'")
            ctx.staged_resources[node.to_pool] = t_delta

        elif isinstance(node, AddRelationshipNode):
            src = ctx.variables.get(node.source_var)
            tgt = ctx.variables.get(node.target_var)
            src_id = src.id if isinstance(src, Entity) else int(src)
            tgt_id = tgt.id if isinstance(tgt, Entity) else int(tgt)
            ctx.touch_entity(src_id, world)
            ctx.touch_entity(tgt_id, world)
            weight = self.eval_expression(node.weight_expr, ctx, world) if node.weight_expr else FixedPoint.from_int(1)
            ctx.staged_added_edges.append(RelationshipEdge(src_id, tgt_id, node.rel_type, weight))

        elif isinstance(node, RemoveRelationshipNode):
            src = ctx.variables.get(node.source_var)
            tgt = ctx.variables.get(node.target_var)
            src_id = src.id if isinstance(src, Entity) else int(src)
            tgt_id = tgt.id if isinstance(tgt, Entity) else int(tgt)
            ctx.touch_entity(src_id, world)
            ctx.touch_entity(tgt_id, world)
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
            source_ent = ctx.variables.get("target")
            entities_to_iterate: List[Entity] = []

            if node.collection_source == "incoming_relationships" and isinstance(source_ent, Entity):
                edges = world.relationships.get_incoming(source_ent.id, node.rel_type)
                for edge in edges[:node.max_iterations]:
                    src_ent = world.entities.get_entity(edge.source_id)
                    if src_ent and src_ent.is_active:
                        entities_to_iterate.append(src_ent)
            elif node.collection_source in ("outgoing_relationships", "relationships") and isinstance(source_ent, Entity):
                edges = world.relationships.get_outgoing(source_ent.id, node.rel_type)
                for edge in edges[:node.max_iterations]:
                    tgt_ent = world.entities.get_entity(edge.target_id)
                    if tgt_ent and tgt_ent.is_active:
                        entities_to_iterate.append(tgt_ent)
            elif node.collection_source == "cell_entities":
                cx = ctx.variables.get("current_cell_x")
                cy = ctx.variables.get("current_cell_y")
                if cx is None or cy is None:
                    if isinstance(source_ent, Entity):
                        cx = source_ent.get_property("cell_x") or 0
                        cy = source_ent.get_property("cell_y") or 0
                    else:
                        cx, cy = 0, 0
                eids = world.spatial_index.get_entities_in_cell(int(cx), int(cy))
                for eid in eids[:node.max_iterations]:
                    ent = world.entities.get_entity(eid)
                    if ent and ent.is_active:
                        entities_to_iterate.append(ent)

            for member in entities_to_iterate:
                ctx.consume_op()  # Step cost per iteration
                ctx.touch_entity(member.id, world)
                ctx.variables[node.iterator_var] = member
                for child in node.body:
                    self.eval_effect(child, ctx, world)

        elif isinstance(node, CreateEntityNode):
            # 5 base ops: 1 consumed in eval_effect, consume remaining 4
            for _ in range(4):
                ctx.consume_op()

            schema = world.schema_registry.get_schema(node.entity_type)
            if not schema:
                raise GRLExecutionError(f"Cannot create entity: schema '{node.entity_type}' not found")

            # Evaluate initial properties in sorted key order
            evaluated_props: Dict[str, Any] = {}
            for prop_name in sorted(node.initial_properties.keys()):
                prop_expr = node.initial_properties[prop_name]
                val = self.eval_expression(prop_expr, ctx, world)
                val = schema.validate_property(prop_name, val)
                evaluated_props[prop_name] = val

            new_id = world.entities._next_id
            world.entities._next_id = check_int64(world.entities._next_id + 1)

            new_ent = Entity(
                entity_id=new_id,
                entity_type=node.entity_type,
                created_tick=world.clock.current_tick,
                properties=evaluated_props,
                is_active=True,
            )
            ctx.staged_created_entities.append(new_ent)
            ctx.touch_entity(new_id, world)
            ctx.variables[node.result_var] = new_ent

        elif isinstance(node, DestroyEntityNode):
            # 3 base ops: 1 consumed in eval_effect, consume remaining 2
            for _ in range(2):
                ctx.consume_op()

            ent = ctx.variables.get(node.entity_var)
            if not isinstance(ent, Entity):
                raise GRLExecutionError(f"Cannot destroy non-entity '{node.entity_var}'")

            ctx.touch_entity(ent.id, world)

            # Purge edge metering: 1 op per incident edge
            out_edges = world.relationships.get_outgoing(ent.id)
            in_edges = world.relationships.get_incoming(ent.id)
            total_edges = len(out_edges) + len(in_edges)
            for _ in range(total_edges):
                ctx.consume_op()

            # Mark entity inactive in-place for single-rule lifetime
            ent.is_active = False
            ctx.staged_destroyed_entities.append(ent.id)

        elif isinstance(node, FindEntityNode):
            candidates: List[Entity] = []

            if node.collection_source == "cell_entities":
                cx = ctx.variables.get("current_cell_x")
                cy = ctx.variables.get("current_cell_y")
                if cx is None or cy is None:
                    target = ctx.variables.get("target")
                    if isinstance(target, Entity):
                        cx = target.get_property("cell_x") or 0
                        cy = target.get_property("cell_y") or 0
                    else:
                        cx, cy = 0, 0
                eids = world.spatial_index.get_entities_in_cell(int(cx), int(cy))
                for eid in eids:
                    ent = world.entities.get_entity(eid)
                    if ent and ent.is_active:
                        if node.entity_type is None or ent.entity_type == node.entity_type:
                            candidates.append(ent)
                            if len(candidates) >= node.max_scan:
                                break

            elif node.collection_source in ("outgoing_relationships", "relationships"):
                target_ent = ctx.variables.get("target")
                if isinstance(target_ent, Entity):
                    edges = world.relationships.get_outgoing(target_ent.id, node.rel_type)
                    for edge in edges:
                        ent = world.entities.get_entity(edge.target_id)
                        if ent and ent.is_active:
                            if node.entity_type is None or ent.entity_type == node.entity_type:
                                candidates.append(ent)
                                if len(candidates) >= node.max_scan:
                                    break

            elif node.collection_source == "incoming_relationships":
                target_ent = ctx.variables.get("target")
                if isinstance(target_ent, Entity):
                    edges = world.relationships.get_incoming(target_ent.id, node.rel_type)
                    for edge in edges:
                        ent = world.entities.get_entity(edge.source_id)
                        if ent and ent.is_active:
                            if node.entity_type is None or ent.entity_type == node.entity_type:
                                candidates.append(ent)
                                if len(candidates) >= node.max_scan:
                                    break

            # Evaluate filter on each candidate
            matched_candidates: List[Entity] = []
            for cand in candidates:
                ctx.touch_entity(cand.id, world)
                ctx.consume_op()  # Candidate inspection cost

                if node.filter_expr is not None:
                    ctx.variables["candidate"] = cand
                    is_match = self.eval_expression(node.filter_expr, ctx, world)
                    if is_match:
                        matched_candidates.append(cand)
                        if node.order_by is None and len(matched_candidates) >= node.limit:
                            break
                else:
                    matched_candidates.append(cand)
                    if node.order_by is None and len(matched_candidates) >= node.limit:
                        break

            # Deterministic sorting if order_by specified
            if node.order_by is not None and matched_candidates:
                # Stable sort: tie-break by ID ASC, then primary sort by property
                matched_candidates.sort(key=lambda c: c.id)
                matched_candidates.sort(
                    key=lambda c: c.get_property(node.order_by) or 0,
                    reverse=(node.order_direction.upper() == "DESC")
                )

            if matched_candidates:
                ctx.variables[node.result_var] = matched_candidates[0]
            else:
                ctx.variables[node.result_var] = None

        elif isinstance(node, AggregateNode):
            self._eval_aggregate(node, ctx, world)

        else:
            raise GRLExecutionError(f"Unsupported effect node: {type(node).__name__}")

    def _eval_aggregate(self, node: AggregateNode, ctx: ExecutionContext, world: WorldState) -> Any:
        """Evaluate bounded AGGREGATE node over spatial cell or relationship neighborhood."""
        candidates: List[Entity] = []

        if node.collection_source == "cell_entities":
            cx = ctx.variables.get("current_cell_x")
            cy = ctx.variables.get("current_cell_y")
            if cx is None or cy is None:
                target = ctx.variables.get("target")
                if isinstance(target, Entity):
                    cx = target.get_property("cell_x") or 0
                    cy = target.get_property("cell_y") or 0
                else:
                    cx, cy = 0, 0
            eids = world.spatial_index.get_entities_in_cell(int(cx), int(cy))
            for eid in eids:
                ent = world.entities.get_entity(eid)
                if ent and ent.is_active:
                    if node.entity_type is None or ent.entity_type == node.entity_type:
                        candidates.append(ent)
                        if len(candidates) >= node.max_elements:
                            break

        elif node.collection_source in ("outgoing_relationships", "relationships"):
            target_ent = ctx.variables.get("target")
            if isinstance(target_ent, Entity):
                edges = world.relationships.get_outgoing(target_ent.id, node.rel_type)
                for edge in edges:
                    ent = world.entities.get_entity(edge.target_id)
                    if ent and ent.is_active:
                        if node.entity_type is None or ent.entity_type == node.entity_type:
                            candidates.append(ent)
                            if len(candidates) >= node.max_elements:
                                break

        elif node.collection_source == "incoming_relationships":
            target_ent = ctx.variables.get("target")
            if isinstance(target_ent, Entity):
                edges = world.relationships.get_incoming(target_ent.id, node.rel_type)
                for edge in edges:
                    ent = world.entities.get_entity(edge.source_id)
                    if ent and ent.is_active:
                        if node.entity_type is None or ent.entity_type == node.entity_type:
                            candidates.append(ent)
                            if len(candidates) >= node.max_elements:
                                break

        func = node.aggregate_func
        count = 0
        total: Any = None
        min_val: Any = None
        max_val: Any = None

        for elem in candidates:
            ctx.touch_entity(elem.id, world)
            ctx.consume_op()  # Element processing cost

            ctx.variables[node.element_var] = elem

            if node.filter_expr is not None:
                if not self.eval_expression(node.filter_expr, ctx, world):
                    continue

            count += 1

            if func in ("SUM", "MIN", "MAX"):
                if node.expr is not None:
                    val = self.eval_expression(node.expr, ctx, world)
                else:
                    val = FixedPoint.from_int(1)

                if func == "SUM":
                    if total is None:
                        total = val
                    else:
                        total = total + val
                elif func == "MIN":
                    if min_val is None or val < min_val:
                        min_val = val
                elif func == "MAX":
                    if max_val is None or val > max_val:
                        max_val = val

        if func == "COUNT":
            result = count
        elif func == "SUM":
            result = total if total is not None else 0
        elif func == "MIN":
            result = min_val if min_val is not None else 0
        elif func == "MAX":
            result = max_val if max_val is not None else 0
        else:
            result = 0

        if node.result_var:
            ctx.variables[node.result_var] = result
        return result

    def _commit_transactions(
        self,
        ctx: ExecutionContext,
        world: WorldState,
        defer_spatial_sync: bool = False,
        rule_priority: int = 0,
    ) -> None:
        """Apply all staged mutations to WorldState."""
        # 1. Created entities
        for new_ent in ctx.staged_created_entities:
            world.entities._entities[new_ent.id] = new_ent
            world.entities._by_type.setdefault(new_ent.entity_type, []).append(new_ent.id)
            cx = new_ent.get_property("cell_x")
            cy = new_ent.get_property("cell_y")
            if cx is None:
                cx = new_ent.get_property("pos_x") or 0
            if cy is None:
                cy = new_ent.get_property("pos_y") or 0
            world.spatial_index.place_entity(new_ent.id, int(cx), int(cy))

            # Emit entity_created domain event
            ev = EventRecord(
                tick=world.clock.current_tick,
                phase=PHASE_GRL_RULES,
                priority=rule_priority,
                sequence_id=world.next_sequence_id(),
                event_type="entity_created",
                payload={
                    "entity_id": str(new_ent.id),
                    "entity_type": new_ent.entity_type,
                    "cell_x": str(int(cx)),
                    "cell_y": str(int(cy)),
                },
            )
            world.event_journal.append(ev)

        # 2. Properties
        for (ent_id, prop_name), val in ctx.staged_properties.items():
            ent = world.entities.get_entity(ent_id)
            if ent:
                ent.set_property(prop_name, val)
                if prop_name in ("cell_x", "cell_y", "pos_x", "pos_y"):
                    if defer_spatial_sync:
                        world.defer_spatial_sync(ent.id)
                    else:
                        world.sync_entity_spatial(ent.id)

        # 3. Resources
        for pool_name, delta in ctx.staged_resources.items():
            pool = world.resources.get_pool(pool_name)
            if pool:
                pool.set_balance(pool.balance + delta)

        # 4. Relationships
        for edge in ctx.staged_added_edges:
            world.relationships.add_edge(
                edge.source_id, edge.target_id, edge.rel_type, edge.weight, edge.properties
            )
        for (s_id, t_id, r_type) in ctx.staged_removed_edges:
            world.relationships.remove_edge(s_id, t_id, r_type)

        # 5. Destroyed entities
        for eid in ctx.staged_destroyed_entities:
            ent = world.entities.get_entity(eid)
            etype = ent.entity_type if ent else "unknown"
            world.spatial_index.remove_entity(eid)
            world.relationships.remove_all_edges_for(eid)
            world.entities.destroy_entity(eid)

            # Emit entity_destroyed domain event
            ev = EventRecord(
                tick=world.clock.current_tick,
                phase=PHASE_GRL_RULES,
                priority=rule_priority,
                sequence_id=world.next_sequence_id(),
                event_type="entity_destroyed",
                payload={
                    "entity_id": str(eid),
                    "entity_type": etype,
                },
            )
            world.event_journal.append(ev)

        # 6. Events
        for ev in ctx.staged_events:
            world.event_queue._events.append(ev)
        world.event_queue._events.sort(key=lambda e: e.sort_key)
