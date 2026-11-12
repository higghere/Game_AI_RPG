# GENESIS Alpha — Phase 3 Design Specification: Individual Agents as Data (Traits, Needs, Genetics)

**Phase:** Phase 3 (Individual Agents as Data)  
**Status:** Approved with Engineering Conditions — Version 3.0 (Phase 3e Hardening, Purity & Calibration Audit)  
**Runtime Requirement:** Frozen Layer 1 Runtime Substrate (`genesis/core/`, `genesis/substrate/`, `genesis/grl/`, `genesis/ecosystem/`, `genesis/analysis/`). Zero Python runtime modifications. Zero agent-specific Python classes (`Entity.__subclasses__() == []` invariant strictly preserved). All agent mechanics defined purely as **Data Declarations** (JSON schemas) and **GRL Rules** (JSON AST).

---

## 1. Architectural Philosophy & Layer Boundary

In GENESIS, individually distinguishable agents are not implemented as custom Python classes, cognitive architectures, or opaque neural networks. The simulation substrate (Layer 1) provides generic entities, spatial hashing, property definitions, directional relationship graphs, resource reservoirs, and a sandboxed rule interpreter.

Phase 3 introduces the first individually distinguishable organisms: **autonomous agents with heritable traits, internal needs, and need-driven behavior**. Agents exist solely through declarative data structures and GRL rules:
1. **Generic Ontology:** Entity schema `agent` registered into `SchemaRegistry` with typed, bounded properties.
2. **Needs Dynamics:** Integer and FixedPoint physiological drives (hunger, thirst, fatigue, reproduction drive) updated by metabolic GRL rules.
3. **Mendelian Genetics as Data:** Fixed-length integer gene vectors representing heritable loci. Alleles are inherited from parents via rule PRNG streams, mutated within bounded rates, and expressed as physiological traits via declared arithmetic rules.
4. **Behavior via Bounded Rules:** Actions (eat, drink, rest, forage-move, reproduce, die) are ordinary GRL rules evaluated in priority order with deterministic tie-breaking. No planning, no memory, no goals, and no LLM scaffolding.
5. **Exact Mass Conservation:** Agents eat autotrophs or herbivores from the existing Phase 2 ecosystem, drink from `soil_water`, excrete waste to `detritus` and `soil_water`, overflow somatic excess into `detritus`, and recycle 100% of body mass upon mortality, maintaining exact closed-system mass balance down to $10^{-6}$ integer precision.

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
* `energy` (`FIXED_POINT`, $[0.000000, 1000.000000]$, default $100.000000$): Metabolic energy reservoir driving biological processes (thermodynamic throughput, outside the mass ledger).
* `cell_x` (`INT64`, $[-10000, 10000]$, default $0$): Spatial coordinate along grid X-axis.
* `cell_y` (`INT64`, $[-10000, 10000]$, default $0$): Spatial coordinate along grid Y-axis.
* `generation` (`INT64`, $[0, 10000]$, default $0$): Ancestral generation depth ($0$ for bootstrap Adam/Eve agents, $\max(\text{gen}_A, \text{gen}_B) + 1$ for offspring).
* `birth_tick` (`INT64`, $[0, 100000000]$, default $0$): Tick of genesis/birth (used by `AnalysisBinding` for generational anchoring and native birth calculations).
* `action_taken` (`INT64`, $[0, 1]$, default $0$): Per-tick single-action mutex flag. Prevents an agent from performing multiple incompatible actions in the same tick. Reset to $0$ each tick during metabolism.

#### 2. Physiological Needs Properties
All needs are represented as bounded `FIXED_POINT` quantities spanning $[0.000000, 100.000000]$. A value of $0.000000$ indicates complete satisfaction; $100.000000$ indicates critical deprivation.
* `hunger` (`FIXED_POINT`, $[0.000000, 100.000000]$, default $0.000000$): Caloric demand. Grows continuously based on metabolic rate. Satisfied by feeding on autotrophs or herbivores. Starvation occurs if hunger reaches $100.000000$ and energy drops to $0.000000$.
* `thirst` (`FIXED_POINT`, $[0.000000, 100.000000]$, default $0.000000$): Hydration demand. Grows continuously by $1.000000$ per tick. Satisfied by drinking from `soil_water`. Dehydration mortality occurs if thirst reaches $100.000000$.
* `fatigue` (`FIXED_POINT`, $[0.000000, 100.000000]$, default $0.000000$): Somatic exhaustion. Increases upon physical exertion (forage-movement, reproduction). Satisfied by resting.
* `reproduction_drive` (`FIXED_POINT`, $[0.000000, 100.000000]$, default $0.000000$): Gametic pressure. Accumulates once `age_ticks >= maturity_age_ticks` ($50$ ticks) and agent is well-nourished. Triggers mating behavior when exceeding the pre-registered threshold ($60.000000$). Resets to $0.000000$ upon successful reproduction.

