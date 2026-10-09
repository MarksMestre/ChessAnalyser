/**
 * The Overview: every panel the legacy report had, plus the ELO section.
 *
 * The original plan asks for an overview page showing the player's ELO and does
 * not ask for anything to be dropped, so nothing is: accuracy trend, per-phase
 * breakdown, recurring weaknesses, brilliancies, best/worst games and the full
 * game list are all here.
 */

import { Link } from 'react-router-dom'
import { BarChart, LineChart } from '../components/charts'
import { Sparkline } from '../components/charts'
import { LabelBadge, Panel, ResultTag, Skeleton, Stat } from '../components/ui'
import type { Brilliancy, PlayerIdentity, Ratings, Report, TrendRow, Weakness } from '../api/types'
import { COUNTED_LABELS, LABEL_TEXT_CLASS, labelMeta } from '../lib/labels'
import { fmtDate } from '../lib/format'
import { ROUTES } from '../router'
import { useReport } from '../state/report'
import styles from './Overview.module.css'

export function Overview() {
  const { report, loading, games } = useReport()
  const dashboard = report?.dashboard

  if (loading || !report || !dashboard) {
    return (
      <div className={styles.page}>
        <div className={styles.hero}>
          <Skeleton height={68} />
        </div>
        <div className={styles.grid3}>
          {Array.from({ length: 6 }, (_, i) => (
            <Skeleton key={i} height={78} />
          ))}
        </div>
        <Skeleton height={230} />
      </div>
    )
  }

  const { totals, ratings } = dashboard
  const record = `${totals.wins}W ${totals.losses}L ${totals.draws}D`

  return (
    <div className={styles.page}>
      {/* ---------------- hero: ELO first, then accuracy ---------------- */}
      <section className={styles.hero}>
        <div className={styles.heroMain}>
          <div className={styles.playerName}>{headlineName(report)}</div>
          <EloHeadline ratings={ratings} />
          {/*
            Per-site, because `--player me` has one name per site and a single
            string cannot say which account is which. Omitted entirely when the
            pack predates the field, rather than shown as an empty line.
          */}
          <IdentityLine identities={report.player_identities} />
          <div className={styles.heroSub}>
            {dashboard.games} game{dashboard.games === 1 ? '' : 's'} analysed · generated{' '}
            {fmtDate(report.generated.slice(0, 10))}
            {report.settings.stockfish ? ` · ${report.settings.stockfish}` : ''}
          </div>
        </div>
        <div className={styles.heroStats}>
          <Stat label="accuracy" value={totals.accuracy_mean.toFixed(1)} />
          <Stat label="ACPL" value={totals.acpl_mean.toFixed(1)} />
          <Stat label="record" value={record} />
        </div>
      </section>

      {/* ---------------- ELO over time ---------------- */}
      <Panel title="Rating over time">
        <EloChart ratings={ratings} />
      </Panel>

      {/* ---------------- ELO, and accuracy by opponent strength -------- */}
      <div className={styles.grid2}>
        <Panel title="Accuracy against opponent strength">
          <p className={styles.note}>
            Raw accuracy hides who you were playing. This splits the same games by
            the opponent's rating.
          </p>
          {ratings ? (
            <OpponentBuckets ratings={ratings} />
          ) : (
            <p className="muted small">
              No rating data in this report. Re-run <code>analyze.py</code> to add it.
            </p>
          )}
        </Panel>

        <Panel title="Move quality">
          <div className={styles.grid3}>
            <Stat label="brilliant" value={totals.counts.brilliant ?? 0} tone="brilliant" />
            <Stat label="great" value={totals.counts.great ?? 0} tone="great" />
            <Stat label="best" value={totals.counts.best ?? 0} tone="best" />
            <Stat label="inaccuracy" value={totals.counts.inaccuracy ?? 0} tone="inaccuracy" />
            <Stat label="mistake" value={totals.counts.mistake ?? 0} tone="mistake" />
            <Stat label="blunder" value={totals.counts.blunder ?? 0} tone="blunder" />
          </div>
        </Panel>
      </div>

      {/* ---------------- accuracy / ACPL trend ---------------- */}
      <Panel
        title="Accuracy by game"
        actions={<Link className={styles.more} to={ROUTES.games}>all games →</Link>}
      >
        {dashboard.trend.length ? (
          <AccuracyTrend trend={dashboard.trend} />
        ) : (
          <p className="muted">No games to chart.</p>
        )}
      </Panel>

      {/* ---------------- per phase ---------------- */}
      <Panel title="Accuracy by phase">
        <p className={styles.note}>
          The lowest column is the part of the game to work on. The opening ends
          where book theory ends.
        </p>
        <PhaseTable phases={dashboard.phases} />
      </Panel>

      {/* ---------------- weaknesses ---------------- */}
      {dashboard.weaknesses.length ? (
        <Panel title="Recurring weaknesses">
          <p className={styles.note}>
            Counted across the whole archive. Every row is checkable against the
            move tables.
          </p>
          <WeaknessList items={dashboard.weaknesses} />
        </Panel>
      ) : null}

      {/* ---------------- brilliancies ---------------- */}
      <Panel title="Your brilliancies">
        {dashboard.brilliancies.length ? (
          <BrilliancyList items={dashboard.brilliancies} />
        ) : (
          <p className="muted">
            None in this set. A brilliant label needs a real sacrifice the engine
            still rates as no worse than the alternatives.
          </p>
        )}
      </Panel>

      {/* ---------------- best / worst ---------------- */}
      <div className={styles.grid2}>
        <GameList title="Best games" rows={dashboard.best_games} />
        <GameList title="Games to review" rows={dashboard.worst_games} />
      </div>

      {/* ---------------- all games ---------------- */}
      <Panel
        title="All games"
        actions={<Link className={styles.more} to={ROUTES.games}>filter →</Link>}
      >
        <GameTable rows={dashboard.trend.slice(0, 12)} loaded={games.size} />
      </Panel>
    </div>
  )
}

