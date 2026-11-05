"""GENESIS Simulation Clock.

Discrete monotonic integer tick counter.
1 tick = 1 day, 365 ticks = 1 year, no leap years.
"""

from __future__ import annotations
from typing import Any, Dict
from genesis.core.arithmetic import check_int64


class SimulationClock:
    """Discrete integer simulation clock."""

    __slots__ = ("_tick",)

    def __init__(self, initial_tick: int = 0) -> None:
        self._tick: int = check_int64(initial_tick)
        if self._tick < 0:
            raise ValueError("Simulation tick cannot be negative")

    @property
    def current_tick(self) -> int:
        return self._tick

    def advance_tick(self) -> int:
        """Advance the clock by exactly 1 tick (1 simulated day)."""
        self._tick = check_int64(self._tick + 1)
        return self._tick

    @staticmethod
    def ticks_to_days(ticks: int) -> int:
        return ticks

    @staticmethod
    def days_to_ticks(days: int) -> int:
        return days

    @staticmethod
    def ticks_to_years(ticks: int) -> int:
        return ticks // 365

    @staticmethod
    def years_to_ticks(years: int) -> int:
        return years * 365

    @staticmethod
    def day_of_year(ticks: int) -> int:
        return ticks % 365

    def to_dict(self) -> Dict[str, Any]:
        """Serialize clock state with integer formatted as decimal string."""
        return {
            "current_tick": str(self._tick),
            "simulated_days": str(self._tick),
            "simulated_years": str(self.ticks_to_years(self._tick)),
            "day_of_year": str(self.day_of_year(self._tick)),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> SimulationClock:
        tick_val = int(data["current_tick"])
        return cls(tick_val)

    def __repr__(self) -> str:
        return f"SimulationClock(tick={self._tick}, year={self.ticks_to_years(self._tick)}, day={self.day_of_year(self._tick)})"
