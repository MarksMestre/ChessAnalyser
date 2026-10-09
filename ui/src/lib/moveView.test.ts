/**
 * Checks on the variation logic.
 *
 * These are the decisions that cannot be checked by looking at the page: which move
 * forks, how a run of fork moves is numbered, and what position a cursor resolves
 * to. Each one, done wrong, produces a board showing a position nobody chose.
 */

import { describe, expect, it } from 'vitest'
import type { AnalysisResult, GameDetail, Move } from '../api/types'
import { START_FEN } from './fen'
import { commentary } from './commentary'
import { fromAnalysis, pendingAnalysis } from './moveView'
import {
  forkDecision,
  groupRun,
  moveNumberOf,
  positionAt,
} from './variation'
import type { ForkMove, Variation } from './variation'

/* ------------------------------------------------------------- fixtures */

/** A recorded move, shaped like the real thing. */
function recorded(overrides: Partial<Move> = {}): Move {
  return {
    ply: 0,
    move_number: 1,
    color: 'white',
    san: 'e4',
    uci: 'e2e4',
    fen: '',
    fen_after: '',
    is_players_turn: true,
    phase: 'opening',
    eval_before: 30,
    eval_after: 25,
    win_percent_before: 52,
    win_percent_after: 51,
    loss_pp: 1,
    accuracy: 97,
    label: 'best',
    glyph: '',
    best_san: 'e4',
    best_uci: 'e2e4',
    best_pv: ['e4'],
    best_eval: 30,
    second_san: null,
    second_uci: null,
    second_eval: null,
    gap_pp: 3,
    in_book: false,
    left_book: false,
    legal: [],
    sacrifice: null,
    depth: 14,
    verified: false,
    survey_label: null,
    lc0_best_uci: null,
    lc0_best_san: null,
    lc0_eval: null,
    lc0_agrees: null,
    lc0_loss_pp: null,
    notes: [],
    ...overrides,
  }
}

/** A four-ply recorded line, each ply's `fen_after` naming itself. */
function gameOfFour(): GameDetail {
  const moves: Move[] = []
  const sans = ['e4', 'e5', 'Nf3', 'Nc6']
  const ucis = ['e2e4', 'e7e5', 'g1f3', 'b8c6']
  for (let ply = 0; ply < 4; ply += 1) {
    moves.push(
      recorded({
        ply,
        move_number: Math.floor(ply / 2) + 1,
        color: ply % 2 === 0 ? 'white' : 'black',
        san: sans[ply],
        uci: ucis[ply],
        fen_after: `fen-after-${ply}`,
        is_players_turn: ply % 2 === 0,
      }),
    )
  }
  return {
    headers: {},
    index: 1,
    player_color: 'white',
    player_name: 'me',
    opening: null,
    eco: null,
    book_end_ply: 0,
    accuracy: 80,
    accuracy_harmonic: 78,
    accuracy_mean: 80,
    acpl: 10,
    phase_accuracy: {},
    eval_curve: [30, 25, 20, 18],
    counts: {},
    result: '1-0',
    player_result: 'win',
    analysis_seconds: 1,
    moves,
  }
}

/**
 * A fork move.
 *
 * `moveNumber` is explicit rather than derived from the index: in a real game both
 * halves of a numbered move share it, so a run of [3...c5, 3...Nf6, 4.d4] carries
 * [3, 3, 4]. Deriving it from the index would produce [3, 4, 5] and quietly make
 * the grouping look correct while printing the wrong notation.
 */
function forked(
  index: number,
  color: 'white' | 'black',
  san: string,
  moveNumber = 3,
): ForkMove {
  return {
    ...pendingAnalysis({
      uci: `f${index}`,
      san,
      moveNumber,
      color,
      ply: index,
    }),
    fen_before: `before-${index}`,
    fen_after: `after-${index}`,
  }
}

/* --------------------------------------------------------- forkDecision */

describe('forkDecision', () => {
  it('follows the game when the move played is the one recorded', () => {
    expect(forkDecision('e2e4', 'e2e4')).toBe('advance')
  })

  it('forks on any move the game did not play', () => {
    expect(forkDecision('e2e4', 'd2d4')).toBe('fork')
  })

  it('forks when there is nothing recorded next, which is the last ply', () => {
    // Playing on from the end of the game is the most natural reason to want a
    // playable analysis board, and every move there forks.
    expect(forkDecision(undefined, 'e2e4')).toBe('fork')
  })

  it('never forks on an identical move', () => {
    // Including a promotion, whose UCI is five characters: an equality check on
    // four would treat a promoted queen as a different move.
    expect(forkDecision('a7a8q', 'a7a8q')).toBe('advance')
  })
})

