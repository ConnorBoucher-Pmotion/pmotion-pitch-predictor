import { NavLink, Outlet } from 'react-router-dom'

const links = [
  { to: '/', label: 'TODAY', end: true },
  { to: '/games', label: 'GAMES' },
  { to: '/pitchers', label: 'PITCHERS' },
  { to: '/lab', label: 'REPLAY LAB' },
]

export function Shell() {
  return (
    <div className="app-shell">
      <header className="brand-bar">
        <div className="brand-left">
          <img className="brand-logo" src={`${import.meta.env.BASE_URL}dodgers-logo.svg`} alt="Dodgers" />
          <div className="brand-mark">
            <span className="brand-kicker">PMotion · Pitch Intelligence</span>
            <h1 className="brand-title">LIVE MLB PLATFORM</h1>
            <p className="brand-sub">Auto schedule · simultaneous game workers · pre-pitch predictions</p>
          </div>
        </div>
        <nav className="tabs" aria-label="Primary">
          {links.map((l) => (
            <NavLink
              key={l.to}
              to={l.to}
              end={l.end}
              className={({ isActive }) => (isActive ? 'tab active' : 'tab')}
            >
              {l.label}
            </NavLink>
          ))}
        </nav>
      </header>
      <Outlet />
    </div>
  )
}
