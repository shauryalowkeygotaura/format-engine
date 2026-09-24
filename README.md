# format-engine

Free YouTube format mining. Finds channels whose packaging is breaking out
right now, deconstructs what makes them work, generates topic pivots with a
real demand-vs-competition check, and writes production briefs that are gated
against the thing that actually kills these channels.

Built from three "YouTube automation" tutorials by *adavia*. The research method
in them is sound. The tooling they sell it with is not necessary, and the
production advice is actively dangerous under YouTube's current monetization
policy. This replaces the first and fixes the second.

## What it replaces

| Their stack | Cost | Here |
|---|---|---|
| TubeGen niche finder | paid | `discover`: YouTube Data API v3, free tier |
| VidIQ Pro outlier score | paid | `profile`: leave-one-out median multiples |
| VidIQ Pro search volume | paid | `bend`: measured demand + competition |
| Whiteboard format breakdown | manual | `deconstruct`: Groq + OpenCV |
| ElevenLabs voiceover | paid | `edge-tts` (already in this vault) |
| ChatGPT Plus scripting | paid | Groq free tier |
| TubeGen renderer | paid | ffmpeg + the vault's existing pipelines |

Running cost: **$0**. YouTube Data API gives 10,000 quota units/day free; Groq's
free tier covers the language work; thumbnail analysis is OpenCV running
offline with no API at all.

## Install

```bash
pip install -r requirements.txt
```

Secrets come from Doppler (`YOUTUBE_API_KEY`, `GROQ_API_KEY`), so every command
is prefixed:

```bash
doppler run -p youtube-title-autoresearch -c dev -- python -m formatengine <cmd>
```

## Pipeline

```
discover  →  deconstruct  →  bend  →  hook  →  package  →  brief  →  verify-thumb
 ~350u         ~5u          ~500u     0u        0u          0u          0u
                                      └── packaging decided here, before the script ──┘
```

```bash
# 1. Who is breaking out right now?
python -m formatengine discover --searches 3 --top 14

# 2. Turn the best one into a reusable format spec
python -m formatengine deconstruct UC4ZpfvppuvCefRu3T7p0ojg --name bluntly-explained

# 3. Where can this format go that isn't already crowded?
python -m formatengine bend bluntly-explained -n 10 --check 5

# 4. Is this external hook worth building packaging around? (no API key needed)
python -m formatengine hook "Carl Jung" --niche anime

# 5. Decide the title and thumbnail BEFORE writing anything
python -m formatengine package bluntly-explained \
    --topic "L Lawliet" --hook "Carl Jung" --niche anime

# 6. Write a script that has to fit the approved title
python -m formatengine brief bluntly-explained --package double-agent-carl-jung-2026-09-05

# 7. Check your finished thumbnail against the format you're copying
python -m formatengine verify-thumb my-thumb.jpg --format bluntly-explained

# Anytime
python -m formatengine quota
python -m formatengine formats
```

A full cycle costs roughly 1,400 of the 10,000 daily units, so seven complete
research cycles per day fit inside the free tier.

## The quota trick

`search.list` costs 100 units. `channels.list`, `playlistItems.list` and
`videos.list` cost 1 unit each and return up to 50 items per call.

So profiling a channel properly: pull its uploads playlist, enumerate 50
videos, fetch full stats on all of them: costs **3 units**, while doing the
same thing through search costs 100. Discovery spends a handful of searches to
get a candidate set and then does every bit of real analysis on the 1-unit
endpoints. One search surfacing 25 channels, each profiled at 3u, is 175 units
for 25 fully-scored channels. Per-channel searches would be 2,600.

That single asymmetry is why this is free and a niche-finder SaaS is not.

## What the scoring actually does

**Outlier detection** (`outlier.py`) improves on views-÷-average four ways:

1. **Median, not mean.** One viral video drags a mean up hard enough that the
   viral video stops looking viral.
2. **Leave-one-out baseline.** A video is scored against its channel's *other*
   videos. On a 4-video channel where one did 1M and three did 900, including
   the 1M in its own baseline halves the apparent multiple.
3. **Shorts and long-form scored separately.** A Short at 2M and a 10-minute
   video at 20k are not comparable; pooling them makes every long-form upload
   on a mixed channel look like a failure.
