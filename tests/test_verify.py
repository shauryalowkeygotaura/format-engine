"""Tone gate, fact check helpers, and the ledger bugs found running a real brief.

Fixtures are the actual 2026-09-11 failure: a brief that passed every
structural check with fabricated facts and graphic content.
"""
from __future__ import annotations

from formatengine import brief as B, config, store, verify


def _beats(*texts):
    return [{"beat": i + 1, "narration": t} for i, t in enumerate(texts)]


# ── graphic content ──────────────────────────────────────────────────────────
def test_gore_counts_markers_across_beats():
    b = {"hook": "A probe fails.",
         "beats": _beats("Blood fills the cabin.", "The flesh gives way.",
                         "The capsule drifts.")}
    g = verify.check_gore(b)
    assert g["count"] == 2 and g["beats_affected"] == 2


def test_gore_ignores_ordinary_peril():
    b = {"hook": "The reactor overheats.",
         "beats": _beats("Alarms sound.", "The hull cracks.", "Radiation spikes.")}
    assert verify.check_gore(b)["count"] == 0


def test_gate_blocks_saturated_gore():
    heavy = "Blood. Flesh. A corpse. Skin peels off. Vomit."
    b = {"title": "Totally New Title Here", "hook": "x " * 10,
         "beats": _beats(heavy, "The Alarm rings.", "Silence falls."),
         "substance": [{"claim": f"c{i}"} for i in range(5)]}
    r = B.gate(b, {"slug": "t", "titles": []})
    assert any(c["check"] == "graphic_content" and not c["pass"] for c in r["checks"])


# ── fact-check helpers (offline parts) ──────────────────────────────────────
def test_entities_prefers_longest_name():
    e = verify.entities("The Soviet Venera-9 spacecraft was tracked by NASA.")
    assert "Venera-9" in e and "NASA" in e
    assert "The" not in e and "Soviet" not in e


def test_check_claim_flags_year_missing_from_article(monkeypatch):
    """The real fabrication: Venera 9 is a Venus mission, not a 1978 breakup."""
    monkeypatch.setattr(verify, "resolve_article", lambda t: "Venera 9")
    monkeypatch.setattr(verify, "article_text", lambda t: (
        "Venera 9 was a Soviet uncrewed space mission to Venus. It was "
        "launched on June 8, 1975."))
    r = verify.check_claim("Venera-9, launched in 1975, broke apart in Earth "
                           "orbit in 1978 releasing plutonium.")
    assert r["verdict"] == "unsupported"
    assert r["missing_years"] == ["1978"]


def test_check_claim_verified_when_years_present(monkeypatch):
    monkeypatch.setattr(verify, "resolve_article", lambda t: "Kosmos 954")
    monkeypatch.setattr(verify, "article_text", lambda t: (
        "Kosmos 954 was launched in 1977 and reentered in 1978 over Canada."))
    r = verify.check_claim("Kosmos 954 reentered over Canada in 1978.")
    assert r["verdict"] == "verified"


def test_summarize_does_not_invent_needs_check(monkeypatch):
    claims = {"checked": 1, "unsupported": 1, "results": [
        {"verdict": "unsupported", "claim": "x", "reason": "r"}]}
    out = verify.summarize(claims, {"count": 0, "hits": []})
    assert "needs_check: false" not in out


# ── ledger bugs ──────────────────────────────────────────────────────────────
def test_regenerating_a_draft_replaces_its_ledger_row(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "LEDGER", tmp_path / "ledger.json")
    store.record_shipped({"title": "Same Title", "format_slug": "f"})
    store.record_shipped({"title": "Same Title", "format_slug": "f"})
    rows = store.read_json(config.LEDGER)["shipped"]
    assert len(rows) == 1


def test_published_row_is_never_replaced(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "LEDGER", tmp_path / "ledger.json")
    store.write_json(config.LEDGER, {"shipped": [
        {"title": "Same Title", "format_slug": "f", "video_id": "abc123"}]})
    store.record_shipped({"title": "Same Title", "format_slug": "f"})
    assert len(store.read_json(config.LEDGER)["shipped"]) == 2


