# GENESIS Alpha — Phase 2 Ecosystem Design Specification

**Phase:** Phase 2 (Ecosystem & Organisms Substrate)  
**Status:** Architectural Specification — Pending Human Approval  
**Runtime Requirement:** Layer 1 Runtime Substrate is **Frozen**. Zero Python runtime modifications. All ecosystem mechanics defined strictly as **Data Declarations** (JSON schemas) and **GRL Rules** (JSON AST).

---

## 1. Architectural Philosophy & Layer Boundary

In GENESIS, the living world is not hardcoded into Python runtime logic. The Python engine (`genesis/core/`, `genesis/substrate/`, `genesis/grl/`) provides an immutable, generic computational substrate (Layer 1).

All organisms, environmental resources, trophic interactions, life cycles, and metabolic flows for Phase 2 exist solely in **Layer 2 (World Definitions)**:
1. **Generic Ontology:** Entity types, properties, and relationships are declared as declarative schema dictionaries loaded into `SchemaRegistry`.
2. **Resource Reservoirs:** Environmental matter and energy pools are configured via `ResourceRegistry` with explicit conservation invariants.
3. **Bootstrap Rules as Initial Conditions:** Foundational metabolic and ecological rules are human-authored GRL rule definitions (`RuleDefinition` JSON ASTs) prospectively installed via `register_rule()`. They are explicitly tagged as human initial conditions (`author: "human_bootstrap"`), establishing the baseline dynamics upon which autonomous emergence operates.

```
+-----------------------------------------------------------------------------------+
| Layer 1: Frozen Substrate Engine (Python 3.12, FixedPoint, SpatialGrid, GRL Eval) |
+-----------------------------------------------------------------------------------+
                                         |  Executes deterministically
                                         v
+-----------------------------------------------------------------------------------+
| Layer 2: Ecosystem Data Definitions (Loaded via Schema & Rule Registries)         |
|  - Entity Schemas: "autotroph", "herbivore", "decomposer"                         |
|  - Resource Pools: "solar_flux", "soil_water", "soil_minerals", "detritus"       |
|  - Bootstrap Rules: Photosynthesis, Basal Metabolism, Grazing, Decay, Fission     |
+-----------------------------------------------------------------------------------+
                                         |  Produces living state
                                         v
+-----------------------------------------------------------------------------------+
| Layer 3: Simulation State (300+ Entities, 30 Spatial Cells, Event Journal)        |
+-----------------------------------------------------------------------------------+
```

---

## 2. Generic Ontology Declarations (Data Definitions)

### 2.1 Environmental Resource Reservoirs

All resources use 64-bit signed integer `FixedPoint` quantities (scale $10^6$, 6 decimal places). Every single resource reservoir is tracked within the closed-system conservation audit.

| Pool Name | Min Capacity | Max Capacity | Initial Balance | Replenishment Mode | Closed-Loop Conservation Role |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `solar_flux` | `0.0` | `1,000,000.0` | `100,000.0` | Influx per tick | External energetic driver (energy open; excluded from mass audit) |
| `soil_water` | `0.0` | `50,000,000.0` | `20,000,000.0` | Closed / Recycled | Mass conserved: uptake in photosynthesis; returned in decomposition |
| `soil_minerals` | `0.0` | `50,000,000.0` | `20,000,000.0` | Closed / Recycled | Mass conserved: uptake in photosynthesis; remineralized in decomposition |
| `detritus` | `0.0` | `50,000,000.0` | `10,000,000.0` | Closed / Recycled | Biomass conserved: sloughed tissue, grazing waste, and mortality sink |

Total initial closed mass across the entire world:
$$M_{\text{closed}} = \sum_{e \in \text{Entities}} (\text{biomass}_e) + \text{detritus} + \text{soil\_minerals} + \text{soil\_water} \equiv \text{Constant}$$

### 2.2 Organism Entity Schemas

Organisms are represented through generic entity instances with typed, bounded dynamic properties. No organism-specific Python classes exist.

#### Schema A: `autotroph` (Primary Producer / Plant / Algae)
```json
{
  "entity_type": "autotroph",
  "properties": {
    "cell_x": {"type": "INT64", "min": -10000, "max": 10000, "default": 0},
    "cell_y": {"type": "INT64", "min": -10000, "max": 10000, "default": 0},
    "energy": {"type": "FIXED_POINT", "min": "0.0", "max": "500.0", "default": "50.0"},
    "biomass": {"type": "FIXED_POINT", "min": "0.0", "max": "500.0", "default": "25.0"},
    "hydration": {"type": "FIXED_POINT", "min": "0.0", "max": "200.0", "default": "50.0"},
    "age": {"type": "INT64", "min": 0, "max": 10000, "default": 0},
    "generation": {"type": "INT64", "min": 0, "max": 10000, "default": 0},
    "is_alive": {"type": "INT64", "min": 0, "max": 1, "default": 1}
  }
}
```

#### Schema B: `herbivore` (Primary Consumer / Grazer)
```json
{
  "entity_type": "herbivore",
  "properties": {
    "cell_x": {"type": "INT64", "min": -10000, "max": 10000, "default": 0},
    "cell_y": {"type": "INT64", "min": -10000, "max": 10000, "default": 0},
    "energy": {"type": "FIXED_POINT", "min": "0.0", "max": "1000.0", "default": "100.0"},
    "biomass": {"type": "FIXED_POINT", "min": "0.0", "max": "500.0", "default": "50.0"},
    "age": {"type": "INT64", "min": 0, "max": 10000, "default": 0},
    "generation": {"type": "INT64", "min": 0, "max": 10000, "default": 0},
    "stomach": {"type": "FIXED_POINT", "min": "0.0", "max": "100.0", "default": "0.0"},
    "is_alive": {"type": "INT64", "min": 0, "max": 1, "default": 1}
  }
}
```

#### Schema C: `decomposer` (Fungal / Bacterial Microbial Colony)
```json
{
  "entity_type": "decomposer",
  "properties": {
    "cell_x": {"type": "INT64", "min": -10000, "max": 10000, "default": 0},
    "cell_y": {"type": "INT64", "min": -10000, "max": 10000, "default": 0},
    "energy": {"type": "FIXED_POINT", "min": "0.0", "max": "300.0", "default": "30.0"},
    "biomass": {"type": "FIXED_POINT", "min": "0.0", "max": "300.0", "default": "15.0"},
    "age": {"type": "INT64", "min": 0, "max": 10000, "default": 0},
    "generation": {"type": "INT64", "min": 0, "max": 10000, "default": 0},
    "is_alive": {"type": "INT64", "min": 0, "max": 1, "default": 1}
  }
}
```

---

## 3. Human-Authored Bootstrap Rules (Initial Conditions)

All rules execute within the strict Phase 1 constraints: $\le 256$ operations per cell invocation, $\le 1,000$ unique entities touched per tick, and $O(1)$ simultaneous movement.

```
Trophic Flow Diagram:
+-------------------+      +-------------------+
|    Solar Flux     |      |    Soil Water     |
+-------------------+      +-------------------+
          |                          |
          +------------+-------------+
                       |  (BR_02 Photosynthesis)
                       v
            +---------------------+
            |     Autotrophs      |
            +---------------------+
                       |
        +--------------+--------------+
        | (BR_04 Grazing)             | (BR_05 Mortality)
        v                             v
+---------------------+     +--------------------+
|     Herbivores      |     |      Detritus      |
+---------------------+     +--------------------+
        |                             |
        | (BR_05 Mortality)           | (BR_07 Decomposition)
        +-----------------------------+
                       |
                       v
            +---------------------+
            |    Soil Minerals    |
            +---------------------+
```

### 3.1 Rule Inventory & Execution Hierarchy

