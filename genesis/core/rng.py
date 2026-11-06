"""GENESIS Deterministic PRNG Substrate.

Self-contained pure-integer xoshiro256** implementation.
Guarantees bit-identical random sequences across CPU architectures, OS platforms,
and Python versions without relying on Python's random or NumPy.
"""

from __future__ import annotations
import hashlib
from typing import Any, Dict, List, Optional, Sequence, Tuple, TypeVar

from genesis.core.arithmetic import FixedPoint, SCALE

T = TypeVar("T")
MASK64 = 0xFFFFFFFFFFFFFFFF
GLOBAL_RULE_CELL_SENTINEL: Tuple[int, int] = (-9223372036854775808, -9223372036854775808)
RULE_STREAM_DOMAIN_TAG: bytes = b"genesis/rule-stream/v1"
FALLBACK_RNG_STATE: List[int] = [1, 1, 1, 1]


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

    def deterministic_shuffle(self, seq: Sequence[T]) -> List[T]:
        """Produce a new list with items deterministically shuffled using Fisher-Yates with xoshiro256**."""
        result = list(seq)
        for i in range(len(result) - 1, 0, -1):
            j = self.next_int_range(0, i)
            result[i], result[j] = result[j], result[i]
        return result

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

    @classmethod
    def from_state(
        cls, s0: int, s1: int, s2: int, s3: int, initial_seed: int = 0
    ) -> GenesisRNG:
        """Create a GenesisRNG instance directly from a 256-bit internal state vector."""
        rng = cls.__new__(cls)
        rng._initial_seed = initial_seed & MASK64
        rng._s = [s0 & MASK64, s1 & MASK64, s2 & MASK64, s3 & MASK64]
        if rng._s == [0, 0, 0, 0]:
            rng._s = list(FALLBACK_RNG_STATE)
        rng._step_count = 0
        return rng


def serialize_rule_stream_payload(
    world_seed: int,
    tick: int,
    rule_id: str,
    cell: Optional[Tuple[int, int]] = None,
    invocation_index: int = 0,
) -> bytes:
    """Serialize stream derivation inputs in a fixed, unambiguous byte format."""
    tag_bytes = RULE_STREAM_DOMAIN_TAG
    rule_id_bytes = rule_id.encode("utf-8")
    if cell is not None:
        cx, cy = cell[0], cell[1]
    else:
        cx, cy = GLOBAL_RULE_CELL_SENTINEL

    return (
        len(tag_bytes).to_bytes(4, "big")
        + tag_bytes
        + (world_seed & MASK64).to_bytes(8, "big")
        + (tick & MASK64).to_bytes(8, "big")
        + len(rule_id_bytes).to_bytes(4, "big")
        + rule_id_bytes
        + cx.to_bytes(8, "big", signed=True)
        + cy.to_bytes(8, "big", signed=True)
        + (invocation_index & 0xFFFFFFFF).to_bytes(4, "big")
    )


def derive_rule_stream(
    world_seed: int,
    tick: int,
    rule_id: str,
    cell: Optional[Tuple[int, int]] = None,
    invocation_index: int = 0,
) -> GenesisRNG:
    """Derive a deterministic per-invocation GenesisRNG stream from stable inputs.

    Inputs:
    - world_seed: original world seed, u64 big-endian
    - tick: current tick, u64 big-endian
    - rule_id: UTF-8 string with 4-byte big-endian length prefix
    - cell: (cell_x, cell_y) signed int64 big-endian each, or sentinel pair for global rules
    - invocation_index: u32 big-endian count of earlier invocations within this tick
    """
    payload = serialize_rule_stream_payload(world_seed, tick, rule_id, cell, invocation_index)
    digest = hashlib.sha256(payload).digest()
    s0 = int.from_bytes(digest[0:8], "big")
    s1 = int.from_bytes(digest[8:16], "big")
    s2 = int.from_bytes(digest[16:24], "big")
    s3 = int.from_bytes(digest[24:32], "big")

    if s0 == 0 and s1 == 0 and s2 == 0 and s3 == 0:
        s0, s1, s2, s3 = FALLBACK_RNG_STATE

    return GenesisRNG.from_state(s0, s1, s2, s3, initial_seed=world_seed)