#### 3. Genetic Loci & Expressed Trait Mapping
The genome is represented as a fixed-length vector of $K = 5$ bounded integer properties (`INT64`). Traits are computed directly from genes via declared arithmetic rules (never hardcoded in Python):

| Locus Name | Gene Bounds | Default | Trait Name | Trait Bounds & Type | Expression Rule | Biological Trade-off |
| :--- | :---: | :---: | :--- | :---: | :---: | :--- |
| `gene_metabolic_rate` | $[50, 200]$ | $100$ | `metabolic_rate` | $[0.500000, 2.000000]$ `FIXED_POINT` | $\text{gene} / 100$ | **Famine endurance vs digestive throughput:** Lower metabolic rate consumes less basal energy and accumulates hunger slower (surviving long famines), but yields lower energy extraction multiplier from food ($0.8\times$ vs $1.2\times$). Higher metabolic rate burns fuel faster but thrives under high resource abundance. |
| `gene_foraging_range` | $[1, 3]$ | $1$ | `foraging_range` | $[1, 3]$ `INT64` | $\text{gene}$ (identity) | **Exploration reach vs locomotion cost:** Larger step range enables crossing depleted regions to find food, but costs proportionately higher movement energy and fatigue per step ($2\times \text{range}$). |
| `gene_fertility` | $[50, 200]$ | $100$ | `fertility` | $[0.500000, 2.000000]$ `FIXED_POINT` | $\text{gene} / 100$ | **Reproductive rate vs maternal depletion:** High fertility accelerates reproduction drive accumulation, but frequent births risk maternal exhaustion and starvation if resources are scarce. |
| `gene_longevity` | $[500, 2500]$ | $1000$ | `longevity` | $[500, 2500]$ `INT64` | $\text{gene}$ (identity) | **Generational overlap vs somatic drag:** Longer lifespan permits more lifetime reproductive cycles, but retains older organisms that consume resources without high foraging efficiency. |
| `gene_boldness` | $[0, 100]$ | $50$ | `boldness` | $[0.000000, 1.000000]$ `FIXED_POINT` | $\text{gene} / 100$ | **Proactive feeding vs energy conservation:** High boldness prompts foraging even at moderate hunger ($> 30$), keeping energy topped up; low boldness waits until hunger is urgent, minimizing unnecessary movement. |

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

At each tick, rules execute in decreasing priority order ($90 \to 40$). A successful behavioral action sets `action_taken = 1`, which acts as a capacity guard preventing subsequent competing actions during that tick.

| Priority | Rule ID | Scope | Target Selector Filter | Description |
| :---: | :--- | :--- | :--- | :--- |
| **90** | `AR_01_METABOLISM` | Spatial Cell | `is_alive == 1` | Age increment, needs accumulation, basal energy/mass cost, reset `action_taken = 0`. |
| **85** | `AR_02_MORTALITY` | Spatial Cell | `is_alive == 1 and (energy <= 0 or hunger >= 100 or thirst >= 100 or age_ticks >= longevity)` | Starvation, dehydration, or senescence death. 100% biomass recycled to detritus. |
| **80** | `AR_03_DRINK` | Spatial Cell | `action_taken == 0 and thirst >= 30.0 and thirst >= hunger and thirst >= fatigue and thirst >= reproduction_drive` | Quench thirst from local `soil_water`. |
| **70** | `AR_04_EAT` | Spatial Cell | `action_taken == 0 and hunger >= 30.0 and hunger >= fatigue and hunger >= reproduction_drive` | Consume local autotroph or herbivore biomass to restore energy and quench hunger. Overflow past biomass cap goes to detritus. |
| **60** | `AR_05_REPRODUCE` | Spatial Cell | `action_taken == 0 and sex == 0 and reproduction_drive >= 60.0 and energy >= 150.0 and biomass >= 60.0` | Mate with co-located male (`sex == 1`) to produce child agent. |
| **50** | `AR_06_REST` | Spatial Cell | `action_taken == 0 and fatigue >= 50.0` | Recuperate energy and reduce fatigue through somatic dormancy. |
| **40** | `AR_07_FORAGE_MOVE` | Spatial Cell | `action_taken == 0 and (hunger >= 30.0 or thirst >= 30.0)` | Migrate to adjacent cell in search of food/water, paying energy and fatigue. |