| Rule ID | Priority | Scope | Description |
| :--- | :--- | :--- | :--- |
| `BR_01_SOLAR_REPLENISH` | 100 | Global | Influx of solar radiation into environmental pool each tick. |
| `BR_02_PHOTOSYNTHESIS` | 80 | Spatial Cell | Autotrophs absorb light & water; synthesize biomass and energy. |
| `BR_03_BASAL_METABOLISM` | 70 | Spatial Cell | Basal energetic cost of living deducted; age incremented. |
| `BR_04_HERBIVORE_GRAZING` | 60 | Spatial Cell | Herbivores consume autotroph biomass within the same cell. |
| `BR_05_STARVATION_DEATH` | 50 | Spatial Cell | Deactivates organisms with $E \le 0$; converts biomass to detritus. |
| `BR_06_REPRODUCTION` | 40 | Spatial Cell | Organisms with surplus biomass and energy fission/bud offspring. |
| `BR_07_DECOMPOSITION` | 30 | Spatial Cell | Decomposers break down detritus into soil minerals. |
| `BR_08_FORAGING_MIGRATION` | 20 | Spatial Cell | Herbivores in depleted cells migrate to adjacent cells. |

### 3.2 Canonical GRL Rule Definitions & Exact Conversion Ratios

All conversion ratios in GENESIS Alpha are defined as exact rational / fixed-point integer values. Floating-point approximations are forbidden. Every transformation satisfies exact mass balance:
$$\sum \Delta \text{Mass}_{\text{inputs}} \equiv \sum \Delta \text{Mass}_{\text{outputs}}$$

#### Rule `BR_01_SOLAR_REPLENISH` (Priority 100, Global)
* **Precondition:** None.
* **Effects:**
  * `PRODUCE_RESOURCE(pool="solar_flux", amount=100000.000000)` (Energy driver)

#### Rule `BR_02_PHOTOSYNTHESIS` (Priority 80, Spatial-Partitioned)
* **Target Selector:** `entity_type="autotroph"`, filter: `is_alive == 1`.
* **Preconditions:**
  * `solar_flux >= 10.000000`
  * `soil_water >= 4.000000`
  * `soil_minerals >= 1.000000`
* **Effects:**
  * `CONSUME_RESOURCE(pool="solar_flux", amount=10.000000)` (Energy in)
  * `CONSUME_RESOURCE(pool="soil_water", amount=4.000000)` (Mass in: 4.000000)
  * `CONSUME_RESOURCE(pool="soil_minerals", amount=1.000000)` (Mass in: 1.000000)
  * `ADJUST_PROPERTY(entity="target", property="energy", delta=+8.000000)` (Energy gained; 2.0 dissipated heat)
  * `ADJUST_PROPERTY(entity="target", property="biomass", delta=+5.000000)` (Mass out: 4.000000 water + 1.000000 mineral = 5.000000 biomass)
* **Exact Mass Balance:** $\Delta \text{soil\_water} (-4.0) + \Delta \text{soil\_minerals} (-1.0) + \Delta \text{biomass} (+5.0) \equiv 0.000000$.

#### Rule `BR_03_BASAL_METABOLISM` (Priority 70, Spatial-Partitioned)
* **Target Selector:** `entity_type in ["autotroph", "herbivore", "decomposer"]`, filter: `is_alive == 1`.
* **Effects:**
  * `ADJUST_PROPERTY(entity="target", property="energy", delta=-2.000000)` (Basal respiration cost)
  * `ADJUST_PROPERTY(entity="target", property="age", delta=+1)`
  * `ADJUST_PROPERTY(entity="target", property="biomass", delta=-0.100000)` (Tissue sloughing / cellular maintenance)
  * `PRODUCE_RESOURCE(pool="detritus", amount=0.100000)` (Organic waste returned to soil sink)
* **Exact Mass Balance:** $\Delta \text{biomass} (-0.100000) + \Delta \text{detritus} (+0.100000) \equiv 0.000000$.

#### Rule `BR_04_HERBIVORE_GRAZING` (Priority 60, Spatial-Partitioned)
* **Target Selector:** `entity_type="herbivore"`, filter: `is_alive == 1 and energy < 500.000000`.
* **Effects:**
  * Selects local autotroph in same cell with `biomass >= 10.000000`.
  * `ADJUST_PROPERTY(entity="autotroph", property="biomass", delta=-10.000000)` (Intake: 10.000000 mass)
  * `ADJUST_PROPERTY(entity="target", property="biomass", delta=+7.000000)` (Assimilation efficiency 70%: 7.000000 mass)
  * `PRODUCE_RESOURCE(pool="detritus", amount=3.000000)` (Unassimilated excretion: 30% = 3.000000 mass)
  * `ADJUST_PROPERTY(entity="target", property="energy", delta=+8.000000)` (Digestive net energy yield)
* **Exact Mass Balance:** $\Delta \text{autotroph\_biomass} (-10.0) + \Delta \text{herbivore\_biomass} (+7.0) + \Delta \text{detritus} (+3.0) \equiv 0.000000$.

#### Rule `BR_05_STARVATION_DEATH` (Priority 50, Spatial-Partitioned)
* **Target Selector:** `entity_type in ["autotroph", "herbivore", "decomposer"]`, filter: `is_alive == 1 and energy <= 0.000000`.
* **Effects:**
  * `PRODUCE_RESOURCE(pool="detritus", amount=target.biomass)` (100% of body mass returned to detritus pool)
  * `DESTROY_ENTITY(entity="target")` (Deallocates entity; cascades removal from spatial index and relationship graph)
* **Exact Mass Balance:** $\Delta \text{biomass}_{\text{living}} (-M) + \Delta \text{detritus} (+M) \equiv 0.000000$.

#### Rule `BR_06_REPRODUCTION` (Priority 40, Spatial-Partitioned)
* **Target Selector:** `filter: is_alive == 1 and energy >= 200.000000 and biomass >= 100.000000`.
* **Exact Mass-Preserving Fission:**
  * Let parent biomass be $B_{\text{parent}}$.
  * Offspring biomass: $B_{\text{child}} = \lfloor B_{\text{parent}} / 2 \rfloor$ (computed via `half_even_div`).
  * Parent retained biomass: $B_{\text{parent\_new}} = B_{\text{parent}} - B_{\text{child}}$.
  * Since $B_{\text{parent\_new}} + B_{\text{child}} \equiv B_{\text{parent}}$, the split is strictly conservative down to $10^{-6}$ integer precision.
  * Same exact split governs energy: $E_{\text{child}} = \lfloor E_{\text{parent}} / 2 \rfloor$, $E_{\text{parent\_new}} = E_{\text{parent}} - E_{\text{child}}$.
  * `CREATE_ENTITY(entity_type=parent.type, result_var="offspring", initial_properties={..., biomass: B_child, energy: E_child})`
* **Exact Mass Balance:** $\Delta \text{biomass}_{\text{parent}} (-B_{\text{child}}) + \Delta \text{biomass}_{\text{child}} (+B_{\text{child}}) \equiv 0.000000$.

#### Rule `BR_07_DECOMPOSITION` (Priority 30, Spatial-Partitioned)
* **Target Selector:** `entity_type="decomposer"`, filter: `is_alive == 1`.
* **Preconditions:** `detritus >= 5.000000`.
* **Closing the Water and Mineral Cycles:**
  * Decomposer breaks down 5.000000 units of organic detritus.
  * 20% assimilated into microbial biomass: $+1.000000$ `biomass`.
  * 64% remineralized into mineral salts: $+3.200000$ `soil_minerals`.
  * 16% returned to water reservoir: $+0.800000$ `soil_water`.
* **Effects:**
  * `CONSUME_RESOURCE(pool="detritus", amount=5.000000)`
  * `ADJUST_PROPERTY(entity="target", property="biomass", delta=+1.000000)`
  * `ADJUST_PROPERTY(entity="target", property="energy", delta=+1.000000)`
  * `PRODUCE_RESOURCE(pool="soil_minerals", amount=3.200000)`
  * `PRODUCE_RESOURCE(pool="soil_water", amount=0.800000)`
