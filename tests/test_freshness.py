"""Hook scoring and the packaging gate.

Every fixture here is a real measurement taken 2026-09-04, recorded in
Deliverables/anime-analysis-interest-factor-research-2026-09-04.md. The point of
pinning them is that the thresholds in config were derived from these numbers,
so if someone retunes a threshold these tests say which real video it breaks.
"""
from __future__ import annotations

import pytest

from formatengine import config, freshness, package


# ── sanitization ─────────────────────────────────────────────────────────────
def test_sanitize_keeps_real_hooks_intact():
    assert freshness.sanitize_hook("Jeffrey Epstein") == "Jeffrey Epstein"
    assert freshness.sanitize_hook("L & Light") == "L & Light"
    assert freshness.sanitize_hook("Re:Zero") == "Re:Zero"


def test_sanitize_strips_leading_dash_so_it_cannot_become_a_flag():
    """yt-dlp is called with argv, so no shell is involved, but a term starting
    with '-' would still be parsed as an option rather than a query."""
    assert not freshness.sanitize_hook("--config-location x").startswith("-")
    assert not freshness.sanitize_hook("-rf /").startswith("-")


def test_sanitize_is_whitelist_not_removal():
    out = freshness.sanitize_hook('Epstein"; rm -rf /; echo "')
    assert '"' not in out and ";" not in out and "/" not in out


def test_sanitize_rejects_empty():
    with pytest.raises(ValueError):
        freshness.sanitize_hook("!!!***")


def test_score_hook_returns_invalid_instead_of_raising():
    """An unusable hook must not crash the CLI with a traceback."""
    out = freshness.score_hook("!!!", check_saturation=False)
    assert out["verdict"] == "INVALID"


# ── attention shape: reported, never gating ──────────────────────────────────
def _series(pairs):
    return [(d, v) for d, v in pairs]


def test_attention_shape_on_empty_series():
    assert freshness.attention_shape([]) == {"available": False}


def test_attention_shape_finds_peak_and_decay():
    # Jeffrey Epstein, real shape: enormous Feb spike decaying to a floor.
    series = ([("2026020%d" % i, 1_000_000) for i in range(1, 6)]
              + [("202607%02d" % i, 11_000) for i in range(1, 29)])
    shape = freshness.attention_shape(series)
    assert shape["available"] is True
    assert shape["peak"] == 1_000_000
    assert shape["pct_of_peak"] < 0.02        # ~1% of peak, as measured
    assert shape["peak_age_days"] > 140       # the winner shipped 151d past peak


# ── the recognition floor, pinned to measured articles ───────────────────────
MEASURED_90D_MEDIAN = {
    # worked as external hooks
    "September 11 attacks": 11_167,
    "Jeffrey Epstein": 10_632,
    "Spider-Man": 5_245,
    "Carl Jung": 3_331,
    "Central Intelligence Agency": 2_752,
    # in-universe subjects, the baseline the hooks beat
    "Death Note": 2_212,
    "Classroom of the Elite": 866,
    "Light novel": 653,
    "L (Death Note)": 535,
    "Light Yagami": 467,
    "Re:Zero": 85,
}
HOOKS_THAT_WORKED = ["September 11 attacks", "Jeffrey Epstein", "Spider-Man",
                     "Carl Jung", "Central Intelligence Agency"]


@pytest.mark.parametrize("name", HOOKS_THAT_WORKED)
def test_floor_admits_every_hook_that_actually_worked(name):
    assert MEASURED_90D_MEDIAN[name] >= config.HOOK_RECOGNITION_FLOOR, (
        f"{name} was used in a video that overperformed; the floor must not "
        f"exclude it")


@pytest.mark.parametrize("name", [n for n in MEASURED_90D_MEDIAN
                                  if n not in HOOKS_THAT_WORKED])
def test_floor_rejects_in_universe_subjects(name):
    assert MEASURED_90D_MEDIAN[name] < config.HOOK_RECOGNITION_FLOOR, (
        f"{name} is an in-universe subject, not an external hook")


