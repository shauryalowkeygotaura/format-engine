"""Niche bending with a real saturation check.

The tutorials get the concept right: keep the packaging that is proven, swap
the topic sideways so you inherit the algorithm's appetite without landing in
a head-to-head fight. Cats to dogs to birds.

What they never do is verify the landing zone. Their instruction is "search it
and if someone's doing it, check if they're any good" - a vibe. That vibe is
the difference between a channel that prints and a channel that dies, so it is
worth measuring.

This module scores every bend candidate on two axes measured from live data:

    demand      - do videos about this topic actually pull views?
                  (median views of the current top results for the term)
    competition - has somebody already bent the format this exact way, recently,
                  and are they strong? (recent results whose titles match the
                  format's own template signature)

High demand + low competition is the whole game. The pair is reported
separately rather than mashed into one number, because "nobody is doing this"
and "nobody wants this" look identical if you only keep the composite.
"""
from __future__ import annotations

import difflib
import re
import statistics
from datetime import datetime, timedelta, timezone

from . import config
from .llm import chat_json
from .yt import QuotaExhausted, YouTube, age_days, views_of

BEND_SYSTEM = """You generate "niche bends" for proven YouTube formats.

A niche bend keeps a format's packaging identical and moves the TOPIC sideways
so the creator inherits proven demand without competing head-on with the
channel that proved it.

Bend distances:
  adjacent - nearest neighbour in the same category (cats -> dogs)
  lateral  - same parent category, different branch (cats -> garden birds)
  far      - same format, entirely different domain (cats -> vintage aircraft)

Rules:
- NEVER return the source topic itself or a synonym of it.
- Each bend must be searchable as a real topic people already care about.
- Prefer topics whose audience skews older or higher-income; those carry higher
  ad rates. Avoid anything aimed at young children.
- Avoid politics, medical claims, gambling, and anything explicit.
- `search_term` is the 2-4 word phrase to check demand with. No punctuation.
- `proposed_title` must be GRAMMATICAL ENGLISH that a human would actually
  click. Follow the template's shape and word order, but pick slot values that
  read naturally together and pluralise the topic where the template implies a
  set. Filling slots blindly produces garbage like "Every Most Disturbing
  Spacetime Explained" - that is a failure, not a title.
- Topics must be broad enough to sustain a full video. A topic with only one
  example in it cannot fill a list format.

Return ONLY JSON."""

BEND_USER = """Format template: {template}
Format archetype: {archetype}
Topic axis (what the topics vary along): {axis}
Source topics already used by this format: {used}
Slot vocabulary available: {vocab}

Generate {n} bend candidates.

Return JSON exactly:
{{
  "bends": [
    {{
      "topic": "...",
      "search_term": "...",
      "distance": "adjacent|lateral|far",
      "proposed_title": "the format template filled in with this topic",
      "why": "one sentence on why this audience exists",
      "audience_age_skew": "young|mixed|older",
      "rpm_guess": "low|medium|high"
    }}
  ]
}}"""


def similarity(a: str, b: str) -> float:
    """Blend of sequence and token overlap. Catches both reword and reorder."""
    a_n = re.sub(r"[^a-z0-9 ]", " ", (a or "").lower())
    b_n = re.sub(r"[^a-z0-9 ]", " ", (b or "").lower())
    seq = difflib.SequenceMatcher(None, a_n, b_n).ratio()
    ta, tb = set(a_n.split()), set(b_n.split())
    jac = len(ta & tb) / len(ta | tb) if (ta | tb) else 0.0
    return round(0.5 * seq + 0.5 * jac, 3)


def generate_bends(spec: dict, n: int = 10, model: str | None = None) -> list[dict]:
    """Ask for bend candidates. Cheap - one Groq call, no YouTube quota."""
    titles = spec.get("titles", [])
    used = [t.get("topic") for t in spec.get("title_format", {}).get("per_title", []) if t.get("topic")]
    used = used or titles[:6]
    tf = spec.get("title_format", {})
    out = chat_json(
        BEND_SYSTEM,
        BEND_USER.format(
            template=tf.get("template", "{topic}"),
            archetype=tf.get("archetype", "other"),
            axis=tf.get("topic_axis", "unknown"),
            used="; ".join(str(u) for u in used[:12]),
            vocab=tf.get("slot_vocabulary", {}),
            n=n,
        ),
        model=model, temperature=0.85, max_tokens=3000,
    )
    bends = out.get("bends", [])
    return [b for b in bends if isinstance(b, dict) and b.get("topic")]


def _signature_terms(template: str) -> list[str]:
    """The fixed words of a template - what makes a title 'this format'."""
    stripped = re.sub(r"\{[a-z_]+\}", " ", template or "")
    words = [w for w in re.findall(r"[a-z]+", stripped.lower()) if len(w) > 2]
    return words