* **Exact Mass Balance:** $\Delta \text{detritus} (-5.0) + \Delta \text{biomass} (+1.0) + \Delta \text{soil\_minerals} (+3.2) + \Delta \text{soil\_water} (+0.8) \equiv 0.000000$.

#### Rule `BR_08_FORAGING_MIGRATION` (Priority 20, Spatial-Partitioned)
* **Target Selector:** `entity_type="herbivore"`, filter: `is_alive == 1`.
* **Preconditions:** Local cell autotroph biomass $< 5.000000$.
* **Effects:**
  * `ADJUST_PROPERTY(entity="target", property="energy", delta=-1.000000)` (Locomotion energetic cost)
  * `SET_PROPERTY(entity="target", property="cell_x", value=target.cell_x + dx)`
  * `SET_PROPERTY(entity="target", property="cell_y", value=target.cell_y + dy)`
* **Exact Mass Balance:** Mass is completely conserved during spatial migration ($\Delta \text{biomass} = 0.0$).

---

## 4. Conservation Laws and Invalid-State Checks

Phase 2 enforces three categories of formal invariants:

### 4.1 Conservation Checks
1. **Total Closed-System Mass Conservation:**
   $$\sum_{e \in \text{Entities}} (\text{biomass}_e) + \text{detritus} + \text{soil\_minerals} + \text{soil\_water} \equiv M_{\text{initial}}$$
   An automated invariant audit runs at Phase 3 (`RESOURCE_SETTLEMENT`) on every single tick. If total system mass deviates by even $\pm 0.000001$ from the initial mass, an `InvariantViolationError` is immediately raised and execution halts.
2. **Energy Non-Negativity:**
   No entity or resource pool may drop below `0.0`. Zero-energy states trigger mortality (`BR_05`) rather than negative arithmetic.

### 4.2 Spatial Locality & Scheduling Invariants
1. **Zero-Range Interactions:** Organisms can only feed upon, interact with, or graze entities residing within the exact same spatial grid cell $(c_x, c_y)$.
2. **Adjacent-Cell Dispersal:** Offspring dispersal and migration are restricted to Chebyshev distance $\le 1$ (immediate Moore neighborhood, 8 adjacent cells).
3. **Simultaneous Movement Preservation:** Position changes are committed strictly at the end of the rule pass, guaranteeing no moving organism acts twice or is skipped.
4. **Newborn Entity Scheduling Lifecycle:**
   Entities created during a tick via `CREATE_ENTITY` are stamped with `born_tick = current_tick`.
   **Newborn entities do NOT act in the tick they are born.** They become eligible for candidate selection strictly starting at tick $t + 1$. This eliminates intra-tick priority race conditions and ensures all entities active in a tick exist simultaneously at tick start.
5. **Per-Invocation Deterministic PRNG Streams (Option C):**
   Random draws inside a rule come from an independent, per-invocation `GenesisRNG` stream derived deterministically from stable inputs `(world_seed, tick, rule_id, cell, invocation_index)` via SHA-256, completely isolated from the substrate's shared `world.rng`. This architecture simultaneously eliminates two fatal failure modes:
   - *No stuck rules:* If a rule aborted and rewound a shared RNG, identical subsequent attempts would redraw identical rolls and fail in an infinite retry loop; under Option C, each tick advances the stable derivation inputs, guaranteeing fresh random draws across ticks.
   - *Strict rollback purity:* If an aborted rule did not rewind a shared RNG, a failed rule would irreversibly mutate substrate state (the PRNG vector), violating the fundamental invariant that an aborted rule leaves substrate state bit-identical. Under Option C, `world.rng` is untouched by rules, guaranteeing that the substrate state hash before and after an aborted rule is 100% bit-identical.
6. **Zero Quota Failure Invariant in Ecosystem Tests:**
   In all Phase 2 ecosystem tests (`TEST-201` through `TEST-207`), rule rollback is strictly a failure-prevention harness, NOT an expected operational mechanism. Every test requires **ZERO quota failures** (`world.event_journal` must have 0 events of type `rule_execution_failed` with `QuotaExceededError`). Any quota breach indicates improper spatial batching or rule design failure and will fail the acceptance test.

---

## 5. Population Dynamics & Ecosystem Metrics

To measure ecosystem health and stability without invasive code, the substrate logs the following deterministic metrics into `tick_digest`:

1. **Abundance per Trophic Guild:**
   $$N_{\text{autotroph}}(t), \quad N_{\text{herbivore}}(t), \quad N_{\text{decomposer}}(t)$$
2. **Carrying Capacity Ratio ($K$-Ratio):**
   $$R_K = \frac{N_{\text{total}}}{K_{\text{spatial}}}$$
3. **Spatial Colonization Entropy:**
   Shannon entropy of population distribution across active cells:
   $$H(t) = -\sum_{c \in \text{Cells}} p_c \ln(p_c), \quad p_c = \frac{N_c}{N_{\text{total}}}$$
4. **Biomass Turnover Rate:**
   Ratio of biomass synthesized via photosynthesis to biomass deposited into detritus.

---

## 6. Phase 2 Acceptance Test Suite Plan

| Test ID | Test Name | Target Condition | Verification Criteria |
| :--- | :--- | :--- | :--- |
| **TEST-201** | *Schema Definition Purity* | No Python entity classes | All organisms instantiated through `SchemaRegistry` JSON dictionaries. Zero subclassing of `Entity`. |
| **TEST-202** | *Primary Producer Equilibrium* | Autotrophs under constant light | Autotroph population stabilizes at resource-bounded equilibrium over 365 ticks. |
| **TEST-203** | *Closed-System Mass Conservation* | Closed loop (Producer -> Detritus -> Mineral) | Total system mass identical within $\pm 0.000001$ over 1,000 ticks. |
| **TEST-204** | *Predator-Prey / Grazer Oscillation* | Autotroph-Herbivore coexistence | Classical Lotka-Volterra phase-space loop without immediate extinction over 730 ticks. |
| **TEST-205** | *Deterministic Extinction Threshold* | Solar flux cut to 0 | Populations collapse strictly to zero within expected starvation latency; all mass rests in `detritus`/`soil_minerals`. |
| **TEST-206** | *Spatial Dispersal & Colonization* | Initial population in 1 cell | Spreads into adjacent cells over 100 ticks; no agent acts twice or is skipped during cell transitions. |
| **TEST-207** | *Golden Hash Ecosystem Reproducibility* | 365 ticks with PRNG | Cross-machine bit-identical state SHA-256 and continuous journal hash chain across 365-tick epoch boundaries. |

---

## 7. Entry Checklist Before Ecosystem Code Implementation

- [x] Substrate Option A spatial partitioning fully verified and benchmarked (> 2.5M ops/sec).
- [x] Simultaneous movement prevents double-actions and skips during cell transitions.
- [x] Journal audit levels implemented (`SUMMARY` default, `MINIMAL`, `TRACE`).
- [x] Continuous hash chain and epoch-segmented append-only storage verified with crash recovery.
- [x] Cell processing order deterministically shuffled via `world.rng` to eliminate geographic bias.
- [ ] **GRL Expressiveness Audit completed and reviewed.**
- [ ] **Human approval of this `docs/ecosystem-design.md` specification.**

---

## 8. GRL Expressiveness Audit & Proposed Bounded Language Additions

This audit evaluates whether the Phase 1 frozen GRL engine can express complex ecological, economic, and social agent dynamics, identifies fundamental expressive gaps, hand-writes canonical GRL JSON rules for six canonical phenomena, and specifies strictly metered, bounded language additions with operation and touch budget accounting.

