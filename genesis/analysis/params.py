"""GENESIS Pre-Registered Emergence Parameters Loader & Integrity Verifier.

Loads hash-pinned emergence parameter files and guarantees version immutability.
"""

from __future__ import annotations
import hashlib
import json
from pathlib import Path
from typing import Any, Dict

FROZEN_PARAMS_V1_HASH: str = (
    "9dc8c96b152a63d118070a2c15dbea0806522a1a0e391477a2b895ea55548591"
)

_CACHED_PARAMS_V1: Dict[str, Any] = {}


def get_params_file_path(version: str = "v1") -> Path:
    """Return the filesystem path to the requested parameter file."""
    data_dir = Path(__file__).resolve().parent / "data"
    return data_dir / f"emergence_params_{version}.json"


def compute_canonical_params_hash(params_dict: Dict[str, Any]) -> str:
    """Compute the SHA-256 hash over canonical JSON bytes (sort keys, indent 2, LF, UTF-8)."""
    canonical_str = json.dumps(params_dict, indent=2, sort_keys=True).replace("\r\n", "\n") + "\n"
    return hashlib.sha256(canonical_str.encode("utf-8")).hexdigest()


def load_emergence_params(version: str = "v1", verify_hash: bool = True) -> Dict[str, Any]:
    """Load, validate, and return the emergence parameters dictionary.

    Raises:
        FileNotFoundError: If parameter file does not exist.
        ValueError: If file content does not match the frozen hash.
    """
    global _CACHED_PARAMS_V1
    if version == "v1" and _CACHED_PARAMS_V1:
        return _CACHED_PARAMS_V1

    params_path = get_params_file_path(version)
    if not params_path.is_file():
        raise FileNotFoundError(f"Emergence parameters file not found: {params_path}")

    with open(params_path, "r", encoding="utf-8") as f:
        data: Dict[str, Any] = json.load(f)

    if verify_hash and version == "v1":
        actual_hash = compute_canonical_params_hash(data)
        if actual_hash != FROZEN_PARAMS_V1_HASH:
            raise ValueError(
                f"Emergence params v1 hash mismatch: expected {FROZEN_PARAMS_V1_HASH}, "
                f"got {actual_hash}. Emergence parameters are frozen and immutable!"
            )

    if version == "v1":
        _CACHED_PARAMS_V1 = data

    return data
