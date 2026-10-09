/**
 * The classification and engine commentary panel.
 *
 * This is the one structural departure from the reference image, which puts a
 * position header above the move list: the original plan asks for the move's
 * classification and the engines' commentary to sit *above* the moves.
 *
 * Takes a `MoveView` rather than a `Move`, so a recorded move and one played on the
 * board go through identical code. The prose is generated from the data rather than
 * stored, so it stays correct when a threshold in labels.py moves. See
 * lib/commentary.ts.
 */

import type { MoveView } from '../../lib/moveView'
import { commentary } from '../../lib/commentary'
import { fmtAccuracy, fmtEval, fmtPp } from '../../lib/format'
import { labelMeta } from '../../lib/labels'
import { LabelBadge, Pill } from '../ui'
import styles from './CommentaryPanel.module.css'

export interface CommentaryPanelProps {
  move: MoveView | null
  /** True while the server is searching. */
  busy?: boolean
  /** Extra context, e.g. "this is not your move". */
  note?: React.ReactNode
}

export function CommentaryPanel({ move, busy, note }: CommentaryPanelProps) {
  if (!move) {
    return (
      <div className={styles.panel}>
        <div className={styles.placeholder}>Select a move to see the engine's view of it.</div>
      </div>
    )
  }

  const meta = labelMeta(move.label)
  /*
   * Three states, not two.
   *
   * A move that has a verdict is judged. One still being searched is waiting. One
   * that will never be searched — no engine behind the page — is *unscored*, and its
   * placeholder label must not be shown as a judgement in either case.
   */
  const judged = !move.pending && !move.unscored
  const lines = commentary(move)

  return (
    <div className={styles.panel}>
      <div className={styles.head}>
        <div className={styles.headline}>
          <span className={styles.move}>
            {move.move_number}
            {move.color === 'black' ? '…' : '.'} {move.san}
          </span>
          {move.is_players_turn && judged ? (
            <LabelBadge label={move.label} glyph={move.glyph} size="lg" />
          ) : move.is_players_turn ? (
            <span className={styles.opponentTag}>
              {move.unscored ? 'not scored' : 'analysing'}
            </span>
          ) : (
            <span className={styles.opponentTag}>opponent</span>
          )}
          {/*
            One word, not two. `busy` is a *separate* signal from the move's own
            state: the move can already have a verdict while a later one is being
            scored, and saying "analysing" in the badge and "analysing…" beside it
            reads as a stutter rather than as two different things. So the badge
            describes the move and this describes the search.
          */}
          {busy && judged ? <span className={styles.searching}>scoring…</span> : null}
        </div>
        <div className={styles.metrics}>
          {judged ? (
            <Metric
              label="eval"
              value={`${fmtEval(move.eval_before)} → ${fmtEval(move.eval_after)}`}
            />
          ) : null}
          {move.is_players_turn && judged ? (
            <>
              <Metric label="loss" value={`${fmtPp(move.loss_pp)}pp`} />
              <Metric label="accuracy" value={fmtAccuracy(move.accuracy)} />
            </>
          ) : null}
        </div>
      </div>

      {/*
        Book and phase tags are properties of the *recorded* game, so they are
        suppressed for a move played on the board: `fromAnalysis` sets both false and
        showing an empty pill would imply the question had been answered.
      */}
      {move.in_book || move.left_book ? (
        <div className={styles.tags}>
          {move.in_book ? <Pill tone="good">book</Pill> : null}
          {move.left_book ? <Pill tone="warn">left book theory</Pill> : null}
        </div>
      ) : null}

      {move.sacrifice && move.sacrifice >= 1 && judged ? (
        <div className={styles.tags}>
          <Pill tone="warn">sac {move.sacrifice}</Pill>
        </div>
      ) : null}

      {move.is_players_turn && judged ? (
        <p className={styles.definition}>{meta.description}</p>
      ) : null}

      {/*
        Keyed on the position so the block cross-fades when the selection changes,
        which is what makes stepping through the game feel like a sequence rather
        than a series of jumps.
      */}
      <div className={styles.body} key={`${move.key}-${move.ply}`}>
        {lines.map((line, i) => (
          <p key={i} className={styles.line}>
            {line}
          </p>
        ))}
      </div>

      {note ? <div className={styles.note}>{note}</div> : null}
    </div>
  )
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className={styles.metric}>
      <span className={styles.metricLabel}>{label}</span>
      <span className={styles.metricValue}>{value}</span>
    </div>
  )
}