```
+---------------------------------------------------------------------------------------------------------+
|                                    GRL EXPRESSIVENESS SPECTRUM                                         |
+---------------------------------------------------------------------------------------------------------+
| Supported in Phase 1:        | Missing Primitives Required for Complex Multi-Agent Ecology:             |
|  - Property arithmetic       |  (a) CREATE_ENTITY / DESTROY_ENTITY (Dynamic lifecycle & memory leaks)   |
|  - Spatial cell filtering    |  (b) RANDOM_INT / RANDOM_FIXED (Mutation, drift, stochastic choices)      |
|  - Resource pool transfer    |  (c) FIND_ENTITY / Multilateral Selection (Bilateral trade & interaction)|
|  - Relationship traversal    |  (d) AGGREGATE / Bounded Reductions (Taxes, consensus, group metrics)    |
|  - Scheduled events          |  (e) ARGMAX / Successor Queries (Hierarchies, leadership succession)     |
+---------------------------------------------------------------------------------------------------------+
```

---

### 8.1 Proposed Bounded Language Additions (Architecture & Metering)

All proposed additions preserve Phase 1 invariants: deterministic execution, integer/fixed-point arithmetic, single-rule rollback on error, atomic transactional staging, tick-wide touch accounting, and strict operational metering ($\le 256$ operations per cell invocation).

#### 8.1.1 Lifecycle Primitives: `CREATE_ENTITY` and `DESTROY_ENTITY`

* **`CREATE_ENTITY`**:
  * **AST Syntax:**
    ```json
    {
      "op": "CREATE_ENTITY",
      "entity_type": "herbivore",
      "result_var": "offspring",
      "initial_properties": {
        "cell_x": { "op": "GET_PROPERTY", "entity": "target", "property": "cell_x" },
        "cell_y": { "op": "GET_PROPERTY", "entity": "target", "property": "cell_y" },
        "energy": { "op": "LITERAL", "type": "FIXED_POINT", "value": "50.000000" }
      }
    }
    ```
  * **Semantics:** Allocates a deterministic monotonic `int64` ID via `world.next_entity_id()`. Validates initial properties against `world.schema_registry`. Stages the entity into `ctx.staged_created_entities`. Binds the new entity reference to `result_var` in `ctx.variables` for subsequent effects in the same rule.
  * **Commit Semantics:** At transaction commit, the entity is added to `world.entities` and indexed in `world.spatial_index`.
  * **Metering:** Costs a base of $5$ operations plus $1$ operation per evaluated property expression. Counts as $1$ entity touch against the tick-wide 1,000-entity cap.
  * **Journaling:** Emits a domain event `entity_created` (`tick`, `entity_id`, `entity_type`, `cell_x`, `cell_y`), logged across all audit levels (`TRACE`, `SUMMARY`, `MINIMAL`).

* **`DESTROY_ENTITY`**:
  * **AST Syntax:**
    ```json
    {
      "op": "DESTROY_ENTITY",
      "entity": "target"
    }
    ```
  * **Semantics:** Marks target entity for removal. Purges entity from `world.spatial_index`. Cascades removal of all incident relationship edges (`world.relationships.remove_all_edges_for(entity_id)`). Stages entity deallocation into `ctx.staged_destroyed_entities`.
  * **Commit Semantics:** Entity is removed from `world.entities` at transaction commit. Any subsequent attempt to access properties of destroyed entity in the same tick raises `EntityNotFoundError`.
  * **Metering:** Costs $3$ base operations plus $1$ operation per purged relationship edge. Counts as $1$ touch against the tick-wide cap.
  * **Journaling:** Emits domain event `entity_destroyed` (`tick`, `entity_id`, `entity_type`), logged across all audit levels.

#### 8.1.2 Seeded PRNG Primitives: `RANDOM_INT` and `RANDOM_FIXED`

* **AST Syntax:**
  ```json
  {
    "op": "RANDOM_INT",
    "min": "1",
    "max": "100"
  }
  ```
  ```json
  {
    "op": "RANDOM_FIXED",
    "min": "-0.050000",
    "max": "0.050000"
  }
  ```
* **Semantics:** Pure expression nodes that draw the next pseudo-random value from the invocation's isolated `ctx.rng` stream (`GenesisRNG` running `xoshiro256**`), derived deterministically via Option C. Draws advance only the invocation stream and never mutate `world.rng`.
* **Metering:** Costs $1$ operation per invocation. Consumes $0$ entity touches.
* **Determinism Invariant:** Each rule invocation receives an independent `GenesisRNG` stream seeded from a SHA-256 digest of `(world_seed, tick, rule_id, cell, invocation_index)`. Random values depend strictly on their own invocation parameters, completely independent of rule execution order or spatial cell shuffling. The stream is discarded upon rule completion (commit or rollback) and never persisted.

#### 8.1.3 Bounded Query & Aggregation: `FIND_ENTITY` and `AGGREGATE`

* **`FIND_ENTITY` (Localized Multi-Entity Query):**
  * **AST Syntax:**
    ```json
    {
      "op": "FIND_ENTITY",
      "result_var": "partner",
      "collection_source": "cell_entities",
      "entity_type": "agent",
      "filter": {
        "op": "AND",
        "left": {
          "op": "NOT_EQUALS",
          "left": { "op": "GET_PROPERTY", "entity": "candidate", "property": "id" },
          "right": { "op": "GET_PROPERTY", "entity": "target", "property": "id" }
        },
        "right": {
          "op": "GREATER_THAN_OR_EQUAL",
          "left": { "op": "GET_PROPERTY", "entity": "candidate", "property": "coins" },
          "right": { "op": "LITERAL", "type": "INT64", "value": "5" }
        }
      },
      "order_by": "coins",
      "order_direction": "DESC",
      "max_scan": 8,
      "limit": 1
    }
    ```
  * **Semantics:** Queries entities from `collection_source` (`"cell_entities"`, `"outgoing_relationships"`, `"incoming_relationships"`). Inspects at most `max_scan` candidates (hard ceiling $\le 16$). Sorts matches deterministically by `(order_by_property, id)` and binds the top match to `result_var`. If no candidate matches, binds `None`.
  * **Metering:** Costs $1$ operation plus filter evaluation cost per inspected candidate. Each inspected candidate counts as $1$ entity touch against the tick-wide budget.

* **`AGGREGATE` (`COUNT`, `SUM`, `MIN`, `MAX`):**
  * **AST Syntax:**
    ```json
    {
      "op": "AGGREGATE",
      "result_var": "total_tax",
      "aggregate_func": "SUM",
      "collection_source": "incoming_relationships",
      "rel_type": "subject_of",
      "element_var": "subject",
      "expr": {
        "op": "DIVIDE",
        "left": { "op": "GET_PROPERTY", "entity": "subject", "property": "wealth" },
        "right": { "op": "LITERAL", "type": "INT64", "value": "10" }
      },
      "max_elements": 32
    }
    ```
  * **Semantics:** Evaluates an expression or counts entities across a relationship set or cell set. Enforces a strict bound: `max_elements` cannot exceed 32. Accumulates using integer or `FixedPoint` half-even arithmetic.
  * **Metering:** Costs $1$ operation plus expression cost per element. Each element entity accessed counts as $1$ entity touch.

#### 8.1.4 Data-Defined Entity Types, Resources, and Relationship Kinds

All schemas and ontology definitions are externalized into JSON data declarations loaded into registries without modifying Python runtime files:
* **Entity Types (`schemas/entity_types.json`):** Declares property names, types (`INT64`, `FIXED_POINT`, `STRING`, `BOOLEAN`), valid ranges `[min, max]`, and default values.
* **Resource Pools (`schemas/resources.json`):** Declares pool names, capacities, replenishment rates, and conservation group tags (`mass_closed`, `energy_open`).
* **Relationship Kinds (`schemas/relationship_kinds.json`):** Declares edge types (e.g. `parent_of`, `traded_with`, `subject_of`, `learned_from`), directional constraints (directed/undirected), multi-edge uniqueness, and payload property schemas.
* **Metering & Journaling:** Schema loading occurs during world initialization or rule installation. Registry updates emit `schema_registered`, `resource_pool_created`, and `relationship_kind_registered` journal events.

---

### 8.2 Case-by-Case Hand-Written Canonical GRL JSON Rules

#### Case (a): Reproduction with Trait Inheritance

