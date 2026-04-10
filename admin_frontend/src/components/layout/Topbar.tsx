import { Menu, LogOut, User } from 'lucide-react'
import { useUIStore } from '../../stores/ui'
import { useAuthStore } from '../../stores/auth'
import { useNavigate } from 'react-router-dom'

interface Props {
  title: string
}

export default function Topbar({ title }: Props) {
  const { toggleSidebar } = useUIStore()
  const { user, logout } = useAuthStore()
  const navigate = useNavigate()

  const handleLogout = () => {
    logout()
    window.location.href = 'https://glitchexecutor.com'
  }

  return (
    <header className="h-14 bg-g-deep border-b border-g-border flex items-center px-4 gap-4 shrink-0">
      <button
        onClick={toggleSidebar}
        className="text-g-muted hover:text-white transition-colors lg:hidden"
      >
        <Menu size={20} />
      </button>

      <h1 className="text-sm font-semibold text-white flex-1">{title}</h1>

      <div className="flex items-center gap-3">
        <div className="flex items-center gap-2 text-sm text-g-muted">
          <User size={14} />
          <span className="hidden sm:inline">{user?.email}</span>
          <span className="text-xs bg-g-border text-g-text px-2 py-0.5 rounded-full">
            {user?.role}
          </span>
        </div>
        <button
          onClick={handleLogout}
          className="text-g-muted hover:text-red-400 transition-colors"
          title="Logout"
        >
          <LogOut size={16} />
        </button>
      </div>
    </header>
  )
}