# ── verdicts ─────────────────────────────────────────────────────────────────
def _score(monkeypatch, *, daily=None, article="X", top_views=0, checked=True,
           slang=None):
    def fake_recognition(term):
        if daily is not None:
            return {"scored": True, "source": "wikipedia", "register": "proper",
                    "term": term, "article": article, "daily_median": daily,
                    "attention": {"available": True, "median": daily,
                                  "recent_7d_mean": daily, "prior_30d_mean": daily,
                                  "trend": 1.0, "peak": daily * 100,
                                  "peak_day": "20260205", "peak_age_days": 151,
                                  "pct_of_peak": 0.01}}
        if slang is not None:
            return {"scored": True, "source": "youtube", "register": "slang",
                    "term": term, "article": None,
                    "youtube": {"n": 12, "top_views": slang, "median_views": 5215}}
        return {"scored": False, "source": None, "register": None, "term": term,
                "article": None, "reason": "no Wikipedia article resolves, and "
                                           "YouTube returns no results at all"}

    def fake_saturation(term, niche="", **kw):
        if not checked:
            return {"checked": False, "reason": "yt-dlp unavailable", "query": term}
        return {"checked": True, "query": term, "n": 10, "n_raw": 12,
                "median_views": top_views // 2, "top_views": top_views,
                "raw_top_views": top_views,
                "top_title": "Could L Catch Epstein?"}

    monkeypatch.setattr(freshness, "recognition", fake_recognition)
    monkeypatch.setattr(freshness, "saturation", fake_saturation)
    return freshness.score_hook("Jeffrey Epstein", "anime")


def test_strong_recognition_open_field_is_go(monkeypatch):
    assert _score(monkeypatch, daily=11_006, top_views=5_000)["verdict"] == "GO"


def test_in_universe_recognition_is_weak(monkeypatch):
    assert _score(monkeypatch, daily=477, top_views=0)["verdict"] == "WEAK"


def test_big_incumbent_makes_it_crowded(monkeypatch):
    # "Could L Catch Epstein?" measured 3,251,712 views on the same hook.
    out = _score(monkeypatch, daily=11_006, top_views=3_251_712)
    assert out["verdict"] == "CROWDED"


def test_slang_scores_via_youtube_not_unscored(monkeypatch):
    """The highest views/day video in the sample (12,952) used a term with no
    Wikipedia article. The YouTube track must actually score it."""
    out = _score(monkeypatch, daily=None, slang=1_942_421)
    assert out["verdict"] == "GO"
    assert out["register"] == "slang"


def test_term_nobody_uses_is_unscored(monkeypatch):
    """The nonsense control returned zero YouTube results and no article."""
    out = _score(monkeypatch, daily=None, slang=None)
    assert out["verdict"] == "UNSCORED"
    assert out["register"] is None


def test_wikipedia_hook_is_proper_register(monkeypatch):
    assert _score(monkeypatch, daily=11_006)["register"] == "proper"


# ── the YouTube recognition floor, pinned to measured terms ──────────────────
@pytest.mark.parametrize("term,n,top", [
    ("goonpocalypse", 12, 1_942_421),
    ("skibidi", 12, 150_681_962),
    ("gooning", 11, 4_684_859),
])
def test_slang_floor_admits_live_slang(term, n, top):
    assert n >= config.SLANG_MIN_RESULTS and top >= config.SLANG_MIN_TOP_VIEWS, (
        f"{term} is live slang and must clear the floor")


def test_slang_floor_rejects_nonsense():
    # "zravnik qplorth" measured n=0.
    assert 0 < config.SLANG_MIN_RESULTS


# ── the competitor filter (the CROWDED false positive) ──────────────────────
def _rows(*pairs):
    return {"ok": True, "query": "q", "reason": None,
            "rows": [{"title": t, "view_count": v} for t, v in pairs]}


