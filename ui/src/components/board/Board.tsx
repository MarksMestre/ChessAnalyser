/**
 * The board, wrapped around chessground.
 *
 * chessground is the board Lichess uses. Hand-rolling this on top of the old
 * SVG renderer would mean reimplementing drag-and-drop, legal-move
 * highlighting, castling, en passant, promotion and piece animation — all of
 * which the library already gets right, including the animation that makes a
 * move legible.
 *
 * Everything the plan asks for lives at this boundary: arrows for your move and
 * the engine's, the last-move highlight, the check square, coordinates, and a
 * playable mode for the experiment feature.
 */

import { useEffect, useRef, useState } from 'react'
import { Chessground } from 'chessground'
import type { Api } from 'chessground/api'
import type { Config } from 'chessground/config'
import type { Key } from 'chessground/types'
import './chessground.css'
import styles from './Board.module.css'

/**
 * Arrow brushes.
 *
 * `green`/`red`/`blue`/`yellow` are chessground's own and mean something
 * specific everywhere else in this app: your move against the engine's. The
 * `hint*` brushes are ours, defined below, and they are *only* for the free-play
 * suggestions -- reusing a built-in brush for them would make a hint look like
 * "the engine wanted this", which is a different claim.
 */
export type ArrowColour = 'green' | 'red' | 'blue' | 'yellow' | 'hint1' | 'hint2' | 'hint3'

export interface BoardArrow {
  from: string
  to: string
  colour: ArrowColour
}

/**
 * Brushes for the free-play hints.
 *
 * Declared rather than inherited so the three ranks are visibly different:
 * rank 1 is the thickest and the most opaque, so "the best move" is legible at
 * a glance and the runner-ups recede. Grey, because a hint is advice and not a
 * verdict -- it should not compete with the red and green move arrows.
 */
const HINT_BRUSHES = {
  hint1: { key: 'hint1', color: '#8b94a7', opacity: 0.55, lineWidth: 12 },
  hint2: { key: 'hint2', color: '#616b80', opacity: 0.4, lineWidth: 10 },
  hint3: { key: 'hint3', color: '#616b80', opacity: 0.26, lineWidth: 8 },
}

/**
 * The whole brush set, because `DrawBrushes` is not partial.
 *
 * The four built-ins are restated at chessground's own default values
 * (state.js). `configure()` deep-merges, so passing only the hints would work at
 * runtime -- but a partial object typed as the full interface is a lie that
 * would break the day someone reads the built-in colours from here.
 */
const BRUSHES = {
  green: { key: 'g', color: '#15781B', opacity: 1, lineWidth: 10 },
  red: { key: 'r', color: '#882020', opacity: 1, lineWidth: 10 },
  blue: { key: 'b', color: '#003088', opacity: 1, lineWidth: 10 },
  yellow: { key: 'y', color: '#e68f00', opacity: 1, lineWidth: 10 },
  ...HINT_BRUSHES,
}

export interface BoardProps {
  fen: string
  orientation?: 'white' | 'black'
  arrows?: BoardArrow[]
  /**
   * Lighter square tones, for the pages where you are playing rather than
   * reading. A tone, not a theme: the overlays and the artwork are unchanged.
   */
  tone?: 'analysis' | 'play'
  /**
   * Whose turn it is.
   *
   * This must be passed explicitly: chessground's FEN reader stops at the first
   * space and only extracts pieces, so the side to move is *not* taken from the
   * FEN. Left unset it defaults to white, which makes Black's pieces unmovable
   * even when `dests` lists their moves — the board then highlights legal
   * squares and silently ignores every click on them.
   */
  turnColor?: 'white' | 'black'
  /** Set for play mode; `dests` comes from the rules engine. */
  movable?: {
    color: 'white' | 'black' | 'both'
    dests: Map<string, string[]>
    onMove: (from: string, to: string, promoted?: string) => void
  }
  /** The two squares of the move just played, for the last-move highlight. */
  lastMove?: [string, string] | null
  animationMs?: number
}

