"""format-engine CLI.

    doppler run -p youtube-title-autoresearch -c dev -- python -m formatengine <cmd>

Pipeline:
    discover     find channels whose format is breaking out right now   (~200u)
    deconstruct  turn one of them into a reusable format spec           (~5u)
    bend         generate topic pivots + measure demand/competition     (~500u)
    hook         score an external hook before committing packaging     (0u)
    package      decide title + thumbnail BEFORE the script exists      (0u)
    brief        write a script that fits an approved package           (0u)
    verify-thumb check your own thumbnail against the measured format   (0u)

`hook` and `package` need no YouTube API key at all - they run on yt-dlp and
Wikipedia pageviews. Packaging is decided first because that is the order the
channels this engine copies actually work in; see README, "Packaging first".
"""
from __future__ import annotations

import argparse
import re
import sys

from . import bend as bend_mod
from . import brief as brief_mod
from . import package as package_mod
from . import config, discover, feedback, freshness, packaging, store
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
    pkg: dict | None = None
    if getattr(args, "package", None):
        # Packaging-first: the title is already decided and gated, so the script
        # is written to fit it rather than the other way round.
        pkg = package_mod.load(args.package)
        if not pkg:
            print(f"No such package: {args.package}. Look in {config.PACKAGES}.",
                  file=sys.stderr)
            return 2
        if not (pkg.get("gate") or {}).get("passed"):
            print(f"Package {args.package!r} did not pass its gate. Fix the "
                  "packaging before paying for a script.", file=sys.stderr)
            return 2
        chosen = {"topic": pkg.get("topic", ""),
                  "search_term": pkg.get("topic", ""),
                  "distance": "packaged",
                  "proposed_title": pkg.get("title", ""),
                  "opportunity": None,
                  "external_hook": pkg.get("external_hook"),
                  "saturation": (pkg.get("hook_score") or {}).get("saturation",
                                                                  {"checked": False})}
        print(f"→ script will be written to fit approved title: {pkg.get('title')!r}")
    elif args.topic:
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
        if pkg:
            # The whole point of packaging-first is that the packaging is fixed
            # before the script exists. build() regenerates a title and a
            # thumbnail spec from the format; both are discarded here in favour
            # of the versions that already passed the packaging gate.
            b["title"] = pkg.get("title") or b.get("title", "")
            b["alt_titles"] = pkg.get("alt_titles", [])
            b["thumbnail_text"] = pkg.get("thumbnail_text") or b.get("thumbnail_text", "")
            b["thumbnail_spec"] = pkg.get("thumbnail_spec", b.get("thumbnail_spec"))
            b["external_hook"] = pkg.get("external_hook")
            b["hook_score"] = pkg.get("hook_score")
            # Carried so store.record_shipped() can charge the slang budget when
            # this brief passes its gate; without it every upload reads "proper"
            # and the budget never depletes.
            b["register"] = pkg.get("register") or package_mod.register_of(pkg)
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


def cmd_hook(args, yt: YouTube) -> int:
    """Score one external hook. No YouTube API key, no quota."""
    print(f"→ scoring hook {args.term!r}"
          + (f" in niche {args.niche!r}" if args.niche else ""))
    score = freshness.score_hook(args.term, args.niche or "",
                                 topic=args.topic or "",
                                 check_saturation=not args.no_saturation)
    print()
    print(freshness.summarize(score))
    return 0 if score["verdict"] in ("GO", "UNSCORED", "CROWDED") else 1


def cmd_package(args, yt: YouTube) -> int:
    """Decide the title and thumbnail BEFORE any script exists."""
    spec = store.load_format(args.format)
    if not spec:
        print(f"No such format: {args.format}. Run `formats` to list.", file=sys.stderr)
        return 2

    print(f"→ scoring hook {args.hook!r}")
    score = freshness.score_hook(args.hook, args.niche, topic=args.topic,
                                 check_saturation=not args.no_saturation)
    print(freshness.summarize(score))
    if score["verdict"] in ("WEAK", "INVALID") and not args.force:
        print(f"\nBLOCKED before spending a Groq call. Pass --force to override.",
              file=sys.stderr)
        return 1

    print(f"\n→ writing packaging for {args.topic!r} x {args.hook!r}")
    try:
        pkg = package_mod.build(spec, args.topic, args.hook,
                                hook_score=score, model=args.model)
    except LLMError as e:
        print(f"Packaging generation failed: {e}", file=sys.stderr)
        return 3

    result = package_mod.gate(pkg, spec)
    path = package_mod.save(pkg, result)
    print()
    print(package_mod.summarize(pkg, result))
    print(f"\n  {path}")
    if result["passed"]:
        print(f"\nNext: python -m formatengine brief {spec['slug']} "
              f"--package {path.stem}")
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

    # Art style is a HARD fail, not one score among many. The single worst video
    # on the reference channel (4,848 views, against a 60,704 median) is the one
    # thumbnail that abandoned the house style: a dark rendered scene with no
    # caption text, on a channel of flat captioned illustration. Leaving the
    # house style is not a near miss that averages out with the other traits.
    house_break = None
    want_style = cl.get("art_style")
    if want_style and a.get("flatness") is not None:
        got_style = "illustrated" if a["flatness"] >= 0.65 else "photographic"
        ok = got_style == want_style
        rows.append(("art style", f"{got_style} ({a['flatness']})", want_style, ok))
        if not ok:
            house_break = (
                f"HOUSE STYLE BREAK: this thumbnail reads {got_style}, the format "
                f"is {want_style}. The one video on the reference channel that "
                "did this is that channel's worst, at 1/12th its median. This is "
                "a hard fail, not a score.")

    print(f"\nThumbnail vs format `{spec['slug']}`\n")
    print(f"{'TRAIT':<16} {'YOURS':<22} {'FORMAT':<22} OK")
    print("-" * 68)
    for name, got, want, ok in rows:
        print(f"{name:<16} {str(got):<22} {str(want):<22} {'yes' if ok else 'NO'}")
        if not ok:
            misses.append(name)
    passed = len(rows) - len(misses)
    print(f"\nMatches {passed}/{len(rows)}")
    if house_break:
        print(f"\n  ! {house_break}")
    if misses:
        print("Fix: " + ", ".join(misses))
    # A house-style break fails even when every other trait matches.
    return 0 if not misses and not house_break else 1