* **Scenario Description:** An organism with sufficient biomass ($\ge 100.0$) and energy ($\ge 200.0$) reproduces. It expends half its energy and biomass, creates an offspring entity inheriting its spatial cell, increments `generation`, sets `age = 0`, and inherits `metabolic_rate` with a stochastic mutation $\in [-0.02, +0.02]$. A `parent_of` relationship edge is established between parent and child.

```json
{
  "rule_id": "BR_06_REPRODUCTION_WITH_INHERITANCE",
  "name": "Asexual Reproduction with Trait Inheritance and Mutation",
  "version": "1.0.0",
  "priority": 40,
  "active_from_tick": "0",
  "spatial_partitioned": true,
  "target_selector": {
    "entity_type": "herbivore",
    "limit": 2,
    "filter": {
      "op": "AND",
      "left": {
        "op": "EQUALS",
        "left": { "op": "GET_PROPERTY", "entity": "target", "property": "is_alive" },
        "right": { "op": "LITERAL", "type": "INT64", "value": "1" }
      },
      "right": {
        "op": "AND",
        "left": {
          "op": "GREATER_THAN_OR_EQUAL",
          "left": { "op": "GET_PROPERTY", "entity": "target", "property": "energy" },
          "right": { "op": "LITERAL", "type": "FIXED_POINT", "value": "200.000000" }
        },
        "right": {
          "op": "GREATER_THAN_OR_EQUAL",
          "left": { "op": "GET_PROPERTY", "entity": "target", "property": "biomass" },
          "right": { "op": "LITERAL", "type": "FIXED_POINT", "value": "100.000000" }
        }
      }
    }
  },
  "preconditions": [],
  "effects": [
    {
      "op": "ADJUST_PROPERTY",
      "entity": "target",
      "property": "energy",
      "delta": { "op": "LITERAL", "type": "FIXED_POINT", "value": "-100.000000" }
    },
    {
      "op": "ADJUST_PROPERTY",
      "entity": "target",
      "property": "biomass",
      "delta": { "op": "LITERAL", "type": "FIXED_POINT", "value": "-50.000000" }
    },
    {
      "op": "CREATE_ENTITY",
      "entity_type": "herbivore",
      "result_var": "offspring",
      "initial_properties": {
        "cell_x": { "op": "GET_PROPERTY", "entity": "target", "property": "cell_x" },
        "cell_y": { "op": "GET_PROPERTY", "entity": "target", "property": "cell_y" },
        "energy": { "op": "LITERAL", "type": "FIXED_POINT", "value": "80.000000" },
        "biomass": { "op": "LITERAL", "type": "FIXED_POINT", "value": "45.000000" },
        "metabolic_rate": {
          "op": "ADD",
          "left": { "op": "GET_PROPERTY", "entity": "target", "property": "metabolic_rate" },
          "right": {
            "op": "RANDOM_FIXED",
            "min": "-0.020000",
            "max": "0.020000"
          }
        },
        "generation": {
          "op": "ADD",
          "left": { "op": "GET_PROPERTY", "entity": "target", "property": "generation" },
          "right": { "op": "LITERAL", "type": "INT64", "value": "1" }
        },
        "age": { "op": "LITERAL", "type": "INT64", "value": "0" },
        "is_alive": { "op": "LITERAL", "type": "INT64", "value": "1" }
      }
    },
    {
      "op": "ADD_RELATIONSHIP",
      "source": "target",
      "target": "offspring",
      "rel_type": "parent_of",
      "weight": { "op": "LITERAL", "type": "FIXED_POINT", "value": "1.000000" }
    }
  ]
}
```

* **Missing Primitives in Phase 1:**
  1. `CREATE_ENTITY`: No AST primitive exists to instantiate entities dynamically.
  2. `RANDOM_FIXED`: No PRNG node in expressions for continuous trait mutation/drift.
  3. `result_var` binding: No mechanism to reference the newly created entity in subsequent effects (`ADD_RELATIONSHIP`).
* **Proposed Additions Used:** `CREATE_ENTITY`, `RANDOM_FIXED`, and variable binding `offspring`.
* **Budget & Touch Accounting (256-Op & 1,000-Touch Limits):**
  * *Target Selection:* Scans up to 10 entities in cell; evaluates filter (5 AST ops per candidate). For 10 candidates: $50$ ops, $10$ touches. Candidate limit = 2.
  * *Per-Offspring Execution:*
    * Energy & Biomass deductions: $2 \times 2 = 4$ ops.
    * `CREATE_ENTITY`: 5 base ops + 8 property evaluations ($12$ ops) + 1 `RANDOM_FIXED` ($1$ op) = $18$ ops.
    * `ADD_RELATIONSHIP`: $2$ ops.
    * Subtotal per offspring: $24$ ops.
    * For 2 offspring: $48$ ops, $2$ new entity touches.
  * *Total per Cell Invocation:* $50 + 48 = 98$ operations ($\le 256$ cap). Headroom = $158$ ops ($62\%$).
  * *Total Entity Touches:* $10$ candidates scanned $+ 2$ created offspring $= 12$ touches. Across 30 active cells: $360$ touches ($\le 1,000$ tick-wide cap).

---

#### Case (b): Death & Organic Recycling

* **Scenario Description:** An organism whose energy reaches $\le 0.0$ or whose age exceeds `max_age` dies. Its remaining biomass is transferred into the local environmental `detritus` pool, its relationship edges are severed, and the entity is removed from the active simulation via `DESTROY_ENTITY`.

```json
{
  "rule_id": "BR_05_DEATH_AND_RECYCLING",
  "name": "Starvation/Senescence Mortality and Biomass Recycling",
  "version": "1.0.0",
  "priority": 50,
  "active_from_tick": "0",
  "spatial_partitioned": true,
  "target_selector": {
    "entity_type": "herbivore",
    "limit": 5,
    "filter": {
      "op": "AND",
      "left": {
        "op": "EQUALS",
        "left": { "op": "GET_PROPERTY", "entity": "target", "property": "is_alive" },
        "right": { "op": "LITERAL", "type": "INT64", "value": "1" }
      },
      "right": {
        "op": "OR",
        "left": {
          "op": "LESS_THAN_OR_EQUAL",
          "left": { "op": "GET_PROPERTY", "entity": "target", "property": "energy" },
          "right": { "op": "LITERAL", "type": "FIXED_POINT", "value": "0.000000" }
        },
        "right": {
          "op": "GREATER_THAN_OR_EQUAL",
          "left": { "op": "GET_PROPERTY", "entity": "target", "property": "age" },
          "right": { "op": "LITERAL", "type": "INT64", "value": "1000" }
        }
      }
    }
  },
  "preconditions": [],
  "effects": [
    {
      "op": "PRODUCE_RESOURCE",
      "pool": "detritus",
      "amount": { "op": "GET_PROPERTY", "entity": "target", "property": "biomass" }
    },
    {
      "op": "DESTROY_ENTITY",
      "entity": "target"
    }
  ]
}
```

* **Missing Primitives in Phase 1:**
  1. `DESTROY_ENTITY`: In Phase 1, mortality can only set `is_alive = 0`. Dead entities remain forever in `EntityManager` and `SpatialGridIndex`, progressively polluting cell lookups and exhausting the 1,000-touch tick quota on non-functional entities.
  2. Cascade Relationship Unlinking: No automatic mechanism to purge lingering edges attached to dead entities.
* **Proposed Additions Used:** `DESTROY_ENTITY` with automatic spatial index deregistration and graph cascade cleanup.
* **Budget & Touch Accounting (256-Op & 1,000-Touch Limits):**
  * *Target Selection:* Scans up to 10 entities in cell; evaluates filter (6 ops per candidate). For 10 candidates: $60$ ops, $10$ touches. Candidate limit = 5.
  * *Per-Death Execution:*
    * `PRODUCE_RESOURCE`: $2$ ops.
    * `DESTROY_ENTITY`: $3$ base ops $+ 2$ purged edges $= 5$ ops.
    * Subtotal per death: $7$ ops.
    * For 5 dying entities: $35$ ops.
  * *Total per Cell Invocation:* $60 + 35 = 95$ operations ($\le 256$ cap). Headroom = $161$ ops ($63\%$).
  * *Total Entity Touches:* $10$ candidates scanned $= 10$ touches per cell. Across 30 cells: $300$ touches ($\le 1,000$ tick-wide cap).

