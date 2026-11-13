# GENESIS Alpha — Pre-Registered Definitions of Emergence (v2)
## Quantitative Operational Specifications for Settlement (Scan Statistic Fix), Group, and Cultural Spread

**Document Version:** `v2.0.0` (Pre-Registered Specification)  
**Status:** Pre-Registered Specification (Approved Baseline `v2`)  
**Hash-Pinned Parameters File:** `genesis/analysis/data/emergence_params_v2.json`  
**Canonical Parameters SHA-256:** `ee4f718cbe4f87421e778e043e0d0c015c6bb7eca0db2e0e0b922464ebeb628f`  
**Previous Baseline:** `docs/emergence-definitions.md` (`v1.1.0`, Hash `9dc8c96b...`)  

---

## 1. Motivation: Why Version 2 Exists

Phase 3 long-duration empirical simulations (specifically the 300-agent 100-year growing population run recorded in `experiments/300agent_final5y_verdicts.json`) exposed a fundamental methodological flaw in the `v1` settlement statistical test.

### 1.1 The Saturated Map Pathology in v1
In `v1`, spatial clustering was operationalized by partitioning active agents into connected components using Chebyshev distance:
$$D_{\text{Chebyshev}}(c_1, c_2) = \max(|x_1 - x_2|, |y_1 - y_2|) \le R_s \quad (R_s = 2)$$
The significance statistic was the size of the largest connected component:
$$S_{\text{obs}} = |C_{\max}|$$

In the 300-agent simulation:
1. The population grew to 482 living agents, uniformly distributed across the $15 \times 10$ toroidal grid.
2. Because nearly every cell was occupied, the Chebyshev graph formed a **single connected component spanning the entire map** ($|C_{\max}| = 482$).
3. Under the permutation null models (re-placing 482 agents uniformly at random across the occupied cells), random dispersal also connected into a giant component spanning most of the map ($99^{\text{th}}$ percentile of null max component size was $470$).
4. Because $482 > 470$, the observed population **beat both the uniform null and the resource-weighted null at the 99th percentile ($p \le 0.01$)**!
5. The only reason the v1 settlement verdict failed in that run was the multi-year member Jaccard persistence criterion ($0.33 < 0.50$).

### 1.2 The Diagnostic Flaw
A statistical test that is satisfied when **"everybody is everywhere"** cannot distinguish demographic nucleation (a true village or town) from spatial saturation (a diffuse, evenly spaced population). The connected-component metric measures graph percolation across the landscape, not local spatial enrichment.

**This change is motivated by simulation results.** The v2 specification replaces the percolation statistic with an exact spatial scan statistic and an effect-size floor, ensuring that a settlement can only be detected when agents nucleate into localized concentrations far denser than random dispersal or uniform saturation.

---

## 2. Unchanged Core Principles

1. **Read-Only Invariant:** Analysis functions inspect state through read-only accessors. They never mutate entity properties, relationships, spatial indices, resource balances, or journal records. Running an analysis leaves `world.compute_state_hash()`, journal hashes, and `world.rng.step_count` byte-identical.
2. **Deterministic Arithmetic:** All arithmetic uses 64-bit integer counts or 64-bit signed `FixedPoint` numbers ($10^6$ scale). Floating-point operations are strictly prohibited in any calculation that affects a verdict, statistic, ratio, or percentile.
3. **Iteration-Order Safety:** Entities, cells, and candidate windows are processed in strictly ascending deterministic order. Ties are broken by lowest entity ID or lowest grid coordinate $(y, x)$.
4. **Isolated Analysis PRNG Stream:** Null models use `genesis/analysis-stream/v1` via SHA-256 derivation over an independent analysis seed. They never invoke or advance `world.rng` or `derive_rule_stream`.
5. **Architectural Purity:** Measurement code is isolated in `genesis/analysis/`. Substrate (`genesis/core/`, `genesis/substrate/`, `genesis/grl/`), ecosystem (`genesis/ecosystem/`), and agent logic (`genesis/agents/`) remain untouched.
6. **Group & Culture Untouched:** Group and Cultural Spread operational definitions and parameters in v2 are bit-identical copies of v1, with explicit changelog lines stating "no change".
7. **Versioned Structured Verdicts:** Verdict records explicitly state the parameter version (`"v2"`) and pinned canonical SHA-256 hash. Version `v1` remains fully intact, executable, and tested.