def test_unrelated_news_video_is_not_a_competitor(monkeypatch):
    """Measured live: 'Jeffrey Epstein anime' returned a 3.5M mainstream news
    video that competes with nothing in this niche."""
    monkeypatch.setattr(freshness, "_youtube_search", lambda *a, **k: _rows(
        ("People have found Epstein accounts", 3_515_737),
        ("Could L Catch Epstein?", 3_251_712),
    ))
    out = freshness.saturation("Jeffrey Epstein", "anime", topic="L Lawliet")
    assert out["n"] == 1
    assert out["n_raw"] == 2
    assert out["top_views"] == 3_251_712       # the real rival
    assert out["raw_top_views"] == 3_515_737   # the news video, reported only


def test_all_results_unrelated_reads_as_open_field(monkeypatch):
    monkeypatch.setattr(freshness, "_youtube_search", lambda *a, **k: _rows(
        ("People have found Epstein accounts", 3_515_737),
        ("Epstein documentary trailer", 900_000),
    ))
    out = freshness.saturation("Jeffrey Epstein", "anime", topic="L Lawliet")
    assert out["n"] == 0 and out["top_views"] == 0


def test_one_letter_character_name_still_matches_as_a_word():
    """This niche is full of one-letter names. 'Could L Catch Epstein?' is a
    real competitor and must not be discarded for being short."""
    assert "l" in freshness._tokens("Could L Catch Epstein?")


def test_short_token_does_not_match_inside_a_longer_word(monkeypatch):
    """A topic of 'L' must not match the 'l' buried in 'helicopter'."""
    assert "l" not in freshness._tokens("Epstein island helicopter footage")
    monkeypatch.setattr(freshness, "_youtube_search", lambda *a, **k: _rows(
        ("Epstein island helicopter footage", 5_000_000),
    ))
    out = freshness.saturation("Jeffrey Epstein", "", topic="L")
    assert out["n"] == 0


def test_no_niche_falls_back_to_hook_matching(monkeypatch):
    monkeypatch.setattr(freshness, "_youtube_search", lambda *a, **k: _rows(
        ("Epstein explained", 400_000), ("Unrelated cooking video", 900_000),
    ))
    out = freshness.saturation("Jeffrey Epstein")
    assert out["n"] == 1 and out["top_views"] == 400_000


def test_failed_saturation_check_is_reported_not_silently_passed(monkeypatch):
    out = _score(monkeypatch, daily=11_006, checked=False)
    assert any("UNKNOWN" in n for n in out["notes"])


# ── the packaging gate ───────────────────────────────────────────────────────
SPEC = {"slug": "smart-analysis", "titles": ["How Smart is L?", "Why Light vs L Isn't Close"],
        "title_format": {"template": "{topic}", "archetype": "other"},
        "thumbnail_checklist": {}}


def _pkg(title, *, verdict="GO", thumb="THE ANSWER", **kw):
    base = {"title": title, "thumbnail_text": thumb, "external_hook": "Jeffrey Epstein",
            "hook_score": {"verdict": verdict, "notes": ["n"],
                           "saturation": {"checked": True, "n": 5,
                                          "top_views": 3_251_712,
                                          "top_title": "Could L Catch Epstein?"}},
            "alt_titles": [], "topic": "L"}
    base.update(kw)
    return base


def test_gate_passes_a_measured_winner():
    # Nucha's actual 444k title.
    r = package.gate(_pkg("No, L Can't Catch Epstein"), SPEC)
    assert r["passed"], r["failures"]


def test_gate_blocks_recommendation_framing():
    """The one non-conflict title in the 80-video sample was the channel floor
    at 396 views/day."""
    r = package.gate(_pkg("Why You Should Read Light Novels"), SPEC)
    assert not r["passed"]
    assert any("396" in f for f in r["failures"])


