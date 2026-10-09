# chess-coach

Analyses your chess games with StockFish, cross-checks the interesting moves with
a neural engine (Lc0), and produces a single self-contained HTML report you can
open offline.

```
python fetch_games.py --player me --site chesscom
python analyze.py     --player me --out out
```

Then open `out\report.html`. `--player me` is an alias for your own username, so
the usual run needs no username typed at all — see `--player me` below.

> **[commands.md](commands.md)** is the full reference: every command, every flag with
> its default, worked examples, measured runtimes and recipes for common jobs.
> The [Command summary](commands.md#command-summary) at its end is a one-page cheat
> sheet. Notable changes are in [CHANGELOG.md](CHANGELOG.md).

---

## What it does

For every ply of every game, with MultiPV=2 so the runner-up line is visible:

```
evalBefore (side to move) --> best line 1  E1
 \--> best line 2  E2
play your move        --> evalAfter, flipped to your point of view

loss_pp = winProb(before) - winProb(after)      # Lichess sigmoid, k = 0.00368208
```

| Label | Rule |
|---|---|
| **Brilliant** `!!` | A sound sacrifice: material given ≥ 1.5 after the opponent's *best* reply, the move costs ≤ 2pp, the position was worth winning in (≥ 30% before) and is still acceptable afterwards (≥ 50%) |
| **Great** `!` | Your move was the engine's, and it beat the next best by ≥ 10pp — there was literally nothing else |
| **Book** | Matches a line in the lichess-openings database |
| **Best / Excellent / Good** | loss ≤ 1 / 1–2 / 2–5 |
| **Inaccuracy / Mistake / Blunder** | loss 5–10 / 10–25 / > 25 |
| **Miss** | You were winning (≥ 85%) and gave the win away |

Per-move accuracy uses Lichess's published curve,
`103.1668·e^(−0.04354·loss_pp) − 3.1669`. Game accuracy weights each move's win
percentage by the evaluation *volatility* around it, the way Lichess does, so
quiet moves count for little and the moments where the game swings carry the
score. Plain mean and harmonic mean are reported alongside, and ACPL too.

**Phases** (opening / middlegame / endgame) each get their own accuracy. The
opening ends where book theory ends. That per-phase breakdown is how you find
out which part of your game is weak.

**Brilliant vs Great are deliberately conservative.** A shallow search calls
plenty of ordinary moves brilliant because it cannot see the refutation, so a
second pass re-verifies every decisive move at a deeper depth (default 24) and
revises the label if the deeper search disagrees. Moves revised by pass 2 are
marked in the report.

### Lc0 as a second opinion

Lc0 learned chess from self-play and carries none of the human biases a
classical engine was built with, so it will endorse creative sacrifices that
StockFish scores as slightly inferior. When Lc0 picks *your* move where
StockFish rejected it, that is a signal a single StockFish cannot produce. Lc0
only runs on the handful of moves the two engines disagree about, at a low node
budget, because it is orders of magnitude slower per position than StockFish.

---

## Setup

```powershell
python setup.py
```

That is the whole install. It creates `.venv`, installs the dependencies, then
downloads and verifies everything `.gitignore` throws away: Stockfish, Lc0, a
neural network and the opening book. It finishes by probing both engines, so you
find out straight away whether the install works.

```
python setup.py                        everything, then verify
python setup.py --verify               probe what is installed, download nothing
python setup.py --skip-lc0             Stockfish only (Lc0 is optional)
python setup.py --only book            just one piece
python setup.py --lc0-build onnx-dml   25 MB DirectML build, no CUDA needed
python setup.py --force                re-download even if present
```

Engine versions are resolved from the projects' GitHub releases rather than
hardcoded, so this keeps working when Stockfish or Lc0 ship a new one, and every
download is checked against the sha256 the release publishes. What got installed
is recorded in `engines/INSTALL.json`; `--pin` reinstalls exactly those versions.

The default Lc0 build follows the hardware: the CUDA build when an NVIDIA GPU is
present, the 25 MB DirectML build on any other DX12-capable Windows machine, and
the CPU build elsewhere. Stockfish 19 uses a universal binary that auto-detects
your CPU; there is no AVX2/AVX-512 choice any more.

**Doing it by hand instead?** Stockfish: `winget install --id=Stockfish.Stockfish -e`,
or unzip a release into `engines\stockfish\`. Lc0: unzip from
<https://lczero.org/play/download/> into `engines\lc0-gpu\` (the GPU build is
picked up automatically), plus a network from
<https://lczero.org/play/networks/bestnets/> into `data\nets\`. The medium
`t3-512x15x16h` net is a good default: the 768-wide network needs ~2.6 GB of VRAM
and will thrash on a 4 GB card. Everything still works with `--no-lc0`.

Both engines and the opening book are located automatically. To override, set
`STOCKFISH_PATH` / `LC0_PATH` / `LC0_NET`, or pass the flags.

---

## Commands

This section covers the flags worth knowing about. For the complete reference —
every flag with its default and its worked examples — see
**[commands.md](commands.md)**.

### `--player me` — your own username

Every entry point wants a username, and `--player` is the one argument you should
never have to look up. Pass `me` instead:

```powershell
python fetch_games.py --player me --site chesscom
python analyze.py     --player me --out out
python -m process_api.cli --player me
```

It resolves from `$CHESS_COACH_PLAYER`, then `player.txt` in the project root.
`player.txt` is git-ignored because a username is personal; copy the template
once and fill it in:

```powershell
copy player_example.txt player.txt
```

```
# player.txt
chesscom=CHESS.COM USERNAME
lichess=LICHESS USERNAME
```

A `site=name` line applies to that platform only; a bare `name` line is the
fallback for any site without its own entry, so a single-platform player can
just write one line. Site names are forgiving — `chess.com` and `chess-com` both
mean `chesscom`. Fill in only the sites you use.

**It is an alias, not a mode.** An explicit `--player yourname` still works and
is passed through untouched, so `me` and a real name mix freely in shell history
and scripts. Every command also defaults to `me`, so `python analyze.py --out out`
is enough.

Two details worth knowing:

- **analyze.py resolves without a site**, because it matches a PGN, which is not a
  platform. A `player.txt` with only `chesscom=…` lines still resolves there: the
  bare default wins if you have one, otherwise the first configured site does.
- **a name that matches no game in the PGN is an error** instead of a report
  full of empty games. It names the White and Black players of the first game so
  you can see what to pass. Chess.com capitalises handles, so a lowercase
  `chesscom=yourname` matches an uppercase `YOURNAME` header — matching is
  case-insensitive.

### fetch_games.py — download your archive

```powershell
python fetch_games.py --player me --site lichess
python fetch_games.py --player me --site chesscom --max 200
python fetch_games.py --player me --site both --since 2024-01-01
```

Both platforms are public and need no login. Chess.com's monthly archive already
embeds each game's PGN, so it is one request per month rather than one per game.

### process_api/cli.py — download your Chess.com archive, incrementally

```powershell
python -m process_api.cli --player me --dry-run   # what would it download?
python -m process_api.cli --player me
python -m process_api.cli --verify
```

Same public API, but it only re-downloads what can have changed.
`process_api\data\metadata.json` records every month already fetched, and a month is
skipped when it is both recorded *and* outside the current calendar month — Chess.com
keeps adding games to the open month for all of it, so that one is re-checked every
run, while closed months cost nothing. In practice a steady-state run is **one
request** plus the open month, whatever the size of your archive.

Games land one file per game under `process_api\data\pgn\<YYYY-MM>\<uuid>.pgn`,
deduplicated by uuid, so re-running cannot duplicate a game and an interrupted run
cannot lose one. `--verify` re-derives what is on disk and compares it to what was
recorded, so the "already up to date" claim is checkable rather than assumed.

Everything it writes lives under `process_api\data\`, which is git-ignored: the
scripts are tracked, the data is rebuilt by the command above. Nothing else is
needed to configure it — `--player me` resolves the username. `api.txt` exists only
as an alternative way to name the account, and is not required; see
`process_api\api_example.txt`.

| Flag | Meaning |
|---|---|
| `--player` | username, or `me` |
| `--dry-run` | print the skip/fetch decision per month and exit |
| `--month YYYY-MM` | restrict to one archive |
| `--force` | ignore the skip rule, re-fetch everything |
| `--limit N` | stop after N archives |
| `--delay` | seconds between requests (default 1.0) |
| `--verify` | check recorded metadata against the PGN on disk |
| `--reset` | drop metadata so the next run re-fetches (`--delete-pgn` removes the files) |

It writes everything under `process_api\data\`, which is git-ignored: the scripts
are tracked, the data is regenerated by the command above. It needs no
configuration file — `--player me` resolves the username.

### analyze.py — analyse

```powershell
python analyze.py --player me --out out
```

Useful flags — the full list is in [commands.md](commands.md#5-analyzepy--analyse-games):

| Flag | Default | Meaning |
|---|---|---|
| `--depth` | 14 | pass 1 survey depth, every ply |
| `--focus-depth` | 24 | pass 2 depth for the moves that decide the report |
| `--survey-time` | 2.0 | seconds per position in pass 1 |
| `--focus-time` | 6.0 | seconds per position in pass 2 |
| `--threads` | 1 | see the note below |
| `--no-lc0` | off | StockFish only |
| `--lc0-nodes` | 3000 | Lc0 budget per position |
| `--lc0-backend` | auto | force a backend (`onnx-dml`, `blas`, …) |
| `--limit` | 0 | analyse only the first N games |

**On the Lc0 backend:** there is nothing to configure. The installed build is
asked which neural backends it accepts and they are tried best-first, because the
valid set differs per build — a CUDA build takes `cuda-auto`/`cuda`/`cuda-fp16`,
the DirectML build takes `onnx-dml`/`onnx-cpu`/`onnx-cuda`/`onnx-trt`, a CPU build
takes `blas`/`eigen`. `setup.py --verify` prints what yours supports.
`--lc0-backend` forces one when the automatic choice is wrong.

The DirectML build also needs `DirectML.dll` beside `lc0.exe`, which ships
separately: run `install.cmd` in the Lc0 folder. `setup.py --verify` warns when
it is absent, because without it `onnx-dml` quietly runs on the CPU instead.

**On `--threads`:** the default is 1, and that is not a mistake. This searches
one position at a time, so StockFish's multi-threaded search mostly pays
helper-thread overhead and contention. Measured on a Ryzen 5 7600X, one position
searched on 1 thread finished in 0.05 s using 34k nodes; the same position on 12
threads took 0.48 s using 3.7M nodes. The whole game pass went from 133 s to
4 s. Raise it only if you are analysing many games concurrently.

**On the time caps:** depth alone does not bound cost. One awkward position at
depth 22 can run for minutes, so a game with a few of them would blow past any
sensible runtime. The engine stops at whichever of depth or time it hits first
and reports the depth it actually reached.

### report.py — re-render

```powershell
python report.py --data out\data.json --out out\report.html
```

Regenerates the HTML without re-running the engine, so you can iterate on the
report after an analysis run.

---

## Output

```
out\
├─ data.json        everything: per-move labels, evals, accuracy, PVs
├─ annotated.pgn    standard PGN, importable into Lichess, En Croissant, SCID
└─ report.html      one self-contained file, opens from file://
```

The HTML has five sections: a **dashboard** (accuracy and ACPL trends, per-phase
breakdown, best and worst games, a recurring-weaknesses panel, and every
brilliancy); a **per-game** view with a clickable eval graph, a move table and a
board showing your move in red against the engine's move in green; a **drill
mode** that hides the answer and reveals the engine line after you pick;
**brilliancies** with the PV that proves each one worked; and **export**, with
the annotated PGN embedded so the download works offline.

Piece artwork is inlined from `chess.svg`, which embeds the SVG paths rather
than linking external files, so there are no network requests and the report
works on a plane.

---

## The interactive report

The HTML above is the offline artefact. There is also a full app, for reading a
whole archive rather than one file:

```
python report.py --pack --out out\pack     # once, to split the data
python serve.py                            # http://127.0.0.1:8000/report.html/
```

**Overview** leads with your rating over time, then accuracy against opponent
strength, the accuracy trend, the per-phase breakdown, recurring weaknesses,
every brilliancy, and the best and worst games. Your name heads it, followed by
one line per platform account — `Chess.com: MARK8HS · 5 games | LICHESS.ORG:
mark8hs · no games` — because `--player me` has a *different* username per site.
A site you have configured but that contributed no games to this run is listed
and dimmed rather than dropped, so "you do not have that account" and "this
report happens to be Chess.com-only" do not look the same.

**Each game** gets a page at `/report.html/games/<id>`: the board on the left
with the player's bars above and below, and on the right the move's
classification and the engines' commentary **above** the move list, the list
itself with an evaluation bar per half-move, and a transport with keyboard
shortcuts. The arrow keys step through the game, `←`/`→`, `Home`/`End`, space to
play, `f` flips the board and `Backspace` steps back one. The board shows the
position **after** the selected move, so it always agrees with the move you
clicked. The opening tab names the move where the game left theory — *"left
theory on 3. g3"* — because that is the first move judged on its own merits
rather than against a book line.

**The board is playable.** Pick up a piece on the game page and the board answers
with its legal destinations. Play the move the game played and the review carries
on; play any other move and a **variation** opens under the move it diverges
from, and the rest of that line is yours to play. A fork move is judged by the
same engine and the same thresholds as a recorded one. The variation appears as a
single indented continuation line — the way a score book sets one — and never
displaces the recorded game. An amber banner tells you when you are inside one and
offers a way back; auto-play is disabled there, because it follows the recorded
game and has nothing to walk from a position that is not in it. `←`/`→` step along
whichever line you are on, and `Backspace` removes a fork move or steps back a
ply.

**You can keep playing from scratch.** `/report.html/games/<id>/play` starts the
position at any move and lets you play on from it — castling, en passant and
promotion all work, because a real rules engine is checking them. Both sides are
yours; there is no engine opponent. Stockfish is an advisor instead: it judges
each move you make using *the same thresholds* the batch analysis used, so a move
you play by hand and a move you played years ago are scored the same way, and it
draws the **1–3 best moves** for the position as translucent grey arrows, ranked
by opacity, with a `1`/`2`/`3` selector it remembers. Without the server the
board still works — you just lose the arrows and the scoring, and moves it cannot
judge are marked *not scored* rather than shown with a placeholder verdict.

**Drill** (`/report.html/games/<id>/drill`) hides the answer and reveals it after
you choose — either every one of your moves, or just the ones labelled an
inaccuracy, a mistake or a blunder, which is usually what you actually want.

### Why the data is split

`data.json` is about 70 KB *per game*, so a 3089-game archive is ~216 MB — far
too much to load into one page. `--pack` writes a light index plus one file per
game, fetched when you open that game. Against a five-game archive the index is
10% of the original, so the whole thing stays responsive.

The offline guarantee still holds. `python report.py --standalone` folds the app,
its artwork and the data into a single HTML file that opens from `file://` with
no network and no console errors. Past a few dozen embedded games the file gets
large, so beyond that cap the app says so rather than showing you an empty page;
`python serve.py` has no such limit.

See **[commands.md](commands.md)** for every flag.

---

## Verifying it

There are no test files in this repo. The pure logic — the `--player me` alias and
the archive skip rule — is checked by a `--self-test` flag on the module that owns
it, so a check cannot drift away from the code it describes:

```powershell
python setup.py --verify                              # runs both, last step
python player.py --self-test                          # 43 checks, the alias
python -m process_api.fetcher --self-test             # 23 checks, the skip rule
```

Both are offline, take under a second, and touch nothing outside a temp directory.

To confirm the *engines* work rather than the logic, `games\opera.pgn` is Morphy
vs the Duke of Brunswick and Count Isouard, Paris 1858 — the game with the famous
16.Qb8+ queen sacrifice.

```powershell
python analyze.py --pgn games\opera.pgn --player Morphy --out out_test
```

The engine finds both real sacrifices and nothing spurious:

```
 7. Qb3   Great !      16pp better than the next best
10. Nxb5  Great !      26pp better than the next best
11. Bxb5+ Great !      42pp better than the next best
13. Rxd7  Brilliant !!  sacrifice 1.8, engine still approves, verified d24
16. Qb8+  Brilliant !!  sacrifice 9.0, engine still approves, verified d24
17. Rd8#  Great !      mate
```

For comparison, `games\opera.pgn` is the reference case and every number in the
rest of this README came out of an actual run against it.

---

## Notes on the labelling

A few decisions are worth knowing about, because they are judgement calls
rather than facts pulled from a formula:

- **Brilliant has no "you were not already winning" gate.** The plan proposed
  requiring `winProb(before) < 0.85`, but that discards precisely the most famous
  brilliancies: Morphy's 16.Qb8+ is played from a winning position. What makes a
  move brilliant is that material was handed over *for a reason*, not that the
  player was losing.
- **The sacrifice is measured against the opponent's best reply,** not against
  what they actually played, so a sacrifice that only works because the opponent
  blundered does not count.
- **Book moves are exempt up to 10pp of loss.** Engines score theory moves
  differently from how humans are taught to play them, so penalising them would
  be measuring the book, not you.
- **Castling and forced moves are never "great."** When there was only one legal
  move, "it was the only good move" is not an achievement.