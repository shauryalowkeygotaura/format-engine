"""Production brief + the differentiation gate.

This is the module that departs hardest from the source material.

The tutorials optimise for one variable: similarity to a proven video. "The
better you are copying, the more views your video will get." That was true, and
on 2025-07-15 YouTube renamed its repetitious-content monetization policy to
"inauthentic content" and pointed it directly at uploads that look "made with a
template with little to no variation". In January 2026 it removed 16 channels
holding roughly 35 million subscribers under that policy. The judgement is
channel-wide, so one templated run can strip monetization from everything.

So the strategy here splits the variable in two:

    PACKAGING  - copy hard. Title structure, thumbnail composition, pacing.
                 This is what the algorithm reads, and it is not what the
                 policy is about.
    SUBSTANCE  - must differ. Every brief has to carry original research that
                 the source format does not have.

`gate()` enforces that split, and it also watches YOUR last N briefs against
each other, because the failure mode is not cloning one channel once - it is
your own uploads converging into a template.
"""
from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone

from . import config, store
from .bend import similarity
from .llm import chat_json

# Phrases that signal value without carrying any. Counted across the whole
# script: one use is a tic, two or more is a habit the viewer feels.
# Trailing punctuation stripped off a beat's first word before comparing.
_PUNCT = ".,:;\"'"

FILLER_PHRASES = (
    "valuable insights", "fascinating", "crucial role", "important to note",
    "sheds light on", "plays a key role", "it is worth noting", "in conclusion",
    "delve into", "rich history", "wide range of",
)

SCRIPT_SYSTEM = """You write production briefs for faceless YouTube videos.

You are given a proven format and a new topic. Match the format's STRUCTURE
exactly - beat count, pacing, person, energy. Do NOT reuse its sentences,
examples, or specific facts.

The `substance` array is the most important field. Each item must be a concrete,
checkable, non-obvious fact about THIS topic: a number, a date, a name, a
mechanism, a documented event. "It is fascinating" is not substance. "The 1977
Vela incident registered a double flash that has never been publicly explained"
is substance. If you are not confident a fact is true, mark it needs_check.

SCRIPT QUALITY. These are not style preferences, they are what separates a
video someone watches from one they close in eight seconds.

- The HOOK is mandatory and it is the single most important line you write. It
  opens the video cold. It must create a specific tension: a stake, a number
  that does not add up, a question the viewer now needs answered. "Asteroids
  have long been a source of fascination and fear" is not a hook. It is a
  throat-clear, and the video dies there.
- Every beat must OPEN WITH A DIFFERENT WORD. A script where six of nine beats
  begin with the same noun reads as a drone, no matter how good the facts are.
- Ban vague value-language. "Valuable insights", "fascinating", "plays a crucial
  role", "it is important to note", "sheds light on" carry no information. Say
  the actual thing instead.
- DELIVER WHAT THE TITLE PROMISES. If the title says "scariest", the beats must
  be frightening. If it implies a countdown or a ranking, the beats must count
  down or rank. A title that promises a list and a body that delivers an
  encyclopedia entry is a bait-and-switch the viewer feels immediately.

Return ONLY JSON."""

SCRIPT_USER = """Format template: {template}
Format archetype: {archetype}
Format rules (these OVERRIDE anything below that conflicts): {notes}
Proven titles in this format:
{titles}

New topic: {topic}
Target title: {title}
Target word count: {words}
Second person: {second_person}

HARD REQUIREMENTS - a response that misses these is rejected:
- Exactly {n_beats} objects in "beats", numbered 1..{n_beats}, together totalling
  roughly {words} words of narration. The arrays below show ONE example element
  each; you must return the full count, not one.
- At least {n_substance} objects in "substance", each about a DIFFERENT aspect
  of the topic. No two may restate the same fact.
- Rewrite the target title so it is natural English. Keep the format's word
  order and rhythm, fix any grammar the template introduced.
- A non-empty "hook" that creates tension in its first sentence. A brief with no
  hook is rejected outright by the renderer.
- "thumbnail_text": 2 to 4 words that DO NOT repeat the title or any fragment of
  it. The viewer has already read the title, so repeating it adds nothing and
  closes the curiosity gap. Name the PAYOFF instead, the worst level or the
  surprising outcome, in words a phone screen can read at a glance.
- No two beats may begin with the same word.
- The beats must actually deliver what the title promises.

Return JSON exactly:
{{
  "title": "...",
  "alt_titles": ["...", "...", "..."],
  "thumbnail_text": "2-4 words for the thumbnail, NOT from the title",
  "hook": "2 sentences, spoken, opening on tension not throat-clearing",
  "beats": [
    {{"beat": 1, "narration": "...", "visual": "image prompt for this beat",
      "seconds": 12}}
  ],
  "substance": [
    {{"claim": "...", "why_it_matters": "...", "needs_check": true}}
  ],
  "description": "3 sentences, keyword dense, no hashtags",
  "hashtags": ["...", "...", "..."],
  "tags": ["...", "..."],
  "end_screen_followup": "the next video title this one should point at"
}}"""


