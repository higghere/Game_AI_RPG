"""GENESIS Cryptographic State Hasher.

Calculates SHA-256 digests over canonical binary serialized states and files.
"""

from __future__ import annotations
import hashlib
from typing import Any, Dict

from genesis.persistence.canonical import canonical_json_bytes


def compute_canonical_hash(data: Dict[str, Any]) -> str:
    """Compute SHA-256 over canonical UTF-8 LF bytes of a data dictionary."""
    b = canonical_json_bytes(data)
    return hashlib.sha256(b).hexdigest()


def compute_file_hash(filepath: str) -> str:
    """Read file in binary mode and compute its SHA-256 digest."""
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()