def cmd_perf(args, yt: YouTube) -> int:
    """How did OUR uploads actually do, versus the source-channel priors."""
    if getattr(args, "attach", None):
        title, vid = args.attach
        ok = feedback.attach_video(title, vid)
        print(f"  {'linked' if ok else 'NO MATCH for'} {title[:50]!r} -> {vid}")
        return 0 if ok else 1

    if getattr(args, "refresh", False):
        # Same handling as every other quota-spending command: a 403 must read
        # as "you are out of quota", not as a traceback.
        try:
            res = feedback.refresh(yt)
        except QuotaExhausted as e:
            print(f"  out of quota: {e}", file=sys.stderr)
            return 1
        except YouTubeError as e:
            print(f"  youtube error: {e}", file=sys.stderr)
            return 1
        print(f"  checked {res['checked']}, updated {res['updated']}"
              + (f" ({res['note']})" if res.get("note") else ""))

    st = feedback.status()
    print(f"\n  shipped {st['shipped']} | with video id {st['with_video_id']} "
          f"| with performance {st['with_performance']}")
    print(f"  loop: {st['verdict']}")

    rows = feedback.format_performance()
    if not rows:
        print("\n  no performance data yet. Link an upload first:")
        print("    python -m formatengine perf --attach \"<brief title>\" <videoId>")
        print("  then, a few days later:  python -m formatengine perf --refresh")
        return 0

    print(f"\n  {'format':<26}{'n':>4}{'median views':>14}{'best':>10}")
    print("  " + "-" * 54)
    for r in rows:
        flag = "" if r["enough_data"] else "  (anecdote)"
        # Format the numbers first, then pad. Applying a width to a comma
        # format spec silently collides once the value is wide enough, which
        # ran two 10-digit view counts together as one unreadable column.
        med = f"{r['median_views']:,}"
        best = f"{r['best']:,}"
        print(f"  {r['format_slug']:<26}{r['n']:>4}{med:>16}{best:>16}{flag}")
    return 0


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

    pf = sub.add_parser("perf", help="how OUR uploads did (closes the loop)")
    pf.add_argument("--refresh", action="store_true",
                    help="pull public stats for linked uploads (1 quota unit per 50)")
    pf.add_argument("--attach", nargs=2, metavar=("TITLE", "VIDEO_ID"),
                    help="link a shipped brief to the video it became")
    pf.set_defaults(fn=cmd_perf)

    b = sub.add_parser("bend", help="generate + saturation-check niche bends")
    b.add_argument("format", help="format slug")
    b.add_argument("-n", type=int, default=10, help="candidates to generate")
    b.add_argument("--check", type=int, default=5, help="how many to search-verify (100u each)")
    b.add_argument("--model", default=None)
    b.set_defaults(fn=cmd_bend)

    hk = sub.add_parser("hook", help="score an external hook (0u, no API key)")
    hk.add_argument("term", help="the external hook, e.g. 'Jeffrey Epstein'")
    hk.add_argument("--niche", default="", help="niche to check saturation within")
    hk.add_argument("--topic", default="",
                    help="in-universe subject, sharpens the competitor filter")
    hk.add_argument("--no-saturation", action="store_true",
                    help="skip the yt-dlp search (faster, recognition only)")
    hk.set_defaults(fn=cmd_hook, needs_yt=False)

    pk = sub.add_parser("package",
                        help="decide title + thumbnail BEFORE the script (0u)")
    pk.add_argument("format", help="format slug")
    pk.add_argument("--topic", required=True, help="the in-universe subject")
    pk.add_argument("--hook", required=True, help="the external hook to collide it with")
    pk.add_argument("--niche", default="", help="niche for the saturation check")
    pk.add_argument("--no-saturation", action="store_true")
    pk.add_argument("--force", action="store_true",
                    help="package even if the hook scores WEAK")
    pk.add_argument("--model", default=None)
    pk.set_defaults(fn=cmd_package, needs_yt=False)

    br = sub.add_parser("brief", help="write a gated production brief")
    br.add_argument("format")
    br.add_argument("--bend", type=int, default=0, help="index into the format's bends")
    br.add_argument("--topic", help="skip bends, brief this topic directly")
    br.add_argument("--package", help="write the script to fit an approved package")
    br.add_argument("--words", type=int, default=1200)
    br.add_argument("--model", default=None)
    br.set_defaults(fn=cmd_brief)

    vt = sub.add_parser("verify-thumb", help="check your thumbnail against a format")
    vt.add_argument("file")
    vt.add_argument("--format", required=True)
    vt.set_defaults(fn=cmd_verify_thumb, needs_yt=False)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    # `hook`, `package` and `verify-thumb` use yt-dlp, Wikipedia and OpenCV, so
    # none of them touches the Data API. Constructing YouTube() unconditionally
    # made those commands fail with a missing-key error they did not need.
    yt = None
    if getattr(args, "needs_yt", True):
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
