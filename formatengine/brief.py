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
- NO GRAPHIC BODILY HARM. Keep the stakes, lose the anatomy. Peril, pressure,
  heat, cold, silence, failure and death are all fine; blood, flesh, peeling
  skin, corpses, dissolving organs and vomit are not. This is an
  advertiser-friendliness rule, not taste: a script saturated with injury detail
  gets limited ads, and these formats live on ad revenue. Write the disaster
  from the OUTSIDE - what fails, how fast, what it costs - not from inside a body.
- Ban vague value-language. "Valuable insights", "fascinating", "plays a crucial
  role", "it is important to note", "sheds light on" carry no information. Say
  the actual thing instead.
- MATCH THE FORMAT'S VOICE, which the user message states explicitly under
  "Voice". Some formats are second person and present tense, putting the viewer
  inside the event; others are explainers that describe real events from the
  outside. Follow the one you are given and do not drift into the other. An
  explainer forced into second person invents a protagonist who was never
  there, which is worse than either register done properly.
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
- Voice: {voice_rule}
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

THE ONLY FACTS YOU MAY USE. These were researched and fact-checked for this
video. Build the beats out of THESE and nothing else. Do not introduce a
different incident, mission or spacecraft, however famous:
{facts}

Anything not in that list is something you are inventing, and inventing gets the
whole brief thrown away. If a beat needs a detail you do not have, write around
it instead of guessing. Do not state a date unless it appears above, and never
give two different dates for the same event.

ALREADY COVERED. Do not restate any of it. Each number, name and operation
below has been used; using it again is filler the viewer feels:
{covered}

The script so far ENDED with this line:
{tail}

Write ONLY beats {first} through {last} inclusive, continuing from that line,
totalling roughly {words} words of narration.

HARD REQUIREMENTS - a response that misses these is rejected:
- Exactly {n} objects in "beats", numbered {first}..{last}.
- Voice: {voice_rule}
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

{source_block}

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

EVERY CLAIM IS CHECKED AGAINST WIKIPEDIA AFTER YOU WRITE IT. A claim whose
dates do not appear in the encyclopedia article about its subject is rejected
and the brief is blocked, so inventing a specific-sounding fact costs more than
omitting one.

- Name a real, well-documented event and get its subject right. Do not blend two
  events into one. A previous attempt claimed "the Soviet Venera-9 broke apart in
  Earth orbit in 1978, scattering plutonium" - Venera 9 was a Venus mission, and
  the event being half-remembered was Kosmos 954. That brief was thrown away.
- If you are not certain of a date, a name or a number, either leave it out or
  set needs_check true. needs_check true is a normal, correct answer and costs
  you nothing. A confident wrong date is the expensive one.
