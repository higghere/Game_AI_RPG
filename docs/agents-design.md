# GENESIS Alpha — Phase 3 Design Specification: Individual Agents as Data (Traits, Needs, Genetics)

**Phase:** Phase 3 (Individual Agents as Data)  
**Status:** Architectural Specification — Stage 1 Pending Human Approval  
**Runtime Requirement:** Frozen Layer 1 Runtime Substrate (`genesis/core/`, `genesis/substrate/`, `genesis/grl/`, `genesis/ecosystem/`, `genesis/analysis/`). Zero Python runtime modifications. Zero agent-specific Python classes (`Entity.__subclasses__() == []` invariant strictly preserved). All agent mechanics defined purely as **Data Declarations** (JSON schemas) and **GRL Rules** (JSON AST).

---

## 1. Architectural Philosophy & Layer Boundary

In GENESIS, individually distinguishable agents are not implemented as custom Python classes, cognitive architectures, or opaque neural networks. The simulation substrate (Layer 1) provides generic entities, spatial hashing, property definitions, directional relationship graphs, resource reservoirs, and a sandboxed rule interpreter.

Phase 3 introduces the first individually distinguishable organisms: **autonomous agents with heritable traits, internal needs, and need-driven behavior**. Agents exist solely through declarative data structures and GRL rules:
1. **Generic Ontology:** Entity schema `agent` registered into `SchemaRegistry` with typed, bounded properties.
2. **Needs Dynamics:** Integer and FixedPoint physiological drives (hunger, thirst, fatigue, reproduction drive) updated by metabolic GRL rules.
3. **Mendelian Genetics as Data:** Fixed-length integer gene vectors representing heritable loci. Alleles are inherited from parents via rule PRNG streams, mutated within bounded rates, and expressed as physiological traits via declared arithmetic rules.
4. **Behavior via Bounded Rules:** Actions (eat, drink, rest, forage-move, reproduce, die) are ordinary GRL rules evaluated in priority order with deterministic tie-breaking. No planning, no memory, no goals, and no LLM scaffolding.
5. **Exact Mass Conservation:** Agents eat autotrophs or herbivores from the existing Phase 2 ecosystem, drink from `soil_water`, excrete waste to `detritus` and `soil_water`, and recycle 100% of body mass upon mortality, maintaining exact closed-system mass balance down to $10^{-6}$ integer precision.

```
+-----------------------------------------------------------------------------------+
| Layer 1: Frozen Substrate Engine (Python 3.12, FixedPoint, SpatialGrid, GRL Eval) |
+-----------------------------------------------------------------------------------+
                                         |  Executes deterministically
                                         v
+-----------------------------------------------------------------------------------+
| Layer 2: Declarative World & Agent Definitions                                    |
|  - Ecosystem Data (Phase 2): autotroph, herbivore, decomposer, resources          |
|  - Agent Schema: "agent" (body state, needs, 5 gene loci, 5 expressed traits)     |
|  - Agent GRL Rules: Metabolism, Mortality, Drink, Eat, Reproduce, Rest, Forage   |
+-----------------------------------------------------------------------------------+
                                         |  Produces living state
                                         v
+-----------------------------------------------------------------------------------+
| Layer 3: Simulation State (100-300 Agents, 200+ Ecosystem Entities, Journal)      |
+-----------------------------------------------------------------------------------+
                                         |  Read-only observation
                                         v
+-----------------------------------------------------------------------------------+
| Layer 4: Emergence Analysis (genesis/analysis/ - Settlement, Group, Culture)      |
+-----------------------------------------------------------------------------------+
```

---

## 2. Agent Schema & Ontology Declarations

### 2.1 Entity Schema: `agent`

Every agent is an entity of type `agent` possessing bounded properties spanning body state, physiological needs, genetic loci, and expressed traits.

#### 1. Body State Properties
* `is_alive` (`INT64`, $[0, 1]$, default $1$): Binary vitality indicator. $0$ designates deceased entity awaiting removal.
* `age_ticks` (`INT64`, $[0, 500000]$, default $0$): Chronological age in simulation ticks.
* `sex` (`INT64`, $[0, 1]$, default $0$): Biological sex encoded purely as data ($0 = \text{female/maternal}$, $1 = \text{male/paternal}$). Determines mating complementarity.
* `biomass` (`FIXED_POINT`, $[0.000000, 500.000000]$, default $40.000000$): Physical body mass contributing to the closed mass ledger.
* `energy` (`FIXED_POINT`, $[0.000000, 1000.000000]$, default $100.000000$): Metabolic energy reservoir driving biological processes.
* `cell_x` (`INT64`, $[-10000, 10000]$, default $0$): Spatial coordinate along grid X-axis.
* `cell_y` (`INT64`, $[-10000, 10000]$, default $0$): Spatial coordinate along grid Y-axis.
* `generation` (`INT64`, $[0, 10000]$, default $0$): Ancestral generation depth ($0$ for bootstrap Adam/Eve agents, $\max(\text{gen}_A, \text{gen}_B) + 1$ for offspring).
* `birth_tick` (`INT64`, $[0, 100000000]$, default $0$): Tick of genesis/birth (used by `AnalysisBinding` for generational anchoring and native birth calculations).
* `action_taken` (`INT64`, $[0, 1]$, default $0$): Per-tick single-action mutex flag. Prevents an agent from performing multiple incompatible actions (e.g. eating and foraging) in the same tick. Reset to $0$ each tick during metabolism.

