import { useEffect, useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api } from '../api'
import { ProbabilityBars } from '../components/ProbabilityBars'
import type { GameDetail, PitchProbability } from '../types'

function pct(n: number | null | undefined) {
  if (n == null) return '—'
  return `${(n * 100).toFixed(1)}%`
}

export default function LiveGamePage() {
  const { gamePk } = useParams()
  const pk = Number(gamePk)
  const [detail, setDetail] = useState<GameDetail | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [demoNote, setDemoNote] = useState<string | null>(null)

  async function load() {
    if (!pk) return
    try {
      const d = await api.gameDetail(pk)
      setDetail(d)
      setError(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  useEffect(() => {
    load()
    const t = setInterval(load, 4000)
    return () => clearInterval(t)
  }, [pk])

  const openProbs: PitchProbability[] = useMemo(() => {
    const items = detail?.open_prediction?.probabilities?.items
    return Array.isArray(items) ? items : []
  }, [detail])

  async function forceTrack() {
    try {
      await api.trackGame(pk)
      setDemoNote('LiveGameWorker attached (auto-start also runs for LIVE games).')
      await load()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  async function startDemo() {
    try {
      // Use this game if it has pitches; else default historical Dodgers game from config era
      const target = pk || 746168
      const st = await api.startHistoricalDemo(target, 1.0)
      setDemoNote(
        `Started labeled_historical_demo on game ${String(st.game_pk)}. NOT live MLB — timing-proof demo only.`,
      )
    } catch (e) {
      // Fallback to known completed game from sample era
      try {
        const st = await api.startHistoricalDemo(746168, 1.0)
        setDemoNote(
          `Feed empty for this game. Started labeled_historical_demo on ${String(st.game_pk)} instead. NOT live.`,
        )
      } catch (e2) {
        setError(e2 instanceof Error ? e2.message : String(e2))
      }
    }
  }

  if (!pk) return <div className="banner error">Invalid game id</div>
  const live = detail?.live
  const game = detail?.game

  return (
    <div className="page">
      <p className="breadcrumb">
        <Link to="/">← TODAY</Link>
      </p>

      {error && <div className="banner error">{error}</div>}
      {demoNote && <div className="banner warn">{demoNote}</div>}

      <section className="panel hero-panel">
        <div>
          <p className="eyebrow">{game?.bucket || live?.abstract_state || 'GAME'}</p>
          <h2 className="panel-title">
            {game?.away_team_name || 'Away'} @ {game?.home_team_name || 'Home'}
          </h2>
          <p className="muted">
            {live?.status || game?.status || '…'} · data_label:{' '}
            <code>{detail?.data_label || live?.data_label || '—'}</code>
          </p>
        </div>
        <div className="score-hero">
          <div>
            <span>{game?.away_team_name}</span>
            <strong>{live?.away_score ?? game?.away_score ?? '—'}</strong>
          </div>
          <div className="inning-chip">
            {live?.inning ? `${live.inning_half || ''} ${live.inning}` : '—'}
          </div>
          <div>
            <span>{game?.home_team_name}</span>
            <strong>{live?.home_score ?? game?.home_score ?? '—'}</strong>
          </div>
        </div>
      </section>

      <div className="two-col">
        <section className="panel">
          <h3 className="section-heading">Live matchup</h3>
          <div className="matchup-board">
            <div>
              <span className="stat-label">Pitcher</span>
              <strong>{live?.pitcher_name || '—'}</strong>
            </div>
            <div>
              <span className="stat-label">Batter</span>
              <strong>{live?.batter_name || '—'}</strong>
            </div>
            <div>
              <span className="stat-label">Count</span>
              <strong className="mono">
                {live?.balls ?? '—'}-{live?.strikes ?? '—'} · {live?.outs ?? '—'} out
              </strong>
            </div>
            <div>
              <span className="stat-label">Runners</span>
              <strong className="mono">
                {live?.runners?.on_1b ? '1B ' : ''}
                {live?.runners?.on_2b ? '2B ' : ''}
                {live?.runners?.on_3b ? '3B' : ''}
                {!live?.runners?.on_1b && !live?.runners?.on_2b && !live?.runners?.on_3b ? 'empty' : ''}
              </strong>
            </div>
          </div>

          <div className="actions-row">
            <button type="button" className="btn" onClick={forceTrack}>
              Attach worker
            </button>
            <button type="button" className="btn secondary" onClick={startDemo}>
              Labeled historical demo
            </button>
          </div>
          <p className="muted small">
            Workers auto-start when MLB marks the game LIVE. The historical demo is explicitly labeled
            <code> labeled_historical_demo</code> — never silent fake live data.
          </p>
        </section>

        <section className="panel">
          <h3 className="section-heading">Next pitch prediction</h3>
          {detail?.open_prediction ? (
            <>
              <p className="muted small">
                Created <code>{detail.open_prediction.prediction_created_at}</code>
                {' · '}actual still <code>{String(detail.open_prediction.actual_pitch_type)}</code>
              </p>
              <p className="pred-top">
                Top-1 <strong>{detail.open_prediction.top1_pitch_type}</strong>
                {detail.open_prediction.top2_pitch_type && (
                  <>
                    {' '}
                    · Top-2 <strong>{detail.open_prediction.top2_pitch_type}</strong>
                  </>
                )}
              </p>
              {openProbs.length > 0 && <ProbabilityBars probabilities={openProbs} />}
              {detail.open_prediction.explanation && (
                <p className="muted">{detail.open_prediction.explanation}</p>
              )}
            </>
          ) : (
            <p className="muted">
              No open prediction yet. Waiting for LIVE matchup state (or start labeled historical demo).
            </p>
          )}
          <div className="stat-strip compact">
            <div>
              <span className="stat-label">Resolved</span>
              <strong>{detail?.accuracy?.resolved ?? 0}</strong>
            </div>
            <div>
              <span className="stat-label">Top-1</span>
              <strong>{pct(detail?.accuracy?.top1_accuracy)}</strong>
            </div>
            <div>
              <span className="stat-label">Top-2</span>
              <strong>{pct(detail?.accuracy?.top2_accuracy)}</strong>
            </div>
          </div>
        </section>
      </div>

      <section className="panel">
        <h3 className="section-heading">Pitch history</h3>
        {!detail?.pitches?.length && <p className="muted">No stored pitches yet for this game.</p>}
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>Inn</th>
                <th>Count</th>
                <th>Type</th>
                <th>Pitcher</th>
                <th>Batter</th>
                <th>Desc</th>
              </tr>
            </thead>
            <tbody>
              {[...(detail?.pitches || [])].reverse().map((p) => (
                <tr key={p.id}>
                  <td className="mono">
                    {p.inning_half?.[0] || ''}
                    {p.inning}
                  </td>
                  <td className="mono">
                    {p.balls}-{p.strikes}
                  </td>
                  <td>
                    <strong>{p.pitch_type}</strong>
                  </td>
                  <td>{p.pitcher_name}</td>
                  <td>{p.batter_name}</td>
                  <td className="muted">{p.description}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="panel">
        <h3 className="section-heading">Prediction log (timing proof)</h3>
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>Created</th>
                <th>Top1</th>
                <th>Actual</th>
                <th>Resolved</th>
                <th>T1/T2</th>
                <th>Label</th>
              </tr>
            </thead>
            <tbody>
              {(detail?.predictions || []).map((p) => (
                <tr key={p.id}>
                  <td className="mono small">{p.prediction_created_at}</td>
                  <td>{p.top1_pitch_type}</td>
                  <td>{p.actual_pitch_type ?? '—'}</td>
                  <td className="mono small">{p.resolved_at ?? 'open'}</td>
                  <td>
                    {p.top1_correct == null ? '—' : p.top1_correct ? '✓' : '✗'}/
                    {p.top2_correct == null ? '—' : p.top2_correct ? '✓' : '✗'}
                  </td>
                  <td className="small">{p.data_label}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  )
}