# Groq counts prompt PLUS reserved completion against the tokens-per-minute
# limit. The prompt here is only about 950 tokens, but a flat max_tokens=8000
# pushed every single request to ~8950 against an 8000 TPM ceiling, so `brief`
# returned HTTP 413 on the on-demand tier no matter which model was chosen. It
# could never have completed on this account.
#
# Budget the completion from the script length actually asked for instead: the
# JSON carries narration (roughly 1.4 tokens per word) plus visuals, substance,
# description and tags, so ~3 tokens per word with a floor for structure. The
# ceiling leaves room for the prompt underneath the TPM cap.
_TPM_CEILING = 8000
_PROMPT_HEADROOM = 1200


def _completion_budget(words: int) -> int:
    """Completion tokens to reserve for a `words`-long script."""
    want = int(words) * 3 + 1500
    return max(1500, min(want, _TPM_CEILING - _PROMPT_HEADROOM))


def build(spec: dict, bend: dict, *, words: int = 1200, model: str | None = None) -> dict:
    """Generate the brief. One Groq call, zero YouTube quota."""
    tf = spec.get("title_format", {})
    titles = spec.get("titles", [])[:8]
    title = bend.get("proposed_title") or f"{bend.get('topic','')}"

    # ~150 spoken words per beat keeps each visual on screen roughly 45-60s at
    # normal narration pace. Clamped so a 400-word test still gets structure and
    # a 3000-word doc does not ask for forty beats in one completion.
    n_beats = max(4, min(20, round(words / 150)))
    # Ask for headroom above the gate so a single weak item does not block the
    # whole brief; gate() is the floor, not the target.
    n_substance = config.MIN_SUBSTANCE_ITEMS + 2

    out = chat_json(
        SCRIPT_SYSTEM,
        SCRIPT_USER.format(
            template=tf.get("template", "{topic}"),
            archetype=tf.get("archetype", "other"),
            notes=spec.get("notes") or "none",
            titles="\n".join(f"- {t}" for t in titles),
            topic=bend.get("topic", ""),
            title=title,
            words=words,
            n_beats=n_beats,
            n_substance=n_substance,
            second_person=bool(tf.get("second_person_rate", 0) >= 0.5),
        ),
        model=model, temperature=0.75, max_tokens=_completion_budget(words),
    )
    out["format_slug"] = spec.get("slug", "")
    out["topic"] = bend.get("topic", "")
    out["bend"] = {k: bend.get(k) for k in
                   ("distance", "opportunity", "why", "search_term", "saturation")}
    out["thumbnail_spec"] = thumbnail_spec(spec, bend)
    out["generated_at"] = datetime.now(timezone.utc).isoformat()
    return out


def thumbnail_spec(spec: dict, bend: dict) -> dict:
    """Turn the measured thumbnail checklist into build instructions."""
    cl = spec.get("thumbnail_checklist", {})
    rules = list(cl.get("rules", []))
    instructions = []
    layout = cl.get("dominant_layout", "single_center_subject")
    n = cl.get("subject_count_mode", 1)

    if layout in ("three_subject", "multi_subject"):
        instructions.append(f"Compose {n} subjects across the frame, evenly spaced.")
        if cl.get("middle_unique_rate", 0) >= 0.6:
            instructions.append(
                "Flanking subjects should be instantly recognisable examples of "
                f"{bend.get('topic','the topic')}; the CENTER subject must be the "
                "unfamiliar one. Familiar-familiar-unknown is what drives the click."
            )
    elif layout == "two_subject_versus":
        instructions.append("Two subjects, split frame, clear visual opposition.")
    elif layout == "scene_no_clear_subject":
        instructions.append(
            "Atmospheric scene, not a cut-out subject. The frame reads as an "
            "environment; mood and colour carry the click, and the text does the "
            "naming. Do not paste a centred hero object onto a backdrop.")
    else:
        instructions.append("One subject, centered, filling roughly half the frame.")

    if cl.get("header_text_rate", 0) >= 0.6:
        instructions.append("Header text band across the top ~25% of the frame.")
    if cl.get("avg_saturation", 0) >= 0.5:
        instructions.append(f"Push saturation to ~{cl.get('avg_saturation'):.2f} (format norm).")
    if cl.get("avg_contrast", 0) >= 0.22:
        instructions.append(f"Hold contrast near {cl.get('avg_contrast'):.2f} (format norm).")

    return {
        "layout": layout,
        "subject_count": n,
        "palette": cl.get("signature_palette", []),
        "measured_rules": rules,
        "instructions": instructions,
        "verify_with": "python -m formatengine verify-thumb <file> --format " + spec.get("slug", ""),
    }


