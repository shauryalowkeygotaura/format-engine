"""Disk persistence: format library, run checkpoints, shipped-brief history.

Everything is plain JSON on disk. Checkpoints exist because discovery runs can
take a while and a 403/kill mid-run should resume from the last good state
rather than re-burning quota on channels already profiled.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import config

_SLUG = re.compile(r"[^a-z0-9]+")


def slugify(text: str, maxlen: int = 60) -> str:
    s = _SLUG.sub("-", (text or "").lower()).strip("-")
    return (s or "untitled")[:maxlen]


def today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def write_json(path: Path, obj: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)
    return path


def read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default


# ── format library ──────────────────────────────────────────────────────────
def save_format(spec: dict) -> Path:
    name = spec.get("slug") or slugify(spec.get("name", "format"))
    spec["slug"] = name
    spec["saved_at"] = datetime.now(timezone.utc).isoformat()
    return write_json(config.FORMATS / f"{name}.json", spec)


def load_format(slug: str) -> dict | None:
    return read_json(config.FORMATS / f"{slugify(slug)}.json")


def list_formats() -> list[dict]:
    out = []
    for p in sorted(config.FORMATS.glob("*.json")):
        spec = read_json(p)
        if spec:
            out.append(spec)
    return out


# ── run checkpoints ─────────────────────────────────────────────────────────
def checkpoint_path(run: str) -> Path:
    return config.DATA / f"checkpoint_{slugify(run)}.json"


def load_checkpoint(run: str) -> dict:
    return read_json(checkpoint_path(run), default={"done": [], "results": []}) or \
        {"done": [], "results": []}


def save_checkpoint(run: str, ckpt: dict) -> None:
    ckpt["updated_at"] = datetime.now(timezone.utc).isoformat()
    write_json(checkpoint_path(run), ckpt)


def clear_checkpoint(run: str) -> None:
    checkpoint_path(run).unlink(missing_ok=True)


# ── shipped briefs (feeds the self-similarity guard) ────────────────────────
def record_shipped(brief: dict) -> None:
    ledger = read_json(config.LEDGER, default={}) or {}
    shipped = ledger.get("shipped", [])
    # Regenerating the same brief must REPLACE its draft row, not add another.
    # Otherwise every retry of one package is counted as a separate upload, the
    # self-similarity guard sees the draft as a "100% similar previous upload",
    # and blocks its own regeneration. Rows that carry a video_id were actually
    # published and are never replaced.
    title = brief.get("title", "")
    shipped = [r for r in shipped
               if not (r.get("title") == title and not r.get("video_id"))]
    shipped.append({
        "at": datetime.now(timezone.utc).isoformat(),
        "title": brief.get("title", ""),
        "format_slug": brief.get("format_slug", ""),
        "topic": brief.get("topic", ""),
        "substance": brief.get("substance", []),
        # Register feeds the slang budget in package.gate(). Absent on anything
        # shipped before 2026-09-05, which reads as "proper" and is the safe
        # default: an unknown past upload should not spend the slang allowance.
        "register": brief.get("register") or "proper",
        "external_hook": brief.get("external_hook"),
    })
    ledger["shipped"] = shipped[-200:]
    write_json(config.LEDGER, ledger)


def recent_shipped(n: int = config.SELF_SIMILARITY_WINDOW,
                   exclude_draft_title: str | None = None) -> list[dict]:
    """The last n ledger rows, optionally hiding one title's own draft rows.

    record_shipped() already replaces a draft row on regeneration, but that
    happens at WRITE time and the gate reads BEFORE the write. So regenerating
    a brief saw the previous attempt at the same title and failed it at 100%
    self-similarity, i.e. the gate blocked a brief for resembling itself.

    Rows carrying a video_id were really published and are never hidden, so a
    genuine attempt to re-upload an existing title still fails the check.
    """
    ledger = read_json(config.LEDGER, default={}) or {}
    rows = ledger.get("shipped") or []
    if exclude_draft_title:
        rows = [r for r in rows
                if not (r.get("title") == exclude_draft_title
                        and not r.get("video_id"))]
    return rows[-n:]