4. **Velocity as well as totals.** Total views reward old videos. views/day
   catches the 3-day-old video mid-explosion: the signal you want *before*
   everyone else copies it.

**RPM** is reported as a band with the label *estimate from category, not
measured*. There is no public API for another channel's RPM. Any tool showing
you a precise dollar figure for someone else's channel invented it.

**Safety filter** auto-drops politics, gambling, medical claims, and explicit
topics at discovery time, and down-weights kids content because it caps RPM
near $1 and triggers COPPA restrictions. The tutorials say "avoid stuff that
gets you banned" and never give the list.

## Saturation: the part the tutorials skip

Their instruction for validating a niche bend is "search it, and if someone's
doing it, check whether they're any good." That is a vibe.

`bend` measures two things from live data and reports them separately:

- **demand**: median views of the current top results for the topic
- **competition**: recent results whose *titles carry the format's own
  signature words*, not merely videos about the same subject

Kept separate on purpose: "nobody is doing this" and "nobody wants this" look
identical once you average them into one number. Real output from a run:

```
  OPP DIST      VERDICT          DEMAND  COMP TITLE
 78.0 adjacent  open            359,880     0 Every Scariest Asteroid Explained
 76.1 lateral   open            191,636     0 Every Scariest Dark Matter Theory Explained
 37.5 adjacent  contested        43,731     3 Every Type Of Nebula Explained
  5.0 adjacent  weak-demand         115     1 Every Type Of Cosmic Ray Explained
```

Asteroids and cosmic rays are equally uncrowded. Only one of them has an
audience.

## Packaging first, and the external hook

Packaging used to be derived from a finished brief. That is backwards, and the
channels this engine copies show it in their own artifacts: a title like
"Kira Case, But It's 2026" cannot have been reverse-engineered out of a
completed analysis video. `package` now produces the title, alternates,
thumbnail text and thumbnail spec on their own, gates them, and `brief
--package` writes a script that has to fit the approved title.

The gate's main input is the **external hook**: the thing in the packaging that
does not come from the source material. Measured 2026-09-04 across 80 videos on
two channels sharing a niche, title templates and runtime, packaging that
collides the in-universe subject with a real-world artifact ran **2.7x-5x on
views/day at matched age**, and the effect replicated on the second channel.

The threshold is **recognition, not recency**, and that distinction was forced
by the data. The obvious design is "is this hook trending". Tested against the
one case with a known outcome, it fails:

```
Jeffrey Epstein, en.wikipedia daily pageviews
  attention peak      2026-02-05 at 1,072,415/day
  video shipped       2026-07-06, 151 days later
  pageviews that day  10,786  =  1% of peak, 0.72x the article's own median
  result              444,864 views — 5.6x that channel's median
```

A freshness gate would have blocked the best video in the sample. So recency is
measured and printed, never enforced. What separates a hook is whether the
audience already recognises it: every hook that worked measured 2,822-12,677
pageviews/day, every in-universe subject measured 2,235/day or less, and
`HOOK_RECOGNITION_FLOOR` splits that gap at 2,500.

### The slang track

Some hooks have no encyclopedia footprint at all, and the highest views/day
video in the reference sample (12,952) was built on one. A second instrument
scores those: YouTube's own result set. Measured 2026-09-05, 12 results asked
for per term:

```
goonpocalypse      n=12   top   1,942,421
skibidi            n=12   top 150,681,962
gooning            n=11   top   4,684,859
"zravnik qplorth"  n=0    (nonsense control)
```

A term nobody uses returns literally nothing, so a full result set plus one
high-view proof is a real signal. Slang hooks therefore **score**, they are not
shrugged at. `UNSCORED` is now reserved for terms neither instrument can see,
which usually means a typo.

Scoreable is not the same as advisable. A hook that only clears the YouTube
track is marked `register: slang`, and so is any title carrying filter-evasion
(`A$$`, `stup*d`, or homoglyphs like `𝓝𝓱𝓪𝓲`) — both reference channels do that,
and unlike innuendo it is mechanically detectable. Those are rationed against a
budget measured off the reference channel: **3 of its last 10 uploads** sat in
that register. So `SLANG_BUDGET_MAX = 3` per `SLANG_BUDGET_WINDOW = 10`.