#### 2. Physiological Needs Properties
All needs are represented as bounded `FIXED_POINT` quantities spanning $[0.000000, 100.000000]$. A value of $0.000000$ indicates complete satisfaction; $100.000000$ indicates critical deprivation.
* `hunger` (`FIXED_POINT`, $[0.000000, 100.000000]$, default $0.000000$): Caloric demand. Grows continuously based on metabolic rate. Satisfied by feeding on autotrophs or herbivores. Starvation occurs if hunger reaches $100.000000$ and energy drops to $0.000000$.
* `thirst` (`FIXED_POINT`, $[0.000000, 100.000000]$, default $0.000000$): Hydration demand. Grows continuously by $1.000000$ per tick. Satisfied by drinking from `soil_water`. Dehydration mortality occurs if thirst reaches $100.000000$.
* `fatigue` (`FIXED_POINT`, $[0.000000, 100.000000]$, default $0.000000$): Somatic exhaustion. Increases upon physical exertion (forage-movement, reproduction). Satisfied by resting.
* `reproduction_drive` (`FIXED_POINT`, $[0.000000, 100.000000]$, default $0.000000$): Gametic pressure. Accumulates once `age_ticks >= maturity_age_ticks` ($50$ ticks) and agent is well-nourished. Triggers mating behavior when exceeding the pre-registered threshold ($60.000000$). Resets to $0.000000$ upon successful reproduction.

#### 3. Genetic Loci (Genome as Integer Vector)
The genome is represented as a fixed-length vector of $K = 5$ bounded integer properties (`INT64`):
* `gene_metabolic_rate` (`INT64`, $[50, 200]$, default $100$): Locus 0. Governs rate of hunger increase and energetic efficiency. Expressed trait: $\text{metabolic\_rate} = \text{gene} / 100$ ($0.500000$ to $2.000000$).
* `gene_foraging_range` (`INT64`, $[1, 3]$, default $1$): Locus 1. Maximum spatial movement step in grid cells during foraging migration.
* `gene_fertility` (`INT64`, $[50, 200]$, default $100$): Locus 2. Rate of reproduction drive accumulation. Expressed trait: $\text{fertility} = \text{gene} / 100$ ($0.500000$ to $2.000000$).
* `gene_longevity` (`INT64`, $[500, 2500]$, default $1000$): Locus 3. Maximum lifespan in ticks before senescence mortality.
* `gene_boldness` (`INT64`, $[0, 100]$, default $50$): Locus 4. Risk tolerance and foraging propensity under moderate hunger. Expressed trait: $\text{boldness} = \text{gene} / 100$ ($0.000000$ to $1.000000$).

#### 4. Expressed Traits
Traits are derived deterministically from genes via declared arithmetic rules (never via hardcoded Python methods):
* `metabolic_rate` (`FIXED_POINT`, $[0.500000, 2.000000]$, default $1.000000$).
* `foraging_range` (`INT64`, $[1, 3]$, default $1$).
* `fertility` (`FIXED_POINT`, $[0.500000, 2.000000]$, default $1.000000$).
* `longevity` (`INT64`, $[500, 2500]$, default $1000$).
* `boldness` (`FIXED_POINT`, $[0.000000, 1.000000]$, default $0.500000$).

### 2.2 Parentage via Substrate Relationships
In strict adherence to runtime boundary rules, **parent IDs are never duplicated as scalar entity properties**. Parent-offspring lineage is maintained exclusively through the substrate relationship graph:
* Edge format: `RelationshipEdge(source_id=parent_id, target_id=child_id, rel_type="parent_of", weight=FixedPoint.from_int(1))`
* Two incoming edges for every sexually reproduced agent: `parent_a -> child` and `parent_b -> child`.
* Traversal: The genealogy is queried through `world.relationships.get_incoming(child_id, "parent_of")` and `world.relationships.get_outgoing(parent_id, "parent_of")`.
* Kinship distance is computed recursively through relationship BFS/DFS by the existing `genesis/analysis/culture.py` module.

---

## 3. Genetics & Heredity Mechanics (Data-Driven Mendelian Model)

### 3.1 Allele Inheritance Protocol
During sexual reproduction between two co-located agents (Parent A and Parent B):
1. **Locus-by-Locus Segregation:** For each locus $k \in \{0, 1, 2, 3, 4\}$, an independent pseudo-random coin flip is drawn from the rule's deterministic PRNG stream:
   $$\text{allele}_k = \begin{cases} \text{Parent A's gene}_k & \text{if } \text{RANDOM\_INT}(0, 1) = 0 \\ \text{Parent B's gene}_k & \text{if } \text{RANDOM\_INT}(0, 1) = 1 \end{cases}$$