---

## 3. Operational Definition 1: Settlement (v2 Specification)

### 3.1 Dimensional Units & Spatial Scale
- All spatial distances and radii, including $R = \text{scan\_window\_radius\_cells}$, are defined in discrete integer **grid cell units**.
- The physical size of each cell is declared in the binding via `AnalysisBinding.cell_size` (FixedPoint) or defaults to unit grid cells.
- A scan window with radius $R = 2$ defines a $(2R+1) \times (2R+1) = 5 \times 5$ cell neighborhood.

### 3.2 State & Journal Inputs
1. **Active Living Agents:** Queried at annual sample ticks $t_k \in \{t_{\text{end}} - 4\Delta t, \dots, t_{\text{end}}\}$ where $\Delta t = \text{sample\_interval\_ticks} = 365$ ticks ($1$ year, $5$ annual samples total).
2. **Spatial Grid Coordinates:** Entity properties `cell_x` and `cell_y` for all active agents.
3. **Declared Landscape Extent:** Queried from `binding.world_extent` as $(X_{\min}, Y_{\min}, X_{\max}, Y_{\max})$. If undeclared (None), falls back to the occupied bounding box of all living agents at that sample.
4. **Birth Records:** Append-only event journal records (`entity_spawned`, `entity_created`, `agent_born`, `reproduction`) containing `(entity_id, tick, cell_x, cell_y)`.
5. **Resource Landscape (Optional):** Local cell resource pool balances or entity properties (`resource_landscape_property`).
6. **Stockpile Levels (Optional):** Local cell stockpile resources (`stockpile_resource_property`).

---

### 3.3 Mathematical Formulation & Sub-Criteria

#### Criterion 1.1: 2D Spatial Scan Statistic & Exact Empirical Significance
Let $C(x, y)$ be the integer count of living agents in cell $(x, y)$.

1. **Integer Summed-Area Table:** Over the declared world extent $[X_{\min}, X_{\max}] \times [Y_{\min}, Y_{\max}]$, construct a 2D prefix sum table $S$:
   $$S(x, y) = C(x, y) + S(x-1, y) + S(x, y-1) - S(x-1, y-1)$$
   with boundary condition $S(x, y) = 0$ outside the extent.

2. **Window Count Evaluation:** For window radius $R = 2$ (cells), each candidate window centered at $(x, y)$ spanning $[x_1, x_2] \times [y_1, y_2] = [\max(X_{\min}, x-R), \min(X_{\max}, x+R)] \times [\max(Y_{\min}, y-R), \min(Y_{\max}, y+R)]$ is evaluated in $O(1)$ operations:
   $$W(x, y) = S(x_2, y_2) - S(x_1-1, y_2) - S(x_2, y_1-1) + S(x_1-1, y_1-1)$$
   The observed test statistic is the maximum window count across all candidate centers:
   $$W_{\max}^{\text{obs}} = \max_{(x,y)} W(x, y)$$

3. **Dual Permutation Null Distributions ($K = 200$):**
   - **Uniform Spatial Permutation:** $N$ agents re-placed uniformly at random across the declared extent (or occupied cells) $K = 200$ times. Compute $W_{\max, k}^{\text{uniform}}$ for each run.
   - **Resource-Weighted Oasis Null:** $N$ agents re-placed across cells with probability proportional to $\max(1, \text{Resource}(c))$ $K = 200$ times. Compute $W_{\max, k}^{\text{resource}}$ for each run.

