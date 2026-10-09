/**
 * The shape of `data.json`, mirrored as TypeScript.
 *
 * These types describe the *pack* (`report.json` + `games/<n>.json`) rather
 * than the original monolithic `data.json`. The only difference is that
 * `GameSummary` has no `moves` — that is the split the pack exists for, and
 * it is why a 3089-game archive loads in tens of KB instead of ~216 MB.
 */

export type Label =
  | 'brilliant'
  | 'great'
  | 'book'
  | 'best'
  | 'excellent'
  | 'good'
  | 'inaccuracy'
  | 'mistake'
  | 'blunder'
  | 'miss'

export type Phase = 'opening' | 'middlegame' | 'endgame'
export type PlayerColor = 'white' | 'black'
export type PlayerResult = 'win' | 'loss' | 'draw' | string

/** One move, as recorded by analyze.py. */
export interface Move {
  ply: number
  move_number: number
  color: PlayerColor
  san: string
  uci: string
  /** Position *before* the move. */
  fen: string
  /** Position *after* the move. */
  fen_after: string
  is_players_turn: boolean
  phase: Phase

  /** Centipawns, always from the mover's point of view. */
  eval_before: number | null
  eval_after: number | null
  win_percent_before: number | null
  win_percent_after: number | null
  loss_pp: number
  accuracy: number

  label: Label
  glyph: string

  best_san: string | null
  best_uci: string | null
  /** SAN of the engine's principal variation. */
  best_pv: string[]
  best_eval: number | null
  second_san: string | null
  second_uci: string | null
  second_eval: number | null
  /** E1 − E2 in win percent: how unique the best move was. */
  gap_pp: number | null

  in_book: boolean
  left_book: boolean
  /** "uci:san" for every legal move — the player's own plies only. */
  legal: string[]
  /** Material in pawns given up against the best reply, if any. */
  sacrifice: number | null

  depth: number
  verified: boolean
  survey_label: string | null

  lc0_best_uci: string | null
  lc0_best_san: string | null
  lc0_eval: number | null
  lc0_agrees: boolean | null
  lc0_loss_pp: number | null

  notes: string[]
}

/** Everything about a game except its moves. */
export interface GameSummary {
  headers: Record<string, string>
  index: number
  player_color: PlayerColor | null
  player_name: string
  opening: string | null
  eco: string | null
  book_end_ply: number
  accuracy: number
  accuracy_harmonic: number
  accuracy_mean: number
  acpl: number
  phase_accuracy: Partial<Record<Phase, PhaseStats>>
  eval_curve: number[]
  counts: Record<string, number>
  result: string
  player_result: PlayerResult
  analysis_seconds: number
  /** Set when the standalone file did not inline this game's detail. */
  _not_embedded?: boolean
}

/** A game with its moves — what `GET /api/games/<n>` returns. */
export interface GameDetail extends GameSummary {
  moves: Move[]
}

/** One row of the dashboard's per-game table. */
export interface TrendRow {
  index: number
  title: string
  date: string
  opening: string | null
  eco: string | null
  result: PlayerResult
  accuracy: number
  accuracy_mean: number
  acpl: number
  counts: Record<string, number>
  eval_curve: number[]
}

export interface PhaseStats {
  moves: number
  games?: number
  accuracy: number
  acpl: number
  brilliant: number
  great: number
  book: number
  best: number
  excellent: number
  good: number
  inaccuracy: number
  mistake: number
  blunder: number
  miss: number
}

export interface Weakness {
  key: string
  label: string
  count: number
  games: number[]
  examples: string[]
  game_count: number
}

export interface Brilliancy {
  game: number
  title: string
  opening: string | null
  move_number: number
  san: string
  uci: string
  sacrifice: number | null
  loss_pp: number
  fen: string
  fen_after: string
  pv: string[]
  lc0_agrees: boolean | null
}

