from pathlib import Path
import unittest

from tinycart.inventory import duplicate_skus, load_inventory, low_stock


ROOT = Path(__file__).resolve().parents[1]


class InventoryTests(unittest.TestCase):
    def test_finds_duplicate_skus(self):
        rows = load_inventory(ROOT / "data" / "inventory.csv")
        self.assertEqual(duplicate_skus(rows), ["CABLE-03", "MUG-01"])

    def test_finds_low_stock_rows(self):
        rows = load_inventory(ROOT / "data" / "inventory.csv")
        self.assertEqual([row.sku for row in low_stock(rows)], ["NOTE-02", "LAMP-04", "PEN-05"])


if __name__ == "__main__":
    unittest.main()
