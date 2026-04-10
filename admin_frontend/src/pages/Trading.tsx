import { useState, useEffect, useCallback, useMemo } from 'react'
import {
  Shield, ShieldAlert, Wifi, WifiOff, AlertTriangle, TrendingUp, TrendingDown,
  Activity, Zap, X, ChevronDown, ChevronUp, Square, Play, DollarSign,
  BarChart3, AlertCircle, CheckCircle, Target,
} from 'lucide-react'
import clsx from 'clsx'

// ═══════════════════════════════════════════════════════════════
// TYPES
// ═══════════════════════════════════════════════════════════════
interface BotStatus {
  status?: string        // only set to "OFFLINE" when offline; absent when online
  account: number
  balance?: number
  equity?: number
  bot?: string
  profile?: string
  timeframe?: string
  positions_count?: number
  error?: string
  portfolio_risk?: {
    daily_pnl: number
    bot: string
    account: number
    [key: string]: any
  }
}

interface Position {
  symbol: string
  type: string // BUY | SELL
  volume: number
  ticket: number
  entry_price?: number
  open_price?: number
  price_open?: number
  price?: number
  current_price?: number
  profit?: number
  sl: number
  tp: number
  comment?: string
  magic?: number
  swap?: number
  bot?: string
}

interface Conflict {
  symbol: string
  long_bots: string[]
  short_bots: string[]
  long_volume: number
  short_volume: number
  net_direction: string
  net_volume: number
  severity: string
}

interface CorrelationWarning {
  currency: string
  net_exposure: number
  direction: string
  severity: string
}

interface DashboardData {
  timestamp: string
  statuses: Record<string, BotStatus>
  positions: Record<string, Position[]>
  conflicts: Conflict[]
  correlation: {
    exposure: Record<string, number>
    warnings: CorrelationWarning[]
  }
  risk: {
    total_positions: number
    total_lots: number
    symbol_counts: Record<string, number>
    total_balance: number
    total_equity: number
    online_bots: number
    total_bots: number
    warnings: string[]
  }
}

interface PropFirmData {
  peak_equity: number
  initial_balance: number
  daily_start_equity: number
  halted: boolean
  halt_reason: string
  risk_mode: string
  target_reached: boolean
  risk_multiplier?: number
  friday_flatten?: boolean
  // Standard bots have config object; hydra has flat fields
  config?: {
    initial_capital: number
    profit_target_pct: number
    daily_loss_halt_pct: number
    trailing_dd_halt_pct: number
  }
  // Hydra-style flat fields
  daily_pnl?: number
  daily_pnl_pct?: number
  trailing_dd?: number
  trailing_dd_pct?: number
  total_profit?: number
  total_profit_pct?: number
  remaining_to_target?: number
  target_amount?: number
  current_balance?: number
  current_equity?: number
}

// ═══════════════════════════════════════════════════════════════
// CONSTANTS
// ═══════════════════════════════════════════════════════════════
const BOTS = [
  { name: 'cobra',    port: 8050, account: 144391, tf: 'H1',  capital: 150000, symbols: ['EURUSD', 'XAUUSD', 'USDJPY', 'BTCUSD'] },
  { name: 'anaconda', port: 8051, account: 144389, tf: 'H4',  capital: 150000, symbols: ['BTCUSD', 'EURUSD', 'USDJPY'] },
  { name: 'taipan',   port: 8055, account: 144385, tf: 'M30', capital: 150000, symbols: ['EURUSD', 'XAUUSD', 'USDJPY'] },
  { name: 'mamba',    port: 8056, account: 144387, tf: 'M15', capital: 150000, symbols: ['EURUSD', 'XAUUSD', 'USDJPY'] },
  { name: 'viper',    port: 8059, account: 144388, tf: 'M5',  capital: 150000, symbols: ['BTCUSD', 'XAUUSD'] },
  { name: 'hydra',    port: 8091, account: 143447, tf: 'M1',  capital: 100000, symbols: ['EURUSD', 'XAUUSD'] },
] as const

const TOTAL_CAPITAL = 850000

const BOT_COLORS: Record<string, { text: string; border: string; dot: string; bg: string }> = {
  cobra:    { text: 'text-orange-400', border: 'border-orange-500/25', dot: 'bg-orange-400', bg: 'bg-orange-500/10' },
  anaconda: { text: 'text-blue-400',   border: 'border-blue-500/25',   dot: 'bg-blue-400',   bg: 'bg-blue-500/10' },
  taipan:   { text: 'text-violet-400', border: 'border-violet-500/25', dot: 'bg-violet-400', bg: 'bg-violet-500/10' },
  mamba:    { text: 'text-purple-400', border: 'border-purple-500/25', dot: 'bg-purple-400', bg: 'bg-purple-500/10' },
  viper:    { text: 'text-green-400',  border: 'border-green-500/25',  dot: 'bg-green-400',  bg: 'bg-green-500/10' },
  hydra:    { text: 'text-cyan-400',   border: 'border-cyan-500/25',   dot: 'bg-cyan-400',   bg: 'bg-cyan-500/10' },
}

function getBotColor(bot: string) {
  return BOT_COLORS[bot] || { text: 'text-g-muted', border: 'border-g-border', dot: 'bg-g-muted', bg: 'bg-white/5' }
}

const RISK_MODE_COLORS: Record<string, string> = {
  normal:       'bg-green-500/20 text-green-300 border-green-500/30',
  warning:      'bg-amber-500/20 text-amber-300 border-amber-500/30',
  conservative: 'bg-orange-500/20 text-orange-300 border-orange-500/30',
  critical:     'bg-red-500/20 text-red-300 border-red-500/30',
}

// ═══════════════════════════════════════════════════════════════
// PROGRESS BAR
// ═══════════════════════════════════════════════════════════════
function ProgressBar({ value, max, color, label, valueLabel }: {
  value: number; max: number; color: string; label: string; valueLabel: string
}) {
  const pct = Math.min(Math.abs(value / max) * 100, 100)
  return (
    <div className="space-y-1">
      <div className="flex justify-between text-[11px]">
        <span className="text-g-muted">{label}</span>
        <span className={color}>{valueLabel}</span>
      </div>
      <div className="h-1.5 bg-g-deep rounded-full overflow-hidden">
        <div className={clsx('h-full rounded-full transition-all duration-500', color.replace('text-', 'bg-'))}
          style={{ width: `${pct}%` }} />
      </div>
    </div>
  )
}

