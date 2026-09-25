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
    """Full plain-text article, or empty string.

    The short REST summary is not enough. Kosmos 954's summary says the
    satellite "reentered the Earth's atmosphere the following year" rather than
    naming 1978, so a true claim about the 1978 reentry was reported as
    unsupported. Relative dates in a lead paragraph are common; the body
    almost always states the year outright, so check the whole article.
    """
    url = ("https://en.wikipedia.org/w/api.php?action=query&prop=extracts"
           "&explaintext=1&redirects=1&format=json&titles="
           + urllib.parse.quote(title.replace(" ", "_")))
    d = _get_json(url, timeout=30)
    if not d:
        return ""
    query = d.get("query") if isinstance(d, dict) else None
    pages = (query or {}).get("pages") if isinstance(query, dict) else None
    for page in (pages or {}).values():
        if not isinstance(page, dict):
            continue                      # API shape varies on errors/redirects
        text = page.get("extract") or ""
        if isinstance(text, str) and text:
            # 200k characters of plain text is far longer than any real
            # article; the cap only bounds memory on a pathological response.
            # Truncation here can only cause a false "unsupported", never a
            # false "verified", which is the safe direction for this check.
            return text[:200_000]
    return ""


def entities(text: str) -> list[str]:
    """Candidate proper nouns, longest first so "Venera-9" beats "Venera"."""
    found = []
    for m in _ENTITY.finditer(text or ""):
        # A capitalised run swallows sentence-initial and adjective words:
        # "The Soviet Venera-9" is one match. Peel leading stop words so the
        # lookup searches the spacecraft, not the phrase.
        words = m.group(1).strip().split(" ")
        while words and words[0] in _ENTITY_STOP:
            words.pop(0)
        e = " ".join(words).strip()
        if len(e) < 3 or e in _ENTITY_STOP:
            continue
        if e.lower() in {f.lower() for f in found}:
            continue
        found.append(e)
    return sorted(found, key=_anchor_score, reverse=True)


_MONTHS = {"january", "february", "march", "april", "may", "june", "july",
           "august", "september", "october", "november", "december"}
# Named things too generic to test a specific claim against. The article on
# "Pacific Ocean" will never mention a given year, so anchoring on it produces
# a true-but-useless "unsupported".
_WEAK_ANCHORS = {"pacific ocean", "atlantic ocean", "earth", "sun", "moon",
                 "canada", "russia", "united states", "soviet union", "europe",
                 "asia", "africa", "nasa", "space", "orbit"}


def _anchor_score(entity: str) -> int:
    """How good a subject this name is for checking one claim.

    Ranking by raw length picked "September 15" over "Venera-9" and reported
    that the September 15 article fails to mention 1978 - a true statement that
    tells you nothing. A designation carrying a number is the specific thing the
    claim is about; a month or a continent is not.
    """
    low = entity.lower()
    score = len(entity)
    if any(ch.isdigit() for ch in entity):
        score += 100                      # Venera-9, Kosmos 954, Apollo 13
    if low.split(" ")[0] in _MONTHS:
        score -= 200                      # a date, not a subject
    if low in _WEAK_ANCHORS:
        score -= 150
    return score


# Words that carry the claim's technical content. Deliberately narrow: only
# hyphenated designations (plutonium-238, uranium-235), acronyms (RTG, RORSAT)
# and long domain nouns. Everything shorter or commoner paraphrases too freely
# for absence to mean anything.
_COMMON = {
    "approximately", "government", "environment", "international", "including",
    "following", "different", "contamination", "acknowledge", "publicly",
    "extent", "roughly", "spent", "scattered", "released", "crashed", "other",
    "after", "into", "from", "with", "that", "this", "were", "their", "which",
}