2. **Point Mutation:** For each locus $k$, mutation occurs at the pre-registered rate $\mu = 10 / 1000$ (1.0% per locus per generation):
   $$\text{mutation\_check} = \text{RANDOM\_INT}(1, 1000)$$
   If $\text{mutation\_check} \le \text{mutation\_rate\_per\_thousand}$ ($10$):
   $$\Delta \text{gene}_k = \text{RANDOM\_INT}(-\text{mutation\_max\_step}, +\text{mutation\_max\_step}) = \text{RANDOM\_INT}(-5, +5)$$
   $$\text{gene}_k' = \text{clamp}(\text{gene}_k + \Delta \text{gene}_k, \text{min}_k, \text{max}_k)$$
3. **Deterministic Trait Expression:** Expressed traits are set to their exact declared transformation of $\text{gene}_k'$ in the `initial_properties` of `CREATE_ENTITY`.

### 3.2 Gene Flow & Journal Audit
Every birth event logs an `agent_birth` event into the immutable `EventJournal` containing:
* `parent_a_id`, `parent_b_id`, `child_id`
* Allele transmission choices ($0$ or $1$) for each locus
* Applied mutations (if any)
* Initial expressed traits

---

## 4. Need-Driven Action Selection & GRL Rules

### 4.1 Deterministic Action Selection Hierarchy
Agents possess no planning, goals, or temporal memory. Action selection is purely reflexive and strictly deterministic, governed by the relative magnitudes of physiological needs with a pre-registered tie-break order:

$$\text{Survival/Dehydration (Thirst)} > \text{Survival/Starvation (Hunger)} > \text{Somatic Rest (Fatigue)} > \text{Reproduction} > \text{Foraging Migration}$$

At each tick, rules execute in decreasing priority order ($90 \to 20$). A successful behavioral action sets `action_taken = 1`, which acts as a capacity guard preventing subsequent competing actions during that tick.

| Priority | Rule ID | Scope | Target Selector Filter | Description |
| :---: | :--- | :--- | :--- | :--- |
| **90** | `AR_01_METABOLISM` | Spatial Cell | `is_alive == 1` | Age increment, needs accumulation, basal energy/mass cost, reset `action_taken = 0`. |
| **85** | `AR_02_MORTALITY` | Spatial Cell | `is_alive == 1 and (energy <= 0 or hunger >= 100 or thirst >= 100 or age_ticks >= longevity)` | Starvation, dehydration, or senescence death. 100% biomass recycled to detritus. |
| **80** | `AR_03_DRINK` | Spatial Cell | `action_taken == 0 and thirst >= 30.0 and thirst >= hunger and thirst >= fatigue and thirst >= reproduction_drive` | Quench thirst from local `soil_water`. |
| **70** | `AR_04_EAT` | Spatial Cell | `action_taken == 0 and hunger >= 30.0 and hunger >= fatigue and hunger >= reproduction_drive` | Consume local autotroph or herbivore biomass to restore energy and quench hunger. |
| **60** | `AR_05_REPRODUCE` | Spatial Cell | `action_taken == 0 and sex == 0 and reproduction_drive >= 60.0 and energy >= 150.0 and biomass >= 60.0` | Mate with co-located male (`sex == 1`) to produce child agent. |
| **50** | `AR_06_REST` | Spatial Cell | `action_taken == 0 and fatigue >= 50.0` | Recuperate energy and reduce fatigue through somatic dormancy. |
| **40** | `AR_07_FORAGE_MOVE` | Spatial Cell | `action_taken == 0 and (hunger >= 30.0 or thirst >= 30.0)` | Migrate to adjacent cell in search of food/water, paying energy and fatigue. |

### 4.2 Detailed Action Specifications

#### 1. `AR_01_METABOLISM` (Priority 90)
* **Effects:**
  * `age_ticks += 1`
  * `energy -= basal_energy_cost * metabolic_rate` (scaled by $1.000000 \times \text{metabolic\_rate}$)
  * `biomass -= 0.100000` (tissue sloughing)
  * `PRODUCE_RESOURCE(pool="detritus", amount=0.100000)`
  * `hunger += base_hunger_growth * metabolic_rate` ($1.000000 \times \text{metabolic\_rate}$)
  * `thirst += base_thirst_growth` ($1.000000$)
  * `fatigue += base_fatigue_growth` ($0.500000$)
  * If `age_ticks >= maturity_age_ticks` ($50$) and `energy >= 100.0`: `reproduction_drive += base_reproduction_growth * fertility`
  * `action_taken = 0` (unlocks action execution for the current tick)

#### 2. `AR_02_MORTALITY` (Priority 85)
* **Precondition/Filter:** `energy <= 0.000000 or hunger >= 100.000000 or thirst >= 100.000000 or age_ticks >= longevity`.
* **Effects:**
  * `PRODUCE_RESOURCE(pool="detritus", amount=target.biomass)` (100% body mass recycles to soil organic pool)
  * `DESTROY_ENTITY(entity="target")` (Cascades removal from spatial index and relationships)

#### 3. `AR_03_DRINK` (Priority 80)
* **Preconditions:** Local environmental `soil_water >= 2.000000`.
* **Effects:**
  * `CONSUME_RESOURCE(pool="soil_water", amount=2.000000)`
  * `PRODUCE_RESOURCE(pool="soil_water", amount=2.000000)` (Instant physiological water throughput: water is utilized for cellular hydration and immediately returned to environmental moisture, conserving water mass with zero net accumulation of dry flesh)
  * `thirst = max(0.000000, thirst - 50.000000)`
  * `action_taken = 1`

