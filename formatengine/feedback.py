"""Close the loop: read back how OUR uploads actually performed.

Every ranking in this project scores formats by how the SOURCE channel did.
That is a prior, not evidence. It says a format works for somebody else; it
cannot say it works for us. This module supplies the missing half.

Deliberately modest in scope, because the failure mode here is not a missing
algorithm - it is a loop that is built and never closed. philosopher-pipeline
has a well-designed epsilon-greedy bandit that has never left round-robin,
because no ledger row ever received a reward. So this does the smallest thing
that produces real reward rows:

  1. attach a video id to a shipped brief          (attach_video)
  2. later, pull public stats for those ids        (refresh)  - 1 quota unit / 50
  3. report per-format means WITH sample sizes     (format_performance)

Quota: videos.list is a 1-unit endpoint and yt.py caches by request hash, so a
refresh over 50 uploads costs a single unit. There is no reason to be shy about
running it, and every reason not to auto-invoke it on every command - see
`status()` for the "is this actually learning" check.
"""
from __future__ import annotations

import statistics
from datetime import datetime, timezone

from . import config, store, yt

# A video needs to have been public long enough for views to mean anything.
# Pulling stats an hour after upload measures nothing but the upload itself.
MIN_AGE_DAYS = 3.0


def attach_video(title: str, video_id: str) -> bool:
    """Record which uploaded video came from which shipped brief.

    Matched on title because that is what record_shipped already stores. Returns
    False rather than raising when nothing matches, so a publish step can call
    this without a try block.
    """
    if not yt.valid_id(video_id):
        return False
    ledger = store.read_json(config.LEDGER, default={}) or {}
    shipped = ledger.get("shipped") or []
    hit = None
    for row in reversed(shipped):          # newest first: titles can repeat
        if isinstance(row, dict) and row.get("title", "").strip() == title.strip():
            hit = row
            break
    if hit is None:
        return False
    hit["video_id"] = video_id
    store.write_json(config.LEDGER, ledger)
    return True


def refresh(client: "yt.YouTube | None" = None, limit: int = 50) -> dict:
    """Pull public stats for shipped briefs that have a video id.

    Skips rows that are too young to have meaningful numbers, and rows already
    refreshed today, so repeated runs are cheap and idempotent.
    """
    ledger = store.read_json(config.LEDGER, default={}) or {}
    shipped = ledger.get("shipped") or []
    today = datetime.now(timezone.utc).date().isoformat()

    want = []
    for row in shipped:
        if not isinstance(row, dict):
            continue
        vid = row.get("video_id")
        if not vid or not yt.valid_id(vid):
            continue
        if row.get("stats_at", "").startswith(today):
            continue
        try:
            if yt.age_days(row.get("at", "")) < MIN_AGE_DAYS:
                continue
        except Exception:
            pass
        want.append(row)
        if len(want) >= limit:
            break

    if not want:
        return {"checked": 0, "updated": 0, "note": "nothing eligible"}

    client = client or yt.YouTube()
    items = client.videos([r["video_id"] for r in want])
    by_id = {i.get("id"): i for i in items if isinstance(i, dict)}

    updated = 0
    for row in want:
        item = by_id.get(row["video_id"])
        if not item:
            continue
        st = item.get("statistics") or {}
        # int() on API strings, guarded: a missing count is absent, not zero.
        def _n(key):
            try:
                return int(st[key])
            except (KeyError, TypeError, ValueError):
                return None
        row["performance"] = {"views": _n("viewCount"),
                              "likes": _n("likeCount"),
                              "comments": _n("commentCount")}
        row["stats_at"] = datetime.now(timezone.utc).isoformat()
        updated += 1

    store.write_json(config.LEDGER, ledger)
    return {"checked": len(want), "updated": updated}


def format_performance(min_samples: int = 2) -> list[dict]:
    """Per-format view stats from OUR uploads, newest 200 shipped rows.

    Median, not mean: one video that happens to catch the algorithm would drag a
    mean far enough to make a bad format look good, which is the same reason
    outlier.py scores against a median baseline.

    Formats below `min_samples` are returned but flagged, never silently hidden.
    A single upload is an anecdote and should be visible as one.
    """
    ledger = store.read_json(config.LEDGER, default={}) or {}
    buckets: dict[str, list[int]] = {}
    for row in ledger.get("shipped") or []:
        if not isinstance(row, dict):
            continue
        views = ((row.get("performance") or {}).get("views"))
        # None means the API gave no viewCount (hidden counts, or a
        # deleted video). Skipping keeps it out of the median rather
        # than counting it as zero, which would understate the format.
        if not isinstance(views, int):
            continue
        buckets.setdefault(row.get("format_slug") or "(none)", []).append(views)

    out = []
    for slug, views in buckets.items():
        out.append({
            "format_slug": slug,
            "n": len(views),
            "median_views": int(statistics.median(views)),
            "best": max(views),
            "enough_data": len(views) >= min_samples,
        })
    return sorted(out, key=lambda r: (-r["median_views"], r["format_slug"]))


def status() -> dict:
    """Is this loop actually closed? The one check worth running.

    An open loop is worse than no loop because it looks finished. philosopher's
    bandit has run in round-robin since it was written, and nothing said so.
    """
    ledger = store.read_json(config.LEDGER, default={}) or {}
    shipped = [r for r in (ledger.get("shipped") or []) if isinstance(r, dict)]
    with_id = sum(1 for r in shipped if r.get("video_id"))
    with_perf = sum(1 for r in shipped if (r.get("performance") or {}).get("views") is not None)
    return {
        "shipped": len(shipped),
        "with_video_id": with_id,
        "with_performance": with_perf,
        "learning": with_perf >= 2,
        "verdict": ("closed" if with_perf >= 2 else
                    "OPEN - no reward data, rankings are still source-channel priors"),
    }
