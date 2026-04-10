import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { getSignals, getEnsemble, getTrades } from '../api/endpoints'
import DataTable, { Column } from '../components/ui/DataTable'
import StatusBadge from '../components/ui/StatusBadge'
import {
  Activity, TrendingUp, TrendingDown, RefreshCw,
  Zap, ChevronLeft, ChevronRight, Bot,
} from 'lucide-react'
import { formatDistanceToNow } from 'date-fns'
import clsx from 'clsx'

// ── Confidence bar ──────────────────────────────────────────────────────────
function ConfidenceBar({ confidence, consensus }: { confidence: number; consensus: string }) {
  const pct   = Math.round(confidence * 100)
  const color =
    consensus === 'BUY'  ? 'bg-green-500' :
    consensus === 'SELL' ? 'bg-red-500'   : 'bg-yellow-500'
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-1.5 bg-white/10 rounded-full overflow-hidden">
        <div className={clsx('h-full rounded-full transition-all', color)} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs font-mono text-g-muted w-8 text-right">{pct}%</span>
    </div>
  )
}

// ── Signal card ─────────────────────────────────────────────────────────────
function SignalCard({ symbol, data }: { symbol: string; data: any }) {
  const consensus  = data.consensus || 'HOLD'
  const confidence = data.confidence || 0
  const price      = data.price ?? data.current_price
  const ts         = data.timestamp || data.generated_at
  const isStrong   = confidence >= 0.75
  const isBuy      = consensus === 'BUY'
  const isSell     = consensus === 'SELL'

  return (
    <div className={clsx(
      'bg-g-card border rounded-xl p-4 flex flex-col gap-3',
      isBuy  && isStrong ? 'border-green-500/30' :
      isSell && isStrong ? 'border-red-500/30'   : 'border-g-border'
    )}>
      <div className="flex items-center justify-between">
        <span className="font-mono font-bold text-white text-sm">{symbol}</span>
        <span className={clsx(
          'inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-bold border',
          isBuy  ? 'bg-green-500/20 text-green-300 border-green-500/30' :
          isSell ? 'bg-red-500/20   text-red-300   border-red-500/30'   :
                   'bg-yellow-500/20 text-yellow-300 border-yellow-500/30'
        )}>
          {isBuy  && <TrendingUp   size={10} />}
          {isSell && <TrendingDown size={10} />}
          {consensus}
        </span>
      </div>

      <ConfidenceBar confidence={confidence} consensus={consensus} />

      {price != null && (
        <div className="text-xs text-g-muted font-mono">
          ${typeof price === 'number'
            ? price.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 6 })
            : price}
        </div>
      )}

      <div className="flex items-center justify-between">
        {isStrong && consensus !== 'HOLD' ? (
          <span className="flex items-center gap-1 text-[10px] text-amber-400 font-medium">
            <Zap size={10} />
            Strong signal
          </span>
        ) : <span />}
        {ts && (
          <span className="text-[10px] text-g-dim">
            {formatDistanceToNow(new Date(ts), { addSuffix: true })}
          </span>
        )}
      </div>
    </div>
  )
}

