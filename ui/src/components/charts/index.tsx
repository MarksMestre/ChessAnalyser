/**
 * The charts, hand-drawn as SVG.
 *
 * A charting library would be a large dependency for four line charts and one
 * bar chart, and each of them needs something specific: a second faint line for
 * the opponent, dots coloured by result, a draw-in on mount. Writing the SVG
 * directly is about the same amount of code and gives exact control.
 *
 * The draw-in uses `stroke-dashoffset`, which is a compositor-friendly property
 * and collapses to nothing under `prefers-reduced-motion`.
 */

import { useId } from 'react'
import { useMeasure } from '../../lib/useMeasure'
import styles from './charts.module.css'

/* ------------------------------------------------------------------ Line */

export interface SeriesPoint {
  x: number
  y: number
  /** Optional label, e.g. a game's result. */
  meta?: string
}

export interface LineChartProps {
  series: SeriesPoint[]
  /** A second, dimmer line — used for the opponent's rating. */
  comparison?: SeriesPoint[]
  width?: number
  height?: number
  yLabel?: string
  /** Dots get this colour when the point is at the extreme. */
  dotTone?: (point: SeriesPoint, index: number) => string
  formatY?: (value: number) => string
  formatX?: (value: number) => string
  /** Repeat an x label only when its value differs from the previous one. */
  dedupeXLabels?: boolean
  /** Force the y-axis to include 0. */
  zeroFloor?: boolean
}

/** The path `d` for a polyline, with a small curve between points. */
function pathFor(points: SeriesPoint[], x: (i: number) => number, y: (v: number) => number) {
  if (!points.length) return ''
  if (points.length === 1) {
    return `M ${x(0)} ${y(points[0].y)}`
  }
  let d = `M ${x(0)} ${y(points[0].y)}`
  for (let i = 1; i < points.length; i += 1) {
    // A gentle cubic: control points at the midpoint, which smooths the line
    // without overshooting the way a Catmull-Rom spline does.
    const prevX = x(i - 1)
    const prevY = y(points[i - 1].y)
    const curX = x(i)
    const curY = y(points[i].y)
    const mid = (prevX + curX) / 2
    d += ` C ${mid} ${prevY}, ${mid} ${curY}, ${curX} ${curY}`
  }
  return d
}

