# GENESIS Alpha — Pre-Registered Definitions of Emergence
## Quantitative Operational Specifications for Settlement, Group, and Cultural Spread

**Document Version:** `v1.1.0` (Approved Baseline `v1`)  
**Status:** Pre-Registered Specification — Approved by Human Evaluator  
**Hash-Pinned Parameters File:** `genesis/analysis/data/emergence_params_v1.json`  
**Canonical Parameters SHA-256:** `9dc8c96b152a63d118070a2c15dbea0806522a1a0e391477a2b895ea55548591`  

---

## 1. Executive Summary & Core Principles

### 1.1 The Anti-Storytelling Invariant
In GENESIS, an LLM describing a civilization, tribe, or religious revival is **not** evidence that one emerged. Simulation success is measured strictly from the computational simulation state. Prior to this specification, terms like *"settlement"*, *"group"*, and *"cultural spread"* lacked operational mathematical definitions, risking confirmation bias where random stochastic noise, genetic drift, or environmental bottlenecks are post-hoc labeled as emergent social order.

This specification pre-registers exact, falsifiable, quantitative definitions for these three phenomena **before any Phase 3 agent, trait, genome, or cognitive architecture is authored**. The parameters defined herein are frozen in `emergence_params_v1.json` and cannot be retroactively adjusted after observing simulation results.

```
+---------------------------------------------------------------------------------------+
|                              LAYER 1: COMPUTATIONAL SUBSTRATE                         |
|  (Entities, Property Tables, Spatial Grid, Relationship Graph, Append-Only Journal)   |
+---------------------------------------------------------------------------------------+
                                           |  Read-only inspection
                                           v
+---------------------------------------------------------------------------------------+
|                           GENESIS ANALYSIS ENGINE (Offline)                           |
|  - AnalysisBinding: Decouples domain ontology from metric algorithms                  |
|  - Deterministic PRNG: Isolated xoshiro256** seeded via SHA-256 analysis domain tag   |
|  - Exact Arithmetic: Pure integer and FixedPoint arithmetic; zero floats in logic     |
+---------------------------------------------------------------------------------------+
        |                                  |                                  |
        v                                  v                                  v
+-------------------+              +-------------------+              +-------------------+
|    SETTLEMENT     |              |       GROUP       |              |  CULTURAL SPREAD  |
| - Spatial Cluster |              | - Co-op Network   |              | - Social Learning |
| - 5-Yr Persistence|              | - Community LPA   |              | - Beyond Lineage  |
| - Generational    |              | - Size >= 8       |              |   (Common Ancestor|
|   Anchoring (30%) |              | - Multi-Yr Repeat |              |    > 4 Gens)      |
| - Dual Null Tests:|              | - 10-Yr Turnover  |              | - Copy Fidelity   |
|   1. Uniform Null |              | - Non-Kin Bounds  |              | - Post-Founder    |
|   2. Oasis Null   |              | - Degree Swap Null|              | - Random Null     |
+-------------------+              +-------------------+              +-------------------+
```

### 1.2 Operational Scale Calibration (Alpha World)
All metrics and default parameters are calibrated for the **GENESIS Alpha** regime:
- **Demographic Scale:** $100$ to $300$ active individuals.
- **Spatial Extent:** $30$ to $100$ spatial cells (e.g. $6 \times 6$ to $10 \times 10$ toroidal grid).
- **Temporal Horizon:** $100$ to $300$ simulation years ($36,500$ to $109,500$ ticks, at $365$ ticks per year).
- **Generation Time:** Estimated at $15$ to $25$ years ($5,475$ to $9,125$ ticks).

### 1.3 Layer Boundary & The Generic Analysis Binding
The analysis engine (`genesis/analysis/`) resides completely outside the Layer 1 runtime substrate. It does not introduce any Python entity subclasses or hardcoded fictional roles. All metrics consume an `AnalysisBinding` schema mapping generic substrate primitives to operational roles:

```python
class AnalysisBinding:
    agent_entity_types: Tuple[str, ...]          # e.g. ("agent", "human")
    pos_x_prop: str                              # default: "cell_x"
    pos_y_prop: str                              # default: "cell_y"
    alive_prop: str                              # default: "is_alive"
    parent_edge_kind: str                        # default: "parent_of"
    cooperation_edge_kinds: Tuple[str, ...]      # e.g. ("traded_with", "allied_with", "subject_of")
    cooperation_event_types: Tuple[str, ...]     # e.g. ("trade_executed", "tax_remitted", "gift_given")
    practice_property: str                       # e.g. "farming_technique", "ritual_practice"
    adoption_event_type: str                     # e.g. "practice_adopted", "technique_learned"
    stockpile_resource_property: Optional[str]   # e.g. "grain", "coins" (None if unbound)
    resource_landscape_property: Optional[str]   # e.g. "soil_water", "carrying_capacity" (None if uniform)
```

