#!/usr/bin/env python3
"""
OpenAlex source — REAL papers, not LLM confabulations.
======================================================
The root fix for fabricated breakthroughs: instead of asking an LLM "what
papers came out" (which invents titles + plausible-famous-name authors +
null links), we pull actual indexed works from OpenAlex. Title, authors,
institution, link, date all come from the database — verifiable by
construction. The LLM, if used at all, only writes the one-line "why".

OpenAlex is free, no API key, ~100k req/day with a mailto. Stdlib only.
"""

import json
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

OPENALEX = "https://api.openalex.org/works"
MAILTO = "radar@ahammadshibil.com"  # polite pool; not auth


def _abstract(inv):
    """Reconstruct an abstract from OpenAlex's inverted index."""
    if not inv:
        return ""
    pos = {}
    for word, idxs in inv.items():
        for i in idxs:
            pos[i] = word
    return " ".join(pos[i] for i in sorted(pos))[:600]


def _link(w):
    if w.get("doi"):
        return w["doi"]  # already a full https://doi.org/... URL
    loc = (w.get("primary_location") or {})
    return loc.get("landing_page_url") or w.get("id")


# Deposit mills / non-peer-reviewed dumps that pollute a broad search with
# real-but-junk records ("Lee Sharks", "The First Waters", etc).
_JUNK_HOSTS = ("zenodo", "figshare", "ssrn", "preprints.org", "researchsquare", "osf.io", "authorea")

# Top-tier venues get a big quality boost so genuine breakthroughs float
# above the long tail of fine-but-forgettable papers. Substring match on
# the venue name (case-insensitive).
_TOP_VENUES = (
    "nature", "science", "cell", "pnas", "proceedings of the national academy",
    "physical review letters", "physical review x", "joule", "matter", "chem",
    "journal of the american chemical society", "angewandte", "advanced materials",
    "nature communications", "science advances", "nature methods", "nature biotechnology",
    "nature medicine", "nature materials", "nature physics", "nature photonics",
    "nature nanotechnology", "nature energy", "nature chemistry", "nature machine intelligence",
    "lancet", "nejm", "new england journal", "immunity", "neuron", "molecular cell",
)
# Titles that signal a non-breakthrough (reviews, opinion, clinical anecdotes).
_NON_BREAKTHROUGH = (
    "review", "survey", "case report", "a case of", "perspective", "commentary",
    "editorial", "viewpoint", "meta-analysis", "systematic review", "scoping review",
    "bibliometric", "overview of", "mini-review", "tutorial",
)


def _venue_boost(venue):
    v = (venue or "").lower()
    for t in _TOP_VENUES:
        if t in v:
            return 10.0
    return 0.0


def _is_non_breakthrough(title, w):
    t = (title or "").lower()
    if any(k in t for k in _NON_BREAKTHROUGH):
        return True
    # OpenAlex sometimes tags the crossref subtype
    if (w.get("type_crossref") or "") in ("review-article", "editorial", "letter"):
        return True
    return False


def recent_works(query, since_days=45, n=6, mailto=MAILTO, min_pool=50):
    """Real recent works matching `query`, ranked by relevance, junk filtered.

    Returns dicts with ONLY verified fields (every value is from OpenAlex):
    {title, authors[], institution, link, year, date, abstract, openalex_id}.
    Default sort is OpenAlex relevance (respects the query) — sorting by
    citations over a short recent window just surfaces nothing-cited-yet
    noise. We over-fetch, drop junk, then keep the top n.
    """
    since = (datetime.now(timezone.utc) - timedelta(days=since_days)).strftime("%Y-%m-%d")
    params = urllib.parse.urlencode({
        "search": query,
        # journal/conference articles from real venues only — no datasets,
        # no paratext, no deposit dumps.
        "filter": f"from_publication_date:{since},type:article,has_doi:true",
        "per-page": max(n, min_pool),
        "mailto": mailto,
    })
    req = urllib.request.Request(f"{OPENALEX}?{params}", headers={"User-Agent": f"deeptech-radar ({mailto})"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            results = json.loads(r.read().decode("utf-8")).get("results", [])
    except Exception as e:
        print(f"  [openalex] '{query[:30]}' failed: {e}")
        return []

    out = []
    for w in results:
        auths = [(a.get("author") or {}).get("display_name") for a in (w.get("authorships") or [])]
        auths = [a for a in auths if a][:4]
        inst = ""
        for a in (w.get("authorships") or []):
            insts = a.get("institutions") or []
            if insts:
                inst = insts[0].get("display_name", "")
                break
        # Quality gate: must have a real institution + a real venue, and not
        # be a deposit-mill record.
        loc = w.get("primary_location") or {}
        src = (loc.get("source") or {})
        venue = (src.get("display_name") or "")
        host = (src.get("host_organization_name") or "") + " " + venue + " " + (w.get("doi") or "")
        if not inst:
            continue
        if not venue:
            continue
        if any(j in host.lower() for j in _JUNK_HOSTS):
            continue
        if len(auths) == 0:
            continue
        if _is_non_breakthrough(w.get("title"), w):
            continue  # drop reviews / case reports / editorials
        # Quality score: top venue dominates, then citation traction, then
        # recency. Surfaces genuine breakthroughs over the competent long tail.
        cites = w.get("cited_by_count", 0) or 0
        days_old = 999
        try:
            days_old = (datetime.now(timezone.utc) - datetime.fromisoformat(w["publication_date"]).replace(tzinfo=timezone.utc)).days
        except Exception:
            pass
        score = _venue_boost(venue) + min(cites, 20) * 0.4 + max(0, 90 - days_old) / 30
        out.append({
            "_score": score,
            "venue": venue,
            "title": w.get("title"),
            "authors": auths,                       # REAL authors
            "institution": inst,
            "link": _link(w),                        # REAL link (DOI/landing)
            "year": w.get("publication_year"),
            "date": w.get("publication_date"),
            "citations": cites,
            "abstract": _abstract(w.get("abstract_inverted_index")),
            "openalex_id": w.get("id"),
            "verified": True,                        # came from the DB, not an LLM
        })
    # Quality-rank the filtered pool, then keep the top n.
    out.sort(key=lambda x: x["_score"], reverse=True)
    return out[:n]


if __name__ == "__main__":
    import sys
    q = " ".join(sys.argv[1:]) or "de novo protein design"
    for w in recent_works(q, n=5):
        print(f"• {w['title'][:60]}")
        print(f"  {', '.join(w['authors'][:3])} — {w['institution']} ({w['date']})")
        print(f"  {w['link']}")