4. **Exact Empirical Monte Carlo p-Value:**
   For each null distribution, the exact empirical p-value is defined as:
   $$p = \frac{1 + \sum_{k=1}^K \mathbb{I}(W_{\max, k}^{\text{null}} \ge W_{\max}^{\text{obs}})}{K + 1}$$
   With $K = 200$, the significance hurdle requires:
   $$p \le 0.010000 \iff \sum_{k=1}^K \mathbb{I}(W_{\max, k}^{\text{null}} \ge W_{\max}^{\text{obs}}) \le 1$$
   *(i.e. observed maximum window count must exceed at least 199 out of the 200 null permutations).*

5. **Multi-Year Persistence Window Requirement:**
   This exact significance hurdle ($p \le 0.01$) must hold at **every annual sample in the 5-year persistence window** ($t_0, t_1, t_2, t_3, t_4$), against **both** the uniform spatial null and the resource-weighted oasis null.

---

#### Criterion 1.2: Effect-Size Floor ($\text{min\_enrichment\_ratio} \ge 2.000000$)
To prevent large populations with slight density perturbations from triggering significance, the observed maximum window count at the evaluation tick must meet or exceed double the larger of the two null means:

1. **Null Means Calculation:**
   $$\text{Mean}_{\text{uniform}} = \frac{1}{K} \sum_{k=1}^K W_{\max, k}^{\text{uniform}}, \quad \text{Mean}_{\text{resource}} = \frac{1}{K} \sum_{k=1}^K W_{\max, k}^{\text{resource}}$$
   $$\text{NullMeanMax} = \max\left(\sum_{k=1}^K W_{\max, k}^{\text{uniform}}, \sum_{k=1}^K W_{\max, k}^{\text{resource}}\right)$$
2. **Exact FixedPoint Ratio:**
   $$\text{ObservedEnrichment} = \text{FixedPoint.from\_raw}\left( \frac{W_{\max}^{\text{obs}} \cdot K \cdot 1{,}000{,}000}{\max(1, \text{NullMeanMax})} \right)$$
3. **Threshold:**
   $$\text{ObservedEnrichment} \ge \text{min\_enrichment\_ratio} \quad (\text{default } 2.000000)$$

---

#### Criterion 1.3: Candidate Settlement Extraction & Size ($N_{\min} \ge 8$)
1. **Significant Mask:** Cells $(x_c, y_c)$ where window count $W(x_c, y_c) \ge P_{99}(W_{\max}^{\text{uniform}})$.
2. **Candidate Footprint:** The union of cells in all windows meeting or exceeding $P_{99}$.
3. **Spatial Connected Components:** Partition footprint cells into components using Chebyshev radius $R_s = 2$.
4. **Candidate Selection:** The largest component by living agent count is designated $C_{\text{cand}}$.
5. **Size Threshold:**
   $$|C_{\text{cand}}| \ge N_{\min} \quad (\text{default } N_{\min} = 8 \text{ agents})$$

---

#### Criterion 1.4: Temporal Persistence (Member Jaccard Gating & Footprint Informational)
1. **Member Jaccard (Required Gating Criterion):**
   Unchanged from v1. For consecutive annual samples $t_k \to t_{k+1}$ across the 5-year window:
   $$J_{\text{member}}(C_k, C_{k+1}) = \frac{|C_k \cap C_{k+1}|}{|C_k \cup C_{k+1}|} \ge \text{min\_jaccard\_similarity} \quad (\text{default } 0.500000)$$
   *Rationale:* Consecutive annual overlap measures year-to-year demographic and social continuity. Requiring 50% year-to-year retention does not preclude a settlement from outliving its founding members, as rolling overlap accommodates gradual replacement over multi-generational spans.
