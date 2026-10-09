/**
 * Which ply is selected, and the chrome around it.
 *
 * Deliberately small and in-memory: one writer, several readers, and nothing
 * worth persisting. A game view is a transient thing — reopening the page at the
 * move you were reading would be nice, and is not what anyone is missing.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react'
import type { ReactNode } from 'react'
import type { GameDetail } from '../api/types'
import type { Cursor, ForkMove, Variation } from '../lib/variation'

export type GameTab = 'moves' | 'info' | 'openings'
export type Speed = 1 | 2 | 4

interface GameViewState {
  game: GameDetail | null
  /**
   * The recorded ply the cursor is on.
   *
   * Meaningful only when `cursor.line === 'main'`; while it is `'fork'` this holds
   * the ply the variation forks from, which is what the banner and the "back to the
   * game" button need.
   */
  ply: number
  /** Which line the cursor is on. See `lib/variation`. */
  cursor: Cursor
  /** The alternative continuation, or null when none has been played. */
  variation: Variation | null
  flipped: boolean
  playing: boolean
  speed: Speed
  tab: GameTab
  /** Jump to a ply, clamped to the game's length. Leaves any variation. */
  select: (ply: number) => void
  step: (delta: number) => void
  first: () => void
  last: () => void
  setFlipped: (value: boolean | ((prev: boolean) => boolean)) => void
  togglePlay: () => void
  setPlaying: (value: boolean) => void
  setSpeed: (value: Speed) => void
  setTab: (tab: GameTab) => void
  /** Move the cursor into the variation at `index`, clamped to its length. */
  selectFork: (index: number) => void
  /** Leave the variation and return to `variation.basePly + 1`. */
  returnToMain: () => void
  /** Start a variation rooted at the current ply. Replaces any existing one. */
  forkFrom: (basePly: number) => void
  /** Append a move to the current variation and step the cursor into it. */
  pushForkMove: (move: ForkMove) => void
  /**
   * Replace the move at `index` — how a fork move's verdict arrives.
   *
   * Replaces rather than merges so the scored `MoveView` is the whole truth: the
   * pending placeholder was a guess, and leaving half of it behind would show a
   * `good` label next to a `blunder`.
   */
  replaceForkMove: (index: number, move: ForkMove) => void
  /** Remove the variation's last move; leaves the variation when it empties. */
  popForkMove: () => void
  /** True when the cursor is inside a variation. */
  inFork: boolean
}

const Ctx = createContext<GameViewState | null>(null)

