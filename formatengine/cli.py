"""format-engine CLI.

    doppler run -p youtube-title-autoresearch -c dev -- python -m formatengine <cmd>

Pipeline:
    discover     find channels whose format is breaking out right now   (~200u)
    deconstruct  turn one of them into a reusable format spec           (~5u)
    bend         generate topic pivots + measure demand/competition     (~500u)
    brief        write a gated production brief for the best bend       (0u)
    verify-thumb check your own thumbnail against the measured format   (0u)
"""
from __future__ import annotations

import argparse
import re
import sys

from . import bend as bend_mod
from . import brief as brief_mod
from . import config, discover, packaging, store
from .llm import LLMError
from .outlier import format_score, profile
from .yt import QuotaExhausted, YouTube, YouTubeError, valid_id


def resolve_channel(yt: YouTube, ref: str) -> str | None:
    """Accept a channel id, /channel/ URL, @handle, or a video URL."""
    ref = (ref or "").strip()
    if valid_id(ref) and ref.startswith("UC"):
        return ref
    m = re.search(r"/channel/(UC[A-Za-z0-9_\-]+)", ref)
    if m:
        return m.group(1)
    m = re.search(r"(?:youtube\.com/watch\?v=|youtu\.be/)([A-Za-z0-9_\-]{11})", ref)
    if m:
        vids = yt.videos([m.group(1)])
        if vids:
            return vids[0].get("snippet", {}).get("channelId")
        return None
    m = re.search(r"@([A-Za-z0-9_.\-]+)", ref)
    if m:
        data = yt.call("channels", part="id", forHandle="@" + m.group(1))
        items = data.get("items", [])
        return items[0]["id"] if items else None
    return None


def cmd_quota(args, yt: YouTube) -> int:
    l = yt.ledger
    print(f"Date          {l.state['day']}")
    print(f"Spent         {l.spent:,} / {config.DAILY_QUOTA:,} units")
    print(f"Remaining     {l.remaining:,} units")
    print(f"Calls         {l.state.get('calls', {})}")
    print(f"\nAffordable with what's left:")
    print(f"  searches (100u)          {max(0, l.remaining - config.QUOTA_RESERVE) // 100}")
    print(f"  channel profiles (3u)    {max(0, l.remaining - config.QUOTA_RESERVE) // 3}")
    return 0


def cmd_discover(args, yt: YouTube) -> int:
    seeds = args.seed or None
    results = discover.discover(
        yt, seeds=seeds, window_days=args.window, top_n=args.top,
        max_searches=args.searches, sample=args.sample,
        run=args.run, resume=not args.fresh,
    )
    print("\n" + discover.summarize(results, limit=args.top))
    path = store.write_json(config.DATA / f"discover-{args.run}-{store.today()}.json", results)
    print(f"\nSaved {len(results)} profiles -> {path}")
    if results:
        best = results[0]
        print(f"\nNext: python -m formatengine deconstruct {best['channel_id']} "
              f"--name \"{store.slugify(best['title'])}\"")
    return 0


def cmd_profile(args, yt: YouTube) -> int:
    cid = resolve_channel(yt, args.channel)
    if not cid:
        print(f"Could not resolve channel: {args.channel}", file=sys.stderr)
        return 2
    chans = yt.channels([cid])
    if not chans:
        print(f"Channel not found: {cid}", file=sys.stderr)
        return 2
    vids = yt.channel_uploads(cid, limit=args.sample)
    prof = profile(chans[0], vids)
    prof["score"] = format_score(prof)

    rpm = prof["rpm_estimate_usd"]
    print(f"\n{prof['title']}  ({prof['channel_id']})")
    print(f"  format score      {prof['score']}/100")
    print(f"  subscribers       {prof['subscribers']:,}")
    print(f"  channel age       {prof['channel_age_days']:.0f} days"
          + ("   BREAKOUT" if prof["is_breakout"] else ""))
    print(f"  sampled uploads   {prof['sampled']}")
    print(f"  momentum          {prof['momentum']:+.4f} (log10 views/day per upload)")
    print(f"  views per sub     {prof['views_per_sub']}")
    print(f"  RPM band          ${rpm['low']:.0f}-${rpm['high']:.0f} ({prof['rpm_band']}) "
          f"- {rpm['note']}")
    if prof["safety_flags"]:
        print(f"  SAFETY FLAGS      {', '.join(prof['safety_flags'])}")

    print(f"\n  Outliers ({len(prof['outliers'])}):")
    for v in prof["outliers"]:
        print(f"    {v['views']:>10,}  {v['view_multiple'] or 0:>5.1f}x views  "
              f"{v['velocity_multiple'] or 0:>5.1f}x vel  {v['age_days']:>5.0f}d  "
              f"{v['title'][:56]}")
    if not prof["outliers"]:
        print("    none - this channel has no breakout to copy")
    store.write_json(config.DATA / f"profile-{cid}.json", prof)
    return 0


