# GENESIS Calibration Log: Pre-100-Year Experiment Parameter Sweeps

This document records all calibration sweeps performed prior to executing the 100-year experiments (`TEST-303`, 36,500 ticks), detailing the hypotheses, parameters evaluated, population trajectories, peak touches, and results.

---

## 1. Context and Invariants
Under the GENESIS Substrate Invariants:
- Substrate Quota Cap: **1,000 entities touched per tick**, **256 ops/rule invocation**.
- Closed Mass Conservation: strictly conserved ($\pm 0.000000$).
- Target: Calibrate a sustainable carrying-capacity equilibrium that maintains long-term survival over 36,500 ticks (100 simulated years) without population collapse to zero and without approaching unsustainable congestion (>600 agents).

---

## 2. Pre-Run Calibration Sweeps

### Sweep 1: Single-Cell Quota Stress Calibration
- **Setup:** Single cell $(0, 0)$, 16 initial agents (8 pairs), 0 autotrophs.
- **Duration:** 50 ticks.
- **Hypothesis:** Test whether dense multi-agent co-location within a single cell violates rule execution quotas under high interaction density.
- **Results & Reconciled Failure Mode:**
  - 263 `QuotaExceededError` events occurred.
  - **Root Cause & Rule Interaction:** When 16 agents occupied $(0, 0)$, `AR_05_REPRODUCE` attempted to evaluate all 16 candidate mates in the cell without a search ceiling, consuming 257 operations (exceeding the 256 ops/rule limit). Concurrently, `AR_07_FORAGE_MOVE` and `AR_01_METABOLISM` encountered excessive candidate evaluation density.
  - **Resolution:** Motivated two coordinated fixes: (1) adding `find_entity_max_scan: 3` and mate pre-filtering in `AR_05_REPRODUCE` to cap mate searches, and (2) dispersing founder populations across a spatial grid (e.g. $10 \times 5$) to prevent unnatural single-cell congestion.

---

### Sweep 2: Low-Replenishment Severe Famine Calibration
- **Setup:** $10 \times 5$ spatial grid (50 cells), 100 founder agents (50 co-located breeding pairs), 50 autotroph plants (1 per cell).
- **Parameters:**
  - Autotroph Biomass Cap: `15.000000`
  - Replenishment Rate: `0.500000` biomass / tick
- **Duration:** 36,500 ticks (100 simulated years).
- **Results (from `experiments/task-4190.log`):**
  - Year 5 (tick 1,825): Population = 31 agents, Max/Cell = 2, Peak Touched = 150.
  - Year 10 (tick 3,650): Population = 0 agents (complete extinction occurred at tick 2,190).
  - Years 15–100: Population = 0.
- **Finding:** A replenishment rate of 0.50 biomass/tick yields only 25.0 aggregate biomass influx per tick across 50 cells, which is insufficient to sustain the basal metabolic burn of ~100 agents (~30–40 biomass/tick aggregate). Agents suffered severe caloric deficit and starved to death by Year 10.

---

### Sweep 3: High-Replenishment Unbounded Growth Calibration
- **Setup:** $10 \times 5$ spatial grid, 100 founder agents (50 pairs), 50 autotroph plants.
- **Parameters:**
  - Autotroph Biomass Cap: `25.000000`
  - Replenishment Rate: `2.000000` biomass / tick
- **Duration:** 7,300 ticks (20 simulated years).
- **Results:**
  - Year 5 (tick 1,825): Population = 284 agents.
  - Year 10 (tick 3,650): Population = 512 agents.
  - Year 20 (tick 7,300): Population = 863 agents.
- **Finding:** Replenishment of 2.00/tick drove rapid exponential population expansion, exceeding 600 agents and approaching 1,000 agents. This risked violating the substrate entity touch quota (1,000 entities/tick limit).

---

### Sweep 4: Intermediate Replenishment Systematic Sweep
- **Setup:** $10 \times 5$ spatial grid, 100 founder agents (50 pairs), 50 autotroph plants, Cap = `25.000000`.
- **Duration:** 3,650 ticks (10 simulated years each).
- **Evaluated Replenishment Rates:** `0.80`, `1.00`, and `1.20` biomass / tick.
- **Results (from `experiments/task-4232.log`):**

