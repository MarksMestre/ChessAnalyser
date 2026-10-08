"""Move labels: brilliant, great, book, best, ... blunder.

Kept separate from the engine plumbing in analyze.py so the thresholds live in
one readable place.  Every rule below is traceable to a stated condition --
nothing is a heuristic fudge factor except where noted.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple


class Label:
    BRILLIANT = "brilliant"
    GREAT = "great"
    BOOK = "book"
    BEST = "best"
    EXCELLENT = "excellent"
    GOOD = "good"
    INACCURACY = "inaccuracy"
    MISTAKE = "mistake"
    BLUNDER = "blunder"
    MISS = "miss"


LABEL_ORDER = (
    Label.BRILLIANT,
    Label.GREAT,
    Label.BOOK,
    Label.BEST,
    Label.EXCELLENT,
    Label.GOOD,
    Label.INACCURACY,
    Label.MISTAKE,
    Label.BLUNDER,
    Label.MISS,
)

GLYPHS = {
    Label.BRILLIANT: "!!",
    Label.GREAT: "!",
    Label.BOOK: "",
    Label.BEST: "",
    Label.EXCELLENT: "",
    Label.GOOD: "",
    Label.INACCURACY: "?!",
    Label.MISTAKE: "?",
    Label.BLUNDER: "??",
    Label.MISS: "!?",
}

GLYPH_COLOURS = {
    Label.BRILLIANT: "#26a69a",
    Label.GREAT: "#7e57c2",
    Label.INACCURACY: "#f9a825",
    Label.MISTAKE: "#ef6c00",
    Label.BLUNDER: "#c62828",
    Label.MISS: "#1565c0",
}


def label_glyph(label: str) -> str:
    return GLYPHS.get(label, "")


# thresholds, all in win-percentage points unless noted
BOOK_MAX_LOSS = 10.0      # above this, "book move" is not an excuse
BRILLIANT_MIN_MATERIAL = 1.5   # pawns of material given up, after best defence
BRILLIANT_MAX_LOSS = 2.0
GREAT_MIN_GAP = 10.0      # E1 - E2, i.e. "there was literally nothing else"
MISS_MIN_WIN_BEFORE = 85.0

# loss bands
BANDS: Tuple[Tuple[float, str], ...] = (
    (1.0, Label.BEST),
    (2.0, Label.EXCELLENT),
    (5.0, Label.GOOD),
    (10.0, Label.INACCURACY),
    (25.0, Label.MISTAKE),
)
BLUNDER_LABEL = Label.BLUNDER


@dataclass
class LabelInput:
    """Everything classify() is allowed to look at."""

    uci: str
    best_uci: Optional[str]
    loss_pp: float
    win_percent_before: float
    win_percent_after: float
    gap_pp: Optional[float]
    sacrifice: Optional[float]
    in_book: bool
    forced: bool
    is_player: bool = True


def by_loss(loss_pp: float) -> str:
    for threshold, label in BANDS:
        if loss_pp <= threshold:
            return label
    return BLUNDER_LABEL


def classify(rec, *, in_book: bool, forced: bool) -> str:
    """Assign the Lichess-style label for one of the player's moves."""
    if not rec.is_players_turn:
        return Label.BEST

    data = LabelInput(
        uci=rec.uci,
        best_uci=rec.best_uci,
        loss_pp=rec.loss_pp or 0.0,
        win_percent_before=rec.win_percent_before or 0.0,
        win_percent_after=rec.win_percent_after or 0.0,
        gap_pp=rec.gap_pp,
        sacrifice=rec.sacrifice,
        in_book=in_book,
        forced=forced,
    )
    return classify_data(data)


def classify_data(d: LabelInput) -> str:
    if not d.is_player:
        return Label.BEST

    matches_best = bool(d.best_uci) and d.best_uci == d.uci
    loss = d.loss_pp

    # 1. Brilliant: a sound sacrifice.
    #
    # "Sound" means the position after the opponent's best reply is not
    # materially worse for the player -- which is exactly what loss_pp measures.
    # Note there is deliberately *no* "you were not already winning" gate: the
    # classic brilliancies (Morphy's 16.Qb8+ in the Opera Game) are played from
    # a winning position, and gating on winProb would throw them away.  What
    # separates a brilliant from an ordinary good move is that material was
    # handed over for a reason, not that the player was losing.
    if (
        (d.sacrifice or 0.0) >= BRILLIANT_MIN_MATERIAL
        and loss <= BRILLIANT_MAX_LOSS
        and not d.in_book
        and not d.forced
    ):
        return Label.BRILLIANT

    # 2. Great: the engine's move, and it was the only good one
    if (
        matches_best
        and (d.gap_pp or 0.0) >= GREAT_MIN_GAP
        and not d.forced
        and not d.in_book
        and loss <= 2.0
    ):
        return Label.GREAT

    # 3. Miss: gave away a won game
    if d.win_percent_before >= MISS_MIN_WIN_BEFORE and d.win_percent_after < MISS_MIN_WIN_BEFORE:
        return Label.MISS

    # 4. Book moves are exempt from penalties, up to a point
    if d.in_book and loss <= BOOK_MAX_LOSS:
        return Label.BOOK

    return by_loss(loss)