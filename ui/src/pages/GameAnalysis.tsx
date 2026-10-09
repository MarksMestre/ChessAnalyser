/**
 * The game analysis page — the layout the plan is really about.
 *
 * Structure follows plans/Anexes/GameAnalysisPageLayout.png; colours and
 * styling do not. Left column: player bar, board, player bar. Right column: tabs,
 * toolbar, the classification and commentary panel, the move list, the transport.
 *
 * The one deliberate departure from the reference image is that the move
 * classification and engine commentary sit *above* the move list, which is what
 * the original plan asks for. The reference puts a position header there.
 *
 * **The board is playable.** Picking a piece up shows what it can do, and playing
 * the recorded move advances the review — playing a different one opens a variation
 * under the move it diverges from, and the rest of that line is yours to play. There
 * is no button to press and no page to open; see plans/003 §4.3.
 */

import { useCallback, useEffect, useMemo, useState } from 'react'
import { Chess } from 'chess.js'
import { Link, useParams } from 'react-router-dom'
import { ApiUnavailable, api, isStandalone } from '../api/client'
import { Board } from '../components/board/Board'
import type { BoardArrow } from '../components/board/Board'
import { EvalBar } from '../components/board/EvalBar'
import { PlayerBar } from '../components/board/PlayerBar'
import { EvalGraph } from '../components/charts'
import { CommentaryPanel } from '../components/moves/CommentaryPanel'
import { MoveList, MovePairs } from '../components/moves/MoveList'
import { Transport } from '../components/moves/Transport'
import {
  Button,
  EmptyState,
  Segmented,
  Skeleton,
  Tabs,
} from '../components/ui'
import { bookExit } from '../lib/book'
import { START_FEN, turnOf } from '../lib/fen'
import { fmtDate, fmtDuration, fmtEval, winPercent } from '../lib/format'
import { COUNTED_LABELS, LABEL_TEXT_CLASS, labelMeta } from '../lib/labels'
import { fromAnalysis, fromRecorded } from '../lib/moveView'
import type { MoveView } from '../lib/moveView'
import {
  forkDecision,
  moveNumberOf,
  positionAt,
} from '../lib/variation'
import type { ForkMove } from '../lib/variation'
import { BASENAME, ROUTES, STANDALONE } from '../router'
import { GameViewProvider, useGameView } from '../state/gameView'
import { useReport } from '../state/report'
import styles from './GameAnalysis.module.css'

/** Which move the URL points at: `/games/3` or `/games/3/14`. */
function parsePly(suffix: string | undefined): number {
  if (!suffix) return 0
  const value = Number.parseInt(suffix, 10)
  return Number.isFinite(value) && value >= 0 ? value : 0
}

export function GameAnalysis() {
  const { gameId, ply } = useParams()
  const { games, loadGame } = useReport()
  const index = Number.parseInt(gameId ?? '', 10)

  const game = Number.isFinite(index) ? (games.get(index) ?? null) : null

  // Fetch on mount and whenever the route changes. The provider caches, so
  // navigating back to a game already read is instant.
  useEffect(() => {
    if (Number.isFinite(index) && !games.has(index)) {
      void loadGame(index)
    }
  }, [index, games, loadGame])

  if (!Number.isFinite(index)) {
    return (
      <div className={styles.page}>
        <EmptyState title="No game selected">
          That URL does not contain a game id.
        </EmptyState>
      </div>
    )
  }

  if (!game) {
    return (
      <div className={styles.page}>
        <div className={styles.loading}>
          <Skeleton height={26} width="320px" />
          <div className={styles.loadingGrid}>
            <Skeleton height={420} />
            <Skeleton height={420} />
          </div>
        </div>
      </div>
    )
  }

  return (
    <GameViewProvider game={game} initialPly={parsePly(ply)}>
      <GameBody />
    </GameViewProvider>
  )
}

