from __future__ import annotations

import os
from pathlib import Path

DATA_DIRNAME = ".optim-jev"


def data_root(project_dir: str | os.PathLike[str]) -> Path:
    """The project's `.optim-jev/` folder, created on first use and ignored by git."""
    root = Path(project_dir) / DATA_DIRNAME
    root.mkdir(parents=True, exist_ok=True)
    ignore = root / ".gitignore"
    if not ignore.exists():
        ignore.write_text("*\n", encoding="utf-8")
    return root
