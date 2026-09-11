"""Automated packaging deconstruction: the whiteboard method, as code.

The tutorials do this by hand on a notepad: write the title out, circle the
interchangeable parts, count the subjects in the thumbnail, note that the
middle one is different. That is a repeatable procedure, which means it can be
run on a hundred videos instead of one.

Two halves:

* `deconstruct_titles` - sends the format's top titles to Groq once and gets
  back a slot template plus the ACTUAL vocabulary used in each slot, mined
  from videos that already performed. The tutorials invent adjectives off the
  top of their head; mining the real distribution tells you which adjectives
  this specific audience actually clicks.

* `analyze_thumbnail` - OpenCV, offline, no API, no key. Counts subjects,
  detects the layout, measures whether the middle subject is the odd one out
  (the "psychology hack"), finds the text band, and pulls the palette. This is
  the checklist you would otherwise write by squinting at a screenshot.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path

import cv2
import numpy as np

from . import config
from .llm import chat_json

TITLE_SYSTEM = """You deconstruct YouTube titles into reusable format templates.

A title format has these possible slots:
  number      - a count, e.g. "25", "7", "Top 10"
  adjective   - the emotional qualifier, e.g. "most incredible", "disturbing"
  topic       - the actual subject, e.g. "birds", "US special operation forces"
  enforcement - a trailing clause that cannot stand alone and only adds urgency,
                e.g. "you must see", "you've never heard of", "that will shock you"
  qualifier   - a scoping clause, e.g. "explained", "in 100 seconds", "ranked"

Rules:
- The `topic` slot is the swappable one. Everything else defines the format.
- `enforcement` must NOT be able to stand alone as a sentence. If the trailing
  words can stand alone, they belong in `qualifier`, not `enforcement`.
- `second_person` is true if the title addresses the viewer as "you" or "your".
- `archetype` is one of: listicle, explainer, levels, pov_life_as, versus,
  ranking, question, howto, story, transformation, other.
- `template` reconstructs the title with slot names in braces, e.g.
  "{number} {adjective} {topic} {enforcement}".

Return ONLY JSON."""

TITLE_USER = """Deconstruct each title below. Then infer the shared format.

Titles:
{titles}

Return JSON exactly:
{{
  "archetype": "...",
  "template": "...",
  "second_person_rate": 0.0,
  "per_title": [
    {{"title": "...", "number": null, "adjective": null, "topic": "...",
      "enforcement": null, "qualifier": null, "second_person": false}}
  ],
  "slot_vocabulary": {{
    "adjective": ["..."], "enforcement": ["..."], "qualifier": ["..."], "number": ["..."]
  }},
  "topic_axis": "the single dimension the topics vary along, e.g. 'species of animal'",
  "notes": "one sentence on what makes this format work"
}}"""


def deconstruct_titles(titles: list[str], model: str | None = None) -> dict:
    """Slot-parse a format's proven titles into a reusable template."""
    titles = [t for t in titles if t and t.strip()][:20]
    if not titles:
        raise ValueError("no titles to deconstruct")
    numbered = "\n".join(f"{i+1}. {t}" for i, t in enumerate(titles))
    out = chat_json(TITLE_SYSTEM, TITLE_USER.format(titles=numbered),
                    model=model, temperature=0.2, max_tokens=3000)
    out.setdefault("per_title", [])
    out.setdefault("slot_vocabulary", {})
    out.setdefault("template", "{topic}")
    out.setdefault("archetype", "other")
    return out


# ── thumbnail deconstruction (offline, free) ────────────────────────────────
def thumbnail_url(video: dict) -> str | None:
    """Prefer the largest thumbnail YouTube actually generated."""
    thumbs = video.get("thumbnails") or video.get("snippet", {}).get("thumbnails", {})
    for key in ("maxres", "standard", "high", "medium", "default"):
        if key in thumbs and thumbs[key].get("url"):
            return thumbs[key]["url"]
    return None