function GameBody() {
  const {
    game,
    ply,
    cursor,
    variation,
    inFork,
    flipped,
    setFlipped,
    selectPly,
    selectFork,
    returnToMain,
    forkFrom,
    pushForkMove,
    replaceForkMove,
    viewMode,
    setViewMode,
    layout,
    setLayout,
    playing,
    speed,
    setSpeed,
    togglePlay,
    step,
    first,
    last,
    onTakeBack,
  } = useGameAnalysis()
  const headers = game?.headers ?? {}
  const lastPly = (game?.moves.length ?? 1) - 1

  /*
   * One lookup for "what is on the board".
   *
   * The board, the eval bar and the commentary panel all need this answer, and each
   * one computing it separately is exactly how the board ended up showing the
   * position *before* the selected move while everything else showed the one after.
   */
  const position = useMemo(
    () => (game ? positionAt(game, cursor, variation) : { fen: '', uci: null, view: null }),
    [game, cursor, variation],
  )
  const fen = position.fen || START_FEN
  const move = position.view

  /*
   * The board shows the position *after* the selected move, which is what
   * every analysis UI does and what makes the board agree with the move you
   * just clicked.
   *
   * It used to be `move.fen` — the position *before* — with the move drawn on it
   * as an arrow. That is defensible in principle and a bug in practice: ply 0's
   * `fen` is the initial position, so clicking the first move looked like
   * nothing had happened, and every later ply showed the board one move behind
   * the move list. The pre-move position is one `Backspace` away.
   */
  const arrows: BoardArrow[] = []
  if (move?.uci) arrows.push({ from: move.uci.slice(0, 2), to: move.uci.slice(2, 4), colour: 'red' })
  const bestUci = move?.best_uci ?? null
  if (bestUci && bestUci !== move?.uci) {
    arrows.push({ from: bestUci.slice(0, 2), to: bestUci.slice(2, 4), colour: 'green' })
  }

  const lastMove: [string, string] | null = move?.uci
    ? [move.uci.slice(0, 2), move.uci.slice(2, 4)]
    : null

  /* ---------------------------------------------------------------- playing */

  /*
   * The rules engine for the position on screen.
   *
   * `chess.js` is the only authority on legality, exactly as on the play page.
   *
   * Derived with `useMemo` rather than kept in a ref and reseeded by an effect: an
   * effect runs *after* the memo that needs it, so the destinations came out one
   * render stale — stepping to the next move showed the previous position's legal
   * moves, and stepping to a position where a piece had moved produced an empty map
   * so nothing could be picked up at all. Building it during render cannot be stale.
   */
  const board = useMemo(() => {
    try {
      return new Chess(fen)
    } catch {
      return null
    }
  }, [fen])

  /*
   * Legal destinations, from the rules engine rather than from
   * `game.moves[].legal`: that field carries the alternatives to the *recorded*
   * move, and only for the player's own plies, so it cannot drive a board you can
   * play both sides on.
   */
  const dests = useMemo(() => {
    const map = new Map<string, string[]>()
    if (!board || board.isGameOver()) return map
    for (const m of board.moves({ verbose: true })) {
      const list = map.get(m.from) ?? []
      list.push(m.to)
      map.set(m.from, list)
    }
    return map
  }, [board])

  const turnColor = turnOf(fen)
  const gameOver = board?.isGameOver() ?? false

  const [serverDown, setServerDown] = useState(isStandalone)

  /*
   * Play a move. Either it is the one the game played and the review carries on, or
   * it is not, and it opens a variation under the move it diverges from.
   *
   * At the last ply there is no recorded next move, so every legal move forks --
   * which is the right answer: playing on from the end of the game is the most
   * natural reason to want a playable analysis board.
   */
  const playMove = useCallback(
    (from: string, to: string) => {
      if (!game || !board || gameOver) return
      /*
       * A fresh instance, because a move is applied by pushing onto it and the memo
       * above must not be mutated. Its starting FEN is the position on screen, which
       * is the same one `board` holds.
       */
      const position_ = new Chess(fen)
      // The FEN *before* the move is what the server scores: it re-derives the "after"
      // evaluation itself, and a move is illegal in the position it created.
      const fenBefore = position_.fen()

      let moved
      try {
        // Promotion defaults to a queen, the common case and the one the arrow implies.
        moved = position_.move({ from, to, promotion: 'q' })
      } catch {
        return
      }
      if (!moved) return

      const uci = from + to + (moved.promotion ?? '')
      const fenAfter = position_.fen()
      const recordedNext = inFork ? undefined : game.moves[ply + 1]?.uci

      if (forkDecision(recordedNext, uci) === 'advance' && recordedNext) {
        selectPly(ply + 1)
        return
      }

      /*
       * A divergent move. `ply` holds the fork's base while the cursor is inside a
       * variation, and the recorded ply otherwise, so it is the last position the two
       * lines share either way.
       */
      const basePly = ply
      if (!inFork) forkFrom(basePly)

      const forkPly = variation?.moves.length ?? 0
      /*
       * Both facts come from the position, not from the fork's own index.
       *
       * The colour read from the FEN because it is Black to move after 1.e4 even
       * though this is the fork's first move — deriving it from the index printed
       * "1. c5" for a Black move. The move number is counted from where the fork
       * starts, because the fork begins a line at a recorded position and its first
       * move is the *next* one in the game.
       */
      const color = turnOf(fenBefore)
      const moveNumber = moveNumberOf(basePly + forkPly + 1)

      const played: ForkMove = {
        ...fromAnalysis(
          {
            label: 'good',
            glyph: '',
            san: moved.san,
            fen: fenBefore,
            fen_after: fenAfter,
            eval_before: 0,
            eval_after: 0,
            win_percent_before: 50,
            win_percent_after: 50,
            loss_pp: 0,
            accuracy: 100,
            best_san: null,
            best_uci: null,
            best_pv: [],
            best_eval: null,
            second_san: null,
            second_uci: null,
            second_eval: null,
            gap_pp: null,
            sacrifice: null,
            depth_reached: 0,
            movetime_ms: 0,
            terminated: position_.isGameOver(),
            result: '*',
          },
          { uci, san: moved.san, moveNumber, color, ply: forkPly, pending: !serverDown },
        ),
        fen_before: fenBefore,
        fen_after: fenAfter,
        /*
         * No engine behind the page means no answer will ever arrive, which is a
         * different state from "still thinking". Left pending, a standalone report
         * would claim to be searching a move forever and show the placeholder label
         * as if it were a verdict.
         */
        unscored: serverDown,
      }
      pushForkMove(played)

      if (serverDown) return

      /*
       * Scored by the same `scoring.py` the batch analysis uses, so a move played by
       * hand is judged by the thresholds in labels.py rather than by a second
       * implementation that could drift from them.
       */
      api
        .analyse({ fen: fenBefore, uci })
        .then((result) => {
          replaceForkMove(forkPly, {
            ...fromAnalysis(result, { uci, san: moved.san, moveNumber, color, ply: forkPly }),
            fen_before: fenBefore,
            fen_after: fenAfter,
          })
        })
        .catch((cause: unknown) => {
          // The move stays listed and unscored, which is what the standalone build
          // always is. Losing the server is not a reason to lose the move.
          if (cause instanceof ApiUnavailable) setServerDown(true)
        })
    },
    [
      game, board, fen, gameOver, inFork, ply, variation, serverDown,
      selectPly, forkFrom, pushForkMove, replaceForkMove,
    ],
  )

  const whiteName = headers.White || 'White'
  const blackName = headers.Black || 'Black'
  const playerIsWhite = game?.player_color === 'white'

  /*
   * The recorded line, projected onto the shared shape, so the move list and the
   * commentary panel read the same kind of move whether it came from `data.json` or
   * from the board.
   */
  const moveViews = useMemo<MoveView[]>(
    () => (game?.moves ?? []).map(fromRecorded),
    [game],
  )

  const eloOf = (name: string) => {
    const key = name === whiteName ? 'WhiteElo' : 'BlackElo'
    const raw = headers[key]
    const value = raw ? Number.parseInt(raw, 10) : NaN
    return Number.isFinite(value) && value > 0 ? value : null
  }

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <div className={styles.headerMain}>
          <h1>{game?.headers.Event ?? 'Game'}</h1>
          <div className={styles.headerMeta}>
            <span>{fmtDate(headers.Date)}</span>
            <span>·</span>
            <span>{game?.opening ?? 'Unknown opening'}</span>
            {game?.eco ? <span className="dim">({game.eco})</span> : null}
            <span>·</span>
            <span>{headers.Result}</span>
          </div>
        </div>
        <div className={styles.headerStats}>
          <Stat label="accuracy" value={game ? game.accuracy.toFixed(1) : '—'} />
          <Stat label="ACPL" value={game ? game.acpl.toFixed(1) : '—'} />
          <Stat label="moves" value={String(game?.moves.length ?? 0)} />
        </div>
        <div className={styles.headerActions}>
          <Link className={styles.linkBtn} to={ROUTES.play(indexOf(game))}>
            Try this position
          </Link>
          <Link className={styles.linkBtn} to={ROUTES.drill(indexOf(game))}>
            Drill
          </Link>
        </div>
      </header>

      {/*
        The eval graph spans the full width above both columns: it is the
        overview of the whole game, and squeezing it into one column would make
        it unreadable.
      */}
      {game ? (
        <div className={styles.graphRow}>
          <EvalGraph
            values={game.eval_curve}
            selected={inFork ? -1 : ply}
            onSelect={selectPly}
            labels={game.moves.map((m) => m.label)}
          />
          <div className={styles.graphLabel}>
            {inFork
              ? // The curve describes the recorded line and has no index for a
                // position that is not in it. Drawing the fork's own curve is its
                // own piece of work; showing it dimmed and uncursored is honest.
                'variation — not on the recorded curve'
              : `evaluation · ${fmtEval(move?.eval_after ?? null)}`}
          </div>
        </div>
      ) : null}

      <div className={styles.columns}>
        {/* ---------------- left: the board ---------------- */}
        <div className={styles.boardColumn}>
          <PlayerBar
            name={whiteName}
            elo={eloOf(whiteName)}
            isPlayer={playerIsWhite}
            country={headers.WhiteTeam ?? null}
            clock={clockOf(headers, 'White')}
            result={resultFor(game?.player_color, headers.Result, true)}
          />

          <div className={styles.boardWrap}>
            <Board
              fen={fen}
              orientation={flipped ? 'black' : 'white'}
              arrows={arrows}
              lastMove={lastMove}
              /*
                `movable` is what makes the analysis board playable at all. Without
                it chessground's `isMovable()` is false for every square: nothing can
                be selected and nothing can be dropped.
              */
              movable={{
                color: turnColor,
                dests,
                onMove: playMove,
              }}
              turnColor={turnColor}
            />
            <button
              className={styles.flip}
              onClick={() => setFlipped((v) => !v)}
              title="Flip the board (F)"
              aria-label="Flip the board"
            >
              ⇅
            </button>
          </div>

          <PlayerBar
            name={blackName}
            elo={eloOf(blackName)}
            isPlayer={!playerIsWhite}
            country={headers.BlackTeam ?? null}
            clock={clockOf(headers, 'Black')}
            result={resultFor(game?.player_color, headers.Result, false)}
          />

          {/* Eval bar under the board, from White's point of view. */}
          <div className={styles.evalStrip}>
            <EvalBar
              whitePercent={winPercent(move?.eval_after ?? null)}
              height={10}
              showLabels
            />
          </div>
        </div>

        {/* ---------------- right: analysis + moves ---------------- */}
        <div className={styles.sideColumn}>
          <Tabs
            value={viewMode}
            onChange={setViewMode}
            tabs={[
              { value: 'moves' as const, label: 'Moves' },
              { value: 'info' as const, label: 'Info' },
              { value: 'openings' as const, label: 'Opening' },
            ]}
          />

          {viewMode === 'moves' ? (
            <>
              {/*
                Being somewhere else without saying so is the failure mode, so the
                banner appears whenever the cursor is inside a variation. The button
                returns to the recorded move the variation forked from -- the row the
                reader was looking at when they left.
              */}
              {inFork && variation ? (
                <div className={styles.variationBanner}>
                  <span>
                    in a variation from move {moveNumberOf(variation.basePly + 1)} ·{' '}
                    {variation.moves.length} move{variation.moves.length === 1 ? '' : 's'}{' '}
                    played
                  </span>
                  <Button onClick={returnToMain} title="Back to the recorded game">
                    back to the game
                  </Button>
                </div>
              ) : null}

              {/* The classification and commentary, above the moves. */}
              <CommentaryPanel
                move={move}
                busy={inFork && move?.pending === true}
              />

              <div className={styles.listHead}>
                <Segmented
                  ariaLabel="Move list layout"
                  value={layout}
                  onChange={setLayout}
                  options={[
                    { value: 'list' as const, label: 'List' },
                    { value: 'pairs' as const, label: 'Pairs' },
                  ]}
                />
                <span className={styles.listHint}>
                  click a move · <kbd>←</kbd> <kbd>→</kbd> to step · drag a piece to
                  play on
                </span>
              </div>

              <div className={styles.moveScroll}>
                {layout === 'list' ? (
                  <MoveList
                    moves={moveViews}
                    selected={ply}
                    selectedFork={inFork ? cursor.ply : null}
                    variation={variation}
                    onSelect={selectPly}
                    onSelectFork={selectFork}
                  />
                ) : (
                  <MovePairs
                    moves={moveViews}
                    selected={ply}
                    selectedFork={inFork ? cursor.ply : null}
                    variation={variation}
                    onSelect={selectPly}
                    onSelectFork={selectFork}
                  />
                )}
              </div>

              {/*
                `step` rather than the main-line-only `stepTo`, so the arrows walk
                whichever line the cursor is on. `first`/`last` jump to the ends of
                the recorded game, which is what the reader expects of them even from
                inside a variation.
              */}
              <Transport
                playing={playing}
                speed={speed}
                ply={ply}
                lastPly={lastPly}
                /* Auto-play walks the recorded line and cannot walk a position that
                   is not in it, so the button is disabled inside a variation rather
                   than silently doing nothing. */
                canPlay={!inFork}
                onFirst={() => first()}
                onPrev={() => step(-1)}
                onTogglePlay={togglePlay}
                onNext={() => step(1)}
                onLast={() => last()}
                onSpeed={setSpeed}
                onStepBack={onTakeBack}
              />
            </>
          ) : null}

          {viewMode === 'info' ? <GameInfo game={game} /> : null}
          {viewMode === 'openings' ? <GameOpening game={game} /> : null}
        </div>
      </div>
    </div>
  )
}

