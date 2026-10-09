/**
 * Alternative continuations: a move played on the analysis board that the game did
 * not play, and the line it grows into.
 *
 * One variation at a time, rooted in the recorded line. Not a tree, not nested, not
 * linkable — the whole point is that picking up a piece and dragging it needs no
 * button and no new page, and one subline covers that.
 */

import type { GameDetail } from '../api/types'
import type { MoveView } from './moveView'
import { fromRecorded } from './moveView'

/** A move played here that the recorded game did not play. */
export interface ForkMove extends MoveView {
  /** Position before the move: the next `dests`, and what the server is asked about. */
  fen_before: string
  /** Position after the move: what the board shows while the cursor is on it. */
  fen_after: string
}

/** One alternative continuation, rooted in the recorded line. */
export interface Variation {
  /**
   * The recorded ply whose `fen_after` this starts from — the last shared ply.
   *
   * So the starting position is `game.moves[basePly].fen_after` and no FEN needs
   * storing for the base.
   */
  basePly: number
  moves: ForkMove[]
}

/** Which line the cursor is on, and where in it. */
export type Cursor =
  | { line: 'main'; ply: number }
  /** Index into `variation.moves`. */
  | { line: 'fork'; ply: number }

/**
 * Does this move follow the game, or fork it?
 *
 * The whole fork rule is this one comparison, which is why it is a function: at the
 * last ply there is no recorded next move, so every legal move forks, and that case
 * falls out of `undefined !== played` rather than needing a branch at the call site.
 */
export function forkDecision(
  recordedUci: string | undefined,
  playedUci: string,
): 'advance' | 'fork' {
  return recordedUci === playedUci ? 'advance' : 'fork'
}

/** The position a cursor names, for the board, the eval bar and the commentary panel. */
export function positionAt(
  game: GameDetail,
  cursor: Cursor,
  variation: Variation | null,
): { fen: string; uci: string | null; view: MoveView | null } {
  if (cursor.line === 'fork' && variation) {
    const move = variation.moves[Math.min(cursor.ply, variation.moves.length - 1)]
    if (move) return { fen: move.fen_after, uci: move.uci, view: move }
  }
  // Anything the cursor cannot name resolves to the recorded line, clamped: a cursor
  // pointing past a fork that was replaced must not leave the board blank.
  const ply = Math.max(0, Math.min(game.moves.length - 1, cursor.ply))
  const move = game.moves[ply]
  return {
    fen: move?.fen_after ?? '',
    uci: move?.uci ?? null,
    view: move ? fromRecorded(move) : null,
  }
}

/** One `N. white black` grouping of a run of moves. */
export interface RunRow<T extends MoveView = MoveView> {
  number: number
  white?: T
  black?: T
}

/**
 * Regroup a run of moves into numbered white/black pairs.
 *
 * The pairing comes from each move's own colour rather than from its index. A fork
 * can begin on Black's move, and grouping by index would then print `3... c5 3. d4` —
 * two different moves under one number. That is the mistake this exists to prevent,
 * and it is why `groupMoves` in MoveList.tsx (which pairs by `move_number` and is
 * therefore safe for a run that starts on White) is not reused here.
 *
 * A row is only reused when the half it needs is still free. Two White moves carrying
 * the same `move_number` cannot both be printed, and silently keeping the second would
 * drop a move from the line without saying so — so the second opens a new row instead.
 *
 * Generic over the element type so a run of `ForkMove`s stays typed as such, which is
 * what lets the caller look a row's move back up in its own array by identity.
 */
export function groupRun<T extends MoveView>(moves: T[]): RunRow<T>[] {
  const rows: RunRow<T>[] = []
  for (const move of moves) {
    const slot = move.color === 'white' ? 'white' : 'black'
    let row = rows.find(
      (r) => r.number === move.move_number && r[slot] === undefined,
    )
    if (!row) {
      row = { number: move.move_number }
      rows.push(row)
    }
    row[slot] = move
  }
  return rows
}

/** The move number a ply falls in. Ply 0 is White's first move. */
export function moveNumberOf(ply: number): number {
  return Math.floor(ply / 2) + 1
}