def test_chunked_path_is_finalized(monkeypatch):
    """Chunked briefs used to skip format_slug/topic/thumbnail_spec entirely."""
    monkeypatch.setattr(B, "_raw_demand", lambda w: 10**6)
    monkeypatch.setattr(B, "_build_chunked", lambda *a, **k: {"beats": []})
    out = B.build({"slug": "bluntly-explained", "title_format": {}},
                  {"topic": "space disaster", "proposed_title": "T"}, words=500)
    assert out["format_slug"] == "bluntly-explained"
    assert out["topic"] == "space disaster"
    assert "thumbnail_spec" in out


def test_anchor_prefers_numbered_designation_over_a_date():
    """Ranking by length picked "September 15" over "Venera-9" and reported
    that the September 15 article fails to mention 1978 - true but useless."""
    e = verify.entities("The Soviet Venera-9 broke apart on September 15, 1978.")
    assert e[0] == "Venera-9"


def test_anchor_deprioritises_generic_geography():
    """A weak anchor must lose to a specific one. In a sentence containing only
    weak anchors something weak necessarily ranks first, so the claim under
    test is the ordering against a real subject."""
    e = verify.entities("NASA tracked Kosmos 954 until it burned up over the "
                        "Pacific Ocean.")
    assert e[0] == "Kosmos 954"
    assert e.index("Pacific Ocean") > 0


def test_relative_date_in_lead_does_not_false_fail(monkeypatch):
    """Kosmos 954's summary says it reentered "the following year" rather than
    naming 1978, so checking only the summary failed a TRUE claim. The full
    article body states the year."""
    monkeypatch.setattr(verify, "resolve_article", lambda t: "Kosmos 954")
    monkeypatch.setattr(verify, "article_text", lambda t: (
        "Kosmos 954 was launched in 1977. It reentered the following year. "
        "On 24 January 1978 the satellite scattered debris over Canada."))
    r = verify.check_claim("Kosmos 954 re-entered the atmosphere in 1978.")
    assert r["verdict"] == "verified"


# ── voice is per-format, the fourth globalised-threshold bug ────────────────
def test_explainer_format_has_no_second_person_floor():
    """bluntly-explained measured second_person_rate 0.10. The global 4.0 floor
    forced an explainer about an UNMANNED satellite to be written as a crewed
    first-person death scene, because that was the only way to clear it."""
    spec = {"title_format": {"second_person_rate": 0.1}}
    assert B._second_person_floor(spec) == 0.0
    assert "THIRD PERSON" in B._voice_rule(spec)


def test_immersive_format_keeps_the_measured_floor():
    spec = {"title_format": {"second_person_rate": 0.8}}
    assert B._second_person_floor(spec) == config.MIN_SECOND_PERSON_PER_100
    assert "SECOND PERSON" in B._voice_rule(spec)


def test_spec_may_override_the_floor():
    spec = {"title_format": {"second_person_rate": 0.1, "min_second_person": 3}}
    assert B._second_person_floor(spec) == 3.0


def test_junk_override_falls_back_to_measurement():
    spec = {"title_format": {"second_person_rate": 0.8, "min_second_person": "x"}}
    assert B._second_person_floor(spec) == config.MIN_SECOND_PERSON_PER_100


def test_explainer_is_not_failed_for_low_second_person():
    b = {"title": "A Totally Distinct Title", "hook": "x " * 10,
         "beats": _beats("Kosmos 954 fell over Canada.", "Crews searched snow.",
                         "The bill reached millions."),
         "substance": [{"claim": f"c{i}"} for i in range(5)]}
    r = B.gate(b, {"slug": "t", "titles": [],
                   "title_format": {"second_person_rate": 0.1}})
    sp = [c for c in r["checks"] if c["check"] == "second_person_per_100w"][0]
    assert sp["pass"] and sp["limit"] == "n/a (explainer format)"


def test_regenerating_is_not_blocked_by_its_own_draft(tmp_path, monkeypatch):
    """record_shipped replaces a draft at WRITE time, but the gate reads first,
    so a regenerated brief failed at 100% similarity to its own last attempt."""
    monkeypatch.setattr(config, "LEDGER", tmp_path / "ledger.json")
    store.write_json(config.LEDGER, {"shipped": [
        {"title": "Real Chernobyl In Space?", "format_slug": "t"}]})
    rows = store.recent_shipped(exclude_draft_title="Real Chernobyl In Space?")
    assert rows == []


