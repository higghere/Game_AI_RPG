"""GENESIS Fixed-Point Arithmetic and Checked Integer Math.

Strictly deterministic 64-bit integer arithmetic with scale 10^6.
Eliminates all IEEE-754 floating-point drift across CPU architectures.
"""

from __future__ import annotations
import math
from typing import Final, Union

from genesis.core.errors import ArithmeticRangeError, DivisionByZeroError

SCALE: Final[int] = 1_000_000
MIN_INT64: Final[int] = -9_223_372_036_854_775_808
MAX_INT64: Final[int] = 9_223_372_036_854_775_807


def check_int64(val: int) -> int:
    """Validate that an integer falls strictly within the signed 64-bit range."""
    if not isinstance(val, int):
        raise TypeError(f"Expected int, got {type(val).__name__}")
    if val < MIN_INT64 or val > MAX_INT64:
        raise ArithmeticRangeError(
            f"Value {val} outside int64 range [{MIN_INT64}, {MAX_INT64}]"
        )
    return val


def half_even_div(numerator: int, denominator: int) -> int:
    """Pure integer division with exact round-half-to-even (banker's rounding)."""
    if denominator == 0:
        raise DivisionByZeroError("Division by zero in integer division")

    sign = -1 if (numerator < 0) ^ (denominator < 0) else 1
    num = abs(numerator)
    den = abs(denominator)

    quotient = num // den
    remainder = num % den
    twice_rem = remainder * 2

    if twice_rem > den:
        quotient += 1
    elif twice_rem == den:
        if quotient % 2 != 0:
            quotient += 1

    result = sign * quotient
    return check_int64(result)


def half_even_mod(numerator: int, denominator: int) -> int:
    """Integer modulo consistent with half_even division.

    Guarantees the identity: a == (a / b) * b + (a % b)
    """
    if denominator == 0:
        raise DivisionByZeroError("Modulo by zero in integer arithmetic")
    q = half_even_div(numerator, denominator)
    rem = numerator - (q * denominator)
    return check_int64(rem)