// ═══════════════════════════════════════════════════════════════
// EXPOSURE BAR
// ═══════════════════════════════════════════════════════════════
function ExposureBar({ currency, value }: { currency: string; value: number }) {
  const absVal = Math.abs(value)
  const maxBar = 6
  const pct = Math.min((absVal / maxBar) * 100, 100)
  const isHigh = absVal >= 3
  const dir = value > 0 ? 'LONG' : value < 0 ? 'SHORT' : 'FLAT'
  const color = isHigh ? 'text-red-400' : value > 0 ? 'text-green-400' : value < 0 ? 'text-orange-400' : 'text-g-muted'
  const barColor = isHigh ? 'bg-red-400' : value > 0 ? 'bg-green-400' : 'bg-orange-400'

  return (
    <div className="flex items-center gap-3 text-xs">
      <span className="w-8 font-mono font-bold text-g-text">{currency}</span>
      <div className="flex-1 h-1.5 bg-g-deep rounded-full overflow-hidden">
        <div className={clsx('h-full rounded-full transition-all', barColor)}
          style={{ width: `${pct}%` }} />
      </div>
      <span className={clsx('w-24 text-right font-mono', color)}>
        {value > 0 ? '+' : ''}{value} net {dir.toLowerCase()}
      </span>
    </div>
  )
}

// ═══════════════════════════════════════════════════════════════
// CONFIRM MODAL
// ═══════════════════════════════════════════════════════════════
function ConfirmModal({ onConfirm, onCancel, loading }: {
  onConfirm: () => void; onCancel: () => void; loading: boolean
}) {
  const [typed, setTyped] = useState('')
  return (
    <div className="fixed inset-0 bg-black/70 z-50 flex items-center justify-center p-4">
      <div className="bg-g-card border border-red-500/30 rounded-xl p-6 max-w-md w-full space-y-4">
        <h3 className="text-lg font-bold text-red-400 flex items-center gap-2">
          <Zap size={20} />
          Emergency Stop All Bots
        </h3>
        <p className="text-sm text-g-text">
          This will immediately close all positions and stop all trading bots.
          This action cannot be undone.
        </p>
        <div>
          <label className="text-xs text-g-muted block mb-1">Type CONFIRM to proceed</label>
          <input
            type="text"
            value={typed}
            onChange={e => setTyped(e.target.value)}
            className="w-full bg-g-deep border border-g-border rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-red-500/50"
            placeholder="CONFIRM"
            autoFocus
          />
        </div>
        <div className="flex gap-2 justify-end">
          <button onClick={onCancel}
            className="px-4 py-2 text-sm bg-g-deep border border-g-border rounded-lg text-g-muted hover:text-white transition-colors">
            Cancel
          </button>
          <button onClick={onConfirm}
            disabled={typed !== 'CONFIRM' || loading}
            className="px-4 py-2 text-sm bg-red-500/20 border border-red-500/40 rounded-lg text-red-300 hover:bg-red-500/30 transition-colors disabled:opacity-40 disabled:cursor-not-allowed font-semibold">
            {loading ? 'Stopping...' : 'EMERGENCY STOP ALL'}
          </button>
        </div>
      </div>
    </div>
  )
}

