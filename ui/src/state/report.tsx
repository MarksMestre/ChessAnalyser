/**
 * The report index, and a cache of the per-game files.
 *
 * Split from the per-game view state on purpose: the index is fetched once and
 * never changes, while the selected ply changes on every click. Mixing them
 * would re-render the whole game list on each arrow key.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react'
import type { ReactNode } from 'react'
import { api, ApiError, ApiUnavailable } from '../api/client'
import type { GameDetail, Report } from '../api/types'

interface ReportState {
  report: Report | null
  /** Per-game detail already fetched, keyed by game index. */
  games: Map<number, GameDetail>
  loading: boolean
  error: string | null
  /** Set when the pack is missing, so the UI can print the command to run. */
  needsBuild: boolean
  loadGame: (index: number) => Promise<GameDetail | null>
  reload: () => void
}

const Ctx = createContext<ReportState | null>(null)

export function ReportProvider({ children }: { children: ReactNode }) {
  const [report, setReport] = useState<Report | null>(null)
  const [games, setGames] = useState<Map<number, GameDetail>>(new Map())
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [needsBuild, setNeedsBuild] = useState(false)
  const [nonce, setNonce] = useState(0)

  // In-flight requests, so two components asking for the same game at once
  // produce one fetch rather than two.
  const inFlight = useRef(new Map<number, Promise<GameDetail | null>>())

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    api
      .report()
      .then((data) => {
        if (cancelled) return
        setReport(data)
        setLoading(false)
      })
      .catch((cause: unknown) => {
        if (cancelled) return
        setLoading(false)
        if (cause instanceof ApiError && cause.status === 404) {
          setNeedsBuild(true)
          setError(null)
        } else if (cause instanceof ApiUnavailable) {
          setError(
            'The analysis server is not running. Start it with `python serve.py`.',
          )
        } else {
          setError(cause instanceof Error ? cause.message : String(cause))
        }
      })
    return () => {
      cancelled = true
    }
  }, [nonce])

  const loadGame = useCallback(
    async (index: number): Promise<GameDetail | null> => {
      const cached = games.get(index)
      if (cached) return cached
      const pending = inFlight.current.get(index)
      if (pending) return pending

      const request = api
        .game(index)
        .then((detail) => {
          setGames((prev) => {
            const next = new Map(prev)
            next.set(index, detail)
            return next
          })
          return detail
        })
        .catch(() => null)
        .finally(() => {
          inFlight.current.delete(index)
        })

      inFlight.current.set(index, request)
      return request
    },
    [games],
  )

  const reload = useCallback(() => {
    inFlight.current.clear()
    setGames(new Map())
    setNonce((n) => n + 1)
  }, [])

  const value = useMemo<ReportState>(
    () => ({ report, games, loading, error, needsBuild, loadGame, reload }),
    [report, games, loading, error, needsBuild, loadGame, reload],
  )

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

export function useReport(): ReportState {
  const ctx = useContext(Ctx)
  if (!ctx) throw new Error('useReport must be used inside <ReportProvider>')
  return ctx
}