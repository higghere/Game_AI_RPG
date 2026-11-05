# GENESIS Alpha — Phase 1 Acceptance Tests Specification

**Version:** 3.1  
**Phase:** Phase 0 / Phase 1  
**Status:** Approved with Engineering Conditions  

---

## 1. Acceptance Test Protocol

Phase 1 requires that **all 14 acceptance tests** plus the **historical immutability test** pass completely with real, executable test code and recorded output.

Key verification standards:
- All snapshots and journal records are written in **binary mode with UTF-8 and LF line endings (`\n`)**.
- All `int64` and `FixedPoint` values are serialized as **decimal strings** to prevent IEEE-754 precision loss.
- PRNG tests use the custom integer **xoshiro256\*\*** implementation.
- Over-quota rule evaluation tests verify **single-rule rollback** without corrupting the state of prior or subsequent rules.
- Test 14 directly tests filesystem boundaries, parameter injection, and limits isolation on Windows.
- Event log tests verify the **append-only SHA-256 hash chain**.

---

## 2. Test Catalog

### AT-01: Create an Entity Type Not Hardcoded in the Application
- **Objective:** Verify dynamic entity type registration and instantiation.
- **Verification:** Register dynamic type `"mineral_deposit"`, instantiate entities, query them by type, verify monotonic `EntityID` sequence (`1`, `2`).

### AT-02: Add Dynamically Defined Properties
- **Objective:** Verify typed dynamic properties (`INT64`, `FIXED_POINT`, `BOOLEAN`, `STRING`, `ENUM`) with validation and decimal string serialization.
- **Verification:** Register properties, set valid values, attempt invalid types and out-of-range bounds, assert clean validation failures.

### AT-03: Create Relationships Between Entities
- **Objective:** Verify dynamic creation, querying, and removal of weighted directed edges.
- **Verification:** Link entities with edge types and fixed-point weights, query outgoing/incoming relations (deterministically ordered by `target_id`), delete edge and verify cleanup.

### AT-04: Execute a Valid GRL Rule
- **Objective:** Verify execution of a valid JSON AST rule mutating entities and resources.
- **Verification:** Create target entity and resource pool, execute rule that consumes resource and adjusts property, verify post-tick state and event ledger record.

### AT-05: Reject Syntactically Invalid GRL
- **Objective:** Reject malformed AST payloads with structured errors before execution.
- **Verification:** Submit AST with missing fields, unknown operators, or invalid data types; assert structured `GRLValidationError` with zero mutations applied.

### AT-06: Reject a Rule Exceeding 256 Operations
- **Objective:** Enforce the $\le 256$ operations ceiling per rule execution with single-rule rollback.
- **Verification:** Submit rule that executes $> 256$ operations; assert `QuotaExceededError`, verify partial changes are rolled back, and state matches pre-rule state.

### AT-07: Reject Loop Nesting Beyond Depth 4
- **Objective:** Statically reject GRL rules with loop depth $> 4$.
- **Verification:** Validate rule with 4 nested loops (passes); validate rule with 5 nested loops (fails static AST check with structured error).

### AT-08: Reject Recursion
- **Objective:** Statically and dynamically prohibit recursion.
- **Verification:** Assert absence of recursive grammar nodes; attempt recursive AST structures and verify parser rejection.

### AT-09: Reject a Rule Exceeding 1,000 Touched Entities Per Tick
- **Objective:** Enforce $\le 1000$ unique entities touched per rule per tick (reads count).
- **Verification:** Query across 1,100 entities; verify halt at entity 1,001 with `QuotaExceededError` and single-rule rollback.

### AT-10: Save and Reload Simulation State
- **Objective:** Verify lossless atomic state persistence using canonical JSON with decimal string quantities.
- **Verification:** Run simulation for 50 ticks, save snapshot, restore into a fresh instance, verify exact equality of all entities, pools, and clock.

### AT-11: Reproduce an Identical Run From the Same Seed
- **Objective:** Verify identical runs using the xoshiro256** PRNG.
- **Verification:** Run two separate 100-tick simulations from seed $S = 42$; verify identical state attributes and counts at every tick.

### AT-12: Match Full-State SHA-256 Hashes Across Two Independent Runs
- **Objective:** Bit-level cross-run hash determinism.
- **Verification:** Run two independent simulations with seed $S = 9999$ for 100 ticks; compute SHA-256 of canonical state and event hash chain; assert identical digests.

### AT-13: Verify RNG State Persists Correctly Across Save and Reload
- **Objective:** Verify xoshiro256** state persistence prevents drift after save/reload.
- **Verification:** Continuous run 0 to 100 ticks matches tick 0 to 50 + save + reload + 50 to 100 ticks bit-for-bit.

### AT-14: Verify Runtime Boundary and Isolation
- **Objective:** Verify security boundaries against malicious inputs.
- **Verification:** Attempt path traversal strings in properties, attempt limit tampering in rules, attempt integer overflows ($> 2^{63}-1$), and verify that all are rejected without side effects.

---

## 3. Historical Immutability Test

- **Protocol:**
  1. Advance simulation to tick $T = 50$.
  2. Compute canonical SHA-256 of the event hash chain up to tick 50 ($H_{50}$).
  3. Save canonical snapshot $S_{50}$.
  4. Install a new valid GRL rule at tick 50 (effective at tick 51).
  5. Advance simulation to tick 100.
  6. Recompute hash of event history slice $0 \dots 50$; verify it equals $H_{50}$.
  7. Verify snapshot $S_{50}$ is bit-for-bit unchanged.