/** Position of the king of the side to move, for the check highlight. */
function kingSquare(fen: string): string | null {
  const turn = fen.split(' ')[1]
  const king = turn === 'w' ? 'K' : 'k'
  const files = 'abcdefgh'
  const rows = fen.split(' ')[0].split('/')
  for (let rowIndex = 0; rowIndex < rows.length; rowIndex += 1) {
    const rank = 8 - rowIndex
    let file = 0
    for (const ch of rows[rowIndex]) {
      if (ch >= '1' && ch <= '8') {
        file += Number(ch)
      } else {
        if (ch === king) return `${files[file]}${rank}`
        file += 1
      }
    }
  }
  return null
}

/**
 * Whether tapping a square selects it, deselects it, or does neither.
 *
 * Chessground will happily select a piece of either colour, or one with no
 * legal move at all, and it will *keep* that selection when you then tap a
 * square that is neither the piece nor a legal destination: `selectSquare()`
 * tries the move, the move is rejected, and the fallthrough `isMovable` check
 * fails for an empty square, so the old selection survives untouched.
 *
 * That is the behaviour people read as "the board is stuck". So the rule is
 * decided here rather than asked of the library: a square is selected if it is
 * a legal origin for the side to move, and tapping anything else clears the
 * selection.
 *
 * Note what this must NOT do: it must not put the answer into React state and let
 * that flow back through the config. The selection is driven imperatively through
 * `api.selectSquare` instead -- see `Board`. Routing it through the config means a
 * re-initialisation on every tap, and the re-initialisation lands in the middle of
 * chessground's own `mousedown` handler, before it gets as far as trying the move.
 * The result is a board you can pick pieces up on and can never play a move on.
 */
export function selectBehaviour(
  key: string,
  dests: Map<string, string[]> | undefined,
): boolean {
  return Boolean(dests?.has(key))
}

