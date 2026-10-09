/**
 * The X best moves for the position on the board, as translucent grey arrows.
 *
 * Free play asks "what would you play here?", and the answer is only useful if
 * it arrives without the board stuttering. Two things make that true:
 *
 * **A debounce, and it is not an optimisation.** Every position change fires a
 * request, and `serve.py` runs *one* Stockfish behind a `threading.Lock`
 * (serve.py:143). Step through a fork quickly and every position queues behind
 * the last, so the arrows for the position you are looking at arrive after you
 * have already moved on. 250ms is long enough to swallow a burst.
 *
 * **Abort and discard.** A slow answer for an old position must not overwrite a
 * new one, so the request is aborted when the FEN changes and its result is
 * dropped if it lands late.
 *
 * Degrades to no arrows when there is no server. The standalone build has none
 * by definition, so this is the expected state there rather than an error.
 */

import { useEffect, useRef, useState } from 'react'
import { api } from '../api/client'
import type { EngineHint, Hints } from '../api/types'

/** How long to wait after the last position change before asking. */
const DEBOUNCE_MS = 250

/** The stored preference, defensively: a corrupt value must not throw on load. */
export function readHintCount(): number {
  try {
    const raw = window.localStorage.getItem('chess-coach.hintCount')
    const value = Number.parseInt(raw ?? '', 10)
    // 1..3 is the whole range the selector offers.
    return value >= 1 && value <= 3 ? value : 1
  } catch {
    // Private browsing, or a blocked origin. A default is fine.
    return 1
  }
}

export function writeHintCount(count: number): void {
  try {
    window.localStorage.setItem('chess-coach.hintCount', String(count))
  } catch {
    /* Not being able to remember the preference is not worth a dialog. */
  }
}

/**
 * The hints for `fen`, or `[]` while loading and whenever the engine is absent.
 *
 * `count` is how many to ask for. `enabled` is false when there is no server,
 * which skips the request entirely rather than letting it fail.
 */
export function useEngineHints(fen: string, count: number, enabled: boolean): Hints['moves'] {
  const [moves, setMoves] = useState<Hints['moves']>([])
  // Guards against a late answer landing after the FEN moved on.
  const generation = useRef(0)

  useEffect(() => {
    if (!enabled || count <= 0) {
      setMoves([])
      return
    }

    const mine = (generation.current += 1)
    const controller = new AbortController()
    let timer = 0

    timer = window.setTimeout(() => {
      api
        .hints({ fen, multipv: count }, controller.signal)
        .then((result) => {
          if (mine === generation.current) setMoves(result.moves)
        })
        .catch(() => {
          // Aborted, or the server went away mid-flight. Either way there is
          // nothing to draw, and the page already says the engine is absent.
          if (mine === generation.current) setMoves([])
        })
    }, DEBOUNCE_MS)

    return () => {
      window.clearTimeout(timer)
      controller.abort()
    }
  }, [fen, count, enabled])

  return moves
}

export type { EngineHint }