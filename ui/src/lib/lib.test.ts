/**
 * Checks on the pure logic the views depend on.
 *
 * These are the checks the plan calls for: the commentary generator, the eval
 * formatting including the mate sentinel, the label map, and the router switch.
 * They live next to the code they describe, for the reason the repo's Python
 * self-tests do — a check that describes a contract should be in the same place
 * as the contract, so it cannot drift away from it.
 */

import { describe, expect, it } from 'vitest'
import { bookExit, bookExitMove } from './book'
import { commentary, engineLine, moveLabel, shortSummary, verdictLine } from './commentary'
import { fmtDate, fmtDuration, fmtEval, monogram, pct, winPercent } from './format'
import {
  COUNTED_LABELS,
  LABEL_CLASS,
  LABEL_ORDER,
  LABEL_TEXT_CLASS,
  labelMeta,
  WEAK_LABELS,
} from './labels'
import { ROUTES, BASENAME } from '../router'
import type { Move } from '../api/types'
import { fromRecorded } from './moveView'
import type { MoveView } from './moveView'

/**
 * A recorded move, already projected onto the shape the views read.
 *
 * `commentary` takes a `MoveView` rather than a raw `Move` so a recorded move and
 * one played on the board go through the same generator, so the fixtures go through
 * the same projection rather than the tests exercising a second shape.
 */
function move(overrides: Partial<Move> = {}): MoveView {
  return fromRecorded({
    ply: 0,
    move_number: 12,
    color: 'white',
    san: 'Ba6',
    uci: 'b7a6',
    fen: '',
    fen_after: '',
    is_players_turn: true,
    phase: 'middlegame',
    eval_before: -5,
    eval_after: -743,
    win_percent_before: 49.5,
    win_percent_after: 6.1,
    loss_pp: 43.45,
    accuracy: 12.39,
    label: 'blunder',
    glyph: '??',
    best_san: 'O-O',
    best_uci: 'e8g8',
    best_pv: ['O-O', 'cxd5', 'exd5'],
    best_eval: -5,
    second_san: 'dxc4',
    second_uci: 'd5c4',
    second_eval: -7,
    gap_pp: 0.18,
    in_book: false,
    left_book: false,
    legal: [],
    sacrifice: null,
    depth: 24,
    verified: true,
    survey_label: 'blunder',
    lc0_best_uci: null,
    lc0_best_san: null,
    lc0_eval: null,
    lc0_agrees: null,
    lc0_loss_pp: null,
    notes: [],
    ...overrides,
  })
}

/* ------------------------------------------------------------------ format */

describe('fmtEval', () => {
  it('formats centipawns as pawns', () => {
    expect(fmtEval(30)).toBe('+0.30')
    expect(fmtEval(-120)).toBe('-1.20')
    expect(fmtEval(0)).toBe('+0.00')
  })

  it('renders a mate score as a distance, not a pawn value', () => {
    // Two conventions are in play, and both have to render as mate rather than
    // as a huge pawn value:
    //   eval_before / eval_after use engines.Line.score_cp, which is 100000
    //   per move; eval_curve uses analyze.MATE_CP, a flat 10000 sentinel.
    expect(fmtEval(100000)).toBe('#1')
    expect(fmtEval(-100000)).toBe('-#1')
    expect(fmtEval(500000)).toBe('#5')
    expect(fmtEval(-500000)).toBe('-#5')
    // The curve sentinel has no distance attached, so it renders as bare "#".
    expect(fmtEval(10000)).toBe('#')
    expect(fmtEval(-10000)).toBe('-#')
  })

  it('does not treat a merely good position as a mate', () => {
    // 89 pawns is an enormous advantage but not mate; it must stay a number.
    expect(fmtEval(8900)).toBe('+89.00')
  })

  it('handles null', () => {
    expect(fmtEval(null)).toBe('—')
    expect(fmtEval(undefined)).toBe('—')
  })
})