// ═══════════════════════════════════════════════════════════════
// BOT DETAIL MODAL
// ═══════════════════════════════════════════════════════════════
function BotDetailModal({ botName, onClose }: { botName: string; onClose: () => void }) {
  const [propFirm, setPropFirm] = useState<PropFirmData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    setLoading(true)
    setError('')
    fetch(`/api/${botName}/prop_firm`)
      .then(r => { if (!r.ok) throw new Error('Failed'); return r.json() })
      .then(d => { setPropFirm(d); setLoading(false) })
      .catch(() => { setError('Failed to load prop firm data'); setLoading(false) })
  }, [botName])

  const bot = BOTS.find(b => b.name === botName)
  const c = getBotColor(botName)

  return (
    <div className="fixed inset-0 bg-black/70 z-50 flex items-center justify-center p-4" onClick={onClose}>
      <div className="bg-g-card border border-g-border rounded-xl p-6 max-w-lg w-full space-y-4" onClick={e => e.stopPropagation()}>
        <div className="flex items-center justify-between">
          <h3 className={clsx('text-lg font-bold capitalize flex items-center gap-2', c.text)}>
            <span className={clsx('w-2.5 h-2.5 rounded-full', c.dot)} />
            {botName} — Prop Firm Details
          </h3>
          <button onClick={onClose} className="text-g-muted hover:text-white"><X size={18} /></button>
        </div>

        {loading ? (
          <p className="text-g-muted text-sm py-8 text-center">Loading...</p>
        ) : error ? (
          <p className="text-red-400 text-sm py-8 text-center">{error}</p>
        ) : propFirm ? (
          <div className="space-y-3">
            <div className="grid grid-cols-2 gap-3 text-sm">
              <div className="bg-g-deep rounded-lg p-3">
                <span className="text-g-muted text-xs block">Initial Balance</span>
                <span className="text-white font-bold">${propFirm.initial_balance.toLocaleString()}</span>
              </div>
              <div className="bg-g-deep rounded-lg p-3">
                <span className="text-g-muted text-xs block">Peak Equity</span>
                <span className="text-white font-bold">${propFirm.peak_equity.toLocaleString()}</span>
              </div>
              <div className="bg-g-deep rounded-lg p-3">
                <span className="text-g-muted text-xs block">Daily Start Equity</span>
                <span className="text-white font-bold">${propFirm.daily_start_equity.toLocaleString()}</span>
              </div>
              {propFirm.current_equity != null ? (
                <div className="bg-g-deep rounded-lg p-3">
                  <span className="text-g-muted text-xs block">Current Equity</span>
                  <span className="text-white font-bold">${propFirm.current_equity.toLocaleString()}</span>
                </div>
              ) : (
                <div className="bg-g-deep rounded-lg p-3">
                  <span className="text-g-muted text-xs block">Risk Multiplier</span>
                  <span className="text-white font-bold">{propFirm.risk_multiplier ?? 1}x</span>
                </div>
              )}
            </div>

            {/* Hydra-style direct P&L metrics */}
            {propFirm.total_profit_pct != null && (
              <div className="grid grid-cols-3 gap-2 text-sm">
                <div className="bg-g-deep rounded-lg p-3">
                  <span className="text-g-muted text-xs block">Total P&L</span>
                  <span className={clsx('font-bold', (propFirm.total_profit ?? 0) >= 0 ? 'text-green-400' : 'text-red-400')}>
                    {(propFirm.total_profit ?? 0) >= 0 ? '+' : ''}${(propFirm.total_profit ?? 0).toFixed(2)}
                    <span className="text-[10px] ml-1">({propFirm.total_profit_pct.toFixed(2)}%)</span>
                  </span>
                </div>
                <div className="bg-g-deep rounded-lg p-3">
                  <span className="text-g-muted text-xs block">Daily P&L</span>
                  <span className={clsx('font-bold', (propFirm.daily_pnl ?? 0) >= 0 ? 'text-green-400' : 'text-red-400')}>
                    {(propFirm.daily_pnl ?? 0) >= 0 ? '+' : ''}${(propFirm.daily_pnl ?? 0).toFixed(2)}
                  </span>
                </div>
                <div className="bg-g-deep rounded-lg p-3">
                  <span className="text-g-muted text-xs block">Trailing DD</span>
                  <span className={clsx('font-bold', (propFirm.trailing_dd_pct ?? 0) < -3 ? 'text-red-400' : 'text-g-text')}>
                    {(propFirm.trailing_dd_pct ?? 0).toFixed(2)}%
                  </span>
                </div>
              </div>
            )}

            {propFirm.remaining_to_target != null && (
              <div className="bg-g-deep rounded-lg p-3 text-sm">
                <span className="text-g-muted text-xs block">Remaining to Target</span>
                <span className="text-accent font-bold">${propFirm.remaining_to_target.toLocaleString(undefined, { maximumFractionDigits: 2 })}</span>
                <span className="text-g-muted text-xs ml-2">(target: ${propFirm.target_amount?.toLocaleString()})</span>
              </div>
            )}

            {propFirm.halted && (
              <div className="bg-red-500/10 border border-red-500/30 rounded-lg p-3 text-red-300 text-sm font-semibold">
                HALTED — {propFirm.halt_reason}
              </div>
            )}
            {propFirm.target_reached && (
              <div className="bg-green-500/10 border border-green-500/30 rounded-lg p-3 text-green-300 text-sm font-semibold flex items-center gap-2">
                <Target size={14} /> Profit target reached!
              </div>
            )}

            <div className="grid grid-cols-2 gap-2 text-xs">
              <div className="flex justify-between bg-g-deep rounded p-2">
                <span className="text-g-muted">Risk Mode</span>
                <span className={clsx('px-2 py-0.5 rounded-full border text-[10px] font-semibold',
                  RISK_MODE_COLORS[propFirm.risk_mode] || RISK_MODE_COLORS.normal)}>
                  {propFirm.risk_mode}
                </span>
              </div>
              {propFirm.friday_flatten != null && (
                <div className="flex justify-between bg-g-deep rounded p-2">
                  <span className="text-g-muted">Friday Flatten</span>
                  <span className={propFirm.friday_flatten ? 'text-amber-400' : 'text-g-text'}>
                    {propFirm.friday_flatten ? 'Yes' : 'No'}
                  </span>
                </div>
              )}
            </div>

            <div className="border-t border-g-border pt-3 space-y-1 text-xs text-g-muted">
              {propFirm.config ? (
                <>
                  <p>Profit Target: <span className="text-g-text">{propFirm.config.profit_target_pct}%</span></p>
                  <p>Daily Loss Halt: <span className="text-g-text">{propFirm.config.daily_loss_halt_pct}%</span> (broker limit 3%)</p>
                  <p>Trailing DD Halt: <span className="text-g-text">{propFirm.config.trailing_dd_halt_pct}%</span> (broker limit 6%)</p>
                </>
              ) : (
                <>
                  <p>Profit Target: <span className="text-g-text">6.0%</span></p>
                  <p>Daily Loss Halt: <span className="text-g-text">2.5%</span> (broker limit 3%)</p>
                  <p>Trailing DD Halt: <span className="text-g-text">5.5%</span> (broker limit 6%)</p>
                </>
              )}
              <p>Account: <span className="text-g-text font-mono">{bot?.account}</span> | Timeframe: <span className="text-g-text">{bot?.tf}</span></p>
            </div>
          </div>
        ) : null}
      </div>
    </div>
  )
}

