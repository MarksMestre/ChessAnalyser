/**
 * Fold the built frontend and a report pack into ONE self-contained HTML file.
 *
 * Why this exists
 * ---------------
 * The existing report is one file that opens from `file://`, and that guarantee
 * is load-bearing: every current user opens it that way, on a plane, with no
 * server. The React app is served over HTTP, which would quietly take that away.
 * So the bundle, the CSS and the piece artwork are inlined here, and the router
 * switches to hash mode when it detects a `file://` origin -- see src/router.ts.
 *
 * Run it after `npm run build`:
 *
 *     node ui/scripts/inline-assets.mjs --pack out/pack --out out/report.html
 *
 * The data is inlined as a `<script>` that assigns a global, which is the only
 * shape that survives `file://` without a module/CORS dance.
 */

import { readFileSync, writeFileSync, mkdirSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = dirname(fileURLToPath(import.meta.url))
const UI_DIR = resolve(HERE, '..')
const DIST = join(UI_DIR, 'dist')

/** Minimal argv parsing — no dependency for four flags. */
function parseArgs(argv) {
  const out = { pack: 'out/pack', out: 'out/report.html', embed: 0 }
  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i]
    if (arg === '--pack') out.pack = argv[++i]
    else if (arg === '--out') out.out = argv[++i]
    else if (arg === '--embed-games') out.embed = Number(argv[++i]) || 0
  }
  return out
}

/**
 * Escape a JSON payload for embedding inside a <script> element.
 *
 * The three characters matter for different reasons: `<` would let a game title
 * containing "</script>" close the tag early, and U+2028/U+2029 are line
 * terminators in JavaScript but not in JSON, so a title containing one would
 * produce a syntax error rather than a parseable string.
 */
function safeJson(value) {
  return JSON.stringify(value)
    .replace(/</g, '\\u003c')
    .replace(/>/g, '\\u003e')
    .replace(/\u2028/g, '\\u2028')
    .replace(/\u2029/g, '\\u2029')
}

function fail(message) {
  console.error(`inline-assets: ${message}`)
  process.exit(1)
}

const args = parseArgs(process.argv.slice(2))

let indexHtml
try {
  indexHtml = readFileSync(join(DIST, 'index.html'), 'utf8')
} catch {
  fail(`no build found at ${DIST}. Run: cd ui && npm install && npm run build`)
}

let report
try {
  report = JSON.parse(readFileSync(resolve(args.pack, 'report.json'), 'utf8'))
} catch {
  fail(
    `no report pack at ${args.pack}.\n` +
      `       Build one first: python report.py --pack --out ${args.pack}`,
  )
}

/*
 * Which games carry their move data is decided by the pack, not here:
 * `report.py --pack --embed-games N` writes `inlined` and that is the single
 * place the cap is applied, so there is one rule rather than two that can
 * disagree. `--embed-games` on this script can only lower that cap.
 */
const packed = report.inlined ?? {}
const keys = Object.keys(packed).sort((a, b) => Number(a) - Number(b))
const kept = args.embed > 0 ? keys.slice(0, args.embed) : keys
report.inlined = {}
for (const key of kept) report.inlined[key] = packed[key]

const embeddedGames = kept.length
const embeddedSet = new Set(kept)
for (const entry of report.games ?? []) {
  if (embeddedSet.has(String(entry.index))) delete entry._not_embedded
  else entry._not_embedded = true
}

// The bundle and stylesheet, inlined in place of their <script>/<link> tags.
const assets = [...indexHtml.matchAll(/(?:src|href)="\/report\.html\/assets\/([^"]+)"/g)].map(
  (match) => match[1],
)

let html = indexHtml
const inlinedAssets = []

for (const asset of assets) {
  const path = join(DIST, 'assets', asset)
  let body
  try {
    body = readFileSync(path)
  } catch {
    fail(`dist references ${asset} but it is not on disk. Rebuild the frontend.`)
  }
  inlinedAssets.push(asset)

  /*
   * The replacer is a *function*, deliberately.
   *
   * A string replacement interprets `$&`, `$'` and friends inside the
   * replacement text. The minified bundle contains `$&` — every bundled string
   * helper does — so a string replacer re-inserted the very <script src=...>
   * tag being removed, and the leftover check then correctly reported an asset
   * that would 404 from file://. A function replacer has no such substitution.
   */
  const isCss = asset.endsWith('.css')
  const pattern = isCss
    ? new RegExp(`<link[^>]*href="\\/report\\.html\\/assets\\/${asset}"[^>]*>`)
    : new RegExp(`<script[^>]*src="\\/report\\.html\\/assets\\/${asset}"[^>]*></script>`)

  html = html.replace(pattern, () =>
    isCss
      ? `<style>\n${body.toString('utf8')}\n</style>`
      : `<script type="module">\n${body.toString('utf8')}\n</script>`,
  )
}

/*
 * The data goes in *before* the bundle, so the app's first render already has
 * it. Without this the page would try to fetch /api/report, fail, and render
 * the "no report pack" error on a file that plainly contains one.
 */
const dataScript = `<script>window.__STANDALONE__ = ${safeJson({
    report,
    generated: new Date().toISOString().slice(0, 19),
    embeddedGames,
  })};</script>`

html = html.replace('</head>', () => `  ${dataScript}\n</head>`)

/*
 * Any asset tag that survived the replacement would 404 on file://; fail loudly.
 *
 * The pattern is anchored to a tag so it does not match the *inlined* bundle,
 * which itself contains the string "/report.html/" -- Vite substitutes
 * import.meta.env.BASE_URL into it -- and a looser check reports a false
 * failure on a perfectly good build.
 */
const leftovers = [
  ...new Set(
    [...html.matchAll(/<(?:script|link)\b[^>]*\s(?:src|href)="\/report\.html\/[^"]*"/g)].map(
      (m) => m[0],
    ),
  ),
]
if (leftovers.length) {
  fail(`these assets were not inlined and would 404 from file://: ${leftovers.join(', ')}`)
}

mkdirSync(dirname(resolve(args.out)), { recursive: true })
writeFileSync(resolve(args.out), html, 'utf8')

const kb = (Buffer.byteLength(html) / 1024).toFixed(0)
console.log(`  standalone: ${args.out} (${kb} KB)`)
console.log(`        ${inlinedAssets.length} asset(s) inlined, ${embeddedGames} game(s) embedded`)
if (embeddedGames < (report.games?.length ?? 0)) {
  console.log(
    `        ${(report.games?.length ?? 0) - embeddedGames} game(s) indexed but not embedded;` +
      ' the UI says so rather than showing an empty page',
  )
}
