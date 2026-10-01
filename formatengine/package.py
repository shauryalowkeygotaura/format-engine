"""Packaging decided BEFORE the script exists.

The old order here was: generate a brief (title and script together), then
derive a thumbnail spec from the finished thing. That is backwards, and the
reference channels show it in their own artifacts. "Kira Case, But It's 2026"
and "No, L Can't Catch Epstein" cannot have been derived from a completed
analysis video; the hook was picked first and the analysis was written to fit
it. MrBeast, Paddy Galloway and adavia all state the same rule independently.

So this module produces a PACKAGE and stops:

    title  ·  alt titles  ·  thumbnail text  ·  thumbnail spec  ·  external hook

Nothing else. No beats, no narration, no substance. `brief --package <slug>`
then writes a script that has to fit an already-approved title, which is the
only ordering where packaging actually constrains production.

The gate here is cheap on purpose. A blocked package costs one Groq call. A
blocked brief costs a full script generation, and a bad title that gets through
costs a render plus the upload slot.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from . import config, freshness, store
from .brief import similarity, thumbnail_spec
from .llm import chat_json

PACKAGE_SYSTEM = """You write YouTube packaging: the title and the thumbnail, decided before any script exists.

You are given a proven format template, a topic, and an EXTERNAL HOOK - something
from outside the source material (a real person, event, institution, meme, or a
different fandom) that will appear in the thumbnail beside the in-universe subject.

The hook is the point. Measured across 80 videos on two channels that share a
niche, title templates and runtime, packaging that collides the in-universe
subject with a real-world artifact ran 2.7x-5x on views/day at matched age. The
anime supplies familiarity; the external artifact supplies the anomaly. A
thumbnail that is only in-universe has already been resolved by the viewer
before they finish looking at it.

Rules for the title:
- 8 words maximum, 40 characters maximum. Measured median is 6 words / 31 chars.
- It must contain a collision, a verdict, or a question with a wrong answer
  available. Recommendation framing ("Why You Should Read X") is the single
  worst-measured shape in the sample and is forbidden.
- NAME THE HOOK IN THE TITLE. This is not a stylistic preference. On a channel
  in a different niche, titles that stated the collision literally (the words
  "Real-Life") measured a median 226,466 views against 42,230 for titles that
  merely implied the same idea - 5.4x for saying it out loud. "Every Real-Life
  Glitch Explained" did 6,182,111; "Every Glitched Brain Setting Explained" did
  66,374. Same concept, one names the collision.
- Do not use a colon-subtitle structure.
- Prefer one ALL-CAPS emphasis word (NOT, WAY, REALLY, WORST, TOTALLY) or a
  question mark. Do not use both in the same title.

Rules for thumbnail_text:
- 2 to 4 words. It is read at thumbnail size, not article size.
- It must NOT restate the title. The title asks, the thumbnail answers, or the
  reverse. Redundant pairs waste the second slot.

Rules for thumbnail_collision:
- Name the two things being composited and the institutional symbol if one fits.
  Be concrete and literal: "photograph of X", not "imagery evoking X".

Return ONLY JSON."""

PACKAGE_USER = """Format template: {template}
Format archetype: {archetype}
Existing titles in this format (do NOT clone these):
{titles}

Topic (the in-universe subject): {topic}
External hook: {hook}
Hook recognition evidence: {hook_evidence}

