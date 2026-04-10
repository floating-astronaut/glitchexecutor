import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { useAuthStore } from './stores/auth'
import Layout from './components/layout/Layout'
import Login from './pages/Login'
import DashboardHome from './pages/DashboardHome'
import Trading from './pages/Trading'
import BotDetail from './pages/BotDetail'
import Clients from './pages/Clients'
import ClientDetail from './pages/ClientDetail'
import Billing from './pages/Billing'
import Infrastructure from './pages/Infrastructure'
import Settings from './pages/Settings'
import Analytics from './pages/Analytics'
import Signals from './pages/Signals'
import ControlCentre  from './pages/admin/ControlCentre'
import TelegramBot    from './pages/admin/TelegramBot'
import UserManagement from './pages/admin/UserManagement'

function AuthGuard({ children }: { children: React.ReactNode }) {
  const { token } = useAuthStore()
  if (!token) return <Navigate to="/login" replace />
  return <>{children}</>
}

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route
          path="/"
          element={
            <AuthGuard>
              <Layout />
            </AuthGuard>
          }
        >
          <Route index element={<DashboardHome />} />
          <Route path="trading" element={<Trading />} />
          <Route path="trading/:profile" element={<BotDetail />} />
          <Route path="clients" element={<Clients />} />
          <Route path="clients/:id" element={<ClientDetail />} />
          <Route path="billing" element={<Billing />} />
          <Route path="infrastructure" element={<Infrastructure />} />
          <Route path="settings" element={<Settings />} />
          <Route path="analytics" element={<Analytics />} />
          <Route path="signals" element={<Signals />} />
          <Route path="admin/control-centre" element={<ControlCentre />} />
          <Route path="admin/telegram"       element={<TelegramBot />} />
          <Route path="admin/users"          element={<UserManagement />} />
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  )
}
