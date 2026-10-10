"""Emit a deliberately verbose but deterministic inventory audit trace."""

from __future__ import annotations

import argparse
import csv
from collections import Counter
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()
    with args.path.open(encoding="utf-8", newline="") as source:
        rows = list(csv.DictReader(source))

    counts = Counter(row["sku"] for row in rows)
    passes = 80 if args.verbose else 1
    for pass_number in range(1, passes + 1):
        for index, row in enumerate(rows, start=1):
            duplicate = "duplicate" if counts[row["sku"]] > 1 else "unique"
            stock = "low" if int(row["quantity"]) <= 3 else "ok"
            print(
                f"trace pass={pass_number:03d} row={index:02d} sku={row['sku']} "
                f"price_cents={row['price_cents']} quantity={row['quantity']} "
                f"identity={duplicate} stock={stock} source={args.path.as_posix()}"
            )

    duplicates = ", ".join(sorted(sku for sku, count in counts.items() if count > 1))
    print(f"summary rows={len(rows)} duplicate_skus={duplicates or 'none'}")


if __name__ == "__main__":
    main()