def cmd_deconstruct(args, yt: YouTube) -> int:
    cid = resolve_channel(yt, args.channel)
    if not cid:
        print(f"Could not resolve channel: {args.channel}", file=sys.stderr)
        return 2
    chans = yt.channels([cid])
    if not chans:
        print(f"Channel not found: {cid}", file=sys.stderr)
        return 2
    vids = yt.channel_uploads(cid, limit=args.sample)
    prof = profile(chans[0], vids)
    prof["score"] = format_score(prof)

    # Deconstruct what WORKED. Outliers lead, but a format's thumbnail rules
    # only emerge over ~6+ images, so top the sample up with the channel's next
    # best performers rather than inferring a "rule" from two pictures.
    long_form = [v for v in prof["videos"] if not v["is_short"]] or prof["videos"]
    pool = [v for v in prof["outliers"] if not v["is_short"]]
    seen = {v["id"] for v in pool}
    for v in sorted(long_form, key=lambda v: -v["views"]):
        if len(pool) >= args.top:
            break
        if v["id"] not in seen:
            pool.append(v)
            seen.add(v["id"])
    pool = pool[:args.top]
    if not pool:
        print("No videos to deconstruct.", file=sys.stderr)
        return 2
    titles = [v["title"] for v in pool]

    print(f"→ deconstructing {len(titles)} proven titles via Groq")
    try:
        title_format = packaging.deconstruct_titles(titles, model=args.model)
    except LLMError as e:
        print(f"Title deconstruction failed: {e}", file=sys.stderr)
        return 3

    print(f"→ analysing {len(pool)} thumbnails offline (OpenCV, no API)")
    analyses = []
    for v in pool:
        p = packaging.download_thumbnail(v)
        if not p:
            continue
        try:
            a = packaging.analyze_thumbnail(p)
            a["video_id"] = v["id"]
            a["title"] = v["title"]
            analyses.append(a)
        except (ValueError, Exception) as e:  # one bad image must not kill the run
            print(f"  skip {v['id']}: {e}")
    checklist = packaging.thumbnail_checklist(analyses)

    spec = {
        "name": args.name or prof["title"],
        "slug": store.slugify(args.name or prof["title"]),
        "source_channel": {"id": cid, "title": prof["title"],
                           "url": f"https://www.youtube.com/channel/{cid}",
                           "subscribers": prof["subscribers"],
                           "age_days": prof["channel_age_days"],
                           "score": prof["score"]},
        "rpm_band": prof["rpm_band"],
        "rpm_estimate_usd": prof["rpm_estimate_usd"],
        "safety_flags": prof["safety_flags"],
        "titles": titles,
        "title_format": title_format,
        "thumbnail_checklist": checklist,
        "thumbnail_analyses": analyses,
        "source_videos": [{"id": v["id"], "title": v["title"], "views": v["views"],
                           "view_multiple": v["view_multiple"],
                           "velocity_multiple": v["velocity_multiple"],
                           "url": v["url"]} for v in pool],
    }
    path = store.save_format(spec)

    print(f"\nFORMAT: {spec['name']}  (slug: {spec['slug']})")
    print(f"  archetype   {title_format.get('archetype')}")
    print(f"  template    {title_format.get('template')}")
    print(f"  topic axis  {title_format.get('topic_axis','?')}")
    print(f"  2nd person  {title_format.get('second_person_rate','?')}")
    vocab = title_format.get("slot_vocabulary", {})
    for slot, words in vocab.items():
        if words:
            print(f"  {slot:<11} {', '.join(str(w) for w in words[:8])}")
    print(f"\n  Thumbnail rules (measured over {checklist.get('sample_size',0)} images):")
    for r in checklist.get("rules", []):
        print(f"    - {r}")
    if not checklist.get("rules"):
        print("    - no consistent rule found; this format's thumbnails vary")
    print(f"\nSaved -> {path}")
    print(f"Next: python -m formatengine bend {spec['slug']}")
    return 0


