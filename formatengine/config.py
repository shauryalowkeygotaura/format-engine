"""Central config for format-engine.

Everything here is tunable without touching logic. Secrets live in Doppler,
never in this file (project `youtube-title-autoresearch`, config `dev`).

Run everything as:
    doppler run -p youtube-title-autoresearch -c dev -- python -m formatengine <cmd>
"""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
CACHE = DATA / "cache"          # raw API responses, keyed by request hash
THUMBS = DATA / "thumbs"        # downloaded thumbnails for CV
FORMATS = DATA / "formats"      # deconstructed format specs (the library)
BRIEFS = DATA / "briefs"        # production briefs ready for the render stack
PACKAGES = DATA / "packages"    # approved title+thumbnail, decided BEFORE script
LEDGER = DATA / "ledger.json"   # quota ledger + shipped-brief history

for _d in (DATA, CACHE, THUMBS, FORMATS, BRIEFS, PACKAGES):
    _d.mkdir(parents=True, exist_ok=True)

# ── YouTube Data API v3 quota ────────────────────────────────────────────────
# Free tier is 10,000 units/day per project. Costs are fixed by Google:
#   search.list        = 100 units  (expensive - use sparingly)
#   videos.list        = 1 unit     (up to 50 ids per call)
#   channels.list      = 1 unit     (up to 50 ids per call)
#   playlistItems.list = 1 unit     (up to 50 items per call)
# The whole point of this engine is to lean on the 1-unit calls so a full day
# of research costs a fraction of what a naive search-everything crawler burns.
QUOTA_COSTS = {"search": 100, "videos": 1, "channels": 1, "playlistItems": 1}
DAILY_QUOTA = int(os.environ.get("YT_DAILY_QUOTA", "10000"))
QUOTA_RESERVE = 500          # keep this much in the tank for interactive calls

# ── Outlier detection thresholds ─────────────────────────────────────────────
# A video is an "outlier" when it beats its own channel's typical performance.
# Two independent lenses, because each catches a case the other misses:
#   view_multiple    - total views vs channel median. Catches the classic
#                      "one video did 1M, everything else did 900".
#   velocity_multiple- views/day vs channel median views/day. Catches the
#                      3-day-old video that is exploding but hasn't
#                      accumulated a big total yet. This is the early signal.
MIN_VIEW_MULTIPLE = 3.0
MIN_VELOCITY_MULTIPLE = 3.0
MIN_OUTLIER_VIEWS = 50_000       # ignore small-sample noise
MIN_CHANNEL_VIDEOS = 3           # need a baseline to be an outlier *against*

# A channel is a "breakout" when it is young AND already landing big numbers.
BREAKOUT_MAX_CHANNEL_AGE_DAYS = 120
BREAKOUT_MIN_TOP_VIEWS = 200_000

# Discovery filters (mirrors the manual TubeGen niche-finder settings).
DISCOVERY_MIN_AVG_VIEWS = 5_000
DISCOVERY_WINDOW_DAYS = 90
DISCOVERY_LANG = "en"

# ── RPM estimate bands (USD per 1,000 monetised views) ───────────────────────
# There is no public API for another channel's RPM. Anyone quoting you an exact
# number for someone else's channel is guessing. These are published-range
# bands by category, reported as a RANGE and clearly labelled an estimate.
# Sources: creator-reported RPM surveys + YouTube category advertiser demand.
RPM_BANDS = {
    "finance": (12.0, 30.0),
    "business": (10.0, 24.0),
    "technology": (6.0, 18.0),
    "education": (5.0, 14.0),
    "health": (6.0, 15.0),
    "automotive": (5.0, 12.0),
    "travel": (4.0, 10.0),
    "food": (3.0, 9.0),
    "history": (4.0, 10.0),
    "science": (4.0, 11.0),
    "pets": (2.5, 7.0),
    "sports": (2.5, 7.0),
    "entertainment": (2.0, 6.0),
    "music": (1.5, 4.0),
    "gaming": (1.5, 5.0),
    "kids": (0.5, 2.0),
    "unknown": (2.0, 8.0),
}

# YouTube `topicCategories` are Wikipedia URLs. Map the slug to an RPM band.
TOPIC_TO_BAND = {
    "Business": "business", "Finance": "finance", "Economics": "finance",
    "Technology": "technology", "Knowledge": "education", "Education": "education",
    "Health": "health", "Medicine": "health", "Physical_fitness": "health",
    "Vehicle": "automotive", "Tourism": "travel", "Food": "food",
    "History": "history", "Science": "science", "Pet": "pets",
    "Sport": "sports", "Association_football": "sports", "Basketball": "sports",
    "Entertainment": "entertainment", "Film": "entertainment",
    "Television_program": "entertainment", "Music": "music",
    "Video_game_culture": "gaming", "Action_game": "gaming",
    "Role-playing_video_game": "gaming", "Lifestyle_(sociology)": "entertainment",
    "Society": "education", "Politics": "education", "Military": "history",
}

