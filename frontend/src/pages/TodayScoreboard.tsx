import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api'
import type { ScoreboardGame } from '../types'

function pct(n: number | null | undefined) {
  if (n == null) return '—'
  return `${(n * 100).toFixed(1)}%`
}

export default function TodayScoreboard() {
  const [games, setGames] = useState<ScoreboardGame[]>([])
  const [date, setDate] = useState('')
  const [workers, setWorkers] = useState<string[]>([])
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [accuracy, setAccuracy] = useState<{ top1_accuracy: number | null; top2_accuracy: number | null; resolved: number } | null>(null)

  async function load() {
    try {
      setLoading(true)
      const [sched, acc] = await Promise.all([api.scheduleToday(), api.accuracy()])
      setGames(sched.games)
      setDate(sched.date)
      setWorkers(sched.live_workers || [])
      setAccuracy(acc)
      setError(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
    const t = setInterval(load, 15000)
    return () => clearInterval(t)
  }, [])

  const buckets: Array<'Live' | 'Scheduled' | 'Final'> = ['Live', 'Scheduled', 'Final']

  return (
    <div className="page">
      <section className="panel hero-panel">
        <div>
          <p className="eyebrow">TODAY&apos;S GAMES · {date || '…'}</p>
          <h2 className="panel-title">Scoreboard</h2>
          <p className="muted">
            Backend discovers the MLB schedule and auto-starts LiveGameWorkers for every LIVE game.
            No manual game picker required.
          </p>
        </div>
        <div className="stat-strip">
          <div>
            <span className="stat-label">Games</span>
            <strong>{games.length}</strong>
          </div>
          <div>
            <span className="stat-label">Live workers</span>
            <strong>{workers.length}</strong>
          </div>
          <div>
            <span className="stat-label">Top-1 live</span>
            <strong>{pct(accuracy?.top1_accuracy)}</strong>
          </div>
          <div>
            <span className="stat-label">Top-2 live</span>
            <strong>{pct(accuracy?.top2_accuracy)}</strong>
          </div>
        </div>
      </section>

      {error && <div className="banner error">{error}</div>}
      {loading && !games.length && <div className="banner">Loading MLB schedule…</div>}
      {!loading && !games.length && !error && (
        <div className="banner">No MLB games on the schedule for this date (off-day / feed empty).</div>
      )}

      {buckets.map((bucket) => {
        const subset = games.filter((g) => g.bucket === bucket)
        if (!subset.length) return null
        return (
          <section key={bucket} className="panel">
            <h3 className="section-heading">
              <span className={`pill bucket-${bucket.toLowerCase()}`}>{bucket}</span>
              <span className="muted">{subset.length} game{subset.length === 1 ? '' : 's'}</span>
            </h3>
            <div className="scoreboard-grid">
              {subset.map((g) => (
                <Link key={g.game_pk} to={`/games/${g.game_pk}`} className="game-card">
                  <div className="game-card-top">
                    <span className={`pill bucket-${(g.bucket || 'scheduled').toLowerCase()}`}>{g.status}</span>
                    {g.worker_active && <span className="pill live-dot">WORKER</span>}
                  </div>
                  <div className="matchup-row">
                    <div>
                      <div className="team">{g.away_team_name}</div>
                      <div className="probable">{g.away_probable || '—'}</div>
                    </div>
                    <div className="score">{g.away_score ?? '—'}</div>
                  </div>
                  <div className="matchup-row">
                    <div>
                      <div className="team">{g.home_team_name}</div>
                      <div className="probable">{g.home_probable || '—'}</div>
                    </div>
                    <div className="score">{g.home_score ?? '—'}</div>
                  </div>
                  <div className="game-card-meta">
                    <span>
                      {g.inning ? `${g.inning_half || ''} ${g.inning}` : g.venue || 'MLB'}
                    </span>
                    <span className="mono">#{g.game_pk}</span>
                  </div>
                </Link>
              ))}
            </div>
          </section>
        )
      })}
    </div>
  )
}
