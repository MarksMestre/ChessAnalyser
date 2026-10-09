/**
 * Routing.
 *
 * The plan asks for `.../report.html/games/3`, and the existing guarantee is
 * that `report.html` opens from `file://`. Those two are in tension: the History
 * API does not work on `file://`, so a pretty path is impossible there.
 *
 * Rather than drop either, the router is chosen at runtime — the served app gets
 * real paths, the standalone file gets a hash. Losing the `file://` case
 * silently would be the most likely way this work damages the project, because
 * every existing user opens the report that way.
 */

import { BrowserRouter, HashRouter } from 'react-router-dom'

export const BASENAME = '/report.html/'

/** True when there is no server behind the page. */
export const STANDALONE =
  typeof window !== 'undefined' && window.location.protocol === 'file:'

/**
 * BrowserRouter is only correct over http(s). On `file://` a pushState to
 * `/games/3` throws a SecurityError in most browsers, so the standalone build
 * routes through the hash instead.
 */
export function pickRouter(standalone: boolean) {
  return standalone ? HashRouter : BrowserRouter
}

export function routerProps(standalone: boolean) {
  return { basename: standalone ? '/' : BASENAME }
}

/** Route paths, written once so no page hardcodes a URL. */
export const ROUTES = {
  overview: '/',
  games: '/games',
  game: (id: number | string) => `/games/${id}`,
  play: (id: number | string) => `/games/${id}/play`,
  drill: (id: number | string) => `/games/${id}/drill`,
  exportPage: '/export',
} as const