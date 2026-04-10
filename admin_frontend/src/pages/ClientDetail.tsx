import { useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { getClientDetail, updateClientTier, updateClientStatus } from '../api/endpoints'
import StatusBadge from '../components/ui/StatusBadge'
import DataTable, { Column } from '../components/ui/DataTable'
import { ArrowLeft, User, Key, Zap, Star, Activity } from 'lucide-react'
import { formatDistanceToNow } from 'date-fns'
import clsx from 'clsx'

type Tab = 'overview' | 'queries' | 'keys' | 'preferences'

export default function ClientDetail() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const qc = useQueryClient()
  const [tab, setTab] = useState<Tab>('overview')
  const [newTier, setNewTier] = useState('')
  const [saving, setSaving] = useState(false)

  const { data, isLoading } = useQuery({
    queryKey: ['clientDetail', id],
    queryFn: () => getClientDetail(Number(id)),
    enabled: !!id,
  })

  const customer = data?.customer || {}
  const queries  = data?.queries || []
  const keys     = data?.exchange_keys || []
  const prefs    = data?.preferences || {}

  const handleTierSave = async () => {
    if (!newTier || newTier === customer.tier) return
    setSaving(true)
    try {
      await updateClientTier(Number(id), newTier)
      qc.invalidateQueries({ queryKey: ['clientDetail', id] })
      qc.invalidateQueries({ queryKey: ['clients'] })
      setNewTier('')
    } finally {
      setSaving(false)
    }
  }

  const handleStatus = async (status: string) => {
    await updateClientStatus(Number(id), status)
    qc.invalidateQueries({ queryKey: ['clientDetail', id] })
    qc.invalidateQueries({ queryKey: ['clients'] })
  }

  const queryCols: Column<any>[] = [
    { key: 'symbol',    label: 'Symbol',   render: r => r.symbol || '—' },
    { key: 'action',    label: 'Action' },
    { key: 'llm_cost_usd', label: 'Cost', render: r => `$${(r.llm_cost_usd ?? 0).toFixed(5)}` },
    { key: 'created_at', label: 'Time',   render: r => r.created_at
      ? formatDistanceToNow(new Date(r.created_at), { addSuffix: true })
      : '—'
    },
  ]

  if (isLoading) return <p className="text-g-muted">Loading…</p>

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-start gap-4">
        <button onClick={() => navigate('/clients')} className="text-g-muted hover:text-white mt-1">
          <ArrowLeft size={18} />
        </button>
        <div className="flex-1">
          <div className="flex items-center gap-3 flex-wrap">
            <User size={18} className="text-g-muted" />
            <h1 className="text-lg font-bold text-white">{customer.username || 'Unknown'}</h1>
            <StatusBadge value={customer.tier || 'trial'} />
            <StatusBadge value={customer.status || 'active'} dot />
          </div>
          <p className="text-xs text-g-muted mt-1 font-mono">
            Telegram ID: {customer.telegram_id} · {customer.email || 'no email'}
          </p>
        </div>
      </div>

      {/* Actions */}
      <div className="flex flex-wrap gap-3 items-center bg-g-card border border-g-border rounded-xl p-4">
        <div className="flex items-center gap-2">
          <span className="text-xs text-g-muted">Change Tier:</span>
          <select
            value={newTier || customer.tier || ''}
            onChange={e => setNewTier(e.target.value)}
            className="bg-g-deep border border-g-border rounded-lg px-2 py-1.5 text-sm text-g-text focus:outline-none focus:border-accent/50"
          >
            <option value="trial">Trial</option>
            <option value="starter">Starter</option>
            <option value="pro">Pro</option>
            <option value="elite">Elite</option>
          </select>
          <button
            onClick={handleTierSave}
            disabled={saving || !newTier || newTier === customer.tier}
            className="px-3 py-1.5 text-xs bg-accent text-black font-semibold rounded-lg disabled:opacity-30 hover:bg-accent/90 transition-colors"
          >
            {saving ? 'Saving…' : 'Save'}
          </button>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => handleStatus('active')}
            className="px-3 py-1.5 text-xs bg-green-500/20 text-green-300 border border-green-500/30 rounded-lg hover:bg-green-500/30 transition-colors"
          >
            Activate
          </button>
          <button
            onClick={() => handleStatus('suspended')}
            className="px-3 py-1.5 text-xs bg-red-500/20 text-red-300 border border-red-500/30 rounded-lg hover:bg-red-500/30 transition-colors"
          >
            Suspend
          </button>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 border-b border-g-border">
        {(['overview', 'queries', 'keys', 'preferences'] as Tab[]).map(t => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={clsx(
              'px-4 py-2 text-sm capitalize transition-colors border-b-2 -mb-px',
              tab === t
                ? 'border-accent text-accent'
                : 'border-transparent text-g-muted hover:text-g-text'
            )}
          >
            {t === 'keys' ? 'Exchange Keys' : t === 'preferences' ? 'Preferences' : t.charAt(0).toUpperCase() + t.slice(1)}
          </button>
        ))}
      </div>

      {/* Tab content */}
      {tab === 'overview' && (
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-4">
          {[
            { label: 'Queries Today', value: customer.queries_today ?? 0 },
            { label: 'Joined', value: customer.created_at
              ? formatDistanceToNow(new Date(customer.created_at), { addSuffix: true })
              : '—'
            },
            { label: 'Tier', value: customer.tier || '—' },
            { label: 'Status', value: customer.status || '—' },
          ].map(({ label, value }) => (
            <div key={label} className="bg-g-card border border-g-border rounded-xl p-4">
              <p className="text-xs text-g-muted mb-1">{label}</p>
              <p className="text-sm font-semibold text-white">{String(value)}</p>
            </div>
          ))}
        </div>
      )}

      {tab === 'queries' && (
        <DataTable
          columns={queryCols}
          data={queries}
          emptyText="No query history"
        />
      )}

      {tab === 'keys' && (
        <div className="space-y-2">
          {keys.length === 0 ? (
            <p className="text-g-muted text-sm">No exchange keys configured</p>
          ) : (
            keys.map((k: any, i: number) => (
              <div key={i} className="flex items-center justify-between bg-g-card border border-g-border rounded-xl px-4 py-3">
                <div className="flex items-center gap-2">
                  <Key size={14} className="text-g-muted" />
                  <span className="text-sm font-medium text-white capitalize">{k.exchange}</span>
                </div>
                <StatusBadge value={k.is_active ? 'active' : 'suspended'} dot />
              </div>
            ))
          )}
        </div>
      )}

      {tab === 'preferences' && (
        <div className="space-y-4">
          {/* Favorite symbols */}
          <div className="bg-g-card border border-g-border rounded-xl p-4">
            <p className="text-xs text-g-muted mb-3 flex items-center gap-1.5">
              <Star size={12} />
              Favorite Symbols
            </p>
            {!prefs.favorite_symbols?.length ? (
              <p className="text-sm text-g-muted">No favorites set</p>
            ) : (
              <div className="flex flex-wrap gap-2">
                {prefs.favorite_symbols.map((sym: string) => (
                  <span
                    key={sym}
                    className="inline-flex items-center px-3 py-1 bg-accent/10 border border-accent/20 text-accent text-xs font-mono rounded-lg"
                  >
                    {sym}
                  </span>
                ))}
              </div>
            )}
          </div>

          {/* Settings */}
          <div className="grid grid-cols-2 gap-4">
            <div className="bg-g-card border border-g-border rounded-xl p-4">
              <p className="text-xs text-g-muted mb-2 flex items-center gap-1.5">
                <Zap size={12} />
                Auto-Execute Trades
              </p>
              {prefs.auto_execute_enabled ? (
                <span className="inline-flex items-center gap-1.5 text-sm font-semibold text-green-400">
                  <span className="w-2 h-2 rounded-full bg-green-400 animate-pulse" />
                  Enabled
                </span>
              ) : (
                <span className="text-sm font-semibold text-g-muted">Disabled</span>
              )}
              <p className="text-[10px] text-g-dim mt-1">
                Auto-trades on strong signals ≥75% (Pro/Elite)
              </p>
            </div>

            <div className="bg-g-card border border-g-border rounded-xl p-4">
              <p className="text-xs text-g-muted mb-2 flex items-center gap-1.5">
                <Activity size={12} />
                Strong Signal Notify
              </p>
              {prefs.strong_signal_notify !== false ? (
                <span className="inline-flex items-center gap-1.5 text-sm font-semibold text-accent">
                  <span className="w-2 h-2 rounded-full bg-accent" />
                  Enabled
                </span>
              ) : (
                <span className="text-sm font-semibold text-g-muted">Disabled</span>
              )}
              <p className="text-[10px] text-g-dim mt-1">
                Telegram notification on strong signals for favorites
              </p>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