def _tech_terms(claim: str) -> set[str]:
    """Distinctive technical vocabulary, lowercased."""
    out: set[str] = set()
    for m in re.finditer(r"[A-Za-z][A-Za-z]+-\d+|\b[A-Z]{3,}\b|\b[a-z]{8,}\b",
                         claim or ""):
        term = m.group(0).lower()
        if term not in _COMMON:
            out.add(term)
    return out


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
        # Technical terms the article never uses. Years catch a fabricated
        # DATE; they cannot catch a fabricated CATEGORY. A brief called Kosmos
        # 954 "an anti-satellite test platform powered by an RTG containing
        # plutonium-238"; it was a radar ocean reconnaissance satellite with a
        # uranium-235 fission reactor, and every date in the claim was right.
        # Absence is a smell, not proof, because an article may paraphrase, so
        # this WARNS and never decides the verdict on its own.
        missing_terms = sorted(t for t in _tech_terms(claim)
                               if t not in text.lower())
        if not years:
            return {"verdict": "unknown", "entity": ent, "article": title,
                    "missing_terms": missing_terms,
                    "reason": "no dates in the claim to check against"}
        missing = sorted(y for y in years if y not in text)
        if not missing:
            return {"verdict": "verified", "entity": ent, "article": title,
                    "missing_years": [], "missing_terms": missing_terms}
        return {"verdict": "unsupported", "entity": ent, "article": title,
                "missing_years": missing, "missing_terms": missing_terms,
                "article_text": text[:300],
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


# Comma-grouped first, so "6,041,174.70" is ONE fact. A looser pattern split it
# into "6,041" and "174.70" and counted a single repeated figure twice.
_NUMBER = re.compile(r"\b\d{1,3}(?:,\d{3})+(?:\.\d+)?\b"
                     r"|\b\d+\.\d+\b"
                     r"|\b\d{3,}\b")
_NAMED = re.compile(r"\b[A-Z][a-z]{2,}(?: [A-Z][a-z]{2,})+\b")
# "BES-5", "uranium-235": the digits belong to a designation, and a video about
# that hardware will name it repeatedly. Stripped before numbers are read.
_DESIGNATION = re.compile(r"\b[A-Za-z]+-\d+\b")
# NOT named _YEAR: that name is already taken at the top of this module by the
# unanchored pattern check_claim() uses to find years inside a claim. Defining
# a second _YEAR here shadowed it, and an anchored pattern finds nothing inside
# a sentence, which would have silently reported every claim as "no dates to
# check against" and disabled the fact check entirely.
_YEAR_EXACT = re.compile(r"^(?:1[89]|20)\d{2}$")


def _facts_in(text: str) -> set[str]:
    """Specific numbers and multi-word proper names, lowercased.

    Years are excluded: an explainer about a 1978 event dates things in several
    beats and that is not repetition. Bare small integers are excluded too, as
    counts like "twelve" carry no identity.
    """
    stripped = _DESIGNATION.sub(" ", text or "")
    out = {m.group(0).lower() for m in _NAMED.finditer(stripped)}
    for m in _NUMBER.finditer(stripped):
        value = m.group(0)
        if not _YEAR_EXACT.match(value):
            out.add(value.lower())
    return out


def check_repetition(brief: dict, *, exclude: str = "") -> dict:
    """Facts restated across beats, which is filler wearing a new sentence.

    Whole-beat text similarity does NOT find this. Measured 2026-09-24, the
    repetitive brief scored a maximum pairwise similarity of 0.16 against 0.12
    for a known-good one: no separation, because the repetition is of specific
    FACTS inside otherwise different prose. Counting the facts themselves
    separates cleanly - 7 repeats against 0, 0 and 0 for three known-good
    briefs across twenty beats.

    `exclude` holds the subject and hook, whose names SHOULD recur: a video
    about Kosmos 954 will say "Kosmos 954" in every beat and that is correct.
    """
    beats = [(b.get("narration") or "") for b in brief.get("beats", [])
             if isinstance(b, dict)]
    skip = {w.lower() for w in re.split(r"[^A-Za-z0-9]+", exclude) if w}
    seen: dict[str, int] = {}
    for text in beats:
        for f in _facts_in(text):
            if f in skip or any(part in skip
                                for part in f.split(" ")):
                continue
            seen[f] = seen.get(f, 0) + 1
    repeated = sorted(f for f, n in seen.items() if n >= 2)
    return {"beats": len(beats), "repeated": repeated, "count": len(repeated)}


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
            # Shown on every verdict, including "verified": the dates can all
            # check out while the category is invented.
            terms = r.get("missing_terms") or []
            if terms and r.get("article"):
                out.append(f"          terms absent from '{r['article']}': "
                           + ", ".join(terms[:6])
                           + " (may be paraphrase - eyeball it)")
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


_NARRATION_JUDGE = """You check a documentary script against source text.
Judge LITERAL factual assertions only: events, amounts, outcomes, causes,
comparisons of size or severity. Ignore obvious rhetoric ("the danger was
invisible"). A sentence that describes a physical event as if it happened
("the ground shook") is a factual assertion.

For each asserted sentence, decide:
  contradicted - the sources say otherwise
  unsupported  - the sources do not say it either way
Leave out sentences the sources support.

Quote each sentence EXACTLY as it appears in the script.
Return JSON: {"flags": [{"sentence": "...", "verdict": "contradicted"|"unsupported", "reason": "..."}]}"""

# Per-source cap. The topic article is the evidence; the hook article is only
# needed for comparison lines ("echoed Chernobyl in scale"), and its lead
# section carries the scale facts. Kept small for the Groq TPM ceiling.
_NARRATION_SOURCE_CHARS = (7000, 2500)


def _default_source(name: str) -> str:
    title = resolve_article(name)
    return article_text(title) if title else ""


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text or "") if s.strip()]


