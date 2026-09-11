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
import re
import statistics
import time

NEWLINE = chr(10)
statistics
re
from collections import Counter
from datetime import datetime, timezone

from . import config, store
from .bend import similarity
from .llm import LLMError, chat_json

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
- Every beat must OPEN WITH A DIFFERENT WORD, and no opening word may be reused
  more than twice in the whole script. A script where six of nine beats begin
  with the same noun reads as a drone, no matter how good the facts are.
- NEVER OPEN A BEAT WITH "You" OR "Your". This is the trap set by the second
  person rule below: "You" is the obvious opener, and taking it produces a
  script where all eight beats start identically, which is rejected. Keep the
  second person, move it OFF the first word. Not "You feel the heat rise" but
  "The heat rises before you hear anything". Open on a noun, verb, number or
  time. This single rule is the most common reason a brief is blocked.
- Ban vague value-language. "Valuable insights", "fascinating", "plays a crucial
  role", "it is important to note", "sheds light on" carry no information. Say
  the actual thing instead.
- WRITE IN SECOND PERSON, PRESENT TENSE. "You're four years old in a cramped
  kindergarten" beats "Visible light dances across the polar horizon". Measured
  across nine working channels in these formats, narration averages 6.1 uses of
  you/your per 100 words; a script at 0 reads as an encyclopedia entry, because
  an encyclopedia is precisely the register that never addresses its reader.
- SHORT SENTENCES. Working scripts run a median of 8 words per sentence. Break
  the long ones. "You're four." "You have nothing left." "You're done."
- NAME THINGS. 3.2 proper nouns per 100 words in working scripts. Marco.
  Modesto. Kim Il-Sung. Night of the Living Dead. Not "satellites in low Earth
  orbit experience mild drag".
- ONE COMPARISON-JOKE PER BEAT, built as a simile: "the problem solving skills
  of a broken toaster", "slower than your great aunt Gertrude after Thanksgiving
  dinner". This is a template, not a talent.
- HAVE AN OPINION. "Their lyrics are stupid. No redeemable qualities
  whatsoever." Encyclopedias never judge; every script that works does.
- NEVER DESCRIBE YOUR OWN STRUCTURE. "The axis of escalation is economic and
  infrastructural damage" is the video explaining its own format to the viewer.
  No working script does this. Show the escalation, do not announce it.
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
- SECOND PERSON. The narration must address the viewer as "you"/"your" at least
  6 times per 100 words, spread across every beat. A script that never says
  "you" is rejected outright. Write what is happening TO THE VIEWER: "You're in
  the kitchen when the lights stutter", not "Residential lighting flickers".
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



SCRIPT_MORE_USER = """You are continuing a script that is already underway. Do not
restart it and do not re-introduce the topic.

Title: {title}
Format rules (these OVERRIDE anything that conflicts): {notes}
Topic: {topic}

The script so far ENDED with this line:
{tail}

Write ONLY beats {first} through {last} inclusive, continuing from that line,
totalling roughly {words} words of narration.

HARD REQUIREMENTS - a response that misses these is rejected:
- Exactly {n} objects in "beats", numbered {first}..{last}.
- SECOND PERSON throughout: address the viewer as "you"/"your" at least 6 times
  per 100 words. A beat that never says "you" is rejected.
- Short sentences, median around 8 words.
- Each beat opens on a DIFFERENT word from the one before it, and NO opening
  word may be reused more than twice in the whole script.
- NEVER open a beat with "You" or "Your". This is the trap: the second-person
  rule above makes "You" the obvious opener, and scripts that take it get
  rejected for reading as a drone. Put the "you" INSIDE the sentence instead.
  Not "You feel the heat rise" but "The heat rises before you hear anything".
  Open on a noun, a verb, a number, or a time.
- Escalate. Every beat must be worse or bigger than the one before it.

Return ONLY JSON of the form:
{{"beats": [{{"beat": {first}, "narration": "...", "visual": "...", "seconds": 30}}]}}
"""