/* ------------------------------------------------------------- identities */

/**
 * The name to show, never the literal alias.
 *
 * `--player me` writes the argument into older reports, so `report.player` can
 * be the two letters "me". Falling back through `ratings.player` recovers the
 * real name for those, and "Player" is the last resort.
 */
function headlineName(report: Report): string {
  const candidates = [report.player, report.dashboard.ratings?.player]
  for (const value of candidates) {
    const name = (value ?? '').trim()
    if (name && !/^me$/i.test(name)) return name
  }
  return 'Player'
}

/**
 * `Chess.com: MARK8HS · 5 games | LICHESS.ORG: mark8hs · no games`
 *
 * A configured-but-empty site is dimmed and says so, which is the whole reason
 * it is listed: otherwise "you only play on Chess.com" and "this report happens
 * to be Chess.com-only" look identical.
 */
function IdentityLine({ identities }: { identities?: PlayerIdentity[] }) {
  if (!identities?.length) return null
  return (
    <div className={styles.identities}>
      {identities.map((identity) => (
        <span
          key={identity.site}
          className={`${styles.identity} ${identity.games ? '' : styles.identityUnused}`}
          title={
            identity.games
              ? `${identity.games} game${identity.games === 1 ? '' : 's'} on ${identity.site}`
              : `No games on ${identity.site} in this report`
          }
        >
          <span className={styles.identitySite}>{identity.site}:</span>{' '}
          <span className={styles.identityName}>{identity.name || '—'}</span>
          <span className={styles.identityCount}>
            {' · '}
            {identity.games ? `${identity.games} game${identity.games === 1 ? '' : 's'}` : 'no games'}
          </span>
        </span>
      ))}
    </div>
  )
}

/* ------------------------------------------------------------------ ELO */

/**
 * The headline rating.
 *
 * The delta is against the first rated game, not against a stored baseline,
 * because no such baseline exists in the data. `games_rated` sits next to it so
 * a delta computed from two points is not mistaken for a trend.
 */
function EloHeadline({ ratings }: { ratings?: Ratings }) {
  if (!ratings || ratings.current === null) {
    return (
      <div className={styles.eloLine}>
        <span className={styles.eloMissing}>no rating data</span>
        <span className="small muted">
          unrated games carry no ELO tag, so there is nothing to plot
        </span>
      </div>
    )
  }

  const delta = ratings.delta
  const direction = delta === null ? '' : delta > 0 ? 'up' : delta < 0 ? 'down' : 'flat'

  return (
    <div className={styles.eloLine}>
      <span className={styles.eloValue}>{ratings.current}</span>
      {delta !== null && delta !== 0 ? (
        <span className={`${styles.eloDelta} ${styles[`elo_${direction}`]}`}>
          {delta > 0 ? '▲' : '▼'} {Math.abs(delta)}
        </span>
      ) : null}
      <span className={styles.eloMeta}>
        peak {ratings.peak} · low {ratings.low} · {ratings.games_rated} rated game
        {ratings.games_rated === 1 ? '' : 's'}
      </span>
    </div>
  )
}

/**
 * The rating chart.
 *
 * Below three points a line would be a straight segment through two guesses, so
 * a message replaces it. That is the difference between a chart and a lie.
 */