export function LineChart({
  series,
  comparison,
  width = 720,
  height = 200,
  yLabel,
  dotTone,
  formatY = (v) => String(Math.round(v)),
  formatX = (v) => String(Math.round(v)),
  /**
   * Whether two adjacent points share an x value. Chess.com archives are often
   * a handful of games on one day, which would otherwise print the same date
   * three times across the axis — technically true and completely unreadable.
   */
  dedupeXLabels = false,
  zeroFloor = false,
}: LineChartProps) {
  const gradientId = useId()
  /*
   * The viewBox follows the measured box, so one user unit is one CSS pixel.
   *
   * The declared `width`/`height` are the fallback for the first paint, before
   * the ResizeObserver has said anything. A zero measurement is ignored rather
   * than adopted, so a chart inside a collapsed panel keeps its last good size.
   */
  const [wrapRef, measured] = useMeasure({ width, height })
  const w = measured.width
  const h = measured.height

  if (series.length === 0) return null

  const padL = 44
  const padR = 14
  const padT = 12
  const padB = 26
  const plotW = w - padL - padR
  const plotH = h - padT - padB

  const all = comparison?.length ? [...series, ...comparison] : series
  const ys = all.map((p) => p.y)
  const xs = all.map((p) => p.x)
  let yMin = Math.min(...ys)
  let yMax = Math.max(...ys)
  if (zeroFloor) yMin = Math.min(0, yMin)
  // A flat series would divide by zero; give it a visible band instead.
  if (yMax === yMin) {
    yMin -= 1
    yMax += 1
  }
  const pad = (yMax - yMin) * 0.12
  yMin -= pad
  yMax += pad

  const xMin = Math.min(...xs)
  const xMax = Math.max(...xs)
  const xSpan = xMax - xMin || 1

  const xAt = (i: number) => padL + (series[i].x - xMin) / xSpan * plotW
  const yAt = (v: number) => padT + (1 - (v - yMin) / (yMax - yMin)) * plotH
  const xComp = (i: number) =>
    padL + ((comparison?.[i]?.x ?? xMin) - xMin) / xSpan * plotW

  const line = pathFor(series, xAt, yAt)
  const compLine = comparison?.length ? pathFor(comparison, xComp, yAt) : ''

  // Area under the main line, so the trend reads as a quantity not a squiggle.
  const area =
    series.length > 1
      ? `${line} L ${xAt(series.length - 1)} ${padT + plotH} L ${xAt(0)} ${padT + plotH} Z`
      : ''

  const ticks = niceTicks(yMin, yMax, 4)
  // Only label the two ends unless there are very few points: a tick per point
  // on a 47-ply game produces an unreadable axis.
  const xTicks =
    series.length <= 4
      ? series.map((_, i) => i)
      : [0, Math.floor(series.length / 2), series.length - 1]

  // Length of the drawn line, for the draw-in animation.
  const approxLength = Math.max(plotW, 100) * Math.max(1, series.length) * 0.5

  return (
    <div className={styles.chartWrap} ref={wrapRef}>
      <svg
        className={styles.chart}
        viewBox={`0 0 ${w} ${h}`}
        role="img"
        aria-label={yLabel ?? 'line chart'}
      >
        <defs>
          <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="var(--accent)" stopOpacity="0.28" />
            <stop offset="100%" stopColor="var(--accent)" stopOpacity="0.01" />
          </linearGradient>
        </defs>

        {/* gridlines + y labels */}
        {ticks.map((t) => (
          <g key={t}>
            <line
              x1={padL}
              x2={w - padR}
              y1={yAt(t)}
              y2={yAt(t)}
              className={styles.grid}
            />
            <text x={padL - 8} y={yAt(t) + 4} className={styles.tick} textAnchor="end">
              {formatY(t)}
            </text>
          </g>
        ))}

        {xTicks.map((i) => {
          const value = series[i].x
          const repeatsPrevious =
            dedupeXLabels && i > 0 && series[i - 1]?.x === value
          return (
            <text
              key={i}
              x={xAt(i)}
              y={h - 8}
              className={styles.tick}
              textAnchor={i === 0 ? 'start' : i === series.length - 1 ? 'end' : 'middle'}
            >
              {repeatsPrevious ? '' : formatX(value)}
            </text>
          )
        })}

        {area ? <path d={area} fill={`url(#${gradientId})`} /> : null}

        {compLine ? (
          <path
            d={compLine}
            className={styles.comparison}
            pathLength={approxLength}
            style={{ '--draw': approxLength } as React.CSSProperties}
          />
        ) : null}

        <path
          d={line}
          className={styles.line}
          pathLength={approxLength}
          style={{ '--draw': approxLength } as React.CSSProperties}
        />

        {series.map((point, i) => (
          <circle
            key={i}
            cx={xAt(i)}
            cy={yAt(point.y)}
            r={4}
            className={styles.dot}
            fill={dotTone ? dotTone(point, i) : 'var(--accent)'}
          >
            {point.meta ? <title>{point.meta}</title> : null}
          </circle>
        ))}
      </svg>
      {yLabel ? <div className={styles.axisLabel}>{yLabel}</div> : null}
    </div>
  )
}

/* ------------------------------------------------------------- Bar chart */

export interface BarChartProps {
  bars: Array<{ label: string; value: number | null; caption?: string }>
  height?: number
  formatValue?: (v: number) => string
  max?: number
}

export function BarChart({
  bars,
  height = 180,
  formatValue = (v) => v.toFixed(1),
  max,
}: BarChartProps) {
  const values = bars.map((b) => b.value ?? 0)
  const top = max ?? Math.max(100, ...values)
  return (
    <div className={styles.bars}>
      {bars.map((bar) => (
        <div key={bar.label} className={styles.barCol}>
          <div className={styles.barValue}>
            {bar.value === null ? '—' : formatValue(bar.value)}
          </div>
          <div className={styles.barTrack} style={{ height }}>
            <div
              className={styles.barFill}
              style={{
                height: `${bar.value === null ? 0 : Math.max(2, (bar.value / top) * 100)}%`,
              }}
            />
          </div>
          <div className={styles.barLabel}>{bar.label}</div>
          {bar.caption ? <div className={styles.barCaption}>{bar.caption}</div> : null}
        </div>
      ))}
    </div>
  )
}

/* ------------------------------------------------------------- Sparkline */

export function Sparkline({
  values,
  width = 90,
  height = 20,
  tone = 'var(--accent)',
}: {
  values: number[]
  width?: number
  height?: number
  tone?: string
}) {
  if (!values.length) return null
  // Mate sentinels would flatten the whole sparkline, so they are excluded from
  // the range — the same reasoning the eval graph uses.
  const real = values.filter((v) => Math.abs(v) < 9000).map((v) => Math.abs(v) / 100)
  const peak = Math.max(1.5, Math.min(12, real.length ? Math.max(...real) : 1.5))
  const yAt = (v: number) => {
    const p = Math.max(-peak, Math.min(peak, v / 100))
    return Math.max(0, Math.min(height, ((peak - p) / (2 * peak)) * height))
  }
  const xAt = (i: number) => (i * width) / Math.max(1, values.length - 1)
  const d = values
    .map((v, i) => `${i ? 'L' : 'M'} ${xAt(i).toFixed(1)} ${yAt(v).toFixed(1)}`)
    .join(' ')
  const midY = yAt(0)

  return (
    <svg width={width} height={height} className={styles.spark} aria-hidden>
      <line x1={0} y1={midY} x2={width} y2={midY} className={styles.sparkZero} />
      <path d={d} fill="none" stroke={tone} strokeWidth={1.2} />
    </svg>
  )
}