def test_gate_blocks_weak_hook():
    r = package.gate(_pkg("Is L Smart?", verdict="WEAK"), SPEC)
    assert not r["passed"]
    assert any("WEAK" in f for f in r["failures"])


def test_gate_does_not_block_unscored_hook():
    r = package.gate(_pkg("How L Survived the Goonpocalypse", verdict="UNSCORED"), SPEC)
    assert r["passed"], r["failures"]
    assert any("check the spelling" in w.lower() for w in r["warnings"])


# ── register detection and the slang budget ──────────────────────────────────
def test_register_detects_symbol_censoring():
    # Avent's actual thumbnail text.
    assert package.register_of(_pkg("A$$ PULL Explained")) == "slang"


def test_register_detects_homoglyph_evasion():
    # Nucha's actual title, mathematical-alphanumeric letters dodging a filter.
    assert package.register_of(_pkg("How 𝓝𝓱𝓪𝓲 Survived It")) == "slang"


def test_register_detects_slang_hook_even_with_clean_title():
    pkg = _pkg("How L Survived It")
    pkg["hook_score"]["register"] = "slang"
    assert package.register_of(pkg) == "slang"


def test_register_proper_for_ordinary_title():
    assert package.register_of(_pkg("No, L Can't Catch Epstein")) == "proper"


def _ledger(monkeypatch, n_slang, n_total=10):
    rows = ([{"title": f"s{i}", "register": "slang"} for i in range(n_slang)]
            + [{"title": f"p{i}", "register": "proper"}
               for i in range(n_total - n_slang)])
    monkeypatch.setattr(package.store, "recent_shipped", lambda *a, **k: rows)


def test_slang_allowed_while_under_budget(monkeypatch):
    """The reference channel ran 3 slang in its last 10, so 2 already spent
    must still leave room for this one."""
    _ledger(monkeypatch, 2)
    r = package.gate(_pkg("A$$ PULL Explained"), SPEC)
    assert r["passed"], r["failures"]
    assert any("last of the slang budget" in w for w in r["warnings"])


def test_slang_blocked_once_budget_is_spent(monkeypatch):
    _ledger(monkeypatch, 3)
    r = package.gate(_pkg("A$$ PULL Explained"), SPEC)
    assert not r["passed"]
    assert any("Slang budget spent" in f for f in r["failures"])


def test_consecutive_slang_is_allowed(monkeypatch):
    """Two of the reference channel's three slang uploads were back to back, so
    this is a rate cap and deliberately not an adjacency rule."""
    _ledger(monkeypatch, 1)
    r = package.gate(_pkg("A$$ PULL Explained"), SPEC)
    assert r["passed"], r["failures"]


def test_proper_register_never_touches_the_budget(monkeypatch):
    _ledger(monkeypatch, 3)
    r = package.gate(_pkg("No, L Can't Catch Epstein"), SPEC)
    assert r["passed"], r["failures"]
    assert not any(c["check"] == "slang_budget" for c in r["checks"])


def test_legacy_ledger_rows_without_register_count_as_proper(monkeypatch):
    monkeypatch.setattr(package.store, "recent_shipped",
                        lambda *a, **k: [{"title": "old"} for _ in range(10)])
    assert package.slang_budget_state()["used"] == 0


def test_gate_warns_but_passes_on_crowded():
    r = package.gate(_pkg("No, L Can't Catch Epstein", verdict="CROWDED"), SPEC)
    assert r["passed"]
    assert any("CROWDED" in w for w in r["warnings"])


def test_gate_blocks_overlong_title():
    long = "Why Ayanokoji Versus Light Yagami And Johan Liebert Is Really Not Close At All"
    r = package.gate(_pkg(long), SPEC)
    assert not r["passed"]
    assert any("cap of" in f for f in r["failures"])