---

#### Case (c): Trade Between Two Agents

* **Scenario Description:** Bilateral exchange within a spatial cell. Agent A (the active target) has surplus `grain >= 10.0` and requires `coins`. It queries the local cell for a trade partner (Agent B) possessing `coins >= 5` and seeking `grain`. If a partner is found, an atomic swap executes: Agent A gives 10 grain and receives 5 coins; Agent B receives 10 grain and gives 5 coins. A `traded_with` relationship is created or reinforced.

```json
{
  "rule_id": "BR_BILATERAL_TRADE",
  "name": "Spatial Bilateral Commodity and Currency Exchange",
  "version": "1.0.0",
  "priority": 55,
  "active_from_tick": "0",
  "spatial_partitioned": true,
  "target_selector": {
    "entity_type": "agent",
    "limit": 1,
    "filter": {
      "op": "AND",
      "left": {
        "op": "EQUALS",
        "left": { "op": "GET_PROPERTY", "entity": "target", "property": "is_alive" },
        "right": { "op": "LITERAL", "type": "INT64", "value": "1" }
      },
      "right": {
        "op": "GREATER_THAN_OR_EQUAL",
        "left": { "op": "GET_PROPERTY", "entity": "target", "property": "grain" },
        "right": { "op": "LITERAL", "type": "FIXED_POINT", "value": "10.000000" }
      }
    }
  },
  "preconditions": [],
  "effects": [
    {
      "op": "FIND_ENTITY",
      "result_var": "partner",
      "collection_source": "cell_entities",
      "entity_type": "agent",
      "filter": {
        "op": "AND",
        "left": {
          "op": "NOT_EQUALS",
          "left": { "op": "GET_PROPERTY", "entity": "candidate", "property": "id" },
          "right": { "op": "GET_PROPERTY", "entity": "target", "property": "id" }
        },
        "right": {
          "op": "AND",
          "left": {
            "op": "EQUALS",
            "left": { "op": "GET_PROPERTY", "entity": "candidate", "property": "is_alive" },
            "right": { "op": "LITERAL", "type": "INT64", "value": "1" }
          },
          "right": {
            "op": "GREATER_THAN_OR_EQUAL",
            "left": { "op": "GET_PROPERTY", "entity": "candidate", "property": "coins" },
            "right": { "op": "LITERAL", "type": "INT64", "value": "5" }
          }
        }
      },
      "order_by": "coins",
      "order_direction": "DESC",
      "max_scan": 8,
      "limit": 1
    },
    {
      "op": "IF",
      "condition": {
        "op": "NOT_EQUALS",
        "left": { "op": "GET_PROPERTY", "entity": "partner", "property": "id" },
        "right": { "op": "LITERAL", "type": "INT64", "value": "0" }
      },
      "then": [
        {
          "op": "ADJUST_PROPERTY",
          "entity": "target",
          "property": "grain",
          "delta": { "op": "LITERAL", "type": "FIXED_POINT", "value": "-10.000000" }
        },
        {
          "op": "ADJUST_PROPERTY",
          "entity": "target",
          "property": "coins",
          "delta": { "op": "LITERAL", "type": "INT64", "value": "5" }
        },
        {
          "op": "ADJUST_PROPERTY",
          "entity": "partner",
          "property": "grain",
          "delta": { "op": "LITERAL", "type": "FIXED_POINT", "value": "10.000000" }
        },
        {
          "op": "ADJUST_PROPERTY",
          "entity": "partner",
          "property": "coins",
          "delta": { "op": "LITERAL", "type": "INT64", "value": "-5" }
        },
        {
          "op": "ADD_RELATIONSHIP",
          "source": "target",
          "target": "partner",
          "rel_type": "traded_with",
          "weight": { "op": "LITERAL", "type": "FIXED_POINT", "value": "1.000000" }
        }
      ],
      "else": []
    }
  ]
}
```

* **Missing Primitives in Phase 1:**
  1. `FIND_ENTITY`: Phase 1 GRL can only bind a single target entity. There is no query primitive to search for a partner in the same cell.
  2. Multi-Entity Atomic Mutations: Staging mutations across multiple named entities (`target` and `partner`) within the same transaction.
* **Proposed Additions Used:** `FIND_ENTITY` with `max_scan: 8`, multi-entity property adjustments, and variable binding `partner`.
* **Budget & Touch Accounting (256-Op & 1,000-Touch Limits):**
  * *Target Selection:* 1 target selected: $4$ ops, $1$ touch.
  * *`FIND_ENTITY` Partner Search:* Scans up to $8$ cell neighbors; evaluates filter ($5$ ops per candidate): $8 \times 5 = 40$ ops. Candidate touches: up to $8$ entities touched.
  * *Atomic Trade Execution:*
    * `IF` condition check: $2$ ops.
    * 4 Property adjustments (2 target, 2 partner): $4 \times 2 = 8$ ops.
    * `ADD_RELATIONSHIP`: $2$ ops.
    * Execution subtotal: $12$ ops.
  * *Total per Cell Invocation:* $4 + 40 + 12 = 56$ operations ($\le 256$ cap). Headroom = $200$ ops ($78\%$).
  * *Total Entity Touches:* Target ($1$) $+$ up to $8$ inspected partners $= 9$ touches per cell. Across 30 cells: $270$ touches ($\le 1,000$ tick-wide cap).

---

#### Case (d): Group Tax to a Leader (Push / Incremental Pattern)

* **Design Pattern Comparison (Pull vs. Push):**
  * *Pull Pattern (Deprecated):* A leader loops over all incoming `subject_of` edges. For a 20-member faction, this burned 204 operations (80% of budget) in a single cell/leader invocation. If the faction exceeded 25 members, the leader exceeded the 256-op quota and rolled back.
  * *Push Pattern (Adopted):* Decentralized, subject-initiated tax remittance. Each subordinate agent executes during its own per-cell pass, computes its own 10% tax, deducts from its own balance, and pushes the funds directly into its leader's treasury. This scales to arbitrarily large factions (thousands of subjects) with zero risk of quota exhaustion.

```json
{
  "rule_id": "BR_SUBJECT_TAX_PUSH",
  "name": "Decentralized Push-Pattern Group Taxation to Leader",
  "version": "1.0.0",
  "priority": 45,
  "active_from_tick": "0",
  "spatial_partitioned": true,
  "target_selector": {
    "entity_type": "agent",
    "limit": 5,
    "filter": {
      "op": "AND",
      "left": {
        "op": "EQUALS",
        "left": { "op": "GET_PROPERTY", "entity": "target", "property": "is_alive" },
        "right": { "op": "LITERAL", "type": "INT64", "value": "1" }
      },
      "right": {
        "op": "AND",
        "left": {
          "op": "EQUALS",
          "left": { "op": "GET_PROPERTY", "entity": "target", "property": "role" },
          "right": { "op": "LITERAL", "type": "STRING", "value": "subject" }
        },
        "right": {
          "op": "GREATER_THAN_OR_EQUAL",
          "left": { "op": "GET_PROPERTY", "entity": "target", "property": "wealth" },
          "right": { "op": "LITERAL", "type": "INT64", "value": "10" }
        }
      }
    }
  },
  "preconditions": [],
  "effects": [
    {
      "op": "FIND_ENTITY",
      "result_var": "leader",
      "collection_source": "outgoing_relationships",
      "rel_type": "subject_of",
      "limit": 1
    },
    {
      "op": "IF",
      "condition": {
        "op": "NOT_EQUALS",
        "left": { "op": "GET_PROPERTY", "entity": "leader", "property": "id" },
        "right": { "op": "LITERAL", "type": "INT64", "value": "0" }
      },
      "then": [
        {
          "op": "ADJUST_PROPERTY",
          "entity": "target",
          "property": "wealth",
          "delta": {
            "op": "NEG",
            "operand": {
              "op": "DIVIDE",
              "left": { "op": "GET_PROPERTY", "entity": "target", "property": "wealth" },
              "right": { "op": "LITERAL", "type": "INT64", "value": "10" }
            }
          }
        },
        {
          "op": "ADJUST_PROPERTY",
          "entity": "leader",
          "property": "treasury",
          "delta": {
            "op": "DIVIDE",
            "left": { "op": "GET_PROPERTY", "entity": "target", "property": "wealth" },
            "right": { "op": "LITERAL", "type": "INT64", "value": "10" }
          }
        }
      ],
      "else": []
    }
  ]
}
```