export function Board(props: BoardProps) {
  const {
    fen,
    orientation = 'white',
    arrows = [],
    movable,
    lastMove,
    tone = 'analysis',
  } = props
  /*
   * The element chessground is mounted into.
   *
   * A container, not the board. Each chessground instance is given a *fresh* child
   * element, because `api.destroy()` does not fully undo what creation did:
   * `Chessground()` binds `mousedown`/`touchstart` on the board element itself and then
   * throws away `bindBoard`'s unbind (chessground.js:43), so `destroy()` — which only
   * unbinds what `bindDocument` returned (api.js:93) — leaves those listeners on the
   * element for good. Mounting into a reused element therefore stacks one handler per
   * re-initialisation, each bound to a state that has been marked destroyed.
   *
   * The symptom is not a leak you can see: the newest handler still draws correctly, so
   * selection looks perfect. But the stale ones also fire `events.select`, with a
   * `movable` from an older position, and the clear they schedule then lands on the
   * *live* board a moment later. Tapping a piece shows its destinations and then they
   * vanish; tapping a legal destination plays nothing. It is indistinguishable from a
   * board that ignores you.
   *
   * A fresh element per instance removes the whole class of problem — the old element
   * and every listener on it goes out of scope with the old instance.
   */
  const containerRef = useRef<HTMLDivElement>(null)

  /*
   * The live chessground instance.
   *
   * Held so the selection can be corrected imperatively, without rebuilding the
   * board. The previous version kept the selection in React state and passed it
   * through the config, which meant every selection change tore down and rebuilt the
   * whole board -- and the rebuild ran inside chessground's own `mousedown` handler,
   * before it reached the code that tries the move. Pieces could be picked up; moves
   * could never be played.
   */
  const apiRef = useRef<Api | null>(null)

  /*
   * The selected square, in React as well as inside chessground.
   *
   * One purpose only: naming it for screen readers, which chessground's own DOM
   * cannot do. It is never fed back into the board.
   */
  const [selected, setSelected] = useState<string | undefined>(undefined)

  // Cleared whenever the position changes: a selection describes the position it
  // was made in, and keeping it across a move shows the circles for a piece that has
  // moved. The board is rebuilt on a position change anyway, so chessground's own
  // selection goes with it; this only clears the copy the label reads.
  useEffect(() => {
    setSelected(undefined)
  }, [fen])

  // chessground ignores the side-to-move in the FEN, so derive it here and pass
  // it explicitly. Left unset it defaults to white, which makes Black's pieces
  // unmovable even when `dests` lists their moves: the board then highlights
  // legal squares and silently ignores every click on them.
  const turnColor: 'white' | 'black' =
    props.turnColor ?? (fen.split(' ')[1] === 'b' ? 'black' : 'white')

  // chessground is imperative, so the config is rebuilt and reapplied whenever
  // anything visible changes. There is no diffing to fight.
  const arrowKey = arrows.map((a) => `${a.from}${a.to}${a.colour}`).join(',')
  const destKey = movable ? JSON.stringify([...movable.dests]) : ''
  const lastKey = lastMove ? lastMove.join('') : ''

  useEffect(() => {
    const container = containerRef.current
    if (!container) return

    // A fresh element per instance, so nothing survives from the previous one.
    const el = document.createElement('div')
    el.className = styles.board
    container.appendChild(el)

    const checked = kingSquare(fen)
    const config: Config = {
      fen,
      orientation,
      coordinates: true,
      addPieceZIndex: true,
      autoCastle: true,
      turnColor,
      /*
       * chessground ignores untrusted events by default: `drag.start` returns
       * immediately unless `e.isTrusted` or `trustAllEvents` is set. That is a
       * sensible default for a public deployment, but it makes the board
       * impossible to drive from an automated test — and a board that cannot be
       * tested is a board whose interaction silently rots. Safe here because
       * the app is served from localhost with no authentication, and the events
       * that get through are still filtered by `movable.dests`, so nothing can
       * be moved that the rules engine has not already allowed.
       */
      trustAllEvents: true,
      animation: { enabled: true, duration: props.animationMs ?? 200 },
      ...(checked ? { check: true } : {}),
      ...(lastMove ? { lastMove: [lastMove[0] as Key, lastMove[1] as Key] } : {}),
      movable: movable
        ? {
            free: false,
            color: movable.color,
            dests: movable.dests as Map<Key, Key[]>,
            showDests: true,
            rookCastle: true,
            events: {
              after: (from, to) => movable.onMove(from, to),
              afterNewPiece: (role, key) => movable.onMove(key, key, role),
            },
          }
        : { free: false },
      /*
       * `events.select` fires *before* chessground applies the selection, and only
       * reports the square. That is enough to make the decision: if the tapped square
       * is a legal origin, leave chessground's own selection alone; otherwise clear it
       * here.
       *
       * The clear is imperative (`api.selectSquare(null)`) and fires *after* the event
       * returns, deliberately. Chessground is about to carry on through
       * `selectSquare` and set its own selection from this same tap; clearing it
       * during the callback would be overwritten a line later, and the stale-selection
       * bug would come straight back. Letting the tap finish and then overriding the
       * result is what makes the rule stick.
       *
       * React state is updated only for the screen-reader label, and never read back
       * into the config.
       */
      events: {
        select: (key: Key) => {
          const keep = movable ? selectBehaviour(key, movable.dests) : false
          setSelected(keep ? key : undefined)
          if (keep) return
          queueMicrotask(() => {
            if (apiRef.current) apiRef.current.selectSquare(null)
          })
        },
      },
      /*
       * Arrows are drawn rather than user-drawn, so the drawing UI is off and the
       * shapes are injected each time instead of being tracked in state.
       */
      drawable: {
        /*
         * `visible: true` but `enabled: false`, and both are load-bearing.
         *
         * `visible: false` looked like "don't show the drawing tool" and quietly
         * deleted the arrows instead: `renderWrap` only creates the `cg-shapes`
         * svg and the `cg-auto-pieces` container when `visible` is true
         * (wrap.js:33), so with it false there was no layer to draw into and
         * every shape -- your move, the engine's move, the free-play hints, and
         * the enlarged selected piece -- was silently dropped. `svg.renderSvg`
         * and `autoPieces.render` both guard on that container existing.
         *
         * `enabled: false` is what keeps the drawing *tool* off, and it is
         * separate: `drawClear` on a stray click is gated on `enabled`, not on
         * `visible`. So the layers exist and render our shapes, and a tap cannot
         * erase them.
         */
        enabled: false,
        visible: true,
        // Declared so `hint1..3` resolve.
        brushes: BRUSHES,
        shapes: arrows.map((arrow) => ({
          orig: arrow.from as Key,
          dest: arrow.to as Key,
          brush: arrow.colour,
        })),
      },
    }

    const api: Api = Chessground(el, config)
    apiRef.current = api

    /*
     * Re-measure and redraw when the element's own size changes, not just when the
     * window does.
     *
     * chessground caches its board box in a closure (`util.memo`, chessground.js:20) and
     * positions every piece from that cache. `updateBounds` is the only thing that clears
     * it, and it runs on creation and on *window* resize (chessground.js:41,43) — never
     * when the element merely moves or resizes within the page. And it does: the board
     * sits in a flex column beside a scrolling move list, so when that list renders and
     * the page grows a scrollbar, the column narrows and the board shrinks with it.
     *
     * The result is a board whose pieces are drawn at the old geometry and whose taps
     * are read against the old box, so a click resolves to the wrong square: nothing
     * selects and no move is ever played. It is intermittent, which is worse — it looks
     * like the board being unresponsive rather than mislaid.
     *
     * `api.redrawAll()` and not `state.dom.redrawNow()`: the latter renders straight
     * from the cached bounds, so it would faithfully redraw the stale geometry.
     * `redrawAll` re-measures first. It rebuilds the DOM layer to do so, which is safe
     * here because `renderWrap` empties the element (wrap.js:17) — the old element and
     * every listener on it go with it.
     */
    let lastWidth = 0
    let lastHeight = 0
    const observer = new ResizeObserver((entries) => {
      const box = entries[0]?.contentRect
      if (!box) return
      // Chessground rounds to whole pixels, so sub-pixel noise from a fractional layout
      // must not count as a change or this rebuilds on every frame of a transition.
      const width = Math.round(box.width)
      const height = Math.round(box.height)
      if (width === lastWidth && height === lastHeight) return
      lastWidth = width
      lastHeight = height
      api.redrawAll()
    })
    observer.observe(el)

    return () => {
      observer.disconnect()
      api.destroy()
      // Cleared before the next instance is assigned, so a queued
      // `selectSquare(null)` cannot land on a destroyed board.
      if (apiRef.current === api) apiRef.current = null
      // Takes this instance's listeners with it, which `destroy()` does not do.
      el.remove()
    }
  }, [
    fen,
    orientation,
    arrowKey,
    lastKey,
    destKey,
    turnColor,
    props.animationMs,
    movable?.color,
    // onMove is excluded deliberately, for the reason on onMove: it is usually a
    // fresh closure each render, and re-initialising the board on every parent
    // render would restart the piece animation.
    //
    // `selected` is excluded for a much sharper reason: including it re-created the
    // board on every tap, inside chessground's own mousedown handler, so a move could
    // never be played. It is driven imperatively instead -- see `apiRef`.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  ])

  return (
    <div
      className={`${styles.frame} ${tone === 'play' ? styles.framePlay : ''}`}
      /*
       * The selection and its destinations are drawn only — colour and shape, with
       * no text anywhere — so a screen reader has nothing to announce. Naming the
       * selected square and how many squares it reaches makes the board usable
       * without sight of it, which matters more now that the analysis board is
       * interactive rather than a picture of a game.
       */
      role="group"
      aria-label={
        selected && movable
          ? `Chessboard. Piece selected on ${selected}; ${
              movable.dests.get(selected)?.length ?? 0
            } legal destination${(movable.dests.get(selected)?.length ?? 0) === 1 ? '' : 's'}.`
          : 'Chessboard'
      }
    >
      {/* The board element itself is created per chessground instance -- see `containerRef`. */}
      <div ref={containerRef} />
    </div>
  )
}