import { Outlet, useLocation } from 'react-router-dom'
import Sidebar from './Sidebar'
import Topbar from './Topbar'

const PAGE_TITLES: Record<string, string> = {
  '/': 'Dashboard',
  '/trading': 'Trading & Bots',
  '/clients': 'Clients',
  '/billing': 'Billing',
  '/infrastructure': 'Infrastructure',
  '/settings': 'Settings',
  '/analytics': 'AI Analytics',
}

export default function Layout() {
  const { pathname } = useLocation()
  const base = '/' + pathname.split('/')[1]
  const title = PAGE_TITLES[base] || PAGE_TITLES[pathname] || 'Admin'

  return (
    <div className="flex h-screen bg-g-bg overflow-hidden">
      <Sidebar />
      <div className="flex flex-col flex-1 min-w-0">
        <Topbar title={title} />
        <main className="flex-1 overflow-y-auto p-4 lg:p-6">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
