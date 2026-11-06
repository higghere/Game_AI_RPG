"""GENESIS Layer 2 Ecosystem Package.

Declarative ecological ontology, data loaders, and ecosystem metrics.
Contains zero organism-specific Python classes.
"""

from genesis.ecosystem.loader import (
    load_ecosystem,
    load_ecosystem_rules,
    load_ecosystem_resources,
    load_ecosystem_schemas,
)
from genesis.ecosystem.metrics import get_ecosystem_metrics

__all__ = [
    "load_ecosystem",
    "load_ecosystem_rules",
    "load_ecosystem_resources",
    "load_ecosystem_schemas",
    "get_ecosystem_metrics",
]