- Prefer fewer, solid, checkable claims over more that sound impressive."""


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
        out = _build_chunked(spec, bend, words=words, model=model,
                             n_beats=n_beats, n_substance=n_substance,
                             title=title, tf=tf, titles=titles)
        # This used to `return _build_chunked(...)` directly, which skipped the
        # finishing block below. Every chunked brief therefore shipped with no
        # format_slug, topic, bend or thumbnail_spec - so template decay could
        # not count it, and two ledger rows were recorded with an empty slug.
        return _finalize(out, spec, bend)

    out = chat_json(
        SCRIPT_SYSTEM,
        SCRIPT_USER.format(
            template=tf.get("template", "{topic}"),
            archetype=tf.get("archetype", "other"),
            notes=spec.get("notes") or "none",
            titles="\n".join(f"- {t}" for t in titles),
            topic=_topic_line(bend),
            title=title,
            words=words,
            n_beats=n_beats,
            n_substance=n_substance,
            second_person=bool(tf.get("second_person_rate", 0) >= 0.5),
            voice_rule=_voice_rule(spec),
        ),
        model=model, temperature=0.75, max_tokens=_completion_budget(words),
    )
    return _finalize(fix_beat_openers(out, model=model), spec, bend)


def source_text(bend: dict, *, limit: int = 4000) -> tuple[str, str]:
    """Encyclopedia text for this video's subject, as grounding for the shell.

    Checking facts the model invented from memory is the wrong order. Across
    three regenerations on one topic the model produced, with every date
    correct, a Venus probe that broke up in Earth orbit, a Rogers Commission
    report on Columbia, and an anti-satellite RTG that was really a radar
    reconnaissance satellite with a uranium reactor. Fabrication was not an
    accident to be caught afterwards, it was the default behaviour of asking a
    small model for specifics it does not hold.

    So the substance call is given real text and told to draw from it. The
    fact check then becomes a regression test rather than the only defence.

    Returns (article_title, text). Both empty when nothing resolves, in which
    case generation falls back to unggrounded and the gate still applies.
    """
    from .verify import article_text, resolve_article
    # TOPIC first. The topic is what the video is ABOUT; the external hook is
    # only what it collides with. Grounding on the hook produced a Chernobyl
    # video wearing a space title: the facts were impeccable (1,661 fuel
    # channels, 134 workers, 28 deaths) and all about Ukraine in 1986.
    for candidate in ((bend.get("topic") or "").strip(),
                      (bend.get("external_hook") or "").strip()):
        if not candidate:
            continue
        title = resolve_article(candidate)
        if not title:
            continue
        text = article_text(title)
        if text:
            return title, text[:limit]
    return "", ""


def _covered_block(beats: list) -> str:
    """Facts already spent by earlier beats, so a later chunk cannot re-tell them."""
    from .verify import _facts_in
    spent: set[str] = set()
    for b in beats or []:
        if isinstance(b, dict):
            spent |= _facts_in(b.get("narration") or "")
    return (NEWLINE.join("- " + f for f in sorted(spent))
            if spent else "- (nothing yet, this is the opening)")


def _facts_block(shell: dict) -> str:
    """The shell's researched claims, as the only material the beats may use."""
    items = [s for s in (shell.get("substance") or []) if isinstance(s, dict)]
    lines = []
    for s in items:
        claim = (s.get("claim") or "").strip()
        if claim:
            lines.append(f"- {claim}"
                         + ("  [UNVERIFIED - do not lead a beat with this]"
                            if s.get("needs_check") else ""))
    hook = (shell.get("hook") or "").strip()
    if hook:
        lines.insert(0, f"- (opening line, already written) {hook}")
    return NEWLINE.join(lines) if lines else "- (none supplied)"


def _topic_line(bend: dict) -> str:
    """Topic, plus the packaging promise the script has to honour.

    Packaging-first makes the title a promise, and the gate now blocks a script
    whose narration never mentions the external hook. Telling the model about
    the hook here is cheaper than letting it fail that check: a 2026-09-23
    brief titled "Real Chernobyl In Space?" spent three of four beats on
    Galileo, Challenger and Columbia, none of them nuclear.
    """
    topic = bend.get("topic", "") or ""
    hook = (bend.get("external_hook") or "").strip()
    if not hook:
        return topic
    return (f"{topic}. The packaging promises a collision with {hook!r}, so the "
            f"narration MUST reference {hook!r} explicitly at least once and the "
            f"beats must stay on that angle. A script that never mentions it is "
            f"rejected.")


def _voice_rule(spec: dict) -> str:
    """The voice instruction for this format, matching what the gate enforces.

    Kept next to _second_person_floor deliberately: if the prompt demands one
    register and the gate measures another, the model is pushed into whichever
    the gate punishes, which is how an explainer about an unmanned satellite
    got written as a first-person death scene.
    """
    if _second_person_floor(spec) > 0:
        return ('SECOND PERSON, present tense. Address the viewer as '
                '"you"/"your" at least 6 times per 100 words, spread across '
                'every beat. Write what is happening TO THE VIEWER: "You are '
                'in the kitchen when the lights stutter", not "Residential '
                'lighting flickers".')
    return ('THIRD PERSON EXPLAINER, past tense for events that happened. '
            'Describe the real event from the outside: what failed, how fast, '
            'what it cost, who dealt with it. Do NOT address the viewer as '
            '"you" and do NOT invent a person experiencing it. If the subject '
            'is an unmanned satellite, nobody was aboard, so there is no one '
            'to put the viewer inside.')


