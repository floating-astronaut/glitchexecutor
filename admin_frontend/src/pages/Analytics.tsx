import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  LineChart, Line, BarChart, Bar,
  XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, Cell, Legend,
} from 'recharts'
import {
  Brain, TrendingUp, TrendingDown, Target,
  BarChart2, Activity, Layers, RefreshCw, Minus,
  Wifi, WifiOff, DollarSign, Briefcase, Search,
} from 'lucide-react'
import { format, parseISO } from 'date-fns'
import clsx from 'clsx'
import DataTable, { Column } from '../components/ui/DataTable'
import KpiCard from '../components/ui/KpiCard'
import {
  getAnalyticsOverview,
  getAnalyticsTimeline,
  getAnalyticsModelAccuracy,
  getAnalyticsConfidenceDist,
  getAnalyticsCorrelation,
  getAnalyticsHistory,
  getAnalyticsLive,
  getIBStatus,
  getIBAccount,
  getIBPositions,
  getIBHistorical,
} from '../api/endpoints'

// ── Constants ─────────────────────────────────────────────────────────────────

const TIME_OPTIONS = [
  { label: '24H', days: 1 },
  { label: '7D',  days: 7 },
  { label: '30D', days: 30 },
]

const MODELS = [
  'TrendFollower', 'MeanReverter', 'MomentumHunter',
  'MLPredictor', 'MultiTFAlign', 'VolumeProfiler', 'SessionAnalyst',
]

const MODEL_SHORT: Record<string, string> = {
  TrendFollower:  'Trend',
  MeanReverter:   'MeanRev',
  MomentumHunter: 'Momentum',
  MLPredictor:    'ML Pred',
  MultiTFAlign:   'MultiTF',
  VolumeProfiler: 'Volume',
  SessionAnalyst: 'Session',
}

// Vote pill styling
function votePill(vote: string | undefined) {
  if (!vote) return <span className="px-1.5 py-0.5 rounded text-[10px] bg-white/5 text-g-dim">—</span>
  const cls =
    vote === 'BUY'  ? 'bg-green-500/20 text-green-300 border border-green-500/30' :
    vote === 'SELL' ? 'bg-red-500/20   text-red-300   border border-red-500/30'   :
                      'bg-white/5      text-g-muted   border border-g-border'
  return <span className={`px-1.5 py-0.5 rounded text-[10px] font-medium ${cls}`}>{vote}</span>
}

const ACCENT     = '#00ff88'
const CHART_GRID = '#1e2330'
const CHART_TEXT = '#6e7681'

// ── Helpers ───────────────────────────────────────────────────────────────────

function corrCellClass(v: number | null, isSelf: boolean): string {
  if (isSelf)   return 'bg-accent/10 text-accent font-semibold'
  if (v === null) return 'bg-white/3 text-g-dim'
  if (v >= 80)  return 'bg-green-500/25 text-green-300'
  if (v >= 65)  return 'bg-green-500/15 text-green-400'
  if (v >= 50)  return 'bg-yellow-500/15 text-yellow-400'
  return 'bg-white/5 text-g-muted'
}

function consensusBadge(c: string | null) {
  if (!c) return <span className="text-g-dim">—</span>
  const cls =
    c === 'BUY'  ? 'text-green-400 bg-green-500/10 border border-green-500/20' :
    c === 'SELL' ? 'text-red-400   bg-red-500/10   border border-red-500/20'   :
                   'text-g-muted   bg-white/5      border border-g-border'
  return <span className={clsx('px-2 py-0.5 rounded text-xs font-medium', cls)}>{c}</span>
}

function outcomeIcon(correct: boolean | null | undefined) {
  if (correct === null || correct === undefined)
    return <Minus size={12} className="text-g-dim" />
  return correct
    ? <TrendingUp   size={12} className="text-green-400" />
    : <TrendingDown size={12} className="text-red-400"   />
}

function pctColor(pct: number | null | undefined) {
  if (pct == null) return 'text-g-dim'
  return pct >= 0 ? 'text-green-400' : 'text-red-400'
}

// ── Custom Recharts Tooltips ──────────────────────────────────────────────────

function TimelineTooltip({ active, payload, label }: any) {
  if (!active || !payload?.length) return null
  const d = payload[0].payload
  return (
    <div className="bg-g-card border border-g-border rounded-lg px-3 py-2 text-xs shadow-xl">
      <p className="text-g-muted mb-1">{label}</p>
      <p className="text-accent font-mono">{d.confidence}% confidence</p>
      <p className="text-g-text">{d.count} prediction{d.count !== 1 ? 's' : ''}</p>
      {d.consensus && <p className="text-g-muted mt-0.5">Consensus: {d.consensus}</p>}
    </div>
  )
}

