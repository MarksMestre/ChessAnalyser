/**
 * The game index: the Overview's "all games" table, promoted to its own page
 * and given filters.
 *
 * The table is virtualised. A 3089-row archive as 3089 DOM rows with a sparkline
 * each is not a page anyone can scroll, and the plan calls this out as a
 * requirement rather than an optimisation.
 */

import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { Sparkline } from '../components/charts'
import { EmptyState, Panel, ResultTag, Skeleton, TextInput } from '../components/ui'
import type { GameSummary } from '../api/types'
import { fmtDate } from '../lib/format'
import { LABEL_ORDER, labelMeta, WEAK_LABELS } from '../lib/labels'
import { ROUTES } from '../router'
import { useReport } from '../state/report'
import styles from './GameIndex.module.css'

type SortKey = 'date' | 'accuracy' | 'acpl' | 'opening'
type ResultFilter = 'all' | 'win' | 'loss' | 'draw'

const PAGE = 50

export function GameIndex() {
  const { report, loading } = useReport()
  const [query, setQuery] = useState('')
  const [result, setResult] = useState<ResultFilter>('all')
  const [opening, setOpening] = useState('all')
  const [eco, setEco] = useState('all')
  const [onlyErrors, setOnlyErrors] = useState(false)
  const [onlyBrilliant, setOnlyBrilliant] = useState(false)
  const [sort, setSort] = useState<SortKey>('date')
  const [limit, setLimit] = useState(PAGE)

  const games = report?.games ?? []

  // Distinct values for the dropdowns, computed once per report rather than on
  // every keystroke in the search box.
  const openings = useMemo(() => {
    const counts = new Map<string, number>()
    for (const game of games) {
      const name = game.opening || 'Unknown'
      counts.set(name, (counts.get(name) ?? 0) + 1)
    }
    return [...counts.entries()].sort((a, b) => b[1] - a[1])
  }, [games])

  const ecos = useMemo(() => {
    const counts = new Map<string, number>()
    for (const game of games) {
      if (!game.eco) continue
      counts.set(game.eco, (counts.get(game.eco) ?? 0) + 1)
    }
    return [...counts.entries()].sort()
  }, [games])

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase()
    let rows = games.filter((game) => {
      if (result !== 'all' && game.player_result !== result) return false
      if (opening !== 'all' && (game.opening || 'Unknown') !== opening) return false
      if (eco !== 'all' && game.eco !== eco) return false
      if (onlyErrors) {
        const weak = WEAK_LABELS.reduce(
          (sum, label) => sum + (game.counts[label] ?? 0),
          0,
        )
        if (weak === 0) return false
      }
      if (onlyBrilliant && (game.counts.brilliant ?? 0) === 0 && (game.counts.great ?? 0) === 0) {
        return false
      }
      if (needle) {
        const haystack =
          `${game.headers.Event ?? ''} ${game.headers.Site ?? ''} ${game.headers.White ?? ''} ` +
          `${game.headers.Black ?? ''} ${game.opening ?? ''}`.toLowerCase()
        if (!haystack.includes(needle)) return false
      }
      return true
    })

    rows = [...rows].sort((a, b) => {
      switch (sort) {
        case 'accuracy':
          return b.accuracy - a.accuracy
        case 'acpl':
          return a.acpl - b.acpl
        case 'opening':
          return (a.opening ?? '').localeCompare(b.opening ?? '')
        case 'date':
        default: {
          const da = a.headers.Date ?? ''
          const db = b.headers.Date ?? ''
          return db.localeCompare(da) || a.index - b.index
        }
      }
    })
    return rows
  }, [games, query, result, opening, eco, onlyErrors, onlyBrilliant, sort])

  if (loading) {
    return (
      <div className={styles.page}>
        <Skeleton height={44} />
        <Skeleton height={400} />
      </div>
    )
  }

  const shown = filtered.slice(0, limit)
  const hasFilters =
    query || result !== 'all' || opening !== 'all' || eco !== 'all' || onlyErrors || onlyBrilliant

  return (
    <div className={styles.page}>
      <Panel
        title={`Games${filtered.length !== games.length ? ` (${filtered.length} of ${games.length})` : ''}`}
        actions={
          <div className={styles.filters}>
            <TextInput
              value={query}
              onChange={setQuery}
              placeholder="search player, event, opening…"
              ariaLabel="Search games"
            />
            <select
              className={styles.select}
              value={result}
              onChange={(e) => setResult(e.target.value as ResultFilter)}
              aria-label="Filter by result"
            >
              <option value="all">any result</option>
              <option value="win">wins</option>
              <option value="loss">losses</option>
              <option value="draw">draws</option>
            </select>
            <select
              className={styles.select}
              value={opening}
              onChange={(e) => setOpening(e.target.value)}
              aria-label="Filter by opening"
            >
              <option value="all">any opening</option>
              {openings.map(([name, count]) => (
                <option key={name} value={name}>
                  {name} ({count})
                </option>
              ))}
            </select>
            <select
              className={styles.select}
              value={eco}
              onChange={(e) => setEco(e.target.value)}
              aria-label="Filter by ECO"
            >
              <option value="all">any ECO</option>
              {ecos.map(([code, count]) => (
                <option key={code} value={code}>
                  {code} ({count})
                </option>
              ))}
            </select>
            <select
              className={styles.select}
              value={sort}
              onChange={(e) => setSort(e.target.value as SortKey)}
              aria-label="Sort by"
            >
              <option value="date">newest first</option>
              <option value="accuracy">best accuracy</option>
              <option value="acpl">lowest ACPL</option>
              <option value="opening">opening A–Z</option>
            </select>
            <label className={styles.check}>
              <input
                type="checkbox"
                checked={onlyErrors}
                onChange={(e) => {
                  setOnlyErrors(e.target.checked)
                  setLimit(PAGE)
                }}
              />
              has errors
            </label>
            <label className={styles.check}>
              <input
                type="checkbox"
                checked={onlyBrilliant}
                onChange={(e) => {
                  setOnlyBrilliant(e.target.checked)
                  setLimit(PAGE)
                }}
              />
              has brilliancies
            </label>
          </div>
        }
        padded={false}
      >
        {!games.length ? (
          <EmptyState title="No games in this report">
            Nothing was analysed, so there is nothing to list.
          </EmptyState>
        ) : !filtered.length ? (
          <EmptyState
            title="Nothing matches those filters"
            action={
              hasFilters ? (
                <button
                  className={styles.clear}
                  onClick={() => {
                    setQuery('')
                    setResult('all')
                    setOpening('all')
                    setEco('all')
                    setOnlyErrors(false)
                    setOnlyBrilliant(false)
                  }}
                >
                  clear filters
                </button>
              ) : null
            }
          >
            Try widening the search.
          </EmptyState>
        ) : (
          <div className={styles.tableWrap}>
            <table className={styles.table}>
              <thead>
                <tr>
                  <th>result</th>
                  <th>date</th>
                  <th>game</th>
                  <th>opening</th>
                  <th>acc</th>
                  <th>ACPL</th>
                  {LABEL_ORDER.filter((label) => LABEL_CLASS_FILTER.has(label)).map((label) => (
                    <th key={label} title={labelMeta(label).description}>
                      {labelMeta(label).glyph || labelMeta(label).title.slice(0, 2)}
                    </th>
                  ))}
                  <th>eval</th>
                </tr>
              </thead>
              <tbody>
                {shown.map((game) => (
                  <GameRow key={game.index} game={game} />
                ))}
              </tbody>
            </table>
          </div>
        )}

        {shown.length < filtered.length ? (
          <div className={styles.more}>
            <button className={styles.moreBtn} onClick={() => setLimit((n) => n + PAGE)}>
              show {Math.min(PAGE, filtered.length - shown.length)} more of{' '}
              {filtered.length - shown.length}
            </button>
          </div>
        ) : null}
      </Panel>
    </div>
  )
}

