/**
 * Drill mode: the answer is hidden, you choose, then the engine line is shown.
 *
 * Two selections — every move, or only the ones worth practising. The second is
 * what a person actually wants: "drill my mistakes" rather than replaying forty
 * moves to reach the three that mattered.
 */

import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import type { Move } from '../api/types'
import { Board } from '../components/board/Board'
import { EvalBar } from '../components/board/EvalBar'
import { PlayerBar } from '../components/board/PlayerBar'
import { CommentaryPanel } from '../components/moves/CommentaryPanel'
import {
  Button,
  EmptyState,
  Progress,
  Segmented,
  Skeleton,
  Tabs,
} from '../components/ui'
import { START_FEN } from '../lib/fen'
import { winPercent } from '../lib/format'
import { fromRecorded } from '../lib/moveView'
import { WEAK_LABELS } from '../lib/labels'
import { ROUTES } from '../router'
import { useReport } from '../state/report'
import styles from './GameDrill.module.css'

type Scope = 'mistakes' | 'all'
type Stage = 'choose' | 'revealed'

interface Question {
  move: Move
  /** The recorded legal moves as "uci:san", which is how data.json stores them. */
  choices: Array<{ uci: string; san: string }>
}

export function GameDrill() {
  const { gameId } = useParams()
  const { games, loadGame } = useReport()
  const index = Number.parseInt(gameId ?? '', 10)
  const game = Number.isFinite(index) ? (games.get(index) ?? null) : null

  useEffect(() => {
    if (Number.isFinite(index) && !games.has(index)) void loadGame(index)
  }, [index, games, loadGame])

  if (!Number.isFinite(index) || !game) {
    return (
      <div className={styles.page}>
        {game ? (
          <Skeleton height={420} />
        ) : (
          <EmptyState title="No game selected">
            <Link to={ROUTES.games}>pick a game</Link>
          </EmptyState>
        )}
      </div>
    )
  }

  return <DrillBody game={game} />
}

