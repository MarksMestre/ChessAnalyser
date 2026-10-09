"""PGN -> labelled moves, per-move accuracy, and a JSON report.

The labelling model follows the plan:

    For each ply, with MultiPV=2 so we can see the runner-up line:

        evalBefore (side to move) ---> best line 1  E1
         \\--> best line 2  E2
        play your move        ---> evalAfter, flipped to your perspective

        loss_pp = winProb(before) - winProb(after)     # Lichess sigmoid

Two passes over the engine:

    pass 1  survey  depth 14, every ply of every game      (~15-25 s/game)
    pass 2  focus   depth 22-24, only the plies that decide the report

Pass 2 is where false brilliant labels get caught: a shallow search calls
plenty of ordinary moves brilliant because it cannot see the refutation.

Efficiency note: every position in the game is searched exactly once.  The
"after" evaluation of ply i is the "before" evaluation of ply i+1, which is why
this costs len(moves)+1 engine calls per game rather than 2*len(moves).
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import sys
import time
from dataclasses import asdict, dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

import chess
import chess.pgn

import engines
import labels
import openings
import player
import scoring
from engines import accuracy_from_loss, win_percent
from labels import LABEL_ORDER, Label, classify, label_glyph

ROOT = os.path.dirname(os.path.abspath(__file__))

PIECE_VALUE = {
    chess.PAWN: 100,
    chess.KNIGHT: 320,
    chess.BISHOP: 330,
    chess.ROOK: 500,
    chess.QUEEN: 900,
    chess.KING: 0,
}

ENDGAME_MATERIAL = 2600  # total non-pawn material of both sides, centipawns
NO_BOOK_OPENING_PLY = 30  # fallback when there is no opening book
MATE_CP = 10000          # how a forced mate is drawn on the eval chart


# --------------------------------------------------------------------------
# position helpers
# --------------------------------------------------------------------------

def material_balance(board: chess.Board, color: chess.Color) -> int:
    """Material advantage for *color*, in centipawns."""
    total = 0
    for piece_type, value in PIECE_VALUE.items():
        total += value * len(board.pieces(piece_type, color))
        total -= value * len(board.pieces(piece_type, not color))
    return total


def non_pawn_material(board: chess.Board) -> int:
    """Material of both sides, pawns excluded."""
    return sum(
        PIECE_VALUE[pt] * len(board.pieces(pt, chess.WHITE))
        + PIECE_VALUE[pt] * len(board.pieces(pt, chess.BLACK))
        for pt in (chess.KNIGHT, chess.BISHOP, chess.ROOK, chess.QUEEN)
    )


def phase_of(board: chess.Board, book_end_ply: int, ply: int) -> str:
    """opening / middlegame / endgame for the position before ply *ply*.

    Without a book the opening is capped at NO_BOOK_OPENING_PLY so that a
    transposition out of book theory still ends the opening phase.
    """
    limit = book_end_ply if book_end_ply > 0 else NO_BOOK_OPENING_PLY
    if ply < limit:
        return "opening"
    if non_pawn_material(board) <= ENDGAME_MATERIAL:
        return "endgame"
    return "middlegame"


def san_pv(board: chess.Board, uci_pv: Sequence[str], limit: int = 8) -> List[str]:
    """Render a UCI pv as SAN, stopping if the pv leaves the board."""
    out: List[str] = []
    b = board.copy(stack=False)
    for uci in uci_pv[:limit]:
        try:
            move = b.parse_uci(uci)
        except (chess.InvalidMoveError, ValueError):
            break
        out.append(b.san(move))
        b.push(move)
    return out


# --------------------------------------------------------------------------
# records
# --------------------------------------------------------------------------

@dataclass
class MoveRecord:
    ply: int
    move_number: int
    color: str
    san: str
    uci: str
    fen: str
    fen_after: str = ""
    is_players_turn: bool = True
    phase: str = "middlegame"

    # evaluation, always from the mover's point of view
    eval_before: Optional[float] = None
    eval_after: Optional[float] = None
    win_percent_before: Optional[float] = None
    win_percent_after: Optional[float] = None
    loss_pp: float = 0.0
    accuracy: float = 100.0

    label: str = Label.BEST
    glyph: str = ""

    best_san: Optional[str] = None
    best_uci: Optional[str] = None
    best_pv: List[str] = field(default_factory=list)
    best_eval: Optional[float] = None
    second_san: Optional[str] = None
    second_uci: Optional[str] = None
    second_eval: Optional[float] = None
    gap_pp: Optional[float] = None   # E1 - E2 in win percent: how unique the best move was

    in_book: bool = False
    left_book: bool = False

    # "uci:san" for every legal move, on the player's own plies only.  Drill
    # mode needs these to let you actually choose a move; opponent plies keep
    # an empty list so the report stays small.
    legal: List[str] = field(default_factory=list)

    # Material, in pawns, given up by this move against the opponent's best
    # reply. Soundness of the sacrifice is not stored separately: it is implied
    # by loss_pp staying under BRILLIANT_MAX_LOSS, which is the same quantity
    # labels.classify() tests.
    sacrifice: Optional[float] = None

    depth: int = 0
    verified: bool = False
    survey_label: Optional[str] = None

    lc0_best_uci: Optional[str] = None
    lc0_best_san: Optional[str] = None
    lc0_eval: Optional[float] = None
    lc0_agrees: Optional[bool] = None
    lc0_loss_pp: Optional[float] = None

    notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class GameResult:
    headers: Dict[str, str]
    index: int
    player_color: Optional[chess.Color] = None
    player_name: str = ""
    moves: List[MoveRecord] = field(default_factory=list)
    opening: Optional[str] = None
    eco: Optional[str] = None
    book_end_ply: int = 0

    accuracy: float = 0.0
    accuracy_harmonic: float = 0.0
    accuracy_mean: float = 0.0
    acpl: float = 0.0
    phase_accuracy: Dict[str, Dict[str, float]] = field(default_factory=dict)
    eval_curve: List[float] = field(default_factory=list)
    counts: Dict[str, int] = field(default_factory=dict)
    result: str = "*"
    player_result: str = "*"
    analysis_seconds: float = 0.0

    def to_dict(self) -> Dict:
        d = asdict(self)
        d["player_color"] = (
            "white" if self.player_color is True
            else "black" if self.player_color is False
            else None
        )
        return d


# --------------------------------------------------------------------------
# aggregation
# --------------------------------------------------------------------------

def harmonic_mean(values: Sequence[float]) -> float:
    vals = [v for v in values if v > 0]
    return len(vals) / sum(1.0 / v for v in vals) if vals else 0.0


def aggregate(records: List[MoveRecord]) -> Dict[str, float]:
    """Game accuracy, Lichess style.

    Each move's win percentage is weighted by the evaluation *volatility*
    around it, so a quiet, stable move counts for little and the moments where
    the game swings carry the score.
    """
    if not records:
        return {"accuracy": 0.0, "accuracy_harmonic": 0.0, "accuracy_mean": 0.0, "acpl": 0.0}

    wps = [r.win_percent_before or 0.0 for r in records]
    losses = [r.loss_pp for r in records]

    volatilities: List[float] = []
    for i, rec in enumerate(records):
        if i == 0:
            v = abs((rec.win_percent_after or 0.0) - wps[0])
        elif i == len(records) - 1:
            v = abs(wps[-1] - (rec.win_percent_after or 0.0))
        else:
            v = abs(wps[i + 1] - wps[i - 1])
        volatilities.append(v)

    total_vol = sum(volatilities)
    if total_vol > 0:
        weighted = sum(v * wp for v, wp in zip(volatilities, wps)) / total_vol
    else:
        weighted = sum(wps) / len(wps)

    return {
        "accuracy": round(weighted, 2),
        "accuracy_harmonic": round(harmonic_mean(wps), 2),
        "accuracy_mean": round(sum(wps) / len(wps), 2),
        "acpl": round(sum(losses) / len(losses), 2),
    }


def phase_rollup(records: List[MoveRecord]) -> Dict[str, Dict[str, float]]:
    out: Dict[str, Dict[str, float]] = {}
    for phase in ("opening", "middlegame", "endgame"):
        sel = [r for r in records if r.phase == phase]
        if not sel:
            continue
        losses = [r.loss_pp for r in sel]
        wps = [r.win_percent_before or 0.0 for r in sel]
        out[phase] = {
            "moves": len(sel),
            "accuracy": round(sum(wps) / len(wps), 2),
            "acpl": round(sum(losses) / len(losses), 2),
            **{lab: sum(1 for r in sel if r.label == lab) for lab in LABEL_ORDER},
        }
    return out


# --------------------------------------------------------------------------
# sacrifice detection (drives the brilliant label)
# --------------------------------------------------------------------------

def detect_sacrifice(
    before: chess.Board, move: chess.Move, best_reply: Optional[chess.Move],
    player: chess.Color,
) -> float:
    """Material, in pawns, that *move* gives up once the refutation is played.

    Positive means the player handed material over.  The opponent's best reply
    is used, not the opponent's worst one, so a sacrifice only counts as a
    sacrifice if it really does cost something against best defence.
    """
    bal_before = material_balance(before, player)
    after = before.copy(stack=False)
    after.push(move)
    if best_reply is not None and best_reply in after.legal_moves:
        after.push(best_reply)
    return (material_balance(after, player) - bal_before) / -100.0


def is_forced_move(board: chess.Board) -> bool:
    """True when the player had essentially no choice (in check, or one move)."""
    return board.is_check() or board.legal_moves.count() <= 1


def first_line_move(lines: List[engines.Line], board: chess.Board) -> Optional[chess.Move]:
    if not lines or not lines[0].uci:
        return None
    try:
        return board.parse_uci(lines[0].uci)
    except (chess.InvalidMoveError, ValueError):
        return None


# --------------------------------------------------------------------------
# the analyser
# --------------------------------------------------------------------------

class Analyser:
    def __init__(
        self,
        sf: engines.Engine,
        *,
        depth: int = 14,
        focus_depth: int = 24,
        book: Optional[openings.OpeningBook] = None,
        lc0: Optional[engines.Engine] = None,
        lc0_nodes: int = 3000,
        lc0_max_moves: int = 12,
        survey_movetime: float = 2.0,
        focus_movetime: float = 6.0,
        verbose: bool = True,
    ) -> None:
        self.sf = sf
        self.depth = depth
        self.focus_depth = focus_depth
        self.book = book if book is not None else openings.OpeningBook.load()
        self.lc0 = lc0
        self.lc0_nodes = lc0_nodes
        self.lc0_max_moves = lc0_max_moves
        self.survey_movetime = survey_movetime
        self.focus_movetime = focus_movetime
        self.verbose = verbose

    # ------------------------------------------------------------------
    def analyse_game(self, game: chess.pgn.Game, *, player_name: str, index: int) -> GameResult:
        started = time.time()
        headers = dict(game.headers)
        player_color = resolve_player_color(headers, player_name)

        result = GameResult(
            headers=headers,
            index=index,
            player_color=player_color,
            player_name=player_name,
            result=headers.get("Result", "*"),
        )
        if player_color is None:
            result.player_result = result.result
            return result

        moves = list(game.mainline_moves())
        boards = board_stack(moves)

        records = self._build_records(boards, moves, player_color)
        result.book_end_ply = next(
            (r.ply for r in records if r.left_book), len(records)
        )
        opening = self._opening
        if opening:
            result.eco, result.opening = opening[0], opening[1]

        lines = self._search_game(boards)
        self._score(records, boards, moves, lines, player_color)

        focus = focus_indices(records)
        if focus:
            if self.verbose:
                print(f"    pass 2: {len(focus)} decisive moves at depth {self.focus_depth}", flush=True)
            self._deep_verify(records, boards, moves, focus)

        if self.lc0 is not None:
            self._lc0_crosscheck(records, boards, moves)

        result.moves = records
        result.player_result = player_result(result.result, player_color)
        agg = aggregate(records)
        result.accuracy = agg["accuracy"]
        result.accuracy_harmonic = agg["accuracy_harmonic"]
        result.accuracy_mean = agg["accuracy_mean"]
        result.acpl = agg["acpl"]
        result.phase_accuracy = phase_rollup(records)
        result.counts = {lab: sum(1 for r in records if r.label == lab) for lab in LABEL_ORDER}
        result.eval_curve = eval_curve(records)
        result.analysis_seconds = round(time.time() - started, 2)
        return result

    # ------------------------------------------------------------------
    def _build_records(
        self, boards: List[chess.Board], moves: List[chess.Move], player_color: chess.Color
    ) -> List[MoveRecord]:
        """Walk the moves once, recording SAN, book state and the phase."""
        history: List[str] = []
        records: List[MoveRecord] = []

        for ply, move in enumerate(moves):
            board = boards[ply]
            in_book = False
            if self.book.available:
                in_book = self.book.is_book_move(history, move.uci()) is not None

            rec = MoveRecord(
                ply=ply,
                move_number=board.fullmove_number,
                color="white" if board.turn == chess.WHITE else "black",
                san=board.san(move),
                uci=move.uci(),
                fen=board.fen(en_passant="fen"),
                fen_after=boards[ply + 1].fen(en_passant="fen"),
                is_players_turn=(board.turn == player_color),
                in_book=in_book,
            )
            records.append(rec)
            history.append(move.uci())

        # the first move that is not book theory closes the opening phase
        for rec in records:
            if not rec.in_book:
                rec.left_book = True
                break
        book_end = next((r.ply for r in records if r.left_book), len(records))
        for rec in records:
            rec.phase = phase_of(boards[rec.ply], book_end, rec.ply)
            if rec.is_players_turn:
                # drill mode offers the real legal moves, not just the played one
                rec.legal = [
                    f"{m.uci()}:{boards[rec.ply].san(m)}"
                    for m in boards[rec.ply].legal_moves
                ]

        self._opening = self._deepest_name(moves)
        return records

    def _deepest_name(self, moves: List[chess.Move]) -> Optional[Tuple[str, str]]:
        """The most specific opening the game reached.

        A game often leaves the named lines partway through (Morphy's Opera Game
        follows 4.dxe5, which the lichess TSV does not contain).  Naming the game
        after the *last* position the book recognises keeps "Philidor Defense"
        instead of drifting back to "King's Pawn Opening".
        """
        if not self.book.available:
            return None
        history: List[str] = []
        best: Optional[Tuple[str, str]] = None
        best_depth = -1
        for move in moves:
            history.append(move.uci())
            hit = self.book.lookup(history)
            if hit and len(history) > best_depth:
                best, best_depth = hit, len(history)
        return best

    def _search_game(self, boards: List[chess.Board]) -> List[List[engines.Line]]:
        """One MultiPV=2 search per position, including the final one.

        The survey pass uses a generous per-position cap: it must finish, and a
        depth-limited search that stops early still reports the depth it reached.
        """
        lines: List[List[engines.Line]] = []
        saved = self.sf.max_movetime
        self.sf.max_movetime = self.survey_movetime
        try:
            for i, board in enumerate(boards):
                if self.verbose and i and i % 40 == 0:
                    print(f"    ply {i}/{len(boards) - 1}", flush=True)
                lines.append(self.sf.analyse(board, depth=self.depth, multipv=2))
        finally:
            self.sf.max_movetime = saved
        return lines

    # ------------------------------------------------------------------
    def _score(
        self,
        records: List[MoveRecord],
        boards: List[chess.Board],
        moves: List[chess.Move],
        lines: List[List[engines.Line]],
        player_color: chess.Color,
    ) -> None:
        for i, rec in enumerate(records):
            before, after = lines[i], lines[i + 1]

            # Scoring and labelling live in scoring.py so the frontend server
            # rates a move played on the board exactly the way this does.
            score = scoring.score_move(
                boards[i], rec.uci, before=before, after=after, depth=self.depth
            )
            rec.eval_before = score.eval_before
            rec.eval_after = score.eval_after
            rec.win_percent_before = score.win_percent_before
            rec.win_percent_after = score.win_percent_after
            rec.loss_pp = score.loss_pp
            rec.accuracy = score.accuracy
            rec.best_uci, rec.best_san = score.best_uci, score.best_san
            rec.best_pv = score.best_pv
            rec.best_eval = score.best_eval
            rec.depth = score.best_depth
            rec.second_uci, rec.second_san = score.second_uci, score.second_san
            rec.second_eval = score.second_eval
            rec.gap_pp = score.gap_pp

            if not rec.is_players_turn:
                rec.label, rec.glyph = Label.BEST, ""
                continue

            given = detect_sacrifice(
                boards[i], moves[i], first_line_move(after, boards[i + 1]), player_color
            )
            if given >= 1.0:
                rec.sacrifice = round(given, 2)

            rec.label = scoring.label_move(
                score,
                uci=rec.uci,
                in_book=rec.in_book,
                forced=is_forced_move(boards[i]),
                sacrifice=rec.sacrifice,
            )
            rec.glyph = score.glyph

    # ------------------------------------------------------------------
    def _deep_verify(
        self,
        records: List[MoveRecord],
        boards: List[chess.Board],
        moves: List[chess.Move],
        focus: List[int],
    ) -> None:
        """Re-score only the plies that decide the report, at focus depth."""
        saved = self.sf.max_movetime
        self.sf.max_movetime = self.focus_movetime
        try:
            self._deep_verify_inner(records, boards, moves, focus)
        finally:
            self.sf.max_movetime = saved

    def _deep_verify_inner(
        self,
        records: List[MoveRecord],
        boards: List[chess.Board],
        moves: List[chess.Move],
        focus: List[int],
    ) -> None:
        for i in focus:
            rec = records[i]
            rec.survey_label = rec.label

            before = self.sf.analyse(boards[i], depth=self.focus_depth, multipv=2)
            after = self.sf.analyse(boards[i + 1], depth=self.focus_depth, multipv=2)
            if not before:
                continue

            eval_before = before[0].score_cp
            eval_after = -after[0].score_cp if after else -eval_before
            rec.eval_before = eval_before
            rec.eval_after = eval_after
            rec.win_percent_before = win_percent(eval_before)
            rec.win_percent_after = win_percent(eval_after)
            rec.loss_pp = max(0.0, rec.win_percent_before - rec.win_percent_after)
            rec.accuracy = round(accuracy_from_loss(rec.loss_pp), 2)
            rec.depth = before[0].depth or self.focus_depth
            rec.verified = True

            best = before[0]
            rec.best_uci, rec.best_san = best.uci, best.san
            rec.best_pv = san_pv(boards[i], best.pv)
            rec.best_eval = best.score_cp
            rec.gap_pp = None
            if len(before) > 1:
                rec.second_uci, rec.second_san = before[1].uci, before[1].san
                rec.second_eval = before[1].score_cp
                rec.gap_pp = round(
                    win_percent(best.score_cp) - win_percent(before[1].score_cp), 2
                )

            if not rec.is_players_turn:
                continue  # only the player's own moves are ever labelled

            player_color = chess.WHITE if rec.color == "white" else chess.BLACK
            given = detect_sacrifice(
                boards[i], moves[i], first_line_move(after, boards[i + 1]), player_color
            )
            rec.sacrifice = round(given, 2) if given >= 1.0 else None
            label = classify(rec, in_book=rec.in_book, forced=is_forced_move(boards[i]))
            rec.label, rec.glyph = label, label_glyph(label)
            if rec.survey_label and rec.survey_label != label:
                rec.notes.append(f"pass 2 revised: {rec.survey_label} -> {label}")

    # ------------------------------------------------------------------
    def _lc0_crosscheck(
        self, records: List[MoveRecord], boards: List[chess.Board], moves: List[chess.Move]
    ) -> None:
        """Second opinion on the moves Stockfish disagreed with.

        Lc0 learned chess from self-play and carries no human bias, so it will
        happily endorse a creative sacrifice that a classical engine scores as
        slightly worse.  "Lc0 agreed with you, Stockfish did not" is the one
        brilliant-move signal a single Stockfish cannot produce.
        """
        if self.lc0 is None:
            return
        candidates = [
            i for i, rec in enumerate(records)
            if rec.is_players_turn and rec.best_uci and rec.best_uci != rec.uci
        ]
        if not candidates:
            return
        # most instructive first: the largest disagreements, then the moves
        # where Lc0 has the best chance of overriding a blunder call
        candidates.sort(key=lambda i: -records[i].loss_pp)
        candidates = candidates[: self.lc0_max_moves]
        if self.verbose:
            print(f"    Lc0 cross-check on {len(candidates)} moves", flush=True)

        for n, i in enumerate(candidates, start=1):
            rec = records[i]
            if self.verbose and n % 5 == 0:
                print(f"      Lc0 {n}/{len(candidates)}", flush=True)
            try:
                lines = self.lc0.analyse(boards[i], nodes=self.lc0_nodes, multipv=1)
                if not lines:
                    continue
                line = lines[0]
                rec.lc0_best_uci, rec.lc0_best_san = line.uci, line.san
                rec.lc0_eval = line.score_cp
                rec.lc0_agrees = line.uci == rec.uci
                # half the budget for the refutation: we only need to know
                # whether Lc0 also thinks the move costs something
                reply = self.lc0.analyse(
                    boards[i + 1], nodes=max(1200, self.lc0_nodes // 2), multipv=1
                )
                if reply:
                    rec.lc0_loss_pp = round(
                        max(0.0, win_percent(line.score_cp) - win_percent(-reply[0].score_cp)), 2
                    )
                if rec.lc0_agrees and rec.loss_pp > 2:
                    rec.notes.append("Lc0 agrees with this move where Stockfish did not")
            except Exception as exc:  # never let the cross-check kill the run
                if self.verbose:
                    print(f"      Lc0 failed on ply {i}: {exc}", file=sys.stderr)


# --------------------------------------------------------------------------
# free functions
# --------------------------------------------------------------------------

def board_stack(moves: Sequence[chess.Move]) -> List[chess.Board]:
    """boards[i] is the position before moves[i]; the last entry is the final position."""
    out: List[chess.Board] = []
    board = chess.Board()
    out.append(board.copy(stack=False))
    for move in moves:
        board.push(move)
        out.append(board.copy(stack=False))
    return out


def focus_indices(records: List[MoveRecord]) -> List[int]:
    """Plies worth a deeper second look, plus the position after each."""
    targets: List[int] = []
    for i, rec in enumerate(records):
        if not rec.is_players_turn:
            continue
        decisive = (
            rec.label in (Label.BLUNDER, Label.MISTAKE, Label.MISS, Label.INACCURACY)
            or rec.sacrifice is not None
            or (rec.loss_pp <= 3 and (rec.gap_pp or 0.0) >= 10)
        )
        if decisive:
            targets.extend((i, i + 1))
    return sorted(set(t for t in targets if t < len(records)))


def eval_curve(records: List[MoveRecord]) -> List[float]:
    """Evaluation after each ply, from White's point of view.

    Mate scores are clamped to +/-MATE_CP.  A literal 100000 would dominate any
    auto-scaled chart and flatten the rest of the game into a straight line; the
    move table still shows the true ``#1``.
    """
    out: List[float] = []
    for rec in records:
        if rec.eval_after is None:
            continue
        v = rec.eval_after if rec.color == "white" else -rec.eval_after
        out.append(round(max(-MATE_CP, min(MATE_CP, v)), 1))
    return out


def resolve_player_color(headers: Dict[str, str], player: str) -> Optional[chess.Color]:
    p = (player or "").strip().lower()
    for color, key in ((chess.WHITE, "White"), (chess.BLACK, "Black")):
        name = (headers.get(key) or "").strip().lower()
        if p and name and (p == name or p in name):
            return color
    return None


# --------------------------------------------------------------------------
# who the player is, per site
# --------------------------------------------------------------------------

#: How each platform's ``Site`` header is shown in the report. Keyed by the
#: substring to look for, because neither platform is consistent about the rest
#: of the header: Chess.com writes "Chess.com", lichess writes "LICHESS.ORG", and
#: older archives carry "https://www.lichess.org/".
SITE_LABELS: Tuple[Tuple[str, str], ...] = (
    ("chess.com", "Chess.com"),
    ("chesscom", "Chess.com"),
    ("lichess", "LICHESS.ORG"),
)

#: The order those two appear in the report header, and the display name for
#: anything else. A fixed order because a line that reorders itself between runs
#: is harder to read than one that is merely incomplete.
SITE_ORDER: Tuple[str, ...] = ("Chess.com", "LICHESS.ORG")


def site_label(raw: str) -> str:
    """``https://www.lichess.org/`` -> ``LICHESS.ORG``. Unrecognised passes through.

    Truncated rather than dropped: an unknown site still identifies where the
    games came from, and inventing a name for it would be worse than showing a
    long one.
    """
    text = (raw or "").strip()
    low = text.lower()
    for needle, label in SITE_LABELS:
        if needle in low:
            return label
    return text[:32] or "Unknown"


def build_identities(results: List[GameResult], player_name: str = "",
                     *, via_alias: bool = True) -> List[Dict]:
    """One entry per platform account the player has, with a game count.

    A single name cannot answer "which account is this?", and ``--player me``
    genuinely has several: ``player.txt`` holds one per site. So the report needs
    per-site identities, and there are two sources to combine:

    * the games actually analysed -- their ``Site`` header says where each came
      from, and the header name of the side that was the player is the spelling
      the platform itself uses (Chess.com upper-cases handles, so ``MARK8HS`` is
      the honest rendering rather than the lowercase alias);
    * ``player.txt``, for a configured site with no games in this run. Without it
      a Chess.com-only report would silently omit the lichess account, which reads
      as "you do not have one" rather than "this report is only Chess.com".

    ``via_alias`` gates the second source, and it matters. ``player.txt`` describes
    the person running the command, so it is only consulted when the player
    *asked* for themselves with ``me``; with an explicit ``--player Morphy`` the
    analysed name is somebody else entirely, and listing the operator's own
    accounts next to their games would be inventing data.

    Pure function of *results* (given ``via_alias``), so it can be asserted in
    ``--self-test`` without an engine or a PGN.
    """
    found: Dict[str, Dict] = {}
    for r in results:
        if not r.moves or r.player_color is None:
            continue
        site = site_label(r.headers.get("Site", ""))
        # The player's own header name, not `player_name`: it is what the
        # platform shows and how it capitalises it.
        side = "White" if r.player_color is True else "Black"
        name = (r.headers.get(side) or "").strip()
        entry = found.setdefault(
            site, {"site": site, "name": name, "games": 0, "player_color": None}
        )
        entry["games"] += 1
        if not entry["name"]:
            entry["name"] = name
        if entry["player_color"] is None:
            entry["player_color"] = "white" if r.player_color is True else "black"

    # Configured but unused. `player.py` is asked per site, so a `me` alias picks
    # up the right name for each one rather than whichever came first.
    if via_alias:
        for key, label in (("chesscom", "Chess.com"), ("lichess", "LICHESS.ORG")):
            try:
                configured = player.resolve(player.ME, key)
            except Exception:
                configured = None
            if configured and label not in found:
                found[label] = {
                    "site": label,
                    "name": configured,
                    "games": 0,
                    "player_color": None,
                }

    if player_name and not found:
        # No site anywhere to attribute the name to. Still better than nothing,
        # and the UI renders it with whatever label we have.
        found["Unknown"] = {
            "site": "Unknown",
            "name": player_name,
            "games": 0,
            "player_color": None,
        }

    def sort_key(item: str) -> Tuple[int, str]:
        return (SITE_ORDER.index(item) if item in SITE_ORDER else len(SITE_ORDER), item)

    return [found[key] for key in sorted(found, key=sort_key)]


def player_result(result: str, color: Optional[chess.Color]) -> str:
    if result == "1-0":
        return "win" if color is True else "loss"
    if result == "0-1":
        return "win" if color is False else "loss"
    if result in ("1/2-1/2", "½-½"):
        return "draw"
    return result


def game_title(headers: Dict[str, str]) -> str:
    """A human-readable label.

    Chess.com labels every game "Live Chess - Chess.com - 2022.08.31", so the
    opponent is appended whenever the event line is not distinctive enough to
    tell two games apart.
    """
    bits = [headers.get(k) for k in ("Event", "Site", "Date")]
    base = " - ".join(b for b in bits if b) or "Game"
    white, black = headers.get("White", ""), headers.get("Black", "")
    if white and black:
        base = f"{base} - {white} vs {black}"
    return base


# --------------------------------------------------------------------------
# ratings
# --------------------------------------------------------------------------

def header_elo(headers: Dict[str, str], color: Optional[chess.Color]) -> Optional[int]:
    """The ELO tag for one side, or None when the game was unrated.

    PGN headers spell this several ways, and platforms omit it entirely for
    unrated games -- which is common enough that treating a missing tag as 0
    would draw a spike to the floor of the chart.
    """
    # No cross-colour fallback: asking for Black's rating on a game with no
    # BlackElo tag must be "unrated", not White's number wearing the wrong hat.
    key = {chess.WHITE: "WhiteElo", chess.BLACK: "BlackElo"}.get(color)
    for key in ([key] if key else ["WhiteElo", "BlackElo"]):
        raw = (headers.get(key) or "").strip()
        if not raw:
            continue
        try:
            value = int(float(raw))
        except ValueError:
            continue
        if value > 0:
            return value
    return None


def game_date(headers: Dict[str, str]) -> str:
    """An ISO date for the game, or "" when the header is unusable.

    PGN dates are "2021.03.31"; lichess adds "2021.03.31 18:16:29".  Falls back
    to UTCDate, which is the same value in ISO order.
    """
    for key in ("UTCDate", "Date"):
        raw = (headers.get(key) or "").strip().replace("-", ".")
        head = raw.split(" ")[0]
        parts = head.split(".")
        if len(parts) == 3 and all(p.isdigit() for p in parts):
            return f"{parts[0]}-{parts[1]}-{parts[2]}"
    return ""


# Fixed bands so the opponent-strength axis does not rescale as data arrives.
RATING_BANDS = ("<400", "400-800", "800-1200", "1200-1600", "1600+")


def _band_for(elo: Optional[int]) -> Optional[str]:
    if elo is None or elo <= 0:
        return None
    if elo < 400:
        return RATING_BANDS[0]
    if elo < 800:
        return RATING_BANDS[1]
    if elo < 1200:
        return RATING_BANDS[2]
    if elo < 1600:
        return RATING_BANDS[3]
    return RATING_BANDS[4]


def build_ratings(results: List[GameResult]) -> Dict:
    """The player's ELO over time, plus accuracy by opponent strength.

    Unrated games are skipped rather than counted as zero, so ``games_rated`` is
    reported next to the series -- the caller can see how thin the data is
    instead of trusting a chart drawn from two points.
    """
    points: List[Dict] = []
    for order, r in enumerate(results):
        if not r.moves or r.player_color is None:
            continue
        elo = header_elo(r.headers, r.player_color)
        if elo is None:
            continue
        other = not r.player_color
        points.append(
            {
                "index": r.index,
                "date": game_date(r.headers),
                "elo": elo,
                "opponent": r.headers.get("Black" if r.player_color else "White", ""),
                "opponent_elo": header_elo(r.headers, other),
                "accuracy": round(r.accuracy, 2),
                "result": r.player_result,
                "_order": order,
            }
        )

    # Chronological, with PGN order as the tiebreak so games sharing a date keep
    # the sequence they were played in.
    points.sort(key=lambda p: (p["date"] or "9999-99-99", p["_order"]))
    for p in points:
        p.pop("_order", None)

    buckets: Dict[str, Dict] = {
        band: {"band": band, "games": 0, "_acc": 0.0} for band in RATING_BANDS
    }
    for r in results:
        if not r.moves or r.player_color is None:
            continue
        band = _band_for(header_elo(r.headers, not r.player_color))
        if band is None:
            continue
        buckets[band]["games"] += 1
        buckets[band]["_acc"] += r.accuracy
    for b in buckets.values():
        b["accuracy"] = round(b.pop("_acc") / b["games"], 2) if b["games"] else None

    elos = [p["elo"] for p in points]
    return {
        "player": next((r.player_name for r in results if r.player_name), ""),
        "current": elos[-1] if elos else None,
        "first": elos[0] if elos else None,
        "peak": max(elos) if elos else None,
        "low": min(elos) if elos else None,
        "delta": (elos[-1] - elos[0]) if len(elos) >= 2 else None,
        "games_rated": len(elos),
        "series": points,
        "buckets": list(buckets.values()),
    }


# --------------------------------------------------------------------------
# self-test
# --------------------------------------------------------------------------

def self_test() -> int:
    """Check the rating extraction and the shared scoring path. No network.

    Lives here rather than in a tests/ directory because the repo keeps no test
    files: these checks describe the contract of the module above them, so they
    cannot drift away from it the way a separate file can.
    """
    checks = 0
    failures: List[str] = []

    def check(label: str, got, want) -> None:
        nonlocal checks
        checks += 1
        if got != want:
            failures.append(f"{label}: got {got!r}, want {want!r}")

    def game(index, headers, color, accuracy=50.0, player="me"):
        g = GameResult(headers=headers, index=index, player_color=color,
                       player_name=player, accuracy=accuracy)
        g.moves = [MoveRecord(ply=0, move_number=1, color="white", san="e4", uci="e2e4",
                              fen="", is_players_turn=(color is chess.WHITE))]
        g.player_result = "win"
        return g

    # -- header_elo: the tag is missing often enough to matter ----------------
    check("elo white", header_elo({"WhiteElo": "1500", "BlackElo": "1400"}, chess.WHITE), 1500)
    check("elo black", header_elo({"WhiteElo": "1500", "BlackElo": "1400"}, chess.BLACK), 1400)
    check("elo missing tag", header_elo({"White": "a", "Black": "b"}, chess.WHITE), None)
    check("elo blank tag", header_elo({"WhiteElo": "  "}, chess.WHITE), None)
    check("elo zero is unrated", header_elo({"WhiteElo": "0"}, chess.WHITE), None)
    check("elo float form", header_elo({"WhiteElo": "1500.5"}, chess.WHITE), 1500)
    check("elo garbage", header_elo({"WhiteElo": "?"}, chess.WHITE), None)

    # -- dates: "2021.03.31", lichess timestamps, ISO, junk -------------------
    check("date dotted", game_date({"Date": "2021.03.31"}), "2021-03-31")
    check("date timestamped", game_date({"Date": "2021.03.31 18:16:29"}), "2021-03-31")
    check("date utc preferred", game_date({"Date": "2021.03.31", "UTCDate": "2020-01-02"}),
          "2020-01-02")
    check("date junk", game_date({"Date": "??.??"}), "")

    # -- bands ---------------------------------------------------------------
    check("band low", _band_for(350), "<400")
    check("band mid", _band_for(900), "800-1200")
    check("band top", _band_for(2400), "1600+")
    check("band unrated", _band_for(None), None)

    # -- build_ratings: the interesting cases --------------------------------
    empty = build_ratings([])
    check("no games -> current", empty["current"], None)
    check("no games -> rated count", empty["games_rated"], 0)
    check("no games -> bands are empty but present", len(empty["buckets"]), len(RATING_BANDS))
    check("no games -> band accuracy is None", empty["buckets"][0]["accuracy"], None)

    one = build_ratings([game(1, {"Date": "2021.03.31", "White": "me",
                                   "Black": "you", "WhiteElo": "900",
                                   "BlackElo": "800"}, chess.WHITE, 70.0)])
    check("single game -> current", one["current"], 900)
    check("single game -> delta is None, not 0", one["delta"], None)
    check("single game -> opponent", one["series"][0]["opponent"], "you")
    check("single game -> opponent elo", one["series"][0]["opponent_elo"], 800)
    check("single game -> bucket counted", one["buckets"][2]["games"], 1)
    check("unrated opponent lands in no band",
          sum(b["games"] for b in build_ratings([
              game(1, {"Date": "2021.03.31", "White": "me", "Black": "you",
                       "WhiteElo": "900"}, chess.WHITE, 70.0)])["buckets"]), 0)

    two = build_ratings([
        game(2, {"Date": "2021.04.01", "White": "me", "Black": "b", "WhiteElo": "1010"},
             chess.WHITE, 80.0),
        game(1, {"Date": "2021.03.31", "White": "me", "Black": "a", "WhiteElo": "900"},
             chess.WHITE, 60.0),
    ])
    check("sorted chronologically", [p["elo"] for p in two["series"]], [900, 1010])
    check("current is the last game", two["current"], 1010)
    check("first is the first game", two["first"], 900)
    check("delta", two["delta"], 110)
    check("peak", two["peak"], 1010)
    check("low", two["low"], 900)
    check("rated count", two["games_rated"], 2)
    check("order field stripped", "_order" in two["series"][0], False)

    # unrated games are skipped, never counted as 0
    mixed = build_ratings([
        game(1, {"Date": "2021.03.31", "White": "me", "Black": "a", "WhiteElo": "900"},
             chess.WHITE),
        game(2, {"Date": "2021.04.02", "White": "me", "Black": "b"}, chess.WHITE),
        game(3, {"Date": "2021.04.03", "White": "me", "Black": "c",
                 "WhiteElo": "1200"}, chess.WHITE),
    ])
    check("unrated skipped", mixed["games_rated"], 2)
    check("unrated does not drag current to 0", mixed["current"], 1200)
    check("unrated game is in no opponent band", sum(b["games"] for b in mixed["buckets"]), 0)

    # undated games sort last rather than first, and keep PGN order
    undated = build_ratings([
        game(1, {"White": "me", "Black": "a", "WhiteElo": "1500"}, chess.WHITE),
        game(2, {"Date": "2021.03.31", "White": "me", "Black": "b", "WhiteElo": "700"},
             chess.WHITE),
    ])
    check("undated sorts last", [p["index"] for p in undated["series"]], [2, 1])

    # games the player is not in contribute no series points
    other = build_ratings([
        game(1, {"Date": "2021.03.31", "White": "a", "Black": "b", "WhiteElo": "900"},
             None, 55.0),
    ])
    check("unmatched player -> no series", other["games_rated"], 0)

    # -- the refactor changed nothing ----------------------------------------
    def labels_mod_label(**kwargs):
        """The label, derived the way `classify()` did before the extraction."""
        return labels.classify_data(
            labels.LabelInput(
                sacrifice=None, in_book=False, forced=False, is_player=True, **kwargs
            )
        )

    # `Analyser._score` used to do this arithmetic inline; it now calls
    # scoring.py. This compares both on identical engine output, so a future
    # edit that quietly changes a sign or a rounding cannot pass unnoticed.
    # The engine itself is not deterministic under a time cap -- it can reach
    # depth 22 on one run and 21 on the next, which is enough to move gap_pp
    # across the 10-point "great" threshold -- so this fixes the *inputs*.
    def legacy_score(lines_before, lines_after, uci):
        """The arithmetic as it was written before scoring.py existed."""
        eval_before = lines_before[0].score_cp if lines_before else 0.0
        eval_after = -lines_after[0].score_cp if lines_after else -eval_before
        wp_before = win_percent(eval_before)
        wp_after = win_percent(eval_after)
        loss = max(0.0, wp_before - wp_after)
        best_uci = lines_before[0].uci if lines_before else None
        best_san = lines_before[0].san if lines_before else None
        best_eval = lines_before[0].score_cp if lines_before else None
        second_uci = second_san = None
        second_eval = None
        gap = None
        if len(lines_before) > 1:
            second = lines_before[1]
            second_uci, second_san = second.uci, second.san
            second_eval = second.score_cp
            gap = round(win_percent(best_eval or 0.0) - win_percent(second.score_cp), 2)
        return {
            "eval_before": eval_before,
            "eval_after": eval_after,
            "win_percent_before": wp_before,
            "win_percent_after": wp_after,
            "loss_pp": loss,
            "accuracy": round(accuracy_from_loss(loss), 2),
            "best_uci": best_uci,
            "best_san": best_san,
            "best_eval": best_eval,
            "second_uci": second_uci,
            "second_san": second_san,
            "second_eval": second_eval,
            "gap_pp": gap,
        }

    fixtures = [
        # a normal move, with a clear runner-up
        (
            [engines.Line("e2e4", "e4", ["e2e4"], cp=30.0, depth=14),
             engines.Line("d2d4", "d4", ["d2d4"], cp=12.0, depth=14)],
            [engines.Line("e7e5", "e5", ["e7e5"], cp=-28.0, depth=14)],
        ),
        # a blunder: the position after is far worse
        (
            [engines.Line("d2d4", "d4", ["d2d4"], cp=25.0, depth=20),
             engines.Line("c2c4", "c4", ["c2c4"], cp=24.0, depth=20)],
            [engines.Line("e7e5", "e5", ["e7e5"], cp=900.0, depth=20)],
        ),
        # a forced mate, where the centipawn sentinel must survive
        (
            [engines.Line("d1h5", "Qh5#", ["d1h5"], mate=1, depth=30),
             engines.Line("a1a8", "Rxa8", ["a1a8"], cp=-900.0, depth=30)],
            [engines.Line("e8f7", "Kf7", ["e8f7"], cp=100000.0, depth=30)],
        ),
        # MultiPV=1, so there is no runner-up at all
        (
            [engines.Line("g1f3", "Nf3", ["g1f3"], cp=12.0, depth=11)],
            [engines.Line("d7d5", "d5", ["d7d5"], cp=10.0, depth=11)],
        ),
    ]

    for index, (before_lines, after_lines) in enumerate(fixtures):
        board = chess.Board()
        uci = "e2e4"
        legacy = legacy_score(before_lines, after_lines, uci)
        modern = scoring.score_move(
            board, uci, before=before_lines, after=after_lines, depth=14
        ).to_dict()
        for field in legacy:
            check(f"fixture {index}: {field} unchanged", modern[field], legacy[field])
        # ...and the label that comes out of it must be identical too.
        legacy_label = labels_mod_label(
            uci=uci,
            best_uci=legacy["best_uci"],
            loss_pp=legacy["loss_pp"],
            win_percent_before=legacy["win_percent_before"],
            win_percent_after=legacy["win_percent_after"],
            gap_pp=legacy["gap_pp"],
        )
        fresh = scoring.score_move(
            board, uci, before=before_lines, after=after_lines, depth=14
        )
        scoring.label_move(fresh, uci=uci, in_book=False, forced=False, sacrifice=None)
        check(f"fixture {index}: label unchanged", fresh.label, legacy_label)

    # -- the shared scoring path agrees with itself --------------------------
    # Values chosen so the move genuinely is best: a centipawn-scale drift after
    # e4 costs well under the 1pp that separates "best" from "excellent".
    board = chess.Board()
    before = [engines.Line("e2e4", "e4", ["e2e4", "e7e5"], cp=30.0, depth=14),
              engines.Line("d2d4", "d4", ["d2d4", "d7d5"], cp=20.0, depth=14)]
    after_board = board.copy()
    after_board.push(board.parse_uci("e2e4"))
    after = [engines.Line("e7e5", "e5", ["e7e5"], cp=-28.0, depth=14)]

    same = scoring.score_move(board, "e2e4", before=before, after=after, depth=14)
    check("best san", same.best_san, "e4")
    check("second san", same.second_san, "d4")
    check("gap is E1-E2 in win percent", round(same.gap_pp or 0, 0),
          round(win_percent(30.0) - win_percent(20.0), 0))
    check("eval_after is negated to the mover's view", same.eval_after, 28.0)
    check("pv rendered as san", same.best_pv[:1], ["e4"])

    label = scoring.label_move(same, uci="e2e4", in_book=False, forced=False, sacrifice=None)
    check("best move labels best", label, Label.BEST)
    check("glyph set", same.glyph, "")

    # The label follows the loss, not whether the move matched the engine's
    # preference: a harmless alternative is still an excellent move.
    off = scoring.score_move(board, "a2a3", before=before, after=after, depth=14)
    scoring.label_move(off, uci="a2a3", in_book=False, forced=False, sacrifice=None)
    check("a harmless alternative is not punished for being different",
          off.label in (Label.BEST, Label.EXCELLENT, Label.GOOD), True)

    # A move that throws the game away is labelled by how much it cost.
    blundered = scoring.score_move(
        board, "d2d4",
        before=before,
        after=[engines.Line("e7e5", "e5", ["e7e5"], cp=900.0, depth=14)],
        depth=14,
    )
    scoring.label_move(blundered, uci="d2d4", in_book=False, forced=False, sacrifice=None)
    check("a move that gives up the game is a blunder", blundered.label, Label.BLUNDER)

    # MultiPV=1 gives no runner-up, so 'great' must be unreachable
    solo = scoring.score_move(board, "e2e4", before=before[:1], after=after, depth=14)
    check("no second line -> gap is None", solo.gap_pp, None)
    scoring.label_move(solo, uci="d2d4", in_book=False, forced=False, sacrifice=None)
    check("great needs a runner-up", solo.label != Label.GREAT, True)

    # is_forced_move gates 'great': with one legal move there was no choice
    forced = chess.Board("7k/8/8/8/8/8/5q2/7K w - - 0 1")
    check("in check counts as forced", is_forced_move(forced), True)

    # detect_sacrifice: material actually given up against the best reply.
    # Queens trade evenly, so the test uses a rook, which leaves a real deficit.
    sac = chess.Board()
    sac_move = sac.parse_uci("e2e4")
    check("nothing given yet", detect_sacrifice(sac, sac_move, None, chess.WHITE), 0.0)

    # The queen takes a pawn that a rook defends, then walks into the recapture:
    # a queen for a pawn. Measured after the refutation, which is the whole
    # point -- a sacrifice that only worked because the opponent blundered
    # would not be a sacrifice.
    # Black king on e8: clear of both the h-file and rank 5, so the rook on h5
    # is not pinning or checking anything before the sacrifice.
    trap = chess.Board("4k3/8/8/3p1r2/8/8/3Q4/K7 w - - 0 1")
    take = trap.parse_uci("d2d5")
    after_take = trap.copy(stack=False)
    after_take.push(take)
    recapture = after_take.parse_uci("f5d5")
    check("queen given for a pawn", detect_sacrifice(trap, take, recapture, chess.WHITE), 8.0)
    # Without the refutation the move simply won a pawn, which is negative:
    # "material given" is measured against the opponent's best reply, so the
    # whole point is that an unrefuted capture does not read as a sacrifice.
    check("an unrefuted capture is not a sacrifice",
          detect_sacrifice(trap, take, None, chess.WHITE), -1.0)
    check("an illegal reply is ignored, not applied",
          detect_sacrifice(trap, take, trap.parse_uci("d2d4"), chess.WHITE), -1.0)

    # -- brilliant needs a position worth winning in --------------------------
    #
    # The bug this guards against: `loss <= 2pp` is vacuous once the position is
    # already lost. At win_percent_before = 10, *every* move costs at most ~10pp,
    # so a queen sacrifice in a lost game passed the "still no worse than the
    # alternatives" test. The two floors below are what make "sound" mean sound.
    def brilliant_of(**overrides):
        """A sacrifice, labelled. Overrides vary the one input under test."""
        base = dict(
            uci="e2e4",
            best_uci="e2e4",
            loss_pp=1.9,
            win_percent_before=95.0,
            win_percent_after=93.1,
            gap_pp=0.5,
            sacrifice=3.3,
            in_book=False,
            forced=False,
            is_player=True,
        )
        base.update(overrides)
        return labels.classify_data(labels.LabelInput(**base))

    # These assert "not brilliant" rather than a specific label, and deliberately
    # so: what the move *is* called instead is the loss band's business, and it
    # shifts when a band moves. Whether it is brilliant is the decision under
    # test.
    def not_brilliant(label, **overrides):
        return brilliant_of(**overrides) != Label.BRILLIANT

    check("a real sacrifice is brilliant", brilliant_of(), Label.BRILLIANT)
    check("a sacrifice in a lost position is not",
          not_brilliant("", win_percent_before=10.2), True)
    check("a sacrifice that leaves you worse is not",
          not_brilliant("", win_percent_after=8.3), True)
    check("both floors, to the numbers from /games/1/31",
          not_brilliant("", win_percent_before=10.2, win_percent_after=8.3), True)
    # Just either side of each floor, so a threshold moved by accident is caught.
    check("just under the before-floor",
          not_brilliant("", win_percent_before=labels.BRILLIANT_MIN_WIN_BEFORE - 0.1),
          True)
    check("just over the before-floor",
          brilliant_of(win_percent_before=labels.BRILLIANT_MIN_WIN_BEFORE + 0.1),
          Label.BRILLIANT)
    check("just under the after-floor",
          not_brilliant("", win_percent_after=labels.BRILLIANT_MIN_WIN_AFTER - 0.1), True)
    check("just over the after-floor",
          brilliant_of(win_percent_after=labels.BRILLIANT_MIN_WIN_AFTER + 0.1),
          Label.BRILLIANT)
    # Morphy's reference cases, which the rule must not discard: both are played
    # from a winning position and both leave White winning.
    check("Morphy 13.Rxd7 stays brilliant",
          brilliant_of(win_percent_before=99.0, win_percent_after=88.0), Label.BRILLIANT)
    check("Morphy 16.Qb8+ stays brilliant",
          brilliant_of(win_percent_before=99.5, win_percent_after=97.0), Label.BRILLIANT)
    # The other gates still apply, so the floors are additive and not a rewrite.
    check("a book sacrifice is still not brilliant",
          not_brilliant("", in_book=True), True)
    check("a forced sacrifice is still not brilliant",
          not_brilliant("", forced=True), True)
    check("no material, no brilliant", not_brilliant("", sacrifice=0.4), True)

    # -- per-site identities --------------------------------------------------
    check("Chess.com is recognised", site_label("Chess.com"), "Chess.com")
    check("a chess.com URL is recognised", site_label("https://www.chess.com/"),
          "Chess.com")
    check("lichess is recognised", site_label("https://lichess.org/"), "LICHESS.ORG")
    check("LICHESS.ORG upper case is recognised", site_label("LICHESS.ORG"),
          "LICHESS.ORG")
    check("an unknown site passes through", site_label("Some Other Server"),
          "Some Other Server")
    check("a blank site does not become blank", site_label(""), "Unknown")

    def site_game(index, site, white, black, color):
        return game(index, {"Site": site, "White": white, "Black": black}, color)

    # `build_identities` consults player.txt for configured-but-unused sites, so
    # these checks point it at a throwaway file. Without that the real one on the
    # developer's machine decides what the test asserts, which is how a suite
    # passes on one checkout and fails on another.
    import tempfile

    with tempfile.TemporaryDirectory() as _tmp_ids:
        saved_txt, saved_env = player.PLAYER_TXT, os.environ.pop(player.ENV_VAR, None)
        player.PLAYER_TXT = os.path.join(_tmp_ids, "player.txt")
        try:
            # -- one site, from the games ---------------------------------------
            with open(player.PLAYER_TXT, "w", encoding="utf-8") as _fh:
                _fh.write("chesscom=mark8hs\n")
            one_site = build_identities([
                site_game(1, "Chess.com", "opponent", "MARK8HS", chess.BLACK),
                site_game(2, "Chess.com", "opponent", "MARK8HS", chess.BLACK),
            ], player_name="mark8hs")
            # The Chess.com entry is the one carrying the games.
            cc = next(i for i in one_site if i["site"] == "Chess.com")
            check("games counted", cc["games"], 2)
            # The platform's own spelling, not the lowercase alias: Chess.com
            # capitalises handles, so this is what a reader would recognise.
            check("the header spelling wins", cc["name"], "MARK8HS")
            check("the colour is recorded", cc["player_color"], "black")
            check("Chess.com sorts first", one_site[0]["site"], "Chess.com")
            # Two games on one site are one identity, not two.
            check("two games, one identity",
                  sum(1 for i in one_site if i["games"]), 1)

            # -- a configured site with no games still appears ------------------
            with open(player.PLAYER_TXT, "w", encoding="utf-8") as _fh:
                _fh.write("chesscom=mark8hs\nlichess=mark8hs\n")
            both = build_identities([
                site_game(1, "LICHESS.ORG", "mark8hs", "opp", chess.WHITE),
                site_game(2, "Chess.com", "opp", "MARK8HS", chess.BLACK),
            ], player_name="mark8hs")
            check("two sites, Chess.com first regardless of PGN order",
                  [i["site"] for i in both], ["Chess.com", "LICHESS.ORG"])
            check("each keeps its own spelling", [i["name"] for i in both],
                  ["MARK8HS", "mark8hs"])

            # -- an unused site is listed with a zero count, not omitted --------
            unused = build_identities([
                site_game(1, "Chess.com", "opp", "MARK8HS", chess.BLACK),
            ], player_name="mark8hs")
            check("the unused site is still listed",
                  [i["site"] for i in unused], ["Chess.com", "LICHESS.ORG"])
            check("the unused site counts zero", unused[1]["games"], 0)
            check("the unused site takes its configured name",
                  unused[1]["name"], "mark8hs")
            check("the unused site has no colour", unused[1]["player_color"], None)

            # -- nothing configured, and no game the player is in ------
            # Both at once, because either alone still leaves player.txt able to
            # contribute an entry, and the point is that neither does.
            with open(player.PLAYER_TXT, "w", encoding="utf-8") as _fh:
                _fh.write("# nothing configured\n")
            check("a game the player is not in contributes no identity",
                  build_identities([site_game(1, "Chess.com", "a", "b", None)], ""),
                  [])

            # -- no configuration at all: the analysed game still gets shown ----
            orphan = build_identities([
                site_game(1, "Chess.com", "opp", "MARK8HS", chess.BLACK),
            ], player_name="mark8hs")
            check("no player.txt -> only the analysed site", len(orphan), 1)
            check("no player.txt -> the site is still named", orphan[0]["site"],
                  "Chess.com")

            # -- an explicit --player must not inherit the operator's accounts --
            # The real bug this caught: `python analyze.py --player Morphy
            # --pgn games/opera.pgn` attributed the Chess.com and LICHESS.ORG
            # accounts from the developer's own player.txt to Morphy's game,
            # because player.txt was read unconditionally. It describes whoever
            # ran the command, so it is only consulted for the `me` alias.
            with open(player.PLAYER_TXT, "w", encoding="utf-8") as _fh:
                _fh.write("chesscom=mark8hs\nlichess=mark8hs\n")
            explicit = build_identities(
                [site_game(1, "Paris, France", "Morphy, Paul", "Duke", chess.WHITE)],
                player_name="Morphy",
                via_alias=False,
            )
            check("an explicit player gets only their own games' sites",
                  [i["site"] for i in explicit], ["Paris, France"])
            check("and none of the operator's accounts",
                  [i["name"] for i in explicit], ["Morphy, Paul"])
            via_alias = build_identities(
                [site_game(1, "Paris, France", "Morphy, Paul", "Duke", chess.WHITE)],
                player_name="Morphy",
                via_alias=True,
            )
            check("the alias does read player.txt", len(via_alias), 3)
        finally:
            player.PLAYER_TXT = saved_txt
            if saved_env is not None:
                os.environ[player.ENV_VAR] = saved_env

    print(f"analyze: {checks - len(failures)}/{checks} checks passed")
    for problem in failures:
        print(f"  FAIL {problem}", file=sys.stderr)
    return 1 if failures else 0


# --------------------------------------------------------------------------
# annotated PGN
# --------------------------------------------------------------------------

def _comment_text(rec: MoveRecord) -> str:
    parts: List[str] = []
    if rec.glyph:
        parts.append(f"{rec.label.title()} {rec.glyph}")
    parts.append(f"phase: {rec.phase}")
    if rec.eval_before is not None and rec.eval_after is not None:
        parts.append(f"eval {_fmt_cp(rec.eval_before)} -> {_fmt_cp(rec.eval_after)}")
    if rec.best_san and rec.best_san != rec.san:
        parts.append(f"best: {rec.best_san}")
    if rec.loss_pp >= 0.5:
        parts.append(f"loss {rec.loss_pp:.1f}pp")
    if rec.sacrifice:
        parts.append(f"sacrifice {rec.sacrifice:.1f}")
    if rec.lc0_agrees and rec.best_uci != rec.uci:
        parts.append(f"Lc0 likes {rec.lc0_best_san} too")
    if rec.verified:
        parts.append(f"verified d{rec.depth}")
    return " ".join(parts) or "ok"


def _fmt_cp(cp: float) -> str:
    """Pawn-relative eval, or # for a forced mate (the move table shows #n)."""
    if cp >= MATE_CP:
        return "#"
    if cp <= -MATE_CP:
        return "-#"
    return f"{cp / 100:+.2f}"