def test_format_may_raise_its_own_title_cap():
    """ThePaintProf's best video ever, 6,182,111 views, is 45 chars. A global
    40-char cap blocks it, so length is per-format."""
    title = "Every Real-Life Glitch Explained in 11 Minutes"
    assert len(title) == 46 > config.MAX_TITLE_CHARS

    tight = dict(SPEC, titles=[])
    assert not package.gate(_pkg(title), tight)["passed"]

    loose = dict(SPEC, titles=[],
                 title_format={"template": "{topic}", "archetype": "other",
                               "max_chars": 50, "max_words": 9})
    r = package.gate(_pkg(title), loose)
    assert r["passed"], r["failures"]


def test_title_caps_ignore_junk_overrides():
    bad = dict(SPEC, title_format={"max_chars": "not-a-number"})
    assert package._title_caps(bad) == (config.MAX_TITLE_CHARS,
                                        config.MAX_TITLE_WORDS)


# ── art style drives the hook instructions (the globalised-spec bug) ─────────
ILLUSTRATED = dict(SPEC, thumbnail_checklist={
    "art_style": "illustrated", "avg_flatness": 0.787,
    "dominant_layout": "grid_menu", "avg_cells": 9.4})
PHOTO = dict(SPEC, thumbnail_checklist={
    "art_style": "photographic", "avg_flatness": 0.548,
    "dominant_layout": "two_subject_versus"})


def test_illustrated_format_is_not_told_to_use_a_photograph():
    """ThePaintProf's 6.18M winner contains no photograph. The old hardcoded
    'must be photographic' would have pushed that format the wrong way."""
    out = " ".join(package._hook_visuals(ILLUSTRATED, "Carl Jung", "Jung + a sigil"))
    assert "NOT as a photograph" in out
    assert "must be an actual photograph" not in out


def test_photographic_format_still_demands_a_real_photograph():
    out = " ".join(package._hook_visuals(PHOTO, "Carl Jung", "Jung + a sigil"))
    assert "must be an actual photograph" in out


def test_unmeasured_art_style_says_so_instead_of_guessing():
    out = " ".join(package._hook_visuals(SPEC, "Carl Jung", "x"))
    assert "UNMEASURED" in out


def test_grid_menu_layout_gets_cell_instructions():
    out = " ".join(package._hook_visuals(ILLUSTRATED, "Carl Jung", "x"))
    assert "ONE captioned cell among many" in out


def test_hook_visuals_always_demand_exact_naming():
    for spec in (ILLUSTRATED, PHOTO, SPEC):
        assert any("exact proper name" in i
                   for i in package._hook_visuals(spec, "Carl Jung", "x"))


# ── template decay ───────────────────────────────────────────────────────────
def _uses(monkeypatch, n):
    monkeypatch.setattr(package, "template_use_count", lambda slug: n)


def test_fresh_template_gets_no_decay_warning(monkeypatch):
    _uses(monkeypatch, 0)
    r = package.gate(_pkg("No, L Can't Catch Epstein"), SPEC)
    assert not any("use #" in w for w in r["warnings"])


def test_fifth_use_warns(monkeypatch):
    _uses(monkeypatch, 4)
    r = package.gate(_pkg("No, L Can't Catch Epstein"), SPEC)
    assert any("use #5" in w and "95%" in w for w in r["warnings"])


def test_tenth_use_warns_loudly(monkeypatch):
    _uses(monkeypatch, 9)
    r = package.gate(_pkg("No, L Can't Catch Epstein"), SPEC)
    assert any("use #10" in w and "99%" in w for w in r["warnings"])


def _lens_spec():
    spec = dict(SPEC)
    spec["title_format"] = {**(SPEC.get("title_format") or {}), "template_kind": "lens"}
    return spec


def test_lens_template_does_not_get_the_99_percent_warning(monkeypatch):
    """Enrico Tartarotti, 2026-09-25: 'The LIES That Make X ACTUALLY Work' held
    1.11M -> 594k -> 688k. The PaintProf curve was not measured on lenses."""
    _uses(monkeypatch, 9)
    r = package.gate(_pkg("No, L Can't Catch Epstein"), _lens_spec())
    assert not any("99%" in w or "95%" in w for w in r["warnings"])
    assert any("use #10" in w and "lens" in w for w in r["warnings"])


