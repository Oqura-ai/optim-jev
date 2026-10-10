"""Box-drawn tables for the stats commands, so all three reports share one shape.

Titles start with "▸", table lines with a box character, notes with "- "; hooks/command-output.tsx draws
titles bold, tables as-is and notes dimmed.
"""

from __future__ import annotations

from collections.abc import Sequence

Row = Sequence[str]


def table(title: str, headers: Row, rows: Sequence[Row], right: Sequence[int] = (), total: Row | None = None) -> list[str]:
    """`right`: indexes of right-aligned (numeric) columns. `total`: a last row set off by a rule."""
    body = [list(map(str, r)) for r in rows] + ([list(map(str, total))] if total else [])
    widths = [max(len(str(h)), *(len(r[i]) for r in body)) for i, h in enumerate(headers)]

    def line(cells: Row) -> str:
        return "│ " + " │ ".join(c.rjust(w) if i in right else c.ljust(w) for i, (c, w) in enumerate(zip(cells, widths))) + " │"

    def rule(left: str, mid: str, end: str) -> str:
        return left + mid.join("─" * (w + 2) for w in widths) + end

    out = [f"▸ {title}", rule("┌", "┬", "┐"), line([str(h) for h in headers]), rule("├", "┼", "┤")]
    out += [line(r) for r in body[: len(rows)]]
    if total:
        out += [rule("├", "┼", "┤"), line(body[-1])]
    out.append(rule("└", "┴", "┘"))
    return out


def render(*blocks: list[str], notes: Sequence[str] = ()) -> str:
    lines: list[str] = []
    for block in blocks:
        if block:
            lines += [*([""] if lines else []), *block]
    if notes:
        lines += ["", *(f"- {n}" for n in notes)]
    return "\n".join(lines)


def net_label(value: float) -> str:
    return "Net saved" if value >= 0 else "Net extra cost"
