#!/usr/bin/env python3
"""
Issue → Atoms & Cells (Substack) markdown
=========================================
Turns a published monthly issue into paste-ready markdown for the
newsletter. Same source as the site page — one issue, two surfaces.

    python to_substack.py 2026-06            # prints markdown to stdout
    python to_substack.py 2026-06 > june.md  # or pipe to a file
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
MONTHS = ["", "January", "February", "March", "April", "May", "June",
          "July", "August", "September", "October", "November", "December"]


def fmt_month(m):
    y, mo = str(m).split("-")
    return f"{MONTHS[int(mo)]} {y}"


def main():
    if len(sys.argv) < 2:
        sys.exit("usage: to_substack.py <YYYY-MM>")
    month = sys.argv[1]
    path = ROOT / "issues" / f"{month}.json"
    # tolerate a BOM if the file was saved by a Windows editor
    issue = json.loads(path.read_text(encoding="utf-8-sig"))

    picks = [p for p in issue.get("papers", []) if p.get("picked") is not False]

    def block(p):
        title = p.get("title", "")
        link = p.get("link")
        lines = [f"**[{title}]({link})**" if link else f"**{title}**"]
        meta = " · ".join(x for x in [p.get("venue"), p.get("institution")] if x)
        if meta:
            lines.append(f"*{meta}*")
        if p.get("why"):
            lines.append(p["why"])
        if p.get("india_connection"):
            lines.append(f"> India angle: {p['india_connection']}")
        lines.append("")
        return "\n".join(lines)

    out = [f"# Papers I found exciting — {fmt_month(month)}\n"]
    if issue.get("intro"):
        out.append(issue["intro"] + "\n")

    # Atoms & Cells taxonomy: Cells (bio) first + heavier, then Atoms.
    cells = [p for p in picks if p.get("track") == "Cells"]
    atoms = [p for p in picks if p.get("track") == "Atoms"]
    rest = [p for p in picks if p.get("track") not in ("Cells", "Atoms")]
    if cells:
        out.append("## Cells — biology\n")
        out += [block(p) for p in cells]
    if atoms:
        out.append("## Atoms — the rest of deep tech\n")
        out += [block(p) for p in atoms]
    out += [block(p) for p in rest]

    out.append("---")
    out.append("*Curated from my DeepTech Radar — [ahammadshibil.com/deeptechradar](https://ahammadshibil.com/deeptechradar). "
               "More at [Atoms & Cells](https://atomsandcells.substack.com).*")
    print("\n".join(out))


if __name__ == "__main__":
    main()
