"""Unit tests for GENESIS FixedPoint arithmetic and checked integer math."""

import unittest
from genesis.core.arithmetic import FixedPoint, SCALE, half_even_div, check_int64, MAX_INT64, MIN_INT64
from genesis.core.errors import ArithmeticRangeError


class TestArithmetic(unittest.TestCase):

    def test_half_even_rounding(self):
        # Even quotient with exactly 0.5 remainder stays even
        # 2 / 4 = 0.5 -> 0 (even)
        self.assertEqual(half_even_div(2, 4), 0)
        # 6 / 4 = 1.5 -> 2 (odd quotient 1 rounds up to even 2)
        self.assertEqual(half_even_div(6, 4), 2)
        # 10 / 4 = 2.5 -> 2 (even quotient 2 stays 2)
        self.assertEqual(half_even_div(10, 4), 2)
        # 14 / 4 = 3.5 -> 4 (odd quotient 3 rounds up to 4)
        self.assertEqual(half_even_div(14, 4), 4)

        # Negative symmetric half-even
        self.assertEqual(half_even_div(-2, 4), 0)
        self.assertEqual(half_even_div(-6, 4), -2)
        self.assertEqual(half_even_div(-10, 4), -2)
        self.assertEqual(half_even_div(-14, 4), -4)

        # Standard rounding (> 0.5 or < 0.5)
        self.assertEqual(half_even_div(8, 5), 2)   # 1.6 -> 2
        self.assertEqual(half_even_div(7, 5), 1)   # 1.4 -> 1
        self.assertEqual(half_even_div(-8, 5), -2) # -1.6 -> -2
        self.assertEqual(half_even_div(-7, 5), -1) # -1.4 -> -1

    def test_fixed_point_basic_operations(self):
        a = FixedPoint.from_decimal_string("1.500000")
        b = FixedPoint.from_decimal_string("2.500000")

        # Addition
        c = a + b
        self.assertEqual(c.to_decimal_string(), "4.000000")

        # Subtraction
        d = b - a
        self.assertEqual(d.to_decimal_string(), "1.000000")

        # Multiplication: 1.5 * 2.5 = 3.750000
        e = a * b
        self.assertEqual(e.to_decimal_string(), "3.750000")

        # Division: 1.5 / 2.5 = 0.600000
        f = a / b
        self.assertEqual(f.to_decimal_string(), "0.600000")

    def test_fixed_point_string_parsing(self):
        fp1 = FixedPoint.from_decimal_string("0.000001")
        self.assertEqual(fp1.raw_value, 1)

        fp2 = FixedPoint.from_decimal_string("-0.000001")
        self.assertEqual(fp2.raw_value, -1)

        fp3 = FixedPoint.from_decimal_string("100")
        self.assertEqual(fp3.raw_value, 100 * SCALE)

        fp4 = FixedPoint.from_decimal_string("-42.5")
        self.assertEqual(fp4.to_decimal_string(), "-42.500000")

    def test_int64_range_enforcement(self):
        check_int64(MAX_INT64)
        check_int64(MIN_INT64)
        with self.assertRaises(ArithmeticRangeError):
            check_int64(MAX_INT64 + 1)
        with self.assertRaises(ArithmeticRangeError):
            check_int64(MIN_INT64 - 1)


if __name__ == "__main__":
    unittest.main()