/* ------------------------------------------------------------ positionAt */

describe('positionAt', () => {
  const game = gameOfFour()

  it('resolves a main-line cursor to that ply', () => {
    const at = positionAt(game, { line: 'main', ply: 2 }, null)
    expect(at.fen).toBe('fen-after-2')
    expect(at.uci).toBe('g1f3')
  })

  it('resolves a fork cursor to the forked position', () => {
    const variation: Variation = {
      basePly: 1,
      moves: [forked(0, 'white', 'c5'), forked(1, 'black', 'e6')],
    }
    expect(positionAt(game, { line: 'fork', ply: 0 }, variation).fen).toBe('after-0')
    expect(positionAt(game, { line: 'fork', ply: 1 }, variation).fen).toBe('after-1')
  })

  it('falls back to the recorded line for a fork cursor with no variation', () => {
    // A stale cursor after the variation was replaced must not blank the board.
    const at = positionAt(game, { line: 'fork', ply: 1 }, null)
    expect(at.fen).toBe('fen-after-1')
  })

  it('clamps a main-line cursor past the end of the game', () => {
    // Reachable from a URL, and the empty board it used to produce is worse than
    // showing the last position.
    expect(positionAt(game, { line: 'main', ply: 9999 }, null).fen).toBe('fen-after-3')
  })

  it('clamps a fork cursor past the end of the variation', () => {
    const variation: Variation = { basePly: 1, moves: [forked(0, 'white', 'c5')] }
    expect(positionAt(game, { line: 'fork', ply: 5 }, variation).fen).toBe('after-0')
  })

  it('handles a game with no moves at all', () => {
    const empty = { ...game, moves: [] }
    expect(positionAt(empty, { line: 'main', ply: 0 }, null).fen).toBe('')
  })
})

/* -------------------------------------------------------------- groupRun */

describe('groupRun', () => {
  it('pairs a run that starts on White', () => {
    const rows = groupRun([
      forked(0, 'white', 'c5', 3),
      forked(1, 'black', 'Nf6', 3),
      forked(2, 'white', 'd4', 4),
    ])
    expect(rows.map((r) => r.number)).toEqual([3, 4])
    expect(rows[0].white?.san).toBe('c5')
    expect(rows[0].black?.san).toBe('Nf6')
    expect(rows[1].white?.san).toBe('d4')
    expect(rows[1].black).toBeUndefined()
  })

  it('pairs a run that starts on Black, which the annex does', () => {
    // plans/Anexes/ANEX2.png opens its subline on Black's move: "2... c5 3. d4
    // cxd4 4. c4 d6". White's reply to a Black move is always the *next* number,
    // so the run carries [2, 3, 3, 4, 4]. Grouping by index instead of by colour
    // would print "3... c5 3. d4" — two different moves under one number.
    const rows = groupRun([
      forked(0, 'black', 'c5', 2),
      forked(1, 'white', 'd4', 3),
      forked(2, 'black', 'cxd4', 3),
      forked(3, 'white', 'c4', 4),
      forked(4, 'black', 'd6', 4),
    ])
    expect(rows.map((r) => r.number)).toEqual([2, 3, 4])
    // The first row holds Black's half only.
    expect(rows[0].white).toBeUndefined()
    expect(rows[0].black?.san).toBe('c5')
    expect(rows[1].white?.san).toBe('d4')
    expect(rows[1].black?.san).toBe('cxd4')
    expect(rows[2].white?.san).toBe('c4')
    expect(rows[2].black?.san).toBe('d6')
  })

  it('handles a single move', () => {
    const rows = groupRun([forked(0, 'black', 'c5', 2)])
    expect(rows).toHaveLength(1)
    expect(rows[0].black?.san).toBe('c5')
  })

  it('handles an empty run', () => {
    expect(groupRun([])).toEqual([])
  })

  it('puts each move in the slot matching its own colour', () => {
    const rows = groupRun([
      forked(0, 'white', 'a', 3),
      forked(1, 'black', 'b', 3),
      forked(2, 'white', 'c', 4),
      forked(3, 'black', 'd', 4),
    ])
    for (const row of rows) {
      // A row's White half is a White move and its Black half is a Black move.
      expect(row.white?.color ?? 'white').toBe('white')
      expect(row.black?.color ?? 'black').toBe('black')
    }
    expect(rows.flatMap((r) => [r.white?.san, r.black?.san].filter(Boolean))).toEqual([
      'a',
      'b',
      'c',
      'd',
    ])
  })

  it('does not drop a move when two share a number and a colour', () => {
    // Not reachable from one variation today, but `groupRun` is handed whatever it
    // gets, and keeping only the second would drop a move in silence.
    const rows = groupRun([forked(0, 'white', 'a', 3), forked(1, 'white', 'b', 3)])
    expect(rows).toHaveLength(2)
    expect(rows[0].white?.san).toBe('a')
    expect(rows[1].white?.san).toBe('b')
  })
})

