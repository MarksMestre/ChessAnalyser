/**
 * The player bars above and below the board.
 *
 * Follows the reference layout: avatar, name, rating in parentheses, flag; and a
 * clock on the outer edge. The clock shows accumulated analysis time rather than
 * a game clock, because the source PGN rarely has one — showing a fabricated
 * clock would be worse than showing none, so the number is labelled for what it
 * is.
 */

import { monogram } from '../../lib/format'
import { Pill } from '../ui'
import styles from './PlayerBar.module.css'

export interface PlayerBarProps {
  name: string | null
  elo: number | null
  /** True for the side the analysis is scoring. */
  isPlayer?: boolean
  /** Country code, when the PGN headers carry one. */
  country?: string | null
  /** Accumulated time on the clock. */
  clock?: string | null
  /** Ranked or not, from the headers. */
  timeControl?: string | null
  result?: string | null
  /** Hides the clock on the top bar when it is not applicable. */
  showClock?: boolean
}

export function PlayerBar({
  name,
  elo,
  isPlayer = false,
  country,
  clock,
  result,
  showClock = true,
}: PlayerBarProps) {
  return (
    <div className={`${styles.bar} ${isPlayer ? styles.player : ''}`}>
      <div className={styles.avatar} aria-hidden>
        {monogram(name)}
      </div>
      <div className={styles.who}>
        <span className={styles.name}>{name || 'Unknown'}</span>
        {elo !== null && elo !== undefined ? (
          <span className={styles.elo}>({elo})</span>
        ) : null}
        {country ? <span className={styles.flag}>{flagEmoji(country)}</span> : null}
        {isPlayer ? <Pill tone="good">you</Pill> : null}
        {result ? <ResultWord result={result} /> : null}
      </div>
      {showClock && clock ? (
        <div className={styles.clock} title="accumulated time in this game">
          {clock}
        </div>
      ) : null}
    </div>
  )
}

function ResultWord({ result }: { result: string }) {
  const tone =
    result === 'win' ? 'good' : result === 'loss' ? 'bad' : 'warn'
  const word = result === 'win' ? 'won' : result === 'loss' ? 'lost' : 'drew'
  return <Pill tone={tone}>{word}</Pill>
}

/**
 * A country code as a flag.
 *
 * Only letters that pair into a regional-indicator pair produce a flag glyph;
 * anything else returns the code itself, because a tofu box is worse than an
 * abbreviation.
 */
export function flagEmoji(code: string): string {
  const clean = code.trim().toUpperCase()
  if (!/^[A-Z]{2}$/.test(clean)) return clean
  const base = 0x1f1e6
  const a = base + (clean.charCodeAt(0) - 65)
  const b = base + (clean.charCodeAt(1) - 65)
  return String.fromCodePoint(a, b)
}