function BarTooltip({ active, payload, label }: any) {
  if (!active || !payload?.length) return null
  return (
    <div className="bg-g-card border border-g-border rounded-lg px-3 py-2 text-xs shadow-xl">
      <p className="text-g-muted mb-1">{label}</p>
      {payload.map((p: any) => (
        <p key={p.dataKey} style={{ color: p.fill }} className="font-mono">
          {p.name}: {p.value != null ? `${p.value}%` : '—'}
        </p>
      ))}
    </div>
  )
}

// ── Section Card wrapper ──────────────────────────────────────────────────────

function SectionCard({ title, icon: Icon, children, className = '' }: {
  title: string
  icon: any
  children: React.ReactNode
  className?: string
}) {
  return (
    <div className={clsx('bg-g-card border border-g-border rounded-xl p-4', className)}>
      <div className="flex items-center gap-2 mb-4">
        <Icon size={14} className="text-accent" />
        <h3 className="text-sm font-semibold text-g-text">{title}</h3>
      </div>
      {children}
    </div>
  )
}

function LoadingBox() {
  return (
    <div className="h-52 flex items-center justify-center text-g-muted text-sm">
      <RefreshCw size={14} className="animate-spin mr-2" /> Loading…
    </div>
  )
}

// ── Main Page ─────────────────────────────────────────────────────────────────

// ── IB preset symbols ─────────────────────────────────────────────────────────
const IB_PRESETS = [
  { label: 'AAPL',   symbol: 'AAPL',   sec_type: 'STK',   exchange: 'SMART',    currency: 'USD' },
  { label: 'NVDA',   symbol: 'NVDA',   sec_type: 'STK',   exchange: 'SMART',    currency: 'USD' },
  { label: 'TSLA',   symbol: 'TSLA',   sec_type: 'STK',   exchange: 'SMART',    currency: 'USD' },
  { label: 'SPY',    symbol: 'SPY',    sec_type: 'STK',   exchange: 'SMART',    currency: 'USD' },
  { label: 'EURUSD', symbol: 'EURUSD', sec_type: 'FOREX', exchange: 'IDEALPRO', currency: 'USD' },
  { label: 'GBPUSD', symbol: 'GBPUSD', sec_type: 'FOREX', exchange: 'IDEALPRO', currency: 'USD' },
  { label: 'BTC',    symbol: 'BTC',    sec_type: 'CRYPTO', exchange: 'PAXOS',   currency: 'USD' },
  { label: 'ETH',    symbol: 'ETH',    sec_type: 'CRYPTO', exchange: 'PAXOS',   currency: 'USD' },
]

const BAR_SIZES  = ['1 min', '5 mins', '15 mins', '1 hour', '4 hours', '1 day']
const DURATIONS  = ['1 D', '1 W', '1 M', '3 M', '6 M', '1 Y']

