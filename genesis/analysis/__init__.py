"""GENESIS Emergence Analysis Package.

Provides pre-registered quantitative definitions and deterministic measurement tools
for detecting emergent Settlement, Group, and Cultural Spread phenomena in GENESIS.
"""

from genesis.analysis.binding import AnalysisBinding
from genesis.analysis.params import (
    load_emergence_params,
    compute_canonical_params_hash,
    FROZEN_PARAMS_V1_HASH,
)
from genesis.analysis.stream import derive_analysis_stream
from genesis.analysis.settlement import evaluate_settlement
from genesis.analysis.group import evaluate_group
from genesis.analysis.culture import evaluate_cultural_spread
from genesis.analysis.metrics import (
    measure_settlement,
    measure_group,
    measure_cultural_spread,
)

__all__ = [
    "AnalysisBinding",
    "load_emergence_params",
    "compute_canonical_params_hash",
    "FROZEN_PARAMS_V1_HASH",
    "derive_analysis_stream",
    "evaluate_settlement",
    "evaluate_group",
    "evaluate_cultural_spread",
    "measure_settlement",
    "measure_group",
    "measure_cultural_spread",
]
