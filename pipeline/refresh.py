#!/usr/bin/env python3
"""
DeepTech Radar — refresh pipeline
=================================
Generates data.json for the static dashboard by querying Perplexity Sonar Pro
across deep-tech sectors. Built for FOUNDERS: every prompt is framed around
"what should I build?" — breakthroughs and their commercialization gap (white
space), who's already building (competition), funding flows, and policy
tailwinds. No deal-sourcing, no VC scoring.

Usage:
    PERPLEXITY_API_KEY=... python refresh.py                 # full refresh
    python refresh.py --section research                     # one section
    python refresh.py --days 7                               # widen window (default 7)
    python refresh.py --out ../data.json                     # output path

Sections: research, global_startups, india_startups, policies, top10
Zero dependencies — Python 3.8+ standard library only.
"""

import argparse
import json
import os
import re
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

PERPLEXITY_URL = "https://api.perplexity.ai/chat/completions"
API_KEY = os.environ.get("PERPLEXITY_API_KEY", "")

# ── Config ────────────────────────────────────────────────────────────────
# Edit these to retarget the radar. SECTORS drives the Research domain cards;
# REGION is the "home market" the India-style sections focus on.
SECTORS = [
    "Semiconductors and Chip Design",
    "AI Infrastructure and Agents",
    "Synthetic Biology and Biotech",
    "Climate Tech and Sustainability",
    "Photonics and Optics",
    "Robotics and Embodied AI",
    "Advanced Materials and Energy",
    "Quantum Computing and Sensing",
    "Space Technology and Defense",
]
REGION = os.environ.get("RADAR_REGION", "India")

# A config file (pipeline/config.json) overrides the defaults if present.
_cfg_path = Path(__file__).parent / "config.json"
if _cfg_path.exists():
    _cfg = json.loads(_cfg_path.read_text())
    SECTORS = _cfg.get("sectors", SECTORS)
    REGION = _cfg.get("region", REGION)


