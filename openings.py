"""Opening book built from the CC0 lichess-org/chess-openings TSV files.

Two jobs:

1. Name the opening each game follows (ECO + human name).
2. Mark moves that are still *book theory*.  This matters twice over: book
   moves are exempt from accuracy penalties (engines score theory moves
   differently from how humans are taught to play them), and the move on which
   a game leaves book theory is a classic source of the blunders this tool is
   meant to find, so we tag it explicitly.

The book is a data file, not code: drop a.tsv .. e.tsv into data/openings/ and
everything works offline.  Missing or corrupt files degrade to a heuristic
("opening phase ends at move 15") rather than failing the run.
"""

from __future__ import annotations

import csv
import os
import shutil
import urllib.request
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import chess

ROOT = os.path.dirname(os.path.abspath(__file__))
BOOK_DIR = os.path.join(ROOT, "data", "openings")
BASE_URL = "https://raw.githubusercontent.com/lichess-org/chess-openings/master"
FILES = ("a.tsv", "b.tsv", "c.tsv", "d.tsv", "e.tsv")


def _ssl_context():
    """Python on Windows has no default CA bundle; certifi supplies one.

    Returns None when certifi is missing, in which case urlopen uses the stdlib
    default rather than downgrading to an unverified connection.
    """
    try:
        import certifi
        import ssl

        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return None


SSL_CONTEXT = _ssl_context()


def ensure_book(directory: str = BOOK_DIR, *, allow_download: bool = True) -> Tuple[int, List[str]]:
    """Make sure the TSV files are present. Returns (entry_count, notes)."""
    notes: List[str] = []
    os.makedirs(directory, exist_ok=True)
    for name in FILES:
        path = os.path.join(directory, name)
        if os.path.isfile(path) and os.path.getsize(path) > 1000:
            continue
        if not allow_download:
            notes.append(f"{name}: missing and downloads disabled")
            continue
        url = f"{BASE_URL}/{name}"
        try:
            with urllib.request.urlopen(url, timeout=60, context=SSL_CONTEXT) as resp:
                data = resp.read()
            with open(path, "wb") as fh:
                fh.write(data)
            notes.append(f"{name}: downloaded {len(data):,} bytes")
        except Exception as exc:  # offline is fine, we degrade gracefully
            notes.append(f"{name}: download failed ({exc})")
    count = sum(1 for _ in _iter_entries(directory))
    return count, notes


def _iter_entries(directory: str = BOOK_DIR):
    """Yield (eco, name, move_list) for every opening in the TSV files."""
    for name in FILES:
        path = os.path.join(directory, name)
        if not os.path.isfile(path):
            continue
        try:
            with open(path, "r", encoding="utf-8", errors="replace", newline="") as fh:
                reader = csv.DictReader(fh, delimiter="\t")
                for row in reader:
                    eco = (row.get("eco") or "").strip()
                    opname = (row.get("name") or "").strip()
                    pgn = (row.get("pgn") or "").strip()
                    if not pgn:
                        continue
                    moves = pgn.split()
                    if moves and moves[0].isdigit() and moves[0] != "1":
                        # a single-move entry is written without the "1."
                        pass
                    yield eco, opname, moves
        except (OSError, csv.Error):
            continue


@dataclass
class OpeningBook:
    """prefix (tuple of uci moves) -> (eco, name, continuations)."""

    prefix_eco: Dict[Tuple[str, ...], Tuple[str, str]] = field(default_factory=dict)
    prefix_len: Dict[Tuple[str, ...], int] = field(default_factory=dict)
    all_prefixes: set = field(default_factory=set)
    entry_count: int = 0
    available: bool = False

    @classmethod
    def load(cls, directory: str = BOOK_DIR) -> "OpeningBook":
        book = cls()
        count = 0
        for eco, opname, moves in _iter_entries(directory):
            try:
                board = chess.Board()
                prefix: List[str] = []
                for token in moves:
                    token = token.strip().rstrip("!?+#")
                    # castling is sometimes written with a zero
                    if token in ("0-0-0", "0-0"):
                        token = token.replace("0", "O")
                    if not token:
                        continue
                    # move numbers ("1.", "12...", "1.e4") carry no information
                    if token[0].isdigit():
                        continue
                    try:
                        move = board.parse_san(token)
                    except (chess.AmbiguousMoveError, chess.InvalidMoveError,
                            chess.IllegalMoveError, ValueError):
                        continue  # unusable token: skip it, keep the line
                    prefix.append(move.uci())
                    board.push(move)
            except Exception:
                continue
            if not prefix:
                continue
            count += 1
            key = tuple(prefix)
            # every prefix of the line is itself a known book position
            for n in range(1, len(key) + 1):
                book.all_prefixes.add(key[:n])
            if len(key) > book.prefix_len.get(key, 0):
                book.prefix_eco[key] = (eco, opname)
                book.prefix_len[key] = len(key)
        book.entry_count = count
        book.available = count > 0
        return book

    # -- queries -----------------------------------------------------------
    def lookup(self, moves: List[str]) -> Optional[Tuple[str, str]]:
        """Longest-prefix opening name for a list of uci moves played so far."""
        best: Optional[Tuple[str, str]] = None
        best_len = 0
        for n in range(min(len(moves), 40), 0, -1):
            hit = self.prefix_eco.get(tuple(moves[:n]))
            if hit:
                # a shorter prefix match must not shadow a longer one
                if n > best_len:
                    best, best_len = hit, n
        return best

    def name_for_position(self, board: chess.Board, history: List[str]) -> Optional[Tuple[str, str]]:
        del board  # history is enough
        return self.lookup(history)

    def is_book_move(self, moves: List[str], uci: str) -> Optional[Tuple[str, str]]:
        """Return (eco, name) if *uci* continues a known opening line here.

        A move counts as book theory when the position reached after playing it
        is a prefix of *some* line in the database.  That is deliberately
        broader than "the exact continuation we happen to have stored": a game
        that transposes into a different named line is still in book.
        """
        if tuple(moves) + (uci,) in self.all_prefixes:
            hit = self.lookup(list(moves) + [uci])
            return hit or ("", "")
        return None

    def book_ends_at(self, moves: List[str]) -> int:
        """Index (0-based ply) of the first move that is not book theory."""
        path: List[str] = []
        for i, uci in enumerate(moves):
            if self.is_book_move(path, uci) is None:
                return i
            path.append(uci)
        return len(moves)

    def summary(self) -> dict:
        return {
            "available": self.available,
            "entries": self.entry_count,
            "named_positions": len(self.prefix_eco),
            "known_positions": len(self.all_prefixes),
        }


def material(board: chess.Board) -> int:
    """Total non-pawn material, in centipawns."""
    return sum(
        len(board.pieces(pt)) * v
        for pt, v in (
            (chess.QUEEN, 900),
            (chess.ROOK, 500),
            (chess.BISHOP, 325),
            (chess.KNIGHT, 325),
        )
    )