export default function Analytics() {
  const [days, setDays] = useState(7)

  // IB chart controls
  const [ibSymbol,   setIbSymbol]   = useState('AAPL')
  const [ibSecType,  setIbSecType]  = useState('STK')
  const [ibExchange, setIbExchange] = useState('SMART')
  const [ibCurrency, setIbCurrency] = useState('USD')
  const [ibBarSize,  setIbBarSize]  = useState('1 day')
  const [ibDuration, setIbDuration] = useState('3 M')
  const [ibFetch,    setIbFetch]    = useState(false)   // trigger on demand

  const q = { refetchInterval: 60_000 }

  const { data: overview, isLoading: loadOv } = useQuery({
    queryKey: ['an-overview', days],
    queryFn:  () => getAnalyticsOverview(days),
    ...q,
  })
  const { data: timeline = [], isLoading: loadTl } = useQuery({
    queryKey: ['an-timeline', days],
    queryFn:  () => getAnalyticsTimeline(days),
    ...q,
  })
  const { data: modelAcc, isLoading: loadAcc } = useQuery({
    queryKey: ['an-model-acc', days],
    queryFn:  () => getAnalyticsModelAccuracy(days),
    ...q,
  })
  const { data: confDist = [], isLoading: loadDist } = useQuery({
    queryKey: ['an-conf-dist', days],
    queryFn:  () => getAnalyticsConfidenceDist(days),
    ...q,
  })
  const { data: corr, isLoading: loadCorr } = useQuery({
    queryKey: ['an-corr', days],
    queryFn:  () => getAnalyticsCorrelation(days),
    ...q,
  })
  const { data: history = [], isLoading: loadHist } = useQuery({
    queryKey: ['an-history', days],
    queryFn:  () => getAnalyticsHistory(days, 200),
    ...q,
  })

  const { data: liveData = [], isLoading: loadLive } = useQuery({
    queryKey: ['an-live'],
    queryFn:  () => getAnalyticsLive(),
    refetchInterval: 30_000,
  })

  // IB queries
  const { data: ibStatus,    isLoading: loadIBStatus }    = useQuery({ queryKey: ['ib-status'],    queryFn: getIBStatus,    refetchInterval: 60_000 })
  const { data: ibAccount,   isLoading: loadIBAccount }   = useQuery({ queryKey: ['ib-account'],   queryFn: getIBAccount,   refetchInterval: 60_000 })
  const { data: ibPositions, isLoading: loadIBPositions } = useQuery({ queryKey: ['ib-positions'], queryFn: getIBPositions, refetchInterval: 60_000 })
  const { data: ibChart, isLoading: loadIBChart, refetch: refetchIBChart } = useQuery({
    queryKey: ['ib-hist', ibSymbol, ibSecType, ibExchange, ibCurrency, ibBarSize, ibDuration],
    queryFn: () => getIBHistorical({ symbol: ibSymbol, sec_type: ibSecType, exchange: ibExchange, currency: ibCurrency, bar_size: ibBarSize, duration: ibDuration }),
    enabled: ibFetch,
    staleTime: 60_000,
  })

  // Model accuracy → flat chart rows
  const accChartData = MODELS.map(m => ({
    name: MODEL_SHORT[m] || m,
    '1h':  modelAcc?.[m]?.['1h']  ?? null,
    '4h':  modelAcc?.[m]?.['4h']  ?? null,
    '24h': modelAcc?.[m]?.['24h'] ?? null,
  }))

  // Timeline x-axis label
  const tlLabel = (v: string) => {
    try {
      const d = parseISO(v)
      return days <= 1 ? format(d, 'HH:mm') : days <= 7 ? format(d, 'EEE HH:mm') : format(d, 'MMM d')
    } catch { return v }
  }

  // Consensus breakdown
  const breakdown = (overview?.consensus_breakdown ?? {}) as Record<string, number>
  const totalBd   = Object.values(breakdown).reduce((a, b) => a + b, 0)

  // History table columns
  const histCols: Column<any>[] = [
    {
      key: 'predicted_at', label: 'Time',
      render: r => (
        <span className="font-mono text-xs text-g-muted">
          {format(parseISO(r.predicted_at), 'MMM d HH:mm')}
        </span>
      ),
    },
    {
      key: 'symbol', label: 'Symbol',
      render: r => <span className="font-mono text-xs text-accent">{r.symbol}</span>,
    },
    {
      key: 'price', label: 'Price',
      render: r => (
        <span className="font-mono text-xs text-g-text">
          {r.price != null
            ? `$${Number(r.price).toLocaleString(undefined, { maximumFractionDigits: 2 })}`
            : '—'}
        </span>
      ),
    },
    {
      key: 'consensus', label: 'Signal',
      render: r => consensusBadge(r.consensus),
    },
    {
      key: 'confidence', label: 'Confidence',
      render: r => (
        <div className="flex items-center gap-2">
          <div className="w-14 bg-white/10 rounded-full h-1.5">
            <div
              className="h-1.5 rounded-full bg-accent"
              style={{ width: `${Math.min(r.confidence ?? 0, 100)}%` }}
            />
          </div>
          <span className="font-mono text-xs text-g-text">
            {r.confidence != null ? `${r.confidence.toFixed(0)}%` : '—'}
          </span>
        </div>
      ),
    },
    {
      key: 'bullish_count', label: 'Bulls / Bears',
      render: r => (
        <span className="font-mono text-xs">
          <span className="text-green-400">{r.bullish_count}↑</span>
          <span className="text-g-dim mx-1">/</span>
          <span className="text-red-400">{r.bearish_count}↓</span>
        </span>
      ),
    },
    {
      key: 'sentiment_direction', label: 'Sentiment',
      render: r => {
        const s = r.sentiment_direction
        if (!s) return <span className="text-g-dim text-xs">—</span>
        return (
          <span className={clsx('text-xs capitalize',
            s === 'bullish' ? 'text-green-400' : s === 'bearish' ? 'text-red-400' : 'text-g-muted'
          )}>
            {s}
          </span>
        )
      },
    },
    {
      key: 'correct_1h', label: '1H Result',
      render: r => (
        <div className="flex items-center gap-1.5">
          {outcomeIcon(r.correct_1h)}
          <span className={clsx('font-mono text-xs', pctColor(r.pct_1h))}>
            {r.pct_1h != null
              ? `${r.pct_1h >= 0 ? '+' : ''}${r.pct_1h.toFixed(2)}%`
              : '—'}
          </span>
        </div>
      ),
    },
    {
      key: 'correct_4h', label: '4H Result',
      render: r => (
        <div className="flex items-center gap-1.5">
          {outcomeIcon(r.correct_4h)}
          <span className={clsx('font-mono text-xs', pctColor(r.pct_4h))}>
            {r.pct_4h != null
              ? `${r.pct_4h >= 0 ? '+' : ''}${r.pct_4h.toFixed(2)}%`
              : '—'}
          </span>
        </div>
      ),
    },
  ]

  // ── Render ──────────────────────────────────────────────────────────────────
  return (
    <div className="space-y-5">

      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center gap-3 justify-between">
        <div>
          <h1 className="text-lg font-bold text-white flex items-center gap-2">
            <Brain size={18} className="text-accent" />
            AI Ensemble Analytics
          </h1>
          <p className="text-xs text-g-muted mt-0.5">
            Multi-model signal performance · {overview?.total_predictions ?? '—'} predictions in range
          </p>
        </div>
        {/* Time range */}
        <div className="flex items-center gap-1 bg-g-card border border-g-border rounded-lg p-1">
          {TIME_OPTIONS.map(opt => (
            <button
              key={opt.days}
              onClick={() => setDays(opt.days)}
              className={clsx(
                'px-3 py-1.5 rounded-md text-xs font-medium transition-colors',
                days === opt.days
                  ? 'bg-accent/15 text-accent'
                  : 'text-g-muted hover:text-g-text hover:bg-white/5'
              )}
            >
              {opt.label}
            </button>
          ))}
        </div>
      </div>

      {/* ── Live Ensemble State ── */}
      <SectionCard title="Live Ensemble State" icon={Brain}>
        {loadLive ? (
          <LoadingBox />
        ) : liveData.length === 0 ? (
          <div className="h-24 flex items-center justify-center text-g-muted text-sm">
            No active symbols in Redis — ensemble may not be running
          </div>
        ) : (
          <div className="space-y-4">
            {/* Per-symbol cards */}
            <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
              {liveData.map((sym: any) => {
                const bullish = Object.values(sym.votes as Record<string, string>).filter(v => v === 'BUY').length
                const bearish = Object.values(sym.votes as Record<string, string>).filter(v => v === 'SELL').length
                const neutral = Object.values(sym.votes as Record<string, string>).filter(v => v === 'HOLD').length
                const conf    = sym.confidence ?? 0
                const sentCls = sym.sentiment_direction === 'bullish' ? 'text-green-400' :
                                 sym.sentiment_direction === 'bearish' ? 'text-red-400' : 'text-g-muted'
                const ttlPct  = sym.ttl_seconds != null ? Math.round((sym.ttl_seconds / 600) * 100) : 100

                return (
                  <div key={sym.symbol} className="bg-g-deep border border-g-border rounded-xl p-3 space-y-3">
                    {/* Symbol header */}
                    <div className="flex items-center justify-between">
                      <div>
                        <span className="font-mono font-bold text-accent text-sm">{sym.symbol}</span>
                        {sym.price != null && (
                          <span className="ml-2 font-mono text-xs text-g-text">
                            ${Number(sym.price).toLocaleString(undefined, { maximumFractionDigits: 2 })}
                          </span>
                        )}
                      </div>
                      <div className="flex items-center gap-2">
                        {sym.sentiment_direction && (
                          <span className={clsx('text-[10px] capitalize', sentCls)}>
                            {sym.sentiment_direction}
                          </span>
                        )}
                        {consensusBadge(sym.consensus)}
                      </div>
                    </div>

                    {/* Confidence bar */}
                    <div>
                      <div className="flex justify-between text-[10px] text-g-muted mb-1">
                        <span>Confidence</span>
                        <span className="font-mono text-accent">{conf.toFixed(0)}%</span>
                      </div>
                      <div className="h-1.5 bg-white/10 rounded-full overflow-hidden">
                        <div className="h-full rounded-full bg-accent transition-all" style={{ width: `${conf}%` }} />
                      </div>
                    </div>

                    {/* Vote tally */}
                    <div className="flex items-center gap-3 text-[10px]">
                      <span className="text-green-400 font-mono">{bullish} BUY</span>
                      <span className="text-red-400   font-mono">{bearish} SELL</span>
                      <span className="text-g-muted   font-mono">{neutral} HOLD</span>
                    </div>

                    {/* Per-model votes grid */}
                    <div className="grid grid-cols-2 gap-x-4 gap-y-1">
                      {MODELS.map(m => (
                        <div key={m} className="flex items-center justify-between">
                          <span className="text-[10px] text-g-muted truncate">{MODEL_SHORT[m]}</span>
                          {votePill((sym.votes as any)[m])}
                        </div>
                      ))}
                    </div>

                    {/* Redis TTL footer */}
                    <div>
                      <div className="flex justify-between text-[10px] text-g-dim mb-1">
                        <span>Cache TTL</span>
                        <span className="font-mono">{sym.ttl_seconds != null ? `${sym.ttl_seconds}s` : '—'}</span>
                      </div>
                      <div className="h-0.5 bg-white/10 rounded-full overflow-hidden">
                        <div
                          className={clsx('h-full rounded-full transition-all',
                            ttlPct > 50 ? 'bg-accent' : ttlPct > 20 ? 'bg-yellow-500' : 'bg-red-500'
                          )}
                          style={{ width: `${ttlPct}%` }}
                        />
                      </div>
                    </div>
                  </div>
                )
              })}
            </div>

            {/* All-symbol model vote matrix (heatmap table) */}
            {liveData.length > 1 && (
              <div className="overflow-x-auto mt-2">
                <p className="text-[10px] text-g-dim mb-2">All symbols × models vote matrix</p>
                <table className="text-[10px] border-collapse w-full">
                  <thead>
                    <tr>
                      <th className="text-left text-g-dim font-normal pb-1 pr-3 whitespace-nowrap">Symbol</th>
                      {MODELS.map(m => (
                        <th key={m} className="text-center text-g-muted font-normal pb-1 px-1 whitespace-nowrap">
                          {MODEL_SHORT[m]}
                        </th>
                      ))}
                      <th className="text-center text-g-muted font-normal pb-1 px-1">Consensus</th>
                    </tr>
                  </thead>
                  <tbody>
                    {liveData.map((sym: any) => (
                      <tr key={sym.symbol}>
                        <td className="font-mono text-accent pr-3 py-0.5 whitespace-nowrap">{sym.symbol}</td>
                        {MODELS.map(m => (
                          <td key={m} className="text-center py-0.5 px-1">
                            {votePill((sym.votes as any)[m])}
                          </td>
                        ))}
                        <td className="text-center py-0.5 px-1">{consensusBadge(sym.consensus)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}
      </SectionCard>

      {/* ── Interactive Brokers ── */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">

        {/* IB Status + Account */}
        <SectionCard title="IB Gateway" icon={ibStatus?.connected ? Wifi : WifiOff}>
          {loadIBStatus ? <div className="h-20 flex items-center justify-center"><RefreshCw size={14} className="animate-spin text-g-muted" /></div> : (
            <div className="space-y-3">
              <div className="flex items-center gap-2">
                <span className={clsx('w-2 h-2 rounded-full', ibStatus?.connected ? 'bg-green-400 animate-pulse' : 'bg-red-500')} />
                <span className={clsx('text-sm font-medium', ibStatus?.connected ? 'text-green-400' : 'text-red-400')}>
                  {ibStatus?.connected ? 'Connected' : 'Disconnected'}
                </span>
                <span className="text-g-dim text-xs font-mono ml-auto">{ibStatus?.host}:{ibStatus?.port}</span>
              </div>
              {ibStatus?.connected && (
                <div className="text-[11px] text-g-muted space-y-1">
                  <div className="flex justify-between"><span>Server Version</span><span className="font-mono text-g-text">{ibStatus.server_version}</span></div>
                  <div className="flex justify-between"><span>Account</span><span className="font-mono text-g-text">{ibAccount?.account ?? '—'}</span></div>
                </div>
              )}
              {/* Account summary */}
              {!loadIBAccount && ibAccount && ibStatus?.connected && (
                <div className="pt-2 border-t border-g-border grid grid-cols-2 gap-y-1.5 text-[11px]">
                  {[
                    ['Net Liq',     ibAccount.NetLiquidation,   'USD'],
                    ['Cash',        ibAccount.TotalCashValue,    'USD'],
                    ['Buying Power',ibAccount.BuyingPower,       'USD'],
                    ['Unreal P&L',  ibAccount.UnrealizedPnL,     'USD'],
                    ['Real P&L',    ibAccount.RealizedPnL,       'USD'],
                    ['Gross Pos',   ibAccount.GrossPositionValue,'USD'],
                  ].map(([label, val, cur]) => (
                    <div key={label as string}>
                      <p className="text-g-dim">{label}</p>
                      <p className={clsx('font-mono font-medium',
                        typeof val === 'number' && (label as string).includes('P&L')
                          ? val >= 0 ? 'text-green-400' : 'text-red-400'
                          : 'text-g-text'
                      )}>
                        {typeof val === 'number'
                          ? `$${val.toLocaleString(undefined, { maximumFractionDigits: 0 })}`
                          : '—'}
                      </p>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </SectionCard>

        {/* IB Positions */}
        <SectionCard title="IB Positions" icon={Briefcase} className="lg:col-span-2">
          {loadIBPositions ? <LoadingBox /> : !ibStatus?.connected ? (
            <div className="h-20 flex items-center justify-center text-g-muted text-sm">IB not connected</div>
          ) : !ibPositions?.length ? (
            <div className="h-20 flex items-center justify-center text-g-muted text-sm">No open positions</div>
          ) : (
            <div className="overflow-x-auto">
              <table className="text-xs w-full border-collapse">
                <thead>
                  <tr className="text-g-dim text-left">
                    {['Symbol','Type','Exchange','Currency','Qty','Avg Cost','Mkt Value'].map(h => (
                      <th key={h} className="pb-2 pr-3 font-normal whitespace-nowrap">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {ibPositions.map((p: any, i: number) => (
                    <tr key={i} className="border-t border-g-border/50 hover:bg-white/3 transition-colors">
                      <td className="py-1.5 pr-3 font-mono text-accent font-medium">{p.symbol}</td>
                      <td className="py-1.5 pr-3 text-g-muted">{p.sec_type}</td>
                      <td className="py-1.5 pr-3 text-g-muted">{p.exchange || '—'}</td>
                      <td className="py-1.5 pr-3 text-g-muted">{p.currency}</td>
                      <td className={clsx('py-1.5 pr-3 font-mono font-medium', p.position > 0 ? 'text-green-400' : 'text-red-400')}>
                        {p.position > 0 ? '+' : ''}{p.position}
                      </td>
                      <td className="py-1.5 pr-3 font-mono text-g-text">
                        {p.avg_cost != null ? `$${Number(p.avg_cost).toFixed(2)}` : '—'}
                      </td>
                      <td className="py-1.5 font-mono text-g-text">
                        {p.market_value != null ? `$${p.market_value.toLocaleString(undefined, {maximumFractionDigits: 0})}` : '—'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </SectionCard>
      </div>

      {/* IB Historical Chart */}
      <SectionCard title="IB Historical Data" icon={BarChart2}>
        {/* Controls */}
        <div className="flex flex-wrap gap-2 mb-4">
          {/* Symbol presets */}
          <div className="flex gap-1 flex-wrap">
            {IB_PRESETS.map(p => (
              <button
                key={p.label}
                onClick={() => { setIbSymbol(p.symbol); setIbSecType(p.sec_type); setIbExchange(p.exchange); setIbCurrency(p.currency) }}
                className={clsx('px-2 py-1 rounded text-xs font-mono transition-colors border',
                  ibSymbol === p.symbol
                    ? 'bg-accent/15 text-accent border-accent/30'
                    : 'bg-white/5 text-g-muted border-g-border hover:text-g-text'
                )}
              >
                {p.label}
              </button>
            ))}
          </div>
          {/* Bar size */}
          <select
            value={ibBarSize}
            onChange={e => setIbBarSize(e.target.value)}
            className="bg-g-deep border border-g-border rounded px-2 py-1 text-xs text-g-text focus:outline-none focus:border-accent/50"
          >
            {BAR_SIZES.map(s => <option key={s} value={s}>{s}</option>)}
          </select>
          {/* Duration */}
          <select
            value={ibDuration}
            onChange={e => setIbDuration(e.target.value)}
            className="bg-g-deep border border-g-border rounded px-2 py-1 text-xs text-g-text focus:outline-none focus:border-accent/50"
          >
            {DURATIONS.map(d => <option key={d} value={d}>{d}</option>)}
          </select>
          {/* Fetch button */}
          <button
            onClick={() => { setIbFetch(true); setTimeout(() => refetchIBChart(), 50) }}
            disabled={loadIBChart}
            className="flex items-center gap-1.5 px-3 py-1 rounded bg-accent/15 text-accent border border-accent/30 text-xs font-medium hover:bg-accent/25 transition-colors disabled:opacity-50"
          >
            {loadIBChart ? <RefreshCw size={11} className="animate-spin" /> : <Search size={11} />}
            {loadIBChart ? 'Fetching…' : 'Fetch'}
          </button>
        </div>

        {/* Chart */}
        {!ibFetch ? (
          <div className="h-48 flex items-center justify-center text-g-muted text-sm">
            Select a symbol and click Fetch to load historical data
          </div>
        ) : loadIBChart ? (
          <LoadingBox />
        ) : !ibChart?.bars?.length ? (
          <div className="h-48 flex items-center justify-center text-g-muted text-sm">No data returned</div>
        ) : (
          <div>
            <div className="flex items-center justify-between mb-2 text-xs text-g-muted">
              <span className="font-mono text-accent font-medium">{ibChart.symbol}</span>
              <span>{ibChart.bars.length} bars · {ibChart.bar_size} · {ibChart.duration}</span>
            </div>
            <ResponsiveContainer width="100%" height={220}>
              <LineChart data={ibChart.bars} margin={{ top: 5, right: 8, left: -10, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke={CHART_GRID} />
                <XAxis
                  dataKey="time"
                  tickFormatter={(v: string) => { try { return format(parseISO(v), ibBarSize.includes('min') ? 'HH:mm' : ibDuration === '1 D' ? 'HH:mm' : 'MMM d') } catch { return v } }}
                  tick={{ fill: CHART_TEXT, fontSize: 10 }}
                  axisLine={{ stroke: CHART_GRID }}
                  tickLine={false}
                  interval="preserveStartEnd"
                />
                <YAxis
                  domain={['auto', 'auto']}
                  tick={{ fill: CHART_TEXT, fontSize: 10 }}
                  axisLine={false}
                  tickLine={false}
                  tickFormatter={(v: number) => v >= 1000 ? `${(v/1000).toFixed(0)}k` : v.toFixed(2)}
                />
                <Tooltip
                  contentStyle={{ background: '#111318', border: '1px solid #1e2330', borderRadius: 8, fontSize: 11 }}
                  labelStyle={{ color: CHART_TEXT }}
                  formatter={(v: any, name: string) => [`${Number(v).toFixed(4)}`, name]}
                />
                <Legend wrapperStyle={{ fontSize: '10px', color: CHART_TEXT }} />
                <Line type="monotone" dataKey="close" name="Close" stroke={ACCENT}     strokeWidth={2} dot={false} activeDot={{ r: 3 }} />
                <Line type="monotone" dataKey="high"  name="High"  stroke="#3b82f6"   strokeWidth={1} dot={false} strokeDasharray="3 3" />
                <Line type="monotone" dataKey="low"   name="Low"   stroke="#ef4444"   strokeWidth={1} dot={false} strokeDasharray="3 3" />
              </LineChart>
            </ResponsiveContainer>
          </div>
        )}
      </SectionCard>

      {/* KPI Row */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <KpiCard
          label="Total Predictions"
          value={loadOv ? '…' : (overview?.total_predictions ?? 0)}
          icon={Brain}
        />
        <KpiCard
          label="Avg Confidence"
          value={loadOv ? '…' : `${overview?.avg_confidence ?? 0}%`}
          icon={Target}
          accent
        />
        <KpiCard
          label="1H Win Rate"
          value={loadOv ? '…' : (overview?.win_rate_1h != null ? `${overview.win_rate_1h}%` : 'No data')}
          icon={TrendingUp}
          trend={overview?.win_rate_1h != null ? (overview.win_rate_1h >= 50 ? 'up' : 'down') : 'neutral'}
        />
        <KpiCard
          label="4H Win Rate"
          value={loadOv ? '…' : (overview?.win_rate_4h != null ? `${overview.win_rate_4h}%` : 'No data')}
          icon={Activity}
          trend={overview?.win_rate_4h != null ? (overview.win_rate_4h >= 50 ? 'up' : 'down') : 'neutral'}
        />
      </div>

      {/* Confidence Timeline + Consensus Breakdown */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">

        <SectionCard title="Confidence Timeline" icon={Activity} className="lg:col-span-2">
          {loadTl ? <LoadingBox /> : timeline.length === 0 ? (
            <div className="h-52 flex items-center justify-center text-g-muted text-sm">
              No data for this period
            </div>
          ) : (
            <ResponsiveContainer width="100%" height={210}>
              <LineChart data={timeline} margin={{ top: 5, right: 8, left: -20, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke={CHART_GRID} />
                <XAxis
                  dataKey="time"
                  tickFormatter={tlLabel}
                  tick={{ fill: CHART_TEXT, fontSize: 10 }}
                  axisLine={{ stroke: CHART_GRID }}
                  tickLine={false}
                  interval="preserveStartEnd"
                />
                <YAxis
                  domain={[0, 100]}
                  tick={{ fill: CHART_TEXT, fontSize: 10 }}
                  axisLine={false}
                  tickLine={false}
                />
                <Tooltip content={<TimelineTooltip />} />
                <Line
                  type="monotone"
                  dataKey="confidence"
                  stroke={ACCENT}
                  strokeWidth={2}
                  dot={false}
                  activeDot={{ r: 4, fill: ACCENT }}
                />
              </LineChart>
            </ResponsiveContainer>
          )}
        </SectionCard>

        <SectionCard title="AI Consensus" icon={Layers}>
          {loadOv ? <LoadingBox /> : (
            <div className="space-y-3 mt-2">
              {(['BUY', 'SELL', 'HOLD'] as const).map(dir => {
                const count = breakdown[dir] ?? 0
                const pct   = totalBd > 0 ? Math.round((count / totalBd) * 100) : 0
                const bar   = dir === 'BUY' ? 'bg-green-500' : dir === 'SELL' ? 'bg-red-500' : 'bg-g-dim'
                const txt   = dir === 'BUY' ? 'text-green-400' : dir === 'SELL' ? 'text-red-400' : 'text-g-muted'
                return (
                  <div key={dir}>
                    <div className="flex justify-between text-xs mb-1">
                      <span className={clsx('font-medium', txt)}>{dir}</span>
                      <span className="text-g-muted font-mono">
                        {count} <span className="text-g-dim">({pct}%)</span>
                      </span>
                    </div>
                    <div className="h-2 bg-white/10 rounded-full overflow-hidden">
                      <div className={clsx('h-full rounded-full transition-all', bar)} style={{ width: `${pct}%` }} />
                    </div>
                  </div>
                )
              })}
              <div className="pt-3 border-t border-g-border space-y-2">
                <div className="flex justify-between text-xs">
                  <span className="text-g-muted">24H Win Rate</span>
                  <span className={clsx('font-mono font-medium',
                    overview?.win_rate_24h != null
                      ? overview.win_rate_24h >= 50 ? 'text-green-400' : 'text-red-400'
                      : 'text-g-dim'
                  )}>
                    {overview?.win_rate_24h != null ? `${overview.win_rate_24h}%` : '—'}
                  </span>
                </div>
                <div className="flex justify-between text-xs">
                  <span className="text-g-muted">Avg Confidence</span>
                  <span className="font-mono text-accent font-medium">{overview?.avg_confidence ?? '—'}%</span>
                </div>
              </div>
            </div>
          )}
        </SectionCard>
      </div>

      {/* Model Accuracy + Confidence Distribution */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">

        <SectionCard title="AI Source Accuracy" icon={BarChart2} className="lg:col-span-2">
          {loadAcc ? <LoadingBox /> : (
            <ResponsiveContainer width="100%" height={210}>
              <BarChart data={accChartData} margin={{ top: 5, right: 8, left: -20, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke={CHART_GRID} vertical={false} />
                <XAxis
                  dataKey="name"
                  tick={{ fill: CHART_TEXT, fontSize: 9 }}
                  axisLine={{ stroke: CHART_GRID }}
                  tickLine={false}
                />
                <YAxis
                  domain={[0, 100]}
                  tick={{ fill: CHART_TEXT, fontSize: 10 }}
                  axisLine={false}
                  tickLine={false}
                />
                <Tooltip content={<BarTooltip />} />
                <Legend wrapperStyle={{ fontSize: '10px', color: CHART_TEXT, paddingTop: '8px' }} />
                <Bar dataKey="1h"  name="1H"  fill="#00ff88" radius={[2,2,0,0]} maxBarSize={14} />
                <Bar dataKey="4h"  name="4H"  fill="#3b82f6" radius={[2,2,0,0]} maxBarSize={14} />
                <Bar dataKey="24h" name="24H" fill="#a855f7" radius={[2,2,0,0]} maxBarSize={14} />
              </BarChart>
            </ResponsiveContainer>
          )}
        </SectionCard>

        <SectionCard title="Confidence Distribution" icon={BarChart2}>
          {loadDist ? <LoadingBox /> : (
            <ResponsiveContainer width="100%" height={210}>
              <BarChart data={confDist} margin={{ top: 5, right: 8, left: -28, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke={CHART_GRID} vertical={false} />
                <XAxis
                  dataKey="range"
                  tick={{ fill: CHART_TEXT, fontSize: 8 }}
                  axisLine={{ stroke: CHART_GRID }}
                  tickLine={false}
                  interval={1}
                />
                <YAxis
                  tick={{ fill: CHART_TEXT, fontSize: 10 }}
                  axisLine={false}
                  tickLine={false}
                />
                <Tooltip
                  contentStyle={{ background: '#111318', border: '1px solid #1e2330', borderRadius: 8, fontSize: 11 }}
                  labelStyle={{ color: CHART_TEXT }}
                  itemStyle={{ color: ACCENT }}
                />
                <Bar dataKey="count" name="Predictions" radius={[2,2,0,0]}>
                  {confDist.map((_: any, i: number) => (
                    <Cell key={i} fill={`rgba(0,255,136,${0.25 + (i / confDist.length) * 0.65})`} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          )}
        </SectionCard>
      </div>

      {/* AI Source Correlation Matrix */}
      <SectionCard title="AI Source Correlation Matrix" icon={Brain}>
        {loadCorr ? <LoadingBox /> : !corr ? (
          <div className="h-40 flex items-center justify-center text-g-muted text-sm">No data</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="text-xs border-collapse w-full">
              <thead>
                <tr>
                  <th className="w-20 text-left text-g-dim pb-2 pr-2 font-normal" />
                  {MODELS.map(m => (
                    <th key={m} className="text-center text-g-muted font-normal pb-2 px-0.5 min-w-[60px]">
                      {MODEL_SHORT[m]}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {MODELS.map(m1 => (
                  <tr key={m1}>
                    <td className="text-g-muted pr-2 py-0.5 whitespace-nowrap font-medium">{MODEL_SHORT[m1]}</td>
                    {MODELS.map(m2 => {
                      const val    = corr.matrix?.[m1]?.[m2] ?? null
                      const isSelf = m1 === m2
                      return (
                        <td key={m2} className="py-0.5 px-0.5">
                          <div className={clsx(
                            'rounded flex items-center justify-center h-8 text-xs font-mono',
                            corrCellClass(val, isSelf)
                          )}>
                            {val !== null ? `${val}%` : '—'}
                          </div>
                        </td>
                      )
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="text-[10px] text-g-dim mt-2">
              % of predictions where both models voted the same direction.
              Green = high agreement · Yellow = moderate · Diagonal = self (100%)
            </p>
          </div>
        )}
      </SectionCard>

      {/* Prediction History */}
      <SectionCard title="Prediction History" icon={Activity}>
        <DataTable
          columns={histCols}
          data={history}
          keyField="id"
          loading={loadHist}
          dateField="predicted_at"
          defaultPageSize={25}
          emptyText="No predictions in this period"
        />
      </SectionCard>

    </div>
  )
}
