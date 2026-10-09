/**
 * The move list, with the eval and loss for each half-move.
 *
 * One row per ply, matching the reference layout's `N. white black` pairing with
 * two thin bars on the right. Those bars are the eval bar and the loss readout —
 * not a clock, because per-move think time is not in `data.json` (see the plan's
 * §6.4: showing a fabricated clock would be worse than showing none).
 *
 * Opponent plies are dimmed, because only your moves carry a classification.
 *
 * A variation is inserted after the recorded row it forks from, as a single
 * indented continuation line rather than a second list — see plans/Anexes/ANEX2.png.
 * The recorded game is never displaced by it: that is the whole reason a subline and
 * not a replacement.
 */

import { useEffect, useRef } from 'react'
import type { MoveView } from '../../lib/moveView'
import { groupRun } from '../../lib/variation'
import type { ForkMove, Variation } from '../../lib/variation'
import { fmtEval, fmtPp, winPercent } from '../../lib/format'
import { LABEL_CLASS, labelMeta } from '../../lib/labels'
import { EvalBar } from '../board/EvalBar'
import styles from './MoveList.module.css'

export interface MoveListProps {
  moves: MoveView[]
  /** The recorded ply the cursor is on. Ignored while the cursor is in a variation. */
  selected: number
  /** Index of the selected variation move, or null when the cursor is on the game. */
  selectedFork: number | null
  /** The alternative continuation, if one has been played. */
  variation: Variation | null
  onSelect: (ply: number) => void
  onSelectFork: (index: number) => void
}

export function MoveList({
  moves,
  selected,
  selectedFork,
  variation,
  onSelect,
  onSelectFork,
}: MoveListProps) {
  const containerRef = useRef<HTMLDivElement>(null)

  // Keep the selected row visible without yanking the page when it is already
  // on screen — 'nearest' is what makes arrow-key navigation usable.
  useEffect(() => {
    const root = containerRef.current
    if (!root) return
    const row =
      root.querySelector<HTMLElement>('[data-selected="true"]') ??
      // The variation is a separate row, so fall back to it when the cursor left
      // the recorded line.
      root.querySelector<HTMLElement>('[data-fork-selected="true"]')
    row?.scrollIntoView({ block: 'nearest' })
  }, [selected, selectedFork])

  if (!moves.length) {
    return <div className={styles.empty}>No moves recorded.</div>
  }

  return (
    <div className={styles.list} ref={containerRef} role="listbox" aria-label="Moves">
      {moves.map((move, index) => {
        const meta = labelMeta(move.label)
        const isSelected = index === selected && selectedFork === null
        const mine = move.is_players_turn
        // The eval is stored from the mover's point of view, so flip it for the
        // bar to read White-vs-Black consistently across both rows.
        const whitePercent = winPercent(move.eval_after ?? null)
        const lossTone =
          move.loss_pp > 25 ? 'loss' : move.loss_pp > 10 ? 'bad' : move.loss_pp > 5 ? 'warn' : ''

        const row = (
          <button
            key={move.key}
            type="button"
            role="option"
            aria-selected={isSelected}
            data-selected={isSelected}
            data-ply={index}
            className={`${styles.row} ${isSelected ? styles.selected : ''} ${
              mine ? '' : styles.opponent
            } ${mine ? LABEL_CLASS[meta.label as never] : ''}`}
            onClick={() => onSelect(index)}
            title={mine ? `${meta.title}: ${meta.description}` : 'Opponent move'}
          >
            <span className={styles.number}>
              {move.move_number}
              {move.color === 'black' ? '…' : '.'}
            </span>
            <span className={styles.san}>{move.san}</span>
            {mine && move.glyph ? (
              <span className={styles.glyph}>{move.glyph}</span>
            ) : null}
            <span className={styles.spacer} />
            <span className={styles.eval} title={`eval ${fmtEval(move.eval_before)}`}>
              {fmtEval(move.eval_after)}
            </span>
            <span className={styles.bar} aria-hidden>
              <EvalBar whitePercent={whitePercent} height={5} />
            </span>
            {mine ? (
              <span className={`${styles.loss} ${lossTone ? styles[lossTone] : ''}`}>
                {move.loss_pp >= 0.5 ? fmtPp(move.loss_pp) : ''}
              </span>
            ) : (
              <span className={styles.loss} />
            )}
          </button>
        )

        /*
         * The variation hangs off the last ply it shares with the game, so it is
         * rendered immediately after that row and nowhere else. `basePly` is the
         * recorded ply whose `fen_after` the fork starts from.
         */
        const forksHere =
          variation !== null && variation.moves.length > 0 && variation.basePly === index

        return (
          <div key={move.key} className={styles.slot}>
            {row}
            {forksHere ? (
              <VariationRow
                moves={variation.moves}
                selected={selectedFork}
                onSelect={onSelectFork}
              />
            ) : null}
          </div>
        )
      })}
      {/* Spacer so the last row can scroll clear of the transport. */}
      <div className={styles.tail} />
    </div>
  )
}