def download_thumbnail(video: dict, dest_dir: Path = config.THUMBS) -> Path | None:
    url = thumbnail_url(video)
    vid = video.get("id", "")
    if not url or not vid:
        return None
    path = dest_dir / f"{vid}.jpg"
    if path.exists() and path.stat().st_size > 1000:
        return path
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            if r.status != 200:
                return None
            blob = r.read()
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError):
        return None
    if len(blob) < 1000:
        return None
    path.write_bytes(blob)
    return path


def _dominant_colors(img: np.ndarray, k: int = 5) -> list[dict]:
    small = cv2.resize(img, (160, 90), interpolation=cv2.INTER_AREA)
    pix = small.reshape(-1, 3).astype(np.float32)
    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 20, 1.0)
    _, labels, centers = cv2.kmeans(pix, k, None, criteria, 3, cv2.KMEANS_PP_CENTERS)
    counts = np.bincount(labels.flatten(), minlength=k)
    order = np.argsort(-counts)
    out = []
    for i in order:
        b, g, r = (int(c) for c in centers[i])
        out.append({"hex": f"#{r:02x}{g:02x}{b:02x}",
                    "share": round(float(counts[i]) / len(labels), 3)})
    return out


def _detect_subjects(img: np.ndarray, text_mask: np.ndarray | None = None) -> dict:
    """Count visually distinct foreground subjects.

    Faces are the strong signal when present, but these thumbnails are often
    cartoon or AI-generated where Haar cascades miss. So faces are combined
    with large-contour blob detection, and the larger of the two wins.

    `text_mask` is subtracted from the edge map first. Overlay text is exactly
    the kind of high-contrast, frame-sized shape the blob pass is looking for,
    so without this a scene thumbnail with three big words measures as a
    three-subject composition.
    """
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape

    faces = []
    try:
        casc = cv2.CascadeClassifier(
            cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
        if not casc.empty():
            found = casc.detectMultiScale(gray, scaleFactor=1.12, minNeighbors=5,
                                          minSize=(int(w * 0.05), int(h * 0.05)))
            faces = [tuple(int(x) for x in f) for f in found]
    except cv2.error:
        faces = []

    # Blob pass: strong edges -> close -> keep contours covering >2% of frame.
    edges = cv2.Canny(cv2.GaussianBlur(gray, (5, 5), 0), 60, 160)
    if text_mask is not None and text_mask.shape == edges.shape:
        # Dilate the glyph mask a little so the stroke outlines around text,
        # not just the glyph interiors, are removed from the edge map.
        grown = cv2.dilate(text_mask,
                           cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9)))
        edges = cv2.bitwise_and(edges, cv2.bitwise_not(grown))
    closed = cv2.morphologyEx(edges, cv2.MORPH_CLOSE,
                              cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (25, 25)))
    contours, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    frame_area = float(w * h)
    blobs = []
    for c in contours:
        x, y, cw, ch = cv2.boundingRect(c)
        if (cw * ch) / frame_area < 0.02:
            continue
        if (cw * ch) / frame_area > 0.85:      # background, not a subject
            continue
        blobs.append((x, y, cw, ch))
    blobs.sort(key=lambda b: -(b[2] * b[3]))
    blobs = blobs[:8]

    count = max(len(faces), min(len(blobs), 5))
    return {"face_count": len(faces), "blob_count": len(blobs),
            "subject_count": count, "faces": faces, "blobs": blobs}


def _flatness(img: np.ndarray) -> float:
    """Share of the frame held by its 8 commonest colours, 0-1.

    Separates flat illustration from photography. Illustration fills large
    regions with identical colour; a photograph spreads across thousands of
    near-shades. Measured 2026-09-10 over 44 real thumbnails:

        ThePaintProf (flat illustration)   n=12  median 0.787  (0.580-0.942)
        NuchaReviews + AventSir            n=32  median 0.548  (0.363-0.865)

    Individual images overlap in the 0.58-0.75 band, so this is only meaningful
    as a FORMAT-level median across a sample, which is how thumbnail_checklist()
    uses it. Do not classify a single thumbnail with it.
    """
    small = cv2.resize(img, (160, 90), interpolation=cv2.INTER_AREA)
    q = (small >> 4).astype(np.uint32)              # 4 bits per channel
    keys = (q[..., 0] << 8) | (q[..., 1] << 4) | q[..., 2]
    _, counts = np.unique(keys, return_counts=True)
    counts = np.sort(counts)[::-1]
    return round(float(counts[:8].sum()) / keys.size, 3)