# categoryId fallback when topicCategories is absent.
CATEGORY_ID_TO_BAND = {
    "1": "entertainment", "2": "automotive", "10": "music", "15": "pets",
    "17": "sports", "19": "travel", "20": "gaming", "22": "entertainment",
    "23": "entertainment", "24": "entertainment", "25": "education",
    "26": "education", "27": "education", "28": "science",
}

# ── Niche safety filter ──────────────────────────────────────────────────────
# The source videos say "avoid anything that can get you banned" but never give
# a list. This is that list, applied automatically at discovery time.
BLOCKED_TOPIC_SUBSTRINGS = [
    "politic", "election", "war crime", "gore", "nsfw", "onlyfans", "nude",
    "porn", "gambling", "betting", "casino", "crypto pump", "get rich quick",
    "conspiracy", "vaccine hoax", "self harm", "suicide",
]
# Kids content is legal but caps RPM around $1 and forces COPPA restrictions.
KIDS_TOPIC_SUBSTRINGS = ["nursery rhyme", "for kids", "toddler", "baby shark", "cocomelon"]

# ── Groq (free tier) ─────────────────────────────────────────────────────────
GROQ_MODEL = os.environ.get("GROQ_MODEL", "qwen/qwen3.8-27b")
GROQ_MODEL_FAST = os.environ.get("GROQ_MODEL_FAST", "llama-3.1-8b-instant")
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

# ── Differentiation gate ─────────────────────────────────────────────────────
# YouTube's "inauthentic content" monetization policy (renamed from
# "repetitious content" on 2025-07-15) targets uploads that look templated with
# little variation. In Jan 2026 YouTube terminated 16 channels totalling ~35M
# subs under it. The source videos teach maximum-similarity cloning and never
# mention this. So: match the format's PACKAGING hard, and force the SUBSTANCE
# to differ. These are the thresholds that gate a brief.
MAX_TITLE_SIMILARITY_TO_SOURCE = 0.72   # above this you are cloning the title
MAX_SELF_SIMILARITY_ROLLING = 0.80      # your own last N briefs vs each other
SELF_SIMILARITY_WINDOW = 8
MIN_SUBSTANCE_ITEMS = 3                 # original facts/angles required per brief

# Narration voice floors, measured from nine working channels in the levels-of
# and your-life-as formats (431K-4.1M views). Their medians: 6.1 second-person
# uses per 100 words, 8-word sentences. Ours scored 0.0 and 13, which is the
# mechanical definition of the "encyclopedia recitation" complaint.
# Graphic bodily-harm markers tolerated in one script. A brief on 2026-09-11
# passed every structural check while describing injury and bodily decay in
# sustained clinical detail across all four beats, in a space-explainer format.
# Structure cannot see tone. Some peril language is fine and these formats trade
# on stakes, so this is not zero; saturation is what signals the script has
# drifted into horror. Policy heuristic aimed at YouTube advertiser-friendliness,
# not a measurement, and labelled as such wherever it surfaces.
MAX_GORE_MARKERS = 4

MIN_SECOND_PERSON_PER_100 = 4.0
MAX_MEDIAN_SENTENCE_WORDS = 12

# ── External hook thresholds ─────────────────────────────────────────────────
# Measured 2026-09-04 over 80 videos on two channels sharing a niche, title
# templates and runtime (NuchaReviews vs AventSir). Packaging that composites a
# real-world artifact beside the in-universe subject ran 2.7x-5x on views/day at
# matched age, and it replicated on the second channel. Method and tables:
#   Deliverables/anime-analysis-interest-factor-research-2026-09-04.md
#
# The floor is RECOGNITION, not recency. en.wikipedia 90d median pageviews,
# 2026-06-01..2026-09-03:
#   worked as hooks: 9/11 12,677 · Epstein 11,006 · Spider-Man 8,916 ·
#                    Carl Jung 3,395 · CIA 2,822
#   in-universe:     Death Note 2,235 · COTE 995 · Light novel 664 ·
#                    L 535 · Light Yagami 477 · Re:Zero 93
# Clean separation between 2,235 and 2,822. 2,500 splits it. This is a measured
# boundary from n=11 terms, not a tuned one; revisit it as cases accumulate.
HOOK_RECOGNITION_FLOOR = 2_500

# Recency is deliberately NOT a threshold. The best video in the sample shipped
# 151 days after its hook peaked, at 1% of peak attention and 0.72x the article's
# own median, and did 5.6x channel median. A freshness gate would have blocked
# it. freshness.attention_shape() reports the curve; nothing enforces it.

# A hook is CROWDED when a single existing video already owns it at this scale.
# Anchor: "Could L Catch Epstein?" measured 3,251,712 views, against Nucha's own
# 444,864 on the same hook. Provisional - one observation, no losing case yet.
HOOK_SATURATION_TOP_VIEWS = 1_000_000

