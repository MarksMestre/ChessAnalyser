/**
 * One shape for a move, however it came to be.
 *
 * Two things produce moves on this app and they do not agree on a type: the batch
 * analysis writes a full `Move` per recorded ply, and `POST /api/analyse` returns an
 * `AnalysisResult` for a move somebody just played. They overlap almost entirely and
 * differ in the details — `phase` and `in_book` exist only on the recorded one,
 * `depth_reached` only on the live one — which previously meant the commentary panel
 * took a `Move` plus an optional `live`, and a variation had no `Move` to pass at all.
 *
 * So both are projected onto `MoveView` here, and every consumer reads that. A row in
 * the move list, a row in a variation, and the commentary panel are then the same code
 * whether the move was played in 1858 or thirty seconds ago.
 */

import type { AnalysisResult, Label, Move, Phase, PlayerColor } from '../api/types'

/** A move, from either source, in the shape the views need. */
export interface MoveView {
  /** Stable across the two sources, so a list can key on it. */
  key: string
  ply: number
  move_number: number
  color: PlayerColor
  san: string
  uci: string
  label: Label
  glyph: string
  /** False for the opponent's moves, which are never labelled. */
  is_players_turn: boolean
  eval_before: number | null
  eval_after: number | null
  loss_pp: number
  accuracy: number
  gap_pp: number | null
  best_san: string | null
  /** The engine's move in UCI, for drawing the green arrow. */
  best_uci: string | null
  best_pv: string[]
  verified: boolean
  depth: number
  in_book: boolean
  left_book: boolean
  sacrifice: number | null
  /** True while the engine has not answered yet. */
  pending: boolean
  /**
   * True when no engine was asked at all.
   *
   * Distinct from `pending`, and the distinction is the whole point: `pending` means
   * an answer is coming, `unscored` means nothing will ever arrive. Without it a
   * standalone report claims to be thinking about a move forever, and — worse — the
   * placeholder label and its commentary would be presented as a real judgement.
   */
  unscored?: boolean
  /*
   * The three fields below exist only on a recorded move. They are on the shared
   * shape rather than left behind so that `commentary.ts` stays one generator for
   * both sources: it can simply test them, instead of the panel needing a second
   * prose path for a move that has no Lc0 data.
   */
  phase?: Phase
  lc0_best_san?: string | null
  lc0_agrees?: boolean | null
  notes?: string[]
}

/** A recorded move, straight out of `data.json`. */
export function fromRecorded(m: Move): MoveView {
  return {
    key: `m${m.ply}`,
    ply: m.ply,
    move_number: m.move_number,
    color: m.color,
    san: m.san,
    uci: m.uci,
    label: m.label,
    glyph: m.glyph,
    is_players_turn: m.is_players_turn,
    eval_before: m.eval_before,
    eval_after: m.eval_after,
    loss_pp: m.loss_pp,
    accuracy: m.accuracy,
    gap_pp: m.gap_pp,
    best_san: m.best_san,
    best_uci: m.best_uci,
    best_pv: m.best_pv ?? [],
    verified: m.verified,
    depth: m.depth,
    in_book: m.in_book,
    left_book: m.left_book,
    sacrifice: m.sacrifice,
    pending: false,
    phase: m.phase,
    lc0_best_san: m.lc0_best_san,
    lc0_agrees: m.lc0_agrees,
    notes: m.notes,
  }
}

/**
 * A move just played, from the server's verdict.
 *
 * The position facts come from `base` because the response only describes the search:
 * which side moved, what number it was, and where it sits in its own line are all
 * things only the caller knows.
 *
 * `verified` is `true` when the engine actually answered. It is not the same claim as
 * the recorded `verified` — that one means "re-checked at depth 24" — but it is the
 * closest thing the live path has, and the commentary panel only uses it to decide
 * whether to name a depth, which is exactly what it should gate on.
 */
export function fromAnalysis(
  a: AnalysisResult,
  base: {
    uci: string
    san?: string | null
    moveNumber: number
    color: PlayerColor
    ply: number
    pending?: boolean
  },
): MoveView {
  const san = base.san || a.san || ''
  return {
    key: `f${base.ply}-${base.uci}`,
    ply: base.ply,
    move_number: base.moveNumber,
    color: base.color,
    san,
    uci: base.uci,
    label: a.label,
    glyph: a.glyph,
    // Both sides are the reader's in free play, so a move played here is always
    // "the player's" as far as labelling goes.
    is_players_turn: true,
    eval_before: a.eval_before,
    eval_after: a.eval_after,
    loss_pp: a.loss_pp,
    accuracy: a.accuracy,
    gap_pp: a.gap_pp,
    best_san: a.best_san,
    best_uci: a.best_uci,
    best_pv: a.best_pv ?? [],
    verified: !base.pending,
    depth: a.depth_reached,
    // Not derivable: a move played here is not in any stored opening line, and the
    // book is a property of the recorded game.
    in_book: false,
    left_book: false,
    sacrifice: a.sacrifice,
    pending: base.pending ?? false,
  }
}

/** A move that exists but has no verdict yet — the request is still in flight. */
export function pendingAnalysis(base: {
  uci: string
  san: string
  moveNumber: number
  color: PlayerColor
  ply: number
}): MoveView {
  return fromAnalysis(
    {
      label: 'good',
      glyph: '',
      san: base.san,
      fen: '',
      fen_after: '',
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
      terminated: false,
      result: '*',
    },
    { ...base, pending: true },
  )
}