def _cell_count(img: np.ndarray) -> int:
    """Count grid cells: many similar small tiles, as in a captioned icon menu.

    This CANNOT reuse _subject_analysis's blobs. That closes with a 25x25
    ellipse, which merges adjacent grid cells into one region larger than the
    85% background cut, so a 12-cell grid reports as ~2 subjects. Measured
    2026-09-10 on 44 thumbnails, this detector scores 7 and 8 on the two real
    grids (6,182,111 and 2,673,243 views) and 0-3 on everything else.
    """
    small = cv2.resize(img, (480, 270), interpolation=cv2.INTER_AREA)
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    edges = cv2.dilate(cv2.Canny(gray, 50, 150), np.ones((3, 3), np.uint8), iterations=1)
    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    area = 480.0 * 270.0
    n = 0
    for c in contours:
        x, y, w, h = cv2.boundingRect(c)
        frac = (w * h) / area
        # Tile-sized and roughly square. Cells in these grids run 1-20% of the
        # frame; the aspect bound rejects text bars and full-width banners.
        if 0.01 <= frac <= 0.20 and 0.35 <= w / max(h, 1) <= 2.8:
            n += 1
    return n


def _thirds_analysis(img: np.ndarray) -> dict:
    """Is the middle third the odd one out?

    The tutorials call this the psychology hack: two familiar subjects flanking
    one unfamiliar one. Visually it shows up as left and right thirds looking
    like each other while the middle looks like neither. Chi-square distance
    between HSV histograms measures exactly that.
    """
    h, w = img.shape[:2]
    third = w // 3
    bands = [img[:, :third], img[:, third:2 * third], img[:, 2 * third:]]
    hists = []
    for b in bands:
        hsv = cv2.cvtColor(b, cv2.COLOR_BGR2HSV)
        hist = cv2.calcHist([hsv], [0, 1], None, [24, 24], [0, 180, 0, 256])
        hists.append(cv2.normalize(hist, hist).flatten())

    def d(a, b):
        return float(cv2.compareHist(hists[a].astype(np.float32),
                                     hists[b].astype(np.float32),
                                     cv2.HISTCMP_CHISQR))

    lr, lm, rm = d(0, 2), d(0, 1), d(1, 2)
    flank_similarity = lr
    middle_distance = (lm + rm) / 2.0
    # Middle is "unique" when the flanks resemble each other far more than
    # either resembles the middle.
    middle_unique = middle_distance > (flank_similarity * 1.6 + 0.05)

    energy = []
    for b in bands:
        g = cv2.cvtColor(b, cv2.COLOR_BGR2GRAY)
        energy.append(float(cv2.Canny(g, 60, 160).mean()))
    total = sum(energy) or 1.0
    center_dominant = energy[1] / total > 0.42

    return {
        "middle_unique": bool(middle_unique),
        "center_dominant": bool(center_dominant),
        "flank_similarity_chisq": round(lr, 3),
        "middle_distance_chisq": round(middle_distance, 3),
        "edge_energy_split": [round(e / total, 3) for e in energy],
    }