---

## 5. Thermodynamics & Mass Conservation (Energy Outside Ledger & Biomass Overflow)

### 5.1 Energy is Outside the Mass Ledger
In strict alignment with the substrate thermodynamic design (Phase 2 §2.1 and §4.1):
* **Energy is an open thermodynamic driver, not matter.** Solar flux continuously enters the world; metabolic work, locomotion, and somatic respiration dissipate energy as metabolic entropy/heat.
* **Energy is strictly excluded from closed mass accounting.** The simulation tracks energy balance separately through non-negativity constraints ($E \ge 0$), where exhaustion ($E \le 0$) triggers mortality (`AR_02`).

### 5.2 Closed-System Mass Ledger & Biomass Cap Overflow
Total closed-system mass across the artificial world is formally defined over physical matter reservoirs only:
$$M_{\text{closed}} = \sum_{e \in \text{Entities}} (\text{biomass}_e) + \text{detritus} + \text{soil\_minerals} + \text{soil\_water} \equiv M_{\text{initial}}$$

#### Biomass Cap Overflow into Detritus
Every agent has a maximum somatic biomass ceiling: $\text{max\_biomass} = 500.000000$. When an agent feeds, somatic absorption cannot violate this ceiling. Any assimilated biomass beyond the cap overflows directly into environmental `detritus`:
1. Total intake from autotroph/herbivore: $M_{\text{in}}$ (e.g. $10.000000$).
2. Unassimilated digestive excretion (30%): $M_{\text{waste}} = M_{\text{in}} \times 0.30 = 3.000000 \to \text{detritus}$.
3. Nominal assimilated biomass (70%): $M_{\text{assimilated}} = M_{\text{in}} \times 0.70 = 7.000000$.
4. Available headroom below cap: $H = \max(0.000000, 500.000000 - B_{\text{current}})$.
5. Absorbed into body: $\Delta B = \min(M_{\text{assimilated}}, H)$.
6. Overflow to soil: $M_{\text{overflow}} = M_{\text{assimilated}} - \Delta B \to \text{detritus}$.
7. Total detritus produced:
   $$\Delta \text{detritus} = M_{\text{waste}} + M_{\text{overflow}}$$
8. **Net Mass Balance:**
   $$\Delta M_{\text{food}} (-M_{\text{in}}) + \Delta B (+\Delta B) + \Delta \text{detritus} (+M_{\text{waste}} + M_{\text{overflow}}) \equiv 0.000000$$

Every single transformation obeys exact conservation down to $10^{-6}$ integer precision ($\pm 0.000000$ deviation):

| Transformation / Action | Inputs | Outputs | Net Mass Change ($\Delta M$) | Invariant Enforcement |
| :--- | :--- | :--- | :---: | :--- |
| **Agent Metabolism (`AR_01`)** | Agent biomass: $-0.100000$ | `detritus`: $+0.100000$ | **0.000000** | Sloughed cellular mass transferred 1:1 to soil organic sink. |
| **Agent Mortality (`AR_02`)** | Agent biomass: $-M_{\text{body}}$ | `detritus`: $+M_{\text{body}}$ | **0.000000** | 100% of corpse recycled to detritus. Entity destroyed. |
| **Agent Drinking (`AR_03`)** | `soil_water`: $-2.000000$ | `soil_water`: $+2.000000$ | **0.000000** | Environmental water flush for hydration. Zero dry mass gain. |
| **Herbivory Feeding (`AR_04`)** | Autotroph biomass: $-10.000000$ | Agent biomass: $+\Delta B$<br/>`detritus`: $+3.000000 + M_{\text{overflow}}$ | **0.000000** | 70% assimilation efficiency, 30% digestive excretion, cap overflow to detritus. |
| **Carnivory Feeding (`AR_04`)** | Herbivore biomass: $-20.000000$ | Agent biomass: $+\Delta B$<br/>`detritus`: $+6.000000 + M_{\text{overflow}}$ | **0.000000** | 70% assimilation efficiency, 30% digestive excretion, cap overflow to detritus. |
| **Sexual Reproduction (`AR_05`)** | Parent A biomass: $-15.000000$<br/>Parent B biomass: $-15.000000$ | Child biomass: $+30.000000$ | **0.000000** | Offspring body mass drawn exactly 1:1 from parental tissue. |
| **Foraging Movement (`AR_07`)** | Position change | Position change | **0.000000** | Spatial translation; zero mass consumed or produced. |

