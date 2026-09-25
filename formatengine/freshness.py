"""Scoring an external hook before a title is committed.

An "external hook" is the thing in the packaging that does not come from the
source material: Epstein's photograph next to the CIA seal on a Death Note
thumbnail, Carl Jung with a Masonic compass, a red 9/11 skyline behind a
schoolgirl. Measured 2026-09-04 across 80 videos on two channels in the same
niche with identical title templates and runtimes, the presence of one is worth
2.7x-5x on views/day at matched age. It replicated on the second channel. Full
method and tables in the vault:

    Deliverables/anime-analysis-interest-factor-research-2026-09-04.md
    Research/YouTube/interest-factor-2026-09-04/

This module decides whether a candidate hook is worth building packaging around.

WHAT THIS IS NOT
----------------
It is not a trend-chasing check, and the distinction is the whole reason this
module exists. The obvious design is "is this hook spiking right now", and that
design is wrong. It was tested against the one case with a known outcome:

    Jeffrey Epstein, en.wikipedia daily pageviews
      attention peak      2026-02-05 at 1,072,415 views/day
      Nucha ships         2026-07-06, 151 days later
      pageviews that day  10,786  =  1% of peak, and 0.72x the 215-day median
      result              444,864 views, 7,414 views/day, 5.6x channel median

The best video on that channel shipped 151 days after its hook stopped
trending, at one percent of peak attention. A freshness gate would have blocked
it. So recency is measured and REPORTED here, never enforced.

WHAT ACTUALLY SEPARATES A HOOK
------------------------------
Recognition mass, not recency. Measured 90-day median daily pageviews,
2026-06-01 to 2026-09-03:

    worked as external hooks          in-universe subjects (the baseline)
      September 11 attacks  12,677      Death Note              2,235
      Jeffrey Epstein       11,006      Classroom of the Elite    995
      Spider-Man             8,916      Light novel               664
      Carl Jung              3,395      L (Death Note)            535
      CIA                    2,822      Light Yagami              477
                                        Re:Zero                    93

Every hook that worked sits above ~2,800. Every in-universe subject sits at or
below 2,235. The hook does not need to be in the news. It needs to be something
the audience already recognises without being told, so the thumbnail can put it
beside the anime and let the collision do the work.

THE SLANG TRACK
---------------
Nucha's single best video by views/day (12,952, "How 𝓝𝓱*𝓷𝓽𝓪𝓲 Survived the
Goonpocalypse") is built on a term with NO Wikipedia article at all. Pageviews
cannot see it, so a second instrument scores it instead: YouTube's own result
set. Measured 2026-09-05, twelve results requested per term:

    goonpocalypse      n=12   median    5,215   max  1,942,421
    skibidi            n=12   median 6,437,502  max 150,681,962
    gooning            n=11   median  418,600   max  4,684,859
    "zravnik qplorth"  n=0    (nonsense control)

A term nobody uses returns literally nothing, so presence of a full result set
plus one high-view proof is a real recognition signal, not a guess. Slang hooks
are therefore SCORED, not shrugged at.

Being scoreable is not the same as being advisable. A hook that only clears the
YouTube track is marked `register="slang"`, and package.gate() rations those
against a budget measured off the reference channel: 3 of its last 10 uploads
sat in that register. Slang works and should stay rare, which is what the
channel actually does rather than what a style rule asserts.
"""
from __future__ import annotations

import json
import re
import statistics
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone

from . import config

# Wikimedia asks for a descriptive UA and rate-limits the default urllib one.
_UA = {"User-Agent": "format-engine/1.0 (vault research; contact via github.com/shauryalowkeygotaura)"}
# Longest Retry-After we will honour. Wikipedia asked for 21s on 2026-09-25.
_MAX_RETRY_AFTER = 30

# Whitelist, not character-removal. An LLM writes these hook strings and they
# are interpolated into URLs and into a yt-dlp search argument.
_HOOK_ALLOWED = re.compile(r"[^A-Za-z0-9 '\-.&:]+")


class FreshnessError(RuntimeError):
    pass


def sanitize_hook(term: str) -> str:
    """Whitelist-only hook string. Never trust an LLM-generated term.

    Leading '-' and '.' are stripped as well as filtered. subprocess is called
    with an argv list so no shell ever sees this, but a term beginning with a
    dash would still be parsed by yt-dlp as an OPTION rather than a query.
    """
    cleaned = _HOOK_ALLOWED.sub(" ", term or "")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    cleaned = cleaned.lstrip("-.").strip()
    if not cleaned:
        raise ValueError(f"hook reduced to empty after whitelist: {term!r}")
    return cleaned[:80]


