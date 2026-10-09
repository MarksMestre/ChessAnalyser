/**
 * A playable fork of a position from a reviewed game.
 *
 * This is the original plan's "continue the game to experimenting, simply by
 * trying to play with the pieces". `chess.js` enforces legality client-side, so
 * the board is fully playable — castling, en passant and promotion included —
 * with no server involved. When the server *is* available each move is also sent
 * to Stockfish and comes back labelled by the same rules the batch analysis
 * uses, because scoring.py is shared between them.
 *
 * When the server is not running the page still works: free play and board
 * navigation need nothing but the client, so it degrades rather than breaks.
 *
 * **Both sides are yours.** There used to be a "vs engine" mode in which
 * Stockfish replied for the other side. It is gone: the engine is an advisor
 * here, not an opponent. It scores every move you make, and it draws the X best
 * moves for the position as translucent grey arrows so you can see what it
 * would have played. Both of those need the server; the board does not.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Chess } from 'chess.js'
import { Link, useParams } from 'react-router-dom'
import { ApiUnavailable, api, isStandalone } from '../api/client'
import type { AnalysisResult, GameDetail, Label } from '../api/types'
import { Board } from '../components/board/Board'
import type { BoardArrow } from '../components/board/Board'
import { PlayerBar } from '../components/board/PlayerBar'
import { Button, EmptyState, ErrorNote, Pill, Segmented, Skeleton, Spinner } from '../components/ui'
import { START_FEN } from '../lib/fen'
import { fmtEval } from '../lib/format'
import { readHintCount, useEngineHints, writeHintCount } from '../lib/hints'
import { LABEL_CLASS } from '../lib/labels'
import { ROUTES } from '../router'
import { useReport } from '../state/report'
import styles from './GamePlay.module.css'

interface PlayMove {
  uci: string
  san: string
  /** True while the engine has not answered yet. */
  pending: boolean
  result: AnalysisResult | null
}

/** How many hints the selector offers. Mirrors the server's 1..3 clamp. */
type HintCount = 1 | 2 | 3

const HINT_OPTIONS: Array<{ value: HintCount; label: string; title: string }> = [
  { value: 1, label: '1', title: 'Show the best move only' },
  { value: 2, label: '2', title: 'Show the two best moves' },
  { value: 3, label: '3', title: 'Show the three best moves' },
]

/**
 * Which brush a hint of this rank uses.
 *
 * Rank 1 is the most opaque, so "the best move" is legible at a glance and the
 * alternatives recede. The rank is clamped rather than trusted, because the
 * server is what decides how many lines came back.
 */
export function hintBrush(rank: number): 'hint1' | 'hint2' | 'hint3' {
  if (rank <= 1) return 'hint1'
  if (rank === 2) return 'hint2'
  return 'hint3'
}

export function GamePlay() {
  const { gameId, ply } = useParams()
  const { games, loadGame } = useReport()
  const index = Number.parseInt(gameId ?? '', 10)
  const game = Number.isFinite(index) ? (games.get(index) ?? null) : null

  useEffect(() => {
    if (Number.isFinite(index) && !games.has(index)) void loadGame(index)
  }, [index, games, loadGame])

  if (!Number.isFinite(index)) {
    return (
      <div className={styles.page}>
        <EmptyState title="No game selected">That URL has no game id.</EmptyState>
      </div>
    )
  }

  if (!game) {
    return (
      <div className={styles.page}>
        <Skeleton height={420} />
      </div>
    )
  }

  const startPly = Math.max(0, Math.min(game.moves.length - 1, Number.parseInt(ply ?? '0', 10) || 0))
  return <PlayBody game={game} startPly={startPly} />
}