def test_published_title_still_blocks_a_repeat(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "LEDGER", tmp_path / "ledger.json")
    store.write_json(config.LEDGER, {"shipped": [
        {"title": "Real Chernobyl In Space?", "format_slug": "t",
         "video_id": "abc123"}]})
    rows = store.recent_shipped(exclude_draft_title="Real Chernobyl In Space?")
    assert len(rows) == 1


# ── the packaging promise must be delivered ─────────────────────────────────
def _brief(hook, *beats):
    return {"title": "A Distinct Title Here", "hook": "x " * 10,
            "external_hook": hook, "beats": _beats(*beats),
            "substance": [{"claim": f"c{i}"} for i in range(5)]}


def test_hook_missing_from_narration_is_blocked():
    """Titled "Real Chernobyl In Space?" but three of four beats were Galileo,
    Challenger and Columbia. The collision never reached the script."""
    b = _brief("Chernobyl disaster",
               "Cosmos 954 carried a reactor.", "Galileo lost its antenna.",
               "Challenger broke up after launch.")
    r = B.gate(b, {"slug": "t", "titles": [], "title_format": {}})
    assert any(c["check"] == "hook_delivered" and not c["pass"] for c in r["checks"])
    assert any("bait-and-switch" in f for f in r["failures"])


def test_hook_present_in_narration_passes():
    b = _brief("Chernobyl disaster",
               "Cosmos 954 carried a reactor.",
               "Chernobyl released more, but this fell from orbit.",
               "Cleanup crews searched the snow.")
    r = B.gate(b, {"slug": "t", "titles": [], "title_format": {}})
    assert any(c["check"] == "hook_delivered" and c["pass"] for c in r["checks"])


def test_no_external_hook_skips_the_check():
    b = _brief("", "A reactor failed.", "Crews searched.", "The bill grew.")
    r = B.gate(b, {"slug": "t", "titles": [], "title_format": {}})
    assert not any(c["check"] == "hook_delivered" for c in r["checks"])


def test_generic_hook_word_does_not_satisfy_delivery():
    """A Columbia-shuttle script passed hook_delivered on the word "disaster"
    alone, from the hook "Chernobyl disaster", never mentioning Chernobyl."""
    b = _brief("Chernobyl disaster",
               "Columbia returned in 2003.", "The disaster cost millions.",
               "Seven astronauts died.")
    r = B.gate(b, {"slug": "t", "titles": [], "title_format": {}})
    assert any(c["check"] == "hook_delivered" and not c["pass"] for c in r["checks"])


def test_facts_block_lists_shell_claims_and_flags_unverified():
    shell = {"hook": "A satellite fell.", "substance": [
        {"claim": "Kosmos 954 reentered in 1978.", "needs_check": False},
        {"claim": "It carried 50kg of plutonium.", "needs_check": True}]}
    out = B._facts_block(shell)
    assert "Kosmos 954 reentered in 1978." in out
    assert "UNVERIFIED" in out
    assert "already written" in out


def test_facts_block_handles_empty_substance():
    assert "none supplied" in B._facts_block({})


# ── fabricated CATEGORY, with every date correct ────────────────────────────
def test_tech_terms_picks_designations_and_acronyms():
    t = verify._tech_terms("Kosmos 954 used an RTG containing plutonium-238.")
    assert "rtg" in t and "plutonium-238" in t
    assert "used" not in t


def test_missing_terms_surface_even_when_dates_check_out(monkeypatch):
    """The real 2026-09-23 failure: every date right, the category invented.
    Kosmos 954 was a radar ocean reconnaissance satellite with a uranium-235
    fission reactor, not an anti-satellite RTG platform."""
    monkeypatch.setattr(verify, "resolve_article", lambda t: "Kosmos 954")
    monkeypatch.setattr(verify, "article_text", lambda t: (
        "Kosmos 954 was a Soviet radar ocean reconnaissance satellite launched "
        "in 1977. Its nuclear reactor used uranium-235. It reentered in 1978."))
    r = verify.check_claim("Kosmos 954, which reentered in 1978, was powered by "
                           "an RTG containing plutonium-238.")
    assert r["verdict"] == "verified"          # the date really is right
    assert "plutonium-238" in r["missing_terms"]
    assert "rtg" in r["missing_terms"]


def test_missing_terms_reported_in_summary():
    claims = {"checked": 1, "unsupported": 0, "results": [
        {"verdict": "verified", "claim": "x", "article": "Kosmos 954",
         "missing_terms": ["rtg", "plutonium-238"]}]}
    out = verify.summarize(claims, {"count": 0, "hits": []})
    assert "terms absent" in out and "plutonium-238" in out