describe('winPercent', () => {
  it('is 50 at equal', () => {
    expect(winPercent(0)).toBeCloseTo(50, 5)
  })

  it('clamps mate scores to the extremes', () => {
    expect(winPercent(10000)).toBe(100)
    expect(winPercent(-10000)).toBe(0)
  })

  it('matches the sigmoid the analysis uses', () => {
    // Same formula as engines.win_percent, so a bar and a data.json number
    // cannot disagree.
    const expected = 100 / (1 + Math.exp(-0.00368208 * 743))
    expect(winPercent(743)).toBeCloseTo(expected, 6)
  })
})

describe('fmtDate', () => {
  it('reads the PGN dotted format', () => {
    expect(fmtDate('2021.03.31')).toBe('31 Mar 2021')
  })

  it('reads ISO', () => {
    expect(fmtDate('2021-03-31')).toBe('31 Mar 2021')
  })

  it('falls back to the input when it cannot parse', () => {
    expect(fmtDate('????')).toBe('????')
    expect(fmtDate('')).toBe('—')
  })
})

describe('fmtDuration', () => {
  it('formats minutes and hours', () => {
    expect(fmtDuration(59)).toBe('0:59')
    expect(fmtDuration(90)).toBe('1:30')
    expect(fmtDuration(3671)).toBe('1:01:11')
  })
})

describe('monogram', () => {
  it('uses initials', () => {
    expect(monogram('Carlsen, Magnus')).toBe('CM')
    expect(monogram('morpheus')).toBe('MO')
    expect(monogram('')).toBe('?')
  })
})

describe('pct', () => {
  it('clamps to 0..100', () => {
    expect(pct(-5)).toBe(0)
    expect(pct(150)).toBe(100)
    expect(pct(null)).toBe(0)
  })
})

/* ------------------------------------------------------------------ labels */

describe('labelMeta', () => {
  it('has a glyph and a description for every label', () => {
    for (const label of LABEL_ORDER) {
      const meta = labelMeta(label)
      expect(meta.title).not.toBe('')
      expect(meta.description.length).toBeGreaterThan(10)
    }
  })

  it('falls back rather than throwing on an unknown label', () => {
    expect(labelMeta('nonsense').title).toBe('nonsense')
    expect(labelMeta(null).label).toBe('best')
  })

  it('pairs the glyph with the label, so colour is never the only channel', () => {
    expect(labelMeta('blunder').glyph).toBe('??')
    expect(labelMeta('mistake').glyph).toBe('?')
    expect(labelMeta('inaccuracy').glyph).toBe('?!')
    expect(labelMeta('brilliant').glyph).toBe('!!')
  })

  it('classifies the weak labels for drilling', () => {
    expect(WEAK_LABELS).toContain('blunder')
    expect(WEAK_LABELS).toContain('mistake')
    expect(WEAK_LABELS).not.toContain('best')
  })
})

/* --------------------------------------------------------------- commentary */

