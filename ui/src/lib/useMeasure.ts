/**
 * Measure an element, so a chart can size its viewBox to its real box.
 *
 * The reason this exists: the charts used to render a fixed `720x200` viewBox
 * with `preserveAspectRatio="none"` into a `width: 100%` box. That scales x and
 * y independently, so a chart 1800px wide stretched every glyph — tick labels,
 * dots — by 2.3x horizontally. `vector-effect: non-scaling-stroke` fixes stroke
 * *width* and nothing else; text stays squashed.
 *
 * Matching the viewBox to the measured box makes one user unit one CSS pixel,
 * so there is nothing left to distort.
 */

import { useCallback, useEffect, useRef, useState } from 'react'

export interface Size {
  width: number
  height: number
}

/**
 * The measured box, falling back to `fallback` until the first observation.
 *
 * A zero measurement is *ignored* rather than adopted. A panel inside a
 * collapsed container reports `width: 0`, and adopting that would render a
 * chart with no plot area; keeping the previous measurement means the chart
 * reappears correctly the moment it is shown again.
 */
export function useMeasure(fallback: Size): [React.RefObject<HTMLDivElement>, Size] {
  const ref = useRef<HTMLDivElement>(null)
  const [size, setSize] = useState<Size>(fallback)

  const measure = useCallback(() => {
    const el = ref.current
    if (!el) return
    const width = el.clientWidth
    const height = el.clientHeight
    if (width <= 0 || height <= 0) return
    setSize((prev) =>
      prev.width === width && prev.height === height ? prev : { width, height }
    )
  }, [])

  useEffect(() => {
    const el = ref.current
    if (!el) return
    measure()
    // ResizeObserver rather than a window listener: the charts also change size
    // when the sidebar reflows without the window moving.
    if (typeof ResizeObserver === 'undefined') {
      window.addEventListener('resize', measure)
      return () => window.removeEventListener('resize', measure)
    }
    const observer = new ResizeObserver(measure)
    observer.observe(el)
    return () => observer.disconnect()
  }, [measure])

  return [ref, size]
}