def _get_json(url: str, *, timeout: int = 25) -> dict | None:
    """GET and parse, or None. Status is checked before the body is touched.

    A 429 is waited out once, for as long as the server's Retry-After asks
    (capped). Without this, Wikipedia throttling after a claim-check loop came
    back as None, which callers read as "no article exists" - and the narration
    check then reported nothing to compare against rather than a rate limit.
    """
    req = urllib.request.Request(url, headers=_UA)
    for attempt in range(2):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                if r.status != 200:
                    return None
                try:
                    return json.loads(r.read().decode("utf-8"))
                except (json.JSONDecodeError, UnicodeDecodeError):
                    return None
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt == 0:
                try:
                    wait = int(e.headers.get("Retry-After") or 5)
                except (TypeError, ValueError):
                    wait = 5
                time.sleep(min(max(wait, 1), _MAX_RETRY_AFTER))
                continue
            return None
        except (urllib.error.URLError, OSError, TimeoutError):
            return None
    return None


# ── Wikipedia: recognition and attention shape ───────────────────────────────
def resolve_article(term: str) -> str | None:
    """Map a loose hook phrase to a real article title, or None.

    "Pennywise clown" -> "Pennywise". Needed because the naive guess
    (`Pennywise_(character)`) resolves to a near-dead article at 4 views/day
    and would score a famous hook as unknown.
    """
    term = sanitize_hook(term)
    url = ("https://en.wikipedia.org/w/api.php?action=query&list=search"
           f"&srsearch={urllib.parse.quote(term)}&srlimit=1&format=json")
    d = _get_json(url)
    if not d:
        return None
    hits = (d.get("query") or {}).get("search") or []
    return hits[0]["title"] if hits else None


def pageview_series(article: str, *, days: int = 90) -> list[tuple[str, int]]:
    """Daily pageviews, oldest first. Empty list if the article has no data."""
    end = date.today() - timedelta(days=1)
    start = end - timedelta(days=days)
    art = urllib.parse.quote(article.replace(" ", "_"), safe="")
    url = ("https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article"
           f"/en.wikipedia/all-access/user/{art}/daily"
           f"/{start:%Y%m%d}/{end:%Y%m%d}")
    d = _get_json(url, timeout=30)
    if not d or "items" not in d:
        return []
    return [(x["timestamp"][:8], int(x["views"])) for x in d["items"]]


def attention_shape(series: list[tuple[str, int]]) -> dict:
    """Describe the attention curve. REPORTED, never used to block.

    See the module docstring: the best measured video shipped 151 days past
    peak at 1% of peak. These numbers are context for a human, not a gate.
    """
    if not series:
        return {"available": False}
    views = [v for _, v in series]
    peak_day, peak = max(series, key=lambda x: x[1])
    recent = views[-7:] or views
    prior = views[-37:-7] or views
    peak_dt = datetime.strptime(peak_day, "%Y%m%d").date()
    return {
        "available": True,
        "median": int(statistics.median(views)),
        "recent_7d_mean": int(statistics.mean(recent)),
        "prior_30d_mean": int(statistics.mean(prior)),
        "trend": round(statistics.mean(recent) / max(statistics.mean(prior), 1), 2),
        "peak": peak,
        "peak_day": peak_day,
        "peak_age_days": (date.today() - peak_dt).days,
        "pct_of_peak": round(statistics.mean(recent) / max(peak, 1), 4),
    }


def youtube_recognition(term: str, *, n: int = 12, timeout: int = 180) -> dict:
    """Second instrument, for terms the encyclopedia cannot see.

    A term nobody uses returns an empty result set: the nonsense control
    "zravnik qplorth" measured n=0, while goonpocalypse, skibidi and gooning all
    returned 11-12 results with a multi-hundred-thousand-view top result. So the
    test is a full result set AND one video proving an audience engages.
    """
    res = _youtube_search(term, n=n, timeout=timeout)
    if not res["ok"]:
        return {"scored": False, "reason": res["reason"], "term": term}
    rows = res["rows"]
    if not rows:
        return {"scored": False, "term": term,
                "reason": "YouTube returns no results at all for this term, which "
                          "is what a term nobody uses looks like"}
    views = sorted((r["view_count"] for r in rows), reverse=True)
    ok = len(rows) >= config.SLANG_MIN_RESULTS and views[0] >= config.SLANG_MIN_TOP_VIEWS
    return {"scored": bool(ok), "term": term, "n": len(rows),
            "top_views": views[0], "median_views": int(statistics.median(views)),
            "reason": None if ok else (
                f"only {len(rows)} results and a {views[0]:,}-view top result; "
                f"below the {config.SLANG_MIN_RESULTS}/{config.SLANG_MIN_TOP_VIEWS:,} "
                "floor that separates live slang from a dead term")}


