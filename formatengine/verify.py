"""Two checks the differentiation gate cannot make: is it TRUE, and is it SHIPPABLE.

The gate measures structure - opener variety, second-person rate, sentence
length, substance COUNT. On 2026-09-11 a brief passed every one of those and was
still unusable, in two independent ways:

FABRICATION. All five substance items were confidently wrong and every one was
marked `needs_check: false`:

    brief:     "The Soviet Venera-9 spacecraft, launched in July 1975, broke
                apart in Earth orbit on September 15, 1978, releasing a
                radioactive plume"
    Wikipedia: "Venera 9 ... was a Soviet uncrewed space mission to Venus ...
                launched on June 8, 1975 ... the first spacecraft to orbit Venus"

The real event it had half-remembered is Kosmos 954, a nuclear-powered
reconnaissance satellite that reentered over northern Canada in 1978. A count of
substance items cannot see any of this; the gate happily scored 5 of 3.

GORE. The same brief's beats were graphic body horror - skin peeling in ribbons,
blood filling the throat, organs dissolving - in a format whose other titles are
"Every Type Of Black Hole Explained". That is an age-restriction and
demonetisation risk in a project whose entire premise is avoiding exactly that.

Neither check is a truth oracle. `check_claims` proves only ABSENCE: that a
number in the claim does not appear in the encyclopedia article about the thing
the claim is about. That is a strong enough smell to block on, and it is the
smell fabricated specifics give off.
"""
from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request

from .freshness import _get_json, resolve_article

# Graphic-content markers. This is a POLICY heuristic, not a measurement, and it
# is labelled as such wherever it surfaces. YouTube's advertiser-friendly rules
# treat depicted bodily harm as limited-or-no-ads, and the project's whole
# premise is not tripping monetisation policy.
_GORE = re.compile(
    r"\b("
    r"blood(y|s)?|bleed(ing|s)?|gore|guts|entrails|intestines?|"
    r"skin peel(s|ing)?|peel(s|ing)? (off|away)|flesh|corpse|mutilat\w*|"
    r"dismember\w*|decapitat\w*|disembowel\w*|vomit\w*|"
    r"organs? (dissolv|liquef|melt|ruptur)\w*|eyeballs?|"
    r"boil(s|ing)? alive|burn(s|ing)? alive|scream(s|ing)? in agony"
    r")\b", re.I)

_YEAR = re.compile(r"\b(1[89]\d{2}|20\d{2})\b")
# A capitalised run, optionally hyphenated with digits: "Venera-9", "NASA",
# "Great Slave Lake". These are the things an encyclopedia has articles about.
_ENTITY = re.compile(r"\b([A-Z][A-Za-z]*(?:[- ][A-Z0-9][A-Za-z0-9]*)*(?:-\d+)?)\b")
_ENTITY_STOP = {
    "The", "A", "An", "It", "In", "On", "At", "This", "That", "These", "Those",
    "Soviet", "Russian", "American", "Earth", "Every", "When", "After", "Before",
    "During", "However", "Although", "While", "Its", "His", "Her", "Their",
}


def article_text(title: str) -> str:
    """Lead section of an article, or empty string."""
    url = ("https://en.wikipedia.org/api/rest_v1/page/summary/"
           + urllib.parse.quote(title.replace(" ", "_")))
    d = _get_json(url, timeout=25)
    if not d:
        return ""
    return " ".join(str(d.get(k) or "") for k in ("extract", "description"))


def entities(text: str) -> list[str]:
    """Candidate proper nouns, longest first so "Venera-9" beats "Venera"."""
    found = []
    for m in _ENTITY.finditer(text or ""):
        e = m.group(1).strip()
        if len(e) < 3 or e in _ENTITY_STOP:
            continue
        if e.lower() in {f.lower() for f in found}:
            continue
        found.append(e)
    return sorted(found, key=len, reverse=True)


def check_claim(claim: str) -> dict:
    """Look the claim's main entity up and report numbers the article lacks.

    Returns a verdict of "verified" (every year in the claim appears in the
    article), "unsupported" (the entity exists but the claim's years do not
    appear in it), or "unknown" (no article, or no years to check).
    """
    ents = entities(claim)
    years = set(_YEAR.findall(claim))
    for ent in ents[:3]:
        title = resolve_article(ent)
        if not title:
            continue
        text = article_text(title)
        if not text:
            continue
        if not years:
            return {"verdict": "unknown", "entity": ent, "article": title,
                    "reason": "no dates in the claim to check against"}
        missing = sorted(y for y in years if y not in text)
        if not missing:
            return {"verdict": "verified", "entity": ent, "article": title,
                    "missing_years": []}
        return {"verdict": "unsupported", "entity": ent, "article": title,
                "missing_years": missing, "article_text": text[:300],
                "reason": (f"the article on {title!r} does not mention "
                           + ", ".join(missing))}
    return {"verdict": "unknown", "entity": ents[0] if ents else None,
            "article": None,
            "reason": "no Wikipedia article resolves for anything named in this claim"}


def check_claims(brief: dict) -> dict:
    """Verify every substance item. Network-bound; call it deliberately."""
    items = [s for s in (brief.get("substance") or []) if isinstance(s, dict)]
    results = []
    for s in items:
        claim = (s.get("claim") or "").strip()
        if not claim:
            continue
        r = check_claim(claim)
        r["claim"] = claim
        r["self_reported_needs_check"] = bool(s.get("needs_check"))
        results.append(r)
    bad = [r for r in results if r["verdict"] == "unsupported"]
    return {"checked": len(results), "unsupported": len(bad), "results": results}


def check_gore(brief: dict) -> dict:
    """Flag graphic bodily-harm language across hook and narration.

    Offline and cheap, so the gate can run it on every brief.
    """
    parts = [("hook", brief.get("hook") or "")]
    for b in brief.get("beats", []):
        if isinstance(b, dict):
            parts.append((f"beat {b.get('beat')}", b.get("narration") or ""))
    hits = []
    for where, text in parts:
        for m in _GORE.finditer(text):
            hits.append({"where": where, "term": m.group(0)})
    return {"hits": hits, "count": len(hits),
            "beats_affected": len({h["where"] for h in hits if h["where"] != "hook"})}


def summarize(claims: dict | None, gore: dict) -> str:
    # Read defensively throughout: these dicts are also loaded back from saved
    # brief JSON, which may have been written by an older schema or hand-edited.
    out = []
    claims = claims or None
    if claims is not None:
        out.append(f"FACT CHECK  {claims.get('checked', 0)} claims, "
                   f"{claims.get('unsupported', 0)} unsupported")
        for r in claims.get("results") or []:
            verdict = r.get("verdict", "unknown")
            mark = {"verified": "ok  ", "unsupported": "FAIL"}.get(verdict, "??  ")
            out.append(f"  [{mark}] {str(r.get('claim',''))[:90]}")
            if verdict != "verified":
                out.append(f"          {r.get('reason','')}")
            # Only claim this when the brief actually said so. A missing key
            # means unknown, and asserting "it was marked false" would put words
            # in the brief's mouth.
            if (verdict == "unsupported"
                    and r.get("self_reported_needs_check") is False):
                out.append("          and it was marked needs_check: false")
    gore = gore or {}
    out.append("")
    out.append(f"GORE CHECK  {gore.get('count', 0)} markers across "
               f"{gore.get('beats_affected', 0)} beats "
               "(policy heuristic, not measured)")
    for h in (gore.get("hits") or [])[:12]:
        out.append(f"  - {h.get('where')}: {h.get('term')!r}")
    return "\n".join(out)
