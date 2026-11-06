"""GENESIS Runtime Configuration.

Immutable, versioned runtime specifications maintained by humans.
GENESIS has zero authority to alter these constants.
"""

from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True)
class RuntimeConfig:
    """Immutable runtime configuration specifications."""

    # GRL Quotas
    max_operations_per_rule: int = 256
    max_loop_depth: int = 4
    recursion_allowed: bool = False
    max_entities_touched_per_tick: int = 1000

    # Simulation & Calendar
    tick_unit: str = "day"
    ticks_per_year: int = 365
    leap_years: bool = False

    # Arithmetic & Numerical Limits
    fixed_point_scale: int = 1_000_000
    division_rounding: str = "half_even"
    min_quantity: int = 0
    max_quantity: int = 9_223_372_036_854_775_807  # 2^63 - 1 (int64 max)
    min_int64: int = -9_223_372_036_854_775_808
    max_int64: int = 9_223_372_036_854_775_807

    # Phase 5 / Emergence Constants (for future specification alignment)
    max_correction_retries: int = 3
    proposals_per_experiment: int = 20
    target_accepted: int = 1
    null_model_paired_seeds: int = 30
    null_percentile: int = 95

    # System Identification
    runtime_version: str = "0.3.0"
    schema_version: str = "1.0.0"

    # Journal & Audit Policy
    audit_level: str = "SUMMARY"  # MINIMAL, SUMMARY, TRACE


DEFAULT_CONFIG: Final[RuntimeConfig] = RuntimeConfig()