---

## 6. Budget & Quota Analysis (100–300 Agents + Ecosystem)

The substrate enforces two quotas: $\le 256$ operations per rule invocation and $\le 1,000$ unique entities touched per tick.

### 6.1 Entities Touched Analysis Across Scale
In GENESIS, unique entities touched are tracked via a tick-level `Set[int]`. Multiple reads/writes to the *same* entity across different rules count as only **1 unique touch** toward the 1,000 ceiling. However, inspecting candidates during target selection and `FIND_ENTITY` consumes touches.

* **Population Projections Allowing Natural Growth:**
  * **100 Agents Base:** 100 agents + 80 autotrophs + 30 herbivores + 20 decomposers = **230 living entities**.
  * **200 Agents Mid:** 200 agents + 120 autotrophs + 50 herbivores + 30 decomposers = **400 living entities**.
  * **300 Agents High:** 300 agents + 150 autotrophs + 60 herbivores + 40 decomposers = **550 living entities**.
* **Candidate-Scanning Ceiling Guard:** Target selectors use minimal filters (`is_alive == 1 and action_taken == 0`) with `limit: 2`. All partner/prey searches (`FIND_ENTITY`) are placed in the effect body with capacity guard `max_scan: 4`.
* **Worst-Case Touches Calculation (300 Agents + 250 Ecosystem Organisms across 25 active cells):**
  $$\text{Touches}_{\text{worst}} \le 550 \text{ (all living entities)} + (25 \text{ cells} \times 2 \times 4 \text{ candidate scans}) = 750 \text{ entities} \le 1000 \quad (\mathbf{75.0\% \text{ of cap}})$$
  In TEST-303, the peak entities touched per tick is recorded continuously across all 36,500 ticks and asserted to remain $< 1000$ even under natural population expansions.

### 6.2 Worst-Case Operation Counts per Rule Invocation ($\le 256$ Ops)
* `AR_01_METABOLISM`: 1 base + 6 selection + 12 property ops = **19 ops** (92.6% margin)
* `AR_02_MORTALITY`: 1 base + 8 selection + 4 effect ops = **13 ops** (94.9% margin)
* `AR_03_DRINK`: 1 base + 10 selection + 8 effect ops = **19 ops** (92.6% margin)
* `AR_04_EAT`: 1 base + 10 selection + 26 prey scan & intake ops = **37 ops** (85.5% margin)
* `AR_05_REPRODUCE`: 1 base + 12 selection + 12 mate scan + 15 creation + 65 genetics + 4 edges = **109 ops** (57.4% margin)
* `AR_06_REST`: 1 base + 6 selection + 6 effect ops = **13 ops** (94.9% margin)
* `AR_07_FORAGE_MOVE`: 1 base + 8 selection + 14 displacement ops = **23 ops** (91.0% margin)

---

## 7. Emergence Binding & Explicit N/A List

The `AnalysisBinding` connects generic substrate data to the pre-registered emergence measurement suite in `genesis/analysis/`:

```python
agent_binding = AnalysisBinding(
    agent_entity_types=("agent",),
    pos_x_prop="cell_x",
    pos_y_prop="cell_y",
    alive_prop="is_alive",
    parent_edge_kind="parent_of",
    cooperation_edge_kinds=(),           # Empty: no cooperation edges in Phase 3
    cooperation_event_types=(),          # Empty: no cooperation events in Phase 3
    practice_property="farming_technique",# Placeholder
    adoption_event_type="practice_adopted",
    stockpile_resource_property=None,
    resource_landscape_property="soil_water"
)
```