def check_saturation(yt: YouTube, bend: dict, spec: dict, *,
                     window_days: int = 180) -> dict:
    """One search (100u) buys both demand and competition for a candidate."""
    term = bend.get("search_term") or bend.get("topic", "")
    tf = spec.get("title_format", {})
    template = tf.get("template", "")
    sig = _signature_terms(template)

    try:
        items = yt.search(term, order="relevance", max_results=25, duration="medium")
    except QuotaExhausted:
        return {"checked": False, "reason": "quota exhausted"}
    except Exception as e:  # network/API problem should not kill the whole run
        return {"checked": False, "reason": f"{type(e).__name__}: {e}"}

    vids = yt.videos([(i.get("id") or {}).get("videoId") for i in items
                      if (i.get("id") or {}).get("videoId")])
    if not vids:
        return {"checked": True, "demand_median_views": 0, "competition_count": 0,
                "competition_strength": 0, "verdict": "no-data"}

    view_list, recent_matches, strengths = [], [], []
    cutoff = datetime.now(timezone.utc) - timedelta(days=window_days)
    for v in vids:
        sn = v.get("snippet", {})
        views = views_of(v)
        view_list.append(views)
        title = (sn.get("title") or "").lower()
        published = sn.get("publishedAt", "")
        if not published:
            continue
        try:
            is_recent = age_days(published) <= window_days
        except ValueError:
            is_recent = False
        # "Someone already bent it this way" = recent AND carries the format's
        # signature words, not merely a video about the same topic.
        hits = sum(1 for w in sig if w in title)
        if is_recent and sig and hits >= max(1, len(sig) // 2):
            recent_matches.append({"title": sn.get("title", ""), "views": views,
                                   "channel": sn.get("channelTitle", ""),
                                   "url": f"https://www.youtube.com/watch?v={v.get('id')}"})
            strengths.append(views)

    demand = int(statistics.median(view_list)) if view_list else 0
    comp_n = len(recent_matches)
    comp_strength = int(statistics.median(strengths)) if strengths else 0

    if demand < 20_000:
        verdict = "weak-demand"
    elif comp_n == 0:
        verdict = "open"
    elif comp_n <= 2 and comp_strength < demand * 0.5:
        verdict = "beatable"
    elif comp_n <= 4:
        verdict = "contested"
    else:
        verdict = "saturated"

    return {
        "checked": True,
        "search_term": term,
        "demand_median_views": demand,
        "demand_max_views": max(view_list) if view_list else 0,
        "competition_count": comp_n,
        "competition_strength": comp_strength,
        "competitors": recent_matches[:5],
        "verdict": verdict,
    }


def opportunity_score(bend: dict) -> float:
    """0-100. Demand you can reach beats demand you cannot."""
    sat = bend.get("saturation", {})
    if not sat.get("checked"):
        return 0.0
    demand = sat.get("demand_median_views", 0)
    verdict = sat.get("verdict", "")
    if verdict == "weak-demand":
        return 5.0
    # log-ish demand curve: 20k -> ~20, 200k -> ~45, 2M -> ~70
    score = min(70.0, 20.0 * (max(demand, 1) / 20_000) ** 0.35)
    score *= {"open": 1.0, "beatable": 0.85, "contested": 0.55,
              "saturated": 0.2, "no-data": 0.4}.get(verdict, 0.5)
    score += {"adjacent": 8.0, "lateral": 12.0, "far": 6.0}.get(bend.get("distance", ""), 5.0)
    score += {"older": 10.0, "mixed": 5.0, "young": 0.0}.get(bend.get("audience_age_skew", ""), 3.0)
    score += {"high": 10.0, "medium": 5.0, "low": 0.0}.get(bend.get("rpm_guess", ""), 3.0)
    return round(min(100.0, score), 1)


def bend_format(yt: YouTube, spec: dict, *, n: int = 10, check_top: int = 5,
                model: str | None = None) -> list[dict]:
    """Generate candidates, then spend searches only on the most promising."""
    bends = generate_bends(spec, n=n, model=model)
    if not bends:
        return []

    # Pre-rank on free signals so the 100u searches go to plausible winners.
    def prior(b):
        return ({"older": 3, "mixed": 2, "young": 0}.get(b.get("audience_age_skew"), 1)
                + {"high": 3, "medium": 2, "low": 0}.get(b.get("rpm_guess"), 1)
                + {"lateral": 2, "adjacent": 1, "far": 1}.get(b.get("distance"), 1))

    bends.sort(key=prior, reverse=True)

    for i, b in enumerate(bends):
        if i < check_top:
            b["saturation"] = check_saturation(yt, b, spec)
        else:
            b["saturation"] = {"checked": False, "reason": "outside search budget"}
        b["opportunity"] = opportunity_score(b)
        b["title_similarity_to_source"] = max(
            (similarity(b.get("proposed_title", ""), t) for t in spec.get("titles", [])),
            default=0.0,
        )
    bends.sort(key=lambda b: -b["opportunity"])
    return bends


def summarize_bends(bends: list[dict], limit: int = 10) -> str:
    if not bends:
        return "No bend candidates."
    lines = [f"{'OPP':>5} {'DIST':<9} {'VERDICT':<12} {'DEMAND':>10} {'COMP':>5} TITLE", "-" * 100]
    for b in bends[:limit]:
        s = b.get("saturation", {})
        lines.append(
            f"{b['opportunity']:>5.1f} {b.get('distance','?'):<9} "
            f"{s.get('verdict','unchecked'):<12} "
            f"{s.get('demand_median_views',0):>10,} {s.get('competition_count',0):>5} "
            f"{b.get('proposed_title','')[:52]}"
        )
    return "\n".join(lines)