def cmd_formats(args, yt: YouTube) -> int:
    specs = store.list_formats()
    if not specs:
        print("No formats saved yet. Run: deconstruct <channel>")
        return 0
    print(f"{'SLUG':<34} {'ARCHETYPE':<14} {'RPM$':>9}  TEMPLATE")
    print("-" * 100)
    for s in specs:
        r = s.get("rpm_estimate_usd", {})
        print(f"{s.get('slug',''):<34} "
              f"{s.get('title_format',{}).get('archetype',''):<14} "
              f"{r.get('low',0):>4.0f}-{r.get('high',0):<4.0f} "
              f"{s.get('title_format',{}).get('template','')[:46]}")
    return 0


def cmd_bend(args, yt: YouTube) -> int:
    spec = store.load_format(args.format)
    if not spec:
        print(f"No such format: {args.format}. Run `formats` to list.", file=sys.stderr)
        return 2
    print(f"→ generating {args.n} bends for {spec['slug']} (Groq, 0 quota)")
    try:
        bends = bend_mod.bend_format(yt, spec, n=args.n, check_top=args.check,
                                     model=args.model)
    except LLMError as e:
        print(f"Bend generation failed: {e}", file=sys.stderr)
        return 3
    print(f"→ saturation-checked top {args.check} ({args.check * 100} units)\n")
    print(bend_mod.summarize_bends(bends, limit=args.n))
    spec["bends"] = bends
    store.save_format(spec)
    if bends:
        print(f"\nNext: python -m formatengine brief {spec['slug']} --bend 0")
    return 0


def cmd_brief(args, yt: YouTube) -> int:
    spec = store.load_format(args.format)
    if not spec:
        print(f"No such format: {args.format}", file=sys.stderr)
        return 2
    bends = spec.get("bends") or []
    if args.topic:
        tf = spec.get("title_format", {})
        # Fill {topic}, then drop any slot the manual path can't fill so the
        # model gets a readable seed title instead of leftover braces.
        seed = tf.get("template", "{topic}").replace("{topic}", args.topic)
        seed = re.sub(r"\{[a-z_]+\}", "", seed)
        seed = re.sub(r"\s{2,}", " ", seed).strip()
        chosen = {"topic": args.topic, "search_term": args.topic, "distance": "manual",
                  "proposed_title": seed, "opportunity": None,
                  "saturation": {"checked": False, "reason": "manual topic"}}
    else:
        if not bends:
            print(f"No bends for {spec['slug']}. Run: bend {spec['slug']}", file=sys.stderr)
            return 2
        if args.bend >= len(bends):
            print(f"--bend {args.bend} out of range (have {len(bends)})", file=sys.stderr)
            return 2
        chosen = bends[args.bend]

    print(f"→ writing brief for: {chosen.get('proposed_title') or chosen.get('topic')}")
    try:
        b = brief_mod.build(spec, chosen, words=args.words, model=args.model)
    except LLMError as e:
        print(f"Brief generation failed: {e}", file=sys.stderr)
        return 3

    result = brief_mod.gate(b, spec)
    jpath, mpath = brief_mod.save(b, spec, result)

    print(f"\n{'PASS' if result['passed'] else 'BLOCKED'}  {b.get('title','')}")
    for c in result["checks"]:
        mark = "ok  " if c["pass"] else "FAIL"
        print(f"  [{mark}] {c['check']:<24} {c['value']} (limit {c['limit']})")
    for f in result["failures"]:
        print(f"  ! {f}")
    for w in result["warnings"]:
        print(f"  ~ {w}")
    print(f"\n  {mpath}\n  {jpath}")
    return 0 if result["passed"] else 1