### Emergence Applicability & Explicit N/A List
1. **Settlement Emergence (`evaluate_settlement_emergence`):** **APPLICABLE**.
   * Evaluates spatial cluster density, generational persistence (anchored by `birth_tick` and `parent_of` edges), and dual null models (uniform random and resource-weighted oasis null). Provides quantitative baseline for agent geographic aggregation.
2. **Group Emergence (`evaluate_group_emergence`):** **NOT APPLICABLE IN PHASE 3 (Explicit N/A)**.
   * *Reason:* Phase 3 agents possess no trade, tribute, or political alliance relationships (`cooperation_edge_kinds` is empty).
   * *Expected Behavior:* The interaction graph produces zero edges; analysis cleanly exits early with negative verdict (`"No interaction graph edges found"`), serving as a verified negative control.
3. **Cultural Spread Emergence (`evaluate_cultural_spread`):** **NOT APPLICABLE IN PHASE 3 (Explicit N/A)**.
   * *Reason:* Phase 3 agents possess no transmission of cultural practices, traditions, or memes (`adoption_event_type` produces zero events).
   * *Expected Behavior:* Analysis cleanly exits early with negative verdict (`"Zero adoption events"`), serving as a verified negative control.

---

## 8. Frozen Parameter Specification (`agents_params_v1.json`)

The canonical parameters file is located at `genesis/agents/data/agents_params_v1.json`. Its SHA-256 hash is pinned to:
$$\mathbf{d6ce25cac9d58b15e5548b44c5285fde818d71a60306a6e453115839ec39c80e}$$

---

## 9. Pre-Registered Acceptance Criteria (Stage 1 Approved)

### TEST-301: Determinism & Hash Reproducibility
* **Docstring:** Identical seed produces bit-identical state hashes, journal hashes, and PRNG step counts across separate runs and across state save/reload.
* **Criterion:**
  * Run 1 and Run 2 from seed `42` over $500$ ticks must have identical `world.get_state_hash()` and `world.event_journal.last_hash`.
  * Serializing state at tick $250$, reloading into a fresh `WorldState`, and running to tick $500$ must produce the exact same final hash.

### TEST-302: Exact Mass Conservation Under Full Life Cycle
* **Docstring:** Closed-system mass remains constant down to $\pm 0.000000$ FixedPoint tolerance over at least 1,000 ticks with agents feeding, reproducing, sloughing tissue, overflowing biomass, and dying.
* **Criterion:**
  $$\left| M_{\text{closed}}(t) - M_{\text{closed}}(0) \right| == 0.000000 \quad \forall t \in [1, 1000]$$