# ── the gate ────────────────────────────────────────────────────────────────
def gate(brief: dict, spec: dict) -> dict:
    """Pass/fail a brief before it costs you a render.

    Three checks, each mapping to a real way these channels die.
    """
    checks, failures, warnings = [], [], []

    # 1. Did we clone the source title rather than bend it?
    src_sim = max((similarity(brief.get("title", ""), t) for t in spec.get("titles", [])),
                  default=0.0)
    ok = src_sim <= config.MAX_TITLE_SIMILARITY_TO_SOURCE
    checks.append({"check": "title_vs_source", "value": src_sim,
                   "limit": config.MAX_TITLE_SIMILARITY_TO_SOURCE, "pass": ok})
    if not ok:
        failures.append(
            f"Title is {src_sim:.0%} similar to a source title. That is a clone, "
            f"not a bend. Change the topic noun, keep the structure.")

    # 2. Are YOUR OWN recent uploads converging into a template?
    recent = store.recent_shipped()
    self_sims = [similarity(brief.get("title", ""), r.get("title", "")) for r in recent]
    peak = max(self_sims) if self_sims else 0.0
    avg = sum(self_sims) / len(self_sims) if self_sims else 0.0
    ok = peak <= config.MAX_SELF_SIMILARITY_ROLLING
    checks.append({"check": "self_similarity_peak", "value": round(peak, 3),
                   "limit": config.MAX_SELF_SIMILARITY_ROLLING, "pass": ok,
                   "window": len(recent)})
    if not ok:
        failures.append(
            f"This title is {peak:.0%} similar to one of your own last "
            f"{len(recent)} uploads. Format consistency is good; near-identical "
            f"titles are what the inauthentic-content policy actually flags.")
    elif avg > 0.6 and len(recent) >= 4:
        warnings.append(
            f"Your last {len(recent)} titles average {avg:.0%} similarity to each "
            f"other. Still inside the format, but drift the topics further apart.")

    # 3. Is there anything in this video that is not in the source format?
    substance = [s for s in brief.get("substance", []) if isinstance(s, dict) and s.get("claim")]
    ok = len(substance) >= config.MIN_SUBSTANCE_ITEMS
    checks.append({"check": "substance_items", "value": len(substance),
                   "limit": config.MIN_SUBSTANCE_ITEMS, "pass": ok})
    if not ok:
        failures.append(
            f"Only {len(substance)} original substance items (need "
            f"{config.MIN_SUBSTANCE_ITEMS}). Without them this is a reskin, which "
            f"is the exact thing that gets a channel demonetised.")

    # 4. Is the SCRIPT watchable? The three checks above only measure whether a
    #    brief is ORIGINAL. A brief can pass all of them and still be unwatchable
    #    filler, which is exactly what shipped in the asteroid render: no hook,
    #    six of nine beats opening on the word "Asteroid", and "valuable
    #    insights" four times. Originality and watchability are different axes.
    beats = [b for b in brief.get("beats", []) if isinstance(b, dict)]
    narrations = [(b.get("narration") or "").strip() for b in beats]

    hook = (brief.get("hook") or "").strip()
    ok = len(hook.split()) >= 5
    checks.append({"check": "hook_present", "value": len(hook.split()), "limit": 5, "pass": ok})
    if not ok:
        failures.append(
            "No usable hook. compose() leads the video with it, so an empty hook "
            "ships a video that opens cold on its first expository beat. That is "
            "the single biggest reason a faceless video loses the first 8 seconds.")

    openers = [n.split()[0].strip(_PUNCT).lower() for n in narrations if n.split()]
    if openers:
        top, n_top = Counter(openers).most_common(1)[0]
        limit = max(2, len(openers) // 3)
        ok = n_top <= limit
        checks.append({"check": "beat_opener_variety", "value": f"{top} x{n_top}",
                       "limit": limit, "pass": ok})
        if not ok:
            failures.append(
                f"{n_top} of {len(openers)} beats open with the word '{top}'. "
                f"That reads as a drone however good the facts are. Vary the "
                f"opening word of every beat.")

    body = " ".join(narrations).lower()
    hits = [ph for ph in FILLER_PHRASES if body.count(ph) >= 2]
    ok = not hits
    checks.append({"check": "filler_phrases", "value": hits, "limit": [], "pass": ok})
    if not ok:
        failures.append(
            "Repeated filler: " + ", ".join(f"'{h}' x{body.count(h)}" for h in hits) +
            ". These phrases carry no information. Say the actual thing instead.")

    unchecked = [s["claim"] for s in substance if s.get("needs_check")]
    if unchecked:
        warnings.append(f"{len(unchecked)} claims are flagged needs_check - verify before scripting.")

    return {"passed": not failures, "checks": checks,
            "failures": failures, "warnings": warnings}


# ── output ──────────────────────────────────────────────────────────────────
def to_markdown(brief: dict, spec: dict, gate_result: dict) -> str:
    tf = spec.get("title_format", {})
    ts = brief.get("thumbnail_spec", {})
    sat = (brief.get("bend") or {}).get("saturation") or {}
    status = "PASS" if gate_result["passed"] else "BLOCKED"

    out = [
        f"# {brief.get('title','(untitled)')}",
        "",
        f"**Gate:** {status}  |  **Format:** `{spec.get('slug','')}`  "
        f"|  **Bend:** {(brief.get('bend') or {}).get('distance','?')}  "
        f"|  **Opportunity:** {(brief.get('bend') or {}).get('opportunity','?')}",
        "",
    ]
    if gate_result["failures"]:
        out += ["## Blocking issues", ""] + [f"- {f}" for f in gate_result["failures"]] + [""]
    if gate_result["warnings"]:
        out += ["## Warnings", ""] + [f"- {w}" for w in gate_result["warnings"]] + [""]

    out += [
        "## Market check", "",
        f"- Demand (median views, top results for `{sat.get('search_term','')}`): "
        f"**{sat.get('demand_median_views',0):,}**",
        f"- Competition in this exact format, last 180d: **{sat.get('competition_count',0)}**",
        f"- Verdict: **{sat.get('verdict','unchecked')}**",
        "",
        "## Packaging (copy this hard)", "",
        f"- Template: `{tf.get('template','')}`",
        f"- Archetype: {tf.get('archetype','')}",
        f"- Alt titles: " + " | ".join(brief.get("alt_titles", [])[:3]),
        "",
        "### Thumbnail", "",
        f"- Layout: **{ts.get('layout','')}** ({ts.get('subject_count','?')} subjects)",
    ]
    for i in ts.get("instructions", []):
        out.append(f"- {i}")
    pal = ", ".join(c["hex"] for c in ts.get("palette", [])[:5])
    if pal:
        out.append(f"- Signature palette: {pal}")
    out += ["", "## Substance (must differ from the source format)", ""]
    for s in brief.get("substance", []):
        mark = " *(verify)*" if s.get("needs_check") else ""
        out.append(f"- **{s.get('claim','')}**{mark} - {s.get('why_it_matters','')}")

    out += ["", "## Script", "", f"**Hook:** {brief.get('hook','')}", ""]
    for b in brief.get("beats", []):
        out.append(f"**Beat {b.get('beat','?')}** ({b.get('seconds','?')}s)")
        out.append(f"> {b.get('narration','')}")
        out.append(f"`visual:` {b.get('visual','')}")
        out.append("")

    out += [
        "## Metadata", "",
        f"**Description:**\n\n{brief.get('description','')}",
        "",
        "**Hashtags:** " + " ".join(brief.get("hashtags", [])),
        "",
        "**Tags:** " + ", ".join(brief.get("tags", [])),
        "",
        f"**End screen should point at:** {brief.get('end_screen_followup','')}",
        "",
        "## Upload checklist", "",
        "- [ ] Made for kids: **NO** (channel setting AND video setting)",
        "- [ ] Channel keywords set, country set to your real country",
        "- [ ] Auto-dubbing ON (free reach in other languages)",
        "- [ ] End screen added, pointing at the follow-up above",
        "- [ ] Altered/synthetic content disclosure set if the visuals are AI-generated",
        "",
        "---",
        "",
        "*Generated by format-engine. Packaging copied deliberately; substance is original.*",
    ]
    return "\n".join(out)


def save(brief: dict, spec: dict, gate_result: dict) -> tuple:
    slug = store.slugify(brief.get("title", "brief"))
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    base = config.BRIEFS / f"{slug}-{stamp}"
    payload = {**brief, "gate": gate_result}
    jpath = store.write_json(base.with_suffix(".json"), payload)
    mpath = base.with_suffix(".md")
    mpath.write_text(to_markdown(brief, spec, gate_result), encoding="utf-8")
    if gate_result["passed"]:
        store.record_shipped(brief)
    return jpath, mpath
