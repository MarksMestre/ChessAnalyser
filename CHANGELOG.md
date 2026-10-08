# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Categories used below are the ones the format defines: Added, Changed, Deprecated,
Removed, Fixed, Security.

## [Unreleased]

Nothing yet.

## [1.0.0] - 2026-10-08

First public release.

### Added

- **Per-move labelling** with MultiPV=2, so the runner-up line is visible: brilliant
  `!!`, great `!`, book, best/excellent/good, inaccuracy, mistake, blunder, and miss.
  Brilliant and great are deliberately conservative — a second pass re-verifies every
  decisive move at a deeper depth and revises the label if the deeper search disagrees.
- **Accuracy** on Lichess's published per-move curve, with game accuracy weighted by
  evaluation volatility the way Lichess does. Plain mean, harmonic mean and ACPL are
  reported alongside.
- **Per-phase accuracy** (opening / middlegame / endgame), which is how you find which
  part of your game is weak. The opening ends where book theory ends.
- **Two-pass depth strategy.** Pass 1 searches every ply at `--depth` 14 with a 2.0 s
  cap; pass 2 re-verifies only the moves that decide the report at `--focus-depth` 24
  with a 6.0 s cap. Every position is searched exactly once — the "after" evaluation of
  ply *i* is the "before" evaluation of ply *i+1*.
- **Lc0 as a second opinion** on the handful of moves where it and Stockfish disagree.
  Lc0 learned chess from self-play and carries none of the classical engine's biases, so
  it endorses creative sacrifices Stockfish scores as slightly inferior. It runs at a low
  node budget because it is orders of magnitude slower per position.
- **`fetch_games.py`** — one-shot PGN download from Chess.com or Lichess. Both platforms
  are public and login-free. Chess.com embeds each game's PGN in the monthly archive, so
  it is one request per month rather than one per game.
- **`python -m process_api.cli`** — incremental Chess.com fetcher. `metadata.json` records
  every month already fetched, and a month is skipped when it is both recorded *and*
  outside the current calendar month, because Chess.com keeps adding games to the open
  month. A steady-state run costs one request whatever the size of the archive. Games
  land one file per game deduplicated by uuid, so re-running cannot duplicate one and an
  interrupted run cannot lose one.
- **`--player me`** — an alias for your own username, resolved from `$CHESS_COACH_PLAYER`
  or `player.txt`. Every command defaults to it, so the usual run needs no username typed
  at all. An explicit name still passes through untouched.
- **`setup.py`** — installs the venv, dependencies, Stockfish, Lc0, a neural network and
  the opening book. Engine versions are resolved from the projects' GitHub releases rather
  than hardcoded, every download is checked against the sha256 the release publishes, and
  `--pin` reinstalls exactly what is recorded in `engines/INSTALL.json`. `--lc0-build`
  picks the build the hardware can run: CUDA on an NVIDIA card, the 25 MB DirectML build on
  any other DX12 GPU, CPU elsewhere.
- **A self-contained HTML report.** Dashboard with accuracy and ACPL trends, per-phase
  breakdown, best and worst games, recurring weaknesses and every brilliancy; a per-game
  view with a clickable eval graph, a move table and a board showing your move in red
  against the engine's in green; a drill mode that hides the answer; and an annotated PGN
  embedded for offline export. Piece artwork is inlined from `chess.svg`, so there are no
  network requests and the report works offline.
- **`--lc0-backend`**, and Lc0 backend discovery that asks the binary which neural
  backends it accepts and tries them best-first, because the valid set differs per build.
- **`commands.md`** — every command, every flag with its default, worked examples,
  measured runtimes and recipes.
- **`--self-test` flags** on `player.py` and `process_api/fetcher.py`, run as the last
  step of `setup.py --verify`. The repo ships no test files: the pure logic is checked by
  the modules that own it, so a check cannot drift away from the code it describes.

### Changed

- `--threads` defaults to 1. Measured on a Ryzen 5 7600X, one position on 1 thread
  finished in 0.05 s using 34k nodes; the same position on 12 threads took 0.48 s using
  3.7M nodes, and the whole game pass went from 133 s to 4 s. Raise it only when analysing
  many games concurrently.
- Per-position time caps added alongside depth. Depth alone does not bound cost — one
  awkward position at depth 22 can run for minutes — so the engine stops at whichever
  limit it hits first and reports the depth it reached.
- `Stockfish.Stockfish` 19 replaces the AVX2/AVX-512 build choice: 19 ships a universal
  binary that auto-detects the CPU.

### Fixed

- Lc0 no longer assumes a CUDA build. The old code tried only `cuda-fp16`, `cuda`,
  `cuda-auto` and `openvino`, so no DirectML or CPU install could ever start; the valid
  set is now read from the binary itself.
- `--player` on `analyze.py` is no longer silently discarded when it is not the alias, and
  a name that matches no game in the PGN is now an error naming the White and Black
  players of the first game, instead of a report full of empty games. Both were found by
  running the reference case rather than the alias path.
- DirectML builds are detected as missing `DirectML.dll`, which ships outside the release
  zip; `setup.py --verify` warns, because without it `onnx-dml` quietly runs on the CPU.

### Removed

- Test files. Verification is the real pipeline run with different arguments, plus the
  two in-module `--self-test` suites; `.gitignore` keeps new test files out.
- `001Initial.md` and the planning documents under `process_api/`, superseded by
  `README.md` and `commands.md`.

### Security

- Personal configuration is git-ignored and replaced by tracked templates:
  `player_example.txt` and `process_api/api_example.txt`. Usernames no longer appear in
  tracked source or documentation.

[unreleased]: https://github.com/MarksMestre/ChessAnalyser/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/MarksMestre/ChessAnalyser/releases/tag/v1.0.0