"""The metadata file: what makes skipping an archive a defensible claim.

One entry per archive URL, plus the whole predicate the plan rests on:

    up_to_date(url) = (url in metadata) and (archive_month(url) != current_month)

A skipped archive is a statement that "the PGN on disk for this month is complete". For
that to be worth anything it has to survive a crash, which is why every write is atomic
and why :func:`load` treats a corrupt file as empty rather than raising — the cost of an
empty file is a re-download of about a minute of requests, and the alternative is a
crash loop.

Writes are ``tmp`` + ``os.replace``, so ``metadata.json`` on disk is always valid JSON.
"""

from __future__ import annotations

import json
import os
import sys
import time
from typing import Any, Dict, List, Optional

from . import config
from .pgn_store import PgnStore

VERSION = 1


class Metadata:
    """The parsed metadata file. Plain dicts inside, so it stays hand-editable."""

    def __init__(self, player: Optional[str] = None, path=None) -> None:
        self.player = player
        self.path = path or config.METADATA
        self.archives: Dict[str, Dict[str, Any]] = {}
        self.updated_at: str = ""

    # ---------------------------------------------------------------- queries

    def __contains__(self, url: str) -> bool:
        return url in self.archives

    def entry(self, url: str) -> Optional[Dict[str, Any]]:
        return self.archives.get(url)

    def is_up_to_date(self, url: str, current_month: str) -> bool:
        """The skip predicate, and nothing else.

        Both conditions matter. Being in the file proves we fetched it at least once;
        being outside the current month proves the source cannot have grown since.
        """
        if url not in self.archives:
            return False
        # The URL is the source of truth for the month; the recorded one is a fallback
        # for hand-edited entries. No month means no completeness claim.
        month = config.archive_month(url) or self.archives[url].get("month") or ""
        if not month:
            return False
        return month != current_month

    # ---------------------------------------------------------------- mutation

    def record(
        self,
        url: str,
        *,
        month: Optional[str] = None,
        label: Optional[str] = None,
        uuids: Optional[List[str]] = None,
        current_month: str = "",
        store: Optional[PgnStore] = None,
    ) -> Dict[str, Any]:
        """Store the facts about an archive after its games are safely on disk.

        ``month`` is the calendar month parsed from the URL, or ``""`` for an
        unrecognised one. ``label`` is the on-disk directory, which for an odd URL is a
        synthetic ``unknown-<digest>`` so it can never be mistaken for a real month.

        ``closed`` records whether the month was outside the current one at write
        time, so a human reading the file can see immediately why a month will be
        re-fetched next run.
        """
        month = month if month is not None else (config.archive_month(url) or "")
        month = month or ""
        label = label or month
        if store is not None:
            pgn_dir = store.relative_dir(label)
            game_count = len(store.uuids_on_disk(label))
            recorded = sorted(store.uuids_on_disk(label))
        else:
            pgn_dir = f"pgn/{label}"
            game_count = len(uuids or [])
            recorded = sorted(uuids or [])
        entry = {
            "month": month,
            "closed": bool(month) and month != current_month,
            "game_count": game_count,
            "pgn_dir": pgn_dir,
            "fetched_at": _now(),
            "uuids": recorded,
        }
        self.archives[url] = entry
        return entry

    def reset(self, month: Optional[str] = None) -> int:
        """Drop entries for ``month``, or all of them. Returns how many went."""
        if month is None:
            count = len(self.archives)
            self.archives.clear()
            return count
        doomed = [
            url
            for url, entry in self.archives.items()
            if entry.get("month") == month
        ]
        for url in doomed:
            del self.archives[url]
        return len(doomed)

    # ------------------------------------------------------------------- io

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": VERSION,
            "player": self.player,
            "updated_at": self.updated_at or _now(),
            "archives": self.archives,
        }

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.updated_at = _now()
        payload = json.dumps(self.to_dict(), indent=2, sort_keys=False) + "\n"
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(payload)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, self.path)     # atomic on Windows and POSIX


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _note(message: str) -> None:
    """A degradation notice. stderr, so it survives a redirected stdout."""
    print(f"  note: {message}", file=sys.stderr)


def load(path=None) -> Metadata:
    """Read the metadata file. Missing or corrupt yields an empty instance.

    Both cases degrade in the safe direction: every archive becomes "not up to date"
    and is re-downloaded.
    """
    path = path or config.METADATA
    md = Metadata(path=path)
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return md
    except OSError as exc:
        _note(f"cannot read {path} ({exc}); treating as empty")
        return md

    try:
        data = json.loads(raw)
    except ValueError:
        _note(f"{path} is corrupt; treating as empty and re-downloading")
        return md

    if not isinstance(data, dict):
        _note(f"{path} has an unexpected shape; treating as empty")
        return md

    version = data.get("version")
    if version != VERSION:
        _note(f"{path} is version {version!r}, expected {VERSION}; treating as empty")
        return md

    md.player = data.get("player")
    md.updated_at = data.get("updated_at", "")
    archives = data.get("archives")
    if isinstance(archives, dict):
        md.archives = {k: v for k, v in archives.items() if isinstance(v, dict)}
    return md


def verify(md: Metadata, current_month: str, store: Optional[PgnStore] = None) -> List[str]:
    """Check that every recorded claim still holds. Returns a list of problems.

    This is what turns "we skipped it" from a leap of faith into something auditable:
    it re-derives what is actually on disk and compares it to what was claimed.
    """
    store = store or PgnStore()
    problems: List[str] = []
    if not md.archives:
        return ["metadata is empty; nothing has been recorded yet"]

    for url, entry in sorted(md.archives.items(), key=lambda kv: kv[1].get("month", "")):
        month = entry.get("month") or config.archive_month(url) or "?"
        where = f"{month} ({url})"

        claimed = entry.get("game_count")
        if not isinstance(claimed, int):
            problems.append(f"{where}: game_count missing or not an integer")
            claimed = None

        on_disk = store.uuids_on_disk(month)
        if claimed is not None and len(on_disk) != claimed:
            problems.append(
                f"{where}: metadata claims {claimed} game(s), "
                f"{len(on_disk)} on disk in {store.relative_dir(month)}"
            )

        recorded = set(entry.get("uuids") or [])
        if recorded and recorded - on_disk:
            missing = sorted(recorded - on_disk)
            problems.append(
                f"{where}: {len(missing)} recorded game(s) missing from disk "
                f"(e.g. {missing[0]})"
            )
        if on_disk - recorded and recorded:
            problems.append(
                f"{where}: {len(on_disk - recorded)} game(s) on disk are not in metadata"
            )

        if entry.get("closed") and month == current_month:
            problems.append(
                f"{where}: marked closed but is the current month; it will be re-fetched"
            )
    return problems