#### 4. `AR_04_EAT` (Priority 70)
* **Candidate Finding (Capacity-Guarded):**
  * `FIND_ENTITY(collection_source="cell_entities", entity_type="autotroph", max_scan=4, limit=1)`
  * If autotroph found with `biomass >= 10.000000`:
    * Autotroph `biomass -= 10.000000`
    * Agent `biomass += 7.000000` (70% assimilation efficiency)
    * `PRODUCE_RESOURCE(pool="detritus", amount=3.000000)` (30% unassimilated excretion)
    * Agent `energy += 15.000000`
    * Agent `hunger = max(0.000000, hunger - 40.000000)`
    * `action_taken = 1`
  * Else fallback `FIND_ENTITY(collection_source="cell_entities", entity_type="herbivore", max_scan=4, limit=1)`:
    * If herbivore found with `biomass >= 20.000000`:
      * Herbivore `biomass -= 20.000000`
      * Agent `biomass += 14.000000` (70% assimilation efficiency)
      * `PRODUCE_RESOURCE(pool="detritus", amount=6.000000)` (30% excretion)
      * Agent `energy += 30.000000`
      * Agent `hunger = max(0.000000, hunger - 60.000000)`
      * `action_taken = 1`

#### 5. `AR_05_REPRODUCE` (Priority 60)
* **Mate Finding (Capacity-Guarded):**
  * Target is female (`sex == 0`).
  * `FIND_ENTITY(collection_source="cell_entities", entity_type="agent", max_scan=4, limit=1, filter: is_alive == 1 and sex == 1 and reproduction_drive >= 60.0 and energy >= 150.0 and biomass >= 60.0)`
  * If mate found:
    * Contributed biomass: $B_A = \lfloor \text{biomass}_A \times 0.25 \rfloor = 15.000000$, $B_B = \lfloor \text{biomass}_B \times 0.25 \rfloor = 15.000000$.
    * Contributed energy: $E_A = 25.000000$, $E_B = 25.000000$.
    * Deduct $B_A, E_A$ from Parent A; deduct $B_B, E_B$ from Parent B.
    * Reset Parent A `reproduction_drive = 0.000000`; Parent B `reproduction_drive = 0.000000`.
    * `CREATE_ENTITY(entity_type="agent", result_var="child", initial_properties={biomass: B_A + B_B, energy: E_A + E_B, is_alive: 1, age_ticks: 0, sex: RANDOM_INT(0, 1), generation: max(gen_A, gen_B) + 1, birth_tick: world.clock.current_tick, cell_x: target.cell_x, cell_y: target.cell_y, action_taken: 1})`
    * Inherit 5 genes via segregated coin-flip + mutation protocol (§3.1).
    * `ADD_RELATIONSHIP(source=target, target=child, rel_type="parent_of", weight=1)`
    * `ADD_RELATIONSHIP(source=mate, target=child, rel_type="parent_of", weight=1)`
    * `action_taken = 1`

#### 6. `AR_06_REST` (Priority 50)
* **Effects:**
  * `fatigue = max(0.000000, fatigue - 40.000000)`
  * `energy = min(max_energy, energy + 2.000000)`
  * `action_taken = 1`

#### 7. `AR_07_FORAGE_MOVE` (Priority 40)
* **Effects:**
  * Determine displacement $dx, dy \in [-\text{foraging\_range}, +\text{foraging\_range}]$ via rule PRNG.
  * `cell_x = target.cell_x + dx`, `cell_y = target.cell_y + dy` (simultaneous movement: staged and committed at rule pass boundary).
  * `energy -= 2.000000`
  * `fatigue += 5.000000`
  * `action_taken = 1`

---

## 5. Budget & Quota Analysis (100–300 Agents + Ecosystem)

The GENESIS substrate enforces two hard operational quotas per tick:
1. `max_operations_per_rule <= 256` per rule invocation.
2. `max_entities_touched_per_tick <= 1000` unique entities across all rules executed in a tick.

### 5.1 Entities Touched Analysis Across Scale

In GENESIS, unique entities touched are tracked via a tick-level `Set[int]`. Multiple reads or writes to the *same* entity across different rules count as only **1 unique entity touch** toward the 1,000 ceiling. However, inspecting candidate entities during target selection and `FIND_ENTITY` consumes touches.

#### 1. Entity Population Projections
| Scenario | Living Agents | Living Autotrophs | Living Herbivores | Living Decomposers | Total Living Entities |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **100 Agents** | 100 | 80 | 30 | 20 | **230 entities** |
| **200 Agents** | 200 | 120 | 50 | 30 | **400 entities** |
| **300 Agents** | 300 | 150 | 60 | 40 | **550 entities** |

#### 2. Candidate-Scanning Ceiling Guard (Effect Body vs Selector Filter)
In Phase 2b, high-density cells caused `target_selector.filter` to iterate over all cell entities, touching every single organism and exhausting operations. To eliminate this vulnerability:
* **Target Selector Limits:** Every agent rule uses a tight target selector limit:
  $$\text{target\_selector.limit} = 2 \text{ agents per cell per rule invocation}$$
