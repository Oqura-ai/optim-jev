## General
- Keep the demo standard-library-only.
- Prefer small, reviewable changes and run `python run_tests.py` after code edits.

## src/tinycart/pricing.py
- All monetary values are integer cents; never introduce floats.
- Discounts must be deterministic and must never produce a negative price.

## data/
- Inventory CSV files are immutable demo fixtures. Write findings under `reports/`.