SHELL_USER = """Format template: {template}
Format archetype: {archetype}
Format notes: {notes}
Existing titles in this format:
{titles}

Topic: {topic}
APPROVED TITLE (already decided, do not change it): {title}

Write ONLY the shell of this video. NO beats, no narration. Beats come later.

Return JSON exactly:
{{
  "title": "{title}",
  "hook": "the cold-open line, 15-30 words, a stake or a number that does not add up",
  "substance": [
    {{"claim": "a specific checkable fact about THIS topic - a number, a date, a name, a documented event",
      "why_it_matters": "one sentence",
      "needs_check": false}}
  ],
  "thumbnail_text": "2-4 words",
  "description": "2 sentences",
  "hashtags": ["#tag"],
  "tags": ["search tag"],
  "end_screen_followup": "a title for the next video"
}}

Exactly {n_substance} substance items. They are the whole point of this call:
without them the video is a reskin of someone else's video and gets
demonetised. "It is fascinating" is not a claim. "The 1977 Vela incident
registered a double flash that has never been publicly explained" is a claim.
If you are not confident a fact is true, set needs_check true."""


def _raw_demand(words: int) -> int:
    """Output tokens a `words`-long script actually needs, UNCLAMPED.

    Kept separate from the reservation because the chunking decision must see
    true demand. Reading the clamped value instead meant every size looked
    identical at the ceiling, so the chunked path could never trigger and a
    7-beat script was attempted inside one 900-token reservation.

    ~2.2 tokens per narration word covers the JSON envelope and the visual and
    seconds fields alongside the prose; +200 is the shell (title, hook, tags).
    """
    return int(int(words) * 2.2 + 200)


def _completion_budget(words: int) -> int:
    """Completion tokens to reserve for one call.

    The old formula was `words * 3 + 1500` with a floor of 1500, built for a
    believed 8000 tokens/minute budget. The real constraint, seen live as a 429
    on 2026-09-11, is OUTPUT tokens per minute and it is 1000. A floor of 1500
    exceeded the entire per-minute allowance on its own, so even a 200-word
    request was unservable.

    Three ceilings, smallest wins. Normally TPM_SAFE_COMPLETION (the safety
    margin we choose) is lowest, but GROQ_OTPM_LIMIT is env-overridable and can
    be set BELOW it when a model's real cap is smaller, so both are kept.
    The max(300, ...) floor also absorbs a zero or negative `words`.
    """
    ceiling = min(_TPM_CEILING - _PROMPT_HEADROOM,
                  config.GROQ_OTPM_LIMIT, config.TPM_SAFE_COMPLETION)
    return max(300, min(_raw_demand(words), ceiling))


def build(spec: dict, bend: dict, *, words: int = 2500, model: str | None = None) -> dict:
    """Generate the brief. One Groq call, zero YouTube quota."""
    tf = spec.get("title_format", {})
    titles = spec.get("titles", [])[:8]
    title = bend.get("proposed_title") or f"{bend.get('topic','')}"

    # Default raised 1200 -> 2500. Nine working channels in these formats run a
    # 2,462-word median (1,990-3,264), which at ~165 wpm is the 14-15 minute
    # runtime the format actually wins at. Our 313-word script was 8x short.
    # NOTE: length drives cost roughly linearly - TTS, shot count and b-roll
    # fetches all scale with it.
    # ~150 spoken words per beat keeps each visual on screen roughly 45-60s at
    # normal narration pace. Clamped so a 400-word test still gets structure and
    # a 3000-word doc does not ask for forty beats in one completion.
    n_beats = max(4, min(20, round(words / 150)))
    # Ask for headroom above the gate so a single weak item does not block the
    # whole brief; gate() is the floor, not the target.
    n_substance = config.MIN_SUBSTANCE_ITEMS + 2

    # Groq's ceiling is 8000 tokens PER MINUTE and counts prompt plus reserved
    # completion together, so a 2500-word script cannot be asked for in one
    # call. Sizing calls is not sufficient either: the cap is per MINUTE, so
    # several legal calls fired back to back still breach it, which is why the
    # chunks below are paced apart rather than merely small.
    # Must read RAW demand. _completion_budget() is clamped to the ceiling, so
    # comparing it against that same ceiling can never be true and every script,
    # at any length, took the single-call path.
    if _raw_demand(words) > config.TPM_SAFE_COMPLETION:
        return _build_chunked(spec, bend, words=words, model=model,
                              n_beats=n_beats, n_substance=n_substance,
                              title=title, tf=tf, titles=titles)

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
    return fix_beat_openers(out, model=model)