def _text_regions(img: np.ndarray) -> tuple[dict, np.ndarray]:
    """MSER glyph detection -> (stats, mask).

    The mask is returned separately rather than inside the stats dict so the
    analysis stays JSON-serialisable; a numpy array in there would break every
    format spec written to disk.

    The filter is deliberately strict. A loose one turns any busy photograph
    into "90% text": MSER fires on cloud edges, rock texture and starfields
    just as happily as on letters. Real overlay glyphs are compact, reasonably
    solid, and bounded in size, so all three are required.
    """
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape
    empty = np.zeros((h, w), np.uint8)
    try:
        mser = cv2.MSER_create()
        mser.setMinArea(int(w * h * 0.0008))
        mser.setMaxArea(int(w * h * 0.04))
        regions, _ = mser.detectRegions(gray)
    except cv2.error:
        return {"text_coverage": 0.0, "has_header_band": False, "text_boxes": 0}, empty

    mask = np.zeros((h, w), np.uint8)
    boxes = 0
    for r in regions:
        pts = r.reshape(-1, 1, 2)
        x, y, rw, rh = cv2.boundingRect(pts)
        if rh == 0 or rw == 0:
            continue
        ar = rw / rh
        # Glyph-shaped: upright-ish, tall enough to read, not a banner-wide smear.
        if not (0.12 < ar < 3.0):
            continue
        if not (h * 0.035 < rh < h * 0.42):
            continue
        # Solidity: the fraction of the bounding box the region actually fills.
        # The upper bound has to stay generous. Thumbnail lettering is heavy
        # display type (Impact, Arial Black), and those glyphs are nearly solid
        # blocks; a tighter ceiling rejects the exact text this is looking for.
        extent = len(r) / float(rw * rh)
        if not (0.18 < extent < 0.96):
            continue
        # Paint the region's OWN pixels, not its bounding box. Filled boxes
        # overlap so heavily on a busy image that coverage saturates near 1.0
        # regardless of whether any text is present, which is what made this
        # metric read 0.9 on plain photographs.
        mask[r[:, 1], r[:, 0]] = 255
        boxes += 1

    coverage = float(mask.mean()) / 255.0
    header = float(mask[:int(h * 0.28), :].mean()) / 255.0
    return ({"text_coverage": round(coverage, 4),
             "has_header_band": bool(header > 0.10 and header > coverage * 1.15),
             "text_boxes": boxes},
            mask)


def analyze_thumbnail(path: Path) -> dict:
    """Full offline thumbnail checklist. No API calls, no key, no cost."""
    img = cv2.imread(str(path))
    if img is None:
        raise ValueError(f"unreadable thumbnail: {path}")
    img = cv2.resize(img, (1280, 720), interpolation=cv2.INTER_AREA)
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # Text first: the subject pass needs its mask so overlay lettering is not
    # counted as composition. Where text sits ON a subject this also erases
    # part of that subject's edges, which is the right trade: a subject large
    # enough to matter still clears the 2% area floor from its unmasked parts.
    text, text_mask = _text_regions(img)
    subjects = _detect_subjects(img, text_mask)
    thirds = _thirds_analysis(img)

    n = subjects["subject_count"]
    if n >= 3:
        layout = "three_subject" if n == 3 else "multi_subject"
    elif n == 2:
        layout = "two_subject_versus"
    elif n == 1:
        layout = "single_center_subject" if thirds["center_dominant"] else "single_subject"
    else:
        layout = "scene_no_clear_subject"

    return {
        "layout": layout,
        "subject_count": n,
        "face_count": subjects["face_count"],
        "middle_unique": thirds["middle_unique"],
        "center_dominant": thirds["center_dominant"],
        "has_header_text": text["has_header_band"],
        "text_coverage": text["text_coverage"],
        "palette": _dominant_colors(img),
        "brightness": round(float(gray.mean()) / 255.0, 3),
        "saturation": round(float(hsv[:, :, 1].mean()) / 255.0, 3),
        "contrast": round(float(gray.std()) / 255.0, 3),
        "edge_density": round(float(cv2.Canny(gray, 60, 160).mean()) / 255.0, 4),
        "flatness": _flatness(img),
        "cell_count": _cell_count(img),
        "_detail": {"thirds": thirds, "text": text,
                    "blob_count": subjects["blob_count"]},
    }