* **Minimal Selector Filters:** The target selector filter checks only lightweight scalar flags: `is_alive == 1 and action_taken == 0`.
* **Bounded `FIND_ENTITY` Scanning:** All prey, mate, and partner lookups in effect bodies use strictly bounded parameters:
  $$\text{max\_scan} = 4, \quad \text{limit} = 1$$
  Even in a cell containing 50 entities, `FIND_ENTITY` inspects at most 4 entities before halting, guaranteeing at most 4 entity touches per invocation.

#### 3. Worst-Case Unique Touches per Tick Calculation
Across an active grid of 25 populated cells with 300 agents and 250 ecosystem organisms ($550$ total living entities):
* Routine processing (metabolism, mortality, feeding, moving) touches each living entity at most once during its target pass: $\le 550$ touches.
* `FIND_ENTITY` queries for prey/mates across 25 cells $\times 2$ invocations $\times 4$ candidate inspections: $\le 200$ touches.
* Worst-case unique entities touched across the entire tick:
  $$\text{Total Touched}_{\text{worst}} \le 550 + 200 = 750 \text{ entities} \le 1000 \quad (\mathbf{75\% \text{ of quota, safely within margin}})$$

### 5.2 Operation Budget per Rule Invocation ($\le 256$ Ops)

| Rule ID | Base AST Evaluation Ops | Target Candidate Checks ($\le 2$) | Effect Body Ops | Worst-Case Total Ops | Margin vs 256 Cap |
| :--- | :---: | :---: | :---: | :---: | :---: |
| `AR_01_METABOLISM` | 1 | 2 candidates $\times 3$ ops = 6 | 12 property ops = 12 | **19 ops** | 92.6% headroom |
| `AR_02_MORTALITY` | 1 | 2 candidates $\times 4$ ops = 8 | 2 effects (detritus, destroy) = 4 | **13 ops** | 94.9% headroom |
| `AR_03_DRINK` | 1 | 2 candidates $\times 5$ ops = 10 | 4 effects (res, prop, mutex) = 8 | **19 ops** | 92.6% headroom |
| `AR_04_EAT` | 1 | 2 candidates $\times 5$ ops = 10 | `FIND_ENTITY` (12) + 6 effects (14) = 26 | **37 ops** | 85.5% headroom |
| `AR_05_REPRODUCE` | 1 | 2 candidates $\times 6$ ops = 12 | Mate scan (12) + Create (15) + 5 Loci (65) + Edges (4) = 96 | **109 ops** | 57.4% headroom |
| `AR_06_REST` | 1 | 2 candidates $\times 3$ ops = 6 | 3 property ops = 6 | **13 ops** | 94.9% headroom |
| `AR_07_FORAGE_MOVE` | 1 | 2 candidates $\times 4$ ops = 8 | Random draw (4) + position (6) + costs (4) = 14 | **23 ops** | 91.0% headroom |

Every single agent rule operates comfortably within the 256 operations ceiling, with the most complex rule (`AR_05_REPRODUCE`) consuming at most $109$ operations ($42.6\%$ of budget).

---

## 6. Mass Conservation & Full System Mass Ledger

Total closed-system mass across the artificial world is formally defined as:
$$M_{\text{closed}} = \sum_{e \in \text{Entities}} (\text{biomass}_e) + \text{detritus} + \text{soil\_minerals} + \text{soil\_water} \equiv M_{\text{initial}}$$

Every agent interaction strictly obeys the mass conservation invariant down to $10^{-6}$ integer precision ($\pm 0.000000$ deviation):

| Transformation / Action | Inputs | Outputs | Net Mass Change ($\Delta M$) | Conservation Verification |
| :--- | :--- | :--- | :---: | :--- |
| **Agent Metabolism (`AR_01`)** | Agent biomass: $-0.100000$ | `detritus`: $+0.100000$ | **0.000000** | Sloughed cellular mass transfers 1:1 to soil organic sink. |
| **Agent Mortality (`AR_02`)** | Agent biomass: $-M_{\text{body}}$ | `detritus`: $+M_{\text{body}}$ | **0.000000** | 100% of corpse recycled to detritus. Entity destroyed. |
| **Agent Drinking (`AR_03`)** | `soil_water`: $-2.000000$ | `soil_water`: $+2.000000$ | **0.000000** | Environmental water flush for hydration. Zero dry mass gain. |
| **Herbivory Feeding (`AR_04`)** | Autotroph biomass: $-10.000000$ | Agent biomass: $+7.000000$<br/>`detritus`: $+3.000000$ | **0.000000** | 70% assimilation efficiency, 30% digestive excretion. |
| **Carnivory Feeding (`AR_04`)** | Herbivore biomass: $-20.000000$ | Agent biomass: $+14.000000$<br/>`detritus`: $+6.000000$ | **0.000000** | 70% assimilation efficiency, 30% digestive excretion. |
| **Sexual Reproduction (`AR_05`)** | Parent A biomass: $-15.000000$<br/>Parent B biomass: $-15.000000$ | Child biomass: $+30.000000$ | **0.000000** | Offspring body mass drawn exactly 1:1 from parental tissue. |
| **Foraging Movement (`AR_07`)** | Position change | Position change | **0.000000** | Pure spatial translation; zero mass consumed or produced. |

---

## 7. Pre-Registered Emergence Binding