def format_pgn(headers: Dict[str, str], moves: List[MoveRecord]) -> str:
    # PGN tag pairs are [Name "value"] -- no colon after the name.  Emitting
    # [Name: "value"] makes every strict parser treat the tag as unknown, which
    # silently loses the player names, dates and results.
    lines = [f'[{k} "{v}"]' for k, v in headers.items()]
    current: List[str] = []
    width = 0
    last_number = None

    for rec in moves:
        if rec.move_number != last_number:
            if current:
                lines.append(" ".join(current))
                current, width = [], 0
            token = f"{rec.move_number}." + ("..." if rec.color == "black" else "")
            current.append(token)
            width += len(token) + 1
            last_number = rec.move_number
        comment = f"{{{_comment_text(rec)}}}"
        current.extend((rec.san, comment))
        width += len(rec.san) + len(comment) + 1
        if width > 72:
            lines.append(" ".join(current))
            current, width = [], 0
    if current:
        lines.append(" ".join(current))
    lines.append(headers.get("Result", "*"))
    return "\n".join(lines)


def write_annotated_pgn(results: List[GameResult], path: str) -> None:
    chunks: List[str] = []
    for res in results:
        if not res.moves:
            continue
        headers = dict(res.headers)
        headers["Annotator"] = "chess-coach"
        chunks.append(format_pgn(headers, res.moves))
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n\n".join(chunks) + ("\n" if chunks else ""))