describe('commentary', () => {
  it('is deterministic: the same move gives the same words', () => {
    expect(commentary(move())).toEqual(commentary(move()))
  })

  it('says what the engine wanted and by how much', () => {
    const line = engineLine(move()) ?? ''
    expect(line).toContain('O-O')
    // gap_pp is 0.18 here, so "alternatives existed", not "the only good move".
    expect(line).toContain('alternatives existed')
  })

  it('says "the only good move" when the gap is 10 points or more', () => {
    const line = engineLine(move({ gap_pp: 14 })) ?? ''
    expect(line).toContain('only good choice')
  })

  it('says the engine agreed when the best move is the one played', () => {
    const line = engineLine(move({ san: 'O-O', best_san: 'O-O' })) ?? ''
    expect(line).toContain('nothing better')
  })

  it('mentions the engine line', () => {
    expect(commentary(move()).join(' ')).toContain('O-O cxd5 exd5')
  })

  it('mentions a verified depth', () => {
    expect(commentary(move()).join(' ')).toContain('depth 24')
  })

  it('does not claim verification when there was none', () => {
    expect(commentary(move({ verified: false })).join(' ')).not.toContain('Verified')
  })

  it('describes a verified brilliancy differently from an unverified blunder', () => {
    const brilliant = commentary(
      move({ label: 'brilliant', glyph: '!!', loss_pp: 1.2, sacrifice: 3.3 }),
    ).join(' ')
    const blunder = commentary(move({ verified: false })).join(' ')
    expect(brilliant).toContain('material')
    expect(brilliant).not.toBe(blunder)
  })

  it('reports an Lc0 endorsement as its own point', () => {
    // When Lc0 agrees, its choice *is* the move played, so the sentence names
    // the move rather than restating the alternative.
    const lines = commentary(move({ lc0_best_san: 'Ba6', lc0_agrees: true })).join(' ')
    expect(lines).toContain('Lc0')
    expect(lines).toContain('Ba6')
    expect(lines).toContain('O-O')
  })

  it('names Lc0’s alternative when the two engines disagree', () => {
    const lines = commentary(move({ lc0_best_san: 'dxc4', lc0_agrees: false })).join(' ')
    expect(lines).toContain('dxc4')
  })

  it('marks book moves as unscored', () => {
    expect(commentary(move({ in_book: true })).join(' ')).toContain('book theory')
  })

  it('does not judge the opponent', () => {
    const lines = commentary(move({ is_players_turn: false }))
    expect(lines.join(' ')).toContain('opponent')
    // No classification line for a move that is not the player's.
    expect(lines).toHaveLength(1)
  })

  it('labels a black move with the ellipsis', () => {
    expect(moveLabel(move({ color: 'black' }))).toBe('12... Ba6')
    expect(moveLabel(move({ color: 'white' }))).toBe('12. Ba6')
  })

  it('summarises for a list row', () => {
    expect(shortSummary(move())).toBe('12. Ba6 Blunder ??')
  })

  it('reports the verdict with the evaluation swing', () => {
    const line = verdictLine(move())
    expect(line).toContain('Blunder')
    expect(line).toContain('??')
    expect(line).toContain('43.5')
  })

  it('omits the loss when there was none', () => {
    const line = verdictLine(move({ loss_pp: 0.1 }))
    expect(line).not.toContain('costing')
  })
})

/* ------------------------------------------------------------------ routes */

/* ------------------------------------------------------------------- book */

describe('bookExitMove', () => {
  /** The move number a ply falls in. Shared by the two invariants below. */
  const moveNoOf = (ply: number) => Math.floor(ply / 2) + 1
  /*
   * The off-by-one this exists for. `book_end_ply` is the ply of the move that
   * LEFT the book, so `ceil(ply / 2)` reports the last book move instead -- and
   * then labels it "the book ended at move N" while move N was itself book.
   *
   * Game 2 is the worked example: in book through 1.d4 d5 2.Nc3 e6 (plies 0-3),
   * leaving on 3.g3 at ply 4. It used to be reported as leaving on move 2.
   */
  it('reports the move that left, not the last one inside', () => {
    expect(bookExitMove(4)).toBe(3) // the real case: 3.g3
  })

  it('converts plies to move numbers with floor(ply/2)+1', () => {
    // ply 0 is White's first move -> move 1
    expect(bookExitMove(1)).toBe(1)
    expect(bookExitMove(2)).toBe(2)
    expect(bookExitMove(3)).toBe(2)
    expect(bookExitMove(5)).toBe(3)
    expect(bookExitMove(6)).toBe(4)
    expect(bookExitMove(33)).toBe(17)
  })

  it('never names a move earlier than the last book ply', () => {
    // Compared as move numbers, because that is what the sentence says. Equality
    // is legitimate and not an off-by-one: book theory can end on Black's reply
    // *within* the numbered move, so "left theory on 2...c5" shares its number with
    // the 2.Bb5 that was still book. Only going *backwards* would be wrong.
    for (let ply = 1; ply <= 60; ply += 1) {
      expect(bookExitMove(ply)).toBeGreaterThanOrEqual(moveNoOf(ply - 1))
    }
  })

  it('names the half-move the leaving ply actually is', () => {
    // Asserted because the displayed string carries both a move number and a SAN,
    // and the two must not disagree about which half of the move was played.
    for (let ply = 1; ply <= 20; ply += 1) {
      expect(bookExitMove(ply)).toBe(moveNoOf(ply))
    }
  })

  it('has no exit move when the book was never available', () => {
    // 0 is the "no left_book record" sentinel, so there is nothing to report.
    expect(bookExitMove(0)).toBeNull()
    expect(bookExitMove(-1)).toBeNull()
  })

  it('includes the SAN, because a bare move number is what confused this', () => {
    expect(bookExit(4, 'g3')).toBe('left theory on 3. g3')
    expect(bookExit(4, null)).toBe('left theory on 3')
    expect(bookExit(0, 'e4')).toBeNull()
  })
})

