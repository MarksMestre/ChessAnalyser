"""data.json -> a report *pack* the React app can load incrementally.

Why this exists
---------------
`data.json` is roughly 70 KB **per game** -- measured at 349 KB for five games.
A 3089-game archive, which is the size README.md talks about, is therefore
around 216 MB. The legacy report inlines all of it into one HTML page, which no
browser opens happily.

So the full `data.json` stays exactly as it is -- nothing about the analysis
changes -- and this module derives a *pack* from it:

    out/pack/
    report.json          dashboard, ratings, and a light index of every game
    games/<index>.json   one game's full move list, fetched when it is opened

The split point matters. The index keeps everything the Overview and the game
list need to draw (title, result, accuracy, counts, the eval curve) and drops
`moves[]`, which is the bulk.

This module knows nothing about HTTP; `serve.py` reads the pack off disk.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

# Keys copied verbatim into the index. Anything under "moves" is excluded by
# construction -- the whole point of the split.
INDEX_FIELDS = (
    "headers",
    "index",
    "player_color",
    "player_name",
    "opening",
    "eco",
    "book_end_ply",
    "accuracy",
    "accuracy_harmonic",
    "accuracy_mean",
    "acpl",
    "phase_accuracy",
    "eval_curve",
    "counts",
    "result",
    "player_result",
    "analysis_seconds",
)

# Games whose detail is too large to inline into a standalone file are marked
# rather than silently missing, so the UI can say so instead of showing a
# half-empty page.
EMBED_LIMIT_MARKER = "_not_embedded"


def game_index_entry(game: Dict[str, Any]) -> Dict[str, Any]:
    """Everything about a game except its move list."""
    return {k: game[k] for k in INDEX_FIELDS if k in game}


def game_detail(game: Dict[str, Any]) -> Dict[str, Any]:
    """The full record for one game, including `moves`."""
    return dict(game)


def build_pack(data: Dict[str, Any]) -> Dict[str, Any]:
    """Return ``{"report": ..., "games": {index: detail}}``.

    Kept as one pure function so the shape can be asserted in a self-test
    without touching the filesystem.
    """
    games = data.get("games") or []
    dashboard = dict(data.get("dashboard") or {})

    index = [game_index_entry(g) for g in games]

    # `trend` is what the legacy dashboard drew. It carries a `title` that is not
    # in the game record itself, so it is kept as-is: the Overview needs exactly
    # this shape and rebuilding it would be churn for no gain.
    dashboard["games_index"] = index

    report = {
        "generated": data.get("generated", ""),
        "player": data.get("player", ""),
        # Carried through verbatim. It is a top-level key rather than a
        # dashboard one because it describes the *reader*, not the games -- and
        # omitting it is what made the header print the literal alias "me".
        "player_identities": data.get("player_identities", []),
        "settings": data.get("settings", {}),
        "elapsed_seconds": data.get("elapsed_seconds", 0),
        "dashboard": dashboard,
        "games": index,
    }
    return {"report": report, "games": {g["index"]: game_detail(g) for g in games}}


def self_test() -> int:
    """Check the split shape. Offline, writes nothing.

    Lives here for the reason the rest of the repo's self-tests live where they
    do: these describe the contract of the code above them, so they cannot drift
    away from it.
    """
    import sys

    checks = 0
    failures: List[str] = []

    def check(label: str, got, want) -> None:
        nonlocal checks
        checks += 1
        if got != want:
            failures.append(f"{label}: got {got!r}, want {want!r}")

    def sample_game(index: int = 1, plies: int = 40) -> Dict[str, Any]:
        """A game shaped like a real one: 40 plies, each with a legal-move list.

        The size win comes almost entirely from those `legal` lists plus the
        per-ply FENs, so a fixture with three empty plies would not exercise the
        thing the split exists for.
        """
        return {
            "headers": {"White": "a", "Black": "b", "Result": "1-0"},
            "index": index,
            "player_color": "white",
            "player_name": "me",
            "opening": "English Opening",
            "eco": "A10",
            "book_end_ply": 2,
            "accuracy": 71.2,
            "accuracy_harmonic": 62.0,
            "accuracy_mean": 70.1,
            "acpl": 5.4,
            "phase_accuracy": {"opening": {"moves": 2, "accuracy": 80.0, "acpl": 1.0}},
            "eval_curve": [0.0, 12.0, 8.0, 10000],
            "counts": {"blunder": 0, "mistake": 1},
            "result": "1-0",
            "player_result": "win",
            "analysis_seconds": 12.5,
            "moves": [
                {
                    "ply": i,
                    "san": "e4",
                    "uci": "e2e4",
                    "fen": "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
                    "fen_after": "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1",
                    "best_pv": ["e4", "e5", "Nf3", "Nc6", "Bb5", "a6"],
                    "legal": [f"{chr(97 + j)}{k}:{chr(97 + j)}{k + 1}" for j in range(8)
                             for k in range(1, 7)],
                }
                for i in range(plies)
            ],
        }

    data = {
        "generated": "2026-10-08T17:25:27",
        "player": "mark8hs",
        "player_identities": [
            {"site": "Chess.com", "name": "MARK8HS", "games": 2,
             "player_color": "black"},
            {"site": "LICHESS.ORG", "name": "mark8hs", "games": 0,
             "player_color": None},
        ],
        "settings": {"depth": 14, "stockfish": "Stockfish 19"},
        "elapsed_seconds": 900,
        "dashboard": {"games": 2, "trend": [{"index": 1}, {"index": 2}],
                      "totals": {"accuracy_mean": 65.0}},
        "games": [sample_game(1), sample_game(2)],
    }

    built = build_pack(data)
    report, games = built["report"], built["games"]

    # -- the split itself ----------------------------------------------------
    check("index has one entry per game", len(report["games"]), 2)
    check("index drops moves", "moves" in report["games"][0], False)
    check("index keeps accuracy", report["games"][0]["accuracy"], 71.2)
    check("index keeps eval_curve", len(report["games"][0]["eval_curve"]), 4)
    check("index keeps counts", report["games"][0]["counts"]["mistake"], 1)
    check("index keeps phase_accuracy", "opening" in report["games"][0]["phase_accuracy"], True)
    check("detail keeps moves", len(games[1]["moves"]), 40)
    check("dashboard survives", report["dashboard"]["totals"]["accuracy_mean"], 65.0)
    check("ratings absent is absent, not invented", "ratings" in report["dashboard"], False)
    check("player recorded", report["player"], "mark8hs")
    # The per-site identities must survive the split, or the header falls back to
    # a single name and the whole point of `player.txt` is lost.
    check("identities reach the report", len(report["player_identities"]), 2)
    check("identity site survives", report["player_identities"][0]["site"], "Chess.com")
    check("identity game count survives",
          report["player_identities"][0]["games"], 2)
    check("an identity with no games still travels",
          report["player_identities"][1]["games"], 0)
    check("a pack with no identities is empty, not missing",
          build_pack({"games": [], "dashboard": {}})["report"]["player_identities"], [])

    # The index is what keeps the payload small, and it is the whole reason this
    # module exists: measured against the real 5-game archive the index is ~10%
    # of data.json, so a 3089-game archive loads in tens of KB rather than ~216 MB.
    import json as _json
    full = len(_json.dumps(data))
    packed = len(_json.dumps(report))
    check("pack is smaller than data.json", packed < full, True)
    check("pack is at most a third of data.json", packed * 3 <= full, True)

    # -- games keyed by index, so /api/games/<n> is a dict lookup ------------
    check("keys are ints", sorted(games), [1, 2])
    check("empty archive does not crash",
          build_pack({"games": [], "dashboard": {}})["report"]["games"], [])

    print(f"pack: {checks - len(failures)}/{checks} checks passed")
    for problem in failures:
        print(f"  FAIL {problem}", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(self_test())


def write_pack(data: Dict[str, Any], out_dir: str, *,
               embed_limit: int = 0) -> str:
    """Write the pack to *out_dir*. Returns the directory written.

    ``embed_limit`` caps how many games get their move list written into
    ``report.json`` itself, for the standalone single-file build. Games past the
    cap are indexed but carry ``_not_embedded`` so the UI can explain itself.
    """
    pack = build_pack(data)
    report = pack["report"]
    games = pack["games"]

    os.makedirs(out_dir, exist_ok=True)
    games_dir = os.path.join(out_dir, "games")
    os.makedirs(games_dir, exist_ok=True)

    for index, detail in games.items():
        with open(os.path.join(games_dir, f"{index}.json"), "w", encoding="utf-8") as fh:
            json.dump(detail, fh)

    inlined: Dict[int, Any] = {}
    if embed_limit > 0:
        for index, detail in list(games.items())[:embed_limit]:
            inlined[index] = detail
    report["inlined_games"] = sorted(inlined)

    # Tell the index which games a reader of this file can actually open.
    if embed_limit > 0:
        for entry in report["games"]:
            if entry["index"] not in inlined:
                entry[EMBED_LIMIT_MARKER] = True

    with open(os.path.join(out_dir, "report.json"), "w", encoding="utf-8") as fh:
        json.dump({**report, "inlined": inlined}, fh)

    return out_dir


def load_pack(pack_dir: str) -> Optional[Dict[str, Any]]:
    """Read the pack off disk, or None when it has not been built yet."""
    report_path = os.path.join(pack_dir, "report.json")
    if not os.path.isfile(report_path):
        return None
    with open(report_path, "r", encoding="utf-8") as fh:
        report = json.load(fh)
    return {
        "report": report,
        "games": {int(k): v for k, v in (report.get("inlined") or {}).items()},
    }


def load_game(pack_dir: str, index: int) -> Optional[Dict[str, Any]]:
    """One game's detail, from ``games/<index>.json``."""
    path = os.path.join(pack_dir, "games", f"{int(index)}.json")
    if not os.path.isfile(path):
        return None
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def pack_size(pack_dir: str) -> Dict[str, int]:
    """Byte counts, so the server can report how big the archive really is."""
    report_path = os.path.join(pack_dir, "report.json")
    out = {"report": 0, "games": 0, "games_count": 0}
    if os.path.isfile(report_path):
        out["report"] = os.path.getsize(report_path)
    games_dir = os.path.join(pack_dir, "games")
    if os.path.isdir(games_dir):
        for name in os.listdir(games_dir):
            if name.endswith(".json"):
                out["games"] += os.path.getsize(os.path.join(games_dir, name))
                out["games_count"] += 1
    return out