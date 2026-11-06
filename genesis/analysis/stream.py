"""GENESIS Analysis PRNG Stream Derivation.

Derives an isolated, deterministic GenesisRNG stream for statistical null models
without ever reading or advancing the simulation's world.rng or rule streams.
"""

from __future__ import annotations
import hashlib
import struct

from genesis.core.rng import GenesisRNG

ANALYSIS_DOMAIN_TAG: bytes = b"genesis/analysis-stream/v1"


def derive_analysis_stream(
    analysis_seed: int,
    domain_label: str,
    iteration_index: int = 0,
    extra_tag: str = "",
) -> GenesisRNG:
    """Derive an independent GenesisRNG stream for analysis null models.

    Inputs are hashed with SHA-256 under domain tag 'genesis/analysis-stream/v1'.
    The 32-byte digest initializes the 256-bit state vector (s0, s1, s2, s3) of GenesisRNG.
    This guarantees that analysis computations are completely decoupled from
    world simulation RNG streams.
    """
    hasher = hashlib.sha256()
    hasher.update(ANALYSIS_DOMAIN_TAG)
    hasher.update(b"\x00")
    hasher.update(analysis_seed.to_bytes(8, byteorder="big", signed=True))
    hasher.update(b"\x00")
    hasher.update(domain_label.encode("utf-8"))
    hasher.update(b"\x00")
    hasher.update(iteration_index.to_bytes(8, byteorder="big", signed=False))
    hasher.update(b"\x00")
    hasher.update(extra_tag.encode("utf-8"))

    digest = hasher.digest()
    s0, s1, s2, s3 = struct.unpack(">QQQQ", digest)
    return GenesisRNG.from_state(s0, s1, s2, s3, initial_seed=analysis_seed)