// ── Main Signals page ───────────────────────────────────────────────────────
export default function Signals() {
  const [tradePage, setTradePage] = useState(1)

  const { data: signals = {}, refetch: refetchSignals, isFetching: signalsFetching } = useQuery({
    queryKey: ['signals'],
    queryFn:  getSignals,
    refetchInterval: 30_000,
  })

  const { data: ensemble } = useQuery({
    queryKey: ['ensemble'],
    queryFn:  getEnsemble,
    refetchInterval: 30_000,
  })

  const { data: tradesData, isLoading: tradesLoading } = useQuery({
    queryKey: ['trades', tradePage],
    queryFn:  () => getTrades(tradePage, 20),
    refetchInterval: 60_000,
  })

  const trades          = tradesData?.trades || []
  const tradesTotal     = tradesData?.total  || 0
  const tradeTotalPages = Math.ceil(tradesTotal / 20)

  const signalEntries = Object.entries(signals as Record<string, any>)
    .sort(([a], [b]) => a.localeCompare(b))

  // ── Trade table columns ─────────────────────────────────────────────────
  const tradeCols: Column<any>[] = [
    { key: 'customer', label: 'Customer', render: r => (
      <span className="font-medium text-white">{r.username || `#${r.customer_id}`}</span>
    )},
    { key: 'symbol', label: 'Symbol', render: r => (
      <span className="font-mono font-bold text-sm text-white">{r.symbol}</span>
    )},
    { key: 'direction', label: 'Dir', render: r => (
      <span className={clsx(
        'inline-flex items-center gap-0.5 text-xs font-bold',
        r.direction === 'BUY' ? 'text-green-400' : 'text-red-400'
      )}>
        {r.direction === 'BUY'
          ? <TrendingUp  size={11} />
          : <TrendingDown size={11} />}
        {r.direction}
      </span>
    )},
    { key: 'entry_price', label: 'Entry', render: r => (
      <span className="font-mono text-xs">
        {r.entry_price != null
          ? Number(r.entry_price).toLocaleString(undefined, { maximumFractionDigits: 6 })
          : '—'}
      </span>
    )},
    { key: 'sl_price', label: 'SL', render: r => (
      <span className="font-mono text-xs text-red-400">
        {r.sl_price != null
          ? Number(r.sl_price).toLocaleString(undefined, { maximumFractionDigits: 6 })
          : '—'}
      </span>
    )},
    { key: 'tp_price', label: 'TP', render: r => (
      <span className="font-mono text-xs text-green-400">
        {r.tp_price != null
          ? Number(r.tp_price).toLocaleString(undefined, { maximumFractionDigits: 6 })
          : '—'}
      </span>
    )},
    { key: 'volume',        label: 'Volume',  render: r => <span className="font-mono text-xs">{r.volume ?? '—'}</span> },
    { key: 'ensemble_vote', label: 'Signal',  render: r => <span className="text-xs text-g-muted">{r.ensemble_vote || '—'}</span> },
    { key: 'status',        label: 'Status',  render: r => <StatusBadge value={r.status || 'pending'} dot /> },
    { key: 'created_at',    label: 'Time',    render: r => r.created_at
      ? formatDistanceToNow(new Date(r.created_at), { addSuffix: true })
      : '—'
    },
  ]

  return (
    <div className="space-y-6">

      {/* ── Ensemble Engine Health ──────────────────────────────────────── */}
      <div className="bg-g-card border border-g-border rounded-xl px-4 py-3 flex items-center gap-4 flex-wrap">
        <span className="text-sm font-semibold text-white flex items-center gap-2">
          <Activity size={15} className="text-accent" />
          Ensemble Engine
        </span>

        {ensemble ? (
          <>
            <StatusBadge value={ensemble.health?.status || 'unknown'} dot />
            <span className="text-xs text-g-muted">
              Cached signals:{' '}
              <span className="text-g-text font-medium">
                {Object.keys(ensemble.signals || {}).length}
              </span>
            </span>
            {ensemble.health?.uptime_seconds != null && (
              <span className="text-xs text-g-muted">
                Uptime:{' '}
                <span className="text-g-text">
                  {Math.round(ensemble.health.uptime_seconds / 60)}m
                </span>
              </span>
            )}
          </>
        ) : (
          <span className="text-xs text-g-muted">Connecting…</span>
        )}

        <button
          onClick={() => refetchSignals()}
          disabled={signalsFetching}
          className="ml-auto text-g-muted hover:text-white transition-colors disabled:opacity-50"
          title="Refresh signals"
        >
          <RefreshCw size={13} className={clsx(signalsFetching && 'animate-spin')} />
        </button>
      </div>

      {/* ── Live AI Signals Grid ────────────────────────────────────────── */}
      <div>
        <h2 className="text-sm font-semibold text-white flex items-center gap-2 mb-3">
          <Zap size={15} className="text-accent" />
          Live AI Signals
          <span className="text-xs text-g-muted font-normal">· refreshes every 30s</span>
          {signalEntries.length > 0 && (
            <span className="ml-1 inline-flex items-center justify-center min-w-[20px] h-5 px-1 bg-accent/20 text-accent text-xs rounded-full font-bold border border-accent/30">
              {signalEntries.length}
            </span>
          )}
        </h2>

        {signalEntries.length === 0 ? (
          <div className="bg-g-card border border-g-border rounded-xl px-4 py-8 text-center">
            <Activity size={24} className="text-g-dim mx-auto mb-2" />
            <p className="text-g-muted text-sm">No signals in cache yet</p>
            <p className="text-g-dim text-xs mt-1">The ensemble engine generates signals every 5 minutes</p>
          </div>
        ) : (
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3">
            {signalEntries.map(([symbol, data]) => (
              <SignalCard key={symbol} symbol={symbol} data={data} />
            ))}
          </div>
        )}
      </div>

      {/* ── Auto-Execute Trades ──────────────────────────────────────────── */}
      <div>
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-sm font-semibold text-white flex items-center gap-2">
            <Bot size={15} className="text-accent" />
            Auto-Execute Trades
            {tradesTotal > 0 && (
              <span className="ml-1 inline-flex items-center justify-center min-w-[20px] h-5 px-1 bg-accent/20 text-accent text-xs rounded-full font-bold border border-accent/30">
                {tradesTotal}
              </span>
            )}
          </h2>
        </div>

        <DataTable
          columns={tradeCols}
          data={trades}
          loading={tradesLoading}
          emptyText="No auto-executed trades yet"
          dateField="created_at"
        />

        {tradeTotalPages > 1 && (
          <div className="flex items-center justify-between mt-3">
            <button
              onClick={() => setTradePage(p => Math.max(1, p - 1))}
              disabled={tradePage === 1}
              className="flex items-center gap-1 px-3 py-1.5 text-sm text-g-muted hover:text-white disabled:opacity-30 transition-colors"
            >
              <ChevronLeft size={14} /> Prev
            </button>
            <span className="text-sm text-g-muted">Page {tradePage} of {tradeTotalPages}</span>
            <button
              onClick={() => setTradePage(p => Math.min(tradeTotalPages, p + 1))}
              disabled={tradePage === tradeTotalPages}
              className="flex items-center gap-1 px-3 py-1.5 text-sm text-g-muted hover:text-white disabled:opacity-30 transition-colors"
            >
              Next <ChevronRight size={14} />
            </button>
          </div>
        )}
      </div>

    </div>
  )
}