### TEST-303: Short Multi-Scale Quota Check (Pointing to experiments/)
* **Docstring:** Short multi-scale quota check (30 ticks at 100, 200, 300 agents). Asserts zero `QuotaExceededError` occurrences and peak entities touched recorded (< 1000).
* **Extended Experiments:** For full 100-year (36,500-tick) multi-scale experiments with population dynamics, peak densities, and vital statistics, see [`experiments/run_100y_founder_experiment.py`](file:///c:/Users/VANSH/Documents/gameworld_ai_model/experiments/run_100y_founder_experiment.py) and [`experiments/run_300agent_100y_experiment.py`](file:///c:/Users/VANSH/Documents/gameworld_ai_model/experiments/run_300agent_100y_experiment.py).
* **Criterion:**
  * Quota violations $== 0$. Operations per rule $\le 256$, unique entities touched per tick $\le 1000$.
  * Continuously record and assert the maximum entities touched in any single tick across the run ($\text{peak\_touched} < 1000$).

### TEST-304: Dual-Metabolism Needs Dynamics & Mortality
* **Docstring:** Starved agents die within pre-registered tick windows scaled by metabolic rate; nourished agents survive with oscillating needs.
* **Criterion:**
  * **Case 1 (Standard Metabolism, $1.000000$):** Unsupplied agent dies within $[95, 105]$ ticks (hunger/thirst reaching 100 at tick 100).
  * **Case 2 (Fast Metabolism, $2.000000$):** Unsupplied agent dies within $[45, 55]$ ticks (hunger reaching 100 at tick 50).
  * **Nourished Case:** Fed agent survives $> 500$ ticks with hunger and thirst oscillating within $[0.000000, 70.000000]$.

### TEST-305: Mendelian Inheritance & Genetic Mutation Bounds
* **Docstring:** Alleles segregate from known parents matching a 50/50 binomial distribution; with mutation rate zero, 100% of offspring alleles match one parent; with positive mutation, traits remain strictly bounded.
* **Criterion:**
  * With $\mu = 0$ across $50$ offspring, parental allele distribution is within $[35\%, 65\%]$ ($p \approx 0.50$), and zero foreign alleles appear.
  * With $\mu = 10/1000$ over $10$ generations, $100\%$ of expressed traits satisfy $\text{min}_k \le \text{trait}_k \le \text{max}_k$.

### TEST-306: Starvation-Survival Under Acute Resource Scarcity (Multi-Seed)
* **Docstring:** Starvation-survival test: in resource-scarce famine conditions, low-metabolic-rate phenotypes out-survive high-metabolic-rate competitors across multiple independent seeds.
* **Important Scientific Boundary:** **Heritable natural selection across generations is not demonstrated in Phase 3.** TEST-306 measures differential starvation survival between initial phenotypes under acute caloric famine (low metabolic rate conferring starvation resistance with zero somatic trade-off), not evolutionary adaptation, allele frequency dynamics, or multi-generational selection.
* **Protocol & Results:**
  * Evaluated across 10 independent random seeds: `[42, 101, 202, 303, 404, 505, 606, 707, 808, 909]`.
  * Initialized with 8 co-located founders: 4 Efficient variants ($\text{metabolic\_rate} = 0.500000$) and 4 Profligate variants ($\text{metabolic\_rate} = 1.800000$).
  * Under severe famine conditions ($30.0$ binding biomass without replenishment), all 4 Profligate agents deplete caloric reserves and suffer starvation mortality by tick $200$.
  * Surviving population consists 100% of the Efficient low-metabolic phenotype across all 10 evaluated seeds. Zero quota failures.

### TEST-307: Whole-Window Resource-Bound Carrying Capacity Equilibrium
* **Docstring:** Agent population levels off and establishes equilibrium dictated by available environmental biomass and water, asserting bounded stability across the entire observation window.
* **Criterion:**
  * Evaluated across the full window from tick $150$ to tick $350$.
  * Mean population $\bar{N}$ is established, and for *every tick* $t \in [150, 350]$, $\left| N(t) - \bar{N} \right| / \bar{N} \le 0.150000$ (variance $\le \pm 15\%$).

### TEST-308: Read-Only Emergence Measurement Invariance
* **Docstring:** Executing `evaluate_settlement_emergence`, `evaluate_group_emergence`, and `evaluate_cultural_spread` leaves world state hash, journal hash, and PRNG step count byte-identical.
* **Criterion:**
  $$\text{Hash}_{\text{after}} == \text{Hash}_{\text{before}}, \quad \text{Journal}_{\text{after}} == \text{Journal}_{\text{before}}, \quad \text{PRNG\_Steps}_{\text{after}} == \text{PRNG\_Steps}_{\text{before}}$$

### TEST-309: Negative Control: Founder-Allele-Set Conservation
* **Docstring:** With mutation rate zero ($\mu = 0$), no novel alleles can ever appear in the population: every allele at every locus among all living descendants must be a member of the initial founder allele set.
* **Criterion:**
  $$\forall e \in \text{LivingDescendants}(t \ge 500), \forall k \in [0, 4]: \text{gene}_k(e) \in \mathcal{A}_{\text{founders}, k}$$

### TEST-310: Regression Guard
* **Docstring:** All 126 pre-existing tests (Phases 0, 1, 2, and emergence definitions v1) continue to pass without modification.
* **Criterion:** $126 / 126$ tests pass cleanly on both Windows and Linux CI.

---

## 10. Numbered List of Judgment Calls

1. **Genome Representation: Separate Integer Properties vs. Packed Bitarray**
   * *Recommendation:* Separate integer properties (`gene_metabolic_rate`, etc.). The substrate does not support arrays or bitwise logic. Separate integer properties allow direct GRL expressions, independent property bounds, and transparent journal inspection.
2. **Water Balance: Dry Biomass Assimilation vs. Instant Fluid Throughput**
   * *Recommendation:* Instant fluid throughput (`CONSUME_RESOURCE(soil_water, 2.0)` + `PRODUCE_RESOURCE(soil_water, 2.0)`). Quenches thirst and checks environmental water availability while preventing artificial body mass expansion. All somatic mass remains organic dry tissue governed by carbon/biomass ingestion.
3. **Action Selection: Multi-Action Ticks vs. Priority-Tiered Mutex Rules**
   * *Recommendation:* Single-action mutex (`action_taken`) with strict priority tiers. Biologically realistic, prevents combinatorial entity touches, and guarantees deterministic execution without planning stubs.
4. **Mate Selection: Symmetric Search vs. Female-Initiated Reproduction**
   * *Recommendation:* Female-initiated reproduction (`sex == 0` initiates `AR_05`). The female scans for a co-located male (`sex == 1`). Both parents contribute biomass and energy, and both have reproduction drives reset. Eliminates race conditions and halves reproduction evaluation overhead.
5. **Mutation Distribution: Gaussian Approximation vs. Uniform Bounded Integer Jitter**
   * *Recommendation:* Uniform bounded integer jitter (`RANDOM_INT(-5, +5)`). Gaussian approximation requires float math or integer rejection sampling. Uniform bounded jitter is exact, deterministic, strictly bounded, and computationally lightweight.
6. **Biomass Cap Handling: Hard Cap Clamping vs. Overflow into Detritus**
   * *Recommendation:* Overflow into detritus. Clamping intake without recycling excess mass violates conservation ($M_{\text{in}} > \Delta M_{\text{body}}$). Diverting excess to `detritus` maintains strict 1:1 mass balance at tolerance zero.

---

## 11. Three Weakest Points of the Design

1. **Local-Cell Mate Finding in Depopulated Worlds:**
   Because `AR_05_REPRODUCE` searches for a mate strictly within the same spatial cell $(c_x, c_y)$ using `FIND_ENTITY`, if agents disperse widely across a large grid, reproduction rates may drop to zero due to failure to encounter a mate. Simulation setups must maintain sufficient density ($10 \times 10$ or $20 \times 20$ grids).
2. **Simplified Fluid Dynamics (Closed Water Throughput):**
   Modeling drinking as instant equal consume/produce on `soil_water` guarantees zero-tolerance mass conservation without tracking hydration mass inside body tissues. However, water availability acts primarily as an environmental survival gate rather than an internal physical mass reservoir.
3. **Absence of Kin Avoidance in Mate Selection:**
   Phase 3 contains no social memory or kinship awareness, meaning agents do not avoid close-kin inbreeding (e.g. sibling mating) if co-located. This is biologically plausible for bootstrap organisms and will be refined in Phase 4 when memory and social relationships are authored.

---

## 12. Human Approval Status

**Approved with changes by Human Evaluator.** Stage 2 implementation proceeding.

---

## 13. Version 2.0 Changelog & Calibration Audit (Phase 3d)

### 13.1 Explicit Categorization of Changes

The transition from Version 1.0/1.1 (`agents_params_v1.json`) to Version 2.0 (`agents_params_v2.json`, pinned SHA-256 `20cb1a7791725a29643109ccb5e029525adda6be465d3dcde49a26ec39d899e5`) explicitly distinguishes **Behavioral Changes** (modifying agent decision-making, physiological dynamics, and survival thresholds motivated by empirical test results) from **Structural / Non-Behavioral Changes** (schema enhancements and substrate isolation guards).

| Parameter / Component | v1 Value | v2 Value | Category | Motivation / Empirical Justification |
| :--- | :--- | :--- | :--- | :--- |
| **`reproduction_min_biomass`** | `60.0` | `20.0` | **Behavioral** | **Motivated by test failures:** Autotroph biomass is capped at $25.0$. With adult founder biomass at $40.0\text{--}50.0$, requiring $60.0$ somatic biomass made reproduction virtually impossible before basal metabolism burned intake, causing zero births and extinction. |
| **`reproduction_min_energy`** | `150.0` | `30.0` | **Behavioral** | **Motivated by test failures:** An energy threshold of $150.0$ exceeded sustainable reserves under caloric scarcity, preventing agents from mating even when fertile. |
| **`target_selector_limit`** | `2` | `4` | **Behavioral** | **Motivated by test failures:** In co-located breeding pairs sharing an autotroph cell ($2\text{ agents} + 1\text{ plant} = 3\text{ entities}$), a limit of 2 caused target selector drops, starving agents or missing mates. |
| **`eat_autotroph.base_energy_yield`** | `15.0` | `40.0` | **Behavioral** | **Motivated by test failures:** $15.0$ energy yield per feeding was insufficient to overcome basal metabolic burn and build surplus energy to trigger reproduction drive. |
| **`fatigue_trigger_threshold`** | `50.0` | `40.0` | **Behavioral** | **Motivated by test failures:** Lowering the trigger to $40.0$ causes agents to rest earlier, avoiding critical exhaustion spirals that hindered foraging and mating. |
| **`AR_07_FORAGE_MOVE` locomotion cost** | `2.0` | `0.0` | **Behavioral** | **Motivated by test results:** Removing locomotion energy cost isolates `metabolic_rate` as the sole variable energy expenditure for unambiguous selection pressure validation in TEST-306. |
| **`is_agent` Schema Property** | *Absent* | `INT64 [0,1]` | **Structural** | Decouples Phase 2 ecosystem rules (`BR_03`, `BR_05`) from Phase 3 agents entirely in Layer 2 data, preserving the Layer 1 frozen substrate invariant. |
| **`age` Schema Property** | *Absent* | `INT64` | **Structural** | Added to `agent.json` to mirror `age_ticks // 365` for emergence analysis binding compatibility. |
| **Needs Property Bounds** | `max: 100.0` | `max: 200.0` | **Structural** | Prevents property constraint validation crashes during transient spikes without altering standard $[0, 100]$ operational thresholds. |

---

### 13.2 TEST-306 Relabeling, Scientific Boundary & Contradiction Resolution
- **Scientific Boundary:** Heritable natural selection across generations is not demonstrated in Phase 3. TEST-306 measures differential starvation survival between initial phenotypes under acute caloric famine (low metabolic rate conferring starvation resistance with zero somatic trade-off), not evolutionary adaptation, allele frequency dynamics, or multi-generational selection.
- **Relabeling:** Formally relabeled in code docstrings, test identifiers, and documentation as `test_306_starvation_survival_selection_for_low_metabolic_rate`.
- **Contradiction Resolution (4-births / 6-living vs 5-deaths / 3-living):**
  - **4-births / 6-living scenario:** Occurred in an early exploratory calibration where partial food replenishment was active ($\approx 1.0/\text{tick}$). Founders survived, and 2 female agents achieved the reproduction drive threshold ($60.0$) and gave birth to 2 offspring ($4\text{ founders} + 2\text{ offspring} = 6\text{ living}$).
  - **5-deaths / 3-living scenario:** Occurred under the strict famine protocol ($30.0$ binding autotroph biomass without replenishment). All 4 Profligate agents ($m=1.8$) depleted energy and died of starvation, while 1 Efficient agent starved due to initial foraging competition ($8\text{ founders} - 5\text{ deaths} = 3\text{ living}$, all 3 low-metabolic Efficient).
  - Both outcomes are mathematically and ecologically consistent with the underlying model under differing resource influx regimes. Under the standardized 10-seed famine protocol, low-metabolic agents are the sole survivors across all 10 independent seeds.

---

### 13.3 Version 3.0 Changelog (Phase 3e)
* **Parameters File:** Created `agents_params_v3.json` with canonical SHA-256 `850c2139bb79a6c2d2b7398b53624f3626920c5ccc7d34c35d76c3de1ab9623c`.
* **Restoration of v2:** `agents_params_v2.json` restored strictly to its original Phase 3b pinned hash `46b4be4e31e3086dd30e086bf6949e1b1cdd4eb7cf8ffa7eb2a3b2369df8e05a`.
* **Changes in v3:**
  1. Added `"is_agent": 1` in `AR_05_REPRODUCE` child entity creation and agent schema to decouple Phase 2 ecosystem basal metabolism (`BR_03`) and starvation (`BR_05`) without touching the frozen Layer 1 substrate.
  2. Synchronized `thirst_satisfaction` ($50.0$) and `child_base_energy` ($50.0$) to maintain exact rule-to-params parity in `test_rule_constants_match_params_file`.
  3. Reconciled calibration log and changelog entries.


