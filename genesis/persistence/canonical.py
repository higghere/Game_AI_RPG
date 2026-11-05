"""GENESIS Canonical Serialization Substrate.

Implements strict canonical serialization based on RFC 8785 rules:
- Lexicographically sorted dictionary keys.
- No extraneous whitespace: separators=(',', ':').
- UTF-8 binary encoding with strict LF (\\n) line endings.
- All 64-bit integers and FixedPoint values encoded as exact decimal strings
  to bypass IEEE-754 2^53 precision limits in standard JSON parsers.
"""

from __future__ import annotations
import json
from typing import Any, Dict

from genesis.core.arithmetic import FixedPoint


def _canonicalize_value(val: Any) -> Any:
    """Recursively convert values to canonical representations."""
    if isinstance(val, FixedPoint):
        return {"__type__": "FIXED_POINT", "val": val.to_raw_string()}
    elif isinstance(val, int) and not isinstance(val, bool):
        return str(val)
    elif isinstance(val, dict):
        return {k: _canonicalize_value(v) for k, v in sorted(val.items())}
    elif isinstance(val, (list, tuple)):
        return [_canonicalize_value(item) for item in val]
    return val


def canonical_json_bytes(data: Dict[str, Any]) -> bytes:
    """Serialize dictionary into canonical UTF-8 bytes with LF line endings."""
    canonical_obj = _canonicalize_value(data)
    json_str = json.dumps(
        canonical_obj,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    # Ensure strict LF ending without carriage return
    clean_str = json_str.replace("\r\n", "\n").replace("\r", "\n") + "\n"
    return clean_str.encode("utf-8")


def canonical_json_string(data: Dict[str, Any]) -> str:
    """Return canonical JSON string representation."""
    return canonical_json_bytes(data).decode("utf-8")