Two of those three were consecutive uploads, so this is a **rate cap and
deliberately not an adjacency rule** — forbidding back-to-back slang would
contradict what the channel actually does.

### Competitors, not results

A raw result set is not a competitor set. Searching "Jeffrey Epstein anime"
live returned a 3,515,737-view mainstream news video as its top hit, which
competes with nothing in this niche, and counting it made every news-derived
hook look `CROWDED`. A result now counts only when its title shares a content
word with the hook **and** one with the niche or topic:

```
"Could L Catch Epstein?"         epstein + l  -> competitor
"People have found Epstein..."   epstein      -> ignored
```

Short tokens are kept deliberately. This niche is full of one and two letter
names (L, Near, Kira), and tokenising on word boundaries already makes that
safe: "helicopter" yields one token, never a stray "l".

### Nothing is global that a second niche can break

Three separate thresholds have now been caught being measured on one niche and
applied to all of them. Each is per-format:

| Trait | Measured from | Where it lives |
|---|---|---|
| Title length | 31c/6w anime vs 44c/7w ThePaintProf | `title_format.max_chars` |
| Art style | flatness 0.548 vs 0.787 | `thumbnail_checklist.art_style` |
| Cell density | 1-2 subjects vs 8-12 captioned cells | `thumbnail_checklist.grid_rate` |
| Second person | rate 0.10 explainer vs 0.80 immersive | `title_format.second_person_rate` |