function EloChart({ ratings }: { ratings?: Ratings }) {
  if (!ratings || ratings.series.length === 0) {
    return (
      <p className="muted">
        No rated games in this set. Chess.com omits the ELO tag for unrated games,
        and those are skipped rather than counted as zero.
      </p>
    )
  }
  if (ratings.series.length < 3) {
    return (
      <p className="muted">
        Only {ratings.series.length} rated game
        {ratings.series.length === 1 ? '' : 's'} in this set, which is not enough
        to draw a trend. Current rating: <b>{ratings.current}</b>.
      </p>
    )
  }

  const series = ratings.series.map((point, i) => ({
    x: i,
    y: point.elo,
    meta: `${fmtDate(point.date)} · ${point.elo} vs ${point.opponent || '?'} (${
      point.opponent_elo ?? '?'
    }) · ${point.accuracy.toFixed(1)}% · ${point.result}`,
  }))

  const comparison = ratings.series
    .filter((point) => point.opponent_elo !== null)
    .map((point, i) => ({ x: i, y: point.opponent_elo as number }))

  return (
    <>
      <LineChart
        series={series}
        comparison={comparison.length ? comparison : undefined}
        yLabel="your rating"
        dotTone={(point) => {
          const result = ratings.series[point.x]?.result
          return result === 'win'
            ? 'var(--win)'
            : result === 'loss'
              ? 'var(--loss)'
              : 'var(--draw)'
        }}
        dedupeXLabels
        formatX={(i) => fmtDate(ratings.series[i]?.date)}
        formatY={(v) => String(Math.round(v))}
      />
      <div className={styles.chartLegend}>
        <span className={styles.legendItem}>
          <i style={{ background: 'var(--win)' }} /> win
        </span>
        <span className={styles.legendItem}>
          <i style={{ background: 'var(--draw)' }} /> draw
        </span>
        <span className={styles.legendItem}>
          <i style={{ background: 'var(--loss)' }} /> loss
        </span>
        <span className={styles.legendItem}>
          <i className={styles.dashed} /> opponent
        </span>
      </div>
    </>
  )
}

function OpponentBuckets({ ratings }: { ratings: Ratings }) {
  const rated = ratings.buckets.filter((bucket) => bucket.games > 0)
  if (!rated.length) {
    return (
      <p className="muted small">
        None of these games recorded the opponent's rating.
      </p>
    )
  }
  return (
    <>
      <BarChart
        bars={ratings.buckets.map((bucket) => ({
          label: bucket.band,
          value: bucket.accuracy,
          caption: `${bucket.games} game${bucket.games === 1 ? '' : 's'}`,
        }))}
        formatValue={(v) => v.toFixed(1)}
      />
      {rated.length < ratings.buckets.length ? (
        <p className="muted small" style={{ marginTop: 'var(--sp-3)' }}>
          Empty bands are opponents you have not faced at that level.
        </p>
      ) : null}
    </>
  )
}

/* ---------------------------------------------------------------- trend */

function AccuracyTrend({ trend }: { trend: TrendRow[] }) {
  const byDate = [...trend].sort((a, b) => (a.date < b.date ? -1 : a.date > b.date ? 1 : 0))
  const series = byDate.map((row, i) => ({
    x: i,
    y: row.accuracy,
    meta: `${row.title} · ${row.accuracy.toFixed(1)}% · ACPL ${row.acpl.toFixed(1)}`,
  }))
  return (
    <LineChart
      series={series}
      yLabel="accuracy %"
      zeroFloor
      dotTone={(point) => {
        const row = byDate[point.x]
        return row?.result === 'win'
          ? 'var(--win)'
          : row?.result === 'loss'
            ? 'var(--loss)'
            : 'var(--draw)'
      }}
      formatX={(i) => fmtDate(byDate[i]?.date)}
      formatY={(v) => v.toFixed(0)}
    />
  )
}

/* ----------------------------------------------------------------- phase */

