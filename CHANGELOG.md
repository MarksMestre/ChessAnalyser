# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Categories used below are the ones the format defines: Added, Changed, Deprecated,
Removed, Fixed, Security.

## [Unreleased]

### Added

- **An interactive React report**, served by `python serve.py` at
  `/report.html/`. Five pages: an **overview** leading with the player's rating
  over time, **every game** with filters, **one game** at
  `/report.html/games/<id>`, a **playable fork** at `.../play`, and **drill mode**
  at `.../drill`. Dark themed, with motion that respects
  `prefers-reduced-motion`.
- **Your ELO, over time.** `analyze.py` now derives `dashboard.ratings` from the
  PGN headers: the rating for each rated game in date order, plus accuracy split
  by opponent strength. Unrated games are skipped rather than counted as zero,
  `games_rated` is reported beside the chart, and fewer than three points renders
  a message rather than a line through two guesses.
- **A playable board.** Fork any position from a reviewed game and play on from
  it. `chess.js` enforces the rules client-side, so castling, en passant and
  promotion all work with no server involved; there is also a free-play mode
  where you move both sides.
- **Live engine judgement for moves you play.** `POST /api/analyse` scores the
  position through the *same* `scoring.py` the batch analysis uses, so a move
  made by hand is labelled by the thresholds in `labels.py` rather than by a
  second implementation that could drift from them. MultiPV=2, because "great" is
  defined against the runner-up line.
- **`scoring.py`** — the one implementation of "how good was that move", shared
  by `analyze.py` and the new server. Scoring and labelling were extracted out of
  `Analyser._score` so batch and live play cannot disagree.
- **`report.py --pack`** — splits `data.json` into a light index plus one file
  per game. At ~70 KB per game the original inlines to ~216 MB for a 3089-game
  archive; the index is ~10% of that, and each game is fetched when opened.
- **`report.py --standalone`** — folds the built app, its artwork and the data
  into one HTML file that still opens from `file://` with no network and no
  console errors. It switches to hash routing automatically, because the History
  API does not work on `file://`.
- **`serve.py`** — Python stdlib HTTP server for the app, the pack and the engine
  endpoint. One long-lived Stockfish serialised behind a lock, because
  `SimpleEngine` is not thread-safe; interactive defaults are deliberately
  shallower than the batch ones (depth 12 / 0.3 s) since somebody is watching,
  and the response always reports the depth actually reached.
- **Self-tests** for the new logic, in the repo's existing `--self-test` style:
  `analyze.py` (54 checks), `pack.py` (14), `serve.py` (31), and 46 Vitest checks
  covering the commentary generator, the mate-value formatting, the router switch
  and the playable board's rules. `pack.py` runs its checks with no `--self-test`
  flag, because it has no CLI.
- **Engine hints in free play.** `POST /api/hints` returns the top 1–3 moves for a
  position, drawn on the board as translucent grey arrows ranked by opacity, with a
  `1`/`2`/`3` selector remembered in `localStorage`. One search and nothing else —
  no move scoring, no book lookup — because it is called for every position you
  pass through. The requests are debounced 250 ms and aborted when the position
  changes, so stepping through a fork does not queue one search per position
  against the single locked engine.
- **A selectable piece looks selected.** The picked-up piece's square takes a
  55% wash and a 6px inset band; its legal destinations get a near-white disc with a
  darker rim, and a capture target gets a *ring* rather than a disc. A wash alone is
  barely visible under a piece, because `chessground` paints squares first and pieces
  after, so a piece covers ~78% of its square — only the margin shows, and the band
  is therefore drawn in the margin. Near-white is the one marker with contrast
  against both square colours; the mid grey this replaced sat close in luminance to
  each of them and read as a smudge on the dark square and a tint on the light one.
  A capture is a ring rather than a disc because the piece hides the centre of its
  own square, which is exactly where a disc would be; shape rather than shade is
  also the accessibility rule.
- **The analysis board is playable.** Pick a piece up on `/games/<id>` and the board
  answers with its legal destinations. Play the move the game played and the review
  carries on; play any other move and a **variation** opens under the ply it
  diverges from, and the rest of that line is yours to play. A fork move is scored
  through the same `POST /api/analyse` the free-play page uses, so it is labelled by
  the thresholds in `labels.py`. `chess.js` is the only authority on legality, and
  the destinations come from it rather than from `game.moves[].legal` — that field
  carries the alternatives to the *recorded* move and only for the player's own
  plies, so it cannot drive a board played from both sides.