# ── grounding: retrieve first, then write ───────────────────────────────────
def test_source_text_prefers_the_external_hook(monkeypatch):
    monkeypatch.setattr(verify, "resolve_article",
                        lambda t: "Kosmos 954" if "Kosmos" in t else None)
    monkeypatch.setattr(verify, "article_text", lambda t: "Reactor text.")
    title, text = B.source_text({"external_hook": "Kosmos 954",
                                 "topic": "space disaster"})
    assert title == "Kosmos 954" and text == "Reactor text."


def test_source_text_falls_back_to_topic(monkeypatch):
    monkeypatch.setattr(verify, "resolve_article",
                        lambda t: None if t == "nothing here" else "Space disaster")
    monkeypatch.setattr(verify, "article_text", lambda t: "Topic text.")
    title, _ = B.source_text({"external_hook": "nothing here",
                              "topic": "space disaster"})
    assert title == "Space disaster"


def test_source_text_empty_when_nothing_resolves(monkeypatch):
    monkeypatch.setattr(verify, "resolve_article", lambda t: None)
    assert B.source_text({"external_hook": "zzz", "topic": "qqq"}) == ("", "")


# ── a topic must be a SUBJECT, not a category ───────────────────────────────
from formatengine import package as P


def _topic_pkg(topic):
    return {"title": "A Distinct Title Here", "thumbnail_text": "SO WHAT",
            "external_hook": "", "topic": topic, "alt_titles": [],
            "hook_score": {"verdict": "GO"}}


def _concrete(topic):
    r = P.gate(_topic_pkg(topic), {"slug": "t", "titles": [], "title_format": {}})
    return [c for c in r["checks"] if c["check"] == "topic_is_concrete"][0]["pass"]


def test_category_topic_is_flagged():
    """"space disaster" resolves on Wikipedia to "Space Shuttle Challenger
    disaster", which is why three scripts drifted onto Challenger/Columbia."""
    assert not _concrete("space disaster")
    assert not _concrete("nuclear accidents")


def test_named_subjects_pass():
    for t in ("Kosmos 954", "Apollo 13", "Chernobyl", "the Carrington Event",
              "NASA"):
        assert _concrete(t), t


def test_category_warns_but_does_not_block():
    r = P.gate(_topic_pkg("space disaster"),
               {"slug": "t", "titles": [], "title_format": {}})
    assert r["passed"], r["failures"]
    assert any("category rather than a named subject" in w for w in r["warnings"])


# ── repeated facts across beats ─────────────────────────────────────────────
def test_repetition_counts_restated_facts():
    b = {"beats": _beats(
        "Operation Morning Light recovered twelve pieces.",
        "Canada billed 6,041,174 dollars.",
        "Operation Morning Light found twelve pieces in snow.")}
    r = verify.check_repetition(b)
    assert "operation morning light" in r["repeated"]


def test_repetition_ignores_the_subject_and_hook():
    """A video about Kosmos 954 says "Kosmos 954" in every beat. Correct."""
    b = {"beats": _beats("Kosmos 954 carried a reactor.",
                         "Kosmos 954 fell over Canada.",
                         "Kosmos 954 cost millions.")}
    r = verify.check_repetition(b, exclude="Kosmos 954 Chernobyl")
    assert r["count"] == 0


def test_repetition_clean_on_distinct_beats():
    b = {"beats": _beats("A reactor failed in 1978.",
                         "Crews searched the snow.",
                         "The bill reached millions.")}
    assert verify.check_repetition(b)["count"] == 0


def test_gate_blocks_heavy_repetition():
    b = {"title": "A Distinct Title Here", "hook": "x " * 10,
         "beats": _beats(
             "Operation Morning Light recovered twelve pieces near Baker Lake.",
             "Great Slave Lake saw 1.1 sieverts per hour readings.",
             "Operation Morning Light again, Baker Lake, 1.1 sieverts, "
             "Great Slave Lake."),
         "substance": [{"claim": f"c{i}"} for i in range(5)]}
    r = B.gate(b, {"slug": "t", "titles": [], "title_format": {}})
    rc = [c for c in r["checks"] if c["check"] == "fact_repetition"][0]
    assert not rc["pass"]
    assert any("restated across beats" in f for f in r["failures"])