The `genesis/analysis/binding.py` interface maps simulation data to emergence measurement algorithms without domain hardcoding. For Phase 3, the binding is specified as:

```python
AnalysisBinding(
    agent_entity_types=("agent",),
    pos_x_prop="cell_x",
    pos_y_prop="cell_y",
    alive_prop="is_alive",
    parent_edge_kind="parent_of",
    cooperation_edge_kinds=(),           # Empty: no social cooperation edges in Phase 3
    cooperation_event_types=(),          # Empty: no cooperation journal events in Phase 3
    practice_property="farming_technique",# Placeholder: no practices in Phase 3
    adoption_event_type="practice_adopted",
    stockpile_resource_property=None,
    resource_landscape_property="soil_water"
)
```

### Applicability of Emergence Measures in Phase 3
* **Settlement Emergence (`evaluate_settlement_emergence`):** **APPLICABLE**. Measures spatial clustering, 5-year temporal persistence, generational anchoring (via `birth_tick` and `parent_of` genealogy), and resource-weighted oasis controls. Provides a quantitative baseline for agent aggregation.
* **Group Emergence (`evaluate_group_emergence`):** **NOT APPLICABLE IN PHASE 3**. Phase 3 agents do not possess economic exchange, alliances, or institutional roles. Attempting group analysis correctly returns early-exit failures (`"No interaction graph edges found"`), serving as a negative control.
* **Cultural Spread Emergence (`evaluate_cultural_spread`):** **NOT APPLICABLE IN PHASE 3**. Phase 3 agents do not possess transmission of practices, traditions, or memes. Attempting cultural analysis correctly returns early-exit failures (`"Zero adoption events"`), serving as a negative control.

---

## 8. Pre-Registered Parameter Specification (`agents_params_v1.json`)

The canonical parameters file is located at `genesis/agents/data/agents_params_v1.json`. Its SHA-256 hash is pinned to:
$$\mathbf{93dd537e3cf571113b0247315eb90ffa63542caab9d0a8308876e8fa3769a9d5}$$

| Parameter Name | Category | Default Value | Unit / Scale | Scientific Rationale |
| :--- | :--- | :--- | :--- | :--- |
| `initial_biomass` | Schema | `"40.000000"` | FixedPoint | Baseline adult organism somatic mass. |
| `max_biomass` | Schema | `"500.000000"` | FixedPoint | Somatic tissue growth upper bound. |
| `initial_energy` | Schema | `"100.000000"` | FixedPoint | Energy reservoir buffer preventing immediate tick-1 death. |
| `max_energy` | Schema | `"1000.000000"` | FixedPoint | Caloric saturation ceiling. |
| `basal_energy_cost` | Metabolism | `"1.000000"` | FixedPoint / tick | Basal respiration required to maintain homeostasis. |
| `basal_biomass_slough` | Metabolism | `"0.100000"` | FixedPoint / tick | Continuous cellular wear and sloughing into detritus. |
| `base_hunger_growth` | Needs | `"1.000000"` | FixedPoint / tick | Caloric demand increment, modulated by `metabolic_rate`. |
| `base_thirst_growth` | Needs | `"1.000000"` | FixedPoint / tick | Hydration demand increment (reaches 100 in 100 ticks without water). |
| `base_fatigue_growth` | Needs | `"0.500000"` | FixedPoint / tick | Neuromuscular exhaustion accumulation. |
| `base_reproduction_growth` | Needs | `"0.500000"` | FixedPoint / tick | Gametic pressure accumulation rate when well-fed. |
| `maturity_age_ticks` | Needs | `50` | INT64 ticks | Post-natal juvenile period before reproductive maturity. |
| `hunger_trigger_threshold` | Behavior | `"30.000000"` | FixedPoint | Hunger level activating feeding action preference. |
| `thirst_trigger_threshold` | Behavior | `"30.000000"` | FixedPoint | Thirst level activating drinking action preference. |
| `fatigue_trigger_threshold` | Behavior | `"50.000000"` | FixedPoint | Fatigue level activating resting action preference. |
| `reproduction_drive_threshold`| Behavior | `"60.000000"` | FixedPoint | Gametic urge required to seek mate and initiate fission/birth. |
| `starvation_hunger_threshold` | Mortality | `"100.000000"` | FixedPoint | Critical hunger causing fatal starvation. |
| `dehydration_thirst_threshold`| Mortality | `"100.000000"` | FixedPoint | Critical thirst causing fatal dehydration. |
| `reproduction_min_energy` | Reproduction | `"150.000000"` | FixedPoint | Minimum energy required to withstand reproductive energy contribution. |
| `reproduction_min_biomass`| Reproduction | `"60.000000"` | FixedPoint | Minimum biomass required to split body mass for offspring. |
| `eat_autotroph_intake_mass` | Feeding | `"10.000000"` | FixedPoint | Biomass consumed per plant-grazing event. |
| `eat_autotroph_efficiency` | Feeding | `"0.700000"` | Ratio | Assimilation fraction into agent biomass (70% body, 30% waste). |
| `eat_autotroph_energy_yield`| Feeding | `"15.000000"` | FixedPoint | Net metabolic energy extracted from grazing. |
| `eat_herbivore_intake_mass` | Feeding | `"20.000000"` | FixedPoint | Biomass consumed per prey hunting event. |
| `eat_herbivore_efficiency` | Feeding | `"0.700000"` | Ratio | Assimilation fraction into agent biomass. |
| `eat_herbivore_energy_yield`| Feeding | `"30.000000"` | FixedPoint | Net metabolic energy extracted from predation. |
| `drink_water_intake` | Drinking | `"2.000000"` | FixedPoint | Moisture flushed through system per drinking event. |
| `thirst_satisfaction` | Drinking | `"50.000000"` | FixedPoint | Thirst reduction per drinking event. |
| `rest_fatigue_recovery` | Resting | `"40.000000"` | FixedPoint | Fatigue reduction per resting tick. |
| `rest_energy_recovery` | Resting | `"2.000000"` | FixedPoint | Passive metabolic energy recovery during rest. |
| `forage_move_fatigue_cost` | Locomotion | `"5.000000"` | FixedPoint | Exertion cost of traversing spatial grid cells. |
| `forage_move_energy_cost` | Locomotion | `"2.000000"` | FixedPoint | Caloric locomotion cost. |
| `locus_count` | Genetics | `5` | Integer | Fixed number of heritable genetic loci. |
| `mutation_rate_per_thousand`| Genetics | `10` | 1/1000 | 1.0% per-locus point mutation probability per generation. |
| `mutation_max_step` | Genetics | `5` | Integer | Maximum allele perturbation step under mutation. |
| `target_selector_limit` | Quota | `2` | Entities / cell | Per-invocation target count preventing candidate scanning storms. |
| `find_entity_max_scan` | Quota | `4` | Entities / search | Bounded candidate search ceiling for prey and mates. |
| `find_entity_limit` | Quota | `1` | Entities / search | Single entity returned per lookup. |

