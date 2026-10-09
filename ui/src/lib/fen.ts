/**
 * FEN constants and helpers the boards share.
 *
 * `START_FEN` lives here rather than in one page because two pages needed it
 * and had drifted: `GameAnalysis` fell back to an *empty* board
 * (`8/8/8/8/8/8/8/8`), which is reachable whenever the URL names a ply past the
 * end of the game. An empty board reads as "the data is broken"; the start
 * position reads as "you are at the beginning".
 */

/** The standard opening position, as python-chess and chess.js both spell it. */
export const START_FEN = 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1'

/**
 * Whose turn it is in a FEN, as chessground spells it.
 *
 * Read from the FEN rather than tracked separately, because chessground does not
 * read it from the FEN itself and passing the wrong one makes Black's pieces
 * highlight their legal squares and then ignore every click on them.
 */
export function turnOf(fen: string): 'white' | 'black' {
  return fen.split(' ')[1] === 'b' ? 'black' : 'white'
}