/* ------------------------------------------------------------ Clickable */

/**
 * An eval graph with a selected position, as a scrubbable control.
 *
 * Clicking maps client coordinates to a point index. Kept separate from
 * `LineChart` because this one is interactive and needs hit-testing, while the
 * dashboard charts are not.
 */
export function EvalGraph({
  values,
  selected,
  onSelect,
  labels,
  width = 1000,
  height = 120,
}: {
  values: number[]
  selected: number
  onSelect: (index: number) => void
  labels?: string[]
  width?: number
  height?: number
}) {
  /*
   * Same measured viewBox as LineChart: with `preserveAspectRatio="none"` a
   * fixed viewBox in a wide box stretched the curve's dots into ellipses.
   *
   * The hit-test below depends on this. It maps a client x to a ratio and then
   * multiplies by the viewBox width — correct only when the viewBox and the
   * element are the same size, which is exactly what measuring guarantees.
   */
  const [wrapRef, measured] = useMeasure({ width, height })
  const w = measured.width
  const h = measured.height

  if (values.length === 0) return null
  const pad = 10
  const plotW = w - pad * 2
  const plotH = h - pad * 2
  const real = values.filter((v) => Math.abs(v) < 9000).map((v) => Math.abs(v) / 100)
  const peak = Math.max(1.5, Math.min(12, real.length ? Math.max(...real) : 1.5))
  const xAt = (i: number) => pad + (i * plotW) / Math.max(1, values.length - 1)
  const yAt = (v: number) => {
    const p = Math.max(-peak, Math.min(peak, v / 100))
    return pad + ((peak - p) / (2 * peak)) * plotH
  }
  const midY = yAt(0)

  let d = ''
  values.forEach((v, i) => {
    d += `${i ? ' L' : ' M'} ${xAt(i).toFixed(1)} ${yAt(v).toFixed(1)}`
  })
  const area = `${d} L ${xAt(values.length - 1)} ${midY} L ${xAt(0)} ${midY} Z`

  const handleClick = (event: React.MouseEvent<SVGSVGElement>) => {
    const rect = event.currentTarget.getBoundingClientRect()
    const rel = (event.clientX - rect.left) / rect.width
    const index = Math.round(((rel * w - pad) / plotW) * (values.length - 1))
    if (index >= 0 && index < values.length) onSelect(index)
  }

  return (
    <div className={styles.evalWrap} ref={wrapRef}>
    <svg
      className={styles.evalGraph}
      viewBox={`0 0 ${w} ${h}`}
      onClick={handleClick}
      role="slider"
      aria-label="Evaluation over the game"
      aria-valuenow={selected}
      aria-valuemin={0}
      aria-valuemax={values.length - 1}
    >
      <line x1={pad} x2={w - pad} y1={midY} y2={midY} className={styles.grid} />
      <path d={area} fill="var(--accent)" opacity={0.14} />
      <path d={d} fill="none" stroke="var(--accent)" strokeWidth={1.6} />
      {labels?.map((label, i) =>
        i < values.length && i >= 0 ? (
          <circle key={i} cx={xAt(i)} cy={yAt(values[i])} r={3} fill={DOT[label] ?? 'transparent'} />
        ) : null,
      )}
      {selected >= 0 && selected < values.length ? (
        <line
          x1={xAt(selected)}
          x2={xAt(selected)}
          y1={pad}
          y2={h - pad}
          className={styles.cursor}
        />
      ) : null}
    </svg>
    </div>
  )
}

const DOT: Record<string, string> = {
  brilliant: 'var(--label-brilliant)',
  great: 'var(--label-great)',
  inaccuracy: 'var(--label-inaccuracy)',
  mistake: 'var(--label-mistake)',
  blunder: 'var(--label-blunder)',
  miss: 'var(--label-miss)',
}

/** Round axis bounds to human numbers. */
function niceTicks(min: number, max: number, count: number): number[] {
  const span = max - min
  if (span <= 0) return [min]
  const rawStep = span / count
  const magnitude = 10 ** Math.floor(Math.log10(rawStep))
  const normalised = rawStep / magnitude
  const step =
    (normalised >= 5 ? 5 : normalised >= 2 ? 2 : 1) * magnitude
  const first = Math.ceil(min / step) * step
  const out: number[] = []
  for (let v = first; v <= max + step * 0.001; v += step) {
    out.push(Math.round(v * 1e6) / 1e6)
  }
  return out
}