- **One variation, rendered the way a score book sets one** — a single indented
  continuation line with a rule down its left edge, hung off the recorded row it
  forks from (`plans/Anexes/ANEX2.png`). It never displaces the recorded game, and
  it is not a tree, not nested and not in the URL: it is transient, and a link to a
  position that no longer exists would be worse than a link to the recorded line.
- **`MoveView`, one shape for a move however it was produced.** The batch analysis
  writes a full `Move` per recorded ply and `POST /api/analyse` returns an
  `AnalysisResult` for a move just played; they overlap and differ in the details,
  which previously meant the commentary panel took a `Move` plus an optional live
  result and a variation had no `Move` at all. Both are now projected onto a single
  type (`ui/src/lib/moveView.ts`), and `commentary.ts` reads that — so a row in the
  move list, a row in a variation and the commentary panel are the same code
  whether the move was played in 1858 or thirty seconds ago, and cannot drift into
  describing the same judgement differently.
- **`ui/src/lib/variation.ts`**, the fork logic as pure functions:
  `forkDecision`, `positionAt`, `groupRun`, `moveNumberOf`. `forkDecision` is the
  whole rule in one comparison — at the last ply there is no recorded next move, so
  every legal move forks, and that falls out of `undefined !== played` rather than
  needing a branch at the call site.
- **The board describes itself to a screen reader.** `role="group"` with an
  `aria-label` naming the selected square and how many squares it reaches. The
  selection and its destinations are drawn only — colour and shape, with no text
  anywhere — so without it a screen reader had nothing to announce, which matters
  more now that the analysis board is interactive rather than a picture of a game.
- **Per-site player identities.** `data.json` carries `player_identities`: one entry
  per platform account, with the name as *that platform* spells it and a game count.
  `--player me` has a different name per site in `player.txt`, and one string could
  not say which account was which. A configured site with no games in the run is
  listed with `no games` rather than omitted.

### Removed

- **The "vs engine" mode on the play page.** Free play is the only mode. The engine
  remains as an advisor — it still scores every move you make and still draws hints —
  but it no longer replies for the other side.
- **The enlarged selected piece.** The board drew the picked-up piece 12% larger via
  `chessground`'s auto-piece shapes. It fought the same problem from the wrong
  direction — a bigger piece over an unchanged square — and it needed the caller to
  look the piece up from the FEN and hand it in as `selectedPiece`. The square's
  margin now carries the highlight instead, so `selectedPiece`, `SELECTED_SCALE`,
  `pieceAt` and the eight `pieceAt` checks in `board.test.ts` all go with it.
  `Board.onSelectChange` went too: it existed only so the page could do that lookup,
  and `Board` already knows its own selection, so it describes itself instead.
- **`liveCommentary`**, the second prose generator. `commentary` reads `MoveView` and
  covers both sources; a second generator existed only because the recorded one took
  a `Move`, and two generators can describe the same judgement differently.

### Changed

- `analyze.py`'s per-move scoring now goes through `scoring.py`. Behaviour is
  unchanged; the arithmetic was moved rather than rewritten, so the two paths
  cannot drift apart.
- `report.py` fills in `dashboard.ratings` for a `data.json` produced before this
  version, so re-rendering an old report does not require re-running the engines.
- **`brilliant` is stricter**, and this changes the labels in `data.json` — a
  re-analysis is needed to see it. A brilliant now also requires the position to have
  been worth winning in (`win_percent_before >= 30`) and to still be acceptable
  afterwards (`win_percent_after >= 50`). Previously, `loss <= 2pp` was the only
  soundness test, and that threshold is vacuous in a lost position: at 10% winning,
  almost any move costs less than 2 points. So a queen sacrifice in a hopeless
  position was labelled brilliant — the tail of a lost game, played six pawns down,
  making the evaluation worse. The new conditions are a *floor* and not a ceiling on
  purpose: a ceiling would discard Morphy's `13.Rxd7` and `16.Qb8+`, which are both
  played from positions he was already winning. The consequence is that brilliant is
  rarer, and an empty brilliancy panel is now a claim you can trust.
- The free-play board uses lighter square tones (`--sq-light-play` / `--sq-dark-play`),
  a tone rather than a theme, so the page says "you are playing here now".
- Count columns in the phase and game tables are one per label (`!! ! ?! ? ?? !?`)
  rather than three headers each spanning two labels. No data change: `PhaseStats`
  already carried every label separately.