function PhaseTable({ phases }: { phases: import('../api/types').Dashboard['phases'] }) {
  const rows = (['opening', 'middlegame', 'endgame'] as const).map((phase) => {
    const stats = phases[phase]
    return stats ? { phase, stats } : null
  }).filter(Boolean) as Array<{
    phase: string
    stats: import('../api/types').PhaseStats
  }>

  if (!rows.length) return <p className="muted">No phase data.</p>

  return (
    <table>
      <thead>
        <tr>
          <th>phase</th>
          <th>moves</th>
          <th>accuracy</th>
          <th>ACPL</th>
          {COUNTED_LABELS.map((label) => (
            <th key={label} title={labelMeta(label).title}>
              {labelMeta(label).glyph}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map(({ phase, stats }) => (
          <tr key={phase}>
            <td>{phase}</td>
            <td>{stats.moves}</td>
            <td>{stats.accuracy.toFixed(1)}</td>
            <td>{stats.acpl.toFixed(1)}</td>
            {COUNTED_LABELS.map((label) => {
              // One number per cell. This used to put two labels in one cell
              // under one header, so `!! 0` rendered as "0 0" and the header
              // claimed to mean brilliant+great when it did not.
              const value = stats[label] ?? 0
              return (
                <td key={label} className={styles.count}>
                  <span className={value ? LABEL_TEXT_CLASS[label] : styles.countZero}>
                    {value}
                  </span>
                </td>
              )
            })}
          </tr>
        ))}
      </tbody>
    </table>
  )
}

/* ------------------------------------------------------------ weaknesses */

function WeaknessList({ items }: { items: Weakness[] }) {
  return (
    <div className={styles.list}>
      {items.map((item) => (
        <div key={item.key} className={styles.listItem}>
          <div className={styles.listHead}>
            <b>{item.label}</b>
            <span className={styles.countPill}>{item.count}×</span>
            <span className={styles.countPill}>
              {item.game_count} game{item.game_count === 1 ? '' : 's'}
            </span>
          </div>
          <div className={styles.examples}>
            {item.examples.slice(0, 4).map((example, i) => (
              <span key={i} className={styles.example}>
                {example}
              </span>
            ))}
          </div>
        </div>
      ))}
    </div>
  )
}

function BrilliancyList({ items }: { items: Brilliancy[] }) {
  return (
    <div className={styles.list}>
      {items.map((item, i) => (
        <Link
          key={i}
          className={styles.listItem}
          to={`${ROUTES.game(item.game)}/${Math.max(0, item.move_number * 2 - 2)}`}
        >
          <div className={styles.listHead}>
            <LabelBadge label="brilliant" glyph="!!" />
            <b>
              {item.move_number}. {item.san}
            </b>
            <span className="small muted">{item.title}</span>
            <span className={styles.go}>open →</span>
          </div>
          <div className={styles.examples}>
            {item.sacrifice
              ? `sacrificed ${item.sacrifice} points of material · `
              : ''}
            loss only {item.loss_pp.toFixed(1)}pp
            {item.pv?.length ? ` · engine line: ${item.pv.join(' ')}` : ''}
          </div>
        </Link>
      ))}
    </div>
  )
}

function GameList({
  title,
  rows,
}: {
  title: string
  rows: Array<{
    index: number
    accuracy: number
    title: string
    opening: string | null
    result: string
  }>
}) {
  return (
    <Panel title={title}>
      <table>
        <tbody>
          {rows.map((row) => (
            <tr key={row.index} className="clickable">
              <td style={{ width: 62 }}>{row.accuracy.toFixed(1)}</td>
              <td>
                {/*
                  A Link, not an onClick that assigns window.location: the
                  latter throws away the whole app and re-fetches the report,
                  which is exactly what the router exists to avoid.
                */}
                <Link to={ROUTES.game(row.index)} className={styles.gameLink}>
                  {row.title}
                </Link>
              </td>
              <td className="muted small">{row.opening ?? ''}</td>
              <td>
                <ResultTag result={row.result} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </Panel>
  )
}

function GameTable({ rows, loaded }: { rows: TrendRow[]; loaded: number }) {
  return (
    <>
      <table>
        <thead>
          <tr>
            <th>result</th>
            <th>game</th>
            <th>opening</th>
            <th>acc</th>
            <th>ACPL</th>
            {COUNTED_LABELS.map((label) => (
              <th key={label} title={labelMeta(label).title}>
                {labelMeta(label).glyph}
              </th>
            ))}
            <th>eval</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.index}>
              <td>
                <Link to={ROUTES.game(row.index)}>
                  <ResultTag result={row.result} />
                </Link>
              </td>
              <td>
                <Link to={ROUTES.game(row.index)} className={styles.gameLink}>
                  {row.title}
                </Link>
              </td>
              <td className="muted small">{row.opening ?? ''}</td>
              <td>{row.accuracy.toFixed(1)}</td>
              <td>{row.acpl.toFixed(1)}</td>
              {COUNTED_LABELS.map((label) => {
                const value = row.counts[label] ?? 0
                return (
                  <td key={label} className={styles.count}>
                    {/* Blank rather than `0` here: this table lists twelve games,
                        and a grid of zeros is noise where the phase table's zeros
                        are the point. */}
                    <span className={value ? LABEL_TEXT_CLASS[label] : undefined}>
                      {value === 0 ? '' : value}
                    </span>
                  </td>
                )
              })}
              <td>
                <Sparkline values={row.eval_curve ?? []} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {loaded > 0 ? (
        <p className="muted small" style={{ marginTop: 'var(--sp-3)' }}>
          {loaded} game{loaded === 1 ? '' : 's'} opened so far. The rest load when
          you open them.
        </p>
      ) : null}
    </>
  )
}

