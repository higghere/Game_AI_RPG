"""GENESIS Phase 3 Agents Parameters Loader.

Loads, verifies, and provides access to frozen pre-registered agent parameters.
Enforces bit-for-bit SHA-256 hash pinning against the canonical specification.
"""

from __future__ import annotations
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Optional

DATA_DIR = Path(__file__).resolve().parent / "data"

FROZEN_AGENTS_PARAMS_V1_HASH: str = (
    "d6ce25cac9d58b15e5548b44c5285fde818d71a60306a6e453115839ec39c80e"
)

_CACHED_PARAMS_V1: Optional[Dict[str, Any]] = None


def compute_canonical_params_hash(params_dict: Dict[str, Any]) -> str:
    """Compute the SHA-256 hash over canonical JSON bytes (sort keys, indent 2, LF, UTF-8)."""
    canonical_str = json.dumps(params_dict, indent=2, sort_keys=True).replace("\r\n", "\n") + "\n"
    return hashlib.sha256(canonical_str.encode("utf-8")).hexdigest()


def load_agents_params(version: str = "v1", verify_hash: bool = True) -> Dict[str, Any]:
    """Load, validate, and return the agent parameters dictionary.

    Raises:
        FileNotFoundError: If parameter file does not exist.
        ValueError: If file content does not match the frozen hash.
    """
    global _CACHED_PARAMS_V1
    if version == "v1" and _CACHED_PARAMS_V1 is not None:
        return _CACHED_PARAMS_V1

    file_path = DATA_DIR / f"agents_params_{version}.json"
    if not file_path.is_file():
        raise FileNotFoundError(f"Agent parameter file not found: {file_path}")

    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if verify_hash and version == "v1":
        computed_hash = compute_canonical_params_hash(data)
        if computed_hash != FROZEN_AGENTS_PARAMS_V1_HASH:
            raise ValueError(
                f"Agent params v1 hash mismatch!\n"
                f"  Expected: {FROZEN_AGENTS_PARAMS_V1_HASH}\n"
                f"  Computed: {computed_hash}\n"
                f"The frozen specification has been modified without bumping the version."
            )

    if version == "v1":
        _CACHED_PARAMS_V1 = data

    return data