| Replenishment Rate | Year 2 Pop | Year 4 Pop | Year 6 Pop | Year 8 Pop | Year 10 Pop | Max / Cell | Peak Touched | Dynamics Observed |
|:-------------------|:-----------|:-----------|:-----------|:-----------|:------------|:-----------|:-------------|:-------------------|
| **0.80 / tick**    | 154        | 150        | 157        | 151        | 155         | 6–7        | 210          | **Stable carrying capacity equilibrium** (fluctuates gently around ~150) |
| **1.00 / tick**    | 186        | 82         | 89         | 76         | 69          | 4–7        | 278          | Boom-bust oscillations (initial surge to 186 followed by sharp famine crash) |
| **1.20 / tick**    | 240        | 98         | 112        | 85         | 72          | 5–8        | 340          | Severe oscillations; over-consumption depletes resource stocks |

---

### Sweep 5: Calibrated Setup Selection
Based on the empirical sweeps (Sweeps 1–4), the **`0.80` biomass/tick replenishment** and **`25.0` cap** regime was selected as the **calibrated setup** for production experiments:
1. **100-Founder Experiment (`experiments/run_100y_founder_experiment.py`):**
   - Grid: $10 \times 5$ (50 cells).
   - Founders: 100 (50 pairs).
   - Resources: 50 autotrophs, cap 25.0, repl 0.80/tick.
   - 100-Year Trajectory: Population maintained between 143 and 162 throughout all 36,500 ticks.
   - Peak Cell Density: 9 agents / cell.
   - Peak Touched / Tick: 210 entities (well within 1,000 quota).
   - Quota Failures: **0**.
2. **300-Agent Growing Experiment (`experiments/run_300agent_100y_experiment.py`):**
   - Grid: $15 \times 10$ (150 cells).
   - Initial Agents: 300 (150 pairs).
   - Resources: 150 autotrophs, cap 25.0, repl 0.80/tick.
   - 100-Year Trajectory: Population maintained between 470 and 503 throughout all 36,500 ticks.
   - Peak Cell Density: 11 agents / cell.
   - Peak Touched / Tick: 671 entities (within 1,000 quota).
   - Quota Failures: **10** (out of 36,500 ticks).

---

## 3. Reconciliation of Parameter Change Rationales

### 1. Locomotion Energy Deduction Removal (`AR_07_FORAGE_MOVE`, $2.0 \to 0.0$)
- **Immediate Empirical Driver:** In `TEST-304`, wandering agents burned $2.0$ energy per foraging movement step in addition to basal metabolism. Unsupplied agents exhausted their energy reserve by tick 58 rather than dying within the pre-registered $[95, 105]$ tick starvation window.
- **Secondary Methodological Effect:** In `TEST-306`, removing locomotion energy cost eliminated movement frequency as an uncontrolled kinetic confound, isolating basal `metabolic_rate` as the sole variable energy expenditure.
- **Synthesis:** The change was originally motivated by calibration against `TEST-304` starvation mortality timing, and subsequently recognized as essential to ensure clean, unconfounded metabolic rate comparisons in `TEST-306`.

### 2. Schema `age` Property Addition (`agent.json`, INT64)
- **Immediate Empirical Driver:** When Phase 3 agents were initially co-located with Phase 2 ecosystem organisms prior to schema-based rule gating, `BR_03_BASAL_METABOLISM` iterated over all cell entities and queried `organism.age`, causing an `UnknownPropertyError` because agents only defined `age_ticks`.
- **Subsequent Evolution:** With Phase 3d implementing declarative schema-level decoupling via `is_agent` (so `BR_03` and `BR_05` strictly ignore agents), `age` was no longer queried by ecosystem rules. However, `age` was retained in `agent.json` to mirror `age_ticks // 365` for emergence analysis bindings (`AnalysisBinding`) and backward compatibility.