# ── Perplexity ──────────────────────────────────────────────────────────────
def ask(prompt: str, system: str = "", temperature: float = 0.2) -> str:
    if not API_KEY:
        sys.exit("PERPLEXITY_API_KEY not set")
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    payload = json.dumps({
        "model": "sonar-pro",
        "messages": messages,
        "temperature": temperature,
        "max_tokens": 8192,
    }).encode("utf-8")
    req = urllib.request.Request(
        PERPLEXITY_URL, data=payload, method="POST",
        headers={"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=180) as resp:
        return json.loads(resp.read().decode("utf-8"))["choices"][0]["message"]["content"]


def extract_json(text: str):
    for pat in (r"```json\s*\n([\s\S]*?)\n```", r"```\s*\n([\s\S]*?)\n```", r"\[[\s\S]*\]", r"\{[\s\S]*\}"):
        m = re.search(pat, text)
        if not m:
            continue
        try:
            return json.loads(m.group(1) if m.lastindex else m.group(0))
        except (json.JSONDecodeError, IndexError):
            continue
    print(f"  [warn] no JSON in response ({len(text)} chars)")
    return None


SYSTEM = (
    "You are a research analyst mapping the frontier of deep tech for FOUNDERS deciding what to build. "
    "You report what is actually happening — real breakthroughs, real companies, real funding — and you "
    "highlight the gap between what research has proven and what has been commercialized (the white space "
    "a founder could fill). Return ONLY valid JSON, no prose. Never fabricate; if a field is unknown, use null."
)


# ── Sections ────────────────────────────────────────────────────────────────
def fetch_research(days):
    def one(sector):
        prompt = (
            f"List 4-6 genuine research breakthroughs in '{sector}' from the last {days} days "
            f"(papers, lab results, working demos). For a founder, what matters is: is this real, how mature, "
            f"and has anyone commercialized it yet. Return JSON array; each item:\n"
            '{"title": str, "authors": [str], "institution": str, "year": int, "field": str, '
            '"key_breakthrough": "2-3 sentences on what was shown AND whether it is commercialized yet (the build gap)", '
            f'"trl": "1-9 string", "india_connection": "{REGION} lab/author/relevance or null", "date": "YYYY-MM-DD"}}'
        )
        items = extract_json(ask(prompt, SYSTEM)) or []
        return {"name": sector, "short_name": sector, "breakthroughs": items, "count": len(items)}
    out = []
    with ThreadPoolExecutor(max_workers=5) as ex:
        futs = {ex.submit(one, s): s for s in SECTORS}
        for f in as_completed(futs):
            try:
                out.append(f.result())
            except Exception as e:
                print(f"  [research] {futs[f]} failed: {e}")
    # keep SECTORS order
    order = {s: i for i, s in enumerate(SECTORS)}
    return sorted(out, key=lambda d: order.get(d["name"], 99))


def fetch_global_startups(days):
    prompt = (
        f"List 8-12 deep-tech startups worldwide that announced funding in the last {days} days. "
        f"This is a founder's competition map. Return JSON array; each item:\n"
        '{"name": str, "sector": str, "country": str, "stage": str, "amount": number_usd_or_null, '
        '"amount_str": "e.g. $12M", "lead_investors": [str], "founders": str, '
        '"technical_thesis": "what they are building + why it is hard", '
        f'"india_relevance": "is this niche open in {REGION}? or null", "source_url": str, "date": "YYYY-MM-DD"}}'
    )
    return extract_json(ask(prompt, SYSTEM)) or []


def fetch_india_startups(days):
    prompt = (
        f"List 8-12 deep-tech startups in {REGION} that announced funding or notable progress in the last {days} days. "
        f"Sources: tech press, government grant lists, university incubators. Return JSON array; each item:\n"
        '{"name": str, "city": str, "sector": str, "funding_stage": str, "amount": number_usd_or_null, '
        '"amount_str": "e.g. $2M", "technology_thesis": "what they are building", "founders": str, '
        '"research_origin": "lab/university spinout or null", "source_url": str, "date": "YYYY-MM-DD"}'
    )
    return extract_json(ask(prompt, SYSTEM)) or []


def fetch_policies(days):
    prompt = (
        f"List 10-20 recent (last {max(days,30)} days) government policies, grants, or programs worldwide that create "
        f"deep-tech BUILD opportunities (the openings a founder could move on). Return JSON array; each item:\n"
        '{"name": str, "country": str, "year": int, "domain": str, "funding_amount": "e.g. $500M or null", '
        '"startup_opportunities": "what this enables founders to build", '
        '"opportunity": "the sharpest single build opening this creates", '
        '"impact_score": "1-10 string", "source_url": str, "date": "YYYY-MM-DD"}'
    )
    return extract_json(ask(prompt, SYSTEM)) or []


def fetch_top10(days):
    prompt = (
        f"Name the 10 highest-signal deep-tech BUILD opportunities right now — spaces where research is proven "
        f"but commercialization is thin (white space), ranked by signal strength. Return JSON array of exactly 10; each:\n"
        '{"rank": int, "name": str, "thesis": "why now + the white space", "market_size_2035": "e.g. $40B", '
        '"signal_strength": "High/Medium + 1 line", "geographic_hubs": [str], '
        f'"india_readiness": "how ready is {REGION} to build this"}}'
    )
    return extract_json(ask(prompt, SYSTEM)) or []


SECTION_FNS = {
    "research": fetch_research,
    "global_startups": fetch_global_startups,
    "india_startups": fetch_india_startups,
    "policies": fetch_policies,
    "top10": fetch_top10,
}
KEY_MAP = {
    "research": "research", "global_startups": "globalStartups",
    "india_startups": "indiaStartups", "policies": "policies", "top10": "top10",
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--section", choices=list(SECTION_FNS), help="refresh one section only")
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--out", default=str(Path(__file__).parent.parent / "data.json"))
    args = ap.parse_args()

    out_path = Path(args.out)
    data = {}
    if out_path.exists():
        try:
            data = json.loads(out_path.read_text())
        except Exception:
            data = {}

    sections = [args.section] if args.section else list(SECTION_FNS)
    for s in sections:
        print(f"[{s}] fetching (last {args.days}d)…")
        data[KEY_MAP[s]] = SECTION_FNS[s](args.days)
        n = len(data[KEY_MAP[s]])
        print(f"[{s}] {n} items")

    data["generatedAt"] = datetime.now(timezone.utc).isoformat()
    out_path.write_text(json.dumps(data))
    print(f"wrote {out_path} ({out_path.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
