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

    out = []
    out.append(f"# Papers I found exciting — {fmt_month(month)}\n")
    if issue.get("intro"):
        out.append(issue["intro"] + "\n")
    for p in issue.get("papers", []):
        if p.get("picked") is False:
            continue
        title = p.get("title", "")
        link = p.get("link")
        head = f"**[{title}]({link})**" if link else f"**{title}**"
        out.append(head)
        meta = " · ".join(x for x in [p.get("venue"), p.get("institution")] if x)
        if meta:
            out.append(f"*{meta}*")
        if p.get("why"):
            out.append(p["why"])
        if p.get("india_connection"):
            out.append(f"> India angle: {p['india_connection']}")
        out.append("")  # blank line between papers
    out.append("---")
    out.append("*Curated from my DeepTech Radar — [ahammadshibil.com/deeptechradar](https://ahammadshibil.com/deeptechradar). "
               "More at [Atoms & Cells](https://atomsandcells.substack.com).*")
    print("\n".join(out))


if __name__ == "__main__":
    main()