2. **Centroid Drift (Required Gating Criterion):**
   Centroid drift between consecutive annual samples must not exceed $D_{\max}$:
   $$\max(|\bar{x}_{k+1} - \bar{x}_k|, |\bar{y}_{k+1} - \bar{y}_k|) \le D_{\max} \quad (\text{default } D_{\max} = 2 \text{ cells})$$
3. **Footprint Jaccard (Informational Only):**
   The spatial footprint overlap $J_{\text{footprint}}$ across consecutive annual samples is computed and recorded in the structured record under `"observed_footprint_jaccard_informational"`, but does not gate the pass/fail verdict.

---

#### Criterion 1.5: Generational Anchoring ($f_{\text{born\_min}} \ge 0.300000$)
Unchanged from v1. At least $30\%$ of the living residents in $C_{\text{cand}}(t_{\text{end}})$ must have their birthplace cell $(x_b, y_b) \in U_{\text{footprint}}$ recorded in the event journal:
$$\text{BornInFraction} = \frac{|\{a \in C_{\text{cand}}(t_{\text{end}}) \mid (x_b(a), y_b(a)) \in U_{\text{footprint}}\}|}{|C_{\text{cand}}(t_{\text{end}})|} \ge 0.300000$$

---

#### Criterion 1.6: Stockpile Enrichment (Optional)
Unchanged from v1. If `stockpile_resource_property` is bound, mean stockpile per cell in $U_{\text{footprint}} \ge 1.5\times$ background. If unbound, outputs `"status": "NOT_ASSESSED"`, `"note": "stockpile not assessed"`, and passes non-blockingly.

---

### 3.4 Summary of Evaluated Statistics per Verdict
Each v2 settlement verdict evaluates exactly **21 quantitative sub-metrics**:
1. Scan statistic empirical $p$-value vs. uniform null across 5 annual samples (5 tests).
2. Scan statistic empirical $p$-value vs. resource-weighted null across 5 annual samples (5 tests).
3. Effect-size enrichment ratio against $\max(\bar{W}_{\text{uniform}}, \bar{W}_{\text{resource}})$ (1 test).
4. Spatial cluster candidate size $|C_{\text{cand}}| \ge 8$ (1 test).
5. Consecutive annual member Jaccard similarities $J_{\text{member}} \ge 0.50$ across 4 annual sample transitions (4 tests).
6. Consecutive annual centroid drift $\le 2$ cells across 4 annual sample transitions (4 tests).
7. Generational anchoring born-in fraction $\ge 0.30$ (1 test).

---

## 4. Parameter Specification Table (`emergence_params_v2.json`)

Canonical SHA-256: `ee4f718cbe4f87421e778e043e0d0c015c6bb7eca0db2e0e0b922464ebeb628f`.