function indexOf(game: { index: number } | null): number {
  return game?.index ?? 0
}

function resultFor(
  playerColor: 'white' | 'black' | null | undefined,
  result: string | undefined,
  isWhite: boolean,
): string | null {
  if (!result || !playerColor) return null
  const playerWon =
    (result === '1-0' && playerColor === 'white') ||
    (result === '0-1' && playerColor === 'black')
  const playerLost =
    (result === '1-0' && playerColor === 'black') ||
    (result === '0-1' && playerColor === 'white')
  const whiteWord = playerWon && isWhite ? 'won' : playerLost && isWhite ? 'lost' : null
  if (whiteWord) return playerWon ? 'win' : 'loss'
  if (result === '1/2-1/2') return 'draw'
  return null
}

/** The clock from the PGN comments, when the game had one. */
function clockOf(headers: Record<string, string>, _side: 'White' | 'Black'): string | null {
  // Per-move clocks are not in data.json; the time control is the honest thing
  // to show rather than an invented number.
  const tc = headers.TimeControl
  return tc ? timeControlLabel(tc) : null
}

function timeControlLabel(tc: string): string {
  if (tc === '-' || tc === '') return '—'
  if (/^\d+$/.test(tc)) return `${tc}s`
  const parts = tc.split('/')
  if (parts.length === 2) return `${parts[0]}+${parts[1]}`
  return tc
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className={styles.stat}>
      <span className={styles.statValue}>{value}</span>
      <span className={styles.statLabel}>{label}</span>
    </div>
  )
}