def cmd_verify_thumb(args, yt: YouTube) -> int:
    """Score YOUR thumbnail against the format you're copying. No quota, no key."""
    from pathlib import Path
    spec = store.load_format(args.format)
    if not spec:
        print(f"No such format: {args.format}", file=sys.stderr)
        return 2
    cl = spec.get("thumbnail_checklist", {})
    try:
        a = packaging.analyze_thumbnail(Path(args.file))
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 2

    rows, misses = [], []
    want_layout = cl.get("dominant_layout")
    rows.append(("layout", a["layout"], want_layout, a["layout"] == want_layout))
    want_n = cl.get("subject_count_mode")
    rows.append(("subjects", a["subject_count"], want_n, a["subject_count"] == want_n))
    if cl.get("middle_unique_rate", 0) >= 0.6:
        rows.append(("middle unique", a["middle_unique"], True, a["middle_unique"]))
    if cl.get("header_text_rate", 0) >= 0.6:
        rows.append(("header text", a["has_header_text"], True, a["has_header_text"]))
    for key, want in (("saturation", cl.get("avg_saturation")), ("contrast", cl.get("avg_contrast")),
                      ("brightness", cl.get("avg_brightness"))):
        if want:
            ok = abs(a[key] - want) <= 0.12
            rows.append((key, round(a[key], 3), round(want, 3), ok))

    print(f"\nThumbnail vs format `{spec['slug']}`\n")
    print(f"{'TRAIT':<16} {'YOURS':<22} {'FORMAT':<22} OK")
    print("-" * 68)
    for name, got, want, ok in rows:
        print(f"{name:<16} {str(got):<22} {str(want):<22} {'yes' if ok else 'NO'}")
        if not ok:
            misses.append(name)
    passed = len(rows) - len(misses)
    print(f"\nMatches {passed}/{len(rows)}")
    if misses:
        print("Fix: " + ", ".join(misses))
    return 0 if not misses else 1


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="formatengine", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("quota", help="show today's quota spend").set_defaults(fn=cmd_quota)

    d = sub.add_parser("discover", help="find breakout channels")
    d.add_argument("--seed", action="append", help="seed phrase (repeatable)")
    d.add_argument("--window", type=int, default=config.DISCOVERY_WINDOW_DAYS)
    d.add_argument("--top", type=int, default=20, help="channels to profile")
    d.add_argument("--searches", type=int, default=4, help="max search calls (100u each)")
    d.add_argument("--sample", type=int, default=30, help="uploads sampled per channel")
    d.add_argument("--run", default="default", help="checkpoint name")
    d.add_argument("--fresh", action="store_true", help="ignore checkpoint")
    d.set_defaults(fn=cmd_discover)

    pr = sub.add_parser("profile", help="score one channel")
    pr.add_argument("channel", help="channel id, URL, @handle, or a video URL")
    pr.add_argument("--sample", type=int, default=50)
    pr.set_defaults(fn=cmd_profile)

    dc = sub.add_parser("deconstruct", help="build a reusable format spec from a channel")
    dc.add_argument("channel")
    dc.add_argument("--name", help="format name (defaults to channel title)")
    dc.add_argument("--sample", type=int, default=50)
    dc.add_argument("--top", type=int, default=8, help="proven videos to deconstruct")
    dc.add_argument("--model", default=None)
    dc.set_defaults(fn=cmd_deconstruct)

    sub.add_parser("formats", help="list saved formats").set_defaults(fn=cmd_formats)

    b = sub.add_parser("bend", help="generate + saturation-check niche bends")
    b.add_argument("format", help="format slug")
    b.add_argument("-n", type=int, default=10, help="candidates to generate")
    b.add_argument("--check", type=int, default=5, help="how many to search-verify (100u each)")
    b.add_argument("--model", default=None)
    b.set_defaults(fn=cmd_bend)

    br = sub.add_parser("brief", help="write a gated production brief")
    br.add_argument("format")
    br.add_argument("--bend", type=int, default=0, help="index into the format's bends")
    br.add_argument("--topic", help="skip bends, brief this topic directly")
    br.add_argument("--words", type=int, default=1200)
    br.add_argument("--model", default=None)
    br.set_defaults(fn=cmd_brief)

    vt = sub.add_parser("verify-thumb", help="check your thumbnail against a format")
    vt.add_argument("file")
    vt.add_argument("--format", required=True)
    vt.set_defaults(fn=cmd_verify_thumb)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        yt = YouTube()
    except YouTubeError as e:
        print(str(e), file=sys.stderr)
        return 4
    try:
        return args.fn(args, yt)
    except QuotaExhausted as e:
        print(f"\nQUOTA: {e}", file=sys.stderr)
        print("Progress is checkpointed - rerun the same command tomorrow to resume.",
              file=sys.stderr)
        return 5
    except YouTubeError as e:
        print(f"\nYouTube API error: {e}", file=sys.stderr)
        return 6
    except KeyboardInterrupt:
        print("\nInterrupted (checkpoint saved).", file=sys.stderr)
        return 130
