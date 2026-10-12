import { useEffect, useMemo, useState } from 'react'
import { api } from '../api'
import type { RosterPitcher } from '../types'

export default function PitchersPage() {
  const [rows, setRows] = useState<RosterPitcher[]>([])
  const [q, setQ] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  async function load(sync = false) {
    try {
      setLoading(true)
      const res = await api.rosterPitchers({ sync, q: q || undefined })
      setRows(res.pitchers)
      setError(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load(true)
  }, [])

  const filtered = useMemo(() => {
    const needle = q.trim().toLowerCase()
    if (!needle) return rows
    return rows.filter(
      (r) =>
        r.full_name.toLowerCase().includes(needle) ||
        (r.team_name || '').toLowerCase().includes(needle) ||
        String(r.player_id).includes(needle),
    )
  }, [rows, q])

  const byTeam = useMemo(() => {
    const map = new Map<string, RosterPitcher[]>()
    for (const r of filtered) {
      const key = r.team_name || 'Unknown'
      if (!map.has(key)) map.set(key, [])
      map.get(key)!.push(r)
    }
    return [...map.entries()].sort((a, b) => a[0].localeCompare(b[0]))
  }, [filtered])

  return (
    <div className="page">
      <section className="panel hero-panel">
        <div>
          <p className="eyebrow">ROSTER DIRECTORY</p>
          <h2 className="panel-title">Pitchers</h2>
          <p className="muted">Current MLB roster pitchers with official player IDs (statsapi.mlb.com).</p>
        </div>
        <div className="actions-row">
          <input
            className="input"
            placeholder="Search name, team, or MLB ID"
            value={q}
            onChange={(e) => setQ(e.target.value)}
          />
          <button type="button" className="btn" onClick={() => load(true)}>
            Refresh rosters
          </button>
        </div>
      </section>

      {error && <div className="banner error">{error}</div>}
      {loading && <div className="banner">Loading MLB rosters…</div>}

      <p className="muted">
        Showing {filtered.length} pitchers · data_label <code>mlb_roster</code>
      </p>

      {byTeam.map(([team, list]) => (
        <section key={team} className="panel">
          <h3 className="section-heading">{team}</h3>
          <div className="pitcher-grid">
            {list.map((p) => (
              <div key={p.player_id} className="pitcher-chip">
                <strong>{p.full_name}</strong>
                <span className="muted">
                  {p.position || 'P'}
                  {p.jersey_number ? ` · #${p.jersey_number}` : ''}
                </span>
                <span className="mono small">MLB ID {p.player_id}</span>
              </div>
            ))}
          </div>
        </section>
      ))}
    </div>
  )
}
