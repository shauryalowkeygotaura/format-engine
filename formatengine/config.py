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
LEDGER = DATA / "ledger.json"   # quota ledger + shipped-brief history

for _d in (DATA, CACHE, THUMBS, FORMATS, BRIEFS):
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
MIN_SECOND_PERSON_PER_100 = 4.0
MAX_MEDIAN_SENTENCE_WORDS = 12
