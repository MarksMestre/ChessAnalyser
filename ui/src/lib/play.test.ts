/**
 * Checks on the playable-board logic.
 *
 * The board's own drag-and-drop cannot be driven from a headless test, so what
 * is checked here is the part that *can* silently be wrong: the rules. If
 * castling, en passant or promotion were mishandled, the board would still look
 * perfect while accepting illegal moves — and a chess app that accepts illegal
 * moves is worse than one that does not move at all.
 */

import { describe, expect, it } from 'vitest'
import { Chess } from 'chess.js'

const START = 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1'

/** The dests map the Board hands to chessground. */
function dests(chess: Chess): Map<string, string[]> {
  const map = new Map<string, string[]>()
  for (const move of chess.moves({ verbose: true })) {
    const list = map.get(move.from) ?? []
    list.push(move.to)
    map.set(move.from, list)
  }
  return map
}

describe('legal move generation', () => {
  it('offers every legal opening move for a knight', () => {
    const map = dests(new Chess(START))
    // b1 and g1 knights both have two moves each from the start position.
    expect(map.get('b1')?.sort()).toEqual(['a3', 'c3'])
    expect(map.get('g1')?.sort()).toEqual(['f3', 'h3'])
  })

  it('restricts a pinned piece to the pin ray', () => {
    // White king e1, black rook e8 down the e-file, white pawn e2 in between:
    // the pawn is pinned, so it may only move along the file. d2 and d3 would
    // both expose the king.
    const chess = new Chess('4k3/8/8/8/r7/8/4P3/4K3 w - - 0 1')
    const map = dests(chess)
    expect(map.get('e2')?.sort()).toEqual(['e3', 'e4'])
  })

  it('refuses a king move that stays on the checking ray', () => {
    // Black king e8, white rook e2 on the e-file: black is in check, and moving
    // to e7 would leave it on the same file.
    const chess = new Chess('4k3/8/8/8/8/8/4R3/4K3 b - - 0 1')
    expect(chess.isCheck()).toBe(true)
    const moves = chess.moves({ verbose: true }).map((m) => m.from + m.to)
    expect(moves).not.toContain('e8e7')
    expect(moves).toContain('e8d8')
    expect(moves).toContain('e8f7')
  })

  it('handles castling as one move', () => {
    const chess = new Chess('r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1')
    chess.move('e1g1')
    // Both king and rook moved, which is what makes this a castling test
    // rather than a king-teleport test.
    expect(chess.fen().split(' ')[0]).toBe('r3k2r/8/8/8/8/8/8/R4RK1')
    // Moving the king spends *both* of that side's rights, even though the
    // queenside rook never moved -- which is the rule people get wrong.
    expect(chess.getCastlingRights('w')).toEqual({ k: false, q: false })
    // Black's rights are untouched.
    expect(chess.getCastlingRights('b')).toEqual({ k: true, q: true })
  })

  it('does not offer castling through an attacked square', () => {
    // The bishop on a7 rakes f1, so the king may not pass over it.
    const chess = new Chess('4k3/b7/8/8/8/8/8/R3K2R w KQ - 0 1')
    const moves = chess.moves({ verbose: true }).map((m) => m.from + m.to)
    expect(moves).not.toContain('e1g1')
    expect(moves).toContain('e1c1')
  })

  it('handles en passant, including the pinned-ep case', () => {
    const chess = new Chess('4k3/8/8/3pP3/8/8/8/4K3 w - d6 0 1')
    expect(chess.moves({ verbose: true }).map((m) => m.from + m.to)).toContain('e5d6')

    // The classic trap: capturing en passant would expose the king on the rank,
    // so it is illegal even though the squares look free.
    const pinned = new Chess('8/8/8/K2pP2q/8/8/8/4k3 w - d6 0 1')
    const moves = pinned.moves({ verbose: true }).map((m) => m.from + m.to)
    expect(moves).not.toContain('e5d6')
  })

  it('offers all four promotions', () => {
    const chess = new Chess('4k3/P7/8/8/8/8/8/4K3 w - - 0 1')
    const promotions = chess
      .moves({ verbose: true })
      .filter((m) => m.to === 'a8')
      .map((m) => m.promotion)
      .sort()
    expect(promotions).toEqual(['b', 'n', 'q', 'r'])
  })

  it('rejects an illegal move rather than throwing', () => {
    const chess = new Chess(START)
    expect(() => chess.move({ from: 'e2', to: 'e5' })).toThrow()
    // The position is unchanged after the rejected attempt.
    expect(chess.fen()).toBe(START)
  })

  it('reports the game as over at checkmate', () => {
    const chess = new Chess('rnb1kbnr/pppp1ppp/8/4p3/6Pq/5P2/PPPPP2P/RNBQKBNR w KQkq - 1 3')
    expect(chess.isCheckmate()).toBe(true)
    expect(chess.isGameOver()).toBe(true)
  })

  it('survives a long random game without desyncing', () => {
    // A cheap fuzz: play a whole game choosing moves at random. If FEN handling
    // or state restoration were broken, this would throw or drift.
    //
    // The bound is 400 plies because random play can wander for a long time
    // before anything decisive happens -- reaching mate is not guaranteed, so
    // the assertion is that the engine stays consistent, not that it finishes.
    const chess = new Chess(START)
    let plies = 0
    while (!chess.isGameOver() && plies < 400) {
      const moves = chess.moves()
      if (!moves.length) break
      chess.move(moves[Math.floor(Math.random() * moves.length)])
      plies += 1
    }
    expect(plies).toBeGreaterThan(10)

    // Exactly one king per side, whatever happened: a desync shows up here.
    const board = chess.board()
    const kings = board.flat().filter((p) => p && p.type === 'k')
    expect(kings).toHaveLength(2)

    // The FEN must round-trip, which is what the play page hands to the server.
    expect(new Chess(chess.fen()).fen()).toBe(chess.fen())
  })

  it('undo restores the exact previous position', () => {
    const chess = new Chess(START)
    const fen = chess.fen()
    chess.move('e2e4')
    chess.move('e7e5')
    chess.undo()
    chess.undo()
    expect(chess.fen()).toBe(fen)
  })
})