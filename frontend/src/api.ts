import type {
  AppConfig,
  GameDetail,
  GameInfo,
  LiveState,
  ModelPerformance,
  PredictionResult,
  ReplayState,
  RosterPitcher,
  ScoreboardGame,
  SituationInput,
  Tendencies,
} from './types'

const API_BASE = (import.meta.env.VITE_API_BASE_URL || '').replace(/\/$/, '')

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...(init?.headers || {}) },
    ...init,
  })
  if (!res.ok) {
    let detail = res.statusText
    try {
      const body = await res.json()
      detail = body?.detail?.detail || body?.detail || JSON.stringify(body)
    } catch {
      /* keep statusText */
    }
    throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail))
  }
  return res.json() as Promise<T>
}

export const api = {
  health: () => request<{ status: string }>('/api/health'),
  config: () => request<AppConfig>('/api/config'),
  tendencies: (pitcherId: number) =>
    request<Tendencies>(`/api/pitchers/${pitcherId}/tendencies`),
  games: (pitcherId: number) =>
    request<{ games: GameInfo[] }>(`/api/pitchers/${pitcherId}/games`),
  starters: () =>
    request<{ starters: Array<{ pitcher_id: number; pitcher_name?: string; pitch_count?: number; error?: string }> }>(
      '/api/pitchers/starters',
    ),
  predict: (situation: SituationInput, weights?: Record<string, number>, model?: string) =>
    request<PredictionResult>('/api/predict', {
      method: 'POST',
      body: JSON.stringify({ situation, weights, model }),
    }),
  replayStart: (gamePk: number, pitcherId?: number) =>
    request<ReplayState>('/api/replay/start', {
      method: 'POST',
      body: JSON.stringify({ game_pk: gamePk, pitcher_id: pitcherId }),
    }),
  replayState: () => request<ReplayState>('/api/replay/state'),
  replayControl: (action: string, speed?: number) =>
    request<ReplayState>('/api/replay/control', {
      method: 'POST',
      body: JSON.stringify({ action, speed }),
    }),
  evaluate: (gamePk: number, pitcherId?: number) =>
    request<Record<string, unknown>>(
      `/api/replay/evaluate?game_pk=${gamePk}${pitcherId ? `&pitcher_id=${pitcherId}` : ''}`,
    ),
  liveStart: (gamePk: number, pitcherId?: number) =>
    request<LiveState>('/api/live/start', {
      method: 'POST',
      body: JSON.stringify({ game_pk: gamePk, pitcher_id: pitcherId }),
    }),
  liveState: () => request<LiveState>('/api/live/state'),
  liveControl: (action: string) =>
    request<LiveState>('/api/live/control', {
      method: 'POST',
      body: JSON.stringify({ action }),
    }),
  liveSchedule: (date: string, teamId = 119) =>
    request<{ games: Array<{ game_pk: number; status?: string; home?: string; away?: string }> }>(
      `/api/live/schedule?date=${date}&team_id=${teamId}`,
    ),
  modelPerformance: (pitcherId?: number) =>
    request<ModelPerformance>(
      `/api/model/performance${pitcherId ? `?pitcher_id=${pitcherId}` : ''}`,
    ),
  trainModel: (pitcherId?: number) =>
    request<Record<string, unknown>>(
      `/api/model/train${pitcherId ? `?pitcher_id=${pitcherId}` : ''}`,
      { method: 'POST' },
    ),

  // Milestone 1 platform
  scheduleToday: (day?: string) =>
    request<{ date: string; games: ScoreboardGame[]; live_workers: string[]; data_label: string; note?: string }>(
      `/api/schedule/today${day ? `?day=${day}` : ''}`,
    ),
  gameDetail: (gamePk: number) => request<GameDetail>(`/api/games/${gamePk}`),
  trackGame: (gamePk: number) =>
    request<{ worker: Record<string, unknown> }>(`/api/games/${gamePk}/track`, { method: 'POST' }),
  rosterPitchers: (opts?: { team_id?: number; q?: string; sync?: boolean }) => {
    const params = new URLSearchParams()
    if (opts?.team_id) params.set('team_id', String(opts.team_id))
    if (opts?.q) params.set('q', opts.q)
    if (opts?.sync) params.set('sync', 'true')
    const qs = params.toString()
    return request<{ pitchers: RosterPitcher[]; count: number; data_label: string }>(
      `/api/pitchers${qs ? `?${qs}` : ''}`,
    )
  },
  accuracy: (gamePk?: number) =>
    request<{ resolved: number; top1_accuracy: number | null; top2_accuracy: number | null }>(
      `/api/accuracy${gamePk ? `?game_pk=${gamePk}` : ''}`,
    ),
  timingProof: (gamePk?: number) =>
    request<{ count: number; all_proof_ok: boolean; items: unknown[]; rule: string }>(
      `/api/predictions/timing-proof${gamePk ? `?game_pk=${gamePk}` : ''}`,
    ),
  startHistoricalDemo: (gamePk: number, stepDelaySec = 1.2) =>
    request<Record<string, unknown>>('/api/demo/historical-live', {
      method: 'POST',
      body: JSON.stringify({ game_pk: gamePk, step_delay_sec: stepDelaySec }),
    }),
  demoStatus: () => request<Record<string, unknown>>('/api/demo/historical-live'),
  stopDemo: () => request<Record<string, unknown>>('/api/demo/historical-live/stop', { method: 'POST' }),
}
