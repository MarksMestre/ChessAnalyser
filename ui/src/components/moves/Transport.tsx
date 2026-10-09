/**
 * The transport under the move list: first, back, play, forward, last.
 *
 * Keyboard shortcuts are bound at the page level rather than here, so the same
 * keys work from anywhere on the game page.
 */

import type { Speed } from '../../state/gameView'
import { Button, Segmented } from '../ui'
import styles from './Transport.module.css'

export interface TransportProps {
  playing: boolean
  speed: Speed
  ply: number
  lastPly: number
  onFirst: () => void
  onPrev: () => void
  onTogglePlay: () => void
  onNext: () => void
  onLast: () => void
  onSpeed: (speed: Speed) => void
  onStepBack: () => void
  /**
   * False when auto-play has nothing to walk.
   *
   * Auto-play follows the *recorded* line, so from a position that is not in it the
   * button would start a timer that steps through a game the reader is not looking
   * at. Disabled with a reason beats silently doing something else.
   */
  canPlay?: boolean
}

export function Transport({
  playing,
  speed,
  ply,
  lastPly,
  onFirst,
  onPrev,
  onTogglePlay,
  onNext,
  onLast,
  onSpeed,
  onStepBack,
  canPlay = true,
}: TransportProps) {
  return (
    <div className={styles.transport}>
      <div className={styles.buttons}>
        <Button variant="ghost" onClick={onFirst} title="First move (Home)" aria-label="First move">
          ⏮
        </Button>
        <Button variant="ghost" onClick={onPrev} title="Previous move (←)" aria-label="Previous move">
          ◀
        </Button>
        <Button
          variant="primary"
          onClick={onTogglePlay}
          disabled={!canPlay}
          title={
            !canPlay
              ? 'Auto-play follows the recorded game, so it cannot run from a variation'
              : playing
                ? 'Pause (Space)'
                : 'Play (Space)'
          }
          aria-label={playing ? 'Pause' : 'Play'}
          className={styles.play}
        >
          {playing ? '❚❚' : '▶'}
        </Button>
        <Button variant="ghost" onClick={onNext} title="Next move (→)" aria-label="Next move">
          ▶
        </Button>
        <Button variant="ghost" onClick={onLast} title="Last move (End)" aria-label="Last move">
          ⏭
        </Button>
      </div>
      <div className={styles.meta}>
        <span className={styles.count}>
          {Math.min(ply + 1, lastPly + 1)} / {lastPly + 1}
        </span>
        <Button
          variant="ghost"
          onClick={onStepBack}
          title="Take back a move and re-search (Backspace)"
        >
          ⟲ take back
        </Button>
        <Segmented
          ariaLabel="Playback speed"
          value={speed}
          onChange={onSpeed}
          options={[
            { value: 1 as Speed, label: '1×' },
            { value: 2 as Speed, label: '2×' },
            { value: 4 as Speed, label: '4×' },
          ]}
        />
      </div>
    </div>
  )
}