### 1.4 Strict Determinism, Invariant Verification, and Null Randomness
1. **Read-Only Invariant:** Analysis functions inspect state through read-only accessors. They never mutate entity properties, the relationship graph, spatial indices, the resource manager, or the event journal. A test must verify that `world.compute_state_hash()` and the journal hash chain are byte-identical before and after running any metric.
2. **Deterministic Arithmetic:** All arithmetic uses 64-bit integer counts or 64-bit signed integer `FixedPoint` numbers ($10^6$ scale). No floating-point operations exist in any code path that influences a verdict, ratio, or percentile.
3. **Iteration-Order Safety:** Entities are processed in strictly ascending order by `entity_id`. Spatial cells are iterated by `(cx, cy)` ascending. Relationship edges are sorted by `(source_id, target_id, rel_type)`. All ties in graph community detection and sorting are resolved deterministically by lowest entity ID.
4. **Isolated Analysis PRNG Stream:** Null models never invoke `world.rng` or `derive_rule_stream`. A dedicated pure generator derives an independent `GenesisRNG` stream using SHA-256 over domain tag `genesis/analysis-stream/v1`, a fixed analysis seed, and iteration indices. Running an analysis null model advances `world.rng.step_count` by exactly **zero**.

---

## 2. Parameter Hash-Pinning & Versioning Governance

All threshold values are serialized in `genesis/analysis/data/emergence_params_v1.json`.

```
File Path: genesis/analysis/data/emergence_params_v1.json
Canonical Serialization: UTF-8, Sort Keys, Indent 2, LF Line Endings
Canonical SHA-256: 9dc8c96b152a63d118070a2c15dbea0806522a1a0e391477a2b895ea55548591
```

### 2.1 Governance & Change Rules
- **Frozen Baseline:** Version `v1` is frozen upon approval.
- **Immutability:** Existing tests must recompute the SHA-256 of `emergence_params_v1.json` and fail if modified by a single byte.
- **Changelog for Version `v1` (Post-Review Approvals):**
  1. *Oasis Null Added:* Added a second resource-landscape-weighted spatial null model. Settlements must beat both uniform null and resource-weighted null at 99th percentile ($p \le 0.01$).
  2. *Group Size & Temporal Repetition:* Raised `min_members` from 5 to 8, and added `min_active_years: 2` requiring cooperation edges to be active across $\ge 2$ distinct annual sample windows.
  3. *Extended Kin Horizon for Culture:* Tightened kin definition to treat any shared common ancestor within $k_{\text{common\_ancestor}} \le 4$ generations as kin, preventing cousin lineages from masquerading as horizontal social transmission.
  4. *Unbound-Stockpile Caveat:* Explicitly report `"stockpile not assessed"` when `stockpile_resource_property` is unbound.

---

## 3. Operational Definition 1: Settlement

### 3.1 Intuition
A settlement is a spatial cluster of agents that is statistically denser than chance, persists across multiple years/generations, and demonstrates generational residency ("born in place"), not a transient nomadic camp, resource-chokepoint queue, or temporary foraging congregation at a fertile oasis.

### 3.2 State & Journal Inputs
1. **Active Living Agents:** Queried at sample ticks $t_k \in \{t_0, t_0 + \Delta t, \dots, t_{\text{end}}\}$ where $\Delta t = \text{sample\_interval\_ticks}$ ($365$ ticks / $1$ year).
2. **Spatial Grid Coordinates:** Entity properties `cell_x` and `cell_y` for all active agents.
3. **Birth / Creation Records:** Historical birth records from the append-only event journal (`entity_spawned` / `entity_created` events) recording `(entity_id, tick, birth_cell_x, birth_cell_y)`.
4. **Stockpile Levels (Optional):** Local resource pool balances or entity inventory properties per cell.
5. **Resource Landscape (Optional/Carrying Capacity):** Local environmental fertility or carrying capacity per cell (`resource_landscape_property`).

### 3.3 Mathematical Formulation & Sub-Criteria

