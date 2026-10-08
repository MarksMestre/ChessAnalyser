"""Paths, URL shapes and the one helper that gives the skip rule its teeth.

Everything the fetcher writes lives under ``process_api/data/`` so the rest of the
project never has to know about it. ``api.txt`` holds the archive-list URL, one line,
which keeps the username out of the code and out of the command history.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent
API_TXT = ROOT / "api.txt"
DATA_DIR = ROOT / "data"
PGN_DIR = DATA_DIR / "pgn"
METADATA = DATA_DIR / "metadata.json"
LOG = DATA_DIR / "fetch.log"

# Chess.com's API rejects requests without a User-Agent and has been known to hand out
# 403/429 to generic bot strings, so it stays plain and honest rather than pretending
# to be a browser.
USER_AGENT = "chess-coach/1.0 (personal game archive importer)"

# The archive endpoints dislike concurrent requests; a serialised 1 s gap keeps a
# 49-month sweep well inside the polite-use envelope.
DEFAULT_DELAY = 1.0
DEFAULT_TIMEOUT = 30
DEFAULT_RETRIES = 4

CHESSCOM_ARCHIVES = "https://api.chess.com/pub/player/{player}/games/archives"
CHESSCOM_GAME = "https://api.chess.com/pub/player/{player}/games/{game_id}"

ARCHIVE_MONTH_RE = re.compile(r"/games/(\d{4})/(\d{2})/?$")
PLAYER_RE = re.compile(r"/pub/player/([^/]+)/games(?:/|$)")
UUID_SAFE_RE = re.compile(r"[^0-9A-Za-z-]")


def archive_month(url: str) -> Optional[str]:
    """``.../games/2026/10`` -> ``2026-10``, or ``None`` if it is not that shape.

    ``None`` means the caller must not assume the archive is complete, so an
    unrecognised URL is always fetched.
    """
    match = ARCHIVE_MONTH_RE.search(url or "")
    if not match:
        return None
    year, month = int(match.group(1)), int(match.group(2))
    if not 1 <= month <= 12:
        return None
    return f"{year:04d}-{month:02d}"


def player_from_url(url: str) -> Optional[str]:
    """Pull the username out of an archive URL, for logging and metadata."""
    match = PLAYER_RE.search(url or "")
    return match.group(1) if match else None


def current_month(today=None) -> str:
    """The ``YYYY-MM`` being written to right now."""
    if today is None:
        from datetime import date

        today = date.today()
    return today.strftime("%Y-%m")


def read_api_url() -> Optional[str]:
    """First non-empty line of ``api.txt``, or ``None`` if it is missing/unusable."""
    try:
        text = API_TXT.read_text(encoding="utf-8")
    except OSError:
        return None
    for line in text.splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            return line
    return None


def archive_list_url(player: Optional[str]) -> Optional[str]:
    """An explicit ``--player`` overrides ``api.txt``; otherwise the file is used."""
    if player:
        return CHESSCOM_ARCHIVES.format(player=player)
    return read_api_url()


def safe_uuid(uuid: str) -> str:
    """A uuid made safe to use as a filename, so a weird id cannot escape data/."""
    return UUID_SAFE_RE.sub("_", uuid or "")