function PlayBody({ game, startPly }: { game: GameDetail; startPly: number }) {
  const startFen = game.moves[startPly]?.fen_after ?? START_FEN

  const chess = useRef(new Chess(startFen))
  const [fen, setFen] = useState(startFen)
  const [flipped, setFlipped] = useState(game.player_color === 'black')
  const [history, setHistory] = useState<PlayMove[]>([])
  /** Index of the last move played; -1 means nothing played yet. */
  const [cursor, setCursor] = useState(-1)
  const [verdict, setVerdict] = useState<AnalysisResult | null>(null)
  const [busy, setBusy] = useState(false)
  const [serverDown, setServerDown] = useState(isStandalone)
  const [serverNote, setServerNote] = useState(
    isStandalone
      ? 'This file is running standalone, so there is no engine behind it. Free play still works.'
      : '',
  )
  /** How many engine hints to draw. 1-3; remembered between visits. */
  const [hintCount, setHintCount] = useState(readHintCount)

  // Rebuild from scratch when the fork point changes.
  useEffect(() => {
    chess.current = new Chess(startFen)
    setFen(startFen)
    setHistory([])
    setCursor(-1)
    setVerdict(null)
  }, [startFen])

  // Probe the engine once, so the UI can say *why* it is unavailable rather than
  // failing on the visitor's first move.
  useEffect(() => {
    if (isStandalone || window.location.protocol === 'file:') return
    let cancelled = false
    api
      .health()
      .then((health) => {
        if (cancelled) return
        if (!health.ok) {
          setServerDown(true)
          setServerNote(health.error || 'No engine available. Free play still works.')
        }
      })
      .catch(() => {
        if (cancelled) return
        setServerDown(true)
        setServerNote(
          'The analysis server is not reachable. Start it with `python serve.py` — free play still works.',
        )
      })
    return () => {
      cancelled = true
    }
  }, [])

  const dests = useMemo(() => {
    const map = new Map<string, string[]>()
    const game_ = chess.current
    if (!game_.isGameOver()) {
      for (const move of game_.moves({ verbose: true })) {
        const list = map.get(move.from) ?? []
        list.push(move.to)
        map.set(move.from, list)
      }
    }
    return map
  }, [fen])

  const turnColor: 'w' | 'b' = fen.split(' ')[1] === 'w' ? 'w' : 'b'
  const gameOver = chess.current.isGameOver()

  /** Apply a move locally, then optionally ask the engine about it. */
  const play = useCallback(
    (from: string, to: string) => {
      const game_ = chess.current
      if (game_.isGameOver()) return

      // The position *before* the move is what the server has to score: it
      // re-derives the "after" evaluation itself, and a move is illegal in the
      // position it created. Captured before pushing, because the first draft
      // read game_.fen() afterwards and every request came back 400.
      const fenBefore = game_.fen()

      // chess.js is the only authority on legality. Promotion defaults to a
      // queen, which is the common case and is the one the arrow would imply.
      let move
      try {
        move = game_.move({ from, to, promotion: 'q' })
      } catch {
        return
      }
      if (!move) return

      const uci = from + to + (move.promotion ?? '')
      /*
       * Every move you make is scored, in both-colour free play. This used to
       * be `opponent === 'engine'`, i.e. only in the mode that has since been
       * removed -- which would have left free play as an unscored sandbox. The
       * score is the point of having an engine on the page at all, and it is
       * also what the hint arrows and the verdict panel are read against.
       */
      const willSearch = !serverDown

      setHistory((prev) => {
        // Anything after the cursor is a redo branch; drop it.
        const next = prev.slice(0, cursor + 1)
        next.push({ uci, san: move.san, pending: willSearch, result: null })
        return next
      })
      setCursor((c) => c + 1)
      setFen(game_.fen())
      setVerdict(null)

      if (!willSearch) return

      setBusy(true)
      const index = cursor + 1
      api
        .analyse({ fen: fenBefore, uci })
        .then((result) => {
          setHistory((prev) => {
            const next = [...prev]
            if (next[index]) next[index] = { ...next[index], result, pending: false }
            return next
          })
          setVerdict(result)
        })
        .catch((cause: unknown) => {
          if (cause instanceof ApiUnavailable) {
            setServerDown(true)
            setServerNote('Engine unreachable — moves are not being scored.')
          }
          // Resolve the move either way: a spinner that never stops is worse
          // than a move with no verdict.
          setHistory((prev) => {
            const next = [...prev]
            if (next[index]) next[index] = { ...next[index], pending: false }
            return next
          })
        })
        .finally(() => setBusy(false))
    },
    [cursor, serverDown],
  )

  const undo = useCallback(() => {
    if (cursor < 0) return
    chess.current.undo()
    const at = cursor - 1
    setFen(chess.current.fen())
    setHistory((prev) => prev.slice(0, at + 1))
    setCursor(at)
    setVerdict(null)
  }, [cursor])

  const reset = useCallback(() => {
    chess.current = new Chess(startFen)
    setFen(startFen)
    setHistory([])
    setCursor(-1)
    setVerdict(null)
  }, [startFen])

  /** Replay the recorded moves up to `index` and show that position. */
  const jumpTo = useCallback(
    (index: number) => {
      const game_ = new Chess(startFen)
      for (let i = 0; i <= index && i < history.length; i += 1) {
        game_.move(history[i].uci.slice(0, 4))
      }
      chess.current = game_
      setFen(game_.fen())
      setCursor(index)
      setVerdict(history[index]?.result ?? null)
    },
    [history, startFen],
  )

  const arrows: BoardArrow[] = []
  const current = cursor >= 0 ? history[cursor] : null
  if (current) {
    arrows.push({ from: current.uci.slice(0, 2), to: current.uci.slice(2, 4), colour: 'blue' })
  }
  if (verdict?.best_uci && current && verdict.best_uci !== current.uci) {
    arrows.push({
      from: verdict.best_uci.slice(0, 2),
      to: verdict.best_uci.slice(2, 4),
      colour: 'green',
    })
  }

  /*
   * The engine's suggestions for this position.
   *
   * Skipped entirely when the game is over or the engine is gone: a hint on a
   * finished game is noise, and the hook skips the request when disabled rather
   * than letting it fail.
   */
  const hintsOn = !serverDown && !gameOver
  const hints = useEngineHints(fen, hintCount, hintsOn)

  for (const hint of hints) {
    const from = hint.uci.slice(0, 2)
    const to = hint.uci.slice(2, 4)
    // Drop a hint that repeats the move just played, or repeats an arrow
    // already drawn. Two identical translucent arrows at different opacities
    // look like a rendering bug, and the engine's own pick is already the green
    // one above.
    if (arrows.some((a) => a.from === from && a.to === to)) continue
    arrows.push({ from, to, colour: hintBrush(hint.rank) })
  }

  const headers = game.headers
  const elo = (side: 'White' | 'Black') => {
    const value = Number.parseInt(headers[`${side}Elo`] ?? '', 10)
    return Number.isFinite(value) && value > 0 ? value : null
  }
  const whiteToMove = turnColor === 'w'

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <div>
          <h1>Try this position</h1>
          <div className={styles.sub}>
            forked from {headers.White ?? 'White'} vs {headers.Black ?? 'Black'} · after move{' '}
            {Math.floor(startPly / 2) + 1}
          </div>
        </div>
        <Link className={styles.back} to={`${ROUTES.game(game.index)}/${startPly}`}>
          ← back to the analysis
        </Link>
      </header>

      {serverDown ? <ErrorNote>{serverNote}</ErrorNote> : null}

      <div className={styles.columns}>
        <div className={styles.boardColumn}>
          <PlayerBar
            name={whiteToMove ? headers.White : headers.Black}
            elo={whiteToMove ? elo('White') : elo('Black')}
            /*
             * Both sides are yours now that there is no engine opponent, so the
             * "you" pill marks the side to move -- the one you are about to
             * play. It used to mark the side the engine was *not* playing.
             */
            isPlayer={whiteToMove}
          />

          <div className={styles.boardWrap}>
            <Board
              fen={fen}
              orientation={flipped ? 'black' : 'white'}
              tone="play"
              movable={{
                // chess.js speaks side-to-move; chessground speaks colour names.
                color: turnColor === 'w' ? 'white' : 'black',
                dests,
                onMove: play,
              }}
              turnColor={turnColor === 'w' ? 'white' : 'black'}
              arrows={arrows}
              lastMove={
                current ? [current.uci.slice(0, 2), current.uci.slice(2, 4)] : null
              }
            />
            <button
              className={styles.flip}
              onClick={() => setFlipped((v) => !v)}
              title="Flip the board"
              aria-label="Flip the board"
            >
              ⇅
            </button>
          </div>

          <PlayerBar
            name={whiteToMove ? headers.Black : headers.White}
            elo={whiteToMove ? elo('Black') : elo('White')}
            isPlayer={false}
          />
        </div>

        <div className={styles.side}>
          <div className={styles.controls}>
            <Button onClick={undo} disabled={cursor < 0} title="Undo (Backspace)">
              ⟲ undo
            </Button>
            <Button onClick={reset} title="Back to the analysed line">
              reset
            </Button>

            {/*
              How many suggestions to draw. A Segmented rather than a native
              select, so it matches the rest of the chrome.
            */}
            <span className={styles.hintCount}>
              <span className={styles.hintLabel}>hints</span>
              <Segmented
                ariaLabel="How many engine hints to show"
                value={hintCount}
                onChange={(value) => {
                  setHintCount(value as HintCount)
                  writeHintCount(value as number)
                }}
                options={HINT_OPTIONS}
              />
            </span>
          </div>

          {/* What the engine suggests here, as a line of text beside the arrows,
              because an arrow with no number is advice you cannot weigh. */}
          {/* `> 0`, not a bare `.length`: a falsy number renders as the digit itself, so
              `hints.length && …` prints a stray "0" whenever there are no hints. */}
          {hints.length > 0 && !busy ? (
            <ul className={styles.hintList}>
              {hints.map((hint) => (
                <li key={hint.uci} className={styles.hintRow}>
                  <span className={styles.hintSan}>{hint.san}</span>
                  <span className={styles.hintScore}>{hint.score_san}</span>
                  <span className={styles.hintMeta}>depth {hint.depth}</span>
                </li>
              ))}
            </ul>
          ) : null}

          {busy ? (
            <div className={styles.busy}>
              <Spinner label="Engine is thinking" />
              <span>the engine is looking at your move…</span>
            </div>
          ) : null}

          {gameOver ? (
            <div className={styles.gameOver}>
              {chess.current.isCheckmate()
                ? `Checkmate. ${chess.current.turn() === 'w' ? 'Black' : 'White'} wins.`
                : chess.current.isDraw()
                  ? 'The game is drawn.'
                  : 'The game has ended.'}
            </div>
          ) : null}

          {verdict ? (
            <LiveVerdict result={verdict} />
          ) : (
            <p className={styles.hint}>
              Drag a piece, or click a square then a destination. Legal moves are
              highlighted. Castling, en passant and promotion all work.
            </p>
          )}

          <div className={styles.scoreline}>
            <h3>moves played here</h3>
            {history.length ? (
              <div className={styles.moveChips}>
                {history.map((move, i) => (
                  <button
                    key={i}
                    className={`${styles.chip} ${i === cursor ? styles.chipOn : ''} ${
                      move.result ? LABEL_CLASS[move.result.label as Label] : ''
                    }`}
                    onClick={() => jumpTo(i)}
                    title={
                      move.result
                        ? `${move.san} — ${move.result.label} ${move.result.glyph}`.trim()
                        : move.san
                    }
                  >
                    {move.san}
                    {move.pending ? <span className={styles.chipSpin} /> : null}
                  </button>
                ))}
              </div>
            ) : (
              <p className="muted small">Nothing played yet.</p>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

/** The engine's verdict on a move made here, in the review page's vocabulary. */
function LiveVerdict({ result }: { result: AnalysisResult }) {
  const tone = result.loss_pp > 25 ? 'bad' : result.loss_pp > 10 ? 'warn' : 'good'
  return (
    <div className={styles.verdict}>
      <div className={styles.verdictHead}>
        <span className={styles.verdictMove}>{result.san}</span>
        <span className={styles.verdictGlyph}>{result.glyph}</span>
        <Pill tone={tone}>{result.label}</Pill>
      </div>
      <div className={styles.verdictMetrics}>
        <span>
          eval {fmtEval(result.eval_before)} → {fmtEval(result.eval_after)}
        </span>
        <span>{result.loss_pp.toFixed(1)}pp lost</span>
        <span>accuracy {result.accuracy.toFixed(1)}</span>
        <span>
          depth {result.depth_reached} · {result.movetime_ms}ms
        </span>
      </div>
      {result.best_pv?.length ? (
        <div className={styles.verdictLine}>
          <b>engine line</b> {result.best_pv.join(' ')}
        </div>
      ) : null}
      {result.sacrifice ? (
        <div className={styles.verdictLine}>
          <b>sacrifice</b> {result.sacrifice} points of material given up
        </div>
      ) : null}
    </div>
  )
}