class FixedPoint:
    """64-bit signed fixed-point number with scale 1,000,000 (6 decimal places).

    All internal math is performed on `raw_value` as an integer.
    """

    __slots__ = ("_raw",)

    def __init__(self, raw_value: int) -> None:
        self._raw: int = check_int64(raw_value)

    @property
    def raw_value(self) -> int:
        return self._raw

    @classmethod
    def from_int(cls, value: int) -> FixedPoint:
        """Create FixedPoint from an integer."""
        check_int64(value)
        raw = check_int64(value * SCALE)
        return cls(raw)

    @classmethod
    def from_raw(cls, raw: int) -> FixedPoint:
        """Create FixedPoint directly from scaled integer."""
        return cls(check_int64(raw))

    @classmethod
    def from_decimal_string(cls, s: str) -> FixedPoint:
        """Parse decimal string (e.g. '12.3456', '-0.5', '100') without float conversion."""
        s = s.strip()
        if not s:
            raise ValueError("Cannot parse empty string as FixedPoint")

        sign = -1 if s.startswith("-") else 1
        if s.startswith("-") or s.startswith("+"):
            s = s[1:]

        parts = s.split(".")
        if len(parts) == 1:
            int_part = int(parts[0])
            frac_raw = 0
        elif len(parts) == 2:
            int_part = int(parts[0]) if parts[0] else 0
            frac_str = parts[1]
            if len(frac_str) > 6:
                # Truncate/round beyond 6 places using half-even
                base_frac = int(frac_str[:6])
                extra = int(frac_str[6:])
                divisor = 10 ** (len(frac_str) - 6)
                frac_raw = base_frac + half_even_div(extra, divisor)
            else:
                frac_str_padded = (frac_str + "000000")[:6]
                frac_raw = int(frac_str_padded)
        else:
            raise ValueError(f"Malformed decimal string: {s}")

        raw = sign * (int_part * SCALE + frac_raw)
        return cls(check_int64(raw))

    def to_decimal_string(self) -> str:
        """Format as decimal string with exactly 6 decimal places (e.g. '12.345678')."""
        sign_str = "-" if self._raw < 0 else ""
        abs_raw = abs(self._raw)
        int_part = abs_raw // SCALE
        frac_part = abs_raw % SCALE
        return f"{sign_str}{int_part}.{frac_part:06d}"

    def to_raw_string(self) -> str:
        """Format raw integer value as decimal string for JSON serialization."""
        return str(self._raw)

    # Arithmetic operators
    def __add__(self, other: Union[FixedPoint, int]) -> FixedPoint:
        if isinstance(other, FixedPoint):
            return FixedPoint(check_int64(self._raw + other._raw))
        if isinstance(other, int):
            return FixedPoint(check_int64(self._raw + (other * SCALE)))
        return NotImplemented

    def __radd__(self, other: int) -> FixedPoint:
        return self.__add__(other)

    def __sub__(self, other: Union[FixedPoint, int]) -> FixedPoint:
        if isinstance(other, FixedPoint):
            return FixedPoint(check_int64(self._raw - other._raw))
        if isinstance(other, int):
            return FixedPoint(check_int64(self._raw - (other * SCALE)))
        return NotImplemented

    def __rsub__(self, other: int) -> FixedPoint:
        if isinstance(other, int):
            return FixedPoint(check_int64((other * SCALE) - self._raw))
        return NotImplemented

    def __mul__(self, other: Union[FixedPoint, int]) -> FixedPoint:
        if isinstance(other, FixedPoint):
            prod = self._raw * other._raw
            return FixedPoint(half_even_div(prod, SCALE))
        if isinstance(other, int):
            check_int64(other)
            return FixedPoint(check_int64(self._raw * other))
        return NotImplemented

    def __rmul__(self, other: int) -> FixedPoint:
        return self.__mul__(other)

    def __truediv__(self, other: Union[FixedPoint, int]) -> FixedPoint:
        if isinstance(other, FixedPoint):
            num = self._raw * SCALE
            return FixedPoint(half_even_div(num, other._raw))
        if isinstance(other, int):
            return FixedPoint(half_even_div(self._raw, other))
        return NotImplemented

    def __floordiv__(self, other: Union[FixedPoint, int]) -> FixedPoint:
        if isinstance(other, FixedPoint):
            if other._raw == 0:
                raise DivisionByZeroError("Floor division by zero in FixedPoint arithmetic")
            return FixedPoint.from_int(self._raw // other._raw)
        if isinstance(other, int):
            if other == 0:
                raise DivisionByZeroError("Floor division by zero in FixedPoint arithmetic")
            return FixedPoint(self._raw // (other * SCALE) * SCALE)
        return NotImplemented

    def __mod__(self, other: Union[FixedPoint, int]) -> FixedPoint:
        if isinstance(other, int):
            other = FixedPoint.from_int(other)
        if isinstance(other, FixedPoint):
            if other._raw == 0:
                raise DivisionByZeroError("Modulo by zero in FixedPoint arithmetic")
            q = self / other
            rem = self - (q * other)
            return rem
        return NotImplemented

    def __neg__(self) -> FixedPoint:
        return FixedPoint(check_int64(-self._raw))

    def __pos__(self) -> FixedPoint:
        return self

    def __abs__(self) -> FixedPoint:
        return FixedPoint(abs(self._raw))

    # Comparisons
    def __eq__(self, other: object) -> bool:
        if isinstance(other, FixedPoint):
            return self._raw == other._raw
        if isinstance(other, int):
            return self._raw == other * SCALE
        return False

    def __lt__(self, other: Union[FixedPoint, int]) -> bool:
        if isinstance(other, FixedPoint):
            return self._raw < other._raw
        if isinstance(other, int):
            return self._raw < other * SCALE
        return NotImplemented

    def __le__(self, other: Union[FixedPoint, int]) -> bool:
        if isinstance(other, FixedPoint):
            return self._raw <= other._raw
        if isinstance(other, int):
            return self._raw <= other * SCALE
        return NotImplemented

    def __gt__(self, other: Union[FixedPoint, int]) -> bool:
        if isinstance(other, FixedPoint):
            return self._raw > other._raw
        if isinstance(other, int):
            return self._raw > other * SCALE
        return NotImplemented

    def __ge__(self, other: Union[FixedPoint, int]) -> bool:
        if isinstance(other, FixedPoint):
            return self._raw >= other._raw
        if isinstance(other, int):
            return self._raw >= other * SCALE
        return NotImplemented

    def __hash__(self) -> int:
        return hash(self._raw)

    def __repr__(self) -> str:
        return f"FixedPoint({self.to_decimal_string()})"

    def __str__(self) -> str:
        return self.to_decimal_string()
