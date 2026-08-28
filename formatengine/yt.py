"""Quota-aware YouTube Data API v3 client.

Design constraints that shaped this file:

1. The free tier is 10,000 quota units/day and `search.list` costs 100 of them.
   A naive "search for everything" crawler dies after 100 calls. So every code
   path here prefers the 1-unit endpoints (channels/playlistItems/videos) and
   treats `search` as a scarce resource with an explicit budget.
2. Every response is cached to disk by request hash. Re-running a command the
   same day costs zero quota.
3. Every call validates the HTTP status and wraps JSON parsing, so a 403
   quotaExceeded surfaces as a clear error instead of a KeyError three frames
   later.
4. The quota ledger is persisted after every call, so a killed run resumes
   with an accurate spend count instead of double-spending.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any, Iterable

from . import config

API_ROOT = "https://www.googleapis.com/youtube/v3/"

# Whitelist, not blacklist: a search query may only contain these characters.
# Removing "bad" characters is a losing game; allowing only known-good ones is
# not. Anything outside the class is dropped before the query is built.
_QUERY_ALLOWED = re.compile(r"[^A-Za-z0-9 '\-]")
_ID_ALLOWED = re.compile(r"^[A-Za-z0-9_\-]{1,64}$")


class QuotaExhausted(RuntimeError):
    pass


class YouTubeError(RuntimeError):
    pass


def sanitize_query(q: str) -> str:
    """Whitelist-only search query. Never trust an LLM-generated query string."""
    cleaned = _QUERY_ALLOWED.sub(" ", q)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if not cleaned:
        raise ValueError(f"query reduced to empty after whitelist: {q!r}")
    return cleaned[:120]


def valid_id(v: str) -> bool:
    """YouTube video/channel/playlist ids are URL-safe base64-ish only."""
    return bool(_ID_ALLOWED.match(v or ""))


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _today() -> str:
    return _now().strftime("%Y-%m-%d")


class Ledger:
    """Persistent quota + run state. Survives a kill mid-run."""

    def __init__(self, path=config.LEDGER):
        self.path = path
        self.state: dict[str, Any] = {"day": _today(), "spent": 0, "calls": {}, "shipped": []}
        if path.exists():
            try:
                loaded = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    self.state.update(loaded)
            except (json.JSONDecodeError, OSError):
                pass  # corrupt ledger: start clean rather than crash the run
        if self.state.get("day") != _today():
            self.state.update({"day": _today(), "spent": 0, "calls": {}})
            self.save()

    @property
    def spent(self) -> int:
        return int(self.state.get("spent", 0))

    @property
    def remaining(self) -> int:
        return config.DAILY_QUOTA - self.spent

    def can_afford(self, endpoint: str, reserve: int = 0) -> bool:
        cost = config.QUOTA_COSTS.get(endpoint, 1)
        return self.remaining - cost >= reserve

    def charge(self, endpoint: str) -> None:
        cost = config.QUOTA_COSTS.get(endpoint, 1)
        self.state["spent"] = self.spent + cost
        self.state.setdefault("calls", {})
        self.state["calls"][endpoint] = self.state["calls"].get(endpoint, 0) + 1
        self.save()

    def save(self) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.state, indent=2), encoding="utf-8")
        tmp.replace(self.path)


class YouTube:
    def __init__(self, api_key: str | None = None, ledger: Ledger | None = None):
        self.api_key = api_key or os.environ.get("YOUTUBE_API_KEY", "")
        if not self.api_key:
            raise YouTubeError(
                "YOUTUBE_API_KEY missing. Run under Doppler:\n"
                "  doppler run -p youtube-title-autoresearch -c dev -- python -m formatengine ..."
            )
        self.ledger = ledger or Ledger()

    # ── transport ────────────────────────────────────────────────────────────
    def _cache_path(self, endpoint: str, params: dict):
        key = hashlib.sha256(
            (endpoint + json.dumps(params, sort_keys=True)).encode()
        ).hexdigest()[:24]
        return config.CACHE / f"{endpoint}_{key}.json"

    def call(self, endpoint: str, *, cache: bool = True, reserve: int | None = None,
             **params) -> dict:
        """One API call. Cached, quota-charged, status-validated."""
        params = {k: v for k, v in params.items() if v is not None}
        cpath = self._cache_path(endpoint, params)
        if cache and cpath.exists():
            try:
                return json.loads(cpath.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                cpath.unlink(missing_ok=True)  # bad cache entry, refetch

        reserve = config.QUOTA_RESERVE if reserve is None else reserve
        if not self.ledger.can_afford(endpoint, reserve):
            raise QuotaExhausted(
                f"{endpoint} needs {config.QUOTA_COSTS.get(endpoint, 1)}u, "
                f"only {self.ledger.remaining}u left today "
                f"(reserve {reserve}u). Quota resets at midnight Pacific."
            )

        url = API_ROOT + endpoint + "?" + urllib.parse.urlencode({**params, "key": self.api_key})
        req = urllib.request.Request(url, headers={"Accept": "application/json"})

        last_err = None
        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, timeout=30) as resp:
                    if resp.status != 200:
                        raise YouTubeError(f"{endpoint} HTTP {resp.status}")
                    raw = resp.read().decode("utf-8", "replace")
                break
            except urllib.error.HTTPError as e:
                body = e.read().decode("utf-8", "replace")
                try:
                    msg = json.loads(body)["error"]["message"]
                    reasons = [d.get("reason") for d in json.loads(body)["error"].get("errors", [])]
                except (json.JSONDecodeError, KeyError, TypeError):
                    msg, reasons = body[:300], []
                if e.code == 403 and any(r in ("quotaExceeded", "dailyLimitExceeded") for r in reasons):
                    self.ledger.state["spent"] = config.DAILY_QUOTA
                    self.ledger.save()
                    raise QuotaExhausted(f"API says quota exhausted: {msg}") from e
                if e.code in (429, 500, 502, 503) and attempt < 2:
                    last_err = e
                    time.sleep(2 ** attempt)
                    continue
                raise YouTubeError(f"{endpoint} HTTP {e.code}: {msg}") from e
            except urllib.error.URLError as e:
                if attempt < 2:
                    last_err = e
                    time.sleep(2 ** attempt)
                    continue
                raise YouTubeError(f"{endpoint} network error: {e.reason}") from e
        else:
            raise YouTubeError(f"{endpoint} failed after retries: {last_err}")

        self.ledger.charge(endpoint)

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            raise YouTubeError(f"{endpoint} returned non-JSON ({raw[:120]!r})") from e
        if not isinstance(data, dict):
            raise YouTubeError(f"{endpoint} returned {type(data).__name__}, expected object")

        if cache:
            try:
                cpath.write_text(json.dumps(data), encoding="utf-8")
            except OSError:
                pass  # cache is an optimisation, never fatal
        return data

    # ── cheap endpoints (1 unit) ─────────────────────────────────────────────
    def videos(self, ids: Iterable[str]) -> list[dict]:
        """Full stats for up to 50 video ids per unit."""
        ids = [i for i in ids if valid_id(i)]
        out: list[dict] = []
        for i in range(0, len(ids), 50):
            data = self.call(
                "videos",
                part="snippet,statistics,contentDetails,topicDetails,status",
                id=",".join(ids[i:i + 50]),
                maxResults=50,
            )
            out.extend(data.get("items", []))
        return out

    def channels(self, ids: Iterable[str]) -> list[dict]:
        ids = [i for i in ids if valid_id(i)]
        out: list[dict] = []
        for i in range(0, len(ids), 50):
            data = self.call(
                "channels",
                part="snippet,statistics,contentDetails,topicDetails,brandingSettings",
                id=",".join(ids[i:i + 50]),
                maxResults=50,
            )
            out.extend(data.get("items", []))
        return out

    def uploads_playlist(self, channel_id: str) -> str | None:
        items = self.channels([channel_id])
        if not items:
            return None
        return (items[0].get("contentDetails", {})
                        .get("relatedPlaylists", {})
                        .get("uploads"))

    def playlist_video_ids(self, playlist_id: str, limit: int = 50) -> list[str]:
        """Enumerate a channel's uploads at 1 unit per 50 videos.

        This is the whole trick: `search.list` filtered by channel costs 100
        units for the same information. Nobody selling you a niche-finder tool
        wants you to know this endpoint exists.
        """
        ids: list[str] = []
        token = None
        while len(ids) < limit:
            data = self.call(
                "playlistItems", part="contentDetails",
                playlistId=playlist_id, maxResults=min(50, limit - len(ids)),
                pageToken=token,
            )
            for it in data.get("items", []):
                vid = it.get("contentDetails", {}).get("videoId")
                if vid and valid_id(vid):
                    ids.append(vid)
            token = data.get("nextPageToken")
            if not token:
                break
        return ids

    def channel_uploads(self, channel_id: str, limit: int = 50) -> list[dict]:
        """Channel's recent uploads with full stats. Costs ~3 units total."""
        pl = self.uploads_playlist(channel_id)
        if not pl:
            return []
        return self.videos(self.playlist_video_ids(pl, limit))

    # ── expensive endpoint (100 units) ───────────────────────────────────────
    def search(self, query: str, *, published_after: str | None = None,
               order: str = "viewCount", max_results: int = 25,
               kind: str = "video", duration: str | None = None,
               region: str | None = None) -> list[dict]:
        """100 units a shot. Callers must budget these deliberately."""
        data = self.call(
            "search",
            part="snippet",
            q=sanitize_query(query),
            type=kind,
            order=order,
            maxResults=min(50, max_results),
            publishedAfter=published_after,
            videoDuration=duration if kind == "video" else None,
            relevanceLanguage=config.DISCOVERY_LANG,
            regionCode=region,
        )
        return data.get("items", [])


# ── parsing helpers ─────────────────────────────────────────────────────────
def parse_ts(ts: str) -> datetime:
    """YouTube timestamps are RFC-3339 with a trailing Z."""
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def age_days(ts: str, floor: float = 0.5) -> float:
    return max(floor, (_now() - parse_ts(ts)).total_seconds() / 86400.0)


def parse_duration(iso: str) -> int:
    """ISO-8601 PT#H#M#S -> seconds. Used to split shorts from long-form."""
    m = re.fullmatch(r"P(?:(\d+)D)?T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso or "")
    if not m:
        return 0
    d, h, mi, s = (int(x) if x else 0 for x in m.groups())
    return d * 86400 + h * 3600 + mi * 60 + s


def views_of(video: dict) -> int:
    try:
        return int(video.get("statistics", {}).get("viewCount", 0))
    except (TypeError, ValueError):
        return 0
