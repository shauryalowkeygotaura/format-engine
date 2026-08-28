"""Outlier + momentum scoring.

This is the part the paid tools charge for, and the part the tutorials do by
eyeballing a screen ("not a single video outside this one got over 1,000
views"). It is arithmetic, and doing it properly beats eyeballing it.

Four things this does that a naive views/average ratio does not:

1. **Median, not mean.** One viral video drags a mean up so hard that the
   viral video stops looking viral. Median is unmoved by it.
2. **Leave-one-out baseline.** A video is scored against the channel's OTHER
   videos. On a 4-video channel where one did 1M and three did 900, including
   the 1M in its own baseline halves its apparent multiple.
3. **Shorts and long-form are scored separately.** A Short doing 2M and a
   10-minute video doing 20k are not comparable, and pooling them makes every
   long-form video on a mixed channel look like a failure.
4. **Velocity as well as totals.** Total views reward old videos. views/day
   catches the 3-day-old video that is mid-explosion, the actual buy signal,
   and the one you want before everyone else copies it.
"""
from __future__ import annotations

import math
import statistics
from typing import Any

from . import config
from .yt import age_days, parse_duration, parse_ts, views_of

SHORTS_MAX_SEC = 180  # YouTube's own Shorts ceiling since late 2024


def is_short(video: dict) -> bool:
    dur = parse_duration(video.get("contentDetails", {}).get("duration", ""))
    return 0 < dur <= SHORTS_MAX_SEC


def enrich(video: dict) -> dict:
    """Flatten a videos.list item into the fields scoring actually needs."""
    sn = video.get("snippet", {})
    published = sn.get("publishedAt", "")
    days = age_days(published) if published else 1.0
    v = views_of(video)
    return {
        "id": video.get("id", ""),
        "title": sn.get("title", ""),
        "channel_id": sn.get("channelId", ""),
        "channel_title": sn.get("channelTitle", ""),
        "published_at": published,
        "age_days": round(days, 2),
        "views": v,
        "vpd": round(v / days, 1),
        "likes": int(video.get("statistics", {}).get("likeCount", 0) or 0),
        "comments": int(video.get("statistics", {}).get("commentCount", 0) or 0),
        "duration_sec": parse_duration(video.get("contentDetails", {}).get("duration", "")),
        "is_short": is_short(video),
        "thumbnails": sn.get("thumbnails", {}),
        "topics": _topic_slugs(video),
        "category_id": sn.get("categoryId", ""),
        "url": f"https://www.youtube.com/watch?v={video.get('id','')}",
    }


def _topic_slugs(video: dict) -> list[str]:
    """topicCategories are Wikipedia URLs; the slug is the useful part."""
    out = []
    for url in video.get("topicDetails", {}).get("topicCategories", []) or []:
        slug = url.rstrip("/").rsplit("/", 1)[-1]
        if slug:
            out.append(slug)
    return out


# ── RPM estimation ──────────────────────────────────────────────────────────
def rpm_band(videos: list[dict]) -> tuple[str, tuple[float, float]]:
    """Estimated RPM band for a set of videos.

    Honest framing: you cannot read another channel's real RPM. This maps the
    channel's declared topics to published category ranges and returns a RANGE
    labelled as an estimate. Any tool quoting you a precise dollar figure for
    somebody else's channel is inventing it.
    """
    counts: dict[str, int] = {}
    for v in videos:
        for slug in v.get("topics", []):
            band = config.TOPIC_TO_BAND.get(slug)
            if band:
                counts[band] = counts.get(band, 0) + 1
        if not v.get("topics"):
            band = config.CATEGORY_ID_TO_BAND.get(str(v.get("category_id", "")))
            if band:
                counts[band] = counts.get(band, 0) + 1
    if not counts:
        return "unknown", config.RPM_BANDS["unknown"]
    best = max(counts, key=counts.get)
    return best, config.RPM_BANDS.get(best, config.RPM_BANDS["unknown"])


def safety_flags(videos: list[dict], channel_desc: str = "") -> list[str]:
    """Auto-apply the 'avoid stuff that gets you banned' rule the videos skip."""
    blob = " ".join(v.get("title", "") for v in videos).lower() + " " + channel_desc.lower()
    blob += " " + " ".join(s.lower() for v in videos for s in v.get("topics", []))
    flags = []
    for term in config.BLOCKED_TOPIC_SUBSTRINGS:
        if term in blob:
            flags.append(f"blocked:{term}")
    for term in config.KIDS_TOPIC_SUBSTRINGS:
        if term in blob:
            flags.append(f"low-rpm-kids:{term}")
    return sorted(set(flags))


# ── core scoring ────────────────────────────────────────────────────────────
def _loo_median(values: list[float], idx: int) -> float:
    """Median of `values` with element `idx` removed. Zero-safe."""
    rest = [v for i, v in enumerate(values) if i != idx]
    if not rest:
        return 0.0
    med = statistics.median(rest)
    return med if med > 0 else 0.0