#### Criterion 1.1: Spatial Clustering ($R_s, N_{\text{min}}$)
Two occupied cells $c_1 = (x_1, y_1)$ and $c_2 = (x_2, y_2)$ are connected if their Chebyshev distance satisfies:
$$D_{\text{Chebyshev}}(c_1, c_2) = \max(|x_1 - x_2|, |y_1 - y_2|) \le R_s \quad (\text{default } R_s = 2)$$

Connected cells partition the agent population into spatial connected components $\{C_1, C_2, \dots\}$. A candidate settlement component $C$ must satisfy:
$$|C| \ge N_{\text{min}} \quad (\text{default } N_{\text{min}} = 8 \text{ agents})$$

#### Criterion 1.2: Multi-Year Temporal Persistence ($T_{\text{persist}}, \Delta t, J_{\text{min}}, D_{\text{max}}$)
The cluster is sampled annually at intervals of $\Delta t = 365$ ticks across a persistence window:
$$T_{\text{persist}} = 1825 \text{ ticks } (5 \text{ simulation years, } 5 \text{ annual samples})$$

Cluster continuity across consecutive samples $t_k \to t_{k+1}$ is established via member Jaccard similarity:
$$J(C_k, C_{k+1}) = \frac{|C_k \cap C_{k+1}|}{|C_k \cup C_{k+1}|} \ge J_{\text{min}} \quad (\text{default } J_{\text{min}} = 0.50)$$
If multiple components at $t_{k+1}$ achieve $J \ge J_{\text{min}}$, the component with the highest $J$ is selected; ties are broken by the lowest minimum entity ID.

Centroid drift between consecutive annual samples must satisfy:
$$\max(|\bar{x}_{k+1} - \bar{x}_k|, |\bar{y}_{k+1} - \bar{y}_k|) \le D_{\text{max}} \quad (\text{default } D_{\text{max}} = 2 \text{ cells})$$

#### Criterion 1.3: Generational Anchoring ($f_{\text{born\_min}}$)
At the conclusion of the persistence window ($t_{\text{end}} = t_0 + T_{\text{persist}}$), let $U_{\text{footprint}}$ be the cumulative spatial footprint of the settlement across its 5-year history:
$$U_{\text{footprint}} = \bigcup_{k=0}^{5} \text{Cells}(C(t_k))$$

For each resident $a \in C(t_{\text{end}})$, its birthplace cell $(x_b(a), y_b(a))$ is extracted from its journal birth record. The born-in-place fraction must satisfy:
$$\text{BornInFraction}(C) = \frac{|\{a \in C(t_{\text{end}}) \mid (x_b(a), y_b(a)) \in U_{\text{footprint}}\}|}{|C(t_{\text{end}})|} \ge f_{\text{born\_min}} \quad (\text{default } f_{\text{born\_min}} = 0.30 \text{ or } 30\%)$$

#### Criterion 1.4: Dual Statistical Significance vs. Spatial Null Models
To prevent both random clusters and environmental oasis congregations from masquerading as settlements, the observed maximum component size $S_{\text{obs}} = |C(t_{\text{end}})|$ must beat **two separate null models**:
1. **Uniform Spatial Permutation Null:**
   - In each of $K_{\text{null}} = 200$ iterations, active agents are re-placed uniformly at random across the bounding extent of all occupied cells.
   - $S_{\text{obs}}$ must exceed the 99th percentile of $S_{\text{uniform\_null}}$ ($p \le 0.01$).
2. **Resource-Landscape-Weighted Spatial Null (The Oasis Guard):**
   - In each of $K_{\text{null}} = 200$ iterations, active agents are re-placed across cells with probability proportional to the local environmental resource abundance:
     $$P(\text{cell } c) = \frac{\max(1, \text{Resource}(c))}{\sum_{c'} \max(1, \text{Resource}(c'))}$$
     *(If no resource property is bound, cell weights default to uniform).*
   - $S_{\text{obs}}$ must exceed the 99th percentile of $S_{\text{resource\_weighted\_null}}$ ($p \le 0.01$).
   - A congregation of organisms clustered solely because an oasis contains 90% of the world's water will generate equally dense clusters in the resource-weighted null, and thus **fails** this criterion.

#### Criterion 1.5: Stockpile Enrichment (Optional)
If `stockpile_resource_property` is bound, the mean stockpile per cell within $U_{\text{footprint}}$ is compared against the mean stockpile across all other occupied cells:
$$\text{EnrichmentRatio} = \frac{\text{MeanStockpile}(U_{\text{footprint}})}{\max(1, \text{MeanStockpile}(\text{RestOfWorld}))} \ge 1.50$$
If `stockpile_resource_property` is unbound (or None), the sub-criterion evaluates to `NOT_ASSESSED` and explicitly outputs `"stockpile not assessed"`. It does not block the settlement verdict.