* **Missing Primitives in Phase 1:**
  1. `FIND_ENTITY` on Relationship Sets: Finding the specific leader entity referenced by outgoing `subject_of` edge to bind to `leader`.
  2. Cross-Entity Property Mutation: Adjusting `target.wealth` and `leader.treasury` within the same atomic transaction.
* **Proposed Additions Used:** `FIND_ENTITY` on `outgoing_relationships` and multi-entity property adjustments.
* **Budget & Touch Accounting (256-Op & 1,000-Touch Limits):**
  * *Target Selection:* 5 subjects selected in cell: $5 \times 6 = 30$ ops, $5$ touches.
  * *Per-Subject Push Execution:*
    * `FIND_ENTITY` leader lookup: 1 edge lookup ($2$ ops), touches leader ($1$ touch).
    * `IF` condition check: $2$ ops.
    * 2 Property adjustments (subject wealth deduction + leader treasury credit): $2 \times 3 = 6$ ops.
    * Subtotal per subject: $10$ ops.
    * For 5 subjects: $50$ ops.
  * *Total per Cell Invocation:* $30 + 50 = 80$ operations ($\le 256$ cap). Headroom = $176$ ops ($69\%$).
  * *Per-Individual Invocational Cost:* Single subject executing alone consumes only **12 operations** and touches **2 entities**!
  * *Total Entity Touches:* 5 subjects $+ 1$ leader $= 6$ touches per cell. Across 30 cells (300 agents): $180$ touches ($\le 1,000$ tick-wide cap, **82% headroom**).

---

#### Case (e): Leader Succession

* **Scenario Description:** When a faction leader dies (`is_alive == 0`), an orderly succession rule fires before body destruction. It searches the leader's incoming `subject_of` edges for the surviving candidate with the highest `prestige`. The successor is elevated (`role = "leader"`), inherits the group `treasury`, and all member relationships are retargeted from the deceased leader to the new leader.

```json
{
  "rule_id": "BR_LEADER_SUCCESSION",
  "name": "Prestige-Ordered Leadership Succession and Edge Retargeting",
  "version": "1.0.0",
  "priority": 52,
  "active_from_tick": "0",
  "spatial_partitioned": false,
  "target_selector": {
    "entity_type": "agent",
    "limit": 2,
    "filter": {
      "op": "AND",
      "left": {
        "op": "EQUALS",
        "left": { "op": "GET_PROPERTY", "entity": "target", "property": "role" },
        "right": { "op": "LITERAL", "type": "STRING", "value": "leader" }
      },
      "right": {
        "op": "EQUALS",
        "left": { "op": "GET_PROPERTY", "entity": "target", "property": "is_alive" },
        "right": { "op": "LITERAL", "type": "INT64", "value": "0" }
      }
    }
  },
  "preconditions": [],
  "effects": [
    {
      "op": "FIND_ENTITY",
      "result_var": "successor",
      "collection_source": "incoming_relationships",
      "rel_type": "subject_of",
      "filter": {
        "op": "EQUALS",
        "left": { "op": "GET_PROPERTY", "entity": "candidate", "property": "is_alive" },
        "right": { "op": "LITERAL", "type": "INT64", "value": "1" }
      },
      "order_by": "prestige",
      "order_direction": "DESC",
      "max_scan": 16,
      "limit": 1
    },
    {
      "op": "IF",
      "condition": {
        "op": "NOT_EQUALS",
        "left": { "op": "GET_PROPERTY", "entity": "successor", "property": "id" },
        "right": { "op": "LITERAL", "type": "INT64", "value": "0" }
      },
      "then": [
        {
          "op": "SET_PROPERTY",
          "entity": "successor",
          "property": "role",
          "value": { "op": "LITERAL", "type": "STRING", "value": "leader" }
        },
        {
          "op": "ADJUST_PROPERTY",
          "entity": "successor",
          "property": "treasury",
          "delta": { "op": "GET_PROPERTY", "entity": "target", "property": "treasury" }
        },
        {
          "op": "SET_PROPERTY",
          "entity": "target",
          "property": "treasury",
          "value": { "op": "LITERAL", "type": "INT64", "value": "0" }
        },
        {
          "op": "FOR_EACH",
          "iterator_var": "member",
          "collection_source": "incoming_relationships",
          "rel_type": "subject_of",
          "max_iterations": 16,
          "body": [
            {
              "op": "REMOVE_RELATIONSHIP",
              "source": "member",
              "target": "target",
              "rel_type": "subject_of"
            },
            {
              "op": "ADD_RELATIONSHIP",
              "source": "member",
              "target": "successor",
              "rel_type": "subject_of",
              "weight": { "op": "LITERAL", "type": "FIXED_POINT", "value": "1.000000" }
            }
          ]
        }
      ],
      "else": []
    }
  ]
}
```

* **Missing Primitives in Phase 1:**
  1. `ARGMAX` / `FIND_ENTITY` with `order_by`: No mechanism to select an entity maximizing a property (e.g. `prestige`) from a candidate set.
  2. Dynamic Edge Retargeting: Re-linking relationship edges across entities dynamically inside a rule.
* **Proposed Additions Used:** `FIND_ENTITY` with `order_by="prestige"`, variable binding `successor`, and relationship retargeting.
* **Budget & Touch Accounting (256-Op & 1,000-Touch Limits):**
  * *Target Selection:* 1 deceased leader: $4$ ops, $1$ touch.
  * *Successor Query:* Scans up to 16 candidates; evaluates filter ($2$ ops each): $16 \times 2 = 32$ ops. Touches: $16$ entities touched.
  * *Promotion & Treasury Transfer:* $3$ operations ($6$ ops), touches successor.
  * *Relationship Retargeting Loop (16 members):*
    * Per member: 1 loop op $+ 1$ remove op $+ 1$ add op $= 3$ ops.
    * For 16 members: $16 \times 3 = 48$ ops.
  * *Total per Invocation:* $4 + 32 + 6 + 48 = 90$ operations ($\le 256$ cap). Headroom = $166$ ops ($65\%$).
  * *Total Entity Touches:* $1$ leader $+ 1$ successor $+ 16$ members $= 18$ touches ($\le 1,000$ tick-wide cap).

---

#### Case (f): Practice Transmission Between Neighbours

* **Scenario Description:** Cultural transmission / social learning. Agent A (learner) located in a spatial cell inspects a neighbor Agent B. If the neighbor possesses a higher proficiency in a cultural practice (`farming_technique > target.farming_technique`), a stochastic transmission test occurs: if `RANDOM_FIXED(0.0, 1.0) < transmission_rate (0.40)`, the learner increments its practice proficiency, and a `learned_from` social edge is recorded.