/* --------------------------------------------------------------- labels */

describe('COUNTED_LABELS', () => {
  it('gives every label its own column, so no cell holds two numbers', () => {
    // The bug this guards against: three headers, each covering two labels, so
    // `!! 0` rendered as "0 0" and the header claimed to mean brilliant+great.
    // One column per label is the only arrangement where a cell is a number.
    expect(COUNTED_LABELS).toHaveLength(6)
    expect(new Set(COUNTED_LABELS).size).toBe(COUNTED_LABELS.length)
  })

  it('carries a glyph for every column, so colour is never the only channel', () => {
    const glyphs = COUNTED_LABELS.map((label) => labelMeta(label).glyph)
    for (const glyph of glyphs) expect(glyph).not.toBe('')
    // `miss` used to share `!` with `great`, which put the same glyph on two
    // different columns.
    expect(new Set(glyphs).size).toBe(glyphs.length)
  })

  it('counts the labels worth acting on, and skips the rest', () => {
    // book/best/excellent/good dominate every phase and are already implied by
    // the accuracy figure beside them, so they get no column.
    for (const skipped of ['book', 'best', 'excellent', 'good'] as const) {
      expect(COUNTED_LABELS).not.toContain(skipped)
    }
    // Every weak label is worth a column: the point of the table is finding them.
    for (const weak of WEAK_LABELS) {
      expect(COUNTED_LABELS).toContain(weak)
    }
    // And the two good-but-remarkable ones.
    expect(COUNTED_LABELS).toContain('brilliant')
    expect(COUNTED_LABELS).toContain('great')
  })

  it('keeps LABEL_ORDER, so the columns read in the documented order', () => {
    const positions = COUNTED_LABELS.map((label) => LABEL_ORDER.indexOf(label))
    expect(positions).toEqual([...positions].sort((a, b) => a - b))
  })

  it('sums across games rather than reading one game', () => {
    // What build_dashboard() produces for two games in the same phase, which is
    // the shape the table reads. Asserted here because the sum is what the
    // single-number cell now has to carry.
    const counts: Record<string, number> = {
      brilliant: 1, great: 2, inaccuracy: 1, mistake: 0, blunder: 3, miss: 0,
    }
    const second: Record<string, number> = {
      brilliant: 0, great: 1, inaccuracy: 2, mistake: 1, blunder: 0, miss: 1,
    }
    const total = Object.fromEntries(
      COUNTED_LABELS.map((label) => [label, (counts[label] ?? 0) + (second[label] ?? 0)]),
    )
    expect(total).toEqual({
      brilliant: 1, great: 3, inaccuracy: 3, mistake: 1, blunder: 3, miss: 1,
    })
  })
})

describe('LABEL_TEXT_CLASS', () => {
  it('covers every label, so a count cell always has a colour', () => {
    for (const label of LABEL_ORDER) {
      expect(LABEL_TEXT_CLASS[label]).toBeTruthy()
    }
  })

  it('is distinct from LABEL_CLASS, which carries badge backgrounds', () => {
    // Reusing the badge classes in a table would put a chip behind every number.
    for (const label of LABEL_ORDER) {
      expect(LABEL_TEXT_CLASS[label]).not.toBe(LABEL_CLASS[label])
    }
  })
})

/* ------------------------------------------------------------------ routes */

describe('router', () => {
  it('builds the paths the plan asks for', () => {
    expect(ROUTES.game(3)).toBe('/games/3')
    expect(ROUTES.play(3)).toBe('/games/3/play')
    expect(ROUTES.drill(3)).toBe('/games/3/drill')
    expect(ROUTES.overview).toBe('/')
  })

  it('serves from the /report.html/ prefix, matching the plan URL', () => {
    expect(BASENAME).toBe('/report.html/')
    expect(`${BASENAME.replace(/\/$/, '')}${ROUTES.game(3)}`).toBe('/report.html/games/3')
  })
})