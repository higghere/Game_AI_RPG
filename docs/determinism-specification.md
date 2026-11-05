# GENESIS Alpha — Determinism Specification

**Version:** 3.1  
**Phase:** Phase 0 / Phase 1  
**Status:** Approved with Engineering Conditions  

---

## 1. The Core Law of Determinism

Determinism in GENESIS is an absolute invariance requirement:
> **Given the same initial world state, identical rule registry, and the same PRNG seed, the simulation must produce the exact same sequence of state mutations, event journals, and full-state SHA-256 digests across any arbitrary number of ticks on any supported hardware architecture (x86_64, ARM64) and operating system (Windows, Linux, macOS).**

A test that compares only population counts, entity counts, or approximate resource averages is **insufficient**. Alpha requires bit-identical matching of the canonical serialized world state and complete event ledger.

---

## 2. The Seven Determinism Protocols

### Protocol 1: Dedicated 64-Bit xoshiro256** PRNG
- **Prohibition of Host PRNGs:** Python's standard `random` (Mersenne Twister MT19937) and NumPy's RNG algorithms have evolved between minor Python/NumPy releases and rely on C-library specifics.
- **Specification:** The runtime implements a self-contained, pure integer `xoshiro256**` (Blackman and Vigna, 2018) PRNG.
- **State Representation:** 256-bit state represented as four 64-bit unsigned integers:
  $$\mathbf{S} = [s_0, s_1, s_2, s_3], \quad s_i \in [0, 2^{64}-1]$$
- **State Checkpointing:** The exact 4-word state vector and step counter are captured in every snapshot and restored bit-for-bit:
  ```json
  "rng_state": {
    "algorithm": "xoshiro256**",
    "state": ["0x123456789abcdef0", "0x0fedcba987654321", "0x4a5b6c7d8e9f0a1b", "0x2c3d4e5f6a7b8c9d"],
    "steps_generated": "10452"
  }
  ```
- **Bitwise Precision:** All operations are masked with `0xFFFFFFFFFFFFFFFF` (`uint64`), guaranteeing identical behavior across 32-bit and 64-bit systems, x86_64, and ARM64.

### Protocol 2: The JSON Number Precision Guard (Stringified 64-Bit Values)
- **The Problem:** RFC 8785 and standard IEEE-754 double precision floats (the default number format for JSON in JavaScript and many parsers) are exact only up to $2^{53} - 1 \approx 9.007 \times 10^{15}$. 
  - The GENESIS `int64` maximum is $9,223,372,036,854,775,807 \approx 9.22 \times 10^{18}$.
  - At fixed-point scale $10^6$, $2^{53}$ is reached at approximately 9 billion real units.
  - Standard JSON parsers silently round values $> 2^{53}$, resulting in silent hash desynchronization across machines.
- **The Mandatory Rule:**
  - **All `int64` and `FixedPoint` raw quantities are serialized as exact decimal strings** in canonical snapshots and event logs:
    ```json
    "quantity": "9223372036854775807",
    "fixed_scale": "1000000",
    "balance": "1500000"
    ```
  - Unbounded integer strings eliminate float truncation completely and ensure cross-language byte determinism.

### Protocol 3: Binary Mode, UTF-8, and Strict LF Line Endings
- **The Windows Newline Danger:** Windows standard I/O and text-mode file operations translate `\n` to `\r\n`. Any CRLF translation destroys cryptographic hash parity with Linux/macOS systems.
- **The Mandatory Rule:**
  - All serialized snapshots, event logs, and state digests are emitted and ingested in **binary mode** (`'wb'` / `'rb'`).
  - Text encoding is strictly **UTF-8** with **LF line endings (`\n`, byte `0x0A`)** and zero carriage returns (`\r`, byte `0x0D`).

### Protocol 4: Append-Only Cryptographic Event Hash Chain
- The event log is an immutable hash chain (Merkle-like journal).
- Every event entry $E_i$ includes:
  $$H_i = \text{SHA-256}(H_{i-1} \,\|\, \text{CanonicalBytes}(E_i))$$
  where $H_0 = \text{SHA-256}(\text{"GENESIS_GENESIS_BLOCK"})$.
- Any retroactive tampering, insertion, deletion, or re-ordering of past events breaks the hash chain at the point of modification.

