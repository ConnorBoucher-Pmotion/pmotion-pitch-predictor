import type { PitchProbability } from '../types'

export function ProbabilityBars({
  probabilities,
  highlight,
}: {
  probabilities: PitchProbability[]
  highlight?: string | null
}) {
  return (
    <div className="prob-list">
      {probabilities.map((p, i) => (
        <div className="prob-row" key={p.pitch_type}>
          <div className="name">
            {p.pitch_type}
            <div style={{ color: 'var(--muted)', fontSize: '0.7rem' }}>{p.pitch_name}</div>
          </div>
          <div className="bar-track">
            <div
              className={`bar-fill ${i === 0 || p.pitch_type === highlight ? 'top' : ''}`}
              style={{ width: `${Math.max(p.probability * 100, 2)}%` }}
            />
          </div>
          <div className="pct">{(p.probability * 100).toFixed(1)}%</div>
        </div>
      ))}
    </div>
  )
}