def test_lens_template_is_quiet_before_the_warn_threshold(monkeypatch):
    _uses(monkeypatch, 2)
    r = package.gate(_pkg("No, L Can't Catch Epstein"), _lens_spec())
    assert not any("use #" in w for w in r["warnings"])


def test_unknown_template_kind_keeps_the_topic_warning(monkeypatch):
    """Unset means unmeasured: the conservative (louder) warning stays."""
    _uses(monkeypatch, 9)
    spec = dict(SPEC)
    spec["title_format"] = {**(SPEC.get("title_format") or {}), "template_kind": "bogus"}
    r = package.gate(_pkg("No, L Can't Catch Epstein"), spec)
    assert any("use #10" in w and "99%" in w for w in r["warnings"])


def test_template_decay_never_blocks(monkeypatch):
    """The curve is real but three mechanisms produce it and public data cannot
    separate them, so this must warn rather than block."""
    _uses(monkeypatch, 50)
    r = package.gate(_pkg("No, L Can't Catch Epstein"), SPEC)
    assert r["passed"], r["failures"]


# ── the hook must be named in the title (5.4x) ──────────────────────────────
def test_hook_named_in_title_passes_quietly():
    r = package.gate(_pkg("No, L Can't Catch Epstein"), SPEC)
    assert not any("does not appear in the title" in w for w in r["warnings"])


def test_hook_missing_from_title_warns():
    r = package.gate(_pkg("No, L Can't Catch Him"), SPEC)
    assert any("does not appear in the title" in w for w in r["warnings"])


def test_short_hook_is_checked_not_skipped():
    """A hook of only short words must not pass by default; both sides are
    tokenised the same way."""
    pkg = _pkg("Why Light Loses", external_hook="CIA")
    r = package.gate(pkg, SPEC)
    assert any("does not appear in the title" in w for w in r["warnings"])


def test_gate_blocks_clone_of_source_title():
    r = package.gate(_pkg("How Smart is L?"), SPEC)
    assert not r["passed"]
    assert any("clone" in f.lower() for f in r["failures"])


def test_gate_blocks_missing_thumbnail_text():
    r = package.gate(_pkg("No, L Can't Catch Epstein", thumb=""), SPEC)
    assert not r["passed"]


def test_gate_warns_when_thumbnail_text_restates_title():
    r = package.gate(_pkg("No, L Can't Catch Epstein",
                          thumb="No L Can't Catch Epstein"), SPEC)
    assert any("restates" in w for w in r["warnings"])


def test_gate_warns_on_title_with_no_collision():
    r = package.gate(_pkg("The Burden of True Altruism"), SPEC)
    assert any("no 'vs'" in w for w in r["warnings"])


def test_mid_title_question_mark_counts_as_shape():
    """Observed live: "Space Chernobyl? Explained" was scored shapeless by a
    trailing-only test."""
    r = package.gate(_pkg("Space Chernobyl? Explained",
                          external_hook="Chernobyl"), SPEC)
    assert not any("no 'vs'" in w for w in r["warnings"])


def test_hook_token_shared_with_niche_does_not_match_alone(monkeypatch):
    """Observed live: hook "Chernobyl disaster" and topic "space disaster"
    share "disaster", which matched a Columbia shuttle video containing no
    "chernobyl" at all."""
    monkeypatch.setattr(freshness, "_youtube_search", lambda *a, **k: _rows(
        ("Kalpana Chawla | Mystery of NASA Columbia Space Disaster", 23_701_530),
        ("Chernobyl in space, the reactor that fell", 120_000),
    ))
    out = freshness.saturation("Chernobyl disaster", "space", topic="space disaster")
    assert out["n"] == 1
    assert out["top_views"] == 120_000
