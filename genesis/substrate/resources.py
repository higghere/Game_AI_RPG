"""GENESIS Resource Accounting Substrate.

Provides conservation-checked, non-negative FixedPoint resource reservoirs
with atomic transfer semantics.
"""

from __future__ import annotations
from typing import Any, Dict, List, Optional

from genesis.core.arithmetic import FixedPoint, MAX_INT64
from genesis.core.config import DEFAULT_CONFIG
from genesis.core.errors import ResourceOverflowError, ResourceUnderflowError


class ResourcePool:
    """A bounded reservoir for a generic continuous resource quantity."""

    __slots__ = ("name", "_balance", "_min_capacity", "_max_capacity")

    def __init__(
        self,
        name: str,
        initial_balance: Optional[FixedPoint] = None,
        min_capacity: Optional[FixedPoint] = None,
        max_capacity: Optional[FixedPoint] = None,
    ) -> None:
        self.name = name
        self._min_capacity = min_capacity if min_capacity is not None else FixedPoint.from_int(DEFAULT_CONFIG.min_quantity)
        self._max_capacity = max_capacity if max_capacity is not None else FixedPoint.from_raw(DEFAULT_CONFIG.max_quantity)
        
        balance = initial_balance if initial_balance is not None else FixedPoint.from_int(0)
        self._validate_balance(balance)
        self._balance = balance

    @property
    def balance(self) -> FixedPoint:
        return self._balance

    @property
    def min_capacity(self) -> FixedPoint:
        return self._min_capacity

    @property
    def max_capacity(self) -> FixedPoint:
        return self._max_capacity

    def _validate_balance(self, val: FixedPoint) -> None:
        if val < self._min_capacity:
            raise ResourceUnderflowError(
                f"ResourcePool '{self.name}' balance {val} drops below min {self._min_capacity}"
            )
        if val > self._max_capacity:
            raise ResourceOverflowError(
                f"ResourcePool '{self.name}' balance {val} exceeds max {self._max_capacity}"
            )

    def produce(self, amount: FixedPoint) -> FixedPoint:
        """Add resources to pool."""
        if amount.raw_value < 0:
            raise ValueError(f"produce amount cannot be negative: {amount}")
        new_balance = self._balance + amount
        self._validate_balance(new_balance)
        self._balance = new_balance
        return self._balance

    def consume(self, amount: FixedPoint) -> FixedPoint:
        """Deduct resources from pool."""
        if amount.raw_value < 0:
            raise ValueError(f"consume amount cannot be negative: {amount}")
        new_balance = self._balance - amount
        self._validate_balance(new_balance)
        self._balance = new_balance
        return self._balance

    def set_balance(self, amount: FixedPoint) -> None:
        self._validate_balance(amount)
        self._balance = amount

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "balance": self._balance.to_raw_string(),
            "min_capacity": self._min_capacity.to_raw_string(),
            "max_capacity": self._max_capacity.to_raw_string(),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ResourcePool:
        return cls(
            name=data["name"],
            initial_balance=FixedPoint.from_raw(int(data["balance"])),
            min_capacity=FixedPoint.from_raw(int(data["min_capacity"])),
            max_capacity=FixedPoint.from_raw(int(data["max_capacity"])),
        )


class ResourceRegistry:
    """Manages all global resource pools and enforces cross-pool conservation."""

    def __init__(self) -> None:
        self._pools: Dict[str, ResourcePool] = {}

    def create_pool(
        self,
        name: str,
        initial_balance: Optional[FixedPoint] = None,
        min_capacity: Optional[FixedPoint] = None,
        max_capacity: Optional[FixedPoint] = None,
    ) -> ResourcePool:
        pool = ResourcePool(name, initial_balance, min_capacity, max_capacity)
        self._pools[name] = pool
        return pool

    def get_pool(self, name: str) -> Optional[ResourcePool]:
        return self._pools.get(name)

    def has_pool(self, name: str) -> bool:
        return name in self._pools

    def transfer(self, from_pool_name: str, to_pool_name: str, amount: FixedPoint) -> None:
        """Atomically transfer resources between two pools."""
        if from_pool_name not in self._pools:
            raise KeyError(f"Source pool '{from_pool_name}' does not exist")
        if to_pool_name not in self._pools:
            raise KeyError(f"Target pool '{to_pool_name}' does not exist")
        if amount.raw_value < 0:
            raise ValueError(f"Transfer amount cannot be negative: {amount}")

        source = self._pools[from_pool_name]
        target = self._pools[to_pool_name]

        # Check preconditions before modifying
        source._validate_balance(source.balance - amount)
        target._validate_balance(target.balance + amount)

        # Apply atomically
        source.consume(amount)
        target.produce(amount)

    def audit_invariants(self) -> None:
        """Ensure all pools meet their non-negativity and max capacity constraints."""
        for pool in self._pools.values():
            pool._validate_balance(pool.balance)

    def all_pools(self) -> List[ResourcePool]:
        return [self._pools[k] for k in sorted(self._pools.keys())]

    def to_dict(self) -> Dict[str, Any]:
        return {k: self._pools[k].to_dict() for k in sorted(self._pools.keys())}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ResourceRegistry:
        reg = cls()
        for name, pdata in data.items():
            reg._pools[name] = ResourcePool.from_dict(pdata)
        return reg
