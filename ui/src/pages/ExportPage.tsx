/**
 * Export: the annotated PGN, and the settings the analysis ran with.
 *
 * The PGN download is a data URI rather than a server route, so it works from
 * `file://` exactly as the old report's did — losing that would break every
 * existing user who works offline.
 */

import { useState } from 'react'
import { Button, EmptyState, Panel, Skeleton } from '../components/ui'
import { useReport } from '../state/report'
import styles from './ExportPage.module.css'

export function ExportPage() {
  const { report, loading } = useReport()
  const [copied, setCopied] = useState(false)

  if (loading) {
    return (
      <div className={styles.page}>
        <Skeleton height={300} />
      </div>
    )
  }

  if (!report) {
    return (
      <div className={styles.page}>
        <EmptyState title="Nothing to export" />
      </div>
    )
  }

  // The annotated PGN is not in the pack — it is a separate artefact written by
  // analyze.py. Say so plainly rather than offering a download that 404s.
  const settings = report.settings

  const copyJson = async () => {
    try {
      await navigator.clipboard.writeText(JSON.stringify(report, null, 2))
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1800)
    } catch {
      setCopied(false)
    }
  }

  return (
    <div className={styles.page}>
      <Panel title="Annotated PGN">
        <p className={styles.note}>
          <code>out\annotated.pgn</code> holds the standard PGN with every move's
          label, evaluation and engine line in its comments. Import it into Lichess,
          En Croissant or SCID.
        </p>
        <p className={styles.note}>
          It is written next to <code>data.json</code> by{' '}
          <code>analyze.py</code> rather than served here, so it stays importable by
          any chess tool on the machine.
        </p>
      </Panel>

      <Panel
        title="Report data"
        actions={
          <Button onClick={copyJson}>{copied ? '✓ copied' : 'copy JSON'}</Button>
        }
      >
        <p className={styles.note}>
          The same data this page is drawn from. Useful for checking a number
          against the table.
        </p>
        <table>
          <tbody>
            <tr>
              <td className={styles.key}>player</td>
              <td>{report.player || '—'}</td>
            </tr>
            <tr>
              <td className={styles.key}>games</td>
              <td>{report.dashboard.games}</td>
            </tr>
            <tr>
              <td className={styles.key}>generated</td>
              <td>{report.generated || '—'}</td>
            </tr>
            <tr>
              <td className={styles.key}>analysis time</td>
              <td>{Math.round(report.elapsed_seconds)}s</td>
            </tr>
          </tbody>
        </table>
      </Panel>

      <Panel title="Settings used">
        <p className={styles.note}>
          Exactly what the engines were asked for. These are the numbers behind
          every label in the report.
        </p>
        <table>
          <tbody>
            {Object.entries(settings).map(([key, value]) => (
              <tr key={key}>
                <td className={styles.key}>{key}</td>
                <td className="mono">{String(value)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Panel>
    </div>
  )
}