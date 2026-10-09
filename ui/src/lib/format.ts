/**
 * Formatting helpers shared by every view.
 */

/**
 * Format centipawns as pawns, with a mate sentinel handled separately.
 *
 * analyze.py stores a forced mate as a large number rather than a separate
 * field, and a mate in 3 rendered as "+100.00" would be nonsense — so it is
 * detected and shown as a distance to mate instead.
 */
export function fmtEval(cp: number | null | undefined): string {
  if (cp === null || cp === undefined) return '—'
  // Anything past this is a mate score, not a pawn value.
  if (Math.abs(cp) >= 9000) {
    const mates = Math.round(Math.abs(cp) / 100000)
    if (mates === 0) return cp > 0 ? '#' : '-#'
    return (cp > 0 ? '#' : '-#') + mates
  }
  const pawns = cp / 100
  return (pawns >= 0 ? '+' : '') + pawns.toFixed(2)
}

/**
 * Win probability as a percentage, for bars.
 *
 * The sigmoid and constant are the same ones `engines.win_percent` uses, so a
 * bar drawn here matches the `win_percent_*` fields in data.json exactly. The
 * ×100 is not decoration: the Python version returns percent, and the first
 * draft of this returned a fraction, which put every bar on the wrong side of
 * the board.
 */
export function winPercent(cp: number | null | undefined): number {
  if (cp === null || cp === undefined) return 50
  if (cp >= 9000) return 100
  if (cp <= -9000) return 0
  return (100 / (1 + Math.exp(-0.00368208 * cp)))
}

export function fmtPp(v: number | null | undefined, digits = 1): string {
  if (v === null || v === undefined) return '—'
  return v.toFixed(digits)
}

export function fmtAccuracy(v: number | null | undefined): string {
  if (v === null || v === undefined) return '—'
  return v.toFixed(1)
}

/** A duration in seconds, as `m:ss` or `h:mm:ss`. */
export function fmtDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || !isFinite(seconds)) return '—'
  const total = Math.max(0, Math.round(seconds))
  const h = Math.floor(total / 3600)
  const m = Math.floor((total % 3600) / 60)
  const s = total % 60
  const pad = (n: number) => String(n).padStart(2, '0')
  return h ? `${h}:${pad(m)}:${pad(s)}` : `${m}:${pad(s)}`
}

/** `2021.03.31` or `2021-03-31` → `31 Mar 2021`. Falls back to the input. */
const MONTHS = [
  'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
  'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec',
]

export function fmtDate(raw: string | null | undefined): string {
  if (!raw) return '—'
  const parts = raw.replace(/-/g, '.').trim().split(/[. ]/)
  if (parts.length < 3) return raw
  const [y, m, d] = parts
  const month = Number(m)
  if (!Number.isInteger(month) || month < 1 || month > 12) return raw
  return `${Number(d)} ${MONTHS[month - 1]} ${y}`
}

/** A name reduced to its initials, for the avatar placeholder. */
export function monogram(name: string | null | undefined): string {
  if (!name) return '?'
  const cleaned = name.replace(/[^a-zA-Z0-9]/g, ' ')
  const parts = cleaned.split(/\s+/).filter(Boolean)
  if (!parts.length) return '?'
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase()
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase()
}

/** A player's display name and rating, as `name (1500)`. */
export function nameWithElo(name: string | null | undefined, elo: number | null): string {
  const n = name || 'Unknown'
  return elo === null || elo === undefined ? n : `${n} (${elo})`
}

/** Percentage for a progress bar, clamped to 0..100. */
export function pct(v: number | null | undefined): number {
  if (v === null || v === undefined || !isFinite(v)) return 0
  return Math.max(0, Math.min(100, v))
}