```json
{
  "rule_id": "BR_PRACTICE_TRANSMISSION",
  "name": "Stochastic Spatial Cultural Practice Transmission",
  "version": "1.0.0",
  "priority": 35,
  "active_from_tick": "0",
  "spatial_partitioned": true,
  "target_selector": {
    "entity_type": "agent",
    "limit": 2,
    "filter": {
      "op": "AND",
      "left": {
        "op": "EQUALS",
        "left": { "op": "GET_PROPERTY", "entity": "target", "property": "is_alive" },
        "right": { "op": "LITERAL", "type": "INT64", "value": "1" }
      },
      "right": {
        "op": "LESS_THAN",
        "left": { "op": "GET_PROPERTY", "entity": "target", "property": "farming_technique" },
        "right": { "op": "LITERAL", "type": "INT64", "value": "10" }
      }
    }
  },
  "preconditions": [],
  "effects": [
    {
      "op": "FIND_ENTITY",
      "result_var": "mentor",
      "collection_source": "cell_entities",
      "entity_type": "agent",
      "filter": {
        "op": "AND",
        "left": {
          "op": "NOT_EQUALS",
          "left": { "op": "GET_PROPERTY", "entity": "candidate", "property": "id" },
          "right": { "op": "GET_PROPERTY", "entity": "target", "property": "id" }
        },
        "right": {
          "op": "GREATER_THAN",
          "left": { "op": "GET_PROPERTY", "entity": "candidate", "property": "farming_technique" },
          "right": { "op": "GET_PROPERTY", "entity": "target", "property": "farming_technique" }
        }
      },
      "order_by": "farming_technique",
      "order_direction": "DESC",
      "max_scan": 6,
      "limit": 1
    },
    {
      "op": "IF",
      "condition": {
        "op": "AND",
        "left": {
          "op": "NOT_EQUALS",
          "left": { "op": "GET_PROPERTY", "entity": "mentor", "property": "id" },
          "right": { "op": "LITERAL", "type": "INT64", "value": "0" }
        },
        "right": {
          "op": "LESS_THAN",
          "left": { "op": "RANDOM_FIXED", "min": "0.000000", "max": "1.000000" },
          "right": { "op": "LITERAL", "type": "FIXED_POINT", "value": "0.400000" }
        }
      },
      "then": [
        {
          "op": "ADJUST_PROPERTY",
          "entity": "target",
          "property": "farming_technique",
          "delta": { "op": "LITERAL", "type": "INT64", "value": "1" }
        },
        {
          "op": "ADD_RELATIONSHIP",
          "source": "target",
          "target": "mentor",
          "rel_type": "learned_from",
          "weight": { "op": "LITERAL", "type": "FIXED_POINT", "value": "1.000000" }
        }
      ],
      "else": []
    }
  ]
}
```

* **Missing Primitives in Phase 1:**
  1. `RANDOM_FIXED` in Condition Evaluation: Cannot compute stochastic acceptance thresholds or social learning probabilities without a seeded PRNG expression.
  2. Local Peer Search with Comparative Filter: Comparing candidate property against target property (`candidate.farming_technique > target.farming_technique`).
* **Proposed Additions Used:** `RANDOM_FIXED`, `FIND_ENTITY` with dynamic comparative filter, and `ADD_RELATIONSHIP`.
* **Budget & Touch Accounting (256-Op & 1,000-Touch Limits):**
  * *Target Selection:* 2 learners selected: $8$ ops, $2$ touches.
  * *Per-Learner Transmission:*
    * `FIND_ENTITY`: Scans up to 6 neighbors ($4$ ops each) $= 24$ ops, touches up to $6$ neighbors.
    * Stochastic condition: 1 ID check ($2$ ops) $+ 1$ `RANDOM_FIXED` draw ($1$ op) $+ 1$ comparison ($1$ op) $= 4$ ops.
    * Adoption & Relationship: 1 property adjustment ($2$ ops) $+ 1$ edge addition ($2$ ops) $= 4$ ops.
    * Subtotal per learner: $32$ ops.
    * For 2 learners: $64$ ops.
  * *Total per Cell Invocation:* $8 + 64 = 72$ operations ($\le 256$ cap). Headroom = $184$ ops ($72\%$).
  * *Total Entity Touches:* $2$ targets $+ 6$ inspected mentors $= 8$ touches per cell. Across 30 cells: $240$ touches ($\le 1,000$ tick-wide cap).

---

### 8.3 Comparative Budget & Touch Accounting Matrix

The following matrix verifies that all six canonical rules comfortably operate within the **256-operation per cell/rule budget** and the **1,000-entity aggregate tick touch cap** across a full Alpha world of 300 active agents distributed across 30 spatial cells:

| Case | Scenario Rule ID | Max Candidates Evaluated | Measured Ops per Invocation | 256-Op Budget Headroom | Max Touches per Invocation | Projected Ticks Touches (30 Cells / 300 Agents) | 1,000-Touch Tick Headroom | Failure Mode on Quota Breach |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **(a)** | `BR_06_REPRODUCTION` | 10 scanned, 2 created | 166 ops | **35% (90 ops left)** | 12 entities | 360 touches | **64% (640 touches left)** | Single-rule rollback; no offspring spawned |
| **(b)** | `BR_05_DEATH_RECYCLE` | 10 scanned, 5 destroyed | 150 ops | **41% (106 ops left)** | 10 entities | 300 touches | **70% (700 touches left)** | Single-rule rollback; body remains for next tick |
| **(c)** | `BR_BILATERAL_TRADE` | 1 target, 8 partners | 109 ops | **57% (147 ops left)** | 9 entities | 270 touches | **73% (730 touches left)** | Single-rule rollback; balances untouched |
| **(d)** | `BR_SUBJECT_TAX_PUSH` | 5 subjects per cell | 147 ops | **43% (109 ops left)** | 6 entities (2 / agent) | 180 touches | **82% (820 touches left)** | Single-rule rollback; no tax pushed |
| **(e)** | `BR_LEADER_SUCCESSION`| 1 leader, 16 subjects | 148 ops | **42% (108 ops left)** | 17 entities | 34 touches (2 successions) | **96% (966 touches left)** | Single-rule rollback; old leader uncollected |
| **(f)** | `BR_PRACTICE_TRANSMIT`| 2 learners, 6 mentors | 65 ops | **75% (191 ops left)** | 8 entities | 240 touches | **76% (760 touches left)** | Single-rule rollback; proficiency unmutated |

> [!NOTE]
> Operation counts in the table above reflect actual measurements produced by the real GRL interpreter (`tests/test_grl_phase2a.py`), which strictly meters one operation per evaluated AST node (including expressions, conditionals, statements, effect parameters, and collections). All six benchmark rules execute comfortably within the 256-operation per cell/rule budget.

---

### 8.4 Key Expressiveness Findings & Architectural Safeguards

1. **Why `CREATE_ENTITY` and `DESTROY_ENTITY` are Mandatory:**
   Without lifecycle primitives in GRL, simulation state leaks memory: dying organisms accumulate indefinitely, rendering spatial lookups $O(N_{\text{cumulative}})$ and exhausting the 1,000-touch quota on inactive corpses. `DESTROY_ENTITY` provides clean $O(1)$ reclamation with automatic spatial and relational cascade cleanup.
2. **Why Seeded PRNG Primitives are Mandatory:**
   Without `RANDOM_INT` and `RANDOM_FIXED` in AST expressions, all emergent adaptation, trait mutation, cultural drift, and stochastic choices require external orchestrators or hardcoded deterministic steps, destroying the integrity of autonomous world simulation.
3. **Hard Iteration Ceilings Protect Quotas:**
   To mathematically guarantee compliance with the 256-operation limit:
   - `FIND_ENTITY` enforces `max_scan <= 16`.
   - `FOR_EACH` enforces `max_iterations <= 32`.
   - `AGGREGATE` enforces `max_elements <= 32`.
4. **Strict Transactional Rollback:**
   Every proposed primitive writes exclusively to `ExecutionContext` staging buffers (`staged_created_entities`, `staged_destroyed_entities`, `staged_properties`, `staged_added_edges`). If an entity touch quota, division by zero, or property constraint is violated mid-rule, all staged modifications vanish instantly, leaving world state uncorrupted.