function GameInfo({ game }: { game: import('../api/types').GameDetail | null }) {
  if (!game) return null
  const h = game.headers
  const rows: Array<[string, string]> = [
    ['Date', fmtDate(h.Date)],
    ['Site', h.Site ?? '—'],
    ['Round', h.Round ?? '—'],
    ['Time control', timeControlLabel(h.TimeControl ?? '')],
    ['Termination', h.Termination ?? '—'],
    ['Result', h.Result ?? '—'],
    ['White', `${h.White ?? '—'}${h.WhiteElo ? ` (${h.WhiteElo})` : ''}`],
    ['Black', `${h.Black ?? '—'}${h.BlackElo ? ` (${h.BlackElo})` : ''}`],
    ['Analysis time', fmtDuration(game.analysis_seconds)],
  ]
  return (
    <div className={styles.infoPanel}>
      <table>
        <tbody>
          {rows.map(([k, v]) => (
            <tr key={k}>
              <td className={styles.infoKey}>{k}</td>
              <td>{v}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <h3 className={styles.infoHeading}>by phase</h3>
      <table>
        <thead>
          <tr>
            <th>phase</th>
            <th>moves</th>
            <th>accuracy</th>
            <th>ACPL</th>
            {COUNTED_LABELS.map((label) => (
              <th key={label} title={labelMeta(label).title}>
                {labelMeta(label).glyph}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {(['opening', 'middlegame', 'endgame'] as const).map((phase) => {
            const s = game.phase_accuracy[phase]
            if (!s) return null
            return (
              <tr key={phase}>
                <td>{phase}</td>
                <td>{s.moves}</td>
                <td>{s.accuracy.toFixed(1)}</td>
                <td>{s.acpl.toFixed(1)}</td>
                {COUNTED_LABELS.map((label) => {
                  const value = s[label] ?? 0
                  return (
                    <td key={label} className={styles.count}>
                      <span className={value ? LABEL_TEXT_CLASS[label] : styles.countZero}>
                        {value}
                      </span>
                    </td>
                  )
                })}
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

function GameOpening({ game }: { game: import('../api/types').GameDetail | null }) {
  if (!game) return null
  /*
   * The move that left book theory, by name.
   *
   * This said "Book ended: move 2" for a game that was in book through 2...e6 and
   * left on 3.g3, because `book_end_ply` is the leaving move's ply and the old
   * arithmetic rounded it the wrong way. Naming the move also makes the tab say the
   * useful thing: the first move judged on its own merits, rather than against a
   * book line.
   */
  const exitPly = game.book_end_ply
  const exitMove = exitPly > 0 ? (game.moves[exitPly] ?? null) : null
  const exit = bookExit(exitPly, exitMove?.san)
  return (
    <div className={styles.infoPanel}>
      <div className={styles.openingName}>{game.opening ?? 'Not recognised'}</div>
      {game.eco ? <div className={styles.eco}>{game.eco}</div> : null}
      <table>
        <tbody>
          <tr>
            <td className={styles.infoKey}>Book theory</td>
            <td>
              {exit ?? 'the whole game matched a stored opening line'}
              {exitMove ? (
                <>
                  {' — '}
                  <span className={LABEL_TEXT_CLASS[exitMove.label]}>
                    {exitMove.label}
                  </span>
                </>
              ) : null}
            </td>
          </tr>
          <tr>
            <td className={styles.infoKey}>Book moves</td>
            <td>{game.counts.book ?? 0}</td>
          </tr>
        </tbody>
      </table>
      {game.headers.ECOUrl ? (
        <a href={game.headers.ECOUrl} target="_blank" rel="noreferrer" className={styles.openingLink}>
          Opening explorer ↗
        </a>
      ) : null}
    </div>
  )
}

/**
 * True when a keystroke belongs to whatever the reader is typing into.
 *
 * Without this, `←` in the game-index search box steps through the game that is
 * not on screen. GameDrill guards only `HTMLInputElement` and therefore has
 * exactly that bug; select and textarea are guarded here too.
 */
function isTypingTarget(target: EventTarget | null): boolean {
  return (
    target instanceof HTMLInputElement ||
    target instanceof HTMLSelectElement ||
    target instanceof HTMLTextAreaElement ||
    (target instanceof HTMLElement && target.isContentEditable)
  )
}

/** Pull the shared view state, and own the two pieces of local UI state. */
function useGameAnalysis() {
  const view = useGameView()
  const { game, ply, select, step, first, last, togglePlay, setFlipped, inFork, popForkMove } = view

  // Two pieces of view-only state, kept here because nothing else reads them.
  const [layout, setLayout] = useState<'list' | 'pairs'>('list')
  const [viewMode, setViewMode] = useState<'moves' | 'info' | 'openings'>('moves')

  /*
   * Selecting a ply rewrites the URL so a position can be linked to. Only the
   * ply path changes, so this is replaceState rather than pushState: stepping
   * through 60 moves should not put 60 entries on the back button.
   *
   * The path needs BASENAME on the front. It did not have it, and that broke
   * the feature this exists for: `ROUTES.game()` is `/games/1`, so selecting a
   * move rewrote the URL to `/games/1/14` — off the `/report.html/` mount the
   * app is built for, where the asset URLs no longer resolve and a copied link
   * comes back blank.
   *
   * Skipped entirely in standalone: there the HashRouter owns the URL, and
   * replaceState would wipe the hash it maintains.
   */
  const selectPly = useCallback(
    (index: number) => {
      select(index)
      if (game && !STANDALONE) {
        const mount = BASENAME.replace(/\/$/, '')
        window.history.replaceState(null, '', `${mount}${ROUTES.game(game.index)}/${index}`)
      }
    },
    [select, game],
  )

  /*
   * Take back. Inside a variation it removes a move from that variation; on the
   * recorded line it steps back one ply. One gesture either way, which is why it is
   * one function rather than two buttons.
   */
  const onTakeBack = useCallback(() => {
    if (inFork) {
      popForkMove()
      return
    }
    if (ply > 0) selectPly(ply - 1)
  }, [inFork, ply, selectPly, popForkMove])

  /*
   * The transport keys.
   *
   * Page-scoped on purpose. App.tsx binds only Escape and says why: a global
   * handler fights the drill page, which owns the same arrows for a different
   * purpose. EvalGraph's own onKeyDown is gone for the same reason — two owners
   * of one key means the ply moves twice.
   *
   * preventDefault is what makes these feel like they work at all: without it
   * Space scrolls the page, Home/End jump the move list to its own ends, and the
   * arrows scroll the list sideways.
   *
   * The arrows go through the context's `step`, which walks whichever line the cursor
   * is on, clamps at a variation's end rather than falling back to the game, and
   * accumulates a burst of key repeats (it keeps a ref for that, so every caller
   * gets it).
   */
  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      if (isTypingTarget(event.target)) return
      // Ctrl+← / Cmd+← is a text-field word jump and Alt+← is browser-back.
      if (event.metaKey || event.ctrlKey || event.altKey) return

      switch (event.key) {
        case 'ArrowLeft':
          event.preventDefault()
          step(-1)
          return
        case 'ArrowRight':
          event.preventDefault()
          step(1)
          return
        case 'Home':
          event.preventDefault()
          first()
          return
        case 'End':
          event.preventDefault()
          last()
          return
        case ' ':
        case 'Spacebar':
          event.preventDefault()
          // Auto-play walks the recorded line and has nothing to walk from a
          // variation. Transport disables its button in that case; the key does
          // the same rather than appearing to do nothing.
          if (!inFork) togglePlay()
          return
        case 'Backspace':
          event.preventDefault()
          onTakeBack()
          return
        case 'f':
        case 'F':
          event.preventDefault()
          setFlipped((v) => !v)
          return
        default:
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [step, first, last, togglePlay, setFlipped, onTakeBack, inFork])

  return { ...view, layout, setLayout, viewMode, setViewMode, selectPly, onTakeBack }
}