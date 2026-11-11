# GENESIS Calibration Log: Pre-100-Year Experiment Parameter Sweeps

This document records all calibration sweeps performed prior to executing the 100-year experiments (`TEST-303`, 36,500 ticks), detailing the hypotheses, parameters evaluated, population trajectories, peak touches, and results.

---

## 1. Context and Objective
Under the GENESIS Substrate Invariants:
- Substrate Quota Cap: **1,000 entities touched per tick**, **256 ops/rule invocation**.
- Closed Mass Conservation: strictly conserved ($\pm 0.000000$).
- Target: Pre-register a stable carrying capacity equilibrium that sustains long-term survival over 36,500 ticks (100 simulated years) without population collapse to zero and without approaching unsustainable congestion (>600 agents).

---

## 2. Pre-Run Calibration Sweeps

### Sweep 1: Single-Cell Quota Stress Calibration
- **Setup:** Single cell $(0, 0)$, 16 initial agents (8 pairs), 0 autotrophs.
- **Duration:** 50 ticks.
- **Hypothesis:** Test whether dense multi-agent co-location within a single cell violates the rule execution quota under high interaction density.
- **Results:**
  - Quota Failures: 263 `QuotaExceededError` events triggered in `AR_01_METABOLISM` and `AR_07_FORAGE_MOVE`.
  - Max cell density: 16 agents/cell.
- **Finding:** High spatial congestion in a single cell exhausts the per-rule budget guard (`256 ops/rule`). Dispersing founders across a grid is essential to maintain zero quota failures.

---

### Sweep 2: Low-Replenishment Severe Famine Calibration
- **Setup:** $10 \times 5$ spatial grid (50 cells), 100 founder agents (50 co-located breeding pairs), 50 autotroph plants (1 per cell).
- **Parameters:**
  - Autotroph Biomass Cap: `15.000000`
  - Replenishment Rate: `0.500000` biomass / tick
- **Duration:** 36,500 ticks (100 simulated years).
- **Results (from `experiments/task-4190.log`):**
  - Year 5 (tick 1,825): Population = 31 agents, Max/Cell = 2, Peak Touched = 150.
  - Year 10 (tick 3,650): Population = 0 agents (extinction at tick 2,190).
  - Years 15–100: Population = 0.
- **Finding:** A replenishment rate of 0.50 biomass/tick provides 25.0 total biomass influx per tick across 50 cells, which is insufficient to support 100 agents with basal metabolic draw (~30–40 biomass/tick total). Agents suffer caloric deficit, failing to reproduce and starving to death by Year 10.

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
- **Finding:** Replenishment of 2.00/tick caused runaway exponential population expansion, exceeding 600 agents and approaching 1,000 agents. This risks violating the substrate entity touch quota (1,000 entities/tick limit).

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

### Sweep 5: Pre-Registered Production Baseline Selection
Based on Sweep 4, the **`0.80` biomass/tick replenishment** and **`25.0` cap** regime was selected as the optimal carrying-capacity configuration:
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