- **The opening tab says which move left book theory**, by name: *"left theory on
  3. g3"*. See the Fixed entry below for the off-by-one behind the old wording, and
  why naming the move is worth more than a number.
- **The cursor is a line as well as a ply.** `gameView` carries `cursor`
  (`main` | `fork`) alongside `ply`, so reading a variation and reading the game are
  one piece of state rather than two that can disagree. `select`/`first`/`last` leave
  a variation; `step` walks whichever line the cursor is on and clamps at a
  variation's end rather than falling back to the game; `Backspace` removes a fork
  move or steps back a ply depending on where you are — one gesture either way. The
  cursor's eager ref moved into `gameView` so a burst of key repeats accumulates for
  *every* caller, not only the keyboard handler.
- **A variation is announced, and you can get out of it.** An amber banner reads
  "in a variation from move N · k moves played", with a **back to the game** button,
  and auto-play is disabled with a reason, because it walks the *recorded* line and
  has nothing to walk from a position that is not in it. Being somewhere else without
  saying so is the failure mode: the board shows a position, the move list highlights
  a row, and nothing connects them.

### Fixed

- **The board could be picked at but never played on.** Three separate faults, each
  enough on its own, all in `Board`:
  - The selection was held in React state and fed back through the chessground config,
    and the config is an effect dependency — so *every tap rebuilt the whole board*. The
    rebuild landed inside chessground's own `mousedown` handler, before it reached the
    code that tries the move. Selection looked perfect throughout, because a fresh
    instance re-renders whatever the config says; the moves just never happened. The
    selection is now driven imperatively (`api.selectSquare`) and React state only names
    it for screen readers.
  - `api.destroy()` does not fully undo creation. `Chessground()` binds `mousedown` on
    the board element and then discards `bindBoard`'s unbind (chessground.js:43), so
    `destroy()` — which unbinds only what `bindDocument` returned (api.js:93) — leaves
    those listeners on the element permanently. Mounting into a reused element therefore
    stacked one handler per rebuild, each bound to a destroyed state, and the stale ones
    fired `events.select` with a `movable` from an older position. Each instance now gets
    a fresh element, so the old one and its listeners go out of scope together.
  - chessground caches its board box in a closure and positions every piece from that
    cache; only `updateBounds` clears it, and it runs on creation and on *window* resize.
    The board also resizes without the window changing — it sits in a flex column beside
    a scrolling move list, and when that list renders and the page grows a scrollbar the
    column narrows. The pieces stayed at the old geometry and taps were read against the
    old box, so a click resolved to the wrong square. A `ResizeObserver` now calls
    `api.redrawAll()`, which re-measures first: `redrawNow()` renders straight from the
    cached bounds and would have faithfully redrawn the stale geometry, which is the trap
    this fell into first.
- **Every chessground-targeted rule in `Board.module.css` was dead.** CSS Modules
  treats every class in a module file as local and *hashes* it — that is the point of
  the system — but `chessground` builds its own DOM and emits the literal class names
  `selected`, `move-dest`, `oc`, `last-move`, `check`, `orientation-white`. Writing
  `.board cg-board square.selected` therefore compiled to
  `._board_1u89s_12 cg-board square._selected_1u89s_108`, which matches nothing
  `chessground` ever creates. The selection highlight, the destination markers, the
  last-move tint, the check highlight and the coordinate colours were all being
  painted by `chessground`'s own defaults while this file said otherwise. It is
  silent: the selector looks right in the source and the DOM *does* carry the class
  the source names, so the mismatch is only visible in the built CSS or in a computed
  style. Every class `chessground` owns is now `:global()`, and ours (`.frame`,
  `.board`) stay hashed.
- **The legal destinations were one render out of date.** `GameAnalysis` kept the
  `chess.js` instance in a ref and reseeded it from a `useEffect`, while the `dests`
  map was built by a `useMemo` — and an effect runs *after* the memo that needs it.
  Stepping to the next move therefore showed the *previous* position's legal moves,
  and stepping to a position where a piece had moved produced an empty map, so
  nothing could be picked up at all. The board is now derived during render, which
  cannot be stale.
