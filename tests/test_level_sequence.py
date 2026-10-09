"""Levels scripts must count 1..N once, and the title must promise N."""
from formatengine import brief as B


def _beats(*labels):
    return [{"narration": f"Level {l}, something happens. More text."} for l in labels]


def test_level_numbers_reads_digits_and_words():
    beats = [{"narration": "Level one, the flicker."}, {"narration": "Level 2: the brownout."},
             {"narration": "No label here."}]
    assert B._level_numbers(beats) == [1, 2, None]


def test_sync_title_count_digit_and_word():
    assert B._sync_title_count("The 4 Levels Of City Grid Failure", 17) == "The 17 Levels Of City Grid Failure"
    assert B._sync_title_count("The Four Stages Of Blackout", 8) == "The Eight Stages Of Blackout"
    assert B._sync_title_count("No count here", 5) == "No count here"


def _gate(title, beats):
    g = B.gate({"title": title, "beats": beats, "hook": "a real hook with five words", "substance": []},
               {"titles": []})
    return next((c for c in g["checks"] if c["check"] == "level_sequence"), None)


def test_gate_fails_restarted_count():
    c = _gate("The 8 Levels Of X", _beats(1, 2, 3, 4, 1, 2, 3, 4))
    assert c and not c["pass"]


def test_gate_fails_title_count_mismatch():
    c = _gate("The 4 Levels Of X", _beats(1, 2, 3, 4, 5, 6))
    assert c and not c["pass"]


def test_gate_passes_clean_sequence():
    c = _gate("The 5 Levels Of X", _beats(1, 2, 3, 4, 5))
    assert c and c["pass"]


def test_gate_skips_scripts_without_levels():
    assert _gate("Why Dams Fail", [{"narration": "Water is heavy."}]) is None
