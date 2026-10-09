/**
 * The engine's assessment of a move, written as prose.
 *
 * `report.py` scattered these facts across several small rows; the plan calls for
 * a single narrative above the move list. The sentences are generated from
 * the data rather than stored, so they stay correct when a threshold moves.
 *
 * Takes a `MoveView`, so a move recorded by the batch analysis and one played on the
 * board are described by the same code and cannot drift into saying different things
 * about the same judgement.
 *
 * Kept separate from the component so it can be asserted on its own — the same
 * move must always produce the same words, and a verified brilliancy must read
 * differently from an unverified blunder.
 */

import type { MoveView } from './moveView'
import { fmtEval, fmtPp } from './format'
import { labelMeta } from './labels'

/** "13...Ba6" — move number with the ellipsis when it is Black's move. */
export function moveLabel(m: MoveView): string {
  return `${m.move_number}${m.color === 'black' ? '...' : '.'} ${m.san}`
}

/** One sentence: what the move was worth. */
export function verdictLine(m: MoveView): string {
  if (!m.is_players_turn) {
    return `${moveLabel(m)} — your opponent.`
  }
  const meta = labelMeta(m.label)
  const bits: string[] = [`${meta.title}${m.glyph ? ' ' + m.glyph : ''}`]
  bits.push(`(${fmtEval(m.eval_before)} → ${fmtEval(m.eval_after)})`)
  if (m.loss_pp >= 0.5) {
    bits.push(`costing ${fmtPp(m.loss_pp)} points of winning chances`)
  }
  return bits.join(' ')
}

/** What the engine wanted instead, and by how much. */
export function engineLine(m: MoveView): string | null {
  if (!m.best_san) return null
  if (m.best_san === m.san) {
    return `The engine played ${m.san} too — there was nothing better.`
  }
  const gap = m.gap_pp
  if (gap !== null && gap !== undefined && gap >= 10) {
    return `The engine wanted ${m.best_san}, which beat your move by ${fmtPp(gap, 0)} points — it was the only good choice.`
  }
  if (gap !== null && gap !== undefined) {
    return `The engine preferred ${m.best_san}, worth ${fmtPp(gap)} points more, but alternatives existed.`
  }
  return `The engine preferred ${m.best_san}.`
}

/** The full commentary block for one move. */
export function commentary(m: MoveView): string[] {
  const out: string[] = []

  if (m.unscored) {
    // No engine was asked, so there is no verdict and none is coming. Saying the
    // engine "played it too" here would be inventing an assessment.
    return ['No engine available, so this move is not scored.']
  }

  if (m.pending) {
    // Nothing has been searched yet. Saying anything about the move would be
    // inventing a verdict, so the only honest line is that one is on the way.
    return ['Asking the engine…']
  }

  if (!m.is_players_turn) {
    out.push(`Your opponent played ${moveLabel(m)}.`)
    return out
  }

  const engine = engineLine(m)
  if (engine) out.push(engine)

  if (m.best_pv?.length) {
    out.push(`Engine line: ${m.best_pv.join(' ')}`)
  }

  if (m.sacrifice && m.sacrifice >= 1) {
    out.push(
      `You gave up ${m.sacrifice} points of material and the engine still rates ` +
        `the position as no worse than the alternatives.`,
    )
  }

  if (m.in_book) {
    out.push('Still in book theory, so this is not scored against you.')
  }
  if (m.left_book) {
    out.push('You left book theory here — the rest of the game is on you.')
  }

  if (m.verified) {
    out.push(`Verified at depth ${m.depth}.`)
  }

  if (m.lc0_best_san) {
    out.push(
      m.lc0_agrees
        ? `Lc0 also rated ${m.san} as best where Stockfish preferred ${m.best_san ?? 'another move'} — a neural engine endorsing a move a classical one rejected.`
        : `Lc0's preference was ${m.lc0_best_san}, also not ${m.san}.`,
    )
  }

  for (const note of m.notes ?? []) out.push(note)

  return out
}

/** One-line summary for lists and tooltips. */
export function shortSummary(m: MoveView): string {
  if (!m.is_players_turn) return moveLabel(m)
  const meta = labelMeta(m.label)
  return `${moveLabel(m)} ${meta.title}${m.glyph ? ' ' + m.glyph : ''}`
}