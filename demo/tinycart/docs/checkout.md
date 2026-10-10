# Checkout

TinyCart stores every price as integer cents. The checkout total is the sum of each unit price multiplied by its quantity.

Run `python run_tests.py` before shipping a pricing change.

## Inventory checks

Inventory data in `data/inventory.csv` can be audited for duplicate SKUs and low-stock rows. The most recent audit report is at [reports/inventory-audit.md](../reports/inventory-audit.md).