# --------------------------------------------------------------------------
# dashboard
# --------------------------------------------------------------------------

def build_dashboard(results: List[GameResult]) -> Dict:
    played = [r for r in results if r.moves]

    trend = [
        {
            "index": r.index,
            "title": game_title(r.headers),
            "date": r.headers.get("Date", ""),
            "opening": r.opening,
            "eco": r.eco,
            "result": r.player_result,
            "accuracy": r.accuracy,
            "accuracy_mean": r.accuracy_mean,
            "acpl": r.acpl,
            "counts": r.counts,
            "eval_curve": r.eval_curve,
        }
        for r in played
    ]

    phases: Dict[str, Dict[str, float]] = {}
    for r in played:
        for phase, stats in r.phase_accuracy.items():
            b = phases.setdefault(
                phase,
                {"moves": 0, "games": 0, "_wp": 0.0, "_loss": 0.0,
                 **{lab: 0 for lab in LABEL_ORDER}},
            )
            b["moves"] += stats["moves"]
            b["games"] += 1
            b["_wp"] += stats["accuracy"] * stats["moves"]
            b["_loss"] += stats["acpl"] * stats["moves"]
            for lab in LABEL_ORDER:
                b[lab] += stats.get(lab, 0)
    for b in phases.values():
        b["accuracy"] = round(b.pop("_wp") / b["moves"], 2) if b["moves"] else 0.0
        b["acpl"] = round(b.pop("_loss") / b["moves"], 2) if b["moves"] else 0.0

    ranked = sorted(played, key=lambda r: r.accuracy, reverse=True)
    return {
        "games": len(played),
        "trend": trend,
        "phases": phases,
        "best_games": [
            {"index": r.index, "accuracy": r.accuracy, "title": game_title(r.headers),
             "opening": r.opening, "result": r.player_result}
            for r in ranked[:5]
        ],
        "worst_games": [
            {"index": r.index, "accuracy": r.accuracy, "title": game_title(r.headers),
             "opening": r.opening, "result": r.player_result}
            for r in reversed(ranked[-5:])
        ],
        "weaknesses": recurring_weaknesses(played),
        "brilliancies": collect_brilliancies(played),
        "totals": totals(played),
        "ratings": build_ratings(results),
    }


