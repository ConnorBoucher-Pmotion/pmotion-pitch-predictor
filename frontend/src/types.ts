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