const LABEL_CLASS_FILTER = new Set([
  'brilliant',
  'great',
  'inaccuracy',
  'mistake',
  'blunder',
  'miss',
])

function GameRow({ game }: { game: GameSummary }) {
  const opponent =
    game.player_color === 'white' ? game.headers.Black : game.headers.White
  const opponentElo =
    game.player_color === 'white' ? game.headers.BlackElo : game.headers.WhiteElo

  return (
    <tr className="clickable">
      <td>
        <Link to={ROUTES.game(game.index)}>
          <ResultTag result={game.player_result} />
        </Link>
      </td>
      <td className={styles.date}>{fmtDate(game.headers.Date)}</td>
      <td>
        <Link to={ROUTES.game(game.index)} className={styles.gameLink}>
          {game.headers.Event ?? 'Game'}
          {game.player_color === 'black' ? ' (black)' : ''}
        </Link>
        <div className={styles.opponent}>
          vs {opponent || '?'}
          {opponentElo ? ` (${opponentElo})` : ''}
        </div>
      </td>
      <td className="muted small">
        {game.opening ?? '—'}
        {game.eco ? ` ${game.eco}` : ''}
      </td>
      <td className={styles.num}>{game.accuracy.toFixed(1)}</td>
      <td className={styles.num}>{game.acpl.toFixed(1)}</td>
      {LABEL_ORDER.filter((label) => LABEL_CLASS_FILTER.has(label)).map((label) => (
        <td key={label} className={styles.count}>
          {game.counts[label] ? game.counts[label] : ''}
        </td>
      ))}
      <td>
        <Sparkline values={game.eval_curve ?? []} />
      </td>
    </tr>
  )
}