---

## 9. Pre-Registered Acceptance Criteria (Stage 1)

All acceptance criteria are pre-registered prior to running simulations. Thresholds cannot be retroactively relaxed.

### TEST-301: Determinism & Hash Reproducibility
* **Docstring:** Identical seed produces bit-identical state hashes, journal hashes, and PRNG step counts across separate runs and across state save/reload.
* **Criterion:**
  * Run 1 and Run 2 from seed `42` over $500$ ticks must have identical `world.get_state_hash()` and `world.event_journal.last_hash`.
  * Serializing state at tick $250$, reloading into a fresh `WorldState`, and running to tick $500$ must produce the exact same final hash.

### TEST-302: Exact Mass Conservation Under Full Life Cycle
* **Docstring:** Closed-system mass remains constant down to $\pm 0.000000$ FixedPoint tolerance over at least 1,000 ticks with agents feeding, reproducing, sloughing tissue, and dying.
* **Criterion:**
  $$\left| M_{\text{closed}}(t) - M_{\text{closed}}(0) \right| == 0.000000 \quad \forall t \in [1, 1000]$$

### TEST-303: Zero Quota Failures Over 100-Year Multi-Scale Runs
* **Docstring:** Zero `QuotaExceededError` occurrences over 100-year (36,500-tick) runs at 100, 200, and 300 agent populations.
* **Criterion:** Quota violations $== 0$. Operations per rule $\le 256$, unique entities touched per tick $\le 1000$.

### TEST-304: Physiological Needs Bounded Dynamics & Mortality
* **Docstring:** Starved or dehydrated agents die within pre-registered tick bounds; fed/hydrated agents survive with oscillating needs.
* **Criterion:**
  * An agent isolated with zero food and water dies within $[95, 105]$ ticks (since hunger and thirst grow at $1.000000$/tick, hitting $100.0$ at tick 100).
  * A nourished agent survives $> 500$ ticks with hunger and thirst oscillating within $[0.000000, 70.000000]$ without runaway upward drift.

### TEST-305: Mendelian Inheritance & Genetic Mutation Bounds
* **Docstring:** Alleles segregate from known parents matching a 50/50 binomial distribution; with mutation rate zero, 100% of offspring alleles match one parent; with positive mutation, traits remain strictly bounded.
* **Criterion:**
  * With $\mu = 0$ across $50$ offspring, Parent A allele frequency is within $[35\%, 65\%]$ ($p \approx 0.50$), and zero foreign alleles appear.
  * With $\mu = 10/1000$ over $10$ generations, $100\%$ of expressed traits satisfy $\text{min}_k \le \text{trait}_k \le \text{max}_k$.

### TEST-306: Resource-Bound Selection Pressure
* **Docstring:** In a resource-scarce environment with limited food, agents with lower metabolic rate outlive and out-reproduce high-metabolic-rate competitors.
* **Pre-Registered Direction:**
  * Two variants initialized: Variant E (Efficient, $\text{metabolic\_rate} = 0.500000$) vs. Variant P (Profligate, $\text{metabolic\_rate} = 1.800000$).
  * In a scarce world with restricted autotroph replenishment ($20\%$ normal solar flux), Variant E must comprise $> 75\%$ of the surviving agent population by tick $500$.

### TEST-307: Resource-Bound Carrying Capacity Equilibrium
* **Docstring:** Agent population levels off and establishes equilibrium dictated by available environmental biomass and water, rather than artificial throughput caps.
* **Criterion:** In a closed environment with finite autotroph replenishment, agent population reaches a steady plateau with variance $\le \pm 15\%$ over a $200$-tick window.