def recognition(term: str) -> dict:
    """The load-bearing measurement: does the audience already know this?

    Two tracks. Wikipedia first, because a hook with an encyclopedia footprint
    is the `proper` register and carries no style cost. Terms it cannot see fall
    through to YouTube and are marked `slang`, which scores but is rationed.
    """
    article = resolve_article(term)
    if article:
        series = pageview_series(article)
        if series:
            shape = attention_shape(series)
            return {"scored": True, "source": "wikipedia", "register": "proper",
                    "term": term, "article": article,
                    "daily_median": shape["median"], "attention": shape}

    yt = youtube_recognition(term)
    if yt.get("scored"):
        return {"scored": True, "source": "youtube", "register": "slang",
                "term": term, "article": None,
                "youtube": {k: yt[k] for k in ("n", "top_views", "median_views")}}

    return {"scored": False, "source": None, "register": None, "term": term,
            "article": article,
            "reason": (f"no Wikipedia article resolves, and {yt.get('reason')}"
                       if not article else
                       f"article {article!r} has no pageview data, and "
                       f"{yt.get('reason')}")}


# ── YouTube: shared search ───────────────────────────────────────────────────
_STOPWORDS = {
    "the", "and", "for", "was", "are", "you", "your", "this", "that", "with",
    "from", "how", "why", "what", "who", "did", "can", "could", "not", "its",
    "but", "all", "has", "have", "his", "her", "them", "they", "than", "then",
    "really", "vs", "versus", "video", "full", "new", "best", "explained",
    # Short function words. These must be listed explicitly because short
    # tokens are NOT dropped by length; see _tokens().
    "a", "an", "i", "is", "it", "in", "of", "on", "or", "to", "be", "by",
    "do", "go", "he", "if", "me", "my", "no", "so", "up", "us", "we", "at",
    "as", "am", "re", "vs.",
}


def _tokens(text: str) -> set[str]:
    """Content words for loose title matching.

    Short tokens are KEPT. This niche is full of one and two letter character
    names - L, Near, Kira - and "Could L Catch Epstein?" is a genuine competitor
    that a 3-character minimum silently discarded. Tokenising on non-alphanumeric
    boundaries already makes this safe: "helicopter" yields one token, never a
    stray "l", so a short name only matches when it stands alone as a word.
    Common short function words are excluded via _STOPWORDS instead.
    """
    return {w for w in re.findall(r"[a-z0-9]+", (text or "").lower())
            if w not in _STOPWORDS}