---

## 4. Operational Definition 2: Group

### 4.1 Intuition
A group is a set of agents bound by repeated cooperative interactions that are significantly stronger internally than externally, which exhibits community structure beyond mere physical co-location, extends beyond a nuclear family clique, and demonstrates institutional persistence across the generational turnover of its founding members.

### 4.2 State & Journal Inputs
1. **Interaction Graph Window:** Evaluated across a persistence window $W_{\text{group}} = [t_0, t_0 + T_{\text{group}}]$ where $T_{\text{group}} = 3650 \text{ ticks}$ ($10 \text{ years}$).
2. **Bound Relationship Edges:** Relationship instances from `world.relationships` of kinds listed in `cooperation_edge_kinds` (e.g. `traded_with`, `allied_with`, `subject_of`).
3. **Bound Journal Cooperative Events:** Journal event records of types in `cooperation_event_types` (e.g. trade execution, tax remittance, shared defense, resource transfer) occurring within $W_{\text{group}}$.
4. **Kinship Lineage Edges:** Edges of type `parent_edge_kind` (e.g. `parent_of`).
5. **Physical Co-Location Exclusion:** **Co-location in the same cell produces ZERO graph edges.** Proximity without interaction is strictly disregarded.

### 4.3 Mathematical Formulation & Sub-Criteria

#### Criterion 2.1: Interaction Graph Construction & Weighting
A weighted undirected graph $G = (V, E, w)$ is constructed over all agents alive during $W_{\text{group}}$:
$$w(u, v) = \sum_{r \in \text{Rels}(u, v)} w_{\text{rel}}(r) + \sum_{e \in \text{Events}(u, v, W_{\text{group}})} w_{\text{event}}(e)$$
Where base weights are $1.0$ FixedPoint ($1,000,000$ raw) per active relationship edge and per recorded cooperative interaction event.

#### Criterion 2.2: Deterministic Community Detection (Weighted LPA)
Communities are extracted using a strictly deterministic Weighted Label Propagation Algorithm:
1. **Initialization:** Every node $u \in V$ is assigned label $\lambda(u) = u$ (its own entity ID).
2. **Node Ordering:** Nodes are visited in strictly ascending order of `entity_id`.
3. **Label Update:** Node $u$ adopts the label maximizing total incident edge weight:
   $$\lambda^*(u) = \arg\max_L \sum_{v \in N(u) \mid \lambda(v) = L} w(u, v)$$
4. **Deterministic Tie-Breaking:** If multiple candidate labels tie for the maximum score, the numerically smallest entity ID label is chosen.
5. **Termination:** Iterates until convergence or until $\text{community\_detection\_max\_iterations} = 20$ iterations is reached.

#### Criterion 2.3: Membership Size, Internal Density, and Cohesion Ratio
A detected community $G_{\text{cand}}$ must satisfy:
1. **Size:** $|G_{\text{cand}}| \ge G_{\text{min}} \quad (\text{default } G_{\text{min}} = 8 \text{ members})$.
2. **Internal Edge Density:**
   $$\rho(G_{\text{cand}}) = \frac{2 \cdot |E_{\text{int}}(G_{\text{cand}})|}{|G_{\text{cand}}|(|G_{\text{cand}}| - 1)} \ge \rho_{\text{min}} \quad (\text{default } \rho_{\text{min}} = 0.20 \text{ or } 20\%)$$
3. **Cohesion Ratio (Inside vs. Outside Weight):**
   $$W_{\text{int}} = \sum_{u, v \in G_{\text{cand}}, u < v} w(u, v), \quad W_{\text{ext}} = \sum_{u \in G_{\text{cand}}, v \notin G_{\text{cand}}} w(u, v)$$
   $$R_{\text{cohesion}} = \frac{W_{\text{int}}}{\max(1, W_{\text{ext}})} \ge R_{\text{cohesion\_min}} \quad (\text{default } R_{\text{cohesion\_min}} = 2.00)$$

#### Criterion 2.4: Multi-Year Temporal Repetition (Anti-Burst Guard)
To prevent a one-off burst of transactions within a short window from qualifying as a group, the group's cooperation edges must exhibit activity across at least:
$$\text{ActiveYears}(G_{\text{cand}}) \ge \text{min\_active\_years} \quad (\text{default } 2 \text{ separate annual sample windows})$$