def _build_chunked(spec, bend, *, words, model, n_beats, n_substance,
                   title, tf, titles) -> dict:
    """Generate a long script across several paced calls.

    The first call establishes the SHELL ONLY: hook, substance, thumbnail text,
    description, tags. No beats. Each later call adds beats and is given the
    previous chunk's closing line so the script continues rather than restarting.

    The shell used to share its call with the opening beats. Once max_tokens
    dropped to ~860 to fit the real OTPM ceiling, that call could no longer
    afford both, and the model spent the budget on beats and returned ZERO
    substance items every time - which the gate correctly blocked as a reskin.
    Giving the shell its own call is what makes a small token budget survivable.

    Partial output is kept on failure: a short script can still be judged by the
    gate, whereas an exception loses everything already paid for.
    """
    out = chat_json(
        SCRIPT_SYSTEM,
        SHELL_USER.format(
            template=tf.get("template", "{topic}"),
            archetype=tf.get("archetype", "other"),
            notes=spec.get("notes") or "none",
            titles=NEWLINE.join("- " + str(x) for x in titles),
            topic=bend.get("topic", ""),
            title=title,
            n_substance=n_substance,
        ),
        model=model, temperature=0.7,
        max_tokens=_completion_budget(260),
    )
    got = len([s for s in (out.get("substance") or []) if isinstance(s, dict)])
    print("  shell - hook + " + str(got) + " substance items")
    beats = []
    made = 0

    while made < n_beats:
        take = min(config.CHUNK_BEATS, n_beats - made)
        chunk_words = max(200, round(words * take / n_beats))
        tail = (beats[-1].get("narration", "") if beats else "")[-400:]
        time.sleep(config.CHUNK_GAP_SECONDS)
        try:
            more = chat_json(
                SCRIPT_SYSTEM,
                SCRIPT_MORE_USER.format(
                    title=out.get("title") or title,
                    notes=spec.get("notes") or "none",
                    topic=bend.get("topic", ""),
                    tail=tail,
                    first=made + 1, last=made + take, n=take,
                    words=chunk_words),
                model=model, temperature=0.75,
                max_tokens=_completion_budget(chunk_words),
            )
        except Exception as exc:
            print("  chunk failed (" + type(exc).__name__ + "); keeping "
                  + str(made) + " beats")
            break
        got = [b for b in (more.get("beats") or []) if isinstance(b, dict)
               and (b.get("narration") or "").strip()]
        if not got:
            break
        beats.extend(got)
        made = len(beats)
        total = sum(len((b.get("narration") or "").split()) for b in beats)
        print("  chunk ok - " + str(made) + "/" + str(n_beats)
              + " beats, " + str(total) + " words")

    for i, b in enumerate(beats, 1):
        b["beat"] = i
    out["beats"] = beats
    # Same repair as the single-call path; chunking makes the "You" opener MORE
    # likely, since each chunk only sees its own beats and cannot tell it is
    # repeating the previous chunk's opener.
    return fix_beat_openers(out, model=model)


OPENER_FIX_SYSTEM = """You rewrite the FIRST SENTENCE of a video narration beat.

The sentence currently starts with "You" or "Your". Rewrite it so it starts with
a different word while keeping the second person somewhere inside it.

  "You feel the heat rise."      -> "The heat rises before you feel it."
  "Your suit is already torn."   -> "Already the suit at your shoulder is torn."

Keep the meaning, the tense and roughly the length. Do not add facts. Every
rewritten sentence must start with a DIFFERENT word from the others.

Return ONLY JSON: {"fixed": ["sentence 1", "sentence 2", ...]} in the same order."""


