import { useParams, useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { getBotDetail } from '../api/endpoints'
import KpiCard from '../components/ui/KpiCard'
import DataTable, { Column } from '../components/ui/DataTable'
import StatusBadge from '../components/ui/StatusBadge'
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell
} from 'recharts'
import { ArrowLeft, Bot, TrendingUp, TrendingDown, Activity } from 'lucide-react'
import { formatDistanceToNow } from 'date-fns'

const BOT_DISPLAY: Record<string, string> = {
  viper3:   'Viper',
  anaconda: 'Anaconda',
  hawk:     'Anaconda',
  mamba:    'Mamba',
  cobra:    'Cobra',
  taipan:   'Taipan',
  oracle:   'Oracle',
}
const getBotDisplay = (bot: string) => BOT_DISPLAY[bot] || bot

export default function BotDetail() {
  const { profile } = useParams<{ profile: string }>()
  const navigate = useNavigate()

  const { data, isLoading } = useQuery({
    queryKey: ['botDetail', profile],
    queryFn: () => getBotDetail(profile!),
    refetchInterval: 30_000,
    enabled: !!profile,
  })

  const stats = data?.stats || {}
  const trades = data?.trades || []
  const trails = data?.trail_updates || []
  const hb = data?.heartbeat || {}

  const tradeCols: Column<any>[] = [
    { key: 'symbol',    label: 'Symbol' },
    { key: 'direction', label: 'Direction', render: r => (
      <span className={r.direction === 'buy' ? 'text-green-400' : 'text-red-400'}>
        {r.direction?.toUpperCase() || '—'}
      </span>
    )},
    { key: 'price',   label: 'Price',   render: r => r.price?.toFixed(4) ?? '—' },
    { key: 'event',   label: 'Event',   render: r => <StatusBadge value={r.event || '—'} /> },
    { key: 'strategy',label: 'Strategy',render: r => r.strategy || '—' },
    { key: 'timestamp',label: 'Time',   render: r => r.timestamp
      ? formatDistanceToNow(new Date(r.timestamp), { addSuffix: true })
      : '—'
    },
  ]

  const trailCols: Column<any>[] = [
    { key: 'symbol',        label: 'Symbol' },
    { key: 'ticket',        label: 'Ticket' },
    { key: 'old_sl',        label: 'Old SL',       render: r => r.old_sl?.toFixed(4) ?? '—' },
    { key: 'new_sl',        label: 'New SL',       render: r => r.new_sl?.toFixed(4) ?? '—' },
    { key: 'current_price', label: 'Price',        render: r => r.current_price?.toFixed(4) ?? '—' },
    { key: 'timestamp',     label: 'Time',         render: r => r.timestamp
      ? formatDistanceToNow(new Date(r.timestamp), { addSuffix: true })
      : '—'
    },
  ]

  if (isLoading) {
    return <p className="text-g-muted">Loading bot data…</p>
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center gap-3">
        <button
          onClick={() => navigate('/trading')}
          className="text-g-muted hover:text-white transition-colors"
        >
          <ArrowLeft size={18} />
        </button>
        <Bot size={20} className="text-accent" />
        <h1 className="text-lg font-bold text-white font-mono">{getBotDisplay(profile || '')}</h1>
        {hb.account && (
          <span className="text-xs text-g-muted font-mono">#{hb.account}</span>
        )}
      </div>

      {/* Stats */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <KpiCard label="Total Entries"   value={stats.total_entries ?? 0}   icon={TrendingUp} accent />
        <KpiCard label="Entries Today"   value={stats.entries_today ?? 0}   icon={Activity} />
        <KpiCard label="Rejections"      value={stats.rejections ?? 0}      icon={TrendingDown} />
        <KpiCard label="Trail Updates"   value={stats.trail_updates ?? 0}   icon={Activity} />
      </div>

      {/* Trades */}
      <div>
        <h2 className="text-sm font-semibold text-white mb-3">Last 50 Trades</h2>
        <DataTable columns={tradeCols} data={trades} emptyText="No trades" dateField="timestamp" />
      </div>

      {/* Trail Updates */}
      <div>
        <h2 className="text-sm font-semibold text-white mb-3">Last 20 Trail Updates</h2>
        <DataTable columns={trailCols} data={trails} emptyText="No trail updates" dateField="timestamp" />
      </div>
    </div>
  )
}