# Title shape. These are DEFAULTS and every format spec may override them via
# spec["title_format"]["max_chars"] / ["max_words"]; see package._title_caps().
#
# Measured on the anime-analysis niche (n=80): median 31 chars / 6 words,
# p10 24, p90 40. The cap is p90, NOT the median - the median is where titles
# cluster, and treating it as a limit would be the invented-spec error this
# project has already made once.
#
# It nearly happened again. ThePaintProf (n=34, different niche) runs a median
# of 44 chars / 7 words, and its best video ever - "Every Real-Life Glitch
# Explained in 11 Minutes", 6,182,111 views - is 45 characters. A global 40-char
# cap would have blocked it. Title length is a property of the FORMAT, not of
# YouTube, so the per-format override exists and should be used.
MAX_TITLE_CHARS = 40
MAX_TITLE_WORDS = 8

# ── The slang track ──────────────────────────────────────────────────────────
# Some hooks have no encyclopedia footprint at all. The highest views/day video
# in the reference sample (12,952) was built on one. YouTube's own result set is
# the second instrument. Measured 2026-09-05, 12 results requested per term:
#   goonpocalypse     n=12  top 1,942,421     skibidi  n=12  top 150,681,962
#   gooning           n=11  top 4,684,859     "zravnik qplorth" (nonsense)  n=0
# A term nobody uses returns literally nothing, so a full result set plus one
# high-view proof separates live slang from a dead phrase.
SLANG_MIN_RESULTS = 8
SLANG_MIN_TOP_VIEWS = 100_000

# Scoreable is not the same as advisable. Slang works and should stay rare.
# Measured off the reference channel's last 10 uploads: 3 sat in the crude/slang
# register (goonpocalypse, "Did Light Crack Misa?", "Did L & Light Shower
# Together?"), the other 7 did not. Two of the three were consecutive uploads,
# so this is a RATE cap and deliberately not an adjacency rule - forbidding
# back-to-back slang would contradict what the channel actually does.
SLANG_BUDGET_WINDOW = 10        # uploads to look back over
SLANG_BUDGET_MAX = 3            # slang-register packages allowed in that window

# The crude register is not only carried by the hook. Both reference channels
# mark it in the TITLE with filter-evasion: homoglyph substitution (Nucha's
# "𝓝𝓱*𝓷𝓽𝓪𝓲") and symbol-censoring (Avent's "A$$ PULL!", Nucha's "stup*d foid").
# Those are mechanically detectable, unlike innuendo, so they are what counts
# here. Detecting innuendo would need an invented lexicon, which is the exact
# error this project has already made once.
SLANG_EVASION_CHARS = "$*@#"    # censoring marks inside an otherwise-normal word

# ── Template decay ───────────────────────────────────────────────────────────
# A template is a depleting resource. Measured on ThePaintProf 2026-09-10, two
# independent templates on one channel, each traced in upload order:
#   "Every ... Explained"      #1 6,182,111 -> #14    33,846
#   "POV: You're About To ..." #1 2,150,187 -> #7      9,526
# Both lost ~99% from first use to last, and both were already down ~95% by the
# fifth use. The first use of a template is worth 10-100x the tenth.
#
# This WARNS, it does not block. Three mechanisms produce the same curve -
# template fatigue, spending the best topics first, and any algorithmic
# penalty for repetition - and public data cannot separate them. Blocking on a
# curve whose cause is unknown is how the invented-spec failure happens.
TEMPLATE_DECAY_WARN_AT = 5      # nth use of a template where the warning starts
TEMPLATE_DECAY_LOUD_AT = 10     # nth use where the warning gets blunt

# Groq free tier is 8000 tokens per MINUTE and counts prompt + reserved
# completion together, so one call cannot cover a 2500-word script (which alone
# reserves ~9000). Beats are generated in paced chunks instead.
# Observed: a 1200-word script (budget 5100) generates fine in ONE call, while
# 2500 words was refused with 'Requested 8393, Limit 8000'. 5200 keeps the
# known-working case single-call and sends only genuinely oversized scripts
# down the slower chunked path.
# CORRECTED 2026-09-11 after a live 429. The binding limit is not the 8000
# tokens-per-minute figure this was built around, it is OUTPUT tokens per
# minute, and it is far smaller:
#   groq HTTP 429: ... on output tokens per minute (OTPM): Limit 1000,
#   Requested 4500. reduce max_tokens
# So no single call may reserve more than ~1000 output tokens, and the old 5200
# was five times over. Everything now goes down the chunked path, in small
# pieces spaced far enough apart for the per-minute window to roll over.
GROQ_OTPM_LIMIT = int(os.environ.get("GROQ_OTPM_LIMIT", "1000"))
TPM_SAFE_COMPLETION = 900       # max_tokens any single call may reserve
CHUNK_BEATS = 2                 # beats per continuation call (~300 words)
CHUNK_GAP_SECONDS = 65          # > 60, so the per-MINUTE window actually resets