def _second_person_floor(spec: dict) -> float:
    """Second-person floor for THIS format, from its own measurement.

    The fourth time this project globalised a threshold measured on one niche.
    MIN_SECOND_PERSON_PER_100 = 4.0 came from "your life as" style channels,
    where the viewer IS the subject. It was then enforced on every format,
    including `bluntly-explained`, whose own measured second_person_rate is
    0.10 - an explainer, not an immersion piece.

    The damage was not a spurious failure, it was the opposite: the gate FORCED
    the wrong register. A 2026-09-18 brief about Kosmos 954, an UNMANNED
    satellite, was written as a crewed first-person death scene ("your ears
    pop", "you check the oxygen gauge") because that was the only way to clear
    a floor the format never earned.

    second_person_rate is the share of the format's source videos that address
    the viewer. Above half, the format really is second person and the measured
    floor applies. At or below half it does not, and an explainer is allowed to
    explain. A spec may override with title_format.min_second_person.
    """
    tf = spec.get("title_format") or {}
    override = tf.get("min_second_person")
    if override is not None:
        try:
            return float(override)
        except (TypeError, ValueError):
            pass
    try:
        measured = float(tf.get("second_person_rate") or 0.0)
    except (TypeError, ValueError):
        measured = 0.0
    return config.MIN_SECOND_PERSON_PER_100 if measured >= 0.5 else 0.0


