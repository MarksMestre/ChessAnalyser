/**
 * The app shell: header, nav, and the route outlet.
 *
 * The nav is a set of tabs rather than a menu, because there are five
 * destinations and all of them are worth being one click away.
 */

import { NavLink, Route, Routes, useNavigate } from 'react-router-dom'
import { useEffect } from 'react'
import { ErrorNote, Skeleton } from './components/ui'
import { useReport } from './state/report'
import { STANDALONE } from './router'
import { ExportPage } from './pages/ExportPage'
import { GameAnalysis } from './pages/GameAnalysis'
import { GameDrill } from './pages/GameDrill'
import { GameIndex } from './pages/GameIndex'
import { GamePlay } from './pages/GamePlay'
import { Overview } from './pages/Overview'
import styles from './App.module.css'

const NAV = [
  { to: '/', label: 'Overview', end: true },
  { to: '/games', label: 'Games', end: false },
]

export function App() {
  const { report, loading, error, needsBuild, reload } = useReport()
  const navigate = useNavigate()

  // The eval graph and the move list both want to own the arrow keys, but only
  // on the game page; a global handler would fight them. So the shortcuts are
  // bound per page, and only Escape returns to the list from a sub-route.
  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        const path = window.location.pathname
        const match = path.match(/\/games\/(\d+)/)
        if (match && path.split('/').length > 3) {
          navigate(`/games/${match[1]}`)
        }
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [navigate])

  return (
    <div className={styles.app}>
      <header className={styles.header}>
        <div className={styles.brand}>
          <span className={styles.mark}>♞</span>
          <span className={styles.name}>chess-coach</span>
          {STANDALONE ? <span className={styles.badge}>standalone</span> : null}
        </div>
        <nav className={styles.nav}>
          {NAV.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) =>
                `${styles.navLink} ${isActive ? styles.navActive : ''}`
              }
            >
              {item.label}
            </NavLink>
          ))}
          <NavLink
            to="/export"
            className={({ isActive }) =>
              `${styles.navLink} ${isActive ? styles.navActive : ''}`
            }
          >
            Export
          </NavLink>
        </nav>
        <div className={styles.headerMeta}>
          {report ? (
            <span className="small muted">
              {/*
                The resolved name, not the `--player` argument. With `--player me`
                a report built before the fix holds the literal string "me" here,
                so the alias is filtered rather than printed as a username.
              */}
              {nameOrFallback(report.player, report.dashboard.ratings?.player)}{' '}
              · {report.dashboard.games} game{report.dashboard.games === 1 ? '' : 's'}
            </span>
          ) : null}
        </div>
      </header>

      <main className={styles.main}>
        {needsBuild ? (
          <div className={styles.centre}>
            <ErrorNote>
              No report pack found. Build one with:
              {'\n\n'}  python report.py --pack --out out\pack
              {'\n\n'}or open a single self-contained file instead:
              {'\n'}  python report.py
            </ErrorNote>
            <button className={styles.retry} onClick={reload}>
              check again
            </button>
          </div>
        ) : error ? (
          <div className={styles.centre}>
            <ErrorNote>{error}</ErrorNote>
            <button className={styles.retry} onClick={reload}>
              retry
            </button>
          </div>
        ) : loading && !report ? (
          <div className={styles.centre}>
            <Skeleton height={120} />
            <Skeleton height={260} />
          </div>
        ) : (
          /*
            Keyed on the pathname so switching games re-mounts the page and its
            animations play. Without it a move-list change would cross-fade the
            entire view, including the board.
          */
          <Routes>
            <Route path="/" element={<Overview />} />
            <Route path="/games" element={<GameIndex />} />
            <Route path="/games/:gameId" element={<GameAnalysis />} />
            <Route path="/games/:gameId/:ply" element={<GameAnalysis />} />
            <Route path="/games/:gameId/play" element={<GamePlay />} />
            <Route path="/games/:gameId/play/:ply" element={<GamePlay />} />
            <Route path="/games/:gameId/drill" element={<GameDrill />} />
            <Route path="/export" element={<ExportPage />} />
            <Route path="*" element={<NotFound />} />
          </Routes>
        )}
      </main>

      <footer className={styles.footer}>
        <span>
          {report?.settings.stockfish ?? 'engine'}
          {report?.settings.lc0 ? ` + ${report.settings.lc0}` : ''}
          {report?.settings.depth
            ? ` · depth ${report.settings.depth}/${report.settings.focus_depth}`
            : ''}
        </span>
      </footer>
    </div>
  )
}

/**
 * The first candidate that is an actual name.
 *
 * `report.player` is the resolved username in current reports, but a pack built
 * before that fix holds the `--player` argument verbatim — so with `--player me`
 * it is the literal string "me", which must never be shown as a username.
 * `ratings.player` has carried the resolved name all along, so it is the
 * fallback.
 */
function nameOrFallback(...candidates: Array<string | undefined | null>): string {
  for (const value of candidates) {
    const name = (value ?? '').trim()
    if (name && !/^me$/i.test(name)) return name
  }
  return 'player'
}

function NotFound() {
  const { report } = useReport()
  return (
    <div className={styles.centre}>
      <ErrorNote>
        Nothing at that address.
        {'\n\n'}
        {report?.games.length
          ? `Try one of the ${report.games.length} analysed games.`
          : 'This report has no games in it.'}
      </ErrorNote>
    </div>
  )
}