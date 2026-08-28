"""Breakout discovery: find channels whose format is working right now.

Replaces the paid niche-finder. The quota trick that makes it free:

    A search costs 100 units. Profiling a channel through
    channels.list + playlistItems.list + videos.list costs 3.

So discovery spends a handful of searches to get a candidate set, then does all
the actual work on the 1-unit endpoints. One search (100u) that surfaces 25
channels, each profiled for 3u, is 175u for 25 fully-scored channels. Doing the
same thing with per-channel searches would cost 2,600u and you would be done
for the day after three seeds.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from . import config, store
from .outlier import format_score, profile
from .yt import QuotaExhausted, YouTube, views_of

# Format phrases that are already proven at scale on faceless channels. These
# are entry points, not the answer - the point is to find who is currently
# winning WITH them, then bend away from that.
DEFAULT_SEEDS = [
    "seven levels of",
    "your life as",
    "explained in",
    "you have never heard of",
    "ranked from worst to best",
    "what if you",
    "the untold story of",
    "how to actually",
    "why nobody talks about",
    "every type of explained",
]


def _published_after(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")


def collect_candidates(yt: YouTube, seeds: list[str], *, window_days: int,
                       per_seed: int = 25, max_searches: int = 6) -> dict[str, dict]:
    """Spend a bounded number of searches, return candidate channels."""
    after = _published_after(window_days)
    candidates: dict[str, dict] = {}
    used = 0
    for seed in seeds:
        if used >= max_searches:
            break
        try:
            items = yt.search(seed, published_after=after, order="viewCount",
                              max_results=per_seed, duration="medium")
        except QuotaExhausted:
            print(f"  [quota] stopping seed sweep after {used} searches")
            break
        used += 1
        for it in items:
            sn = it.get("snippet", {})
            cid = sn.get("channelId")
            vid = (it.get("id") or {}).get("videoId")
            if not cid or not vid:
                continue
            entry = candidates.setdefault(cid, {
                "channel_id": cid,
                "channel_title": sn.get("channelTitle", ""),
                "seeds": [],
                "video_ids": [],
            })
            if seed not in entry["seeds"]:
                entry["seeds"].append(seed)
            entry["video_ids"].append(vid)
        print(f"  seed {used}/{max_searches}: {seed!r} -> {len(items)} results, "
              f"{len(candidates)} channels so far")
    return candidates


def rank_candidates(yt: YouTube, candidates: dict[str, dict], top_n: int) -> list[str]:
    """Cheap pre-rank so the 3u profiles are spent on the best prospects.

    One videos.list call covers 50 ids for 1 unit, so pre-ranking the entire
    candidate pool by the views of the video that surfaced it costs ~2 units.
    """
    all_ids = [vid for c in candidates.values() for vid in c["video_ids"][:2]]
    seen, ids = set(), []
    for v in all_ids:
        if v not in seen:
            seen.add(v)
            ids.append(v)
    best: dict[str, int] = {}
    for v in yt.videos(ids):
        cid = v.get("snippet", {}).get("channelId", "")
        best[cid] = max(best.get(cid, 0), views_of(v))
    return [cid for cid, _ in sorted(best.items(), key=lambda kv: -kv[1])][:top_n]


def discover(yt: YouTube, *, seeds: list[str] | None = None, window_days: int | None = None,
             top_n: int = 20, max_searches: int = 6, sample: int = 30,
             run: str = "discover", resume: bool = True) -> list[dict]:
    """End-to-end discovery. Checkpointed: a kill resumes without re-spending."""
    seeds = seeds or DEFAULT_SEEDS
    window_days = window_days or config.DISCOVERY_WINDOW_DAYS

    ckpt = store.load_checkpoint(run) if resume else {"done": [], "results": []}
    done = set(ckpt.get("done", []))
    results = list(ckpt.get("results", []))
    if done:
        print(f"  [resume] {len(done)} channels already profiled, skipping them")

    if not ckpt.get("candidate_order"):
        print(f"→ seeding ({len(seeds)} phrases, max {max_searches} searches)")
        candidates = collect_candidates(yt, seeds, window_days=window_days,
                                        max_searches=max_searches)
        if not candidates:
            return results
        print(f"→ pre-ranking {len(candidates)} candidate channels (~2 units)")
        order = rank_candidates(yt, candidates, top_n)
        ckpt["candidate_order"] = order
        ckpt["candidate_meta"] = {c: candidates[c] for c in order if c in candidates}
        store.save_checkpoint(run, ckpt)
    order = ckpt["candidate_order"]
    meta = ckpt.get("candidate_meta", {})

    print(f"→ profiling {len(order)} channels at ~3 units each")
    for i, cid in enumerate(order, 1):
        if cid in done:
            continue
        try:
            chans = yt.channels([cid])
            if not chans:
                done.add(cid)
                continue
            vids = yt.channel_uploads(cid, limit=sample)
        except QuotaExhausted as e:
            print(f"  [quota] halting at {i}/{len(order)}: {e}")
            break
        if not vids:
            done.add(cid)
            continue

        prof = profile(chans[0], vids)
        prof["score"] = format_score(prof)
        prof["seeds"] = meta.get(cid, {}).get("seeds", [])
        prof["url"] = f"https://www.youtube.com/channel/{cid}"
        results.append(prof)
        done.add(cid)

        ckpt["done"] = sorted(done)
        ckpt["results"] = results
        store.save_checkpoint(run, ckpt)

        flag = " BREAKOUT" if prof["is_breakout"] else ""
        warn = "  !" + ",".join(prof["safety_flags"]) if prof["safety_flags"] else ""
        print(f"  [{i}/{len(order)}] {prof['title'][:38]:38} "
              f"score={prof['score']:5.1f} subs={prof['subscribers']:>9,} "
              f"outliers={len(prof['outliers'])}{flag}{warn}")

    results.sort(key=lambda p: -p["score"])
    return results


def summarize(results: list[dict], limit: int = 15) -> str:
    if not results:
        return "No channels profiled."
    lines = [
        f"{'#':<3} {'SCORE':>5} {'CHANNEL':<32} {'SUBS':>9} {'TOP VIEWS':>11} "
        f"{'AGE(d)':>7} {'RPM$':>9} {'OUT':>4} MOM",
        "-" * 104,
    ]
    for i, p in enumerate(results[:limit], 1):
        rpm = p["rpm_estimate_usd"]
        lines.append(
            f"{i:<3} {p['score']:>5.1f} {p['title'][:32]:<32} {p['subscribers']:>9,} "
            f"{p['top_video_views']:>11,} {p['channel_age_days']:>7.0f} "
            f"{rpm['low']:>4.0f}-{rpm['high']:<4.0f} {len(p['outliers']):>4} "
            f"{p['momentum']:+.3f}"
            + ("  BREAKOUT" if p["is_breakout"] else "")
            + ("  !" + ",".join(p["safety_flags"]) if p["safety_flags"] else "")
        )
    return "\n".join(lines)