The fourth one is the cautionary tale, because the damage ran the other way.
`MIN_SECOND_PERSON_PER_100 = 4.0` came from "your life as" channels where the
viewer *is* the subject. Applied globally, it hit `bluntly-explained`, whose own
measured rate is **0.10** — an explainer. The gate did not merely misjudge the
script, it **forced the wrong one**: a brief about Kosmos 954, an *unmanned*
satellite, came back written as a crewed first-person death scene ("your ears
pop", "you check the oxygen gauge"), because that was the only way to clear a
floor the format never earned.

That is the *second* failure on this topic, and a different one from the
fabrication described under "What the gate cannot see" below. The 2026-09-11
brief invented a Venera 9 incident; once the fact check forced it onto the real
event, the 2026-09-18 brief got Kosmos 954 right and then narrated it as
fiction. Same pipeline, same topic, two independent defects.

A prompt demanding one register while the gate measures another pushes the model
into whichever the gate punishes. `_voice_rule()` and `_second_person_floor()`
in `formatengine/brief.py` are defined next to each other for exactly that
reason, so a change to one cannot silently drift from the other.

Art style is a **hard fail** in `verify-thumb`, not one score among many. The
worst video on ThePaintProf (4,848 views against a 60,704 median) is the one
thumbnail that abandoned the channel's house style.

### Templates are a depleting resource

Measured on ThePaintProf, two independent templates on one channel, in upload
order:

```
"Every ... Explained"       #1 6,182,111  ->  #14   33,846
"POV: You're About To ..."  #1 2,150,187  ->   #7    9,526
```

Both lost ~99% first use to last, and both were already down ~95% by the fifth.
`package` warns from use #5 and gets blunt at #10. It **warns rather than
blocks**: template fatigue, spending your best topics first, and any
repetition penalty all produce this identical curve, and public data cannot
separate them. Open a new format with your strongest idea rather than saving it.

Full method, tables and knowledge gaps:
`Deliverables/anime-analysis-interest-factor-research-2026-09-04.md` in the vault.

## Why `brief` is slow, and why that is not a bug

Groq's free tier meters **output tokens per minute**, and the number is small.
Measured live on 2026-09-11:

```
429 ... on output tokens per minute (OTPM): Limit 1000, Requested 4500
```

It is checked against `max_tokens` **before** any tokens are generated, so a
generous reservation is refused outright even when the reply would have been
short. Three consequences, all of them baked into the config:

- No single call may reserve more than `TPM_SAFE_COMPLETION` (900).
- Scripts are generated in small chunks (`CHUNK_BEATS = 2`, roughly 300 words).
- Chunks are spaced `CHUNK_GAP_SECONDS` (65) apart, which **must** exceed 60,
  because the window is per MINUTE.

So a 3-beat brief takes two or three minutes, most of it deliberate waiting.
Run it in the background rather than watching it.

The shell (hook, substance, thumbnail text) gets its **own** call, before any
beats. When shell and beats shared a call, the model spent the whole 860-token
budget on beats and returned zero substance items every time, which the
differentiation gate correctly blocked as a reskin.

If you point this at a paid tier or a model with a higher ceiling, raise
`GROQ_OTPM_LIMIT` (env) and `TPM_SAFE_COMPLETION`, and the chunking will
naturally stop triggering.

## What the gate cannot see: `verify`

The differentiation gate measures **structure** — opener variety, second-person
rate, sentence length, substance *count*. On 2026-09-11 a brief passed every one
of those and was still unusable in two independent ways.

**It was fabricated.** All five substance items were confidently wrong, and every
one was marked `needs_check: false`:

```
brief:     "The Soviet Venera-9 spacecraft, launched in July 1975, broke apart
            in Earth orbit on September 15, 1978, releasing a radioactive plume"
Wikipedia: "Venera 9 ... a Soviet uncrewed space mission to Venus ... launched
            on June 8, 1975 ... the first spacecraft to orbit Venus"
```

The event it had half-remembered is Kosmos 954. A *count* of substance items
cannot see any of that; the gate happily scored 5 of 3.

**Its tone was wrong for the format.** The beats described injury and bodily
decay in sustained detail, in a channel whose other titles are "Every Type Of
Black Hole Explained". That is an advertiser-friendliness problem in a project
whose entire premise is not tripping monetisation policy.

```bash
python -m formatengine verify real-chernobyl-in-space-2026-09-11
```

```
FACT CHECK  5 claims, 3 unsupported
  [FAIL] The Soviet Venera-9 spacecraft, launched in July 1975, broke apart ...
          the article on 'Venera 9' does not mention 1978
          and it was marked needs_check: false

GORE CHECK  5 markers across 2 beats (policy heuristic, not measured)
```

### Retrieve first, then write

Checking facts the model invented is the wrong order, and three regenerations on
one topic made that unarguable. Each produced confident, specific, wrong claims:

| Attempt | What it claimed | Reality |
|---|---|---|
| 09-11 | Venera 9 broke apart in Earth orbit in 1978 | a Venus mission; the event was Kosmos 954 |
| 09-23a | the Rogers Commission reported on Columbia | Rogers investigated *Challenger* |
| 09-23b | Kosmos 954 was an anti-satellite RTG platform | radar ocean recon, uranium-235 reactor |

The last one had **every date correct**. Fabrication was not an accident to be
caught afterwards; it was the default behaviour of asking a small model for
specifics it does not hold.

So the substance call is now **grounded**: `source_text()` resolves the topic or
external hook to a Wikipedia article, and the shell prompt hands the model that
passage with an instruction to take names, dates and numbers *from it* rather
than from memory. The fact check becomes a regression test instead of the only
defence. When nothing resolves, generation falls back to ungrounded and the
prompt tells the model to keep claims general and set `needs_check`.

### Repeated facts, and why text similarity misses them

Chunked generation shows each call only the **previous beat's tail**, so a later
chunk happily re-tells what an earlier one covered. One brief gave Operation
Morning Light and the twelve recovered pieces in two separate beats, and the
Canadian invoice in two more.

Whole-beat text similarity cannot see this. Measured across every beat pair:

```
repetitive brief   max pairwise similarity 0.16
known-good brief   max pairwise similarity 0.12
```

No separation, because the repetition is of specific *facts* inside otherwise
different prose. Counting the facts themselves separates cleanly:

| Brief | Repeated facts |
|---|---|
| the repetitive one | **7** |
| blackout (8 beats) | 0 |
| solar storms (4 beats) | 0 |
| asteroid (8 beats) | 0 |

`check_repetition()` counts numbers and multi-word proper names appearing in two
or more beats, **excluding the subject and the external hook** — a video about
Kosmos 954 says "Kosmos 954" in every beat and that is correct. The continuation
prompt now also receives the facts already spent, so the model is told what not
to re-tell rather than only punished for it afterwards.

### The check itself

The fact check proves only **absence**: that a number in the claim does not
appear in the encyclopedia article about the thing the claim is about. It is not
a truth oracle, but that is the exact smell a fabricated specific gives off.

Years alone were not enough, because a fabricated *category* keeps its dates
straight. So the check also reports **technical terms absent from the article**,
and that is what surfaced the last row in the table above:

```
[??] Kosmos 954 was an anti-satellite test platform powered by a radioisotope...
     terms absent from 'Kosmos 954': generator, platform, plutonium-238,
     radioisotope, rtg, thermoelectric (may be paraphrase - eyeball it)
```

Six technical terms the article never uses. That warns rather than blocks, since
an article may legitimately paraphrase, and the wording says so.
Anchor choice matters and is scored, not guessed: ranking candidate subjects by
raw length once picked `September 15` over `Venera-9` and reported that the
September 15 article fails to mention 1978, which is true and useless.

The gore scan is offline and cheap, so **the gate runs it on every brief**
(`MAX_GORE_MARKERS`). The fact check is network-bound, so it lives in `verify`
and you run it deliberately before rendering.

Both failures are now also pushed back into the prompts: the script prompt bans
graphic bodily harm outright, and the shell prompt tells the model its claims
will be checked against Wikipedia and that `needs_check: true` is a free,
correct answer while a confident wrong date is the expensive one.

## The differentiation gate

The tutorials optimise a single variable: similarity to a proven video. *"The
better you are copying, the more views your video will get."*

On 2025-07-15 YouTube renamed its repetitious-content monetization policy to
**inauthentic content**, aimed at uploads that look "made with a template with
little to no variation across videos." In January 2026 it terminated 16
channels holding roughly 35 million subscribers under it. Enforcement is
channel-wide: one templated run can strip monetization from everything.

So the variable is split in two:

- **Packaging: copy hard.** Title structure, thumbnail composition, pacing.
  This is what the algorithm reads and it is not what the policy is about.
- **Substance: must differ.** Every brief carries original, checkable research
  the source format does not have.

`brief` blocks on three checks:

| Check | Catches |
|---|---|
| `title_vs_source` ≤ 0.72 | You cloned the title instead of bending the topic |
| `self_similarity_peak` ≤ 0.80 | **Your own** last 8 uploads are converging into a template |
| `substance_items` ≥ 3 | The video is a reskin with nothing new in it |

The second is the one nobody warns you about. The failure mode isn't cloning
someone else once: it's your own channel flattening into a pattern over a
month of uploads. It is checked against a persistent ledger of what you have
shipped, so it works across sessions.

## Handing off to production

`brief` emits beats with narration and per-beat visual prompts. The vault
already has the free render half:

- **Voice**: `edge-tts`, free neural TTS (see `Code/voicezero`)
- **Assembly**: ffmpeg (see `Code/philosopher-pipeline`, `Code/football-shorts-autopilot`)
- **Thumbnails**: generate, then `verify-thumb` against the measured format

Nothing here re-implements a renderer that already exists.

## Layout

```
formatengine/
  config.py      thresholds, quota costs, RPM bands, safety lists
  yt.py          quota-aware API client: disk cache, ledger, retries, whitelist
  outlier.py     outlier maths, momentum, RPM band, safety flags, format score
  packaging.py   title slot parsing (Groq) + thumbnail deconstruction (OpenCV)
  discover.py    checkpointed breakout discovery
  bend.py        bend generation + demand/competition measurement
  brief.py       brief generation + the differentiation gate
  store.py       format library, checkpoints, shipped-brief ledger
  cli.py         command line
data/
  formats/       saved format specs (the library that accrues value)
  briefs/        generated briefs, .json + .md
  cache/         raw API responses: reruns cost zero quota
  ledger.json    quota spend + shipped history
```

Discovery checkpoints after every channel, so a kill or a 403 resumes without
re-spending quota.

## Honest limits

- **RPM is an estimate band, not a measurement.** Only your own Analytics knows
  your real RPM.
- **Demand is a proxy.** Median views of top results, not YouTube's internal
  search volume, which no public API exposes.
- **The format spec is only as coherent as the source channel.** A channel
  running two sub-formats yields a muddled template; check the mined template
  before building on it.
- **Nothing here makes a bad video good.** It tells you which format is
  working, where it can go, and whether you are about to build something
  YouTube will demonetise. The video still has to be worth watching.
