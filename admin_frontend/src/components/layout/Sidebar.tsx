import { useState } from 'react'
import { NavLink } from 'react-router-dom'
import {
  LayoutDashboard, Bot, Users, CreditCard,
  Server, Settings, Zap, X, Brain,
  LayoutGrid, MessageCircle, ShieldCheck, ChevronDown,
} from 'lucide-react'
import { useUIStore } from '../../stores/ui'
import clsx from 'clsx'

const nav = [
  { section: 'PORTFOLIO', items: [
    { label: 'Dashboard',        icon: LayoutDashboard, to: '/' },
    { label: 'Prop Challenge',    icon: Bot,             to: '/trading' },
    { label: 'AI Signals',       icon: Zap,             to: '/signals' },
    { label: 'AI Analytics',     icon: Brain,           to: '/analytics' },
  ]},
  { section: 'BUSINESS', items: [
    { label: 'Billing',          icon: CreditCard,      to: '/billing' },
  ]},
  { section: 'SYSTEM', items: [
    { label: 'Infrastructure',   icon: Server,          to: '/infrastructure' },
    { label: 'Settings',         icon: Settings,        to: '/settings' },
  ]},
]

const adminNav = [
  { label: 'Control Centre',  icon: LayoutGrid,    to: '/admin/control-centre' },
  { label: 'Telegram Bot',    icon: MessageCircle, to: '/admin/telegram' },
  { label: 'User Management', icon: ShieldCheck,   to: '/admin/users' },
]

export default function Sidebar() {
  const { sidebarOpen, setSidebarOpen } = useUIStore()
  const [adminOpen, setAdminOpen] = useState(true)

  return (
    <>
      {/* Mobile overlay */}
      {sidebarOpen && (
        <div
          className="fixed inset-0 bg-black/60 z-20 lg:hidden"
          onClick={() => setSidebarOpen(false)}
        />
      )}

      <aside className={clsx(
        'fixed top-0 left-0 h-full z-30 flex flex-col',
        'bg-g-deep border-r border-g-border transition-transform duration-200',
        'w-56',
        sidebarOpen ? 'translate-x-0' : '-translate-x-full',
        'lg:translate-x-0 lg:static lg:z-auto'
      )}>
        {/* Logo */}
        <div className="flex items-center gap-2 px-4 h-14 border-b border-g-border shrink-0">
          <Zap size={18} className="text-accent" />
          <span className="font-bold text-sm tracking-wide text-white">GlitchExecutor</span>
          <span className="ml-1 text-xs text-g-muted font-mono">admin</span>
          <button
            className="ml-auto lg:hidden text-g-muted hover:text-white"
            onClick={() => setSidebarOpen(false)}
          >
            <X size={16} />
          </button>
        </div>

        {/* Nav */}
        <nav className="flex-1 overflow-y-auto py-4 px-2 space-y-4">
          {nav.map(group => (
            <div key={group.section}>
              <p className="text-[10px] font-semibold text-g-dim tracking-widest px-2 mb-1">
                {group.section}
              </p>
              {group.items.map(item => (
                <NavLink
                  key={item.to}
                  to={item.to}
                  end={item.to === '/'}
                  className={({ isActive }) => clsx(
                    'flex items-center gap-3 px-3 py-2 rounded-lg text-sm transition-colors',
                    isActive
                      ? 'bg-accent/10 text-accent font-medium'
                      : 'text-g-muted hover:text-g-text hover:bg-white/5'
                  )}
                >
                  <item.icon size={16} />
                  {item.label}
                </NavLink>
              ))}
            </div>
          ))}

          {/* ADMIN collapsible section */}
          <div>
            <button
              onClick={() => setAdminOpen(o => !o)}
              className="w-full flex items-center justify-between px-2 mb-1 group"
            >
              <p className="text-[10px] font-semibold text-g-dim tracking-widest group-hover:text-accent transition-colors">
                ADMIN
              </p>
              <ChevronDown
                size={12}
                className={clsx(
                  'text-g-dim transition-transform duration-200',
                  adminOpen ? 'rotate-0' : '-rotate-90'
                )}
              />
            </button>
            {adminOpen && adminNav.map(item => (
              <NavLink
                key={item.to}
                to={item.to}
                className={({ isActive }) => clsx(
                  'flex items-center gap-3 px-3 py-2 rounded-lg text-sm transition-colors',
                  isActive
                    ? 'bg-accent/10 text-accent font-medium'
                    : 'text-g-muted hover:text-g-text hover:bg-white/5'
                )}
              >
                <item.icon size={16} />
                {item.label}
              </NavLink>
            ))}
          </div>
        </nav>

        {/* Bottom version */}
        <div className="px-4 py-3 border-t border-g-border text-[10px] text-g-dim font-mono">
          v1.0.0
        </div>
      </aside>
    </>
  )
}
