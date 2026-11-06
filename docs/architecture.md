# GENESIS Alpha — System Architecture Specification

**Version:** 3.1  
**Phase:** Phase 0 / Phase 1  
**Status:** Approved with Engineering Conditions  

---

## 1. System Philosophy and Alpha Objective

GENESIS is a long-term initiative to construct a fully local, autonomous intelligence capable of creating, simulating, and evolving a living fictional world. A key architectural tenet is that rich worlds—such as an emergent medieval setting—must arise organically from underlying simulated dynamics, rather than from human-authored tropes, predefined kingdoms, hardcoded racial hierarchies, or scripted historical storylines.

### The Objective of Alpha
Alpha does **not** simulate a medieval kingdom, a sprawling RPG world, or a complex civilization. **Alpha proves one foundational hypothesis:**
> *GENESIS can define and execute new world-specific rules through a stable, deterministic, human-maintained substrate while strictly preserving state integrity and historical immutability.*

---

## 2. Four-Layer Architectural Boundary

| Layer | Primary Components | Owner | Alpha Permission |
| :--- | :--- | :--- | :--- |
| **Layer 1: Runtime Substrate** | GRL interpreter, state engine, event loop, clock, persistence, schema validation, resource limits | Humans | **Frozen.** GENESIS has zero write access. Cannot modify Python code, execution engine, or limits. |
| **Layer 2: World Definitions** | Entity type schemas, property declarations, relationship typologies, GRL rules | GENESIS (via proposals) | **Propose only.** Installs *only* prospectively after automated syntax, limit, and sandbox validation. |
| **Layer 3: Living Simulation** | Active entity graph, dynamic properties, resource reservoirs, event journal, snapshots | The Simulation | **Produced by running Layer 2 on Layer 1.** Fully deterministic state machine. |
| **Layer 4: Intelligence Engine** | Local model (7B–9B quantized), rule proposer, experiment runner, fitness evaluator | GENESIS | **Proposes only.** Operates outside simulation state; never executes arbitrary code or accesses the host shell. |

---

## 3. Core Substrate Architecture (Phase 1 Engineering Decisions)

1. **Entity & Property Storage:** Generic entities with dynamic property schemas. 64-bit unsigned integer `EntityID` values incremented monotonically. No hardcoded fictional types.
2. **Relationships:** Directed/weighted edges with property metadata. Queries return items deterministically sorted by `target_id`.
3. **Fixed-Point Arithmetic:** Pure integer `FixedPoint` scaling ($10^6$) with banker's rounding (`half_even`) implemented strictly in integer math. Floats are prohibited in state.
4. **JSON Number Stringification:** To bypass the IEEE-754 $2^{53}$ precision barrier in standard JSON parsers, all `int64` and `FixedPoint` values are stored as decimal strings in canonical snapshots.
5. **Deterministic PRNG:** Pure integer `xoshiro256**` with 256-bit state vector, checkpointed completely in every snapshot.
6. **Binary I/O with LF Line Endings:** All files hashed or snapshotted are written in binary mode with UTF-8 encoding and LF (`\n`) endings to eliminate Windows CRLF divergence.
7. **Append-Only Event Ledger with Hash Chains:** Every event entry incorporates the SHA-256 of the prior record, forming an immutable cryptographic chain.
8. **Atomic Persistence:** All disk writes write to a `.tmp` sibling file, flush, fsync, and atomic rename (`os.replace`).
9. **Rule Execution Order & Single-Rule Rollback:** Rules execute ordered by `(-priority, rule_id)`. Operational quota breaches roll back only the offending rule, recording a failure event.
10. **Schema & Rule Migration:** Explicitly **not supported in Alpha**. Breaking changes require a fresh simulation run.
11. **Offline Purity:** No external network requests, cloud services, or external APIs are used anywhere in the codebase.
12. **Spatial Grid Index & Locality Partitioning (Option A):**
    - Entities are partitioned into discrete 2D spatial grid cells `(cx, cy)` using integer or FixedPoint coordinates (zero floats).
    - Iteration is strictly deterministic: occupied cells are sorted by `(cx, cy)` ascending, and entities in each cell are sorted by `entity_id` ascending.
    - Spatial-partitioned rules execute once per occupied cell per tick in sorted cell order, with a fresh per-cell budget of 256 operations.
    - Matched/evaluated entities count toward the tick-wide aggregate cap (1,000 entities) tracked via $O(1)$ incremental accounting.
    - Spatial state is serialized canonically into snapshots and can be deterministically rebuilt from entity properties (`cell_x`/`cell_y` or `pos_x`/`pos_y`), guaranteeing bit-identical state hashes across snapshot save and reload.
    - Single-cell rollback: failure or quota breach in one cell rolls back only that cell's staged mutations, recording an event and allowing other cells to execute normally.

---

## 4. Package Structure (Phase 1 Substrate)

```text
genesis/
├── __init__.py
├── core/
│   ├── __init__.py
│   ├── arithmetic.py         # FixedPoint (scale 10^6, half_even, int64 decimal string support)
│   ├── clock.py              # Discrete tick clock (365 ticks/year, conversions)
│   ├── config.py             # Human-maintained immutable runtime constants
│   ├── errors.py             # Standard domain exceptions
│   └── rng.py                # Pure-integer xoshiro256** with full state serialization
├── substrate/
│   ├── __init__.py
│   ├── entities.py           # Generic Entity & EntityStorage with monotonic IDs
│   ├── properties.py         # Dynamic property schemas & validation
│   ├── relationships.py      # Typed graph edges & deterministic queries
│   ├── resources.py          # FixedPoint resource reservoirs & conservation checks
│   ├── spatial.py            # SpatialGridIndex, 2D coordinates, cell queries, canonical serialization
│   ├── events.py             # Deterministic event queue, phases, and hash-chain log
│   └── world_state.py        # Central WorldState aggregating components
├── grl/
│   ├── __init__.py
│   ├── ast.py                # GRL AST data classes
│   ├── parser.py             # JSON AST parser & validator
│   ├── validator.py          # Static limit & recursion validator (256 ops, depth 4)
│   ├── interpreter.py        # Sandboxed metered interpreter with single-rule rollback
│   ├── serializer.py         # Read-only human-readable formatter
│   └── registry.py           # Rule registry with deterministic ordering & prospective activation
└── persistence/
    ├── __init__.py
    ├── canonical.py          # RFC 8785 canonical JSON serializer (binary UTF-8 LF)
    ├── hasher.py             # SHA-256 state and journal hash computation
    └── snapshot.py           # Atomic state snapshot saver and restorer
```
