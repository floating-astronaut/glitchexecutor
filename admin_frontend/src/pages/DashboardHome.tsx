import { useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { getKpis, getAlerts, getActivity } from '../api/endpoints'
import KpiCard from '../components/ui/KpiCard'
import DataTable, { Column } from '../components/ui/DataTable'
import StatusBadge from '../components/ui/StatusBadge'
import {
  Users, DollarSign, Bot, Activity, Mail,
  TrendingUp, AlertCircle, ArrowRight, Zap,
} from 'lucide-react'
import { formatDistanceToNow } from 'date-fns'

export default function DashboardHome() {
  const navigate = useNavigate()
  const { data: kpis, isLoading: kpisLoading } = useQuery({
    queryKey: ['kpis'],
    queryFn: getKpis,
    refetchInterval: 30_000,
  })
  const { data: alerts = [] } = useQuery({
    queryKey: ['alerts'],
    queryFn: getAlerts,
    refetchInterval: 30_000,
  })
  const { data: activity = [], isLoading: actLoading } = useQuery({
    queryKey: ['activity'],
    queryFn: getActivity,
    refetchInterval: 30_000,
  })

  const activityCols: Column<any>[] = [
    { key: 'type', label: 'Type', render: r => (
      <span className="text-xs font-mono text-g-muted">{r.type}</span>
    )},
    { key: 'customer', label: 'Source' },
    { key: 'symbol', label: 'Symbol', render: r => r.symbol || '—' },
    { key: 'action', label: 'Action' },
    { key: 'created_at', label: 'Time', render: r => r.created_at
      ? formatDistanceToNow(new Date(r.created_at), { addSuffix: true })
      : '—'
    },
  ]

  return (
    <div className="space-y-6">
      {/* Alerts */}
      {alerts.length > 0 && (
        <div className="space-y-2">
          {alerts.map((alert: any, i: number) => (
            <div key={i} className={`flex items-center gap-3 px-4 py-3 rounded-xl border text-sm ${
              alert.severity === 'critical'
                ? 'bg-red-500/10 border-red-500/30 text-red-300'
                : 'bg-yellow-500/10 border-yellow-500/30 text-yellow-300'
            }`}>
              <AlertCircle size={16} />
              <span>{alert.message}</span>
            </div>
          ))}
        </div>
      )}

      {/* Primary KPIs */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <KpiCard
          label="Total Customers"
          value={kpisLoading ? '…' : kpis?.total_customers ?? 0}
          icon={Users}
          sub={`${kpis?.active_customers ?? 0} active`}
        />
        <KpiCard
          label="MRR"
          value={kpisLoading ? '…' : `$${(kpis?.mrr_usd ?? 0).toLocaleString()}`}
          icon={DollarSign}
          accent
          sub={`ARR $${((kpis?.arr_usd ?? 0)).toLocaleString()}`}
          trend="up"
        />
        <KpiCard
          label="Auto-Execute Users"
          value={kpisLoading ? '…' : kpis?.auto_execute_users ?? 0}
          icon={Bot}
          sub={`${kpis?.strong_signal_notify_users ?? 0} strong signal notify`}
        />
        <KpiCard
          label="Ensemble"
          value={kpisLoading ? '…' : kpis?.ensemble_status ?? '—'}
          icon={Activity}
        />
      </div>

      {/* Secondary KPIs */}
      <div className="grid grid-cols-2 lg:grid-cols-3 gap-4">
        <KpiCard
          label="Auto-Exec Trades Today"
          value={kpisLoading ? '…' : kpis?.auto_execute_trades_today ?? 0}
          icon={TrendingUp}
        />
        <KpiCard
          label="Query Cost Today"
          value={kpisLoading ? '…' : `$${(kpis?.query_cost_today_usd ?? 0).toFixed(4)}`}
          icon={DollarSign}
        />
        <KpiCard
          label="Email Signups"
          value={kpisLoading ? '…' : kpis?.email_signups ?? 0}
          icon={Mail}
        />
      </div>

      {/* Tier breakdown */}
      {kpis?.by_tier && (
        <div className="bg-g-card border border-g-border rounded-xl p-4">
          <h2 className="text-sm font-semibold text-white mb-3">Customers by Tier</h2>
          <div className="flex gap-4 flex-wrap">
            {Object.entries(kpis.by_tier).map(([tier, count]: [string, any]) => (
              <div key={tier} className="flex items-center gap-2">
                <StatusBadge value={tier} />
                <span className="text-sm font-medium text-white">{count}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Quick actions */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        {[
          { label: 'Manage Clients', to: '/clients', icon: Users },
          { label: 'AI Signals & Trades', to: '/signals', icon: Zap },
          { label: 'Billing Overview', to: '/billing', icon: DollarSign },
        ].map(({ label, to, icon: Icon }) => (
          <button
            key={to}
            onClick={() => navigate(to)}
            className="flex items-center justify-between px-4 py-3 bg-g-card border border-g-border rounded-xl hover:border-accent/30 hover:bg-accent/5 transition-all group"
          >
            <div className="flex items-center gap-2 text-sm text-g-text">
              <Icon size={16} className="text-g-muted group-hover:text-accent" />
              {label}
            </div>
            <ArrowRight size={14} className="text-g-dim group-hover:text-accent" />
          </button>
        ))}
      </div>

      {/* Recent activity */}
      <div>
        <h2 className="text-sm font-semibold text-white mb-3">Recent Activity</h2>
        <DataTable
          columns={activityCols}
          data={activity}
          loading={actLoading}
          emptyText="No recent activity"
          dateField="created_at"
        />
      </div>
    </div>
  )
}