def fix_beat_openers(brief: dict, *, model: str | None = None) -> dict:
    """Repair beats that open on "You", in place.

    Three full regenerations with the rule stated ever more loudly all returned
    8 of 8 beats opening on "You", while second-person density climbed from 9.4
    to 11.3 per 100 words. The model satisfies the loud second-person rule by
    taking the obvious opener, and a negative constraint buried in a 100-line
    prompt does not survive that. A short, single-purpose call does.

    Purely cosmetic on the first word; if the repair fails the brief is returned
    untouched and the gate blocks it as before.
    """
    beats = [b for b in brief.get("beats", []) if isinstance(b, dict)]
    targets = [b for b in beats
               if re.match(r"^\s*your?\b", (b.get("narration") or ""), re.I)]
    if not targets:
        return brief

    firsts = []
    for b in targets:
        text = (b.get("narration") or "").strip()
        m = re.match(r"^(.+?[.!?])(\s|$)", text)
        firsts.append(m.group(1) if m else text)

    # Groq's cap is 8000 tokens per MINUTE, counting prompt plus reserved
    # completion. This call lands seconds after the script call that just
    # reserved most of that, so without pacing it is refused every time. That
    # is exactly what happened: the repair worked perfectly in isolation and
    # never once fired inside build(), because the failure was swallowed below.
    print(f"  fixing {len(targets)} beat openers "
          f"(pausing {config.CHUNK_GAP_SECONDS}s for the Groq per-minute cap)")
    time.sleep(config.CHUNK_GAP_SECONDS)
    try:
        out = chat_json(
            OPENER_FIX_SYSTEM,
            "Rewrite each of these opening sentences:\n"
            + "\n".join(f"{i+1}. {s}" for i, s in enumerate(firsts)),
            model=model, temperature=0.7, max_tokens=900,
        )
        fixed = [str(s).strip() for s in (out.get("fixed") or [])]
    except LLMError as e:
        # Never silent. A swallowed error here looks identical to "the model
        # ignored the prompt", which cost three full regenerations to diagnose.
        print(f"  opener repair FAILED ({e}); gate will block on openers")
        return brief
    if len(fixed) != len(targets):
        print(f"  opener repair returned {len(fixed)} of {len(targets)}; skipped")
        return brief

    for b, old, new in zip(targets, firsts, fixed):
        if not new or re.match(r"^\s*your?\b", new, re.I):
            continue        # repair did not actually fix this one; leave it
        b["narration"] = (b.get("narration") or "").replace(old, new, 1)
    return brief