| Parameter Key | Type | Default Value | Rationale |
| :--- | :--- | :--- | :--- |
| `settlement.scan_window_radius_cells` | `int` | `2` | 5x5 window radius in cell units, representing local daily foraging/interaction radius on Alpha grids. |
| `settlement.min_enrichment_ratio` | `FixedPoint` | `"2.000000"` | Effect-size floor requiring local density in peak window to be at least double ($\ge 2.0\times$) the larger null mean. |
| `settlement.min_jaccard_similarity` | `FixedPoint` | `"0.500000"` | Gating member Jaccard overlap across consecutive annual samples measuring demographic continuity. |
| `settlement.min_footprint_jaccard_informational` | `FixedPoint` | `"0.500000"` | Informational metric in structured record tracking physical footprint overlap. |
| `settlement.min_agents` | `int` | `8` | Minimum viable community size. |
| `settlement.max_centroid_drift_cells` | `int` | `2` | Gating maximum annual centroid migration distance. |
| `settlement.min_born_in_fraction` | `FixedPoint` | `"0.300000"` | Minimum resident born-in-place fraction. |
| `settlement.persistence_years` | `int` | `5` | 5 annual observation ticks required. |
| `settlement.persistence_ticks` | `int` | `1825` | 5 years at 365 ticks/year. |
| `settlement.sample_interval_ticks` | `int` | `365` | Annual observation cadence. |
| `settlement.radius_cells` | `int` | `2` | Chebyshev connection radius for merging significant windows. |
| `settlement.resource_weighted_null_percentile` | `int` | `99` | 99th percentile significance hurdle ($p \le 0.01$). |
| `settlement.significance_alpha` | `FixedPoint` | `"0.010000"` | Gating significance level ($p = (1+\#\text{null} \ge \text{obs})/(K+1) \le 0.01$). |
| `settlement.stockpile_enrichment_ratio_min` | `FixedPoint` | `"1.500000"` | Stockpile enrichment ratio threshold when bound. |
| `calibration_targets.false_positive_rate_max` | `FixedPoint` | `"0.030000"` | Pre-registered upper bound on false-positive rate across 200 uniform random worlds ($\le 3\%$). |
| `calibration_targets.power_min_at_3x` | `FixedPoint` | `"0.950000"` | Pre-registered minimum statistical power ($\ge 95\%$) at $3\times$ enrichment for $N=100$ and $N=300$. |
| `calibration_targets.uniform_null_worlds_count` | `int` | `200` | Sample size for false-positive rate calibration test. |
| `calibration_targets.power_test_worlds_count` | `int` | `100` | Sample size for statistical power calibration test. |
| `null_models.k_permutations` | `int` | `200` | Sample size for empirical null distribution allowing exact $p \le 0.01$ evaluation. |
| `null_models.default_analysis_seed` | `int` | `1337` | Fixed analysis PRNG seed for deterministic derivation of null permutations. |
| `group.*` (all parameters) | — | *Identical to v1* | Unchanged from v1. |
| `cultural_spread.*` (all parameters) | — | *Identical to v1* | Unchanged from v1. |

---

## 5. Control Worlds Pre-Registration Table

The test suite evaluates the following synthetic control worlds:

| Control World ID | Population ($N$) | Spatial Setup | Expected Verdict | Primary Gating Failure Reason |
| :--- | :--- | :--- | :--- | :--- |
| `dense_cluster_baseline` | 16 | Dense $4 \times 4$ cluster, 5-yr persistent, 50% native | **PASS** | — |
| `dense_cluster_100_agents`| 100 | Dense cluster at $(0,0)$ on $20 \times 20$ grid | **PASS** | — |
| `dense_cluster_300_agents`| 300 | Dense cluster at $(0,0)$ on $30 \times 30$ grid | **PASS** | — |
| `just_above_enrichment_floor` | 50 | Cluster with enrichment ratio $\approx 2.1\times$ | **PASS** | — |
| `outlier_wanderers_present` | 52 | Dense cluster (50) + 2 distant wanderers | **PASS** | Outliers do not alter verdict category |
| `saturated_uniform_random` | 300 | Uniform random dispersal, persistent members | **FAIL** | Fails scan significance and enrichment floor |
| `regular_lattice_overdispersed` | 100 | Exactly 1 agent per cell evenly spaced | **FAIL** | Fails scan significance and enrichment floor |
| `tiny_enrichment_large_population`| 1000 | $1.05\times$ slight density elevation | **FAIL** | Fails effect-size floor ($1.05 < 2.0$) |
| `dissolving_cluster` | 20 | Disperses by Year 3 | **FAIL** | Fails member Jaccard persistence |
| `immigrants_only` | 20 | Dense persistent cluster, 0% native births | **FAIL** | Fails generational anchoring ($0\% < 30\%$) |
| `undersized_cluster` | 6 | Dense persistent cluster of 6 agents | **FAIL** | Fails minimum size ($6 < 8$) |
| `oasis_resource_weighted_congregation`| 50 | Clustered on high-resource patch (steep gradient) | **FAIL** | Fails resource-weighted oasis null ($p > 0.01$) |
| `gentle_oasis_congregation` | 100 | Agents tracking 5x gentle oasis gradient | **FAIL** | Fails resource-weighted oasis null ($p > 0.01$) |
| `saturated_uniform_plus_wanderers` | 302 | 300 on $15 \times 10$ + 2 wanderers at $(50,50), (60,60)$ | **NOT_ASSESSED** / **FAIL** | Undeclared extent yields NOT_ASSESSED; declared extent yields FAIL ($p=1.0$) |

---

## 6. Limitations & Known False Negatives

1. **Pre-Registered Statistical Power Target at $3\times$ Enrichment Was Not Met in Empirical Curve:**
   - **Pre-Registered Target:** $\ge 95\%$ power at $3\times$ enrichment for $N=100$ and $N=300$.
   - **Empirical Power Curve Results:** The synthetic calibration curve realized **$20\%$ power at $N=100$** and **$0\%$ power at $N=300$** under the $3\times$ background density elevation scenario.
   - **Unambiguous Definition of "$3\times$ Enrichment":**
     - *Background Density Multiple:* Seeding a $5 \times 5$ window with $3\times$ the spatially uniform expected count $\lambda_{\text{bg}} = N \cdot \frac{25}{\text{Area}}$ (e.g. at $N=100$ on $20 \times 20$, $\lambda_{\text{bg}} = 6.25$, so $3\lambda_{\text{bg}} \approx 19$ agents).
     - *Ratio to Null Maximum Mean:* The test statistic's enrichment ratio is defined as $\frac{W_{\max}^{\text{obs}}}{\max(\bar{W}_{\text{unif}}, \bar{W}_{\text{res}})}$, where $\bar{W}_{\text{unif}}$ is the mean of the **maximum window count across the entire grid** over $K=200$ null permutations.
     - Because extreme Poisson-binomial spatial fluctuations across a multi-hundred cell grid produce maximum window counts substantially higher than the spatial average (for $N=100$, $\bar{W}_{\max}^{\text{null}} \approx 10.2$, whereas average window count is only $6.25$), an observed window count of $19$ agents yields an observed enrichment ratio of $\frac{19}{10.2} \approx 1.86 < 2.0$. It thus fails the effect-size floor ($2.0\times$), despite clearing the significance rank ($p \le 0.01$).
     - At $N=300$ on $30 \times 30$, expected background count per window is $\approx 8.33$, so $3\times$ seeding places $\approx 25$ agents; however, uniform null maximums average $\approx 15.6$, yielding an enrichment ratio of $\frac{25}{15.6} \approx 1.60 < 2.0$, also failing the effect-size floor.
   - **Limitation Statement:** Under the frozen v2 parameter set ($\text{min\_enrichment\_ratio} = 2.000000$), reliable detection ($\ge 95\%$ power) requires roughly **$5\times$ background density** at $N=100\text{--}300$ (e.g., $N=100$ at $5\times \implies 100\%$ power; $N=300$ at $5\times \implies 100\%$ power). In accordance with instructions, **no thresholds are changed**; this behavior is formally documented as a conservative sensitivity floor of the v2 metric.

2. **Elongated / Ribbon-Shaped Settlements (Known False Negative):**
   - The scan statistic evaluates $(2R+1) \times (2R+1)$ square windows ($5 \times 5$ cells for $R=2$). A dense, highly nucleated settlement configured as an elongated strip (e.g. $2 \times 12$ cells along a riverbank, road, or canyon) achieves statistical significance ($W_{\max} = 10 > P_{99} = 7$, $p \le 0.01$), but the square window captures only a fraction of its total population ($\le 10$ agents out of 24).
   - Consequently, the observed enrichment ratio is $1.974333\times$, narrowly failing the isotropic $2.000000\times$ effect-size floor.
   - This is documented as a known false negative of isotropic square scan windows; non-isotropic / directional kernels are left for future parameter sets to preserve the low computational complexity ($O(W \cdot H)$ integer prefix sums) and strict family-wise error rate control of v2.
