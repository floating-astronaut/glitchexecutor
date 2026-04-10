import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { getClients } from '../api/endpoints'
import DataTable, { Column } from '../components/ui/DataTable'
import StatusBadge from '../components/ui/StatusBadge'
import { Search, ChevronLeft, ChevronRight, Eye, Zap } from 'lucide-react'
import { formatDistanceToNow } from 'date-fns'

export default function Clients() {
  const navigate = useNavigate()
  const [page, setPage] = useState(1)
  const [search, setSearch] = useState('')
  const [tier, setTier] = useState('')
  const [status, setStatus] = useState('')

  const { data, isLoading } = useQuery({
    queryKey: ['clients', page, search, tier, status],
    queryFn: () => getClients({ page, limit: 20, search, tier, status }),
    placeholderData: (prev) => prev,
  })

  const totalPages = Math.ceil((data?.total || 0) / 20)

  const cols: Column<any>[] = [
    { key: 'username', label: 'Username', render: r => (
      <span className="font-medium text-white">{r.username || '—'}</span>
    )},
    { key: 'telegram_id', label: 'Telegram ID', render: r => (
      <span className="font-mono text-xs text-g-muted">{r.telegram_id}</span>
    )},
    { key: 'email',  label: 'Email',  render: r => r.email || '—' },
    { key: 'tier',   label: 'Tier',   render: r => <StatusBadge value={r.tier || 'trial'} /> },
    { key: 'status', label: 'Status', render: r => <StatusBadge value={r.status || 'active'} dot /> },
    { key: 'queries_today', label: 'Queries Today' },
    { key: 'favorites_count', label: 'Favs', render: r => (
      <span className="text-xs text-g-muted">{r.favorites_count ?? 0}</span>
    )},
    { key: 'auto_execute_enabled', label: 'Auto-Exec', render: r => r.auto_execute_enabled ? (
      <span className="inline-flex items-center gap-1 text-xs text-green-400 font-medium">
        <Zap size={11} />
        On
      </span>
    ) : (
      <span className="text-xs text-g-dim">Off</span>
    )},
    { key: 'created_at', label: 'Joined', render: r => r.created_at
      ? formatDistanceToNow(new Date(r.created_at), { addSuffix: true })
      : '—'
    },
    { key: 'actions', label: '', render: r => (
      <button
        onClick={() => navigate(`/clients/${r.id}`)}
        className="text-g-muted hover:text-accent transition-colors"
        title="View"
      >
        <Eye size={14} />
      </button>
    )},
  ]

  return (
    <div className="space-y-4">
      {/* Filters */}
      <div className="flex flex-wrap gap-3">
        <div className="relative flex-1 min-w-48">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-g-muted" />
          <input
            value={search}
            onChange={e => { setSearch(e.target.value); setPage(1) }}
            placeholder="Search username, email…"
            className="w-full bg-g-card border border-g-border rounded-lg pl-8 pr-3 py-2 text-sm text-white placeholder-g-dim focus:outline-none focus:border-accent/50"
          />
        </div>
        <select
          value={tier}
          onChange={e => { setTier(e.target.value); setPage(1) }}
          className="bg-g-card border border-g-border rounded-lg px-3 py-2 text-sm text-g-text focus:outline-none focus:border-accent/50"
        >
          <option value="">All Tiers</option>
          <option value="trial">Trial</option>
          <option value="starter">Starter</option>
          <option value="pro">Pro</option>
          <option value="elite">Elite</option>
        </select>
        <select
          value={status}
          onChange={e => { setStatus(e.target.value); setPage(1) }}
          className="bg-g-card border border-g-border rounded-lg px-3 py-2 text-sm text-g-text focus:outline-none focus:border-accent/50"
        >
          <option value="">All Statuses</option>
          <option value="active">Active</option>
          <option value="suspended">Suspended</option>
          <option value="cancelled">Cancelled</option>
          <option value="pending">Pending</option>
        </select>
      </div>

      <div className="text-xs text-g-muted">
        {data?.total ?? 0} customers total
      </div>

      <DataTable
        columns={cols}
        data={data?.customers || []}
        loading={isLoading}
        emptyText="No customers found"
      />

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-between">
          <button
            onClick={() => setPage(p => Math.max(1, p - 1))}
            disabled={page === 1}
            className="flex items-center gap-1 px-3 py-1.5 text-sm text-g-muted hover:text-white disabled:opacity-30 transition-colors"
          >
            <ChevronLeft size={14} /> Prev
          </button>
          <span className="text-sm text-g-muted">Page {page} of {totalPages}</span>
          <button
            onClick={() => setPage(p => Math.min(totalPages, p + 1))}
            disabled={page === totalPages}
            className="flex items-center gap-1 px-3 py-1.5 text-sm text-g-muted hover:text-white disabled:opacity-30 transition-colors"
          >
            Next <ChevronRight size={14} />
          </button>
        </div>
      )}
    </div>
  )
}