def thumbnail_checklist(analyses: list[dict]) -> dict:
    """Collapse many thumbnails into the rules the format actually follows.

    A trait only becomes a rule when the format keeps doing it. 60% is the cut:
    below that it is one designer's choice on one video, not a format rule.
    """
    if not analyses:
        return {}
    n = len(analyses)

    def rate(key):
        return round(sum(1 for a in analyses if a.get(key)) / n, 2)

    layouts: dict[str, int] = {}
    for a in analyses:
        layouts[a["layout"]] = layouts.get(a["layout"], 0) + 1
    dominant_layout = max(layouts, key=layouts.get)

    counts = [a["subject_count"] for a in analyses]
    palette: dict[str, float] = {}
    for a in analyses:
        for c in a.get("palette", [])[:3]:
            palette[c["hex"]] = palette.get(c["hex"], 0.0) + c["share"]
    top_colors = sorted(palette.items(), key=lambda kv: -kv[1])[:5]

    rules = []
    if layouts[dominant_layout] / n >= 0.6:
        rules.append(f"layout: {dominant_layout} ({layouts[dominant_layout]}/{n} videos)")
    if rate("middle_unique") >= 0.6:
        rules.append("middle subject must visually contrast with the flanking two")
    if rate("center_dominant") >= 0.6:
        rules.append("center of frame carries the visual weight")
    if rate("has_header_text") >= 0.6:
        rules.append("header text band across the top")
    avg_sat = sum(a["saturation"] for a in analyses) / n
    if avg_sat >= 0.5:
        rules.append(f"high saturation (format average {avg_sat:.2f})")
    avg_con = sum(a["contrast"] for a in analyses) / n
    if avg_con >= 0.22:
        rules.append(f"high contrast (format average {avg_con:.2f})")

    # Art style. Photographic and illustrated formats want opposite source
    # material, and hardcoding "use a real photograph" broke ThePaintProf, whose
    # 6.18M winner is entirely flat illustration. Threshold 0.65 sits midway
    # between the two measured format medians (0.548 vs 0.787); see _flatness().
    flats = [a["flatness"] for a in analyses if a.get("flatness") is not None]
    avg_flat = (sum(flats) / len(flats)) if flats else None
    art_style = None
    if avg_flat is not None:
        art_style = "illustrated" if avg_flat >= 0.65 else "photographic"
        rules.append(f"art style: {art_style} (flatness {avg_flat:.2f})")

    # Cell density. A menu of many small captioned tiles is a real layout the
    # subject-count vocabulary cannot express: ThePaintProf's two biggest videos
    # (6.18M, 2.67M) are 8-12 captioned icon cells, which the classifier would
    # otherwise flatten to "multi_subject" and describe as evenly spaced
    # characters. Uses _cell_count, NOT blob_count - see _cell_count().
    cells = [a.get("cell_count", 0) for a in analyses]
    avg_cells = sum(cells) / n if cells else 0
    grid_rate = round(sum(1 for c in cells if c >= 6) / n, 2)
    if grid_rate >= 0.6:
        dominant_layout = "grid_menu"
        rules.append(f"grid of many captioned cells ({avg_cells:.1f} average)")
    elif grid_rate > 0:
        # Reported without changing the layout. On ThePaintProf only 2 of 12
        # sampled thumbnails are grids - but they are the two biggest videos on
        # the channel, so this is worth surfacing rather than rounding away.
        rules.append(f"grid layout used on {grid_rate:.0%} of thumbnails "
                     "(check whether those are the outliers)")

    return {
        "sample_size": n,
        "dominant_layout": dominant_layout,
        "art_style": art_style,
        "avg_flatness": round(avg_flat, 3) if avg_flat is not None else None,
        "grid_rate": grid_rate,
        "avg_cells": round(avg_cells, 1),
        "layout_distribution": layouts,
        "subject_count_mode": max(set(counts), key=counts.count),
        "middle_unique_rate": rate("middle_unique"),
        "center_dominant_rate": rate("center_dominant"),
        "header_text_rate": rate("has_header_text"),
        "avg_saturation": round(avg_sat, 3),
        "avg_contrast": round(avg_con, 3),
        "avg_brightness": round(sum(a["brightness"] for a in analyses) / n, 3),
        "signature_palette": [{"hex": h, "weight": round(w, 2)} for h, w in top_colors],
        "rules": rules,
    }