def score_videos(videos: list[dict]) -> list[dict]:
    """Attach outlier scores. Shorts and long-form are bucketed separately."""
    enriched = [v if "vpd" in v else enrich(v) for v in videos]
    for bucket in (True, False):
        group = [v for v in enriched if v["is_short"] is bucket]
        if len(group) < config.MIN_CHANNEL_VIDEOS:
            for v in group:
                v.update(view_multiple=None, velocity_multiple=None,
                         is_outlier=False, outlier_reason="insufficient-sample")
            continue
        view_vals = [float(v["views"]) for v in group]
        vpd_vals = [float(v["vpd"]) for v in group]
        for i, v in enumerate(group):
            vm_base = _loo_median(view_vals, i)
            vel_base = _loo_median(vpd_vals, i)
            vm = round(v["views"] / vm_base, 2) if vm_base else None
            vel = round(v["vpd"] / vel_base, 2) if vel_base else None
            v["view_multiple"] = vm
            v["velocity_multiple"] = vel
            v["baseline_views"] = int(vm_base)
            v["baseline_vpd"] = round(vel_base, 1)

            reasons = []
            if vm is not None and vm >= config.MIN_VIEW_MULTIPLE:
                reasons.append(f"{vm}x channel median views")
            if vel is not None and vel >= config.MIN_VELOCITY_MULTIPLE:
                reasons.append(f"{vel}x channel median views/day")
            big_enough = v["views"] >= (config.MIN_OUTLIER_VIEWS if not bucket
                                        else config.MIN_OUTLIER_VIEWS * 2)
            v["is_outlier"] = bool(reasons) and big_enough
            v["outlier_reason"] = "; ".join(reasons) if reasons else "within channel norm"
            if reasons and not big_enough:
                v["outlier_reason"] += " (below absolute view floor)"
    return enriched


def momentum(videos: list[dict]) -> float:
    """Trend in log(views/day) across uploads, oldest -> newest.

    Positive means each new upload is outperforming the last. Log scale because
    view counts are multiplicative, and a least-squares slope because it is
    stable against one bad upload in the middle of a good run.
    """
    ordered = sorted([v for v in videos if v["vpd"] > 0], key=lambda v: v["published_at"])
    if len(ordered) < 4:
        return 0.0
    ys = [math.log10(v["vpd"]) for v in ordered]
    xs = list(range(len(ys)))
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    denom = sum((x - mx) ** 2 for x in xs)
    if denom == 0:
        return 0.0
    return round(sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / denom, 4)


def profile(channel: dict, videos: list[dict]) -> dict:
    """Full channel verdict: outliers, breakout status, momentum, RPM, safety."""
    scored = score_videos(videos)
    sn = channel.get("snippet", {})
    stats = channel.get("statistics", {})
    subs = int(stats.get("subscriberCount", 0) or 0)
    created = sn.get("publishedAt", "")
    ch_age = age_days(created) if created else 9999.0

    outliers = sorted([v for v in scored if v["is_outlier"]],
                      key=lambda v: (v["velocity_multiple"] or 0), reverse=True)
    top_views = max((v["views"] for v in scored), default=0)
    band_name, band = rpm_band(scored)
    recent_views = sum(v["views"] for v in scored if v["age_days"] <= 30)

    breakout = (ch_age <= config.BREAKOUT_MAX_CHANNEL_AGE_DAYS
                and top_views >= config.BREAKOUT_MIN_TOP_VIEWS)

    # views-per-subscriber: high means the algorithm is carrying the channel
    # rather than its existing audience. Exactly the "low subs, high views"
    # heuristic from the tutorials, made into a number.
    vps = round(top_views / subs, 2) if subs > 0 else None

    return {
        "channel_id": channel.get("id", ""),
        "title": sn.get("title", ""),
        "description": (sn.get("description", "") or "")[:400],
        "created_at": created,
        "channel_age_days": round(ch_age, 1),
        "subscribers": subs,
        "total_views": int(stats.get("viewCount", 0) or 0),
        "video_count": int(stats.get("videoCount", 0) or 0),
        "sampled": len(scored),
        "top_video_views": top_views,
        "views_per_sub": vps,
        "views_last_30d_sampled": recent_views,
        "momentum": momentum(scored),
        "is_breakout": breakout,
        "rpm_band": band_name,
        "rpm_estimate_usd": {"low": band[0], "high": band[1], "note": "estimate from category, not measured"},
        "safety_flags": safety_flags(scored, sn.get("description", "")),
        "outliers": outliers[:10],
        "videos": scored,
    }


def format_score(prof: dict) -> float:
    """Single 0-100 ranking number for 'is this format worth copying'.

    Deliberately transparent rather than a black box: each term below maps to a
    thing the tutorials tell you to look for by eye.
    """
    if prof.get("safety_flags"):
        if any(f.startswith("blocked:") for f in prof["safety_flags"]):
            return 0.0
    score = 0.0
    # 1. Proof the format breaks out at all (0-30)
    best = max((v.get("velocity_multiple") or 0) for v in prof["videos"]) if prof["videos"] else 0
    score += min(30.0, best * 4.0)
    # 2. Low competition proxy: young channel already landing views (0-25)
    if prof["is_breakout"]:
        score += 25.0
    elif prof["channel_age_days"] <= 365:
        score += 12.0
    # 3. Algorithm-carried rather than audience-carried (0-15)
    vps = prof.get("views_per_sub") or 0
    score += min(15.0, vps * 1.5)
    # 4. Still climbing (0-15)
    score += max(0.0, min(15.0, prof["momentum"] * 30.0))
    # 5. Monetisation ceiling (0-15)
    score += min(15.0, prof["rpm_estimate_usd"]["high"] * 0.6)
    if any(f.startswith("low-rpm-kids") for f in prof.get("safety_flags", [])):
        score *= 0.4
    return round(min(100.0, score), 1)
