import unittest

from tinycart.pricing import CartLine, cart_total, line_total


class PricingTests(unittest.TestCase):
    def test_line_total_uses_integer_cents(self):
        self.assertEqual(line_total(1299, 3), 3897)

    def test_negative_values_are_rejected(self):
        with self.assertRaises(ValueError):
            line_total(-1, 1)
        with self.assertRaises(ValueError):
            line_total(100, -1)

    def test_cart_total_adds_lines(self):
        lines = [CartLine("MUG-01", 1299, 2), CartLine("PEN-05", 299, 1)]
        self.assertEqual(cart_total(lines), 2897)


if __name__ == "__main__":
    unittest.main()