Return JSON exactly:
{{
  "title": "the one you would actually ship",
  "alt_titles": ["three more, each a different angle on the same hook"],
  "thumbnail_text": "2-4 words",
  "thumbnail_collision": "what is composited with what",
  "why_this_hook_lands": "one sentence, concrete"
}}"""


def build(spec: dict, topic: str, hook: str, *, hook_score: dict | None = None,
          model: str | None = None) -> dict:
    """Generate packaging only. One Groq call, zero YouTube quota."""
    tf = spec.get("title_format", {})
    titles = spec.get("titles", [])[:8]

    # hook_score may arrive from disk (a saved package, possibly written by an
    # older schema), so read it defensively rather than by subscript.
    evidence = "not scored"
    rec = (hook_score or {}).get("recognition") or {}
    daily = rec.get("daily_median")
    if rec.get("scored") and isinstance(daily, (int, float)):
        evidence = (f"{rec.get('article', hook)} draws {daily:,} Wikipedia "
                    "pageviews/day, so the audience knows it without being told")

    out = chat_json(
        PACKAGE_SYSTEM,
        PACKAGE_USER.format(
            template=tf.get("template", "{topic}"),
            archetype=tf.get("archetype", "other"),
            titles="\n".join(f"- {t}" for t in titles) or "- (none on file)",
            topic=topic,
            hook=hook,
            hook_evidence=evidence,
        ),
        model=model, temperature=0.9, max_tokens=900,
    )

    bend = {"topic": topic, "search_term": topic}
    tspec = thumbnail_spec(spec, bend)
    # The measured differentiator, appended to whatever the format's own
    # checklist already says. Winners composite a REAL photograph in; the
    # losing pattern is anime-beside-anime, which both channels' medians show.
    tspec["external_hook"] = hook
    tspec["instructions"] = list(tspec.get("instructions", [])) + _hook_visuals(
        spec, hook, out.get("thumbnail_collision") or hook)

    return {
        "title": (out.get("title") or "").strip(),
        "alt_titles": [t.strip() for t in (out.get("alt_titles") or []) if t.strip()],
        "thumbnail_text": (out.get("thumbnail_text") or "").strip(),
        "thumbnail_collision": (out.get("thumbnail_collision") or "").strip(),
        "why_this_hook_lands": (out.get("why_this_hook_lands") or "").strip(),
        "thumbnail_spec": tspec,
        "external_hook": hook,
        "hook_score": hook_score,
        "topic": topic,
        "format_slug": spec.get("slug", ""),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


# ── the packaging gate ───────────────────────────────────────────────────────
_BANNED_SHAPES = (
    (re.compile(r"^\s*(why|how)\s+you\s+should\b", re.I),
     "Recommendation framing. The only such title in the 80-video sample was the "
     "channel floor at 396 views/day, roughly 1/30th of the hook videos."),
    (re.compile(r"^\s*(a|an|the)\s+(complete|ultimate|full)\s+guide\b", re.I),
     "Guide framing carries no collision and no verdict."),
)

_EMPHASIS = re.compile(r"\b(NOT|WAY|REALLY|WORST|TOTALLY|EVERY|NEVER)\b")

# Filter-evasion inside an otherwise-normal word: "A$$", "stup*d", "f#ck".
_EVASION = re.compile(r"[A-Za-z][" + re.escape(config.SLANG_EVASION_CHARS) + r"]+[A-Za-z]?")
# Homoglyph substitution: mathematical-alphanumeric letters standing in for
# ASCII, which is how "𝓝𝓱*𝓷𝓽𝓪𝓲" gets past a keyword filter.
_HOMOGLYPH = re.compile(r"[\U0001D400-\U0001D7FF]")


def _hook_visuals(spec: dict, hook: str, collision: str) -> list[str]:
    """How to composite the external hook, in THIS format's visual language.

    This used to assert "the real artifact must be photographic". That was
    measured on two anime-analysis channels, where the winners pair a manga crop
    with an actual photograph. ThePaintProf's two biggest videos (6,182,111 and
    2,673,243 views) are entirely flat illustration and contain no photograph at
    all, so the instruction was globalised from one niche and would have pushed
    a working format the wrong way. Art style now comes from measurement.
    """
    cl = spec.get("thumbnail_checklist") or {}
    style = cl.get("art_style")
    layout = cl.get("dominant_layout")
    out = [f"Collide {hook!r} with the in-universe subject in one frame: {collision}."]

    if style == "illustrated":
        out.append(
            "Render the hook in the format's own illustration style, NOT as a "
            "photograph. This format is measured illustrated "
            f"(flatness {cl.get('avg_flatness')}); dropping a photo into it "
            "breaks the house style, and the one thumbnail on the reference "
            "channel that left its house style is that channel's worst video.")
    elif style == "photographic":
        out.append(
            "The hook must be an actual photograph, not an illustration of one. "
            "The measured winners pair an anime/manga crop with a real "
            "photograph plus an institutional symbol (agency seal, occult "
            "sigil, skyline).")
    else:
        out.append(
            "Art style for this format is UNMEASURED (run `deconstruct` to fill "
            "thumbnail_checklist.art_style). Match whatever the format's "
            "existing thumbnails already do rather than guessing.")

    if layout == "grid_menu":
        out.append(
            f"Layout is a grid menu ({cl.get('avg_cells')} cells average). The "
            "hook is ONE captioned cell among many, not a hero subject. Density "
            "is the promise: the viewer scans the grid for the one item that "
            "applies to them, so every cell needs its own readable caption.")

    out.append(
        "Source the artifact by exact proper name, never by mood. 'Jeffrey "
        "Epstein photograph' and 'CIA seal' are exact; 'sinister figure' is the "
        "failure mode that produced a beach for water pressure.")
    return out


def _title_caps(spec: dict) -> tuple[int, int]:
    """Title length caps for this format, falling back to the global default.

    Length is a property of the format, not of YouTube. The anime-analysis
    niche runs 31 chars / 6 words median; ThePaintProf runs 44 / 7, and its
    6,182,111-view best video is 45 characters long. A single global cap blocks
    one of those two niches, so a spec may carry its own measured numbers in
    title_format.max_chars / title_format.max_words.
    """
    tf = spec.get("title_format") or {}
    try:
        chars = int(tf.get("max_chars") or config.MAX_TITLE_CHARS)
    except (TypeError, ValueError):
        chars = config.MAX_TITLE_CHARS
    try:
        words = int(tf.get("max_words") or config.MAX_TITLE_WORDS)
    except (TypeError, ValueError):
        words = config.MAX_TITLE_WORDS
    return chars, words


def register_of(pkg: dict) -> str:
    """"slang" or "proper". Two independent markers, either one is enough.

    The hook itself can be slang (no Wikipedia article, YouTube-only), and the
    TITLE can carry the crude register even when the hook is respectable, via
    filter-evasion. Both reference channels do the second thing.
    """
    hook_register = ((pkg.get("hook_score") or {}).get("register")
                     or (pkg.get("hook_score") or {}).get("recognition", {}).get("register"))
    if hook_register == "slang":
        return "slang"
    title = pkg.get("title") or ""
    if _EVASION.search(title) or _HOMOGLYPH.search(title):
        return "slang"
    return "proper"


def template_use_count(format_slug: str) -> int:
    """How many times this format has already shipped.

    Counts the whole ledger, not the recent window: decay is cumulative over a
    template's life, unlike the slang budget which is about recent mix.
    """
    ledger = store.read_json(config.LEDGER, default={}) or {}
    return sum(1 for r in (ledger.get("shipped") or [])
               if r.get("format_slug") == format_slug)


def slang_budget_state() -> dict:
    """How much of the slang allowance the recent upload window has spent."""
    recent = store.recent_shipped(config.SLANG_BUDGET_WINDOW)
    used = sum(1 for r in recent if (r.get("register") or "proper") == "slang")
    return {"window": config.SLANG_BUDGET_WINDOW, "seen": len(recent),
            "used": used, "max": config.SLANG_BUDGET_MAX,
            "remaining": max(0, config.SLANG_BUDGET_MAX - used)}


def gate(pkg: dict, spec: dict) -> dict:
    """Pass/fail packaging before a single word of script is paid for."""
    checks: list[dict] = []
    failures: list[str] = []
    warnings: list[str] = []
    title = pkg.get("title", "") or ""

    # 1. The hook itself. WEAK blocks; UNSCORED never does, because the highest
    #    views/day video in the reference sample used a term with no article.
    score = pkg.get("hook_score") or {}
    verdict = score.get("verdict", "UNSCORED")
    ok = verdict not in ("WEAK", "INVALID")
    checks.append({"check": "hook_recognition", "value": verdict,
                   "limit": "not WEAK", "pass": ok})
    if not ok:
        failures.append(
            f"Hook {pkg.get('external_hook')!r} scored {verdict}. "
            + " ".join(score.get("notes", [])[:1]))
    elif verdict == "CROWDED":
        warnings.append(
            f"Hook is CROWDED: {score.get('saturation', {}).get('top_title')} already "
            f"holds it at {score.get('saturation', {}).get('top_views', 0):,} views. "
            "Ship only if your angle genuinely differs from theirs.")
    elif verdict == "UNSCORED":
        warnings.append(
            "Hook could not be scored by EITHER instrument: no Wikipedia article "
            "and no YouTube result set. A term nobody uses looks exactly like "
            "this, so check the spelling before assuming the audience knows it.")

    # 1b. The slang budget. Slang is allowed and measured to work; what is not
    #     allowed is a channel that becomes mostly slang.
    reg = register_of(pkg)
    budget = slang_budget_state()
    if reg == "slang":
        ok = budget["used"] < budget["max"]
        checks.append({"check": "slang_budget",
                       "value": f"{budget['used'] + 1}/{budget['max']} in last "
                                f"{budget['window']}",
                       "limit": budget["max"], "pass": ok})
        if not ok:
            failures.append(
                f"Slang budget spent: {budget['used']} of your last "
                f"{budget['seen']} uploads are already in the crude/slang "
                f"register, and the cap is {budget['max']} per "
                f"{budget['window']}. The reference channel ran 3 in 10, not 6 "
                "in 10. Ship a proper-register hook next, or retitle this one "
                "without the filter-evasion.")
        elif budget["used"] + 1 == budget["max"]:
            warnings.append(
                f"This spends the last of the slang budget ({budget['max']} per "
                f"{budget['window']} uploads). The next few should be "
                "proper-register hooks.")

    # 1c. Template decay. Warns, never blocks: the curve is unmistakable but its
    #     cause is not separable from public data.
    used = template_use_count(spec.get("slug", ""))
    nth = used + 1
    checks.append({"check": "template_use", "value": f"use #{nth}",
                   "limit": f"warn at {config.TEMPLATE_DECAY_WARN_AT}", "pass": True})
    kind = (spec.get("title_format") or {}).get("template_kind")
    if kind == "lens":
        # A lens ("The LIES That Make X ACTUALLY Work") promises a hidden
        # mechanism and re-applies to any subject. Enrico Tartarotti 2026-09-25:
        # 1.11M -> 594k -> 688k over three uses. The ~99% curve was measured on
        # topic-bound templates, so it is not quoted here. Unset stays loud.
        if nth >= config.TEMPLATE_DECAY_WARN_AT:
            warnings.append(
                f"This is use #{nth} of {spec.get('slug')!r}, a lens template. "
                "Lens decay is unmeasured past use #3 on the reference channel; "
                "compare this upload's views against the template's first uses.")
    elif nth >= config.TEMPLATE_DECAY_LOUD_AT:
        warnings.append(
            f"This is use #{nth} of {spec.get('slug')!r}. On the reference "
            "channel both templates were down ~99% by this point (6,182,111 to "
            "33,846 over 14 uploads). A new template's FIRST use outperformed "
            "this template's tenth by 10-100x. Strongly consider opening a new "
            "format instead, and open it with your best idea rather than saving "
            "that one.")
    elif nth >= config.TEMPLATE_DECAY_WARN_AT:
        warnings.append(
            f"This is use #{nth} of {spec.get('slug')!r}. Both measured "
            "templates were already down ~95% by their fifth use. Watch the "
            "numbers on this one; if it lands soft, the template is the "
            "suspect, not the topic.")

    # 1d. Is the topic a SUBJECT or a category? Everything downstream assumes a
    #     subject. "space disaster" is a category: it resolves on Wikipedia to
    #     "Space Shuttle Challenger disaster", which is why three separate
    #     scripts drifted onto Challenger and Columbia, and grounding it fell
    #     through to the hook and produced a Chernobyl video with a space title.
    #     A concrete subject carries a proper noun or a designation number.
    topic = (pkg.get("topic") or "").strip()
    words = topic.split()
    concrete = bool(
        any(ch.isdigit() for ch in topic)          # a designation: Kosmos 954
        or any(w[:1].isupper() for w in words[1:])  # a name past position one
        # A short capitalised phrase is a name: "Chernobyl", "Apollo 13".
        or (words and words[0][:1].isupper() and len(words) <= 3)
    )
    checks.append({"check": "topic_is_concrete", "value": topic or "(none)",
                   "limit": "a named subject", "pass": concrete})
    if topic and not concrete:
        warnings.append(
            f"Topic {topic!r} reads as a category rather than a named subject. "
            "Grounding and the beats both need one specific thing: 'Kosmos 954', "
            "not 'space disaster'. A category lets the script wander onto "
            "whatever famous example the model reaches for first.")

    # 2. Title length, from the FORMAT's own measurements where it has them.
    max_chars, max_words = _title_caps(spec)
    n_chars, n_words = len(title), len(title.split())
    ok = n_chars <= max_chars and n_words <= max_words
    checks.append({"check": "title_length",
                   "value": f"{n_chars}c/{n_words}w",
                   "limit": f"{max_chars}c/{max_words}w",
                   "pass": ok})
    if not ok:
        failures.append(
            f"Title is {n_chars} chars / {n_words} words, over this format's cap of "
            f"{max_chars} chars / {max_words} words. If the format genuinely runs "
            "longer titles, set title_format.max_chars on its spec rather than "
            "trimming a title that reads correctly.")

    # 3. Shape: collision, verdict, or question. Measured across all 80 titles:
    #    27 end in "?", 31 contain "vs", 22 carry an ALL-CAPS emphasis word.
    # "?" anywhere, not only terminal: "Space Chernobyl? Explained" is a
    # question-shaped title that a trailing-only test scored as shapeless.
    has_shape = bool("?" in title
                     or re.search(r"\bvs\.?\b", title, re.I)
                     or _EMPHASIS.search(title))
    checks.append({"check": "title_shape", "value": has_shape, "limit": True,
                   "pass": has_shape})
    if not has_shape:
        warnings.append(
            "Title has no question mark, no 'vs', and no ALL-CAPS emphasis word. "
            "69 of 80 measured titles carry at least one. Not fatal, but check "
            "there is a real collision in it.")

    # 3b. Is the hook actually named in the title? Stating the collision
    #     measured 5.4x over implying it (226,466 vs 42,230 median).
    #     Both sides use freshness._tokens so short hooks ("CIA", "AI", "L")
    #     are compared symmetrically; filtering only one side let a short hook
    #     pass by default without ever being checked.
    hook_words = freshness._tokens(pkg.get("external_hook") or "")
    title_words = freshness._tokens(title)
    named = bool(hook_words & title_words) if hook_words else True
    checks.append({"check": "hook_named_in_title", "value": named,
                   "limit": True, "pass": named})
    if not named:
        warnings.append(
            f"The hook {pkg.get('external_hook')!r} does not appear in the "
            "title, so the collision is only in the thumbnail. Titles that "
            "stated the collision measured 226,466 median views against 42,230 "
            "for titles that implied it. Put it in both if it reads naturally.")

    for pat, why in _BANNED_SHAPES:
        if pat.search(title):
            failures.append(f"{why} Rewrite: {title!r}")
            checks.append({"check": "banned_shape", "value": pat.pattern,
                           "limit": "none", "pass": False})
            break

    # 4. The existing originality guards, applied at packaging time rather than
    #    after a script has already been paid for.
    src_sim = max((similarity(title, t) for t in spec.get("titles", [])), default=0.0)
    ok = src_sim <= config.MAX_TITLE_SIMILARITY_TO_SOURCE
    checks.append({"check": "title_vs_source", "value": round(src_sim, 3),
                   "limit": config.MAX_TITLE_SIMILARITY_TO_SOURCE, "pass": ok})
    if not ok:
        failures.append(f"Title is {src_sim:.0%} similar to a source title. That is a "
                        "clone, not a bend.")

    # Same as brief.gate: a package regenerated under its own title must not be
    # blocked for resembling its own unpublished draft.
    recent = store.recent_shipped(exclude_draft_title=title)
    peak = max((similarity(title, r.get("title", "")) for r in recent), default=0.0)
    ok = peak <= config.MAX_SELF_SIMILARITY_ROLLING
    checks.append({"check": "self_similarity_peak", "value": round(peak, 3),
                   "limit": config.MAX_SELF_SIMILARITY_ROLLING, "pass": ok,
                   "window": len(recent)})
    if not ok:
        failures.append(f"Title is {peak:.0%} similar to one of your own last "
                        f"{len(recent)} uploads.")

    # 5. Thumbnail text must not restate the title.
    tt = (pkg.get("thumbnail_text") or "").strip()
    tt_sim = similarity(tt, title) if tt else 0.0
    ok = bool(tt) and tt_sim < 0.6
    checks.append({"check": "thumb_text_distinct", "value": round(tt_sim, 3),
                   "limit": 0.6, "pass": ok})
    if not tt:
        failures.append("No thumbnail text. The thumbnail carries the second half of "
                        "the packaging; leaving it empty wastes the slot.")
    elif tt_sim >= 0.6:
        warnings.append(f"Thumbnail text {tt!r} restates the title ({tt_sim:.0%} similar). "
                        "Make one of them ask and the other answer.")

    passed = not failures
    return {"passed": passed, "checks": checks, "failures": failures,
            "warnings": warnings}


# ── persistence ──────────────────────────────────────────────────────────────
def save(pkg: dict, gate_result: dict) -> "object":
    slug = store.slugify(pkg.get("title", "package"))
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    path = config.PACKAGES / f"{slug}-{stamp}.json"
    # Pin the register at save time so the ledger and any later re-read agree,
    # rather than recomputing it from a hook_score that may have been trimmed.
    return store.write_json(path, {**pkg, "register": register_of(pkg),
                                   "gate": gate_result})


def load(name: str) -> dict | None:
    """Load by slug, with or without the date stamp or .json suffix."""
    stem = name[:-5] if name.endswith(".json") else name
    exact = config.PACKAGES / f"{stem}.json"
    if exact.exists():
        return store.read_json(exact)
    hits = sorted(config.PACKAGES.glob(f"{store.slugify(stem)}*.json"))
    return store.read_json(hits[-1]) if hits else None


def summarize(pkg: dict, gate_result: dict) -> str:
    out = [
        f"{'PASS' if gate_result['passed'] else 'BLOCKED'}  {pkg.get('title','')}",
        f"  thumbnail text    {pkg.get('thumbnail_text','')}",
        f"  collision         {pkg.get('thumbnail_collision','')}",
        f"  hook              {pkg.get('external_hook','')} "
        f"[{(pkg.get('hook_score') or {}).get('verdict','?')}]",
        f"  register          {register_of(pkg)}"
        + (f"   (slang budget {slang_budget_state()['used']}/"
           f"{config.SLANG_BUDGET_MAX} spent in last "
           f"{config.SLANG_BUDGET_WINDOW})" if register_of(pkg) == "slang" else ""),
        "",
    ]
    for c in gate_result["checks"]:
        out.append(f"  [{'ok  ' if c['pass'] else 'FAIL'}] {c['check']:<22} "
                   f"{c['value']} (limit {c['limit']})")
    if pkg.get("alt_titles"):
        out += ["", "  alternates:"] + [f"    - {t}" for t in pkg["alt_titles"]]
    for f in gate_result["failures"]:
        out.append(f"  ! {f}")
    for w in gate_result["warnings"]:
        out.append(f"  ~ {w}")
    return "\n".join(out)