#### Criterion 2.5: Extended Social Structure (Non-Kin Bound)
Kinship is defined on the undirected graph spanned by `parent_of` edges. Two agents $u, v$ are defined as **immediate kin** if their shortest path distance on the kinship graph satisfies:
$$d_{\text{kin}}(u, v) \le d_{\text{kin\_max}} \quad (\text{default } d_{\text{kin\_max}} = 2)$$
This encompasses parent-child ($d=1$), siblings ($d=2$ via common parent), and grandparent-grandchild ($d=2$).

Let $E_{\text{int}}(G_{\text{cand}})$ be the internal cooperation edges of the group. The fraction of internal edges connecting non-kin agents must satisfy:
$$f_{\text{non\_kin\_edges}} = \frac{|\{(u, v) \in E_{\text{int}}(G_{\text{cand}}) \mid d_{\text{kin}}(u, v) > 2\}|}{|E_{\text{int}}(G_{\text{cand}})|} \ge f_{\text{non\_kin\_min}} \quad (\text{default } 0.30 \text{ or } 30\%)$$

#### Criterion 2.6: Institutional Persistence Through Generational Turnover
The group must persist across $T_{\text{group}} = 3650 \text{ ticks}$ ($10$ years) sampled annually ($\Delta t = 365$ ticks):
- Community identity between consecutive samples is tracked via Jaccard similarity $\ge 0.50$.
- Let $G(t_0)$ be the founding cohort of the group at tick $t_0$, and $G(t_{\text{end}})$ be the cohort at tick $t_0 + T_{\text{group}}$.
- Generational turnover measures the fraction of original founding members that have died or departed:
  $$\text{Turnover} = 1.0 - \frac{|G(t_{\text{end}}) \cap G(t_0)|}{|G(t_0)|} \ge \tau_{\text{min}} \quad (\text{default } \tau_{\text{min}} = 0.50 \text{ or } 50\%)$$

#### Criterion 2.7: Statistical Significance vs. Degree-Preserving Randomization Null
The observed cohesion ratio $R_{\text{cohesion}}$ is evaluated against a degree-preserving graph randomization null:
- In each of $K_{\text{null}} = 200$ iterations, the observed interaction graph undergoes Maslov-Sneppen edge-swapping preserving the exact degree sequence of every node.
- Observed $R_{\text{cohesion}}$ must exceed the 99th percentile of $R_{\text{null}}$ ($p \le 0.01$).

---

## 5. Operational Definition 3: Cultural Spread

### 5.1 Intuition
Cultural spread means a learned practice moves between individuals via social transmission (horizontal or oblique), spreading faster and wider across geographic space than genetic inheritance alone, with high copying fidelity, and persisting after the original adopters have died.

### 5.2 State & Journal Inputs
1. **Practice Property:** Agent property specified in `AnalysisBinding.practice_property` (e.g. `farming_technique`, `tool_use`).
2. **Adoption Journal Events:** Journal events of type `AnalysisBinding.adoption_event_type` recording:
   $$(t, \text{adopter\_id}, \text{source\_id}, \text{practice\_id}, \text{transmitted\_value})$$
3. **Kinship Lineage:** Traversed via `AnalysisBinding.parent_edge_kind` to evaluate genealogical descent.
4. **Spatial Positions:** Cell locations of adopters over time.

### 5.3 Mathematical Formulation & Sub-Criteria

#### Criterion 3.1: Social Transmission Beyond Extended Kinship ($k_{\text{common\_ancestor}} \le 4$)
Let $E_{\text{adopt}}$ be the set of recorded adoption events for practice $P$ over the evaluation window:
- For each event $e = (t, A, S)$, the genealogical relationship between adopter $A$ and mentor/source $S$ is evaluated on the directed `parent_of` genealogy.
- **Extended Kin Definition:** $A$ and $S$ are defined as kin if they share **any common ancestor within $k_{\text{common\_ancestor}} \le 4$ generations** (parents, grandparents, great-grandparents, or great-great-grandparents, covering first, second, and third cousins).
- An adoption event is strictly **non-kin transmission** if and only if $A$ and $S$ share zero common ancestors within $4$ generations.
- The non-kin transmission fraction must satisfy:
  $$f_{\text{non\_kin\_trans}} = \frac{|\{e = (t, A, S) \mid A \text{ and } S \text{ share no common ancestor } \le 4 \text{ gen}\}|}{|E_{\text{adopt}}|} \ge f_{\text{non\_kin\_trans\_min}} \quad (\text{default } 0.50 \text{ or } 50\%)$$

