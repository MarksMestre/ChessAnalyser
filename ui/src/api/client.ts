/**
 * Thin wrappers over the four endpoints `serve.py` exposes.
 *
 * Every call funnels through `request()`, so the handling of "the server is not
 * running" lives in one place. That case is not hypothetical: the standalone
 * single-file build opens from `file://` with no server at all, and play mode
 * has to degrade rather than break there.
 */

import type {
  AnalysisResult,
  GameDetail,
  Health,
  Hints,
  Report,
} from './types'

/** Thrown when the API cannot be reached, so callers can distinguish it. */
export class ApiUnavailable extends Error {
  readonly detail: string
  constructor(message: string, detail = '') {
    super(message)
    this.name = 'ApiUnavailable'
    this.detail = detail
  }
}

/** Thrown when the server answered, but with an error. */
export class ApiError extends Error {
  readonly status: number
  constructor(message: string, status: number) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(path, {
      ...init,
      headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
    })
  } catch (cause) {
    // An aborted request is not a failure to report. The caller cancelled it
    // because the position changed, and ApiUnavailable would make the page
    // claim the server is down when it is answering the next request fine.
    if (init?.signal?.aborted) {
      throw new DOMException('aborted', 'AbortError')
    }
    // fetch only rejects on a network-level failure, which in practice means
    // "no server" — the file:// case, or serve.py not being started yet.
    throw new ApiUnavailable(
      'The analysis server is not reachable.',
      'Start it with `python serve.py`, or use the board in free-play mode.',
    )
  }

  const text = await response.text()
  let payload: unknown = null
  if (text) {
    try {
      payload = JSON.parse(text)
    } catch {
      throw new ApiError(`Malformed response from ${path}`, response.status)
    }
  }

  if (!response.ok) {
    const message =
      payload && typeof payload === 'object' && 'error' in payload
        ? String((payload as { error: unknown }).error)
        : `${response.status} ${response.statusText}`
    throw new ApiError(message, response.status)
  }
  return payload as T
}

/**
 * True when a request to the API cannot possibly work.
 *
 * On `file://` the origin is `null` and every fetch is blocked by CORS, so the
 * attempt is guaranteed to fail and logs a console error. A standalone report
 * is read straight from the embedded payload instead, which is what keeps the
 * "opens with no console errors" guarantee the plan calls for.
 */
const apiUnreachable =
  typeof window !== 'undefined' && window.location.protocol === 'file:'

export const api = {
  /**
   * The report index.
   *
   * The API is tried first and the embedded payload is the fallback, so the same
   * code serves both modes and a standalone file opened next to a running server
   * still gets the live data.
   */
  report: async (): Promise<Report> => {
    const baked = embedded()
    if (baked) {
      if (apiUnreachable) return baked.report
      try {
        return await request<Report>('/api/report')
      } catch {
        return baked.report
      }
    }
    return request<Report>('/api/report')
  },

  /** One game's move list. Falls back to the embedded copy when there is one. */
  game: async (index: number): Promise<GameDetail> => {
    const baked = embedded()
    if (baked) {
      const detail = baked.report.inlined?.[String(index)]
      if (!apiUnreachable) {
        try {
          return await request<GameDetail>(`/api/games/${index}`)
        } catch {
          /* fall through to the embedded copy */
        }
      }
      if (detail) return detail
      throw new ApiError(
        `This game is not embedded in this file. It came from a single-file build ` +
          `carrying only ${baked.embeddedGames} game(s); run \`python serve.py\` for the ` +
          `full archive.`,
        404,
      )
    }
    return request<GameDetail>(`/api/games/${index}`)
  },

  health: (): Promise<Health> => request<Health>('/api/health'),

  analyse: (body: {
    fen: string
    uci: string
    depth?: number
    movetime?: number
  }): Promise<AnalysisResult> =>
    request<AnalysisResult>('/api/analyse', {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  /**
   * The top moves for a position, with no move of yours involved.
   *
   * Deliberately not an extension of `analyse`: that endpoint scores *your*
   * move, which needs the position before and after it — two searches. This
   * needs one, and it is called on every position you pass through, so the
   * difference is the whole cost of the feature.
   */
  hints: (body: { fen: string; multipv?: number }, signal?: AbortSignal): Promise<Hints> =>
    request<Hints>('/api/hints', {
      method: 'POST',
      body: JSON.stringify(body),
      signal,
    }),
}

/**
 * Data baked into a standalone file by `ui/scripts/inline-assets.mjs`.
 *
 * The single-file build has no server to talk to, so the report is read from
 * here instead of from `/api/report`. Present only in that build.
 */
export interface StandalonePayload {
  report: Report & { inlined?: Record<string, GameDetail> }
  generated: string
  embeddedGames: number
}

export function embedded(): StandalonePayload | null {
  const payload = (window as unknown as { __STANDALONE__?: StandalonePayload })
    .__STANDALONE__
  return payload && payload.report ? payload : null
}

/**
 * True when there is no server behind the page.
 *
 * Both signals are checked: the protocol, and the presence of embedded data.
 * A page opened as `file://` in a browser that somehow *does* have a server
 * reachable still works, because the API path is tried first.
 */
export const isStandalone =
  typeof window !== 'undefined' &&
  (window.location.protocol === 'file:' || embedded() !== null)