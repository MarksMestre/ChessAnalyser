"""Turn engine output into the numbers and the label the report displays.

This module exists so that there is exactly **one** implementation of "how good
was that move".  ``analyze.py`` scores every ply of every game in a batch; the
frontend server scores one position at a time while somebody plays on the board.
Both go through here, so the batch report and live play cannot drift apart: if a
threshold moves in ``labels.py``, both change together.

Nothing here touches an engine.  The caller does the searching and passes the
``engines.Line`` objects in.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import chess

import labels as labels_mod
from engines import Line, accuracy_from_loss, win_percent

# Re-exported so callers only need to import this module.
LabelInput = labels_mod.LabelInput
classify_data = labels_mod.classify_data
label_glyph = labels_mod.label_glyph

PIECE_VALUE = {
    chess.PAWN: 100,
    chess.KNIGHT: 320,
    chess.BISHOP: 330,
    chess.ROOK: 500,
    chess.QUEEN: 900,
    chess.KING: 0,
}


@dataclass
class Score:
    """One move, scored and labelled, in the shape both callers want."""

    # evaluation, always from the mover's point of view
    eval_before: float = 0.0
    eval_after: float = 0.0
    win_percent_before: float = 50.0
    win_percent_after: float = 50.0
    loss_pp: float = 0.0
    accuracy: float = 100.0

    best_uci: Optional[str] = None
    best_san: Optional[str] = None
    best_eval: Optional[float] = None
    best_pv: List[str] = field(default_factory=list)
    best_depth: int = 0

    second_uci: Optional[str] = None
    second_san: Optional[str] = None
    second_eval: Optional[float] = None
    gap_pp: Optional[float] = None

    # filled in by label_move()
    label: str = "best"
    glyph: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "eval_before": self.eval_before,
            "eval_after": self.eval_after,
            "win_percent_before": self.win_percent_before,
            "win_percent_after": self.win_percent_after,
            "loss_pp": self.loss_pp,
            "accuracy": self.accuracy,
            "best_uci": self.best_uci,
            "best_san": self.best_san,
            "best_eval": self.best_eval,
            "best_pv": self.best_pv,
            "depth": self.best_depth,
            "second_uci": self.second_uci,
            "second_san": self.second_san,
            "second_eval": self.second_eval,
            "gap_pp": self.gap_pp,
            "label": self.label,
            "glyph": self.glyph,
        }


def san_pv(board: chess.Board, uci_pv: Any, limit: int = 8) -> List[str]:
    """SAN for a principal variation, stopping at the first move that will not
    apply.  Kept byte-compatible with ``analyze.san_pv``."""
    if not uci_pv:
        return []
    out: List[str] = []
    b = board.copy(stack=False)
    for uci in list(uci_pv)[:limit]:
        try:
            move = b.parse_uci(uci)
        except (chess.InvalidMoveError, ValueError):
            break
        out.append(b.san(move))
        b.push(move)
    return out


def score_move(
    board: chess.Board,
    uci: str,
    *,
    before: List[Line],
    after: List[Line],
    depth: int = 0,
) -> Score:
    """Score one move from engine lines searched on ``board`` and on the
    position after ``uci``.

    ``before`` is the MultiPV search of the position before the move and
    ``after`` the search of the position after it.  Both are scored from the side
    to move, so ``after`` is negated to keep everything in the mover's frame --
    which is the convention ``data.json`` already uses.
    """
    s = Score()

    # The pv lines are scored from the side to move; flip the "after" one.
    eval_before = before[0].score_cp if before else 0.0
    eval_after = -after[0].score_cp if after else -eval_before

    s.eval_before = eval_before
    s.eval_after = eval_after
    s.win_percent_before = win_percent(eval_before)
    s.win_percent_after = win_percent(eval_after)
    s.loss_pp = max(0.0, s.win_percent_before - s.win_percent_after)
    s.accuracy = round(accuracy_from_loss(s.loss_pp), 2)

    if before:
        best = before[0]
        s.best_uci, s.best_san = best.uci, best.san
        s.best_pv = san_pv(board, best.pv)
        s.best_eval = best.score_cp
        s.best_depth = best.depth or depth

    # MultiPV=2 because "great" is defined against the runner-up: without a
    # second line there is no gap_pp and the label cannot be assigned correctly.
    if len(before) > 1:
        second = before[1]
        s.second_uci, s.second_san = second.uci, second.san
        s.second_eval = second.score_cp
        s.gap_pp = round(
            win_percent(s.best_eval or 0.0) - win_percent(second.score_cp), 2
        )
    return s


def label_move(
    s: Score,
    *,
    uci: str,
    in_book: bool,
    forced: bool,
    sacrifice: Optional[float],
    is_player: bool = True,
) -> str:
    """Assign the Lichess-style label.  Mutates ``s`` with ``label``/``glyph``
    and returns the label."""
    s.label = classify_data(
        LabelInput(
            uci=uci,
            best_uci=s.best_uci,
            loss_pp=s.loss_pp,
            win_percent_before=s.win_percent_before,
            win_percent_after=s.win_percent_after,
            gap_pp=s.gap_pp,
            sacrifice=sacrifice,
            in_book=in_book,
            forced=forced,
            is_player=is_player,
        )
    )
    s.glyph = label_glyph(s.label)
    return s.label


def first_line_move(lines: List[Line], board: chess.Board) -> Optional[chess.Move]:
    """The move the engine's top line plays on ``board``, if it is legal there."""
    if not lines or not lines[0].uci:
        return None
    try:
        return board.parse_uci(lines[0].uci)
    except (chess.InvalidMoveError, ValueError):
        return None


def material_balance(board: chess.Board, color: chess.Color) -> int:
    """Material advantage for *color*, in centipawns."""
    total = 0
    for piece_type, value in PIECE_VALUE.items():
        total += value * len(board.pieces(piece_type, color))
        total -= value * len(board.pieces(piece_type, not color))
    return total


def detect_sacrifice(
    board: chess.Board, move: chess.Move, best_reply: Optional[chess.Move],
    player: chess.Color,
) -> float:
    """Material, in pawns, that *move* gives up once the refutation is played.

    Positive means the player handed material over.  The opponent's best reply
    is used, not the opponent's worst one, so a sacrifice only counts as a
    sacrifice if it really does cost something against best defence.
    """
    bal_before = material_balance(board, player)
    after = board.copy(stack=False)
    after.push(move)
    if best_reply is not None and best_reply in after.legal_moves:
        after.push(best_reply)
    return (material_balance(after, player) - bal_before) / -100.0


def is_forced_move(board: chess.Board) -> bool:
    """True when there was only one legal move, or the mover is in check.

    A move that had no alternative is not an achievement, so "great" must not
    apply to it.
    """
    return board.is_check() or board.legal_moves.count() <= 1