Additionally, let $A_{\text{all}}$ be all agents that ever adopted practice $P$. Tracing backwards to the foundational lineage roots:
$$\text{DistinctLineageRoots}(A_{\text{all}}) \ge L_{\text{min}} \quad (\text{default } L_{\text{min}} = 3 \text{ distinct lineages})$$

#### Criterion 3.2: Demographic and Spatial Reach
At evaluation tick $t_{\text{eval}}$:
1. **Adopter Count:**
   $$N_{\text{adopters}}(t_{\text{eval}}) \ge N_{\text{adopt\_abs\_min}} \quad (\text{default } 8 \text{ living agents})$$
   $$\frac{N_{\text{adopters}}(t_{\text{eval}})}{N_{\text{living\_total}}(t_{\text{eval}})} \ge f_{\text{adopt\_min}} \quad (\text{default } 0.10 \text{ or } 10\%)$$
2. **Spatial Expansion:** Let $c_{\text{founder}}$ be the cell where practice $P$ was first introduced. At $t_{\text{eval}}$, the spatial span of living adopters must exceed the founder's immediate neighborhood:
   $$\text{Span}_{\text{Chebyshev}}(A_{\text{adopters}}, c_{\text{founder}}) = \max_{a \in A_{\text{adopters}}} D_{\text{Chebyshev}}(\text{cell}(a), c_{\text{founder}}) \ge \Delta \text{Span}_{\text{min}} \quad (\text{default } 2 \text{ cells})$$

#### Criterion 3.3: Transmission Speed Beyond Genetic Lineage
Let $F_0$ be the original founder of practice $P$ at tick $t_{\text{intro}}$. At evaluation tick $t_{\text{eval}}$:
- $N_{\text{cult}}(t_{\text{eval}})$: Number of living agents currently holding practice $P$.
- $N_{\text{desc}}(t_{\text{eval}})$: Number of living genetic descendants of founder $F_0$ at $t_{\text{eval}}$.
- Speed ratio:
  $$R_{\text{speed}} = \frac{N_{\text{cult}}(t_{\text{eval}})}{\max(1, N_{\text{desc}}(t_{\text{eval}}))} \ge R_{\text{speed\_min}} \quad (\text{default } R_{\text{speed\_min}} = 2.00)$$

#### Criterion 3.4: Copying Fidelity
When practice $P$ is transmitted from source $S$ to adopter $A$, the adopted value must match the source value without corruptive noise:
$$\text{Fidelity} = \frac{|\{e \in E_{\text{adopt}} \mid \text{value}(A) == \text{value}(S)\}|}{|E_{\text{adopt}}|} \ge f_{\text{fidelity\_min}} \quad (\text{default } 0.90 \text{ or } 90\%)$$

#### Criterion 3.5: Post-Founder Generational Persistence
Let $\mathcal{F}$ be the set of initial founding adopters. At evaluation tick $t_{\text{eval}}$, **all** founding adopters must be deceased:
$$\forall f \in \mathcal{F}, \quad \text{is\_alive}(f) == 0$$
The count of active living agents still holding and practicing $P$ must satisfy:
$$N_{\text{post\_founder\_adopters}}(t_{\text{eval}}) \ge N_{\text{post\_founder\_min}} \quad (\text{default } 5 \text{ agents})$$

#### Criterion 3.6: Statistical Significance vs. Random Adoption Null
In each of $K_{\text{null}} = 200$ iterations, the timing of recorded adoptions is held fixed, but adopter and source identities are reassigned uniformly at random among agents alive at that tick.
- Observed non-kin transmission fraction and spatial clustering must exceed the 99th percentile of the null distribution ($p \le 0.01$).

---

## 6. Cross-Cutting Standards & Structured Verdict Schema

### 6.1 State-Only Evidence Invariant
A metric may inspect entity property state, relationship graphs, spatial indices, resource balances, and event journals. A metric must **never** read, parse, or evaluate any natural language text or LLM commentary.

### 6.2 Structured Verdict Schema
Every measurement returns a deterministic dictionary adhering strictly to the following JSON structure:

