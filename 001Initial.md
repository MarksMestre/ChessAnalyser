All unknowns resolved. Here's the plan.
Setup facts verified
- Stockfish.Stockfish 19.0 available in winget; SF 19 uses universal binaries (auto-detects your CPU — no AVX2/AVX-512 choice anymore)
- chess (python-chess) 1.11.2 installs cleanly on your Python 3.14
- chess.svg.board() inlines piece paths (PIECES[...]) with no external URLs → the HTML report can be fully offline, single file
- Only dependency: chess. Downloads/CSV/JSON all use stdlib
Files to create
C:\Users\yourname\chess-coach\
├─ fetch_games.py    pull full PGN archive from Chess.com / Lichess by username (public API, no login)
├─ analyze.py        PGN -> labelled moves + accuracy + JSON
├─ report.py         JSON -> single self-contained HTML
└─ out\              raw.pgn  annotated.pgn  report.html  data.json
Usage: python analyze.py --player yourname --depth 14 --out out\ → opens out\report.html.
The core: how moves get labelled
For each ply, with MultiPV=2 so we can see the runner-up line:
evalBefore (side to move) ──► best line 1  E1
 └► best line 2  E2
play your move         ──► evalAfter, flipped to your perspective
loss_pp = winProb(before) - winProb(after)      # Lichess sigmoid, 0.00368208
Label	Rule
Brilliant !!	Sound sacrifice: material given ≥ 3.0 after the opponent's best reply and loss_pp ≤ 2 and you weren't already winning (winProb(before) < 0.85)
Great !	Your move = engine's, and E1 − E2 ≥ 10pp (literally the only good move), not a forced recapture, not book
Book / Best / Excellent / Good	loss_pp ≤ 1 / 1–2 / 2–5
Inaccuracy / Mistake / Blunder	loss_pp 5–10 / 10–25 / > 25
Miss	You were winning, and the engine's best move stayed winning while yours didn't
Accuracy per move: 103.1668 · e^(−0.04354 · loss_pp) − 3.1669 (Lichess's published formula).
Game accuracy: Lichess-style harmonic mean + eval-volatility weighting, plus plain mean for comparison. ACPL reported alongside.
Phases: opening (until book ends, ~move 15) / middlegame / endgame (non-pawn material ≤ 2600), each with its own accuracy — this is how you find which part of your game is weak.
Two-pass depth strategy (this matters for speed)
Pass	Depth	Scope	Time/game
1 — survey	14	every ply, every game	~15–25 s
2 — focus	22–24	only plies around blunders, misses, brilliant candidates	~5 s
Deep analysis of everything would take ~20–40 min/game on your box for no extra insight. Pass 2 re-verifies only the moves that decide the report, which is also where false brilliant labels get caught. Default --depth 14/24, overridable.
HTML report (single file, offline, opens with file://)
1. Dashboard — accuracy & ACPL trend over time, blunders/mistakes/inaccuracies per phase, best and worst games, and a "recurring weaknesses" panel (e.g. material dropped in the middlegame, 7 times; missed knight forks, 4 times)
2. Per game — clickable eval graph, move table with !!/?? glyphs and per-move loss, and a live board where clicking a move shows the position with your move in red and the engine's best move as a green arrow
3. Drill mode — hides the answer, you pick the move, then it reveals the engine line. This is the actual learning tool
4. Your brilliancies — dedicated section listing every sacrifice you played, with the engine's PV proving it worked
5. Export — annotated .pgn you can re-import into Lichess, En Croissant, or SCID
Steps
1. winget install --id=Stockfish.Stockfish -e, verify with bench (expect1–3M nps on your CPU)
2. pip install chess
3. Write fetch_games.py → analyze.py → report.py
4. Verify on a known game: analyze a famous game, confirm labels and evals match Lichess's published review within reason
5. Run on your archive
Two decisions for you
a) Add Lc0 as a second engine? Lc0 (AlphaZero-style net) often likes human creative moves that Stockfish rates as inferior — running both and flagging "Lc0 agreed with you, Stockfish didn't" is a genuinely good brilliant-move detector, and it's the one thing StockFish alone can't do. Roughly doubles analysis time and adds a ~2 GB net download.
b) Opening book — I want to fetch the CC0 lichess-openings TSV so the tool can flag "you left book theory here" (a common source of blunders) and name your openings. Small download, needs internet once. Say yes to both, either, or neither.