/**
 * One continuation line, the way a score book sets one.
 *
 * `role="group"` rather than another `role="option"`: the container is a listbox,
 * and a group that contains options is the one legal nesting, which keeps what a
 * screen reader announces sane.
 */
function VariationRow({
  moves,
  selected,
  onSelect,
}: {
  moves: ForkMove[]
  selected: number | null
  onSelect: (index: number) => void
}) {
  const last = moves[moves.length - 1]
  return (
    <div className={styles.variation} role="group" aria-label="Variation">
      {groupRun(moves).map((row) => (
        <span key={`${row.number}-${row.white?.key ?? row.black?.key ?? 'x'}`} className={styles.variationRun}>
          <span className={styles.variationNumber}>
            {row.number}
            {row.black && !row.white ? '…' : '.'}
          </span>
          {(['white', 'black'] as const).map((slot) => {
            const move = row[slot]
            if (!move) return null
            const isSelected = selected === moves.indexOf(move)
            return (
              <button
                key={move.key}
                type="button"
                role="option"
                aria-selected={isSelected}
                data-fork-selected={isSelected}
                className={`${styles.variationMove} ${isSelected ? styles.variationSelected : ''} ${
                  move.pending ? styles.variationPending : ''
                }`}
                onClick={() => onSelect(moves.indexOf(move))}
                title={move.pending ? 'being analysed' : moveLabelOf(move)}
              >
                {move.san}
                {move.pending ? <span className={styles.variationSpin} /> : null}
              </button>
            )
          })}
        </span>
      ))}
      <span className={styles.spacer} />
      <span className={styles.bar} aria-hidden>
        <EvalBar whitePercent={winPercent(last?.eval_after ?? null)} height={5} />
      </span>
    </div>
  )
}

function moveLabelOf(m: MoveView): string {
  return `${m.move_number}${m.color === 'black' ? '...' : '.'} ${m.san}`
}

/** Group plies into `1. e4 e5` pairs, for a compact alternate view. */
export function groupMoves(moves: MoveView[]): Array<{ number: number; white?: MoveView; black?: MoveView }> {
  const rows: Array<{ number: number; white?: MoveView; black?: MoveView }> = []
  for (const move of moves) {
    let row = rows.find((r) => r.number === move.move_number)
    if (!row) {
      row = { number: move.move_number }
      rows.push(row)
    }
    if (move.color === 'white') row.white = move
    else row.black = move
  }
  return rows
}

export function MovePairs({
  moves,
  selected,
  selectedFork,
  variation,
  onSelect,
  onSelectFork,
}: MoveListProps) {
  const rows = groupMoves(moves)
  return (
    <div className={styles.pairs}>
      {rows.map((row) => {
        const whiteIdx = row.white ? moves.indexOf(row.white) : -1
        const blackIdx = row.black ? moves.indexOf(row.black) : -1
        const forksHere =
          variation !== null && variation.moves.length > 0 && variation.basePly === row.number - 1
        return (
          <div key={row.number} className={styles.pair}>
            <span className={styles.number}>{row.number}.</span>
            {[row.white, row.black].map((move, i) => {
              if (!move) return <span key={i} className={styles.half} />
              const index = i === 0 ? whiteIdx : blackIdx
              const meta = labelMeta(move.label)
              return (
                <button
                  key={i}
                  type="button"
                  className={`${styles.half} ${index === selected && selectedFork === null ? styles.selected : ''} ${
                    move.is_players_turn ? LABEL_CLASS[meta.label as never] : styles.opponent
                  }`}
                  onClick={() => onSelect(index)}
                  title={move.is_players_turn ? meta.title : 'Opponent move'}
                >
                  {move.san}
                  {move.is_players_turn && move.glyph ? (
                    <span className={styles.glyph}> {move.glyph}</span>
                  ) : null}
                </button>
              )
            })}
            <span className={styles.spacer} />
            {row.white ? (
              <span className={styles.bar} aria-hidden>
                <EvalBar whitePercent={winPercent(row.white.eval_after ?? null)} height={5} />
              </span>
            ) : null}
            {forksHere ? (
              <div className={styles.variationInline} role="group" aria-label="Variation">
                {variation?.moves.map((move, index) => (
                  <button
                    key={move.key}
                    type="button"
                    role="option"
                    aria-selected={selectedFork === index}
                    className={`${styles.variationMove} ${selectedFork === index ? styles.variationSelected : ''}`}
                    onClick={() => onSelectFork(index)}
                    title={moveLabelOf(move)}
                  >
                    {move.move_number}
                    {move.color === 'black' ? '…' : '.'} {move.san}
                  </button>
                ))}
              </div>
            ) : null}
          </div>
        )
      })}
    </div>
  )
}