def _finalize(out: dict, spec: dict, bend: dict) -> dict:
    """Stamp the fields every brief needs, whichever generation path made it."""
    out["format_slug"] = spec.get("slug", "")
    out["topic"] = bend.get("topic", "")
    out["bend"] = {k: bend.get(k) for k in
                   ("distance", "opportunity", "why", "search_term", "saturation")}
    out["thumbnail_spec"] = thumbnail_spec(spec, bend)
    out["generated_at"] = datetime.now(timezone.utc).isoformat()
    return out



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
    src_title, src_text = source_text(bend)
    if src_text:
        print(f"  grounding substance in Wikipedia: {src_title}")
        source_block = (
            "SOURCE TEXT. Every substance claim must come from the passage "
            f"below, which is the Wikipedia article on {src_title!r}. Take the "
            "numbers, dates and names FROM IT rather than from memory, and do "
            "not add specifics it does not contain. If the passage does not "
            "support a claim you wanted to make, drop that claim.\n"
            "---\n" + src_text + "\n---")
    else:
        source_block = ("No source text could be retrieved, so keep the claims "
                        "general and set needs_check true on anything specific.")

    out = chat_json(
        SCRIPT_SYSTEM,
        SHELL_USER.format(
            template=tf.get("template", "{topic}"),
            archetype=tf.get("archetype", "other"),
            notes=spec.get("notes") or "none",
            titles=NEWLINE.join("- " + str(x) for x in titles),
            topic=_topic_line(bend),
            title=title,
            n_substance=n_substance,
            source_block=source_block,
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
                    topic=_topic_line(bend),
                    tail=tail,
                    first=made + 1, last=made + take, n=take,
                    words=chunk_words,
                    voice_rule=_voice_rule(spec),
                    # Anchor the beats to the SHELL's researched facts. Without
                    # this the only anchor was the topic string, which for a
                    # packaged brief is something generic like "space disaster",
                    # so the beats wandered: a script whose hook was Kosmos 954
                    # spent all four beats on Columbia, gave two different dates
                    # for the same reentry, and credited the Rogers Commission
                    # (which investigated Challenger) with the Columbia report.
                    facts=_facts_block(out),
                    # Every chunk previously saw only the LAST beat's tail, so
                    # chunk 3 happily re-told what chunk 1 covered. Listing the
                    # facts already spent is what stops that.
                    covered=_covered_block(beats)),
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
    #    Hide this title's own unpublished draft row, or regenerating a brief
    #    fails for being 100% similar to its own previous attempt.
    recent = store.recent_shipped(exclude_draft_title=brief.get("title", ""))
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

    # 4c. Does the script actually DELIVER the hook the packaging promised?
    #     Packaging-first means the title is a promise. A 2026-09-23 brief
    #     titled "Real Chernobyl In Space?" opened on a nuclear satellite and
    #     then spent three of four beats on Galileo, Challenger and Columbia,
    #     none of them nuclear. The collision was in the title and the thumbnail
    #     and nowhere in the video, which is the bait-and-switch a viewer feels
    #     immediately. Mechanical check only: the hook's own words must appear
    #     in the narration somewhere.
    ext_hook = (brief.get("external_hook") or "").strip()
    if ext_hook:
        from .freshness import _tokens
        # Only DISTINCTIVE hook words count. "Chernobyl disaster" shares
        # "disaster" with ordinary script vocabulary, and a script about the
        # Columbia shuttle passed this check on that word alone while never
        # mentioning Chernobyl. Same lesson as the saturation filter.
        generic = _tokens("disaster event incident accident failure crisis "
                          "explosion story history moment case")
        want = _tokens(ext_hook) - generic
        if not want:                       # hook is entirely generic words
            want = _tokens(ext_hook)
        body_tokens = _tokens(" ".join(narrations))
        hit = bool(want & body_tokens)
        checks.append({"check": "hook_delivered", "value": hit,
                       "limit": True, "pass": hit})
        if not hit:
            failures.append(
                f"The packaging promises {ext_hook!r} but the narration never "
                "mentions it. The title and thumbnail carry the collision and "
                "the script does not deliver it, which is a bait-and-switch. "
                "Work the hook into the beats or repackage the video.")

    # 4d. Are the beats restating each other's facts? Chunked generation only
    #     shows each call the PREVIOUS beat's tail, so later chunks re-tell what
    #     earlier ones already covered. A 2026-09-24 brief gave Operation
    #     Morning Light and the twelve recovered pieces in two separate beats
    #     and the Canadian invoice in two more. Whole-beat similarity cannot see
    #     it; repeated facts can.
    from .verify import check_repetition
    rep = check_repetition(
        brief, exclude=f"{brief.get('topic','')} {brief.get('external_hook','')}")
    ok = rep["count"] <= config.MAX_REPEATED_FACTS
    checks.append({"check": "fact_repetition", "value": rep["count"],
                   "limit": config.MAX_REPEATED_FACTS, "pass": ok})
    if not ok:
        failures.append(
            f"{rep['count']} facts are restated across beats "
            f"({', '.join(rep['repeated'][:5])}). Three known-good briefs "
            "repeat none. Each beat has to advance the story; re-telling the "
            "same number in new words is filler the viewer feels.")

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
    floor = _second_person_floor(spec)
    # A zero floor means this format is an explainer and the check does not
    # apply; reporting it as "0.0 >= 0.0 pass" would imply a rule was met.
    if floor <= 0:
        checks.append({"check": "second_person_per_100w", "value": rate,
                       "limit": "n/a (explainer format)", "pass": True})
    else:
        ok = rate >= floor
        checks.append({"check": "second_person_per_100w", "value": rate,
                       "limit": floor, "pass": ok})
        if not ok:
            failures.append(
                f"Narration uses second person {rate} times per 100 words, "
                f"below this format's floor of {floor}. This format's source "
                f"videos do address the viewer, so at {rate} the script reads "
                f"as an encyclopedia entry rather than something happening to "
                f"them. Rewrite in second person, present tense.")

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