/* ------------------------------------------------------------ fromAnalysis */

describe('fromAnalysis', () => {
  const result: AnalysisResult = {
    label: 'inaccuracy',
    glyph: '?!',
    san: 'Nf6',
    fen: START_FEN,
    fen_after: START_FEN,
    eval_before: 30,
    eval_after: -40,
    win_percent_before: 52,
    win_percent_after: 47,
    loss_pp: 5,
    accuracy: 92,
    best_san: 'd4',
    best_uci: 'd2d4',
    best_pv: ['d4', 'd5'],
    best_eval: 31,
    second_san: 'Nf6',
    second_uci: 'g1f3',
    second_eval: 22,
    gap_pp: 1.2,
    sacrifice: null,
    depth_reached: 12,
    movetime_ms: 240,
    terminated: false,
    result: '*',
  }

  const base = {
    uci: 'g1f3',
    san: 'Nf3',
    moveNumber: 2,
    color: 'white' as const,
    ply: 1,
  }

  it('carries the label, evaluation and loss across', () => {
    const view = fromAnalysis(result, base)
    expect(view.label).toBe('inaccuracy')
    expect(view.glyph).toBe('?!')
    expect(view.loss_pp).toBe(5)
    expect(view.eval_after).toBe(-40)
    expect(view.depth).toBe(12)
  })

  it('treats a played move as the player\'s, since both sides are', () => {
    expect(fromAnalysis(result, base).is_players_turn).toBe(true)
  })

  it('is not book: a played move is in no stored opening line', () => {
    const view = fromAnalysis(result, base)
    expect(view.in_book).toBe(false)
    expect(view.left_book).toBe(false)
  })

  it('survives a null gap_pp, which MultiPV=1 produces', () => {
    // A row that dereferences this unconditionally throws on a one-line search.
    expect(fromAnalysis({ ...result, gap_pp: null }, base).gap_pp).toBeNull()
    expect(fromAnalysis({ ...result, gap_pp: null }, base).best_pv).toEqual(['d4', 'd5'])
  })

  it('survives a mate score', () => {
    const view = fromAnalysis({ ...result, eval_after: 100000, loss_pp: 0 }, base)
    expect(view.eval_after).toBe(100000)
  })

  it('takes the SAN from the result when the caller has none', () => {
    expect(fromAnalysis(result, { ...base, san: null }).san).toBe('Nf6')
  })

  it('marks a move pending until the engine answers', () => {
    const pending = pendingAnalysis({
      uci: 'g1f3',
      san: 'Nf3',
      moveNumber: 2,
      color: 'white',
      ply: 1,
    })
    expect(pending.pending).toBe(true)
    // Not verified: nothing has been searched yet, and the panel uses this to decide
    // whether to name a depth.
    expect(pending.verified).toBe(false)
  })

  it('distinguishes "not scored" from "still scoring"', () => {
    // They are different states and conflating them makes a standalone report claim
    // to be searching a move forever, and show its placeholder label as a verdict.
    const pending = pendingAnalysis({
      uci: 'g1f3',
      san: 'Nf3',
      moveNumber: 2,
      color: 'white',
      ply: 1,
    })
    expect(pending.unscored ?? false).toBe(false)
    expect(commentary(pending).join(' ')).toContain('Asking the engine')

    const unscored = { ...pending, pending: false, unscored: true }
    const lines = commentary(unscored).join(' ')
    expect(lines).toContain('not scored')
    // And it must not claim the engine endorsed the move.
    expect(lines).not.toContain('nothing better')
  })

  it('gives each position its own key', () => {
    // Keyed by ply *and* uci: two forks from the same base can share a ply.
    const a = fromAnalysis(result, base)
    const b = fromAnalysis(result, { ...base, uci: 'd2d4', san: 'd4' })
    expect(a.key).not.toBe(b.key)
  })
})

/* ------------------------------------------------------- ply arithmetic */

describe('ply arithmetic', () => {
  it('numbers plies the way the move list does', () => {
    expect(moveNumberOf(0)).toBe(1)
    expect(moveNumberOf(1)).toBe(1)
    expect(moveNumberOf(2)).toBe(2)
    expect(moveNumberOf(31)).toBe(16)
  })
})