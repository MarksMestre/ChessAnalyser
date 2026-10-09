/**
 * Where a game left opening theory.
 *
 * `book_end_ply` is the ply of the move that **left** the book — the first record
 * with `left_book` set (analyze.py). So it converts to a move number with
 * `floor(ply / 2) + 1`.
 *
 * The arithmetic this replaces was `Math.ceil(ply / 2)`, which reports the *last*
 * book move instead and then labels it "the book ended at move N" — while move N
 * was itself book theory. Game 2 stayed in book for four plies (1.d4 d5 2.Nc3 e6)
 * and left on 3.g3, and was reported as leaving on move 2.
 */

/** The move number of the move that left book theory, or null if it never did. */
export function bookExitMove(bookEndPly: number): number | null {
  return bookEndPly > 0 ? Math.floor(bookEndPly / 2) + 1 : null
}

/**
 * "the move where you stopped playing theory", ready to display.
 *
 * The SAN is included because a bare move number is what started the confusion, and
 * because the move that leaves theory is usually the move worth looking at: it is
 * the first one judged on its own merits rather than against a book line.
 */
export function bookExit(
  bookEndPly: number,
  san: string | null | undefined,
): string | null {
  const move = bookExitMove(bookEndPly)
  if (move === null) return null
  return `left theory on ${move}${san ? `. ${san}` : ''}`
}