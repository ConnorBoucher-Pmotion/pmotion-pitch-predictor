import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { Shell } from './components/Shell'
import GamesIndex from './pages/GamesIndex'
import LegacyLab from './pages/LegacyLab'
import LiveGamePage from './pages/LiveGamePage'
import PitchersPage from './pages/PitchersPage'
import TodayScoreboard from './pages/TodayScoreboard'
import './index.css'

const basename = import.meta.env.BASE_URL.replace(/\/$/, '') || undefined

export default function App() {
  return (
    <BrowserRouter basename={basename}>
      <Routes>
        <Route element={<Shell />}>
          <Route index element={<TodayScoreboard />} />
          <Route path="games" element={<GamesIndex />} />
          <Route path="games/:gamePk" element={<LiveGamePage />} />
          <Route path="pitchers" element={<PitchersPage />} />
          <Route path="lab" element={<LegacyLab />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}
