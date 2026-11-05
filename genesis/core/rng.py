"""GENESIS Deterministic PRNG Substrate.

Self-contained pure-integer xoshiro256** implementation.
Guarantees bit-identical random sequences across CPU architectures, OS platforms,
and Python versions without relying on Python's random or NumPy.
"""

from __future__ import annotations
from typing import Any, Dict, List, Sequence, TypeVar

from genesis.core.arithmetic import FixedPoint, SCALE

T = TypeVar("T")
MASK64 = 0xFFFFFFFFFFFFFFFF


def _rotl(x: int, k: int) -> int:
    """64-bit bitwise left rotation."""
    return (((x << k) & MASK64) | (x >> (64 - k))) & MASK64


class GenesisRNG:
    """Pure-integer xoshiro256** pseudo-random number generator with 256-bit state."""

    __slots__ = ("_s", "_step_count", "_initial_seed")

    def __init__(self, seed: int) -> None:
        self._initial_seed = seed & MASK64
        self._s: List[int] = [0, 0, 0, 0]
        self._step_count: int = 0
        self._seed_splitmix64(self._initial_seed)

    def _seed_splitmix64(self, seed: int) -> None:
        """Initialize 4 64-bit state words from seed using SplitMix64."""
        sm_state = seed & MASK64
        for i in range(4):
            sm_state = (sm_state + 0x9E3779B97F4A7C15) & MASK64
            z = sm_state
            z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & MASK64
            z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & MASK64
            self._s[i] = ((z ^ (z >> 31)) & MASK64) or 1  # ensure non-zero

    def next_uint64(self) -> int:
        """Generate the next 64-bit pseudo-random unsigned integer."""
        s0, s1, s2, s3 = self._s

        # result = rotl(s1 * 5, 7) * 9
        res = (_rotl((s1 * 5) & MASK64, 7) * 9) & MASK64

        t = (s1 << 17) & MASK64

        self._s[2] ^= s0
        self._s[3] ^= s1
        self._s[1] ^= s2
        self._s[0] ^= s3

        self._s[2] ^= t
        self._s[3] = _rotl(self._s[3], 45)

        self._step_count += 1
        return res

    def next_int_range(self, min_val: int, max_val: int) -> int:
        """Generate a random integer in inclusive range [min_val, max_val]."""
        if min_val > max_val:
            raise ValueError(f"min_val {min_val} cannot exceed max_val {max_val}")
        range_size = (max_val - min_val) + 1
        if range_size == 1:
            return min_val
        raw = self.next_uint64()
        return min_val + (raw % range_size)

    def next_fixed_point_unit(self) -> FixedPoint:
        """Generate a FixedPoint value in the range [0.000000, 1.000000]."""
        raw = self.next_uint64() % (SCALE + 1)
        return FixedPoint.from_raw(raw)

    def choice(self, seq: Sequence[T]) -> T:
        """Deterministically choose an item from a non-empty sequence."""
        if not seq:
            raise IndexError("Cannot choose from empty sequence")
        idx = self.next_int_range(0, len(seq) - 1)
        return seq[idx]

    @property
    def step_count(self) -> int:
        return self._step_count

    def get_state(self) -> Dict[str, Any]:
        """Serialize complete PRNG internal state vector as stringified hex."""
        return {
            "algorithm": "xoshiro256**",
            "initial_seed": str(self._initial_seed),
            "state": [f"{w:016x}" for w in self._s],
            "step_count": str(self._step_count),
        }

    def set_state(self, state_dict: Dict[str, Any]) -> None:
        """Restore complete PRNG internal state vector."""
        if state_dict.get("algorithm") != "xoshiro256**":
            raise ValueError(f"Unknown PRNG algorithm: {state_dict.get('algorithm')}")
        self._initial_seed = int(state_dict.get("initial_seed", "0"))
        self._s = [int(w, 16) & MASK64 for w in state_dict["state"]]
        self._step_count = int(state_dict["step_count"])