function DrillBody({ game }: { game: import('../api/types').GameDetail }) {
  const [scope, setScope] = useState<Scope>('mistakes')
  const [stage, setStage] = useState<Stage>('choose')
  const [picked, setPicked] = useState<string | null>(null)
  const [at, setAt] = useState(0)
  const [scored, setScored] = useState({ right: 0, wrong: 0 })

  const questions = useMemo<Question[]>(() => {
    const mine = game.moves.filter((move) => move.is_players_turn && move.legal?.length)
    const chosen =
      scope === 'mistakes'
        ? mine.filter((move) => WEAK_LABELS.includes(move.label))
        : mine
    return chosen.map((move) => ({
      move,
      choices: move.legal.map((entry) => {
        const [uci, san] = entry.split(':')
        return { uci, san: san ?? uci }
      }),
    }))
  }, [game, scope])

  // Changing scope invalidates the current answer, so start over.
  useEffect(() => {
    setAt(0)
    setStage('choose')
    setPicked(null)
    setScored({ right: 0, wrong: 0 })
  }, [scope])

  const question = questions[at] ?? null

  const reveal = useCallback(() => {
    if (!question) return
    setPicked((current) => current ?? question.move.uci)
    setStage('revealed')
  }, [question])

  const next = useCallback(() => {
    setAt((current) => Math.min(current + 1, Math.max(0, questions.length - 1)))
    setStage('choose')
    setPicked(null)
  }, [questions.length])

  // Keyboard: Enter reveals, arrows step between questions.
  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      if (event.target instanceof HTMLInputElement) return
      if (event.key === 'Enter' && stage === 'choose') {
        event.preventDefault()
        reveal()
      }
      if (event.key === 'ArrowRight' && stage === 'revealed') {
        event.preventDefault()
        next()
      }
      if (event.key === 'ArrowLeft') {
        event.preventDefault()
        setAt((current) => Math.max(0, current - 1))
        setStage('choose')
        setPicked(null)
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [stage, reveal, next])

  if (!questions.length) {
    return (
      <div className={styles.page}>
        <EmptyState
          title={scope === 'mistakes' ? 'No mistakes to drill' : 'No moves to drill'}
          action={
            scope === 'mistakes' ? (
              <Button onClick={() => setScope('all')}>drill every move instead</Button>
            ) : null
          }
        >
          {scope === 'mistakes'
            ? 'Nothing in this game was labelled an inaccuracy, mistake or blunder. Switch to every move to practise anyway.'
            : 'This game has no recorded moves.'}
        </EmptyState>
      </div>
    )
  }

  const move = question?.move ?? null
  const headers = game.headers
  const right = picked !== null && picked === move?.uci

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <div>
          <h1>Drill</h1>
          <div className={styles.sub}>
            {headers.White ?? 'White'} vs {headers.Black ?? 'Black'} · question {at + 1} of{' '}
            {questions.length}
          </div>
        </div>
        <div className={styles.headerRight}>
          <Segmented
            ariaLabel="What to drill"
            value={scope}
            onChange={setScope}
            options={[
              { value: 'mistakes' as Scope, label: 'my mistakes', title: 'Only weak moves' },
              { value: 'all' as Scope, label: 'every move' },
            ]}
          />
          <Link className={styles.back} to={ROUTES.game(game.index)}>
            ← the analysis
          </Link>
        </div>
      </header>

      <div className={styles.progressRow}>
        <Progress value={((at + (stage === 'revealed' ? 1 : 0)) / questions.length) * 100} />
        <span className={styles.tally}>
          <span className={styles.right}>{scored.right}</span> right ·{' '}
          <span className={styles.wrong}>{scored.wrong}</span> wrong
        </span>
      </div>

      <div className={styles.columns}>
        <div className={styles.boardColumn}>
          <PlayerBar
            name={move?.color === 'white' ? headers.White : headers.Black}
            elo={null}
            isPlayer={move?.color === game.player_color}
          />
          <div className={styles.boardWrap}>
            <Board
              /*
                Drill keeps `move.fen`, the position *before* the question —
                unlike the analysis page, which shows the position after the
                move. The question is "what would you play here?", so the
                starting position is the correct one to show.
              */
              fen={move?.fen ?? START_FEN}
              orientation={game.player_color === 'black' ? 'black' : 'white'}
              arrows={
                stage === 'revealed' && move?.uci
                  ? [
                      {
                        from: move.uci.slice(0, 2),
                        to: move.uci.slice(2, 4),
                        colour: 'red',
                      },
                    ]
                  : []
              }
            />
          </div>
          <EvalBar whitePercent={winPercent(move?.eval_before ?? null)} height={8} />
        </div>

        <div className={styles.side}>
          <Tabs
            value={stage}
            onChange={(value) => (value === 'choose' ? setPicked(null) : reveal())}
            tabs={[
              { value: 'choose' as Stage, label: 'Your move' },
              { value: 'revealed' as Stage, label: 'Engine' },
            ]}
          />

          <div className={styles.sideBody}>
            {move ? (
              <>
                <p className={styles.prompt}>
                  {move.move_number}
                  {move.color === 'black' ? '…' : '.'} What did you play?
                </p>

                <div className={styles.choices}>
                  {question?.choices.map((choice) => {
                    const isPicked = picked === choice.uci
                    const isAnswer = choice.uci === move.uci
                    const show = stage === 'revealed' || isPicked
                    return (
                      <button
                        key={choice.uci}
                        className={`${styles.choice} ${
                          isPicked ? styles.choicePicked : ''
                        } ${show && isAnswer ? styles.choiceRight : ''} ${
                          show && isPicked && !isAnswer ? styles.choiceWrong : ''
                        }`}
                        onClick={() => {
                          if (stage === 'revealed') return
                          setPicked(choice.uci)
                        }}
                        title={show && !isAnswer ? 'this is not what was played' : undefined}
                      >
                        {choice.san}
                      </button>
                    )
                  })}
                </div>

                {stage === 'choose' ? (
                  <Button variant="primary" onClick={reveal}>
                    Reveal the answer
                  </Button>
                ) : (
                  <>
                    <div className={styles.verdict}>
                      {picked ? (
                        <p className={right ? styles.good : styles.bad}>
                          {right
                            ? 'You found it.'
                            : `You would have played ${
                                question?.choices.find((c) => c.uci === picked)?.san ?? '?'
                              }.`}
                        </p>
                      ) : null}
                      <CommentaryPanel move={move ? fromRecorded(move) : null} />
                      <Button onClick={next} variant="primary">
                        {at + 1 < questions.length ? 'Next move →' : 'Done'}
                      </Button>
                    </div>
                  </>
                )}

                <p className={styles.hint}>
                  <kbd>Enter</kbd> reveals · <kbd>←</kbd> <kbd>→</kbd> step
                </p>

                {/* Tally, recorded once the answer is seen. */}
                {stage === 'revealed' && picked ? <Tally right={right} onRecord={setScored} /> : null}
              </>
            ) : null}
          </div>
        </div>
      </div>
    </div>
  )
}

/** Records the result of the current question exactly once. */
function Tally({
  right,
  onRecord,
}: {
  right: boolean
  onRecord: (updater: (prev: { right: number; wrong: number }) => { right: number; wrong: number }) => void
}) {
  useEffect(() => {
    onRecord((prev) => ({
      right: prev.right + (right ? 1 : 0),
      wrong: prev.wrong + (right ? 0 : 1),
    }))
    // Runs once per reveal: `right` is the only input, and the parent re-renders
    // the question afterwards so this must not repeat on every render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [right])
  return null
}

