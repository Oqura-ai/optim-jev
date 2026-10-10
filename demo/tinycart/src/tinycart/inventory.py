"""Read and inspect TinyCart's inventory fixtures."""

from __future__ import annotations

import csv
from collections import Counter
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class InventoryRow:
    sku: str
    name: str
    price_cents: int
    quantity: int


def load_inventory(path: str | Path) -> list[InventoryRow]:
    with Path(path).open(encoding="utf-8", newline="") as source:
        return [
            InventoryRow(
                sku=row["sku"],
                name=row["name"],
                price_cents=int(row["price_cents"]),
                quantity=int(row["quantity"]),
            )
            for row in csv.DictReader(source)
        ]


def duplicate_skus(rows: list[InventoryRow]) -> list[str]:
    counts = Counter(row.sku for row in rows)
    return sorted(sku for sku, count in counts.items() if count > 1)


def low_stock(rows: list[InventoryRow], threshold: int = 3) -> list[InventoryRow]:
    return [row for row in rows if row.quantity <= threshold]