/** One point on the ELO chart. */
export interface RatingPoint {
  index: number
  date: string
  elo: number
  opponent: string
  opponent_elo: number | null
  accuracy: number
  result: PlayerResult
}

/** Accuracy against a band of opponent strength. */
export interface RatingBucket {
  band: string
  games: number
  accuracy: number | null
}

export interface Ratings {
  player: string
  current: number | null
  first: number | null
  peak: number | null
  low: number | null
  delta: number | null
  games_rated: number
  series: RatingPoint[]
  buckets: RatingBucket[]
}

export interface Totals {
  counts: Record<string, number>
  accuracy_mean: number
  acpl_mean: number
  wins: number
  losses: number
  draws: number
}

export interface Dashboard {
  games: number
  trend: TrendRow[]
  phases: Partial<Record<Phase, PhaseStats>>
  best_games: Array<Pick<GameSummary, 'index' | 'accuracy' | 'result'> & {
    title: string
    opening: string | null
  }>
  worst_games: Array<Pick<GameSummary, 'index' | 'accuracy' | 'result'> & {
    title: string
    opening: string | null
  }>
  weaknesses: Weakness[]
  brilliancies: Brilliancy[]
  totals: Totals
  /** Added in v2. Absent when the pack was built from older data. */
  ratings?: Ratings
  games_index?: GameSummary[]
}

export interface Settings {
  depth?: number
  focus_depth?: number
  stockfish?: string
  stockfish_path?: string
  lc0?: string
  lc0_net?: string
  lc0_nodes?: number
  positions_searched?: number
  cache_hits?: number
  [key: string]: unknown
}

/** `GET /api/report` — the whole index, no move data. */
export interface Report {
  generated: string
  /**
   * The resolved username.
   *
   * Not the `--player` argument: with `--player me` that argument is the
   * literal string `me`, which is what this used to hold and what the header
   * used to print. Empty only when nothing is configured.
   */
  player: string
  /**
   * One entry per platform account, since `--player me` has a different name
   * per site. Absent from a pack built before this existed — the UI falls back
   * to `player` alone rather than failing.
   */
  player_identities?: PlayerIdentity[]
  settings: Settings
  elapsed_seconds: number
  dashboard: Dashboard
  games: GameSummary[]
}

/** `POST /api/analyse` — the server's verdict on a move you played. */
export interface AnalysisResult {
  label: Label
  glyph: string
  san: string
  fen: string
  fen_after: string
  eval_before: number
  eval_after: number
  win_percent_before: number
  win_percent_after: number
  loss_pp: number
  accuracy: number
  best_san: string | null
  best_uci: string | null
  best_pv: string[]
  best_eval: number | null
  second_san: string | null
  second_uci: string | null
  second_eval: number | null
  gap_pp: number | null
  sacrifice: number | null
  depth_reached: number
  movetime_ms: number
  terminated: boolean
  result: string
}

/** `GET /api/health`. */
export interface Health {
  ok: boolean
  stockfish: string | null
  lc0: string | null
  movetime: number
  depth: number
  error: string
}

/** One engine suggestion for a position, as drawn on the board. */
export interface EngineHint {
  rank: number
  uci: string
  san: string
  score_cp: number
  /** "+0.31", or a mate distance like "#2". */
  score_san: string
  /** Win probability for the side to move, 0-100. */
  win_percent: number
  depth: number
  /** The line the engine expects after this move, in SAN. */
  pv: string[]
}

/** `POST /api/hints` — the top N moves for a position, nothing more. */
export interface Hints {
  moves: EngineHint[]
  elapsed_ms: number
  depth_reached: number
  /** Whose move it is in this FEN. */
  turn: 'white' | 'black'
}

/** One platform account, as it appears in the report header. */
export interface PlayerIdentity {
  site: string
  name: string
  /** Games in this report from this site. 0 means configured but unused. */
  games: number
  player_color: PlayerColor | null
}