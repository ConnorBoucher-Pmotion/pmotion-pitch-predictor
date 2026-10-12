export type PitchType = string

export interface SituationInput {
  pitcher_id: number
  balls: number
  strikes: number
  outs: number
  inning: number
  stand: 'L' | 'R'
  on_1b: boolean
  on_2b: boolean
  on_3b: boolean
  previous_pitch_type: PitchType | null
  previous_two_pitch_types: PitchType[]
  times_through_order: number
  pitcher_pitch_count: number
}

export interface PitchProbability {
  pitch_type: PitchType
  pitch_name: string
  probability: number
  why: string[]
}

export interface PredictionResult {
  pitcher_id: number
  pitcher_name: string
  situation: SituationInput
  probabilities: PitchProbability[]
  top_pitch: PitchType
  top_probability: number
  baseline_most_common: PitchType
  baseline_most_common_rate: number
  explanation_summary: string
  data_label: string
  model: string
}

export interface ReplayAccuracy {
  total_revealed: number
  correct: number
  accuracy: number
  most_common_baseline_correct: number
  most_common_baseline_accuracy: number
  beats_most_common: boolean
  by_pitch_type: Record<string, { n: number; correct: number }>
}

export interface ReplayState {
  data_label: string
  game_pk: number
  pitcher_id: number
  index: number
  total: number
  paused: boolean
  speed: number
  done: boolean
  revealed: boolean
  situation: SituationInput | null
  prediction: PredictionResult | null
  actual_pitch_type: string | null
  correct: boolean | null
  accuracy: ReplayAccuracy
  current_pa: Array<{
    index: number
    pitch_type: string
    pitch_name: string
    balls: number
    strikes: number
    description?: string
  }>
  pitch_meta: {
    inning: number
    inning_topbot: string
    outs: number
    batter_name: string
    pitcher_name: string
    game_date: string
    pitch_number_in_game: number
  } | null
}

export interface Tendencies {
  pitcher_id: number
  pitcher_name: string
  pitch_count: number
  arsenal: Record<string, number>
  by_strikes: Record<string, Record<string, number>>
  by_count: Record<string, Record<string, number>>
  vs_hand: Record<string, Record<string, number>>
  by_runners: Record<string, Record<string, number>>
  after_pitch: Record<string, Record<string, number>>
  pitch_names: Record<string, string>
  data_label?: string
}

export interface GameInfo {
  game_pk: number
  game_date: string
  pitcher_id: number
  pitcher_name: string
  pitch_count: number
}

export interface ModelPerformance {
  data_label: string
  pitcher_id: number
  pitcher_name: string
  train_pitches: number
  test_pitches: number
  metrics: {
    most_common_pitch: string
    most_common_accuracy: number
    count_only_accuracy?: number | null
    weighted_baseline_accuracy: number
    ml_accuracy?: number | null
    beats_most_common: boolean
    beats_count_only?: boolean
    beats_weighted_baseline?: boolean
  }
  weights: Record<string, number>
  model: string
  ml_status: string
  prediction_log?: {
    total_logged: number
    scored: number
    accuracy: number | null
    by_source: Record<string, { n: number; correct: number }>
    log_path: string
  }
  use_sample_data?: boolean
}

export interface AppConfig {
  default_pitcher_id: number
  default_pitcher_name: string
  default_start_date: string
  default_end_date: string
  default_game_pk: number
  use_sample_data: boolean
  dodgers_starter_ids?: number[]
  prefer_ml_predictions?: boolean
  data_label_note: string
}

export interface LiveState {
  data_label: string
  game_pk: number
  pitcher_id: number
  pitch_count: number
  index: number
  polling: boolean
  status: string | null
  poll_error: string | null
  mode: string
  situation: SituationInput | null
  prediction: PredictionResult | null
  note?: string
}

export interface ScoreboardGame {
  game_pk: number
  game_date?: string | null
  status: string
  abstract_state?: string | null
  bucket: 'Scheduled' | 'Live' | 'Final' | string
  home_team_id?: number | null
  away_team_id?: number | null
  home_team_name?: string | null
  away_team_name?: string | null
  home_score?: number | null
  away_score?: number | null
  inning?: number | null
  inning_half?: string | null
  venue?: string | null
  worker_active?: boolean
  data_label?: string
  away_probable?: string
  home_probable?: string
}

export interface StoredPrediction {
  id: number
  game_pk: number
  at_bat_index: number
  pitch_number: number
  pitcher_id: number
  top1_pitch_type: string
  top2_pitch_type?: string | null
  probabilities: {
    items?: PitchProbability[]
    top_pitch?: string
  }
  prediction_created_at: string | null
  actual_pitch_type: string | null
  top1_correct: boolean | null
  top2_correct: boolean | null
  resolved_at: string | null
  data_label: string
  explanation?: string | null
  timing_proof?: {
    actual_was_null_at_creation: boolean
    prediction_created_at: string | null
    resolved_at: string | null
    created_before_resolve: boolean
  }
}

export interface GameDetail {
  game: ScoreboardGame
  live: {
    status?: string
    abstract_state?: string
    home_score?: number
    away_score?: number
    inning?: number
    inning_half?: string
    balls?: number
    strikes?: number
    outs?: number
    pitcher_id?: number | null
    pitcher_name?: string | null
    batter_id?: number | null
    batter_name?: string | null
    runners?: { on_1b: boolean; on_2b: boolean; on_3b: boolean }
    current_matchup?: Record<string, unknown> | null
    feed_pitch_count?: number
    data_label?: string
    error?: string
  } | null
  worker: Record<string, unknown>
  open_prediction: StoredPrediction | null
  predictions: StoredPrediction[]
  pitches: Array<{
    id: number
    at_bat_index: number
    pitch_number: number
    pitch_type: string
    pitch_name?: string
    pitcher_name?: string
    batter_name?: string
    balls: number
    strikes: number
    outs: number
    inning: number
    inning_half?: string
    description?: string
  }>
  accuracy: {
    resolved: number
    top1_accuracy: number | null
    top2_accuracy: number | null
    open_predictions?: number
  }
  data_label?: string
}

export interface RosterPitcher {
  player_id: number
  full_name: string
  team_id: number
  team_name: string
  team_abbreviation?: string | null
  position?: string | null
  jersey_number?: string | null
  status?: string | null
  data_label: string
}
