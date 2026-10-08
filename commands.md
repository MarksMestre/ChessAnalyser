# commands.md

Complete reference for every command in this project: what each one does, every flag,
worked examples, and the recipes for common jobs.

All examples assume Windows PowerShell from the project root (`C:\Projs\ChessAnalyser`).

---

## Contents

| Section | Command | Purpose |
|---|---|---|
| [Setup](#1-setup) | `setup.py` | install venv, engines, network, book |
| [Configuration](#2-configuration---player-me) | `player.txt` | your username behind `--player me` |
| [Fetch](#3-fetch_gamespy--download-games) | `fetch_games.py` | one-shot PGN download |
| [Fetch incrementally](#4-process_apicli--incremental-fetch) | `python -m process_api.cli` | re-runnable, skips what it has |
| [Analyse](#5-analyzepy--analyse-games) | `analyze.py` | the engine run |
| [Re-render](#6-reportpy--re-render-the-report) | `report.py` | rebuild HTML without re-analysing |
| [Verifying](#7-verifying-a-change) | `--self-test` | check a change without a test suite |
| [Recipes](#8-recipes) | — | common end-to-end jobs |
| [Environment variables](#9-environment-variables) | — | override engine paths |
| [Exit codes](#10-exit-codes) | — | scripting and CI |

---

## Quick start

If everything is installed already:

```powershell
python fetch_games.py --player me --site chesscom
python analyze.py     --player me --out out
```

Then open `out\report.html`.

From a clean machine:

```powershell
python setup.py                    # venv + deps + engines + net + book, then verify
python fetch_games.py --player me --site chesscom
python analyze.py     --player me --out out
```

---

## 1. `setup.py`

Installs everything the project downloads: the virtualenv, Python dependencies,
Stockfish, Lc0, a neural network and the opening book. Every download is checked
against the sha256 the upstream project publishes, and engine versions are resolved
from GitHub releases rather than hardcoded.

```powershell
python setup.py
```

### Steps

The five steps run in this order. Each can be selected with `--only` or skipped
with `--skip`.

| Step | What it installs | Size | Notes |
|---|---|---|---|
| `venv` | `.venv\` + `requirements.txt` | ~7 MB | skipped if `.venv` already exists |
| `stockfish` | `engines\stockfish\` | ~98 MB | universal binary, auto-detects your CPU |
| `lc0` | `engines\lc0-gpu\` or `lc0-cpu\` | 25 MB – 582 MB | GPU build by default |
| `net` | `data\nets\*.pb.gz` | ~146 MB | `t3-512x15x16h`, a safe default |
| `book` | `data\openings\*.tsv` | ~4 MB | CC0, from lichess-org |

### Flags

| Flag | Default | Meaning |
|---|---|---|
| `--only STEP...` | all five | run only these steps. One of `venv`, `stockfish`, `lc0`, `net`, `book` |
| `--skip STEP...` | none | skip these steps. Same values as `--only` |
| `--verify` | off | probe what is installed, download nothing |
| `--no-verify` | off | skip the verification pass at the end |
| `--force` | off | re-download and reinstall even if already present |
| `--pin` | off | reinstall exactly the versions in `engines\INSTALL.json` |
| `--lc0-build NAME` | `auto` | which Lc0 build. See the table below |
| `--net FILE` | `t3-512x15x16h-distill-swa-2767500.pb.gz` | network filename to fetch |
| `--python EXE` | current interpreter | interpreter used to create the venv |

### `--lc0-build` values

| Value | Size | Needs |
|---|---|---|
| `auto` | varies | picks for your hardware (default) |
| `onnx-dml` | 25 MB | any DX12 GPU — AMD, Intel, NVIDIA. **Use this without an NVIDIA card** |
| `cuda12` | 582 MB | NVIDIA GPU + CUDA 12 |
| `cuda12-nodll` | ~100 MB | NVIDIA, ships without CUDA runtime |
| `cuda11` | ~500 MB | NVIDIA, CUDA 11 |
| `cpu-openblas` | ~22 MB | nothing — runs on CPU |
| `cpu-dnnl` | ~50 MB | nothing — runs on CPU, Intel-optimised |

`auto` uses `cuda12` when an NVIDIA GPU is detected, `onnx-dml` on any other
DX12-capable Windows machine, and a CPU build elsewhere.

### Examples

```powershell
# Everything, then verify
python setup.py

# Check the install without downloading anything (safe, fast, offline)
python setup.py --verify

# Stockfish only; skip the large Lc0 download entirely
python setup.py --skip-lc0

# Just the opening book
python setup.py --only book

# Just the venv and dependencies, reinstalled
python setup.py --only venv --force

# No NVIDIA GPU? Get the 25 MB DirectML build
python setup.py --only lc0 --lc0-build onnx-dml --force

# Downgrade to a smaller network (146 MB -> 37 MB)
python setup.py --only net --net t1-256x10-distilled-swa-2432500.pb.gz

# Reinstall the exact versions already recorded in engines\INSTALL.json
python setup.py --pin

# Replace a working install with a different Lc0 build
python setup.py --only lc0 --lc0-build cpu-openblas --force
```

### Gotchas

**`python setup.py` does not reinstall dependencies into an existing `.venv`.**
`step_venv` runs `pip install` only when it just created the venv or when
`--force` is passed. If you already have a `.venv` and want the dependencies
(re)installed, you must pass `--force`:

```powershell
python setup.py --only venv --force
```

Otherwise install directly:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

**Both Lc0 builds ship an identically named `lc0.exe`.** Replacing one with
another via `--force` is fine, but copying one by hand into the other folder is
not — `setup.py` warns when it detects a known different build being replaced.

**A DirectML build needs `DirectML.dll`,** which is not in the release zip. Run
`install.cmd` in the Lc0 folder, or `onnx-dml` silently falls back to the CPU.
`python setup.py --verify` warns when it is missing.

### What `--verify` prints

```
==> verification
    Stockfish: engines\stockfish\stockfish-windows-x86-64-universal.exe
      98.3 MB binary, ready for analyze.py
    Lc0: engines\lc0-gpu\lc0.exe
      net t3-512x15x16h.pb.gz (146.0 MB)
      backends onnx-dml, onnx-cpu, onnx-cuda, onnx-trt
    opening book: 3,865 entries
    stockfish: {'binary': 'engines\\stockfish\\stockfish-windows-x86-64-universal.exe'}
    lc0: {'binary': 'engines\\lc0-gpu\\lc0.exe', 'build': 'onnx-dml', 'tag': 'v0.32.1', ...}
    net: t3-512x15x16h.pb.gz
==> self-tests
player: 43/43 checks passed
fetcher: 23/23 checks passed
```

The last step runs the two in-module self-tests described in
[Verifying a change](#7-verifying-a-change), so one command covers both the
install and the logic.

Exit code 0 means everything is usable, 1 means something is missing or broken.

---

## 2. Configuration — `--player me`

Every command wants a username. Rather than type it into every invocation, put
it in `player.txt` in the project root and pass `me`.

### Creating `player.txt`

`player.txt` is git-ignored, because a username is personal. The template is
tracked, so a fresh clone has it. Copy it once and fill in your own names:

```powershell
copy player_example.txt player.txt
```

```
# player.txt
chesscom=CHESS.COM USERNAME
lichess=LICHESS USERNAME
```

If you only play on one platform, delete the other line — or use a single bare
line, which applies to every site:

```
chesscom=yourname
```

Site names are forgiving — `chess.com`, `chess-com` and `chess_com` all mean
`chesscom`. `#` starts a comment.

### Resolution order

1. An explicit name: `--player yourname` — passed through untouched, always wins.
2. `$CHESS_COACH_PLAYER` — a one-off override that touches no file.
3. `player.txt`.
4. Nothing found → exit 2 with instructions.

`me` is case-insensitive and ignores surrounding whitespace, so `--player Me`
works. Every command also **defaults** to `me`, so `--player` can be omitted.

`analyze.py` resolves without a site, because it matches a PGN and a PGN is not a
platform. A `player.txt` with only `chesscom=` lines still resolves there: the
bare default wins if you have one, otherwise the first configured site does.

### Overriding per run

```powershell
# someone else's games
python analyze.py --player Morphy --pgn games\opera.pgn --out out_test

# a one-off, without editing player.txt
$env:CHESS_COACH_PLAYER = "someotheruser"
python fetch_games.py --player me --site lichess
```

---

## 3. `fetch_games.py` — download games

Downloads a PGN archive from Chess.com and/or Lichess into one file. Both platforms
are public and need no login or API key.

```powershell
python fetch_games.py --player me --site chesscom
```

### Flags

| Flag | Default | Meaning |
|---|---|---|
| `--player NAME` | `me` | username on the platform, or `me` for the one in `player.txt` |
| `--site SITE` | `lichess` | `lichess`, `chesscom`, or `both` |
| `--out PATH` | `games\raw.pgn` | output PGN path |
| `--max N` | `0` (no limit) | cap the number of games downloaded |
| `--since DATE` | none | only games on or after `YYYY-MM-DD` |
| `--append` | off | append to the output instead of overwriting |
| `--quiet` | off | only report problems |

### `--site` values

| Value | API used | Cost |
|---|---|---|
| `lichess` | `GET /api/games/user/{user}` | 1 request for all games, PGN inline |
| `chesscom` | `GET /pub/player/{user}/games/archives`, then one per game | ~1 request per month |
| `both` | both of the above | sums them |

Chess.com embeds each game's PGN in the monthly archive, so it is one request per
*month* rather than one per game. A 49-month archive is ~49 requests at the 1 s
default delay.

### Examples

```powershell
# Your Chess.com archive
python fetch_games.py --player me --site chesscom

# Just the 50 most recent games, for a quick test
python fetch_games.py --player me --site chesscom --max 50

# Only last year's games
python fetch_games.py --player me --site chesscom --since 2025-01-01

# Both platforms into one file
python fetch_games.py --player me --site both --out games\all.pgn

# Add to an existing archive rather than replacing it
python fetch_games.py --player me --site chesscom --append

# A different player, without touching player.txt
python fetch_games.py --player yourname --site chesscom
```

### Behaviour

- **Overwrites** `games\raw.pgn` unless `--append` is given.
- Prints `Next: python analyze.py --player ...` when finished, so the next step
  is copy-pasteable.
- Exits 1 with "No games downloaded" if the username yields nothing — which is
  also what a 404 looks like, so check the spelling.

---

## 4. `python -m process_api.cli` — incremental fetch

Same public API, but re-runnable. It only re-downloads what can have changed, which
matters once your archive is thousands of games.

```powershell
python -m process_api.cli --player me --dry-run
python -m process_api.cli --player me
```

### How the skip rule works

`process_api\data\metadata.json` records every month already fetched. A month is
skipped when it is both recorded *and* outside the current calendar month — Chess.com
keeps adding games to the open month for all of it, so that one is re-checked on
every run while closed months cost nothing.

In practice a steady-state run is **one request** plus the open month, whatever
the size of your archive.

Games land one file per game under `process_api\data\pgn\<YYYY-MM>\<uuid>.pgn`,
deduplicated by uuid, so re-running cannot duplicate a game and an interrupted
run cannot lose one.

Everything it writes lives under `process_api\data\`, which is git-ignored — the
scripts are tracked, the data is rebuilt by this command. No configuration file
is required: `--player me` resolves the username. `api.txt` is an optional
alternative way to name the account; see `process_api\api_example.txt`.

### Flags

| Flag | Default | Meaning |
|---|---|---|
| `--player NAME` | `me` | username on Chess.com |
| `--dry-run` | off | print the skip/fetch decision per month and exit. Makes one request |
| `--force` | off | ignore the skip rule, re-fetch everything |
| `--month YYYY-MM` | none | restrict to one archive |
| `--delay SECONDS` | `1.0` | seconds between requests |
| `--limit N` | `0` (no limit) | stop after N archives |
| `--verify` | off | check recorded metadata against the PGN on disk |
| `--reset` | off | drop metadata so the next run re-fetches |
| `--delete-pgn` | off | with `--reset`, also delete the stored PGN files |
| `--quiet` | off | only report problems |

### `--dry-run` output

```
player: yourname
Archive list: 49 month(s) for yourname
  skip   2021-03
  ...
  skip   2026-04
  skip   2026-06
  fetch  2026-10  (stale)
48 month(s) up to date, 0 fetched, 0 failed, 0 new game(s) written, 3089 total on disk
```

`skip` means the metadata says it is complete; `fetch (stale)` marks the open
calendar month, which is always re-checked.

### `--verify`

Re-derives what is on disk and compares it to what was recorded, so the "already up
to date" claim is checkable rather than assumed. Offline — no network.

```
OK: 49 archive(s) recorded, 3089 game(s) on disk
```

Exit 0 clean, 1 if anything disagrees.

### Examples

```powershell
# Always do this first: one cheap request, tells you everything
python -m process_api.cli --player me --dry-run

# The normal run
python -m process_api.cli --player me

# Confirm what is on disk matches the metadata
python -m process_api.cli --verify

# Backfill one specific month
python -m process_api.cli --month 2024-06

# Faster (less polite) - still fine occasionally
python -m process_api.cli --delay 0.3

# Start over: forget the metadata but keep the PGN
python -m process_api.cli --reset

# Start truly over: metadata and stored PGN both gone
python -m process_api.cli --reset --delete-pgn

# Force a full re-download
python -m process_api.cli --force
```

### Known bug

**`--month YYYY-MM` currently rejects every value**, including valid ones like
`2024-06`. The validation passes `"/games/2024-06"` to a function whose regex
expects `"/games/2024/06"`, so the dash never matches. Until that is fixed, use
`--limit` or `--force` instead, or backfill a month by deleting its entry from
`process_api\data\metadata.json`. **Verify before trusting my other claims here —
I found this by reading the code, not by running it.**

---

## 5. `analyze.py` — analyse games

The engine run. Searches every position with StockFish, labels every move,
optionally cross-checks the interesting ones with Lc0, and writes an HTML report.

```powershell
python analyze.py --player me --out out
```

### The two passes

| Pass | Positions | Depth | Time cap | Purpose |
|---|---|---|---|---|
| 1 — survey | every ply | `--depth` (14) | `--survey-time` (2.0 s) | label every move |
| 2 — focus | decisive moves only | `--focus-depth` (24) | `--focus-time` (6.0 s) | verify brilliancies |

Pass 2 exists because a shallow search calls plenty of ordinary moves brilliant —
it cannot see the refutation. Moves revised by pass 2 are marked in the report.

### Flags

#### Input and output

| Flag | Default | Meaning |
|---|---|---|
| `--pgn PATH` | `games\raw.pgn` | input PGN. Accepts any file |
| `--player NAME` | `me` | player to score, matched against the PGN headers |
| `--out DIR` | `out` | output directory, created if absent |
| `--limit N` | `0` (no limit) | analyse only the first N games |
| `--no-book` | off | ignore the opening book — nothing is labelled `Book` |
| `--no-report` | off | skip HTML generation, write `data.json` only |
| `--quiet` | off | only report problems |

#### Pass 1 and pass 2 search

| Flag | Default | Meaning |
|---|---|---|
| `--depth N` | `14` | pass 1 depth, every ply |
| `--focus-depth N` | `24` | pass 2 depth for the moves that decide the report |
| `--survey-time SECONDS` | `2.0` | time cap per position in pass 1. `0` = no cap |
| `--focus-time SECONDS` | `6.0` | time cap per position in pass 2. `0` = no cap |

Depth alone does not bound cost: one awkward position at depth 22 can run for
minutes. The engine stops at whichever of depth or time it hits first and reports
the depth it actually reached. `0` disables a cap, which is how you ask for a pure
depth-limited search — usually a mistake.

#### StockFish

| Flag | Default | Meaning |
|---|---|---|
| `--stockfish PATH` | auto-discovered | path to the binary |
| `--threads N` | `1` | search threads. See the note below |
| `--hash MB` | `512` | hash table size |

**On `--threads`:** the default of 1 is not a mistake. This searches one position
at a time, so multi-threaded search mostly pays helper-thread overhead and
contention. Measured on a Ryzen 5 7600X, one position on 1 thread finished in
0.05 s using 34k nodes; the same position on 12 threads took 0.48 s using 3.7M
nodes. The whole game pass went from 133 s to 4 s. Raise it only if you are
analysing many games concurrently.

#### Lc0 (the second opinion)

| Flag | Default | Meaning |
|---|---|---|
| `--no-lc0` | off | StockFish only |
| `--lc0 PATH` | auto-discovered | path to the Lc0 binary |
| `--lc0-net PATH` | auto-discovered | path to a `.pb.gz` network |
| `--lc0-backend NAME` | auto | force a neural backend |
| `--lc0-nodes N` | `3000` | node budget per cross-checked position |
| `--lc0-max-moves N` | `12` | max moves to cross-check per game |

`--lc0-backend` rarely needs setting: the installed build is asked which backends
it accepts and they are tried best-first, because the valid set differs per build —
a CUDA build takes `cuda-auto`/`cuda`/`cuda-fp16`, a DirectML build takes
`onnx-dml`/`onnx-cpu`/`onnx-cuda`/`onnx-trt`, a CPU build takes `blas`/`eigen`.
Use the flag when the automatic choice is wrong.

Lc0 runs only on the handful of moves where Stockfish and Lc0 disagree, capped by
`--lc0-max-moves`. It is orders of magnitude slower per position than StockFish, so
`--lc0-nodes` is the main cost dial.

### Output

```
out\
 ├─ data.json        everything: per-move labels, evals, accuracy, PVs
 ├─ annotated.pgn    standard PGN, importable into Lichess, SCID
 └─ report.html      one self-contained file, opens from file://
```

### Measured runtimes

Your archive is ~3089 Chess.com games. Timings measured on this machine
(AMD Radeon integrated, no NVIDIA):

| Configuration | Per game | 3089 games |
|---|---|---|
| `--no-lc0` | ~157 s | ~135 h |
| `--lc0-nodes 200 --lc0-max-moves 4` | ~309 s | ~265 h |
| Lc0 defaults (`--lc0-nodes 3000`) | worse still | not viable |

The defaults assume a GPU Lc0 build. On CPU-bound hardware you must lower
`--lc0-nodes` or use `--no-lc0`. Use `--limit` and `--since` to keep runs sane.

### Examples

```powershell
# Normal run
python analyze.py --player me --out out

# A quick look at the first 10 games
python analyze.py --player me --out out --limit 10

# StockFish only: roughly twice as fast
python analyze.py --player me --out out --no-lc0

# Both engines, affordable Lc0 budget
python analyze.py --player me --out out --lc0-nodes 200 --lc0-max-moves 4

# Fast survey: shallower, tighter time caps
python analyze.py --player me --out out --depth 10 --focus-depth 16 --survey-time 1.0 --focus-time 3.0

# Maximum quality on a handful of games
python analyze.py --player me --out out_deep --limit 20 --depth 18 --focus-depth 30 --survey-time 4.0 --focus-time 10.0

# Pure depth, no time caps (slow - positions can run for minutes)
python analyze.py --player me --out out --survey-time 0 --focus-time 0

# Force a specific Lc0 backend
python analyze.py --player me --out out --lc0-backend blas

# Data only, render the HTML later
python analyze.py --player me --out out --no-report
python report.py --data out\data.json --out out\report.html

# Analyse a single PGN file, someone else
python analyze.py --player Morphy --pgn games\opera.pgn --out out_test
```

### Gotchas

**A name that matches no game in the PGN is an error** (exit 2), rather than a
report full of silently empty games. The message names the White and Black players
of the first game so you can see what to pass. Matching is case-insensitive, so
`--player yourname` matches a `YOURNAME` header.

**`--out` overwrites.** `data.json` and `report.html` are rewritten in place. Use
a different directory to keep an old run.

**Verify before trusting the reference numbers.** The README's Morphy output and
the runtimes above come from actual runs, but the *default* configuration was
tuned for a GPU. Check your own with `--limit 10` before committing to a long run.

---

## 6. `report.py` — re-render the report

Rebuilds the HTML from existing `data.json`, without touching an engine. Seconds
instead of minutes.

```powershell
python report.py --data out\data.json --out out\report.html
```

### Flags

| Flag | Default | Meaning |
|---|---|---|
| `--data PATH` | `out\data.json` | input data written by `analyze.py` |
| `--out PATH` | `out\report.html` | output HTML |

### Examples

```powershell
# Rebuild the standard report
python report.py

# From a specific analysis into a new file
python report.py --data out_deep\data.json --out out_deep\report.html

# Render into a different folder
python report.py --data out\data.json --out review\report.html
```

Note this takes no `--player`: the player is already recorded in `data.json`.

---

## 7. Verifying a change

The repo ships no test files — `.gitignore` keeps new ones out. Instead, the pure
logic is checked by the modules that own it, via a `--self-test` flag. Because
those checks live next to the rules they describe, they cannot drift away from
the code the way a separate file can.

### The self-tests

```powershell
python setup.py --verify            # runs both, as its last step

python player.py --self-test        # 43 checks: the `--player me` alias
python -m process_api.fetcher --self-test   # 23 checks: the archive skip rule
```

Both are offline and take under a second. Neither writes outside a temp directory,
and neither touches your real `player.txt`, `metadata.json` or `out\`.

| Module | What it pins down |
|---|---|
| `player.py` | resolution order (`$CHESS_COACH_PLAYER` over `player.txt`), per-site vs bare-line precedence, `chess.com`/`chess-com` normalisation, `me` never resolving to itself, explicit names passing through, `resolve_or_exit` exiting 2 with usable guidance, `player_example.txt` parsing |
| `process_api/fetcher.py` | `archive_month` parsing, the skip predicate across the month boundary, `plan_archives` under `force` / `only_month` / `limit` and oldest-first ordering, `reset` |

Exit 0 means every check passed. Failures print `FAIL <label>: got …, want …`.

### Then the real pipeline

The self-tests cover the decisions; they cannot tell you the engines work. For
that, run the pipeline:

```powershell
# 1. Does one known game analyse correctly?  ~1-4 min, no network.
#    Morphy vs Brunswick & Isouard 1858: both real sacrifices must be found.
python analyze.py --player Morphy --pgn games\opera.pgn --out out_test

# 2. Does a real archive fetch?  ~1 min, one request per month.
python fetch_games.py --player me --site chesscom --max 5 --out games\check.pgn

# 3. Does a real archive analyse?  Minutes, scales with --limit.
python analyze.py --player me --pgn games\check.pgn --out out_check
```

Step 1 is the one worth running after any change that touches labels, evals or the
report. `games\opera.pgn` has a known-correct answer, so it catches a broken
engine, a wrong default, or a bad report without needing your own games or any
network access. Expect `13.Rxd7` and `16.Qb8+` labelled `Brilliant`, and nothing
spurious.

---

## 8. Recipes

### First-time setup on this machine

No NVIDIA GPU, so the DirectML build:

```powershell
python setup.py --only venv
python setup.py --lc0-build onnx-dml
.\engines\lc0-gpu\install.cmd
python setup.py --verify
```

The third command fetches `DirectML.dll`, which is not in the release zip.
`--verify` warns if it is missing.

### Check the install

```powershell
python setup.py --verify
```

Look for both engines, a net, backends, and the book. Exits 0 when usable.

### Smoke-test the analysis pipeline

`games\opera.pgn` is Morphy vs. Brunswick & Isouard, Paris 1858 — the game with
the famous 16.Qb8+ queen sacrifice. One short game, known expected output.

```powershell
python analyze.py --player Morphy --pgn games\opera.pgn --out out_test
```

Expected roughly:

```
  7. Qb3   Great !      16pp better than the next best
 10. Nxb5  Great !      26pp better than the next best
 11. Bxb5+ Great !      42pp better than the next best
 13. Rxd7  Brilliant !!  sacrifice 1.8, engine still approves, verified d24
 16. Qb8+  Brilliant !!  sacrifice 9.0, engine still approves, verified d24
 17. Rd8#  Great !      mate
```

Both real sacrifices found, nothing spurious. If this works, the pipeline is sound.

### Full analysis of your own archive

```powershell
python fetch_games.py --player me --site chesscom
python analyze.py --player me --out out --limit 10
```

Look at the per-game time, then extrapolate before committing to the whole archive.
Read `out\report.html`.

To narrow by date, filter at **fetch** time — `analyze.py` has no `--since`, it
analyses every game in the PGN it is handed:

```powershell
python fetch_games.py --player me --site chesscom --since 2025-01-01 --out games\recent.pgn
python analyze.py --player me --pgn games\recent.pgn --out out --limit 10
```

### Analyse the whole archive, StockFish only

```powershell
python analyze.py --player me --out out --no-lc0
```

Roughly twice as fast. Use when you want the accuracy and label picture, not the
neural second opinion.

### Then deep-dive with Lc0 on the games you care about

```powershell
python analyze.py --player me --out out_deep --limit 20 --lc0-nodes 400 --lc0-max-moves 6
```

Broad sweep without Lc0, then high-quality Lc0 on a small selection.

### Re-analyse after a setting change

```powershell
python analyze.py --player me --out out --depth 16 --focus-depth 26
```

Re-runs everything with different search settings. `--out` is overwritten, so pass
a different directory if you want to keep the previous report side by side:

```powershell
python analyze.py --player me --out out_v2 --depth 16 --focus-depth 26
```

### Merge both platforms

```powershell
python fetch_games.py --player me --site both --out games\all.pgn
python analyze.py --player me --pgn games\all.pgn --out out
```

### Import the annotated PGN

`out\annotated.pgn` opens in Lichess, SCID or En Croissant with the labels intact.
The HTML report also embeds it, so the download works offline.

---

## 9. Environment variables

Set in PowerShell before running, or permanently via
[Set-Item](https://learn.microsoft.com/powershell/module/microsoft.powershell.core/set-item):

```powershell
$env:STOCKFISH_PATH = "C:\engines\stockfish.exe"
$env:LC0_PATH      = "C:\engines\lc0.exe"
$env:LC0_NET       = "C:\nets\t3-512x15x16h.pb.gz"
$env:CHESS_COACH_PLAYER = "yourname"
```

| Variable | Purpose | Precedence |
|---|---|---|
| `STOCKFISH_PATH` | override the StockFish binary | beats auto-discovery |
| `LC0_PATH` | override the Lc0 binary | beats auto-discovery |
| `LC0_NET` | override the `.pb.gz` network | beats `data\nets\` |
| `CHESS_COACH_PLAYER` | your username, without `player.txt` | beats `player.txt` |
| `GITHUB_TOKEN` | optional; raises GitHub's download rate limit in `setup.py` | not required |

Auto-discovery looks in `engines\`, then `PATH`, then winget package dirs,
preferring `*-gpu` over `*-cpu`.

---

## 10. Exit codes

All entry points follow this, so they compose in scripts and CI.

| Code | Meaning |
|---|---|
| `0` | success |
| `1` | the run completed but reported a problem — no games downloaded, verification failed, fetch had failures |
| `2` | the invocation was wrong — bad flag, unresolvable `--player me`, missing PGN, `--player` matched no game |

---

## Command summary

```powershell
# Setup
python setup.py                              # everything, then verify
python setup.py --verify                     # probe only, downloads nothing
python setup.py --skip-lc0                   # StockFish only
python setup.py --only book                  # just the opening book
python setup.py --only venv --force          # reinstall dependencies
python setup.py --lc0-build onnx-dml         # 25 MB DirectML build, no CUDA needed

# Fetch
python fetch_games.py --player me --site chesscom
python fetch_games.py --player me --site chesscom --max 50
python fetch_games.py --player me --site chesscom --since 2025-01-01
python fetch_games.py --player me --site both --out games\all.pgn

python -m process_api.cli --player me --dry-run    # one request, prints decisions
python -m process_api.cli --player me
python -m process_api.cli --verify                # offline consistency check

# Analyse
python analyze.py --player me --out out
python analyze.py --player me --out out --limit 10
python analyze.py --player me --out out --no-lc0
python analyze.py --player me --out out --lc0-nodes 200 --lc0-max-moves 4
python analyze.py --player Morphy --pgn games\opera.pgn --out out_test

# Re-render
python report.py --data out\data.json --out out\report.html

# Verify a change (no test files; --self-test lives in the modules)
python setup.py --verify                              # includes both self-tests
python player.py --self-test
python -m process_api.fetcher --self-test
python analyze.py --player Morphy --pgn games\opera.pgn --out out_test
```

---

## First run on a new clone

```powershell
copy player_example.txt player.txt      # then edit in your usernames
python setup.py
python fetch_games.py --player me --site chesscom
python analyze.py     --player me --out out --limit 10
```

`player.txt` and `process_api\api.txt` are the only two files you create by hand;
both come from a tracked `*_example.txt` template. Everything else in the tree is
either source or something a command regenerates.