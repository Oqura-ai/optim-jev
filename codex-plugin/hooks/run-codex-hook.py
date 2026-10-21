from __future__ import annotations

import sys

try:
    from optim_jev.hosts.codex import main
except Exception:
    sys.stdout.write("{}")
else:
    main()