def thumbnail_spec(spec: dict, bend: dict) -> dict:
    """Turn the measured thumbnail checklist into build instructions."""
    cl = spec.get("thumbnail_checklist", {})
    rules = list(cl.get("rules", []))
    instructions = []
    layout = cl.get("dominant_layout", "single_center_subject")
    n = cl.get("subject_count_mode", 1)

    if layout == "grid_menu":
        # ThePaintProf's two biggest videos (6.18M, 2.67M) are 8-12 captioned
        # icon cells. Describing that as "N subjects evenly spaced" loses the
        # thing that makes it work, which is that each cell is separately
        # labelled and the viewer scans for the one that applies to them.
        instructions.append(
            f"Grid of roughly {cl.get('avg_cells', 8)} small cells, each its own "
            "captioned icon. Not a hero subject.")
        instructions.append(
            "Every cell carries a short readable label underneath. Density is "
            "the promise: the grid shows the whole menu at once so the viewer "
            "finds the item that applies to them personally.")
    elif layout in ("three_subject", "multi_subject"):
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

    # Strip a leading "Level three," label before judging opener variety.
    # The levels-of spec REQUIRES every beat to open with it, because every
    # working channel in the format does; without this strip, the two rules
    # contradict and a correct script is rejected for "8 of 8 beats open with
    # the word level". Variety is measured on what follows the label.
    _LVL = re.compile(r"^\s*level\s+(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten)\s*[,:.\-]?\s*",
                      re.I)
    _ART = re.compile(r"^\s*(?:the|a|an|your|you're)\s+", re.I)
    # Also drop a leading article: after the label is stripped, every beat
    # legitimately starts "the <name>" and the gate would fire on "the".
    stripped = [_ART.sub("", _LVL.sub("", n)) for n in narrations]
    openers = [n.split()[0].strip(_PUNCT).lower() for n in stripped if n.split()]
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

    # 4b. Graphic bodily harm. A brief passed every structural check on
    #     2026-09-11 while describing injury and bodily decay in sustained
    #     detail across all four beats, in a format whose other titles are
    #     "Every Type Of Black Hole Explained". Structure cannot see tone, and
    #     the monetisation risk this project exists to avoid is exactly this.
    #     Policy heuristic, not a measurement, so it warns below the limit and
    #     blocks only when the script is saturated with it.
    from .verify import check_gore
    gore = check_gore(brief)
    ok = gore["count"] <= config.MAX_GORE_MARKERS
    checks.append({"check": "graphic_content", "value": gore["count"],
                   "limit": config.MAX_GORE_MARKERS, "pass": ok})
    if not ok:
        failures.append(
            f"{gore['count']} graphic bodily-harm markers across "
            f"{gore['beats_affected']} beats "
            f"({', '.join(sorted({h['term'].lower() for h in gore['hits']}))}). "
            "That is an advertiser-friendliness problem, not a style note. "
            "Keep the stakes, lose the anatomy.")
    elif gore["count"]:
        warnings.append(
            f"{gore['count']} graphic marker(s): "
            f"{', '.join(sorted({h['term'].lower() for h in gore['hits']}))}. "
            "Under the limit, but check it reads as a documentary rather than a "
            "horror film.")

    # 5. Does the narration address the viewer at all?
    # Reuse the narrations already derived above rather than re-deriving them.
    # The duplicate derivation returned an empty string here and scored every
    # script 0.0, which read as "the model ignores second person" when the
    # script in front of me used "you" 45 times in 620 words.
    narration = " ".join(narrations)
    nwords = max(1, len(narration.split()))
    _PRON = {"you", "your", "you're", "yours", "yourself", "youre"}
    # Tokenise and match a set rather than a word-boundary regex. The regex
    # literal here was mangled by an escaping layer into a backslash followed
    # by "b", which matches nothing, so every script scored 0.0 and looked like
    # a model that refused to write second person. It was the counter.
    you = sum(1 for w in re.split(r"[^A-Za-z']+", narration) if w.lower() in _PRON)
    rate = round(100 * you / nwords, 1)
    ok = rate >= config.MIN_SECOND_PERSON_PER_100
    checks.append({"check": "second_person_per_100w", "value": rate,
                   "limit": config.MIN_SECOND_PERSON_PER_100, "pass": ok})
    if not ok:
        failures.append(
            f"Narration uses second person {rate} times per 100 words; working "
            f"channels in this format average 6.1. At {rate} the script reads as "
            f"an encyclopedia entry rather than something happening to the "
            f"viewer. Rewrite in second person, present tense.")

    # 6. Sentence length. Working scripts sit at a median of 8 words.
    sents = [s for s in re.split(r"(?<=[.!?])\s+", narration) if s.strip()]
    med = statistics.median([len(s.split()) for s in sents]) if sents else 0
    ok = med <= config.MAX_MEDIAN_SENTENCE_WORDS
    checks.append({"check": "median_sentence_words", "value": med,
                   "limit": config.MAX_MEDIAN_SENTENCE_WORDS, "pass": ok})
    if not ok:
        failures.append(
            f"Median sentence is {med} words against a working median of 8. "
            f"Long sentences are what makes narration sound like a bulletin.")

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