```json
{
  "phenomenon": "settlement",
  "params_version": "v1",
  "params_sha256": "9dc8c96b152a63d118070a2c15dbea0806522a1a0e391477a2b895ea55548591",
  "passed": false,
  "evaluated_ticks": {
    "start_tick": 0,
    "end_tick": 1825,
    "total_ticks": 1825,
    "years": 5
  },
  "candidate_id": "settlement_cluster_c0",
  "sub_criteria": {
    "spatial_cluster_size": {
      "passed": true,
      "observed": 12,
      "threshold": 8,
      "margin": 4
    },
    "temporal_persistence": {
      "passed": true,
      "observed_years": 5,
      "threshold_years": 5,
      "min_jaccard": "0.620000",
      "threshold_jaccard": "0.500000"
    },
    "generational_anchoring": {
      "passed": false,
      "observed_born_in_fraction": "0.150000",
      "threshold_born_in_fraction": "0.300000",
      "margin": "-0.150000"
    },
    "significance_uniform_null": {
      "passed": true,
      "null_model": "spatial_uniform_permutation",
      "k_permutations": 200,
      "observed_statistic": 12,
      "null_99th_percentile": 7,
      "p_value_bound": "0.005000"
    },
    "significance_resource_weighted_null": {
      "passed": false,
      "null_model": "spatial_resource_weighted_permutation",
      "k_permutations": 200,
      "observed_statistic": 12,
      "null_99th_percentile": 14,
      "p_value_bound": "0.120000"
    },
    "stockpile_enrichment": {
      "status": "NOT_ASSESSED",
      "note": "stockpile not assessed",
      "passed": true
    }
  },
  "failure_reasons": [
    "Generational anchoring failed: observed born-in fraction 0.150000 < threshold 0.300000 (margin: -0.150000)",
    "Resource-weighted null significance failed: observed 12 did not exceed 99th percentile 14 (oasis congregation)"
  ]
}
```

### 6.3 Informative Failure Guarantees
A verdict is never a bare boolean. When a candidate fails, `failure_reasons` lists every failed sub-criterion, its observed numeric value, its required threshold, and the exact shortfall margin.

### 6.4 Multiple Comparisons Control
When evaluating $M$ candidate entities, clusters, or sliding time windows across a world:
1. **Max-Statistic Null Model:** Significance null models evaluate the **global maximum statistic** across all detected components in each permutation iteration $k$, providing exact Family-Wise Error Rate (FWER) control at $\alpha = 0.01$.
2. **Discrete Candidate Hypothesis Testing:** If testing $M$ independent candidate hypotheses simultaneously without max-statistic pooling, the required significance threshold applies a strict Bonferroni correction: $\alpha_{\text{corrected}} = 0.01 / M$.

---

## 7. Master Frozen Parameter Table (`v1`)

The following parameters are hash-pinned in `genesis/analysis/data/emergence_params_v1.json`:

| Category | Parameter Name | Canonical Type | Value in v1 | Time Unit | Written Rationale |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **System** | `version` | `STRING` | `"v1"` | — | Schema version tag |
| **System** | `ticks_per_year` | `INT64` | `365` | Ticks | Time model standard for seasonal/annual epoch |
| **Settlement** | `radius_cells` | `INT64` | `2` | Cells | Chebyshev distance allowing contiguous $5 \times 5$ cell territorial patch |
| **Settlement** | `min_agents` | `INT64` | `8` | Agents | Distinguishes communal settlement from isolated nuclear family (scale 100–300) |
| **Settlement** | `sample_interval_ticks`| `INT64` | `365` | 1 Year | Filters out intra-annual seasonal foraging oscillations |
| **Settlement** | `persistence_ticks` | `INT64` | `1825` | 5 Years | Requires multi-year stability across typical organism life stages |
| **Settlement** | `persistence_years` | `INT64` | `5` | Years | Human-readable counterpart to `persistence_ticks` |
| **Settlement** | `min_jaccard_similarity`| `FIXED_POINT`| `"0.500000"` | Ratio | Requires majority membership continuity across consecutive years |
| **Settlement** | `max_centroid_drift_cells`| `INT64`| `2` | Cells/Yr | Prevents nomadic herds from qualifying as stationary settlements |
| **Settlement** | `min_born_in_fraction` | `FIXED_POINT`| `"0.300000"` | Ratio | 30% born-in-place ensures demographic reproduction, not immigrant flux |
| **Settlement** | `stockpile_enrichment_ratio_min`| `FIXED_POINT`| `"1.500000"` | Ratio | 50% surplus over ambient baseline if stockpile bound |
| **Settlement** | `resource_weighted_null_percentile`| `INT64` | `99` | Percentile | Requires exceeding 99th percentile of resource landscape null (oasis guard) |
| **Group** | `min_members` | `INT64` | `8` | Agents | Raised to 8: prevents small trading triads plus hangers-on from qualifying |
| **Group** | `min_internal_density` | `FIXED_POINT`| `"0.200000"` | Ratio | At least 20% of all possible internal bilateral edges must exist |
| **Group** | `min_cohesion_ratio` | `FIXED_POINT`| `"2.000000"` | Ratio | Internal cooperation weight must be $\ge 2\times$ external weight |
| **Group** | `min_active_years` | `INT64` | `2` | Years | Cooperation edges must be active across $\ge 2$ distinct annual sample windows |
| **Group** | `max_kin_generation_depth`| `INT64` | `2` | Generations | Direct kin horizon for graph edges |
| **Group** | `min_non_kin_edge_fraction`| `FIXED_POINT`| `"0.300000"` | Ratio | $\ge 30\%$ non-kin ties ensures structure extends beyond nuclear family |
| **Group** | `sample_interval_ticks`| `INT64` | `365` | 1 Year | Sampling frequency for group membership tracking |
| **Group** | `persistence_ticks` | `INT64` | `3650` | 10 Years | Multi-decade institutional longevity |
| **Group** | `persistence_years` | `INT64` | `10` | Years | Human-readable counterpart to `persistence_ticks` |
| **Group** | `min_jaccard_similarity`| `FIXED_POINT`| `"0.500000"` | Ratio | Group identity continuity across annual samples |
| **Group** | `min_turnover_fraction` | `FIXED_POINT`| `"0.500000"` | Ratio | $\ge 50\%$ founders replaced proves persistence beyond individuals |
| **Group** | `community_detection_max_iterations` | `INT64` | `20` | Iterations | Bounded execution cap for deterministic Weighted LPA |
| **Culture** | `max_common_ancestor_generations`| `INT64` | `4` | Generations | Common ancestor within 4 generations counted as kin for transmission test |
| **Culture** | `min_non_kin_transmission_fraction`| `FIXED_POINT`| `"0.500000"` | Ratio | Majority of adoptions ($\ge 50\%$) must occur between non-kin |
| **Culture** | `min_distinct_lineages` | `INT64` | `3` | Roots | Spans at least 3 distinct genealogical root families |
| **Culture** | `min_adopter_fraction` | `FIXED_POINT`| `"0.100000"` | Ratio | Reaches at least 10% of living population |
| **Culture** | `min_adopter_absolute` | `INT64` | `8` | Agents | Absolute adoption threshold prevents small-population percentages passing on 1-2 agents |
| **Culture** | `min_spatial_span_cells`| `INT64` | `2` | Cells | Practice spreads $\ge 2$ cells away from founding cell |
| **Culture** | `min_speed_ratio_vs_lineage`| `FIXED_POINT`| `"2.000000"` | Ratio | Cultural spread outpaces founder's living biological descent $\ge 2:1$ |
| **Culture** | `min_fidelity_fraction` | `FIXED_POINT`| `"0.900000"` | Ratio | $\ge 90\%$ transmission events preserve exact practice definition |
| **Culture** | `min_post_founder_adopters`| `INT64` | `5` | Agents | Survives founder mortality with $\ge 5$ active practitioners |
| **Null** | `k_permutations` | `INT64` | `200` | Iterations | Number of randomized null world evaluations per test |
| **Null** | `significance_percentile`| `INT64` | `99` | Percentile | Requires empirical $p \le 0.01$ (rank 198 of 200) |
| **Null** | `alpha_significance` | `FIXED_POINT`| `"0.010000"` | Alpha | Target family-wise significance ceiling |
| **Null** | `analysis_stream_domain_tag`| `STRING` | `"genesis/analysis-stream/v1"` | — | Unique PRNG isolation tag for analysis generator |
| **Null** | `default_analysis_seed` | `INT64` | `1337` | Seed | Fixed seed for offline reproducible null distribution verification |

---

## 8. Limitations & Excluded Phenomena

This specification deliberately operationalizes only proto-social foundations. To avoid premature conceptual expansion, the following phenomena are **explicitly excluded** from the Alpha scope and must not be inferred from these metrics:

1. **Linguistic Semantics & Grammar:** No syntax, grammar, dialect vocabulary, or symbolic discourse is measured.
2. **Religious & Mythological Systems:** No theological doctrines, rituals, or supernatural beliefs are represented.
3. **Formal State Institutions & Jurisdictions:** No sovereign kingdoms, legal constitutions, or courts exist. Groups represent cooperative interaction clusters, not administrative states.
4. **Macro-Economic Markets & Currencies:** No general price discovery, inflation, or international trade networks are modeled.
5. **Organized Warfare:** No tactical military units, siege mechanics, or formal warfare treaties are evaluated.