// ═══════════════════════════════════════════════════════════════
// MAIN TRADING PAGE
// ═══════════════════════════════════════════════════════════════
export default function Trading() {
  const [dashboard, setDashboard] = useState<DashboardData | null>(null)
  const [oracleOffline, setOracleOffline] = useState(false)
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null)
  const [showKillModal, setShowKillModal] = useState(false)
  const [killLoading, setKillLoading] = useState(false)
  const [detailBot, setDetailBot] = useState<string | null>(null)
  const [controlsOpen, setControlsOpen] = useState(false)
  const [botActions, setBotActions] = useState<Record<string, string>>({})

  // Per-bot prop_firm data cache for cards
  const [propFirmCache, setPropFirmCache] = useState<Record<string, PropFirmData>>({})

  // Direct-poll fallback: for bots Oracle reports as OFFLINE, hit their /status directly
  const backfillOfflineBots = useCallback(async (data: DashboardData) => {
    const offlineBots = BOTS.filter(b => {
      const s = data.statuses?.[b.name]
      return !s || s.status === 'OFFLINE'
    })
    if (offlineBots.length === 0) return data

    const patched = { ...data, statuses: { ...data.statuses }, positions: { ...data.positions } }
    await Promise.allSettled(
      offlineBots.map(async bot => {
        try {
          const res = await fetch(`/api/${bot.name}/status`)
          if (!res.ok) return
          const d = await res.json()
          // Merge direct status into dashboard — mark as direct-polled
          patched.statuses[bot.name] = {
            account: d.account ?? bot.account,
            balance: d.account_info?.balance ?? d.balance,
            equity: d.account_info?.equity ?? d.equity,
            bot: d.bot,
            timeframe: d.timeframe ?? bot.tf,
            positions_count: d.tracked_positions ?? d.positions_count ?? 0,
            portfolio_risk: d.portfolio_risk,
            // If the bot itself says it's halted, don't mark OFFLINE
            status: d.status === 'halted' ? undefined : undefined,
          }
          // Also try to get positions for this bot
          try {
            const posRes = await fetch(`/api/${bot.name}/positions`)
            if (posRes.ok) {
              const posData = await posRes.json()
              patched.positions[bot.name] = posData.positions ?? posData ?? []
            }
          } catch { /* ignore */ }
        } catch { /* bot truly unreachable */ }
      })
    )
    // Recalculate risk totals with backfilled data
    let totalBalance = 0, totalEquity = 0, totalPositions = 0, totalLots = 0, onlineBots = 0
    const symbolCounts: Record<string, number> = {}
    for (const bot of BOTS) {
      const s = patched.statuses[bot.name]
      if (s && s.status !== 'OFFLINE') {
        onlineBots++
        totalBalance += s.balance ?? 0
        totalEquity += s.equity ?? 0
      }
      const positions = patched.positions[bot.name] ?? []
      totalPositions += positions.length
      for (const p of positions) {
        totalLots += p.volume ?? 0
        symbolCounts[p.symbol] = (symbolCounts[p.symbol] ?? 0) + 1
      }
    }
    patched.risk = {
      ...patched.risk,
      total_balance: totalBalance,
      total_equity: totalEquity,
      total_positions: totalPositions,
      total_lots: totalLots,
      online_bots: onlineBots,
      total_bots: BOTS.length,
      symbol_counts: { ...patched.risk.symbol_counts, ...symbolCounts },
    }
    return patched
  }, [])

  const fetchDashboard = useCallback(async () => {
    try {
      const res = await fetch('/api/oracle/dashboard')
      if (!res.ok) { setOracleOffline(true); return }
      const data: DashboardData = await res.json()
      // Backfill any bots Oracle reports as OFFLINE by polling them directly
      const patched = await backfillOfflineBots(data)
      setDashboard(patched)
      setLastUpdated(new Date())
      setOracleOffline(false)
    } catch {
      setOracleOffline(true)
    }
  }, [backfillOfflineBots])

  // Fetch prop_firm for each bot periodically (every 30s)
  const fetchPropFirm = useCallback(async () => {
    const results: Record<string, PropFirmData> = {}
    await Promise.allSettled(
      BOTS.map(async bot => {
        try {
          const res = await fetch(`/api/${bot.name}/prop_firm`)
          if (res.ok) {
            results[bot.name] = await res.json()
          }
        } catch { /* ignore */ }
      })
    )
    if (Object.keys(results).length > 0) {
      setPropFirmCache(prev => ({ ...prev, ...results }))
    }
  }, [])

  useEffect(() => {
    fetchDashboard()
    fetchPropFirm()
    const dashInterval = setInterval(fetchDashboard, 10000)
    const propInterval = setInterval(fetchPropFirm, 30000)
    return () => { clearInterval(dashInterval); clearInterval(propInterval) }
  }, [fetchDashboard, fetchPropFirm])

  // Bot control actions
  const handleBotAction = async (action: 'start' | 'stop', botName: string) => {
    setBotActions(prev => ({ ...prev, [botName]: action === 'start' ? 'starting' : 'stopping' }))
    try {
      const res = await fetch(`/api/oracle/${action}/${botName}`, { method: 'POST' })
      if (!res.ok) throw new Error()
      setBotActions(prev => ({ ...prev, [botName]: action === 'start' ? 'started' : 'stopped' }))
      setTimeout(() => setBotActions(prev => { const n = { ...prev }; delete n[botName]; return n }), 3000)
      fetchDashboard()
    } catch {
      setBotActions(prev => ({ ...prev, [botName]: 'error' }))
      setTimeout(() => setBotActions(prev => { const n = { ...prev }; delete n[botName]; return n }), 3000)
    }
  }

  const handleKillAll = async () => {
    setKillLoading(true)
    try {
      await fetch('/api/oracle/kill', { method: 'POST' })
      setShowKillModal(false)
      fetchDashboard()
    } catch { /* */ }
    setKillLoading(false)
  }

  // Derived data — use risk totals but supplement with prop_firm data for bots Oracle missed
  const risk = dashboard?.risk
  const totalEquity = useMemo(() => {
    let eq = risk?.total_equity ?? 0
    // Add equity for bots Oracle reports offline but we have prop_firm data for
    for (const bot of BOTS) {
      const s = dashboard?.statuses?.[bot.name]
      const isOracleOffline = !s || s.status === 'OFFLINE'
      if (isOracleOffline && !(s?.balance)) {
        // Bot wasn't backfilled into risk totals — add from prop_firm cache
        const pf = propFirmCache[bot.name]
        if (pf?.current_equity) eq += pf.current_equity
      }
    }
    return eq
  }, [risk, dashboard, propFirmCache])
  const totalPnl = totalEquity - TOTAL_CAPITAL
  const totalPnlPct = TOTAL_CAPITAL > 0 ? (totalPnl / TOTAL_CAPITAL) * 100 : 0

  // All positions flat array
  const allPositions = useMemo(() => {
    if (!dashboard?.positions) return []
    const flat: (Position & { bot: string })[] = []
    for (const [bot, positions] of Object.entries(dashboard.positions)) {
      for (const p of positions) {
        flat.push({ ...p, bot })
      }
    }
    return flat
  }, [dashboard])

  // Accounts analysis
  const accountsOnTrack = useMemo(() => {
    if (!dashboard?.statuses) return 0
    return BOTS.filter(b => {
      const s = dashboard.statuses[b.name]
      const eq = s?.equity ?? propFirmCache[b.name]?.current_equity ?? 0
      return eq > b.capital
    }).length
  }, [dashboard, propFirmCache])

  const accountsAtRisk = useMemo(() => {
    if (!dashboard?.statuses || !propFirmCache) return 0
    return BOTS.filter(b => {
      const pf = propFirmCache[b.name]
      if (!pf) return false
      const s = dashboard.statuses[b.name]
      if (!s) return false
      const eq = s.equity ?? 0
      const dailyPnlPct = pf.daily_start_equity > 0
        ? ((eq - pf.daily_start_equity) / pf.daily_start_equity) * 100
        : 0
      const trailingDdPct = pf.peak_equity > 0
        ? ((eq - pf.peak_equity) / pf.peak_equity) * 100
        : 0
      return dailyPnlPct < -1.5 || trailingDdPct < -4
    }).length
  }, [dashboard, propFirmCache])

  // Global risk level
  const globalRiskLevel = useMemo(() => {
    if (!risk) return 'unknown'
    if ((risk.warnings?.length ?? 0) > 0) return 'critical'
    if ((dashboard?.conflicts?.length ?? 0) > 0) return 'warning'
    if (accountsAtRisk > 0) return 'warning'
    return 'healthy'
  }, [risk, dashboard, accountsAtRisk])

  // ═══════════════════════════════════════════════════════════════
  // ORACLE OFFLINE OVERLAY
  // ═══════════════════════════════════════════════════════════════
  if (oracleOffline && !dashboard) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <div className="text-center space-y-4">
          <div className="w-16 h-16 mx-auto rounded-full bg-red-500/20 border-2 border-red-500/40 flex items-center justify-center">
            <WifiOff size={28} className="text-red-400" />
          </div>
          <h2 className="text-xl font-bold text-red-400">Oracle Offline</h2>
          <p className="text-g-muted text-sm max-w-sm">
            Cannot reach the Oracle coordinator at <code className="text-g-text">/api/oracle/dashboard</code>.
            Retrying every 10 seconds...
          </p>
          <div className="flex items-center justify-center gap-2 text-xs text-g-muted">
            <span className="w-2 h-2 rounded-full bg-red-400 animate-pulse" />
            Attempting to reconnect
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {/* Modals */}
      {showKillModal && (
        <ConfirmModal
          onConfirm={handleKillAll}
          onCancel={() => setShowKillModal(false)}
          loading={killLoading}
        />
      )}
      {detailBot && (
        <BotDetailModal botName={detailBot} onClose={() => setDetailBot(null)} />
      )}

      {/* ══════════════════════════════════════════════════════════
          SECTION 1: CHALLENGE OVERVIEW BANNER
          ══════════════════════════════════════════════════════════ */}
      <div className="rounded-xl border border-g-border bg-g-card p-5">
        {/* Title row */}
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-3">
            <Target size={20} className="text-accent" />
            <div>
              <h1 className="text-base font-bold text-white">Prop Firm Challenge</h1>
              <p className="text-[11px] text-g-muted">GetLeveraged-Trade | 6% Target | 3% Daily Limit | 6% Trailing DD</p>
            </div>
          </div>
          <div className="flex items-center gap-2 text-xs text-g-muted">
            {lastUpdated && (
              <span className="font-mono">{lastUpdated.toLocaleTimeString()}</span>
            )}
            <span className={clsx(
              'w-2 h-2 rounded-full',
              oracleOffline ? 'bg-red-400' : 'bg-green-400 animate-pulse'
            )} />
            <span>{oracleOffline ? 'Offline' : 'Live'}</span>
          </div>
        </div>

        {/* KPIs */}
        <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-8 gap-3">
          <div className="bg-g-deep rounded-lg p-3">
            <span className="text-[10px] text-g-muted block">Total Capital</span>
            <span className="text-sm font-bold text-white">${TOTAL_CAPITAL.toLocaleString()}</span>
          </div>
          <div className="bg-g-deep rounded-lg p-3">
            <span className="text-[10px] text-g-muted block">Current Equity</span>
            <span className="text-sm font-bold text-white">${totalEquity.toLocaleString()}</span>
          </div>
          <div className="bg-g-deep rounded-lg p-3">
            <span className="text-[10px] text-g-muted block">Combined P&L</span>
            <span className={clsx('text-sm font-bold', totalPnl >= 0 ? 'text-green-400' : 'text-red-400')}>
              {totalPnl >= 0 ? '+' : ''}${totalPnl.toLocaleString(undefined, { maximumFractionDigits: 0 })}
              <span className="text-[10px] ml-1">({totalPnlPct >= 0 ? '+' : ''}{totalPnlPct.toFixed(2)}%)</span>
            </span>
          </div>
          <div className="bg-g-deep rounded-lg p-3">
            <span className="text-[10px] text-g-muted block">On Track</span>
            <span className="text-sm font-bold text-green-400">{accountsOnTrack}/6</span>
          </div>
          <div className="bg-g-deep rounded-lg p-3">
            <span className="text-[10px] text-g-muted block">At Risk</span>
            <span className={clsx('text-sm font-bold', accountsAtRisk > 0 ? 'text-red-400' : 'text-g-text')}>
              {accountsAtRisk}
            </span>
          </div>
          <div className="bg-g-deep rounded-lg p-3">
            <span className="text-[10px] text-g-muted block">Risk Level</span>
            <span className={clsx('inline-flex items-center gap-1 text-xs font-bold px-2 py-0.5 rounded-full border',
              globalRiskLevel === 'healthy'  ? 'bg-green-500/20 text-green-300 border-green-500/30' :
              globalRiskLevel === 'warning'  ? 'bg-amber-500/20 text-amber-300 border-amber-500/30' :
              globalRiskLevel === 'critical' ? 'bg-red-500/20 text-red-300 border-red-500/30' :
                                               'bg-g-deep text-g-muted border-g-border')}>
              {globalRiskLevel}
            </span>
          </div>
          <div className="bg-g-deep rounded-lg p-3">
            <span className="text-[10px] text-g-muted block">Conflicts</span>
            <span className={clsx('text-sm font-bold',
              (dashboard?.conflicts?.length ?? 0) > 0 ? 'text-red-400' : 'text-g-text')}>
              {dashboard?.conflicts?.length ?? 0}
            </span>
          </div>
          <div className="bg-g-deep rounded-lg p-3">
            <span className="text-[10px] text-g-muted block">Corr. Warnings</span>
            <span className={clsx('text-sm font-bold',
              (dashboard?.correlation?.warnings?.length ?? 0) > 0 ? 'text-amber-400' : 'text-g-text')}>
              {dashboard?.correlation?.warnings?.length ?? 0}
            </span>
          </div>
        </div>
      </div>

      {/* ══════════════════════════════════════════════════════════
          SECTION 2: BOT CARDS (2x3 grid)
          ══════════════════════════════════════════════════════════ */}
      <div>
        <h2 className="text-sm font-semibold text-white flex items-center gap-2 mb-3">
          <Activity size={15} className="text-accent" />
          Trading Bots
        </h2>
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
          {BOTS.map(bot => {
            const status = dashboard?.statuses?.[bot.name]
            const pf = propFirmCache[bot.name]
            const isOffline = !status || status.status === 'OFFLINE'
            const isOnline = !!status && status.status !== 'OFFLINE'
            const isHalted = pf?.halted === true
            const c = getBotColor(bot.name)

            const balance = status?.balance ?? pf?.current_balance ?? 0
            const equity = status?.equity ?? pf?.current_equity ?? 0
            const pnl = equity - bot.capital
            const pnlPct = bot.capital > 0 ? (pnl / bot.capital) * 100 : 0
            const posCount = dashboard?.positions?.[bot.name]?.length ?? status?.positions_count ?? 0

            // Prop firm metrics — use direct fields from prop_firm if available (hydra-style),
            // otherwise compute from equity vs daily_start_equity / peak_equity
            const dailyPnlPct = pf?.daily_pnl_pct != null
              ? pf.daily_pnl_pct
              : pf && pf.daily_start_equity > 0
                ? ((equity - pf.daily_start_equity) / pf.daily_start_equity) * 100
                : status?.portfolio_risk?.daily_pnl != null && bot.capital > 0
                  ? (status.portfolio_risk.daily_pnl / bot.capital) * 100
                  : 0
            const trailingDdPct = pf?.trailing_dd_pct != null
              ? pf.trailing_dd_pct
              : pf && pf.peak_equity > 0 && pf.peak_equity !== equity
                ? ((equity - pf.peak_equity) / pf.peak_equity) * 100
                : 0
            const targetPct = pf?.total_profit_pct != null
              ? Math.min(Math.max(pf.total_profit_pct, 0), 6)
              : pnlPct > 0 ? Math.min(pnlPct, 6) : 0
            const targetDisplay = pf?.total_profit_pct != null
              ? pf.total_profit_pct
              : pnlPct

            // Color logic for bars
            const dailyColor = Math.abs(dailyPnlPct) > 2 ? 'text-red-400' :
              Math.abs(dailyPnlPct) > 1.5 ? 'text-amber-400' : dailyPnlPct >= 0 ? 'text-green-400' : 'text-orange-400'
            const trailingColor = Math.abs(trailingDdPct) > 4.5 ? 'text-red-400' :
              Math.abs(trailingDdPct) > 3 ? 'text-amber-400' : 'text-g-muted'

            return (
              <div key={bot.name}
                className={clsx(
                  'relative rounded-xl border bg-g-card overflow-hidden transition-all cursor-pointer hover:border-g-dim',
                  isHalted ? 'border-red-500/30' : isOffline ? 'border-g-border opacity-60' : c.border
                )}
                onClick={() => setDetailBot(bot.name)}
              >
                {/* Halted overlay */}
                {isHalted && (
                  <div className="absolute inset-0 bg-red-500/10 z-10 flex items-center justify-center">
                    <div className="bg-red-500/20 border border-red-500/40 rounded-lg px-4 py-2 text-red-300 text-sm font-bold">
                      HALTED — {pf?.halt_reason || 'Unknown'}
                    </div>
                  </div>
                )}

                {/* Header */}
                <div className="px-4 py-3 border-b border-g-border/50 flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <span className={clsx('w-2 h-2 rounded-full',
                      isOnline ? 'bg-green-400 animate-pulse' :
                      isHalted ? 'bg-red-400' : 'bg-g-dim'
                    )} />
                    <span className={clsx('font-bold text-sm uppercase', c.text)}>{bot.name}</span>
                    <span className="text-[10px] text-g-muted font-mono bg-g-deep px-1.5 py-0.5 rounded">{bot.tf}</span>
                    <span className="text-[10px] text-g-dim font-mono">Acc: {bot.account}</span>
                  </div>
                  {isOffline && !isHalted && (
                    <span className="text-[10px] font-bold text-g-dim bg-g-deep px-2 py-0.5 rounded">OFFLINE</span>
                  )}
                </div>

                {/* Body */}
                <div className="px-4 py-3 space-y-3">
                  {/* Balance / Equity / Positions */}
                  <div className="space-y-1.5 text-xs">
                    <div className="flex justify-between">
                      <span className="text-g-muted">Balance</span>
                      <span className="text-white font-mono font-semibold">${balance.toLocaleString()}</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-g-muted">Equity</span>
                      <div className="flex items-center gap-2">
                        <span className="text-white font-mono font-semibold">${equity.toLocaleString()}</span>
                        <span className={clsx('font-mono text-[11px]', pnl >= 0 ? 'text-green-400' : 'text-red-400')}>
                          {pnl >= 0 ? '+' : ''}${pnl.toLocaleString(undefined, { maximumFractionDigits: 0 })}
                          ({pnlPct >= 0 ? '+' : ''}{pnlPct.toFixed(2)}%)
                        </span>
                      </div>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-g-muted">Positions</span>
                      <span className="text-white font-semibold">{posCount} open</span>
                    </div>
                  </div>

                  {/* Progress bars */}
                  <div className="space-y-2 pt-2 border-t border-g-border/50">
                    <ProgressBar
                      value={Math.abs(dailyPnlPct)} max={3}
                      color={dailyColor}
                      label="Daily P&L"
                      valueLabel={`${dailyPnlPct >= 0 ? '+' : ''}${dailyPnlPct.toFixed(2)}%`}
                    />
                    <ProgressBar
                      value={Math.abs(trailingDdPct)} max={6}
                      color={trailingColor}
                      label="Trailing DD"
                      valueLabel={`${trailingDdPct.toFixed(2)}%`}
                    />
                    <ProgressBar
                      value={targetPct} max={6}
                      color="text-accent"
                      label="Target"
                      valueLabel={`${targetDisplay.toFixed(1)}% / 6.0%`}
                    />
                  </div>

                  {/* Risk mode + status */}
                  <div className="flex items-center justify-between pt-2 border-t border-g-border/50">
                    <span className={clsx(
                      'inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-semibold border',
                      RISK_MODE_COLORS[pf?.risk_mode ?? 'normal'] || RISK_MODE_COLORS.normal
                    )}>
                      {(pf?.risk_mode ?? 'normal').toUpperCase()}
                    </span>
                    {pf?.target_reached && (
                      <span className="inline-flex items-center gap-1 text-[10px] text-green-400 font-semibold">
                        <Target size={10} /> TARGET HIT
                      </span>
                    )}
                  </div>
                </div>
              </div>
            )
          })}
        </div>
      </div>

      {/* ══════════════════════════════════════════════════════════
          SECTION 3: LIVE POSITIONS TABLE
          ══════════════════════════════════════════════════════════ */}
      <div>
        <h2 className="text-sm font-semibold text-white flex items-center gap-2 mb-3">
          <TrendingUp size={15} className="text-accent" />
          Live Positions
          {allPositions.length > 0 && (
            <span className="ml-1 inline-flex items-center justify-center min-w-[20px] h-5 px-1 bg-accent/20 text-accent text-xs rounded-full font-bold">
              {allPositions.length}
            </span>
          )}
        </h2>

        <div className="overflow-x-auto rounded-xl border border-g-border">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-g-border bg-g-deep">
                {['Bot', 'Symbol', 'Dir', 'Lots', 'Entry Price', 'Current', 'P&L', 'SL', 'TP', 'Ticket'].map(h => (
                  <th key={h} className="text-left px-4 py-3 text-xs font-semibold text-g-muted uppercase tracking-wider">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {allPositions.length === 0 ? (
                <tr>
                  <td colSpan={10} className="text-center py-8 text-g-muted text-sm">No open positions</td>
                </tr>
              ) : (
                allPositions.map((p, i) => {
                  const c = getBotColor(p.bot)
                  return (
                    <tr key={`${p.bot}-${p.ticket}-${i}`} className="border-b border-g-border/50 hover:bg-white/[0.02] transition-colors">
                      <td className="px-4 py-3">
                        <span className={clsx('inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-xs font-semibold border',
                          c.text, c.border, 'bg-white/5')}>
                          <span className={clsx('w-1.5 h-1.5 rounded-full', c.dot)} />
                          {p.bot}
                        </span>
                      </td>
                      <td className="px-4 py-3 font-mono text-sm font-semibold text-white">{p.symbol}</td>
                      <td className="px-4 py-3">
                        <span className={clsx(
                          'inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-bold border',
                          p.type === 'BUY'
                            ? 'bg-blue-500/15 text-blue-300 border-blue-500/30'
                            : 'bg-orange-500/15 text-orange-300 border-orange-500/30'
                        )}>
                          {p.type === 'BUY' ? <TrendingUp size={10} /> : <TrendingDown size={10} />}
                          {p.type}
                        </span>
                      </td>
                      <td className="px-4 py-3 font-mono text-xs text-g-text">{p.volume}</td>
                      <td className="px-4 py-3 font-mono text-xs text-g-text">{(p.open_price ?? p.price_open ?? p.entry_price)?.toFixed(5) ?? '—'}</td>
                      <td className="px-4 py-3 font-mono text-xs text-g-text">{p.current_price?.toFixed(5) ?? '—'}</td>
                      <td className={clsx('px-4 py-3 font-mono text-xs font-semibold',
                        (p.profit ?? 0) >= 0 ? 'text-green-400' : 'text-red-400')}>
                        {p.profit != null ? `${p.profit >= 0 ? '+' : ''}$${p.profit.toFixed(2)}` : '—'}
                      </td>
                      <td className="px-4 py-3 font-mono text-xs text-red-400">{p.sl?.toFixed(5) ?? '—'}</td>
                      <td className="px-4 py-3 font-mono text-xs text-green-400">{p.tp?.toFixed(5) ?? '—'}</td>
                      <td className="px-4 py-3 font-mono text-xs text-g-muted">{p.ticket ?? '—'}</td>
                    </tr>
                  )
                })
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* ══════════════════════════════════════════════════════════
          SECTION 4: RISK & ALERTS PANEL
          ══════════════════════════════════════════════════════════ */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {/* Conflicts */}
        <div className="rounded-xl border border-g-border bg-g-card p-4">
          <h3 className="text-sm font-semibold text-white flex items-center gap-2 mb-3">
            <ShieldAlert size={14} className="text-red-400" />
            Conflicts
          </h3>
          {(dashboard?.conflicts?.length ?? 0) === 0 ? (
            <div className="flex items-center gap-2 text-sm text-green-400">
              <CheckCircle size={14} />
              No conflicts
            </div>
          ) : (
            <div className="space-y-2">
              {dashboard!.conflicts.map((c, i) => (
                <div key={i} className="rounded-lg border border-red-500/20 bg-red-500/5 p-3 text-xs space-y-1">
                  <div className="flex items-center gap-2">
                    <AlertTriangle size={12} className="text-red-400 shrink-0" />
                    <span className="font-mono font-bold text-white">{c.symbol}</span>
                    <span className={clsx(
                      'px-1.5 py-0.5 rounded text-[10px] font-bold border',
                      c.severity === 'HIGH' ? 'bg-red-500/20 text-red-300 border-red-500/30' :
                        'bg-amber-500/20 text-amber-300 border-amber-500/30'
                    )}>
                      {c.severity}
                    </span>
                  </div>
                  <p className="text-g-text">
                    {c.long_bots.join(', ')} <span className="text-green-400">LONG</span> {c.long_volume.toFixed(2)}
                    {' vs '}
                    {c.short_bots.join(', ')} <span className="text-red-400">SHORT</span> {c.short_volume.toFixed(2)}
                  </p>
                  <p className="text-g-muted">
                    Net: <span className={c.net_direction === 'LONG' ? 'text-green-400' : 'text-red-400'}>
                      {c.net_direction} {c.net_volume.toFixed(2)}
                    </span>
                  </p>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Currency Exposure */}
        <div className="rounded-xl border border-g-border bg-g-card p-4">
          <h3 className="text-sm font-semibold text-white flex items-center gap-2 mb-3">
            <BarChart3 size={14} className="text-amber-400" />
            Currency Exposure
          </h3>
          {dashboard?.correlation?.exposure ? (
            <div className="space-y-2.5">
              {Object.entries(dashboard.correlation.exposure)
                .sort(([,a], [,b]) => Math.abs(b) - Math.abs(a))
                .map(([currency, value]) => (
                  <ExposureBar key={currency} currency={currency} value={value} />
                ))
              }
              {(dashboard.correlation.warnings?.length ?? 0) > 0 && (
                <div className="pt-2 border-t border-g-border/50 space-y-1">
                  {dashboard.correlation.warnings.map((w, i) => (
                    <div key={i} className={clsx(
                      'text-[11px] px-2 py-1 rounded border',
                      w.severity === 'HIGH' ? 'bg-red-500/10 text-red-300 border-red-500/20' :
                        'bg-amber-500/10 text-amber-300 border-amber-500/20'
                    )}>
                      {w.currency}: net {w.net_exposure} {w.direction} [{w.severity}]
                    </div>
                  ))}
                </div>
              )}
            </div>
          ) : (
            <p className="text-g-muted text-sm">No data</p>
          )}
        </div>

        {/* Oracle Limits */}
        <div className="rounded-xl border border-g-border bg-g-card p-4">
          <h3 className="text-sm font-semibold text-white flex items-center gap-2 mb-3">
            <Shield size={14} className="text-amber-400" />
            Oracle Limits
          </h3>
          {risk ? (
            <div className="space-y-3">
              <ProgressBar
                value={risk.total_positions} max={15}
                color={risk.total_positions > 12 ? 'text-red-400' : risk.total_positions > 8 ? 'text-amber-400' : 'text-accent'}
                label="Positions"
                valueLabel={`${risk.total_positions} / 15`}
              />
              <ProgressBar
                value={risk.total_lots} max={2.0}
                color={risk.total_lots > 1.5 ? 'text-red-400' : risk.total_lots > 1.0 ? 'text-amber-400' : 'text-accent'}
                label="Total Lots"
                valueLabel={`${risk.total_lots.toFixed(2)} / 2.0`}
              />
              <div className="pt-2 border-t border-g-border/50">
                <span className="text-[10px] text-g-muted block mb-1.5">Symbol Distribution</span>
                <div className="flex flex-wrap gap-1.5">
                  {Object.entries(risk.symbol_counts).map(([sym, count]) => (
                    <span key={sym} className="text-[10px] font-mono bg-g-deep text-g-text px-2 py-0.5 rounded border border-g-border">
                      {sym}: {count}
                    </span>
                  ))}
                </div>
              </div>
              <div className="pt-2 border-t border-g-border/50 flex justify-between text-xs">
                <span className="text-g-muted">Bots Online</span>
                <span className="text-white font-bold">{risk.online_bots}/{risk.total_bots}</span>
              </div>
              {(risk.warnings?.length ?? 0) > 0 && (
                <div className="space-y-1">
                  {risk.warnings.map((w, i) => (
                    <div key={i} className="text-[11px] bg-red-500/10 text-red-300 border border-red-500/20 rounded px-2 py-1">
                      {w}
                    </div>
                  ))}
                </div>
              )}
            </div>
          ) : (
            <p className="text-g-muted text-sm">No data</p>
          )}
        </div>
      </div>

      {/* ══════════════════════════════════════════════════════════
          SECTION 5: BOT CONTROLS
          ══════════════════════════════════════════════════════════ */}
      <div className="rounded-xl border border-g-border bg-g-card">
        <button
          onClick={() => setControlsOpen(o => !o)}
          className="w-full px-4 py-3 flex items-center justify-between hover:bg-white/[0.02] transition-colors"
        >
          <h2 className="text-sm font-semibold text-white flex items-center gap-2">
            <Shield size={15} className="text-amber-400" />
            Bot Controls
          </h2>
          {controlsOpen ? <ChevronUp size={14} className="text-g-muted" /> : <ChevronDown size={14} className="text-g-muted" />}
        </button>

        {controlsOpen && (
          <div className="px-4 pb-4 space-y-3">
            {/* Per-bot rows */}
            <div className="space-y-2">
              {BOTS.map(bot => {
                const status = dashboard?.statuses?.[bot.name]
                const isOnline = !!status && status.status !== 'OFFLINE'
                const c = getBotColor(bot.name)
                const actionState = botActions[bot.name]

                return (
                  <div key={bot.name} className="flex items-center gap-3 bg-g-deep rounded-lg px-4 py-2.5">
                    <span className={clsx('w-20 font-bold text-sm uppercase', c.text)}>{bot.name}</span>
                    <span className={clsx(
                      'w-2 h-2 rounded-full',
                      isOnline ? 'bg-green-400 animate-pulse' : 'bg-g-dim'
                    )} />
                    <span className="text-xs text-g-muted flex-1">
                      {isOnline ? 'Running' : status?.status || 'Offline'}
                    </span>

                    {actionState && (
                      <span className={clsx('text-[10px] font-mono',
                        actionState === 'error' ? 'text-red-400' :
                        actionState === 'started' || actionState === 'stopped' ? 'text-green-400' :
                        'text-amber-400'
                      )}>
                        {actionState}
                      </span>
                    )}

                    <button
                      onClick={(e) => { e.stopPropagation(); handleBotAction('start', bot.name) }}
                      disabled={!!actionState && actionState !== 'error'}
                      className="flex items-center gap-1 px-3 py-1.5 text-xs bg-green-500/15 text-green-300 border border-green-500/25 rounded-lg hover:bg-green-500/25 transition-colors disabled:opacity-40"
                    >
                      <Play size={10} />
                      Start
                    </button>
                    <button
                      onClick={(e) => { e.stopPropagation(); handleBotAction('stop', bot.name) }}
                      disabled={!!actionState && actionState !== 'error'}
                      className="flex items-center gap-1 px-3 py-1.5 text-xs bg-orange-500/15 text-orange-300 border border-orange-500/25 rounded-lg hover:bg-orange-500/25 transition-colors disabled:opacity-40"
                    >
                      <Square size={10} />
                      Stop
                    </button>
                  </div>
                )
              })}
            </div>

            {/* Emergency kill */}
            <div className="pt-3 border-t border-g-border/50">
              <button
                onClick={() => setShowKillModal(true)}
                className="flex items-center gap-2 px-4 py-2.5 bg-red-500/15 text-red-300 border border-red-500/30 rounded-lg hover:bg-red-500/25 transition-colors font-bold text-sm w-full justify-center"
              >
                <Zap size={16} />
                EMERGENCY STOP ALL
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
