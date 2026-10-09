/** Small presentational primitives shared across the app. */

import type { ReactNode } from 'react'
import { useId } from 'react'
import { labelMeta, LABEL_CLASS } from '../../lib/labels'
import styles from './ui.module.css'

/* ------------------------------------------------------------------ Panel */

export function Panel({
  title,
  actions,
  children,
  padded = true,
}: {
  title?: ReactNode
  actions?: ReactNode
  children: ReactNode
  padded?: boolean
}) {
  return (
    <section className={styles.panel}>
      {(title || actions) && (
        <header className={styles.panelHead}>
          {typeof title === 'string' ? <h2>{title}</h2> : title}
          {actions && <div className={styles.panelActions}>{actions}</div>}
        </header>
      )}
      <div className={padded ? styles.panelBody : undefined}>{children}</div>
    </section>
  )
}

/* ------------------------------------------------------------------- Stat */

export function Stat({
  label,
  value,
  sub,
  tone,
  onClick,
}: {
  label: string
  value: ReactNode
  sub?: ReactNode
  tone?: string
  onClick?: () => void
}) {
  const content = (
    <>
      <div className={`${styles.statValue} ${tone ?? ''}`}>{value}</div>
      <div className={styles.statLabel}>{label}</div>
      {sub ? <div className={styles.statSub}>{sub}</div> : null}
    </>
  )
  return onClick ? (
    <button className={`${styles.stat} ${styles.statButton}`} onClick={onClick}>
      {content}
    </button>
  ) : (
    <div className={styles.stat}>{content}</div>
  )
}

/* --------------------------------------------------------------- Controls */

export function Button({
  children,
  onClick,
  variant = 'default',
  disabled,
  title,
  active,
  type = 'button',
  className,
}: {
  children: ReactNode
  onClick?: () => void
  variant?: 'default' | 'primary' | 'ghost' | 'danger'
  disabled?: boolean
  title?: string
  active?: boolean
  type?: 'button' | 'submit'
  /** Extra classes, for one-off sizing. */
  className?: string
}) {
  return (
    <button
      type={type}
      className={`${styles.btn} ${styles[`btn_${variant}`]} ${
        active ? styles.btnActive : ''
      } ${className ?? ''}`}
      onClick={onClick}
      disabled={disabled}
      title={title}
      aria-pressed={active}
    >
      {children}
    </button>
  )
}

export function Segmented<T extends string | number>({
  options,
  value,
  onChange,
  ariaLabel,
}: {
  options: Array<{ value: T; label: ReactNode; title?: string }>
  value: T
  onChange: (value: T) => void
  ariaLabel: string
}) {
  return (
    <div className={styles.segmented} role="group" aria-label={ariaLabel}>
      {options.map((opt) => (
        <button
          key={String(opt.value)}
          type="button"
          className={`${styles.segment} ${opt.value === value ? styles.segmentOn : ''}`}
          onClick={() => onChange(opt.value)}
          title={opt.title}
          aria-pressed={opt.value === value}
        >
          {opt.label}
        </button>
      ))}
    </div>
  )
}

export function Tabs<T extends string>({
  tabs,
  value,
  onChange,
}: {
  tabs: Array<{ value: T; label: ReactNode }>
  value: T
  onChange: (value: T) => void
}) {
  return (
    <div className={styles.tabs} role="tablist">
      {tabs.map((tab) => (
        <button
          key={tab.value}
          type="button"
          role="tab"
          aria-selected={tab.value === value}
          className={`${styles.tab} ${tab.value === value ? styles.tabOn : ''}`}
          onClick={() => onChange(tab.value)}
        >
          {tab.label}
        </button>
      ))}
    </div>
  )
}

/** A pill. `tone` maps onto the label colours, so it stays consistent. */
export function Pill({
  children,
  tone,
  title,
}: {
  children: ReactNode
  tone?: string
  title?: string
}) {
  return (
    <span className={`${styles.pill} ${tone ? styles[`pill_${tone}`] : ''}`} title={title}>
      {children}
    </span>
  )
}

/* -------------------------------------------------------------- Badges */

/**
 * A move's classification: glyph plus word.
 *
 * The glyph is not decoration. It is the second channel of information, so the
 * label survives colour blindness and a greyscale screenshot.
 */
export function LabelBadge({
  label,
  glyph,
  size = 'md',
  title,
}: {
  label: string
  glyph?: string
  size?: 'sm' | 'md' | 'lg'
  title?: string
}) {
  const meta = labelMeta(label)
  return (
    <span
      className={`${styles.badge} ${LABEL_CLASS[meta.label as never]} ${styles[`badge_${size}`]}`}
      title={title ?? meta.description}
    >
      {glyph ? <span className={styles.badgeGlyph}>{glyph}</span> : null}
      <span className={styles.badgeText}>{meta.title}</span>
    </span>
  )
}

/** A result as a word, coloured by win/loss/draw. */
export function ResultTag({ result }: { result: string }) {
  const tone =
    result === 'win' ? 'win' : result === 'loss' ? 'loss' : result === 'draw' ? 'draw' : ''
  return (
    <span className={`${styles.result} ${tone ? styles[`result_${tone}`] : ''}`}>
      {result}
    </span>
  )
}

/* -------------------------------------------------------------- Feedback */

export function Spinner({ label = 'Loading' }: { label?: string }) {
  return (
    <div className={styles.spinner} role="status" aria-label={label}>
      <span className={styles.spinnerDot} />
      <span className={styles.spinnerDot} />
      <span className={styles.spinnerDot} />
    </div>
  )
}

/**
 * A skeleton, not a spinner, for content that has a known shape.
 *
 * Waiting on a spinner when the layout is known makes the page jump once the
 * data lands; a placeholder holds the space instead.
 */
export function Skeleton({ height = 16, width = '100%' }: { height?: number; width?: string }) {
  return <div className={styles.skeleton} style={{ height, width }} aria-hidden />
}

export function EmptyState({
  title,
  children,
  action,
}: {
  title: string
  children?: ReactNode
  action?: ReactNode
}) {
  return (
    <div className={styles.empty}>
      <h3>{title}</h3>
      {children ? <div className={styles.emptyBody}>{children}</div> : null}
      {action ? <div className={styles.emptyAction}>{action}</div> : null}
    </div>
  )
}

export function ErrorNote({ children }: { children: ReactNode }) {
  return (
    <div className={styles.error} role="alert">
      {children}
    </div>
  )
}

/* ------------------------------------------------------------------ Misc */

export function Progress({ value }: { value: number }) {
  const clamped = Math.max(0, Math.min(100, value))
  return (
    <div className={styles.progress}>
      <i style={{ width: `${clamped}%` }} />
    </div>
  )
}

/** A labelled text input. */
export function TextInput({
  value,
  onChange,
  placeholder,
  label,
  ariaLabel,
  type = 'search',
}: {
  value: string
  onChange: (value: string) => void
  placeholder?: string
  label?: string
  ariaLabel?: string
  type?: string
}) {
  const id = useId()
  return (
    <div className={styles.field}>
      {label ? (
        <label className={styles.fieldLabel} htmlFor={id}>
          {label}
        </label>
      ) : null}
      <input
        id={id}
        className={styles.input}
        type={type}
        value={value}
        placeholder={placeholder}
        aria-label={ariaLabel ?? label}
        onChange={(e) => onChange(e.target.value)}
      />
    </div>
  )
}