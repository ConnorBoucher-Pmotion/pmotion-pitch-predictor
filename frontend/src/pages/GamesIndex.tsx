import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api'
import type { ScoreboardGame } from '../types'

export default function GamesIndex() {
  const [games, setGames] = useState<ScoreboardGame[]>([])
  const [date, setDate] = useState('')
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    ;(async () => {
      try {
        const sched = await api.scheduleToday()
        setGames(sched.games)
        setDate(sched.date)
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e))
      }
    })()
  }, [])

  return (
    <div className="page">
      <section className="panel">
        <h2 className="panel-title">Games · {date}</h2>
        <p className="muted">All of today&apos;s MLB games tracked by the backend engine.</p>
        {error && <div className="banner error">{error}</div>}
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>Status</th>
                <th>Matchup</th>
                <th>Score</th>
                <th>Worker</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {games.map((g) => (
                <tr key={g.game_pk}>
                  <td>
                    <span className={`pill bucket-${(g.bucket || '').toLowerCase()}`}>{g.bucket}</span>
                  </td>
                  <td>
                    {g.away_team_name} @ {g.home_team_name}
                  </td>
                  <td className="mono">
                    {g.away_score ?? '—'}–{g.home_score ?? '—'}
                  </td>
                  <td>{g.worker_active ? 'active' : '—'}</td>
                  <td>
                    <Link to={`/games/${g.game_pk}`}>Open</Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  )
}
