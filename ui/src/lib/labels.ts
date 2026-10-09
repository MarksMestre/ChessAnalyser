/**
 * The one place a label becomes a colour or a CSS class.
 *
 * The move list, the commentary badge, the eval-chart dots and the game list all
 * read from here, so a badge and a chart dot for the same move cannot disagree
 * about what "blunder" looks like.
 */

import type { Label, Phase } from '../api/types'

interface LabelMeta {
  label: Label
  glyph: string
  title: string
  /** Anything that loses more than this is coloured "bad". */
  tone: 'great' | 'good' | 'neutral' | 'warn' | 'bad'
  description: string
}

const META: Record<Label, LabelMeta> = {
  brilliant: {
    label: 'brilliant',
    glyph: '!!',
    title: 'Brilliant',
    tone: 'great',
    description:
      'A sound sacrifice: real material handed over, and still no worse than the alternatives once the opponent replies with their best defence.',
  },
  great: {
    label: 'great',
    glyph: '!',
    title: 'Great',
    tone: 'great',
    description:
      'The engine’s move, and it beat the next best by at least 10 points — there was literally nothing else.',
  },
  book: {
    label: 'book',
    glyph: '',
    title: 'Book',
    tone: 'neutral',
    description: 'Theory. Engines score book moves differently from how they are taught, so this is not scored against you.',
  },
  best: {
    label: 'best',
    glyph: '',
    title: 'Best',
    tone: 'good',
    description: 'Lost less than 1 point of winning chances.',
  },
  excellent: {
    label: 'excellent',
    glyph: '',
    title: 'Excellent',
    tone: 'good',
    description: 'Lost 1–2 points.',
  },
  good: {
    label: 'good',
    glyph: '',
    title: 'Good',
    tone: 'good',
    description: 'Lost 2–5 points.',
  },
  inaccuracy: {
    label: 'inaccuracy',
    glyph: '?!',
    title: 'Inaccuracy',
    tone: 'warn',
    description: 'Lost 5–10 points. Usually playable, rarely best.',
  },
  mistake: {
    label: 'mistake',
    glyph: '?',
    title: 'Mistake',
    tone: 'warn',
    description: 'Lost 10–25 points. A real error, usually hard to recover from.',
  },
  blunder: {
    label: 'blunder',
    glyph: '??',
    title: 'Blunder',
    tone: 'bad',
    description: 'Lost more than 25 points. The move gave something away outright.',
  },
  miss: {
    label: 'miss',
    // `!?`, not `!`: labels.py GLYPHS says so, and a header row that puts the
    // same glyph on "great" and "missed win" is not distinguishing them.
    glyph: '!?',
    title: 'Missed win',
    tone: 'warn',
    description: 'You were winning and gave it away.',
  },
}

export function labelMeta(label: string | null | undefined): LabelMeta {
  return (
    META[(label ?? 'best') as Label] ?? {
      label: 'best',
      glyph: '',
      title: label ?? 'Unknown',
      tone: 'neutral',
      description: '',
    }
  )
}

/**
 * Colour for bare text, without the badge background.
 *
 * `LABEL_CLASS` is for badges and rows, and its classes carry a background and
 * a border — right for a chip, wrong for a table cell, where a grid of coloured
 * chips outshouts the numbers. These live in base.css as global classes, so any
 * page can use them without importing a module.
 */
export const LABEL_TEXT_CLASS: Record<Label, string> = {
  brilliant: 't-brilliant',
  great: 't-great',
  book: 't-book',
  best: 't-best',
  excellent: 't-excellent',
  good: 't-good',
  inaccuracy: 't-inaccuracy',
  mistake: 't-mistake',
  blunder: 't-blunder',
  miss: 't-miss',
}

export const LABEL_CLASS: Record<Label, string> = {
  brilliant: 'lbl-brilliant',
  great: 'lbl-great',
  book: 'lbl-book',
  best: 'lbl-best',
  excellent: 'lbl-excellent',
  good: 'lbl-good',
  inaccuracy: 'lbl-inaccuracy',
  mistake: 'lbl-mistake',
  blunder: 'lbl-blunder',
  miss: 'lbl-miss',
}

/** The order used for the legend and the game-index filters. */
export const LABEL_ORDER: Label[] = [
  'brilliant',
  'great',
  'book',
  'best',
  'excellent',
  'good',
  'inaccuracy',
  'mistake',
  'blunder',
  'miss',
]

export const PHASE_CLASS: Record<Phase, string> = {
  opening: 'ph-opening',
  middlegame: 'ph-middlegame',
  endgame: 'ph-endgame',
}

/** Labels that count as an error worth drilling. */
export const WEAK_LABELS: Label[] = ['inaccuracy', 'mistake', 'blunder', 'miss']

/**
 * The labels a count column is worth showing.
 *
 * `book`/`best`/`excellent`/`good` are excluded: they dominate every phase and
 * are already implied by the accuracy figure beside them. What is left is the
 * part of the game worth working on, one column per label.
 *
 * Used by every table that counts labels, so the phase table, the per-game
 * phase table and the all-games table cannot drift apart again.
 */
export const COUNTED_LABELS: Label[] = [
  'brilliant',
  'great',
  'inaccuracy',
  'mistake',
  'blunder',
  'miss',
]