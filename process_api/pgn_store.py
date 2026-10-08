"""On-disk PGN layout: one file per game, grouped into a directory per month.

    data/pgn/2026-10/6f1c9d2e-....pgn

Per game rather than per month, because the open month is appended to on every run:

* "is this game already downloaded" becomes an existence check on the uuid, not a
  content index — so re-fetching the current month cannot duplicate anything;
* a run killed mid-write loses at most the one file being written, since each write is
  ``tmp`` + ``os.replace``;
* a month directory is a clean unit to hand to ``analyze.py`` later.

The cost is inodes rather than one growing file, which is a fair trade for correctness.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set

from . import config

# Chess.com PGN tags that break downstream parsers or that we simply do not need.
_CURRENT_POSITION_RE = re.compile(r'\[CurrentPosition\s+"[\s\S]*?"\]\s*')
_CLOCK_EVAL_RE = re.compile(r"\{\s*\[[^\]]*\][^}]*\}")     # {[%clk 0:59:56.7]}
_EMPTY_BRACE_RE = re.compile(r"\{\s*\}")
_TRAILING_WS_RE = re.compile(r"[ \t]+\n")
_BLANK_LINES_RE = re.compile(r"\n{3,}")
_EVENT_RE = re.compile(r"^\[Event\s", flags=re.MULTILINE)
_REPEATED_SPACES_RE = re.compile(r"[ ]{2,}")


def _tidy_movetext(text: str) -> str:
    """Collapse runs of spaces left behind by comment removal.

    Only movetext lines are touched: a tag value is quoted data, so squeezing its
    spaces would be editing the record rather than tidying formatting.
    """
    lines = []
    for line in text.split("\n"):
        if line.startswith("["):
            lines.append(line)
        else:
            lines.append(_REPEATED_SPACES_RE.sub(" ", line).rstrip())
    return "\n".join(lines)


def normalise_pgn(text: str) -> str:
    """Turn Chess.com PGN into strict PGN.

    ``[CurrentPosition]`` is dropped because Chess.com embeds a literal newline in it,
    which python-chess refuses to parse. ``{[%clk ...]}`` and ``{[%eval ...]}`` are
    stripped for the same reason ``fetch_games.py`` strips them.
    """
    text = _CURRENT_POSITION_RE.sub("", text)
    text = _CLOCK_EVAL_RE.sub("", text)
    text = _EMPTY_BRACE_RE.sub("", text)
    text = _TRAILING_WS_RE.sub("\n", text)
    text = _BLANK_LINES_RE.sub("\n\n", text)
    return _tidy_movetext(text).strip()


def pgn_count(text: str) -> int:
    return len(_EVENT_RE.findall(text))


class PgnStore:
    """Reads and writes ``data/pgn/<month>/<uuid>.pgn``."""

    def __init__(self, root=None) -> None:
        self.root = Path(root) if root else config.PGN_DIR

    # ------------------------------------------------------------------ paths

    def month_dir(self, month: str) -> Path:
        return self.root / month

    def relative_dir(self, month: str) -> str:
        """The month directory as stored in metadata, relative to ``data/``."""
        return f"pgn/{month}"

    def path_for(self, month: str, uuid: str) -> Path:
        return self.month_dir(month) / f"{config.safe_uuid(uuid)}.pgn"

    # ------------------------------------------------------------------ reads

    def uuids_on_disk(self, month: str) -> Set[str]:
        """Every game already stored for ``month``, from the filenames."""
        directory = self.month_dir(month)
        if not directory.is_dir():
            return set()
        return {p.stem for p in directory.glob("*.pgn")}

    def exists(self, month: str, uuid: str) -> bool:
        return self.path_for(month, uuid).is_file()

    def count_games(self, month: str) -> int:
        """Number of ``[Event`` headers across a month, used by ``--verify``."""
        directory = self.month_dir(month)
        if not directory.is_dir():
            return 0
        total = 0
        for path in directory.glob("*.pgn"):
            try:
                total += pgn_count(path.read_text(encoding="utf-8", errors="replace"))
            except OSError:
                continue
        return total

    def total_games(self) -> int:
        if not self.root.is_dir():
            return 0
        return sum(1 for _ in self.root.glob("*/*.pgn"))

    def read(self, month: str, uuid: str) -> Optional[str]:
        path = self.path_for(month, uuid)
        try:
            return path.read_text(encoding="utf-8")
        except OSError:
            return None

    # ----------------------------------------------------------------- writes

    def write_game(self, month: str, uuid: str, pgn: str) -> bool:
        """Write one game atomically. Returns ``False`` if there was no PGN."""
        text = normalise_pgn(pgn or "")
        if not text:
            return False
        directory = self.month_dir(month)
        directory.mkdir(parents=True, exist_ok=True)
        target = self.path_for(month, uuid)
        tmp = target.with_suffix(".pgn.tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, target)
        return True

    def write_month(
        self, month: str, games: Iterable[Dict[str, Any]], *, merge: bool = True
    ) -> int:
        """Store a month's games, skipping any already on disk when ``merge``.

        Returns how many files were written. ``merge=False`` overwrites existing games,
        which is what ``--force`` on a closed month wants: the source may have been
        corrected and we would rather replace than keep stale text.
        """
        written = 0
        for game in games:
            uuid = (game.get("uuid") or "").strip()
            pgn = game.get("pgn") or ""
            if not uuid:
                continue
            if merge and self.exists(month, uuid):
                continue
            if self.write_game(month, uuid, pgn):
                written += 1
        return written

    def remove_month(self, month: str) -> int:
        directory = self.month_dir(month)
        if not directory.is_dir():
            return 0
        count = sum(1 for _ in directory.glob("*.pgn"))
        import shutil

        shutil.rmtree(directory, ignore_errors=True)
        return count

    def months(self) -> List[str]:
        if not self.root.is_dir():
            return []
        return sorted(p.name for p in self.root.iterdir() if p.is_dir())