def _youtube_search(query: str, *, n: int = 15, timeout: int = 180) -> dict:
    """Run one yt-dlp search. Zero YouTube Data API quota."""
    try:
        q = sanitize_hook(query)
    except ValueError as e:
        return {"ok": False, "reason": str(e), "query": None, "rows": []}
    try:
        p = subprocess.run(
            # "--" ends option parsing so the search term can never be read as
            # a flag, belt-and-braces with the lstrip in sanitize_hook.
            ["yt-dlp", "--flat-playlist", "--dump-json", "--ignore-errors",
             "--", f"ytsearch{int(n)}:{q}"],
            capture_output=True, text=True, timeout=timeout,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
        return {"ok": False, "reason": f"yt-dlp unavailable: {e}", "query": q, "rows": []}

    rows = []
    for line in p.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        if r.get("view_count") is not None:
            rows.append(r)

    # An empty result and a failed call look identical downstream, so separate
    # them here rather than reporting "nobody has covered this" after a 403.
    if not rows and p.returncode != 0:
        return {"ok": False, "query": q, "rows": [],
                "reason": f"search failed (rc={p.returncode}): "
                          f"{(p.stderr or '').strip()[:200]}"}
    return {"ok": True, "query": q, "rows": rows, "reason": None}


# ── YouTube: saturation ──────────────────────────────────────────────────────
def saturation(term: str, niche: str = "", *, topic: str = "", n: int = 15,
               timeout: int = 180) -> dict:
    """Has this hook already been taken, and by how big a video?

    Uses yt-dlp search, which costs zero YouTube Data API quota. The pairing
    that matters is hook AND niche: "Epstein" alone is a news query, "Epstein
    anime" is the actual landing zone.

    A raw result set is NOT a competitor set. Observed live 2026-09-05,
    "Jeffrey Epstein anime" returned a 3,515,737-view mainstream news video as
    its top hit, which competes with nothing in this niche. Counting it made
    every news-derived hook look CROWDED. So a result only counts as a
    competitor when its title shares a content word with the HOOK *and* one
    with the niche or topic:

        "Could L Catch Epstein?"        epstein + lawliet  -> competitor
        "People have found Epstein..."  epstein + nothing  -> ignored

    Both figures are returned: `top_views` is the competitor scale that drives
    the verdict, `raw_top_views` is the unfiltered number for eyeballing.
    """
    # Search on hook + whatever context exists. dict.fromkeys dedupes while
    # keeping order, so a caller passing the same string as both niche and
    # topic does not double it in the query.
    parts = list(dict.fromkeys(p for p in (term, niche, topic) if p and p.strip()))
    res = _youtube_search(" ".join(parts), n=n, timeout=timeout)
    if not res["ok"]:
        return {"checked": False, "reason": res["reason"], "query": res["query"]}

    rows, query = res["rows"], res["query"]
    if not rows:
        return {"checked": True, "query": query, "n": 0, "n_raw": 0,
                "median_views": 0, "top_views": 0, "top_title": None,
                "raw_top_views": 0}

    # The hook must match on a token the niche does NOT also supply. Observed
    # live 2026-09-10: hook "Chernobyl disaster" and topic "space disaster"
    # share "disaster", which alone satisfied both halves of the test, so a
    # video about the Columbia shuttle matched a Chernobyl hook without
    # containing "chernobyl" at all. Only distinctive hook tokens count.
    niche_tokens = _tokens(f"{niche} {topic}")
    hook_tokens = _tokens(term) - niche_tokens
    if not hook_tokens:                     # hook is entirely inside the niche
        hook_tokens = _tokens(term)
    def is_competitor(r):
        t = _tokens(r.get("title") or "")
        if not hook_tokens & t:
            return False
        # With no niche or topic given there is nothing to disambiguate
        # against, so fall back to hook-only matching rather than silently
        # returning zero competitors and reporting the field as open.
        return bool(niche_tokens & t) if niche_tokens else True

    raw_views = sorted((r["view_count"] for r in rows), reverse=True)
    comp = [r for r in rows if is_competitor(r)]
    if not comp:
        return {"checked": True, "query": query, "n": 0, "n_raw": len(rows),
                "median_views": 0, "top_views": 0, "top_title": None,
                "raw_top_views": int(raw_views[0]),
                "note": f"{len(rows)} results, none of them actually about this "
                        "hook in this niche"}

    views = sorted((r["view_count"] for r in comp), reverse=True)
    top = max(comp, key=lambda r: r["view_count"])
    return {"checked": True, "query": query, "n": len(comp), "n_raw": len(rows),
            "median_views": int(statistics.median(views)),
            "top_views": int(views[0]),
            "top_title": (top.get("title") or "")[:120],
            "raw_top_views": int(raw_views[0])}


# ── the verdict ──────────────────────────────────────────────────────────────
def score_hook(term: str, niche: str = "", *, topic: str = "",
               check_saturation: bool = True) -> dict:
    """Score one candidate external hook. Returns a verdict plus its evidence.

    Verdicts:
      GO       recognition clears the measured floor and nothing big owns it
      CROWDED  recognition is fine but a real competitor already holds this hook
      WEAK     recognition sits in in-universe territory; this is not a hook
      UNSCORED neither instrument can see the term. Genuinely unknown.

    Every scored hook also carries a `register`: "proper" when Wikipedia knows
    it, "slang" when only YouTube does. Both are shippable; the slang budget is
    enforced in package.gate(), not here, because it is a property of the
    upload schedule rather than of the hook.
    """
    try:
        term = sanitize_hook(term)
    except ValueError as e:
        return {"term": term, "niche": niche, "verdict": "INVALID",
                "recognition": {"scored": False, "reason": str(e)},
                "saturation": {"checked": False, "reason": "not attempted"},
                "notes": [f"Hook string is unusable: {e}"],
                "checked_at": datetime.now(timezone.utc).isoformat()}
    rec = recognition(term)
    sat = (saturation(term, niche, topic=topic) if check_saturation
           else {"checked": False, "reason": "skipped"})
    notes: list[str] = []

    if not rec["scored"]:
        verdict = "UNSCORED"
        notes.append(
            f"{rec.get('reason')}. Check the spelling before assuming the "
            "audience knows it.")
    elif rec["source"] == "youtube":
        yt = rec["youtube"]
        verdict = "GO"
        notes.append(
            f"SLANG register. No Wikipedia article, but YouTube returns "
            f"{yt['n']} results with a {yt['top_views']:,}-view top video, so the "
            "term is live. The nonsense control returned zero results, so this "
            "is a real signal. Slang is rationed by the budget in package.gate(), "
            "not blocked here.")
    else:
        daily = rec["daily_median"]
        if daily >= config.HOOK_RECOGNITION_FLOOR:
            verdict = "GO"
            notes.append(f"{daily:,}/day median recognition clears the "
                         f"{config.HOOK_RECOGNITION_FLOOR:,} floor.")
        else:
            verdict = "WEAK"
            notes.append(
                f"{daily:,}/day median sits below the {config.HOOK_RECOGNITION_FLOOR:,} "
                "floor, which is in-universe territory. In the reference sample "
                "every hook that worked measured 2,822-12,677/day and every "
                "in-universe subject measured 2,235/day or less. A hook the "
                "audience must be told about is not doing the work of a hook.")
        att = rec["attention"]
        notes.append(
            f"Attention peaked {att['peak_age_days']}d ago at {att['peak']:,}/day; "
            f"now at {att['pct_of_peak']:.1%} of peak, trend {att['trend']}x. "
            "Reported only. The reference winner shipped 151d past peak at 1% "
            "of peak, so age is not a reason to drop a hook.")

    if sat.get("checked") and sat.get("n"):
        if sat["top_views"] >= config.HOOK_SATURATION_TOP_VIEWS:
            if verdict == "GO":
                verdict = "CROWDED"
            notes.append(
                f"Already held: {sat['top_views']:,} views on "
                f"\"{sat['top_title']}\". Going head-to-head needs a genuinely "
                "different angle, not the same premise.")
        else:
            notes.append(f"Landing zone is open: biggest real competitor "
                         f"{sat['top_views']:,} views across {sat['n']} of "
                         f"{sat.get('n_raw', sat['n'])} results.")
    elif sat.get("checked") and sat.get("n") == 0 and sat.get("n_raw"):
        notes.append(
            f"Landing zone is open: {sat['n_raw']} results came back but none "
            "were about this hook in this niche "
            f"(biggest unrelated result {sat.get('raw_top_views', 0):,} views).")
    elif check_saturation and not sat.get("checked"):
        notes.append(f"Saturation UNKNOWN ({sat.get('reason','no reason given')}). "
                     "Verdict is based on recognition alone.")

    return {"term": term, "niche": niche, "topic": topic, "verdict": verdict,
            "register": rec.get("register"),
            "recognition": rec, "saturation": sat, "notes": notes,
            "checked_at": datetime.now(timezone.utc).isoformat()}


def summarize(score: dict) -> str:
    """Human-readable block for the CLI."""
    rec = score["recognition"]
    reg = score.get("register")
    out = [f"HOOK  {score['term']!r}   →  {score['verdict']}"
           + (f"  [{reg}]" if reg else "")]
    if rec.get("scored") and rec.get("source") == "wikipedia":
        att = rec["attention"]
        out.append(f"  article           {rec['article']}")
        out.append(f"  recognition       {rec['daily_median']:,}/day median "
                   f"(floor {config.HOOK_RECOGNITION_FLOOR:,})")
        out.append(f"  attention peak    {att['peak']:,}/day, {att['peak_age_days']}d ago "
                   f"- now {att['pct_of_peak']:.1%} of peak (reported, not gating)")
    elif rec.get("scored") and rec.get("source") == "youtube":
        yt = rec["youtube"]
        out.append(f"  recognition       YouTube only: {yt['n']} results, "
                   f"top {yt['top_views']:,} views (no Wikipedia article)")
    sat = score["saturation"]
    if sat.get("checked") and sat.get("n"):
        out.append(f"  competitors       top {sat['top_views']:,} views, "
                   f"{sat['n']} of {sat.get('n_raw', sat['n'])} results are real rivals")
        out.append(f"                    \"{sat['top_title']}\"")
    elif sat.get("checked") and sat.get("n_raw"):
        out.append(f"  competitors       none of {sat['n_raw']} results actually "
                   "compete on this hook in this niche")
    out.append("")
    out += [f"  · {n}" for n in score["notes"]]
    return "\n".join(out)
