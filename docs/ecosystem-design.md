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

All resources use 64-bit signed integer `FixedPoint` quantities (scale $10^6$, 6 decimal places).

| Pool Name | Min Capacity | Max Capacity | Replenishment Mode | Conservation Invariant |
| :--- | :--- | :--- | :--- | :--- |
| `solar_flux` | `0.0` | `1,000,000.0` | Influx per tick | External energetic driver |
| `soil_water` | `0.0` | `50,000,000.0` | Closed / Recycled | Mass conserved: organism uptake + detritus release |
| `soil_minerals` | `0.0` | `50,000,000.0` | Closed / Recycled | Mass conserved: mineralization from detritus |
| `detritus` | `0.0` | `50,000,000.0` | Organic decay sink | Biomass conserved from expired organisms |

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

### 3.2 Canonical GRL Rule Definitions

#### Rule `BR_01_SOLAR_REPLENISH` (Priority 100, Global)
* **Precondition:** None.
* **Effects:**
  * `PRODUCE_RESOURCE(pool="solar_flux", amount=100000.0)`

#### Rule `BR_02_PHOTOSYNTHESIS` (Priority 80, Spatial-Partitioned)
* **Target Selector:** `entity_type="autotroph"`, filter: `is_alive == 1`.
* **Preconditions:**
  * `solar_flux >= 10.0`
  * `soil_water >= 5.0`
* **Effects:**
  * `CONSUME_RESOURCE(pool="solar_flux", amount=10.0)`
  * `CONSUME_RESOURCE(pool="soil_water", amount=5.0)`
  * `ADJUST_PROPERTY(entity="target", property="energy", delta=+8.0)`
  * `ADJUST_PROPERTY(entity="target", property="biomass", delta=+2.0)`

#### Rule `BR_03_BASAL_METABOLISM` (Priority 70, Spatial-Partitioned)
* **Target Selector:** `entity_type in ["autotroph", "herbivore", "decomposer"]`, filter: `is_alive == 1`.
* **Effects:**
  * `ADJUST_PROPERTY(entity="target", property="energy", delta=-2.0)`
  * `ADJUST_PROPERTY(entity="target", property="age", delta=+1)`

#### Rule `BR_04_HERBIVORE_GRAZING` (Priority 60, Spatial-Partitioned)
* **Target Selector:** `entity_type="herbivore"`, filter: `is_alive == 1 and energy < 500.0`.
* **Effects:**
  * Selects local autotroph in same cell, deducts $10.0$ biomass from autotroph, adds $+8.0$ energy and $+2.0$ biomass to herbivore.

#### Rule `BR_05_STARVATION_DEATH` (Priority 50, Spatial-Partitioned)
* **Target Selector:** `entity_type in ["autotroph", "herbivore", "decomposer"]`, filter: `is_alive == 1 and energy <= 0.0`.
* **Effects:**
  * `SET_PROPERTY(entity="target", property="is_alive", value=0)`
  * `PRODUCE_RESOURCE(pool="detritus", amount=target.biomass)`
  * `SCHEDULE_EVENT(event_type="death", delay_ticks=0, payload={"entity_id": target.id})`

#### Rule `BR_06_REPRODUCTION` (Priority 40, Spatial-Partitioned)
* **Target Selector:** `filter: is_alive == 1 and energy >= 200.0 and biomass >= 100.0`.
* **Effects:**
  * Deducts $50\%$ energy and biomass from parent.
  * Schedules perception event `birth` with new entity attributes.

#### Rule `BR_07_DECOMPOSITION` (Priority 30, Spatial-Partitioned)
* **Target Selector:** `entity_type="decomposer"`, filter: `is_alive == 1`.
* **Preconditions:** `detritus >= 5.0`.
* **Effects:**
  * `CONSUME_RESOURCE(pool="detritus", amount=5.0)`
  * `PRODUCE_RESOURCE(pool="soil_minerals", amount=4.0)`
  * `ADJUST_PROPERTY(entity="target", property="energy", delta=+1.0)`

---

## 4. Conservation Laws and Invalid-State Checks

Phase 2 enforces three categories of formal invariants:

### 4.1 Conservation Checks
1. **Mass Conservation:**
   $$\text{Biomass}_{\text{living}} + \text{Detritus} + \text{Soil Minerals} == \text{Total Initial Mass} \pm \Delta \text{Boundary Flux}$$
   An automated invariant audit runs at Phase 3 (`RESOURCE_SETTLEMENT`). If mass disappears without a corresponding journaled flux, an `InvariantViolationError` is raised.
2. **Energy Non-Negativity:**
   No entity or resource pool may drop below `0.0`. Zero-energy states trigger mortality (`BR_05`) rather than negative arithmetic.

### 4.2 Spatial Locality Invariants
1. **Zero-Range Interactions:** Organisms can only feed upon, interact with, or graze entities residing within the exact same spatial grid cell $(c_x, c_y)$.
2. **Adjacent-Cell Dispersal:** Offspring dispersal and migration are restricted to Chebyshev distance $\le 1$ (immediate Moore neighborhood, 8 adjacent cells).
3. **Simultaneous Movement Preservation:** Position changes are committed strictly at the end of the rule pass, guaranteeing no moving organism acts twice or is skipped.

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
- [ ] **Human approval of this `docs/ecosystem-design.md` specification.**
