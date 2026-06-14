#!/usr/bin/env python3
"""
Monthly issue drafter — "Papers I found exciting this month"
============================================================
Turns the radar's research breakthroughs into a DRAFT monthly issue you
then trim: keep the ones that actually excited you, edit the one-line take,
write the intro. Pipeline-drafts-you-trim by design — your taste is the point.

    python draft_issue.py                      # draft current month from ../data.json
    python draft_issue.py --month 2026-06      # specific month label
    python draft_issue.py --pick 10            # shortlist size (default 8)
    PERPLEXITY_API_KEY=... python draft_issue.py --llm   # LLM-written "why" lines

Writes ../issues/<YYYY-MM>.draft.json. Review it, edit the `why` lines +
`intro`, set `picked:false` on any you drop, then rename to
<YYYY-MM>.json and add the month to ../issues/index.json to publish.
"""

import argparse
import json
import os
import re
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent.parent
PERPLEXITY_URL = "https://api.perplexity.ai/chat/completions"
API_KEY = os.environ.get("PERPLEXITY_API_KEY", "")

# Voice seed for the optional LLM pass — a builder-scientist's lens, not a
# press summary. You edit these anyway; this just gives a sharper start.
VOICE = (
    "You are drafting one-line takes for a curated monthly digest titled "
    "'Papers I found exciting this month', written by a biologist-turned-VC who "
    "is building a bio-AI company. The take should say WHY a builder should care: "
    "the white space it opens, the thing it makes newly possible, or the assumption "
    "it breaks. First-principles, biology-native where relevant, no hype words, "
    "under 30 words, declarative. Return ONLY the sentence."
)


def _why_llm(bt):
    if not API_KEY:
        return None
    prompt = (
        f"Paper: {bt.get('title')}\nInstitution: {bt.get('institution')}\n"
        f"Field: {bt.get('field')}\nWhat was shown: {bt.get('key_breakthrough')}\n\n"
        "Write the one-line 'why this is exciting' take."
    )
    try:
        payload = json.dumps({
            "model": "sonar-pro",
            "messages": [{"role": "system", "content": VOICE}, {"role": "user", "content": prompt}],
            "temperature": 0.4, "max_tokens": 120,
        }).encode("utf-8")
        req = urllib.request.Request(PERPLEXITY_URL, data=payload, method="POST",
            headers={"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=60) as r:
            txt = json.loads(r.read().decode("utf-8"))["choices"][0]["message"]["content"].strip()
        return txt.strip().strip('"')
    except Exception as e:
        print(f"  [why] llm failed for {bt.get('title','?')[:40]}: {e}")
        return None


def _why_fallback(bt):
    # Deterministic seed: first sentence of the breakthrough, trimmed.
    kb = (bt.get("key_breakthrough") or "").strip()
    first = re.split(r"(?<=[.!?])\s+", kb)[0] if kb else ""
    return first[:240]


# Ordering heuristic (you re-rank by hand anyway): recent first, India bonus,
# and only real/linkable papers float up.
def _score(bt):
    s = 0.0
    d = bt.get("date") or ""
    try:
        days = (datetime.now(timezone.utc) - datetime.fromisoformat(d).replace(tzinfo=timezone.utc)).days
        s += max(0, 60 - days) / 10
    except Exception:
        pass
    if bt.get("india_connection"):
        s += 1.5
    if bt.get("link"):
        s += 1.0
    return s


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--month", default=datetime.now(timezone.utc).strftime("%Y-%m"))
    ap.add_argument("--pick", type=int, default=8)
    ap.add_argument("--data", default=str(ROOT / "data.json"))
    ap.add_argument("--llm", action="store_true", help="use Perplexity to write the 'why' lines")
    args = ap.parse_args()

    data = json.loads(Path(args.data).read_text())
    bts, seen = [], set()
    for dom in data.get("research", []):
        for bt in dom.get("breakthroughs", []):
            # Dedupe across sectors — the same paper can match two queries.
            key = (bt.get("link") or "") or re.sub(r"[^a-z0-9]", "", (bt.get("title") or "").lower())[:50]
            if key in seen:
                continue
            seen.add(key)
            bts.append({**bt, "domain": dom.get("name")})
    if not bts:
        sys.exit("No breakthroughs in data.json — run refresh.py first.")

    bts.sort(key=_score, reverse=True)
    shortlist = bts[: args.pick]

    papers = []
    for bt in shortlist:
        why = (_why_llm(bt) if args.llm else None) or _why_fallback(bt)
        # Real link straight from the source (OpenAlex DOI/landing); fall back
        # to an arXiv id only if that's all there is. Never synthesize one.
        link = bt.get("link") or (f"https://arxiv.org/abs/{bt['arxiv_id']}" if bt.get("arxiv_id") else None)
        papers.append({
            "title": bt.get("title"),
            "authors": bt.get("authors") or [],
            "institution": bt.get("institution"),
            "domain": bt.get("domain"),
            "field": bt.get("field"),
            "trl": bt.get("trl"),
            "india_connection": bt.get("india_connection"),
            "link": link,
            "why": why,            # ← edit this in your voice
            "picked": True,         # ← set false to drop from the issue
        })

    issue = {
        "month": args.month,
        "title": "Papers I found exciting",
        "intro": "",  # ← write a 2-3 line opener
        "papers": papers,
        "draftedAt": datetime.now(timezone.utc).isoformat(),
    }
    out = ROOT / "issues" / f"{args.month}.draft.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(issue, indent=2))
    print(f"wrote {out} — {len(papers)} candidates. Trim it, then publish:")
    print(f"  1) edit `why` lines + `intro`, drop with picked:false")
    print(f"  2) rename to {args.month}.json")
    print(f"  3) add \"{args.month}\" to issues/index.json")


if __name__ == "__main__":
    main()