def check_narration(brief: dict, *, chat=None, source=None) -> dict:
    """Ask a judge model which narration sentences the sources contradict.

    check_claims() only reads `substance`. The narration is written FROM the
    substance but by a separate call, and it embellishes: the 2026-09-24
    Kosmos 954 brief had five verified claims and narration saying the Soviets
    paid the bill (they paid about half) and that it matched Chernobyl in scale.

    The judge is a small model and is not trusted blindly: a flag only counts
    if its quoted sentence really occurs in the narration, so a paraphrased or
    invented quote is dropped rather than failing the brief. "contradicted"
    blocks; "unsupported" warns, because sources omit plenty of true things.
    """
    if chat is None:
        from .llm import chat_json as chat
    source = source or _default_source
    names = [(brief.get("topic") or "").strip(),
             (brief.get("external_hook") or "").strip()]
    parts = []
    for name, cap in zip(names, _NARRATION_SOURCE_CHARS):
        text = source(name) if name else ""
        if text:
            parts.append(f"SOURCE: {name}\n{text[:cap]}")
    beats = [b for b in brief.get("beats", []) if isinstance(b, dict)]
    if not parts:
        return {"status": "unknown", "flags": [], "contradicted": 0,
                "unsupported": 0, "dropped": 0,
                "reason": "no source article resolved for topic or hook"}

    script = "\n\n".join(f"BEAT {b.get('beat')}: {b.get('narration') or ''}"
                         for b in beats)
    out = chat(_NARRATION_JUDGE,
               "\n\n".join(parts) + "\n\nSCRIPT:\n" + script,
               temperature=0.0)

    where = {}
    for b in beats:
        for s in _sentences(b.get("narration") or ""):
            where.setdefault(s.lower(), b.get("beat"))
    flags, dropped = [], 0
    for f in (out or {}).get("flags") or []:
        if not isinstance(f, dict):
            continue
        sentence = (f.get("sentence") or "").strip()
        verdict = f.get("verdict")
        beat = where.get(sentence.lower())
        if beat is None or verdict not in ("contradicted", "unsupported"):
            dropped += 1
            continue
        flags.append({"beat": beat, "sentence": sentence, "verdict": verdict,
                      "reason": f.get("reason") or ""})
    n_bad = sum(f["verdict"] == "contradicted" for f in flags)
    return {"status": "checked", "flags": flags, "contradicted": n_bad,
            "unsupported": len(flags) - n_bad, "dropped": dropped}


def summarize_narration(r: dict) -> str:
    if r.get("status") != "checked":
        return f"NARRATION CHECK  unknown: {r.get('reason', '')}"
    out = [f"NARRATION CHECK  {r['contradicted']} contradicted, "
           f"{r['unsupported']} unsupported"
           + (f" ({r['dropped']} judge quotes not found, ignored)"
              if r.get("dropped") else "")]
    for f in sorted(r["flags"], key=lambda f: f["verdict"]):
        mark = "FAIL" if f["verdict"] == "contradicted" else "??  "
        out.append(f"  [{mark}] beat {f['beat']}: {f['sentence'][:80]}")
        out.append(f"          {f['reason'][:110]}")
    return "\n".join(out)