def test_grouped_number_is_one_fact():
    """A looser pattern split "6,041,174.70" into "6,041" and "174.70" and
    counted one repeated figure twice."""
    assert verify._facts_in("Canada billed 6,041,174.70 dollars.") == {"6,041,174.70"}


def test_designation_digits_are_not_facts():
    """BES-5 and uranium-235 are subject vocabulary, not repeated figures."""
    assert verify._facts_in("A BES-5 reactor held uranium-235.") == set()


def test_event_year_is_not_repetition():
    """An explainer about a 1978 event dates things in several beats."""
    assert verify._facts_in("It reentered in 1978.") == set()


def test_year_regexes_do_not_shadow_each_other(monkeypatch):
    """_YEAR (unanchored, used by check_claim) and _YEAR_EXACT (anchored, used
    by _facts_in) are different patterns. Naming both _YEAR silently disabled
    the whole fact check by reporting every claim as dateless."""
    monkeypatch.setattr(verify, "resolve_article", lambda t: "Kosmos 954")
    monkeypatch.setattr(verify, "article_text", lambda t: "Reentered in 1978.")
    r = verify.check_claim("Kosmos 954 reentered in 1978.")
    assert r["verdict"] == "verified"


# ── narration grounding ──────────────────────────────────────────────────────
# The 2026-09-24 Kosmos 954 brief: all five substance claims checked out, and
# the NARRATION still said "The Soviets paid" (they paid C$3M of the C$6M
# bill), "The ground shook", and that it "echoed Chernobyl disaster in scale".
# The claim check never reads narration, so none of that could be seen.
_KOSMOS = {"topic": "Kosmos 954", "external_hook": "Chernobyl disaster",
           "beats": _beats("Canada billed the Soviet Union. The Soviets paid.",
                           "The ground shook. The cleanup began in the snow.")}


def _judge(flags):
    return lambda system, user, **kw: {"flags": flags}


def _src(title):
    return {"Kosmos 954": "The Soviet Union paid C$3 million.",
            "Chernobyl disaster": "The worst nuclear disaster."}.get(title, "")


def test_narration_contradiction_fails():
    r = verify.check_narration(_KOSMOS, chat=_judge([
        {"sentence": "The Soviets paid.", "verdict": "contradicted",
         "reason": "paid C$3M of C$6M"}]), source=_src)
    assert r["contradicted"] == 1 and r["flags"][0]["beat"] == 1


def test_narration_drops_quotes_the_judge_invented():
    # A small judge model paraphrases. A flag whose sentence is not actually in
    # the narration cannot be located or fixed, so it must not fail the brief.
    r = verify.check_narration(_KOSMOS, chat=_judge([
        {"sentence": "The Soviets refused to pay anything.",
         "verdict": "contradicted", "reason": "x"}]), source=_src)
    assert r["contradicted"] == 0 and r["dropped"] == 1


def test_narration_unsupported_warns_only():
    r = verify.check_narration(_KOSMOS, chat=_judge([
        {"sentence": "The ground shook.", "verdict": "unsupported",
         "reason": "not in source"}]), source=_src)
    assert r["contradicted"] == 0 and r["unsupported"] == 1


def test_narration_without_source_is_unknown_not_clean():
    r = verify.check_narration(_KOSMOS, chat=_judge([]), source=lambda t: "")
    assert r["status"] == "unknown"


def test_narration_matches_quote_despite_trivial_differences():
    # Groq drops the trailing period or re-cases a word; that is the same line.
    r = verify.check_narration(_KOSMOS, chat=_judge([
        {"sentence": "the soviets paid", "verdict": "contradicted",
         "reason": "half"}]), source=_src)
    assert r["contradicted"] == 1 and r["dropped"] == 0


def test_narration_keeps_dropped_quotes_for_eyeballing():
    # The judge varies run to run on the same input, so a flag it could not
    # quote exactly may still be a real contradiction. Surface it, never lose it.
    r = verify.check_narration(_KOSMOS, chat=_judge([
        {"sentence": "The Soviets refused to pay anything.",
         "verdict": "contradicted", "reason": "x"}]), source=_src)
    assert r["dropped_flags"][0]["sentence"].startswith("The Soviets refused")
    assert "refused" in verify.summarize_narration(r)
