import { useEffect, useMemo, useState } from 'react'
import { api } from '../api'
import { ProbabilityBars } from '../components/ProbabilityBars'
import type {
  AppConfig,
  GameInfo,
  LiveState,
  ModelPerformance,
  PredictionResult,
  ReplayState,
  SituationInput,
  Tendencies,
} from '../types'

type Tab = 'live' | 'replay' | 'analysis' | 'model'

const PITCH_OPTIONS = ['FF', 'ST', 'CU', 'FS', 'FC', 'SL', 'CH', 'SI']

function defaultSituation(pitcherId: number): SituationInput {
  return {
    pitcher_id: pitcherId,
    balls: 0,
    strikes: 0,
    outs: 0,
    inning: 1,
    stand: 'R',
    on_1b: false,
    on_2b: false,
    on_3b: false,
    previous_pitch_type: null,
    previous_two_pitch_types: [],
    times_through_order: 1,
    pitcher_pitch_count: 0,
  }
}

function pct(n?: number | null) {
  if (n == null || Number.isNaN(n)) return '—'
  return `${(n * 100).toFixed(1)}%`
}

export default function LegacyLab() {
  const [tab, setTab] = useState<Tab>('replay')
  const [config, setConfig] = useState<AppConfig | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  const [situation, setSituation] = useState<SituationInput>(defaultSituation(808967))
  const [prediction, setPrediction] = useState<PredictionResult | null>(null)
  const [prevPitch, setPrevPitch] = useState<string>('')
  const [liveMode, setLiveMode] = useState<'manual' | 'mlb'>('manual')
  const [liveGamePk, setLiveGamePk] = useState<number>(0)
  const [liveState, setLiveState] = useState<LiveState | null>(null)

  const [games, setGames] = useState<GameInfo[]>([])
  const [gamePk, setGamePk] = useState<number>(745545)
  const [replay, setReplay] = useState<ReplayState | null>(null)
  const [evalReport, setEvalReport] = useState<Record<string, unknown> | null>(null)

  const [tendencies, setTendencies] = useState<Tendencies | null>(null)
  const [perf, setPerf] = useState<ModelPerformance | null>(null)

  const pitcherId = config?.default_pitcher_id ?? 808967

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        setLoading(true)
        const cfg = await api.config()
        if (cancelled) return
        setConfig(cfg)
        setSituation(defaultSituation(cfg.default_pitcher_id))
        setGamePk(cfg.default_game_pk)
        const [g, t, p] = await Promise.all([
          api.games(cfg.default_pitcher_id),
          api.tendencies(cfg.default_pitcher_id),
          api.modelPerformance(cfg.default_pitcher_id),
        ])
        if (cancelled) return
        setGames(g.games)
        if (g.games.length) {
          const ids = new Set(g.games.map((x) => x.game_pk))
          if (!ids.has(cfg.default_game_pk)) {
            setGamePk(g.games[0].game_pk)
          }
        }
        setTendencies(t)
        setPerf(p)
        setError(null)
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e))
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])

  const arsenalList = useMemo(
    () => (tendencies ? Object.entries(tendencies.arsenal).sort((a, b) => b[1] - a[1]) : []),
    [tendencies],
  )

  async function runPredict() {
    try {
      setError(null)
      const sit = {
        ...situation,
        pitcher_id: pitcherId,
        previous_pitch_type: prevPitch || null,
        previous_two_pitch_types: prevPitch ? [prevPitch] : [],
      }
      const result = await api.predict(sit)
      setPrediction(result)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  async function startReplay() {
    try {
      setError(null)
      const state = await api.replayStart(gamePk, pitcherId)
      setReplay(state)
      setEvalReport(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  async function control(action: string, speed?: number) {
    try {
      setError(null)
      const state = await api.replayControl(action, speed)
      setReplay(state)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  async function runEval() {
    try {
      setError(null)
      const report = await api.evaluate(gamePk, pitcherId)
      setEvalReport(report)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  async function startMlbLive() {
    try {
      setError(null)
      if (!liveGamePk) throw new Error('Enter an MLB game_pk to start live feed')
      const state = await api.liveStart(liveGamePk, pitcherId)
      setLiveState(state)
      setLiveMode('mlb')
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  async function refreshLive() {
    try {
      setError(null)
      const state = await api.liveControl('refresh')
      setLiveState(state)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  async function retrain() {
    try {
      setError(null)
      await api.trainModel(pitcherId)
      const p = await api.modelPerformance(pitcherId)
      setPerf(p)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  const dataBadge =
    config?.use_sample_data === false ? 'Statcast cache / download' : 'Sample / fallback'

  return (
    <div className="app-shell">
      <header className="brand-bar">
        <div className="brand-left">
          <img className="brand-logo" src={`${import.meta.env.BASE_URL}dodgers-logo.svg`} alt="Los Angeles Dodgers" />
          <div className="brand-mark">
            <div className="eyebrow">PMOTION · LAD</div>
            <h1>
              PITCH PREDICTION <span>ENGINE</span>
            </h1>
          </div>
        </div>
        <div className="brand-meta">
          <div>{config?.default_pitcher_name ?? 'Loading pitcher…'}</div>
          <div>
            ID {pitcherId} · {config?.default_start_date} → {config?.default_end_date}
          </div>
          <div className="data-badge">{dataBadge}</div>
        </div>
      </header>

      <nav className="tabs">
        {(
          [
            ['live', 'Live'],
            ['replay', 'Replay'],
            ['analysis', 'Pitcher Analysis'],
            ['model', 'Model Performance'],
          ] as const
        ).map(([id, label]) => (
          <button
            key={id}
            className={tab === id ? 'active' : ''}
            onClick={() => setTab(id)}
            type="button"
          >
            {label}
          </button>
        ))}
      </nav>

      {error && <div className="error-banner">API error: {error}</div>}
      {loading && <div className="loading">Loading pitcher data…</div>}

      {tab === 'live' && (
        <section className="panel">
          <div className="section" style={{ marginBottom: '1rem' }}>
            <h2>Live modes</h2>
            <p className="sub">
              MLB Stats API/GUMBO is real live. Manual mode is labeled mock. Replay stays on the Replay
              tab.
            </p>
            <div className="btn-row">
              <button
                className={liveMode === 'manual' ? 'primary' : 'ghost'}
                type="button"
                onClick={() => setLiveMode('manual')}
              >
                Manual (mocked)
              </button>
              <button
                className={liveMode === 'mlb' ? 'primary' : 'ghost'}
                type="button"
                onClick={() => setLiveMode('mlb')}
              >
                MLB live feed
              </button>
            </div>
          </div>

          {liveMode === 'mlb' ? (
            <div className="grid-2">
              <div className="section">
                <h2>MLB live session</h2>
                <div className="data-badge live">data_label: live_mlb_stats_api</div>
                <div className="field-grid" style={{ marginTop: '0.75rem' }}>
                  <label>
                    Game PK
                    <input
                      type="number"
                      value={liveGamePk || ''}
                      onChange={(e) => setLiveGamePk(Number(e.target.value))}
                      placeholder="e.g. 775300"
                    />
                  </label>
                </div>
                <div className="btn-row">
                  <button className="primary" type="button" onClick={startMlbLive}>
                    Start live
                  </button>
                  <button className="ghost" type="button" onClick={refreshLive}>
                    Refresh / poll now
                  </button>
                  <button
                    className="ghost"
                    type="button"
                    onClick={async () => {
                      try {
                        setLiveState(await api.liveControl('log_current'))
                      } catch (e) {
                        setError(e instanceof Error ? e.message : String(e))
                      }
                    }}
                  >
                    Log prediction vs actual
                  </button>
                </div>
                {liveState && (
                  <p className="sub" style={{ marginTop: '0.85rem' }}>
                    Status: {liveState.status ?? '—'} · pitches seen: {liveState.pitch_count} ·
                    polling: {liveState.polling ? 'on' : 'off'}
                    {liveState.poll_error ? ` · error: ${liveState.poll_error}` : ''}
                  </p>
                )}
                {liveState?.note && <p className="sub">{liveState.note}</p>}
              </div>
              <div className="section">
                <h2>Live prediction</h2>
                {!liveState?.prediction && (
                  <div className="loading">Start a live game_pk (in-progress MLB game) to predict.</div>
                )}
                {liveState?.prediction && (
                  <>
                    <div className="data-badge live">{liveState.prediction.data_label}</div>
                    <p style={{ margin: '0.75rem 0' }}>{liveState.prediction.explanation_summary}</p>
                    <ProbabilityBars probabilities={liveState.prediction.probabilities} />
                  </>
                )}
              </div>
            </div>
          ) : (
            <div className="grid-2">
              <div className="section">
                <h2>Game situation</h2>
                <p className="sub">Manual situation builder — mocked live, not an MLB feed.</p>
                <div className="data-badge" style={{ marginBottom: '0.85rem' }}>
                  Mode: mocked live (manual)
                </div>
                <div className="field-grid">
                  <label>
                    Balls
                    <select
                      value={situation.balls}
                      onChange={(e) =>
                        setSituation((s) => ({ ...s, balls: Number(e.target.value) }))
                      }
                    >
                      {[0, 1, 2, 3].map((n) => (
                        <option key={n} value={n}>
                          {n}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label>
                    Strikes
                    <select
                      value={situation.strikes}
                      onChange={(e) =>
                        setSituation((s) => ({ ...s, strikes: Number(e.target.value) }))
                      }
                    >
                      {[0, 1, 2].map((n) => (
                        <option key={n} value={n}>
                          {n}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label>
                    Outs
                    <select
                      value={situation.outs}
                      onChange={(e) =>
                        setSituation((s) => ({ ...s, outs: Number(e.target.value) }))
                      }
                    >
                      {[0, 1, 2].map((n) => (
                        <option key={n} value={n}>
                          {n}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label>
                    Inning
                    <input
                      type="number"
                      min={1}
                      max={15}
                      value={situation.inning}
                      onChange={(e) =>
                        setSituation((s) => ({ ...s, inning: Number(e.target.value) }))
                      }
                    />
                  </label>
                  <label>
                    Batter side
                    <select
                      value={situation.stand}
                      onChange={(e) =>
                        setSituation((s) => ({
                          ...s,
                          stand: e.target.value as 'L' | 'R',
                        }))
                      }
                    >
                      <option value="R">RHB</option>
                      <option value="L">LHB</option>
                    </select>
                  </label>
                  <label>
                    Previous pitch
                    <select value={prevPitch} onChange={(e) => setPrevPitch(e.target.value)}>
                      <option value="">None (first pitch)</option>
                      {PITCH_OPTIONS.map((p) => (
                        <option key={p} value={p}>
                          {p}
                        </option>
                      ))}
                    </select>
                  </label>
                </div>
                <div className="checks">
                  {(
                    [
                      ['on_1b', '1B'],
                      ['on_2b', '2B'],
                      ['on_3b', '3B'],
                    ] as const
                  ).map(([key, label]) => (
                    <label key={key}>
                      <input
                        type="checkbox"
                        checked={situation[key]}
                        onChange={(e) =>
                          setSituation((s) => ({ ...s, [key]: e.target.checked }))
                        }
                      />
                      {label}
                    </label>
                  ))}
                </div>
                <div className="btn-row">
                  <button className="primary" type="button" onClick={runPredict}>
                    Predict next pitch
                  </button>
                </div>
              </div>
              <div className="section">
                <h2>Next pitch probabilities</h2>
                <p className="sub">ML preferred when trained; otherwise weighted baseline.</p>
                {!prediction && <div className="loading">Set a situation and predict.</div>}
                {prediction && (
                  <>
                    <div className="data-badge">{prediction.data_label} · {prediction.model}</div>
                    <p style={{ margin: '0.75rem 0' }}>{prediction.explanation_summary}</p>
                    <ProbabilityBars probabilities={prediction.probabilities} />
                    <div className="why">
                      <strong>WHY — {prediction.probabilities[0]?.pitch_name}</strong>
                      <ul>
                        {(prediction.probabilities[0]?.why || []).map((w) => (
                          <li key={w}>{w}</li>
                        ))}
                      </ul>
                    </div>
                  </>
                )}
              </div>
            </div>
          )}
        </section>
      )}

      {tab === 'replay' && (
        <section className="panel">
          <div className="section" style={{ marginBottom: '1rem' }}>
            <h2>Historical game replay</h2>
            <p className="sub">
              Pitch-by-pitch replay. Upcoming pitch stays hidden until reveal. Predictions are logged.
            </p>
            <div className="field-grid">
              <label>
                Game
                <select value={gamePk} onChange={(e) => setGamePk(Number(e.target.value))}>
                  {games.map((g) => (
                    <option key={g.game_pk} value={g.game_pk}>
                      {g.game_date} · {g.game_pk} ({g.pitch_count} pitches)
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Replay speed
                <select
                  value={replay?.speed ?? 1}
                  onChange={(e) => control('set_speed', Number(e.target.value))}
                >
                  <option value={0.5}>0.5x</option>
                  <option value={1}>1x</option>
                  <option value={2}>2x</option>
                </select>
              </label>
            </div>
            <div className="btn-row">
              <button className="primary" type="button" onClick={startReplay}>
                Load game
              </button>
              <button className="ghost" type="button" onClick={() => control('start')}>
                Start
              </button>
              <button className="ghost" type="button" onClick={() => control('pause')}>
                Pause
              </button>
              <button className="ghost" type="button" onClick={() => control('reveal')}>
                Reveal
              </button>
              <button className="ghost" type="button" onClick={() => control('next')}>
                Next
              </button>
              <button className="ghost" type="button" onClick={() => control('previous')}>
                Previous
              </button>
              <button className="danger" type="button" onClick={() => control('reset')}>
                Reset
              </button>
              <button className="ghost" type="button" onClick={runEval}>
                Entire game evaluation
              </button>
            </div>
          </div>

          {replay && (
            <>
              <div className="stat-tiles">
                <div className="stat-tile">
                  <div className="label">Pitch</div>
                  <div className="value">
                    {Math.min(replay.index + 1, replay.total)}/{replay.total}
                  </div>
                </div>
                <div className="stat-tile">
                  <div className="label">Model accuracy</div>
                  <div className={`value ${replay.accuracy.beats_most_common ? 'ok' : ''}`}>
                    {pct(replay.accuracy.accuracy)}
                  </div>
                </div>
                <div className="stat-tile">
                  <div className="label">Most-common baseline</div>
                  <div className="value">{pct(replay.accuracy.most_common_baseline_accuracy)}</div>
                </div>
                <div className="stat-tile">
                  <div className="label">Beats baseline?</div>
                  <div className={`value ${replay.accuracy.beats_most_common ? 'ok' : 'bad'}`}>
                    {replay.accuracy.total_revealed === 0
                      ? '—'
                      : replay.accuracy.beats_most_common
                        ? 'YES'
                        : 'NO'}
                  </div>
                </div>
              </div>

              <div className="grid-2">
                <div className="section">
                  <h2>Current situation</h2>
                  <div className="data-badge">{replay.data_label}</div>
                  {replay.pitch_meta && (
                    <p style={{ margin: '0.75rem 0' }}>
                      {replay.pitch_meta.game_date} · {replay.pitch_meta.inning_topbot}{' '}
                      {replay.pitch_meta.inning} · {replay.pitch_meta.outs} outs · vs{' '}
                      {replay.pitch_meta.batter_name}
                    </p>
                  )}
                  {replay.situation && (
                    <p className="sub">
                      Count {replay.situation.balls}-{replay.situation.strikes} · stand{' '}
                      {replay.situation.stand} · prev{' '}
                      {replay.situation.previous_pitch_type ?? '—'} · TTO{' '}
                      {replay.situation.times_through_order}
                    </p>
                  )}
                  <h2 style={{ marginTop: '1rem' }}>Current PA</h2>
                  <div className="pa-pills">
                    {replay.current_pa.length === 0 && (
                      <span className="loading">No pitches revealed in this PA yet</span>
                    )}
                    {replay.current_pa.map((p) => (
                      <span className="pa-pill" key={p.index}>
                        {p.pitch_type}
                      </span>
                    ))}
                  </div>
                  {replay.revealed && (
                    <div className="reveal-flash" style={{ marginTop: '1rem' }}>
                      Actual:{' '}
                      <strong style={{ color: replay.correct ? 'var(--ok)' : 'var(--danger)' }}>
                        {replay.actual_pitch_type}
                      </strong>{' '}
                      · Prediction {replay.correct ? 'correct' : 'miss'}
                    </div>
                  )}
                </div>
                <div className="section">
                  <h2>Prediction</h2>
                  {replay.prediction ? (
                    <>
                      <p style={{ marginTop: 0 }}>{replay.prediction.explanation_summary}</p>
                      <ProbabilityBars
                        probabilities={replay.prediction.probabilities}
                        highlight={replay.actual_pitch_type}
                      />
                      <div className="why">
                        <strong>WHY</strong>
                        <ul>
                          {(replay.prediction.probabilities[0]?.why || []).map((w) => (
                            <li key={w}>{w}</li>
                          ))}
                        </ul>
                      </div>
                    </>
                  ) : (
                    <div className="loading">Replay complete.</div>
                  )}
                </div>
              </div>
            </>
          )}

          {evalReport && (
            <div className="section" style={{ marginTop: '1rem' }}>
              <h2>Entire game evaluation</h2>
              <div className="data-badge">{String(evalReport.data_label)}</div>
              <pre
                style={{
                  margin: '0.75rem 0 0',
                  fontFamily: 'var(--font-mono)',
                  fontSize: '0.78rem',
                  whiteSpace: 'pre-wrap',
                  color: 'var(--muted)',
                }}
              >
                {JSON.stringify(evalReport.metrics, null, 2)}
              </pre>
            </div>
          )}
        </section>
      )}

      {tab === 'analysis' && tendencies && (
        <section className="panel grid-2">
          <div className="section">
            <h2>Arsenal — {tendencies.pitcher_name}</h2>
            <p className="sub">{tendencies.pitch_count} pitches · {tendencies.data_label}</p>
            <table className="rate-table">
              <thead>
                <tr>
                  <th>Pitch</th>
                  <th>Usage</th>
                </tr>
              </thead>
              <tbody>
                {arsenalList.map(([pt, rate]) => (
                  <tr key={pt}>
                    <td>
                      {pt} · {tendencies.pitch_names[pt] || pt}
                    </td>
                    <td>{(rate * 100).toFixed(1)}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="section">
            <h2>By count / hand / runners</h2>
            <p className="sub">Slices consumed by the weighted baseline.</p>
            <table className="rate-table">
              <thead>
                <tr>
                  <th>Slice</th>
                  <th>Top pitch</th>
                  <th>Rate</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(tendencies.by_count)
                  .slice(0, 8)
                  .map(([k, rates]) => {
                    const top = Object.entries(rates).sort((a, b) => b[1] - a[1])[0]
                    return (
                      <tr key={`c-${k}`}>
                        <td>Count {k}</td>
                        <td>{top?.[0]}</td>
                        <td>{((top?.[1] || 0) * 100).toFixed(0)}%</td>
                      </tr>
                    )
                  })}
                {Object.entries(tendencies.vs_hand).map(([k, rates]) => {
                  const top = Object.entries(rates).sort((a, b) => b[1] - a[1])[0]
                  return (
                    <tr key={`h-${k}`}>
                      <td>vs {k}HB</td>
                      <td>{top?.[0]}</td>
                      <td>{((top?.[1] || 0) * 100).toFixed(0)}%</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {tab === 'model' && perf && (
        <section className="panel">
          <div className="stat-tiles">
            <div className="stat-tile">
              <div className="label">ML accuracy</div>
              <div className={`value ${perf.metrics.beats_most_common ? 'ok' : ''}`}>
                {pct(perf.metrics.ml_accuracy)}
              </div>
            </div>
            <div className="stat-tile">
              <div className="label">Weighted baseline</div>
              <div className="value">{pct(perf.metrics.weighted_baseline_accuracy)}</div>
            </div>
            <div className="stat-tile">
              <div className="label">Count-only</div>
              <div className="value">{pct(perf.metrics.count_only_accuracy)}</div>
            </div>
            <div className="stat-tile">
              <div className="label">Most-common</div>
              <div className="value">{pct(perf.metrics.most_common_accuracy)}</div>
            </div>
          </div>
          <div className="grid-2">
            <div className="section">
              <h2>Chronological holdout</h2>
              <p className="sub">
                {perf.ml_status} · train {perf.train_pitches} / test {perf.test_pitches}
              </p>
              <div className="data-badge">{perf.data_label}</div>
              <div className="compare-bars" style={{ marginTop: '1rem' }}>
                {(
                  [
                    ['ML (sklearn RF)', perf.metrics.ml_accuracy],
                    ['Weighted baseline', perf.metrics.weighted_baseline_accuracy],
                    ['Count-only', perf.metrics.count_only_accuracy],
                    [`Most-common (${perf.metrics.most_common_pitch})`, perf.metrics.most_common_accuracy],
                  ] as const
                ).map(([label, value]) => (
                  <div className="compare-row" key={label}>
                    <div className="name" style={{ fontFamily: 'var(--font-mono)', fontSize: '0.78rem' }}>
                      {label}
                    </div>
                    <div className="bar-track">
                      <div
                        className={`bar-fill ${label.startsWith('ML') ? 'top' : ''}`}
                        style={{ width: `${Math.max((value || 0) * 100, 2)}%` }}
                      />
                    </div>
                    <div className="pct">{pct(value)}</div>
                  </div>
                ))}
              </div>
              <div className="btn-row">
                <button className="primary" type="button" onClick={retrain}>
                  Retrain ML model
                </button>
              </div>
              <p className="sub" style={{ marginTop: '0.75rem' }}>
                Beats most-common: {perf.metrics.beats_most_common ? 'YES' : 'NO'} · count-only:{' '}
                {perf.metrics.beats_count_only ? 'YES' : 'NO'} · weighted:{' '}
                {perf.metrics.beats_weighted_baseline ? 'YES' : 'NO'}
              </p>
            </div>
            <div className="section">
              <h2>Weights + prediction logs</h2>
              <table className="rate-table">
                <thead>
                  <tr>
                    <th>Component</th>
                    <th>Weight</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(perf.weights).map(([k, v]) => (
                    <tr key={k}>
                      <td>{k}</td>
                      <td>{v.toFixed(2)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {perf.prediction_log && (
                <p className="sub" style={{ marginTop: '1rem' }}>
                  Logged {perf.prediction_log.total_logged} rows · scored{' '}
                  {perf.prediction_log.scored} · accuracy{' '}
                  {perf.prediction_log.accuracy == null
                    ? '—'
                    : pct(perf.prediction_log.accuracy)}
                </p>
              )}
            </div>
          </div>
        </section>
      )}
    </div>
  )
}