export function GameViewProvider({
  game,
  initialPly = 0,
  children,
}: {
  game: GameDetail | null
  initialPly?: number
  children: ReactNode
}) {
  const [ply, setPly] = useState(0)
  const [cursor, setCursor] = useState<Cursor>({ line: 'main', ply: 0 })
  const [variation, setVariation] = useState<Variation | null>(null)
  const [flipped, setFlipped] = useState(false)
  const [playing, setPlaying] = useState(false)
  const [speed, setSpeed] = useState<Speed>(1)
  const [tab, setTab] = useState<GameTab>('moves')

  /*
   * The cursor, readable and writable synchronously.
   *
   * State is only refreshed when this component re-renders, and holding `→` fires
   * keydown about thirty times a second — several presses arrive inside one batched
   * render. Each would then compute the next position from the same stale value and
   * three presses would advance a single ply. Worse, the two would disagree: React
   * would commit whichever landed last.
   *
   * So the ref is written *eagerly*, at call time, before the state update goes out.
   * A burst of keys accumulates instead of collapsing, and the next render
   * reconciles the ref with the committed state. It lives here rather than in a page
   * hook because every caller has the same requirement.
   */
  const cursorRef = useRef<Cursor>(cursor)
  cursorRef.current = cursor

  const lastPly = (game?.moves.length ?? 1) - 1
  const inFork = cursor.line === 'fork'

  /*
   * Reset when the game changes, or a previous game's ply leaks into the next.
   *
   * Clamped rather than seeded raw: `initialPly` comes from the URL, so
   * `/games/1/9999` put the view past the end of the move list and every
   * lookup fell through to the empty-board fallback. `select()` and `step()`
   * already clamped; the seed did not.
   *
   * The variation is dropped with it. A continuation keyed to a different game is
   * the one piece of state here that would be genuinely wrong rather than merely
   * stale, so it is cleared in the same effect rather than carried across.
   */
  useEffect(() => {
    const clamped = Math.max(0, Math.min(lastPly, initialPly))
    setPly(clamped)
    cursorRef.current = { line: 'main', ply: clamped }
    setCursor(cursorRef.current)
    setVariation(null)
    setPlaying(false)
    setTab('moves')
  }, [game?.index, initialPly, lastPly])

  // Default the orientation to the player's colour, so their pieces are at the
  // bottom. Only on load — after that it is the reader's choice.
  useEffect(() => {
    setFlipped(game?.player_color === 'black')
  }, [game?.index, game?.player_color])

  /*
   * The recorded line's navigation. Every one of these leaves a variation, because
   * clicking the game means "show me the game" — the alternative is that reading the
   * game silently keeps pointing at a position you left, which is the failure mode
   * worth avoiding.
   */
  const select = useCallback(
    (next: number) => {
      const clamped = Math.max(0, Math.min(lastPly, next))
      setPly(clamped)
      cursorRef.current = { line: 'main', ply: clamped }
      setCursor(cursorRef.current)
    },
    [lastPly],
  )

  /**
   * One step, within whichever line the cursor is on.
   *
   * Inside a variation, stepping walks the variation and clamps at its end. It never
   * falls back to the recorded line: a reader pressing `→` expects to move forward,
   * and teleporting them out of the variation reads as a glitch. They click the game
   * to go back, which is unambiguous.
   *
   * Read from and written to the ref, not the state, so a burst of key repeats
   * accumulates.
   */
  const step = useCallback(
    (delta: number) => {
      const current = cursorRef.current
      if (current.line === 'fork' && variation) {
        const next: Cursor = {
          line: 'fork',
          ply: Math.max(0, Math.min(variation.moves.length - 1, current.ply + delta)),
        }
        cursorRef.current = next
        setCursor(next)
        return
      }
      select(current.ply + delta)
    },
    [variation, select],
  )

  const first = useCallback(() => select(0), [select])
  const last = useCallback(() => select(lastPly), [select, lastPly])

  const selectFork = useCallback(
    (index: number) => {
      if (!variation) return
      const next: Cursor = {
        line: 'fork',
        ply: Math.max(0, Math.min(variation.moves.length - 1, index)),
      }
      cursorRef.current = next
      setCursor(next)
    },
    [variation],
  )

  /*
   * Back to the game, at the move the variation forked *from* -- so the reader lands
   * on the row they were looking at when they left, not somewhere else in the game.
   */
  const returnToMain = useCallback(() => {
    if (!variation) return
    const target = Math.min(lastPly, variation.basePly + 1)
    setPly(target)
    cursorRef.current = { line: 'main', ply: target }
    setCursor(cursorRef.current)
  }, [variation, lastPly])

  const forkFrom = useCallback((basePly: number) => {
    setVariation({ basePly, moves: [] })
    cursorRef.current = { line: 'main', ply: basePly }
    setCursor(cursorRef.current)
    // Auto-play walks the recorded line and cannot walk a position that is not in
    // it, so it stops rather than carrying on behind the reader's back.
    setPlaying(false)
  }, [])

  const pushForkMove = useCallback((move: ForkMove) => {
    setVariation((prev) => {
      const base = prev ?? { basePly: move.ply, moves: [] }
      return { ...base, moves: [...base.moves, move] }
    })
    // Step into the move just played, so the board shows its position.
    const next: Cursor = {
      line: 'fork',
      ply: cursorRef.current.line === 'fork' ? cursorRef.current.ply + 1 : 0,
    }
    cursorRef.current = next
    setCursor(next)
  }, [])

  const replaceForkMove = useCallback((index: number, move: ForkMove) => {
    setVariation((prev) => {
      if (!prev) return prev
      const moves = [...prev.moves]
      if (index < 0 || index >= moves.length) return prev
      moves[index] = move
      return { ...prev, moves }
    })
  }, [])

  const popForkMove = useCallback(() => {
    if (!variation || variation.moves.length === 0) return
    if (variation.moves.length === 1) {
      // Removing the only move leaves nothing to show, so the variation goes and the
      // cursor returns to the recorded position it forked from. Same gesture as
      // stepping back one ply.
      const target = Math.min(lastPly, variation.basePly)
      setVariation(null)
      setPly(target)
      cursorRef.current = { line: 'main', ply: target }
      setCursor(cursorRef.current)
      return
    }
    setVariation({ ...variation, moves: variation.moves.slice(0, -1) })
    const next: Cursor = {
      line: 'fork',
      ply: Math.max(0, cursorRef.current.ply - 1),
    }
    cursorRef.current = next
    setCursor(next)
  }, [variation, lastPly])

  // Auto-play. Intervals are cleared before each new one is set, so changing
  // speed mid-play does not leave the old timer running.
  useEffect(() => {
    if (!playing) return
    const id = window.setInterval(() => {
      setPly((p) => {
        if (p >= lastPly) {
          setPlaying(false)
          return p
        }
        return p + 1
      })
    }, 1100 / speed)
    return () => window.clearInterval(id)
  }, [playing, speed, lastPly])

  const togglePlay = useCallback(() => {
    // Pressing play at the end restarts, which is what a transport is expected to
    // do rather than doing nothing.
    if (!playing && ply >= lastPly) {
      setPly(0)
      cursorRef.current = { line: 'main', ply: 0 }
      setCursor(cursorRef.current)
    }
    setPlaying((p) => !p)
  }, [playing, ply, lastPly])

  const value = useMemo<GameViewState>(
    () => ({
      game,
      ply,
      cursor,
      variation,
      inFork,
      flipped,
      playing,
      speed,
      tab,
      select,
      step,
      first,
      last,
      setFlipped,
      togglePlay,
      setPlaying,
      setSpeed,
      setTab,
      selectFork,
      returnToMain,
      forkFrom,
      pushForkMove,
      replaceForkMove,
      popForkMove,
    }),
    [
      game, ply, cursor, variation, inFork, flipped, playing, speed, tab,
      select, step, first, last, togglePlay, selectFork, returnToMain,
      forkFrom, pushForkMove, replaceForkMove, popForkMove,
    ],
  )

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

export function useGameView(): GameViewState {
  const ctx = useContext(Ctx)
  if (!ctx) throw new Error('useGameView must be used inside <GameViewProvider>')
  return ctx
}

/** The currently selected recorded move, or null before anything is loaded. */
export function useSelectedMove() {
  const { game, ply, inFork } = useGameView()
  // Inside a variation the recorded move at `ply` is the one the fork starts from,
  // not the one being read, so there is no "selected move" to report.
  if (inFork) return null
  return game?.moves[ply] ?? null
}