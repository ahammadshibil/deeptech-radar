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
    """Real papers from OpenAlex (title/authors/institution/link are from the
    database, never the LLM). The LLM, if a key is set, only writes the
    one-line founder 'why' from the real abstract — it cannot invent a
    paper or an author. This is the fix for the confabulated-breakthrough
    root cause: you can't fabricate what you didn't generate."""
    from openalex import recent_works

    # Research indexing lags; use a wider window than the funding sections.
    window = max(days, 45)

    def why_line(w):
        ab = (w.get("abstract") or "").strip()
        if API_KEY and ab:
            try:
                p = (f"Paper: {w['title']}\nAbstract: {ab[:500]}\n\n"
                     "One line: why should a deep-tech builder care? The white space it opens "
                     "or the thing it makes newly possible. Under 30 words, declarative, no hype.")
                return ask(p, SYSTEM, 0.3).strip().strip('"')
            except Exception:
                pass
        # Deterministic fallback: first sentence of the real abstract.
        return re.split(r"(?<=[.!?])\s+", ab)[0][:240] if ab else None

    # Sector display-name → a sharp OpenAlex search query. Vague sector
    # labels ("AI Infrastructure") return miscellaneous indexed noise;
    # concrete frontier topics return the actual papers.
    SECTOR_QUERY = {
        "Semiconductors and Chip Design": "transistor scaling 2D semiconductor chip architecture",
        "AI Infrastructure and Agents": "large language model agents inference systems",
        "Synthetic Biology and Biotech": "de novo protein design gene editing cell therapy",
        "Climate Tech and Sustainability": "carbon capture electrochemical green hydrogen ammonia",
        "Photonics and Optics": "integrated photonics optical computing nanophotonics",
        "Robotics and Embodied AI": "robot learning manipulation embodied policy",
        "Advanced Materials and Energy": "solid state battery perovskite solar fusion confinement",
        "Quantum Computing and Sensing": "quantum error correction qubit quantum sensing",
        "Space Technology and Defense": "satellite propulsion earth observation small launch",
    }

    def one(sector):
        works = recent_works(SECTOR_QUERY.get(sector, sector), since_days=window, n=6)
        bts = []
        for w in works:
            bts.append({
                "title": w["title"],
                "authors": w["authors"],            # REAL
                "institution": w["institution"],     # REAL
                "year": w["year"],
                "field": sector,
                "key_breakthrough": why_line(w),
                "trl": None,                         # not inferred from a paper; omit rather than guess
                "india_connection": (REGION if REGION.lower() in (w["institution"] or "").lower() else None),
                "link": w["link"],                   # REAL
                "date": w["date"],
                "verified": True,
            })
        return {"name": sector, "short_name": sector, "breakthroughs": bts, "count": len(bts)}

    out = []
    with ThreadPoolExecutor(max_workers=5) as ex:
        futs = {ex.submit(one, s): s for s in SECTORS}
        for f in as_completed(futs):
            try:
                out.append(f.result())
            except Exception as e:
                print(f"  [research] {futs[f]} failed: {e}")
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