### TEST-308: Read-Only Emergence Measurement Invariance
* **Docstring:** Executing `evaluate_settlement_emergence`, `evaluate_group_emergence`, and `evaluate_cultural_spread` leaves world state hash, journal hash, and PRNG step count byte-identical.
* **Criterion:**
  $$\text{Hash}_{\text{after}} == \text{Hash}_{\text{before}}, \quad \text{Journal}_{\text{after}} == \text{Journal}_{\text{before}}, \quad \text{PRNG\_Steps}_{\text{after}} == \text{PRNG\_Steps}_{\text{before}}$$

### TEST-309: Negative Control: Trait Drift Invariance
* **Docstring:** With mutation rate zero and uniform initial traits, heritable traits exhibit zero variance across 10 generations.
* **Criterion:** $\text{Var}(\text{trait}_k) == 0.000000$ for all loci $k$ across all living descendants at generation $\ge 5$.

### TEST-310: Regression Guard
* **Docstring:** All 126 pre-existing tests (Phases 0, 1, 2, and emergence definitions v1) continue to pass without modification.
* **Criterion:** $126 / 126$ tests pass cleanly on both Windows and Linux CI.

---

## 10. Numbered List of Judgment Calls

### 1. Representation of the Genome: Separate Integer Properties vs. Packed Bytearray
* **Alternative Considered:** Packing 5 loci into a single 64-bit integer bitfield (e.g. 8 bits per gene) or an array property.
* **Recommendation:** **Separate integer properties (`gene_metabolic_rate`, `gene_foraging_range`, etc.)**. The substrate `PropertyType` does not support arrays, and bitwise manipulation is not supported in GRL `BINARY_OPS`. Dedicated integer properties allow direct GRL arithmetic, independent min/max schema constraints, and transparent inspection in event journals and state hashes.

### 2. Water Balance: Dry Biomass Uptake vs. Instant Fluid Throughput
* **Alternative Considered:** Converting consumed water into agent `biomass`, requiring an explicit urination rule to excrete water back to `soil_water`.
* **Recommendation:** **Instant fluid throughput (`CONSUME_RESOURCE(soil_water, 2.0)` + `PRODUCE_RESOURCE(soil_water, 2.0)`)**. Quenches thirst and checks environmental water availability while preventing artificial body mass ballooning. All somatic mass remains organic dry tissue governed by carbon/biomass ingestion.

### 3. Action Selection: Complex Behavioral Trees vs. Priority-Tiered Mutex Rules
* **Alternative Considered:** Multi-action tick evaluation where an agent can simultaneously eat, forage, and reproduce in the same tick.
* **Recommendation:** **Single-action mutex (`action_taken`) with strict priority tiers**. Biologically realistic (an organism cannot forage to a new cell and sleep simultaneously), prevents combinatorial entity touches, and guarantees deterministic execution without planning stubs.

### 4. Mate Selection: Symmetric Bi-Directional Search vs. Female-Initiated Reproduction
* **Alternative Considered:** Both sexes initiate reproduction independently, risking duplicate child creation or race conditions in the same tick.
* **Recommendation:** **Female-initiated reproduction (`sex == 0` initiates `AR_05`)**. The female agent scans for a co-located mature male (`sex == 1`). Both parents contribute biomass and energy, and both have reproduction drives reset. Eliminates race conditions and halves reproduction rule evaluation overhead.

### 5. Mutation Distribution: Uniform Bounded Jitter vs. Gaussian Integer Draw
* **Alternative Considered:** Box-Muller Gaussian integer rounding.
* **Recommendation:** **Uniform bounded integer jitter (`RANDOM_INT(-5, +5)`)**. Gaussian approximation requires floating-point math or complex integer rejection sampling. Uniform bounded jitter is exact, deterministic, trivially constrained to schema bounds, and computationally lightweight.

---

## 11. Three Weakest Points of the Design

1. **Local-Cell Mate Finding in Depopulated Worlds:**
   Because `AR_05_REPRODUCE` searches for a mate strictly within the same spatial cell $(c_x, c_y)$ using `FIND_ENTITY` with `collection_source="cell_entities"`, if agents disperse widely across a large grid, reproduction rates may plummet to zero due to failure to meet in the same cell. In Phase 3 tests, spatial dimensions will be appropriately sized ($10 \times 10$ or $20 \times 20$) to maintain viable encounter density.
2. **Simplified Fluid Dynamics (Closed Water Throughput):**
   Modeling drinking as instant equal consume/produce on `soil_water` ensures perfect zero-tolerance mass conservation without tracking hydration mass inside body tissues. However, this means water availability is checked only as an environmental gate rather than as an internal physical mass reservoir.
3. **Absence of Kin Avoidance in Mate Selection:**
   Phase 3 contains no cultural or social memory, meaning agents do not inspect kinship relationships prior to mating. Close-kin inbreeding (e.g. brother-sister or parent-child mating) is possible if they share a cell. This is biologically plausible for primitive bootstrap organisms and will be refined in Phase 4 when memory and social relationships are authored.

---

## 12. Human Review Gate

Stage 1 is complete. No rules, loaders, or tests have been implemented.

**Approve agents design v1 and proceed to Stage 2?**
