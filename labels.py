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
#: Brilliant needs the position to still be live.
#:
#: Without this floor the `loss <= BRILLIANT_MAX_LOSS` test is vacuous in a lost
#: position. ``loss_pp`` is measured against ``win_percent_before``, so at 10%
#: winning *every* move costs at most ~10 points -- which meant a queen
#: sacrifice in a hopeless game was labelled brilliant. That is not a rare
#: edge case either: it is what happened to 16...Qe7 in a real report, where
#: the player was six pawns down and the move made the evaluation worse.
#:
#: A floor and not a ceiling, deliberately. A ceiling ("you must not already be
#: winning") would discard the classic brilliancies -- Morphy's 13.Rxd7 and
#: 16.Qb8+ are both played from a position he was already winning -- which is
#: the mistake this rule originally avoided and must keep avoiding.
BRILLIANT_MIN_WIN_BEFORE = 30.0
#: ...and the move has to leave the position acceptable.
#:
#: This is the "the sacrifice worked" test: after handing the material over, and
#: against the opponent's *best* reply, you are still at least equal. Measured in
#: the mover's frame, so it means the same thing for White and Black. Without it
#: nothing required the sacrifice to achieve anything at all.
BRILLIANT_MIN_WIN_AFTER = 50.0
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
    # "Sound" means real material was handed over (BRILLIANT_MIN_MATERIAL,
    # measured against the opponent's *best* reply), it cost almost nothing
    # (BRILLIANT_MAX_LOSS), the position was worth winning in
    # (BRILLIANT_MIN_WIN_BEFORE), and the move leaves it acceptable
    # (BRILLIANT_MIN_WIN_AFTER).
    #
    # Note there is deliberately *no* "you were not already winning" gate: the
    # classic brilliancies (Morphy's 16.Qb8+ in the Opera Game) are played from
    # a winning position, and gating on winProb from above would throw them away.
    # What separates a brilliant from an ordinary good move is that material was
    # handed over for a reason, not that the player was losing.
    #
    # The two win-percent floors are what stop a lost position from producing
    # brilliant labels by default. See the comments on the constants: without
    # them `loss <= 2.0` passes for nearly any move once you are already losing,
    # because there is little winning probability left to lose.
    if (
        (d.sacrifice or 0.0) >= BRILLIANT_MIN_MATERIAL
        and loss <= BRILLIANT_MAX_LOSS
        and d.win_percent_before >= BRILLIANT_MIN_WIN_BEFORE
        and d.win_percent_after >= BRILLIANT_MIN_WIN_AFTER
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