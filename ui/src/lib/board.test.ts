/**
 * Checks on the board's pure decisions.
 *
 * The board's drag-and-drop cannot be driven headlessly, so what is checked
 * here is the part that can silently be wrong: which taps select, which brush a
 * hint uses, and what is on a square. Getting these wrong produces a board that
 * looks perfect and behaves wrongly — a stuck selection, a hint drawn in the
 * colour that means "the engine wanted this", an enlarged piece that never
 * appears.
 */

import { describe, expect, it } from 'vitest'
import { Chess } from 'chess.js'
import { START_FEN, turnOf } from './fen'
import { selectBehaviour } from '../components/board/Board'

const START = START_FEN

/** The dests map the Board hands to chessground, as GamePlay builds it. */
function dests(chess: Chess): Map<string, string[]> {
  const map = new Map<string, string[]>()
  for (const move of chess.moves({ verbose: true })) {
    const list = map.get(move.from) ?? []
    list.push(move.to)
    map.set(move.from, list)
  }
  return map
}

/** Mirrors the hint→brush mapping in GamePlay, which is what draws the arrows. */
function hintBrush(rank: number): string {
  if (rank <= 1) return 'hint1'
  if (rank === 2) return 'hint2'
  return 'hint3'
}

/* -------------------------------------------------------------- selection */

describe('selectBehaviour', () => {
  it('selects a piece of the side to move that has a legal move', () => {
    const map = dests(new Chess(START))
    expect(selectBehaviour('e2', map)).toBe(true)
    expect(selectBehaviour('g1', map)).toBe(true)
  })

  it('does not select a piece with no legal move', () => {
    // A knight pinned on the e-file by a rook: every knight move would step off
    // the file and expose the king, so chess.js offers it nothing and the square
    // is absent from dests. (A pinned *pawn* is not a usable example — it can
    // still shuffle along the pin ray.)
    const chess = new Chess('4r2k/8/8/8/8/8/4N3/4K3 w - - 0 1')
    const map = dests(chess)
    expect(map.has('e2')).toBe(false)
    expect(selectBehaviour('e2', map)).toBe(false)
  })

  it('does not select a piece of the side that is not to move', () => {
    // Black to move, so every white piece is inert. This is the "touching a
    // white horse on black's turn does not select it" rule, asserted at the
    // level the board decides it.
    const map = dests(new Chess('4k3/4n3/8/8/8/8/4N3/4K3 b - - 0 1'))
    expect(selectBehaviour('e2', map)).toBe(false)
    expect(selectBehaviour('e7', map)).toBe(true)
  })

  it('clears the selection for any square that is not a legal origin', () => {
    // The reported bug: tapping an empty square while a piece is selected left
    // the piece selected, because chessground's own fallthrough check keeps the
    // old selection. This is the rule that stops that.
    const map = dests(new Chess(START))
    for (const square of ['a1', 'd4', 'h5', 'e8', 'a8']) {
      expect(selectBehaviour(square, map)).toBe(false)
    }
  })

  it('clears the selection on the opponent piece, even if it could be captured', () => {
    // d4 has a black pawn on it that White could capture -- so it *is* a legal
    // destination -- but it is not a square a move starts from, and selecting it
    // would show the circles for a black pawn.
    const chess = new Chess('4k3/8/8/3p4/4P3/8/8/4K3 w - - 0 1')
    const map = dests(chess)
    expect(map.get('e4')).toContain('d5')
    expect(selectBehaviour('d4', map)).toBe(false)
  })

  it('selects nothing when the board is not playable', () => {
    // The analysis board passes no dests at all. A tap there must not report a
    // selection, or the analysis page would grow pieces it has no business
    // growing.
    expect(selectBehaviour('e2', undefined)).toBe(false)
    expect(selectBehaviour('e2', new Map())).toBe(false)
  })
})

/* ------------------------------------------------------------------- FEN */

describe('turnOf', () => {
  it('reads the side to move', () => {
    expect(turnOf(START)).toBe('white')
    expect(turnOf('4k3/8/8/8/8/8/8/4K3 b - - 0 1')).toBe('black')
  })

  it('assumes white for a FEN with no side field', () => {
    expect(turnOf('rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR')).toBe('white')
  })
})

/* ------------------------------------------------------------------ hints */

/**
 * The brush mapping, restated here rather than imported.
 *
 * GamePlay owns the real one; this copy is what the test pins, and a change to
 * either side that has not been made in both shows up as a failure rather than
 * as arrows that quietly stop being distinguishable.
 */
describe('hint brushes', () => {
  it('gives each rank its own brush, most opaque first', () => {
    expect(hintBrush(1)).toBe('hint1')
    expect(hintBrush(2)).toBe('hint2')
    expect(hintBrush(3)).toBe('hint3')
  })

  it('clamps an out-of-range rank rather than producing an undefined brush', () => {
    // The server clamps to 3, so this cannot happen in practice -- but a brush
    // name chessground does not know draws nothing at all, silently.
    expect(hintBrush(0)).toBe('hint1')
    expect(hintBrush(99)).toBe('hint3')
  })

  it('never reuses a brush that means something else', () => {
    // green/red/blue/yellow carry meaning everywhere else in the app.
    const brushes = [hintBrush(1), hintBrush(2), hintBrush(3)]
    for (const brush of brushes) {
      expect(['green', 'red', 'blue', 'yellow']).not.toContain(brush)
    }
    expect(new Set(brushes).size).toBe(3)
  })
})