def totals(results: List[GameResult]) -> Dict:
    counts = {lab: 0 for lab in LABEL_ORDER}
    for r in results:
        for lab, n in r.counts.items():
            counts[lab] = counts.get(lab, 0) + n
    accs = [r.accuracy for r in results]
    return {
        "counts": counts,
        "accuracy_mean": round(sum(accs) / len(accs), 2) if accs else 0.0,
        "acpl_mean": round(
            sum(r.acpl for r in results) / len(results), 2
        ) if results else 0.0,
        "wins": sum(1 for r in results if r.player_result == "win"),
        "losses": sum(1 for r in results if r.player_result == "loss"),
        "draws": sum(1 for r in results if r.player_result == "draw"),
    }


def recurring_weaknesses(results: List[GameResult]) -> List[Dict]:
    """Countable, evidenced failure patterns across the archive.

    Every entry carries its count and the games involved, so any claim in the
    panel can be checked against the move table.
    """
    patterns: Dict[str, Dict] = {}

    def bump(key: str, label: str, game: GameResult, detail: str = "") -> None:
        p = patterns.setdefault(
            key, {"key": key, "label": label, "count": 0, "games": [], "examples": []}
        )
        p["count"] += 1
        if game.index not in p["games"]:
            p["games"].append(game.index)
        if detail and len(p["examples"]) < 4:
            p["examples"].append(detail)

    for game in results:
        title = game_title(game.headers)
        for rec in game.moves:
            if not rec.is_players_turn:
                continue
            where = f"{title} {rec.move_number}.{rec.san}"

            if rec.label in (Label.BLUNDER, Label.MISTAKE, Label.INACCURACY):
                if rec.left_book:
                    bump("left_book", "Blunders on the first move out of book theory",
                         game, where)
                bump(f"phase_{rec.phase}", f"Errors in the {rec.phase}", game, where)
                if rec.sacrifice and rec.loss_pp > 5:
                    bump("unsound_sac", "Unsound sacrifices (material given, no compensation)",
                         game, where)
                if rec.lc0_agrees and rec.best_uci != rec.uci and rec.loss_pp > 5:
                    bump("lc0_vs_sf", "Moves Lc0 endorsed but Stockfish scored as errors",
                         game, where)
            elif rec.label == Label.MISS:
                bump("missed_win", "Missed winning positions", game, where)
                if rec.phase == "endgame":
                    bump("missed_win_endgame", "Missed wins in the endgame", game, where)

    out = list(patterns.values())
    out.sort(key=lambda p: (-p["count"], p["label"]))
    for p in out:
        p["game_count"] = len(p["games"])
    return out


