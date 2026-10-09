/**
 * A horizontal win-probability bar for the current position.
 *
 * The move list carries a thin version of this per half-move; the wide one sits
 * under the board. Both read the same win percentage, so a bar that says 88%
 * and a number that says 88% cannot disagree.
 */

import styles from './EvalBar.module.css'

export interface EvalBarProps {
  /** Win probability from White's point of view, 0..100. */
  whitePercent: number
  /** Mate in N, drawn as a hard edge rather than a percentage. */
  mate?: number | null
  /** Whose side the bar fills from. White by default. */
  flip?: boolean
  height?: number
  showLabels?: boolean
}

export function EvalBar({
  whitePercent,
  mate = null,
  flip = false,
  height = 8,
  showLabels = false,
}: EvalBarProps) {
  const pct = Math.max(0, Math.min(100, whitePercent))
  const isMate = mate !== null && mate !== 0
  const whiteSideWins = isMate ? (mate as number) > 0 : pct >= 50

  return (
    <div
      className={styles.wrap}
      style={{ height }}
      title={
        isMate
          ? `Mate in ${Math.abs(mate as number)}`
          : `White ${pct.toFixed(1)}% · Black ${(100 - pct).toFixed(1)}%`
      }
      role="img"
      aria-label={
        isMate
          ? `Mate in ${Math.abs(mate as number)} for ${whiteSideWins ? 'White' : 'Black'}`
          : `White ${pct.toFixed(0)} percent, Black ${(100 - pct).toFixed(0)} percent`
      }
    >
      <div
        className={styles.fill}
        style={{
          width: isMate ? (whiteSideWins ? '100%' : '0%') : `${pct}%`,
          // The bar grows from whichever side is winning, so it reads the same
          // way for both colours.
          [flip ? 'right' : 'left']: 0,
        }}
      />
      {showLabels ? (
        <div className={styles.labels}>
          <span className={pct >= 50 ? styles.strong : ''}>
            {isMate ? (whiteSideWins ? `#${Math.abs(mate as number)}` : '') : pct.toFixed(0)}
          </span>
          <span className={pct < 50 ? styles.strong : ''}>
            {isMate
              ? whiteSideWins
                ? ''
                : `#${Math.abs(mate as number)}`
              : (100 - pct).toFixed(0)}
          </span>
        </div>
      ) : null}
    </div>
  )
}

/**
 * The eval for the side to move, as the signed number the report shows.
 *
 * `data.json` stores evaluations from the mover's point of view, so a negative
 * number means *the mover* is worse off — not that Black is winning. This
 * returns the mate distance if there is one.
 */
export function mateDistance(cp: number | null | undefined): number | null {
  if (cp === null || cp === undefined) return null
  if (Math.abs(cp) < 9000) return null
  const mates = Math.round(Math.abs(cp) / 100000)
  return mates === 0 ? (cp > 0 ? 1 : -1) : (cp > 0 ? mates : -mates)
}