### Protocol 5: Deterministic Entity Iteration Order
- Entity collections are never iterated using arbitrary hash table or dictionary insertion orders.
- Whenever entities are queried, filtered, or looped over in GRL, they are sorted strictly by their immutable 64-bit integer `EntityID` ascending:
  $$\text{Iteration Order} = [E_1, E_2, \dots, E_n] \quad \text{where } \text{ID}(E_i) < \text{ID}(E_{i+1})$$

### Protocol 6: Deterministic Rule Execution Order and Rollback Scope
- **Execution Order:** Active rules in the registry are sorted deterministically before evaluation:
  $$\text{Rule Order} = (\text{priority} \downarrow, \text{rule\_id} \uparrow)$$
- **Rollback Scope (Single Rule):** When a rule violates an operational quota ($\le 256$ operations, $\le 1000$ touched entities) or fails a precondition/invariant:
  1. The **single offending rule** is aborted and its staged mutations are rolled back.
  2. The world state is restored to the exact state immediately preceding that rule's execution.
  3. A structured `RuleExecutionFailureEvent` is recorded in the event log.
  4. Subsequent rules continue execution in their deterministic order.
  5. The tick does **not** fail in its entirety unless a global settlement invariant fails.

### Protocol 7: Atomic File Persistence
To prevent corrupt snapshots or partial writes during power loss or abrupt termination:
1. Snapshots and event blocks are written to a temporary sibling file: `filename.tmp`.
2. The buffer is flushed to disk via `flush()` and `os.fsync()`.
3. The file is atomically renamed via `os.replace(temp_path, final_path)`.

---

## 3. Self-Contained xoshiro256** Algorithm Specification

The `xoshiro256**` algorithm is implemented in pure Python using exact 64-bit arithmetic:

```python
def rotl(x: int, k: int) -> int:
    return ((x << k) & 0xFFFFFFFFFFFFFFFF) | (x >> (64 - k))

class Xoshiro256StarStar:
    """Pure integer xoshiro256** PRNG with 256-bit state."""
    __slots__ = ("s", "step_count")

    def __init__(self, seed: int):
        self.s = [0, 0, 0, 0]
        self.step_count = 0
        self._seed_splitmix64(seed)

    def _seed_splitmix64(self, seed: int) -> None:
        # Standard SplitMix64 initialization
        sm_state = seed & 0xFFFFFFFFFFFFFFFF
        for i in range(4):
            sm_state = (sm_state + 0x9E3779B97F4A7C15) & 0xFFFFFFFFFFFFFFFF
            z = sm_state
            z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & 0xFFFFFFFFFFFFFFFF
            z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & 0xFFFFFFFFFFFFFFFF
            self.s[i] = (z ^ (z >> 31)) & 0xFFFFFFFFFFFFFFFF

    def next_uint64(self) -> int:
        s0, s1, s2, s3 = self.s
        result = (rotl((s1 * 5) & 0xFFFFFFFFFFFFFFFF, 7) * 9) & 0xFFFFFFFFFFFFFFFF
        t = (s1 << 17) & 0xFFFFFFFFFFFFFFFF

        self.s[2] ^= s0
        self.s[3] ^= s1
        self.s[1] ^= s2
        self.s[0] ^= s3

        self.s[2] ^= t
        self.s[3] = rotl(self.s[3], 45)
        self.step_count += 1
        return result

    def get_state(self) -> dict:
        return {
            "algorithm": "xoshiro256**",
            "state": [f"{v:016x}" for v in self.s],
            "step_count": str(self.step_count)
        }

    def set_state(self, state_dict: dict) -> None:
        self.s = [int(v, 16) for v in state_dict["state"]]
        self.step_count = int(state_dict["step_count"])
```

---

## 4. Integer Fixed-Point Arithmetic (Scale $10^6$, Half-Even)

```python
SCALE = 1_000_000

def half_even_div(numerator: int, denominator: int) -> int:
    """Exact integer division with round-half-to-even (banker's rounding)."""
    if denominator == 0:
        raise ZeroDivisionError("FixedPoint division by zero")
    
    sign = -1 if (numerator < 0) ^ (denominator < 0) else 1
    num = abs(numerator)
    den = abs(denominator)

    quotient = num // den
    remainder = num % den
    twice_rem = remainder * 2

    if twice_rem > den:
        quotient += 1
    elif twice_rem == den:
        if quotient % 2 != 0:
            quotient += 1

    return sign * quotient
```