- **"Book ended at move 2" for a game that left theory on 3. g3.** `book_end_ply` is
  the ply of the move that *left* the book, so the move number is `ply // 2 + 1`;
  the arithmetic was `Math.ceil(ply / 2)`, which is the *last* book move — and then
  labelled it "the book ended at move N" while move N was itself book theory. The
  engine was right and the wording was wrong: `1.d4 d5 2.Nc3 e6 3.g3` is genuinely
  absent from `data/openings/d.tsv`, which stores only `1.d4 d5 2.Nc3` and `...e6`,
  so `book_end_ply=4` is correct. Both renderers now name the move —
  *"left theory on 3. g3"* — because the leaving move is the one worth looking at: it
  is the first judged on its own merits rather than against a book line.
- **A fork move was numbered and coloured as White's.** The side to move was derived
  from the fork's own index, so after `1.e4` a Black move printed as `1. c5`. It now
  comes from the FEN, which is the only thing that knows whose turn it is.
- A fork move played with no engine behind the page stayed `pending` forever and the
  panel said "Asking the engine…" indefinitely, with the placeholder label shown as
  if it were a verdict. `MoveView.unscored` distinguishes *no answer is coming* from
  *an answer is on the way*, and the panel says "No engine available, so this move is
  not scored." and shows no metrics.
- `groupRun` reused a row whenever the move number matched, so two same-colour moves
  sharing a number silently dropped one. It now reuses a row only when the half it
  needs is still free.
- The board was highlighting Black's legal destinations while ignoring clicks on
  them: `chessground` parses only the piece placement out of a FEN and never
  learns the side to move, so it needs `turnColor` passed explicitly.
- Per-move time is not in `data.json`, so the bar beside each half-move shows the
  evaluation rather than a clock. Showing a fabricated clock would have been
  worse than showing none.
- **The player name above the ELO read `ME`.** `analyze.py` wrote the `--player`
  argument into `data.json` verbatim, so with `--player me` it was the literal two
  letters. The resolved name was already in the data, in `dashboard.ratings.player`.
- **The board showed the position *before* the selected move.** Clicking move 1
  therefore looked like nothing had happened, and every later ply showed the board
  one move behind the move list. It now shows the position after the move, as every
  other analysis UI does; the pre-move position is one `Backspace` away. A URL
  naming a ply past the end of the game used to render an empty board, and now lands
  on the last ply.
- **The arrow keys did nothing in game analysis.** The page advertised `←`/`→` and
  labelled its transport buttons with them, but bound no handler — `App.tsx` binds
  only `Escape` and its comment said the arrows were bound per page. `←`/`→`,
  `Home`/`End`, `Space`, `f` and `Backspace` all work now, and they call
  `preventDefault` so they no longer scroll the page. Keystrokes from a text field,
  and any with a modifier held, are ignored. The eval graph's own handler was removed
  so one key does not have two owners.
- **Charts distorted their axes in fullscreen.** A fixed viewBox with
  `preserveAspectRatio="none"` scales x and y independently, so in a wide panel the
  tick labels were stretched 2.3× horizontally and the dots were ellipses. The charts
  now measure their box and set the viewBox to the real pixel size.
- **The phase tables showed two numbers in one cell.** The `!!` column held
  `brilliant` and `great`, `?!` held `inaccuracy` and `mistake`, and `??` held
  `blunder` and `miss` — so a `!!` of zero read as `0 0` under a header that claimed
  to mean the sum of two different labels. Each label now has its own column.
- **Tapping an unreachable square left the piece selected.** `chessground` keeps the
  old selection when a tap is neither the piece nor a legal destination, so the piece
  stayed picked up with its destination circles still showing. The selection rule now
  lives in the app: a square is selected if it is a legal origin for the side to move,
  and anything else clears it.
- **No arrow was ever drawn.** `Board` set `drawable: { enabled: false, visible: false }`
  on the assumption that `visible` meant "hide the drawing tool". It does not:
  `renderWrap` only creates the `cg-shapes` svg and the `cg-auto-pieces` container when
  `visible` is true, so with it false there was no layer to draw into and every shape was
  silently dropped — the red/green move arrows on the game page, the blue/green arrows on
  the play page, and the new hint arrows alike. `visible` is now `true` and `enabled` stays
  `false`, which is what actually governs the drawing tool and the erase-on-click.
- **A copied position link came back blank.** Selecting a move rewrote the URL from
  `ROUTES.game()` without the router's `/report.html/` basename, producing `/games/1/14` —
  off the mount the app is built for, where its asset URLs no longer resolve. The transport
  buttons and the keyboard keys now go through the same path, so the address bar always
  names the position on screen rather than only the last one clicked.

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