def collect_brilliancies(results: List[GameResult]) -> List[Dict]:
    out: List[Dict] = []
    for game in results:
        for rec in game.moves:
            if rec.label == Label.BRILLIANT:
                out.append(
                    {
                        "game": game.index,
                        "title": game_title(game.headers),
                        "opening": game.opening,
                        "move_number": rec.move_number,
                        "san": rec.san,
                        "uci": rec.uci,
                        "sacrifice": rec.sacrifice,
                        "loss_pp": rec.loss_pp,
                        "fen": rec.fen,
                        "fen_after": rec.fen_after,
                        "pv": rec.best_pv,
                        "lc0_agrees": rec.lc0_agrees,
                    }
                )
    return out


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def load_games(pgn_path: str) -> List[chess.pgn.Game]:
    games: List[chess.pgn.Game] = []
    with open(pgn_path, "r", encoding="utf-8", errors="replace") as fh:
        while True:
            game = chess.pgn.read_game(fh)
            if game is None:
                break
            games.append(game)
    return games


def main(argv: Optional[Sequence[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    # Offline check of the rating extraction and the shared scoring path. Cheap
    # enough that it can run before every analysis.
    if "--self-test" in argv:
        return self_test()

    ap = argparse.ArgumentParser(
        description="Analyse a PGN with Stockfish, cross-checked with Lc0."
    )
    ap.add_argument("--pgn", default=os.path.join("games", "raw.pgn"), help="input PGN")
    ap.add_argument(
        "--player", default=player.ME,
        help=f"player to score (matched against the PGN headers), or {player.ME!r} "
             f"for the one in player.txt; empty falls back to White (default {player.ME!r})",
    )
    ap.add_argument("--out", default="out", help="output directory")
    ap.add_argument("--depth", type=int, default=14, help="pass 1 survey depth")
    ap.add_argument("--focus-depth", type=int, default=24, help="pass 2 verification depth")
    ap.add_argument(
        "--survey-time", type=float, default=2.0,
        help="seconds cap per position in pass 1 (0 = no cap)",
    )
    ap.add_argument(
        "--focus-time", type=float, default=6.0,
        help="seconds cap per position in pass 2 (0 = no cap)",
    )
    ap.add_argument("--limit", type=int, default=0, help="analyse at most N games")
    ap.add_argument("--stockfish", default="", help="path to the stockfish binary")
    ap.add_argument(
        "--threads", type=int, default=1,
        help="stockfish threads (default 1: fastest for sequential per-position search)",
    )
    ap.add_argument("--hash", type=int, default=512, help="stockfish hash table, MB")
    ap.add_argument("--lc0", default="", help="path to the lc0 binary")
    ap.add_argument("--lc0-net", default="", help="path to an Lc0 .pb.gz network")
    ap.add_argument(
        "--lc0-nodes", type=int, default=3000,
        help="Lc0 node budget per position (default 3000; Lc0 gets expensive fast, "
             "and a low budget is plenty to see whether it endorses your move)",
    )
    ap.add_argument(
        "--lc0-backend",
        default="",
        help="force an Lc0 neural backend (onnx-dml, onnx-cuda, cuda-fp16, blas, ...). "
             "Left empty, the build is asked which ones it supports and they are "
             "tried best-first",
    )
    ap.add_argument("--lc0-max-moves", type=int, default=12, help="max moves to cross-check per game")
    ap.add_argument("--no-lc0", action="store_true", help="skip the Lc0 cross-check")
    ap.add_argument("--no-book", action="store_true", help="ignore the opening book")
    ap.add_argument("--no-report", action="store_true", help="skip HTML generation")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)

    verbose = not args.quiet
    os.makedirs(args.out, exist_ok=True)

    # resolve() already passes an explicit name through verbatim; only an unresolved
    # alias becomes empty, which keeps the old behaviour of falling back to the
    # White header when nothing is configured.
    player_name = player.resolve(args.player) or ""
    if player_name and player.is_me(args.player) and verbose:
        print(f"Player: {player_name}")

    if not os.path.isfile(args.pgn):
        print(f"error: PGN not found: {args.pgn}\nRun fetch_games.py first.", file=sys.stderr)
        return 2

    games = load_games(args.pgn)
    if args.limit:
        games = games[: args.limit]
    if verbose:
        print(f"Loaded {len(games)} game(s) from {args.pgn}")

    # A name that matches nothing used to yield a report of empty games, because
    # analyse_game cannot pick a side. Fail here instead, while it is still cheap.
    if player_name:
        # `is not None`, not truthiness: the colour IS False when you are Black,
        # and a Black game is a match just as much as a White one.
        matched = sum(
            1
            for g in games
            if resolve_player_color(dict(g.headers), player_name) is not None
        )
        if not matched:
            who = ""
            if games:
                headers = dict(games[0].headers)
                who = f"\nfirst game is White: {headers.get('White', '?')} / Black: {headers.get('Black', '?')}"
            print(
                f"error: no game in {args.pgn} has {player_name} as a player.{who}\n"
                "Pass the name as it appears in the PGN, e.g. --player YourName",
                file=sys.stderr,
            )
            return 2
        if matched < len(games) and verbose:
            print(f"{matched}/{len(games)} game(s) match {player_name}; the rest are skipped")

    if args.no_book:
        book = openings.OpeningBook()
    else:
        _, notes = openings.ensure_book()
        for note in notes:
            print(f"  book: {note}", file=sys.stderr)
        book = openings.OpeningBook.load()
        if verbose:
            print(f"Opening book: {book.summary()}")

    sf = engines.open_stockfish(
        args.stockfish or None,
        threads=args.threads,
        hash_mb=args.hash,
        verbose=verbose,
    )
    if verbose:
        print(f"Stockfish: {sf.id.get('name')}  ({sf.path})")

    lc0 = None
    if not args.no_lc0:
        try:
            lc0 = engines.open_lc0(
                args.lc0 or None,
                net=args.lc0_net or None,
                backend=args.lc0_backend or "",
                verbose=verbose,
            )
            if verbose:
                print(
                    f"Lc0: {lc0.id.get('name')}  net={os.path.basename(getattr(lc0, 'net', ''))}"
                    f"  backend={getattr(lc0, 'backend', '?')}"
                )
        except Exception as exc:
            print(f"  ! Lc0 unavailable, continuing with Stockfish only:\n    {exc}", file=sys.stderr)

    analyser = Analyser(
        sf,
        depth=args.depth,
        focus_depth=args.focus_depth,
        book=book,
        lc0=lc0,
        lc0_nodes=args.lc0_nodes,
        lc0_max_moves=args.lc0_max_moves,
        survey_movetime=args.survey_time or None,
        focus_movetime=args.focus_time or None,
        verbose=verbose,
    )

    results: List[GameResult] = []
    started = time.time()
    for i, game in enumerate(games, start=1):
        if verbose:
            print(f"[{i}/{len(games)}] {game_title(dict(game.headers))}")
        # Named for the module import above, which this local would otherwise shadow.
        game_player = player_name or game.headers.get("White", "")
        try:
            res = analyser.analyse_game(game, player_name=game_player, index=i)
        except Exception as exc:
            print(f"  ! game {i} failed: {exc}", file=sys.stderr)
            continue
        if verbose:
            print(
                f"    acc {res.accuracy:5.1f}  acpl {res.acpl:5.1f}  "
                f"blunder {res.counts.get('blunder', 0)}  "
                f"brilliant {res.counts.get('brilliant', 0)}  "
                f"({res.analysis_seconds:.1f}s)"
            )
        results.append(res)

    elapsed = time.time() - started
    if verbose:
        print(f"Analysed {len(results)} game(s) in {elapsed:.1f}s")

    data = {
        "generated": _dt.datetime.now().isoformat(timespec="seconds"),
        # The *resolved* name, not `args.player`: with `--player me` that
        # argument is the literal string "me", which is what the report used to
        # print above the ELO. `player_name` is empty only when nothing is
        # configured, in which case the old text is the honest fallback.
        "player": player_name or args.player,
        # Per-site, because one name cannot answer "which account is this?" and
        # `--player me` has one per site in player.txt. `via_alias` keeps
        # player.txt out of a report about somebody else's games.
        "player_identities": build_identities(
            results, player_name, via_alias=player.is_me(args.player)
        ),
        "settings": {
            "depth": args.depth,
            "focus_depth": args.focus_depth,
            "stockfish": sf.id.get("name"),
            "stockfish_path": sf.path,
            "lc0": lc0.id.get("name") if lc0 else None,
            "lc0_net": os.path.basename(getattr(lc0, "net", "")) if lc0 else None,
            "lc0_nodes": args.lc0_nodes if lc0 else 0,
            "positions_searched": sf.positions_searched,
            "cache_hits": sf.cache_hits,
        },
        "book": book.summary(),
        "elapsed_seconds": round(elapsed, 1),
        "dashboard": build_dashboard(results),
        "games": [r.to_dict() for r in results],
    }

    with open(os.path.join(args.out, "data.json"), "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=1)
    write_annotated_pgn(results, os.path.join(args.out, "annotated.pgn"))

    if not args.no_report:
        import report
        html_path = os.path.join(args.out, "report.html")
        report.write_report(data, html_path, verbose=verbose)
        if verbose:
            print(f"Report: {html_path}")

    if lc0:
        lc0.close()
    sf.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())