import { useState, useEffect, useRef } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  getCC_Containers, restartContainer,
  getCC_System, getCC_Redis, getCC_Postgres, getCC_Logs,
} from '../../api/endpoints'
import {
  RefreshCw, Cpu, HardDrive, MemoryStick, Database,
  Activity, Terminal, AlertTriangle, CheckCircle2, XCircle, Clock,
} from 'lucide-react'
import clsx from 'clsx'

// ── helpers ──────────────────────────────────────────────────────────────────
function fmtUptime(s: number) {
  if (!s) return '—'
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  if (h > 0) return `${h}h ${m}m`
  return `${m}m`
}

function fmtShortName(name: string) {
  return name.replace('glitch-', '')
}

function StatusDot({ status, health }: { status: string; health: string }) {
  if (status === 'running' && health === 'healthy')
    return <span className="w-2 h-2 rounded-full bg-accent inline-block" />
  if (status === 'running' && (health === 'starting' || health === 'none'))
    return <span className="w-2 h-2 rounded-full bg-yellow-400 inline-block" />
  if (status === 'running' && health === 'unhealthy')
    return <span className="w-2 h-2 rounded-full bg-orange-400 inline-block" />
  return <span className="w-2 h-2 rounded-full bg-red-500 inline-block" />
}

function ResourceBar({ value, label, color = 'accent' }: { value: number; label: string; color?: string }) {
  const cls = color === 'red'    ? 'bg-red-500'
            : color === 'yellow' ? 'bg-yellow-400'
            : 'bg-accent'
  return (
    <div>
      <div className="flex justify-between text-xs text-g-muted mb-1">
        <span>{label}</span><span>{value.toFixed(1)}%</span>
      </div>
      <div className="h-1.5 rounded-full bg-white/10">
        <div
          className={clsx('h-1.5 rounded-full transition-all', cls)}
          style={{ width: `${Math.min(value, 100)}%` }}
        />
      </div>
    </div>
  )
}

// ── Container card ────────────────────────────────────────────────────────────
function ContainerCard({ c, onRestart }: { c: any; onRestart: (name: string) => void }) {
  const [confirming, setConfirming] = useState(false)
  const borderCls =
    c.status === 'running' && c.health === 'healthy'   ? 'border-accent/20'
  : c.status === 'running' && c.health !== 'unhealthy' ? 'border-yellow-400/20'
  : c.status === 'running'                              ? 'border-orange-400/20'
  :                                                       'border-red-500/30'

  return (
    <div className={clsx('rounded-xl p-4 border bg-g-card flex flex-col gap-3', borderCls)}>
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <StatusDot status={c.status} health={c.health} />
          <span className="font-mono text-sm text-white font-medium">{fmtShortName(c.name)}</span>
        </div>
        <span className={clsx('text-xs px-2 py-0.5 rounded-full font-medium',
          c.status === 'running' ? 'bg-accent/10 text-accent' : 'bg-red-500/10 text-red-400'
        )}>
          {c.status}
        </span>
      </div>

      <div className="grid grid-cols-2 gap-2 text-xs text-g-muted">
        <div><span className="text-g-dim">CPU</span> <span className="text-white">{c.cpu_percent}%</span></div>
        <div><span className="text-g-dim">RAM</span> <span className="text-white">{c.mem_mb}MB</span></div>
        <div><span className="text-g-dim">Uptime</span> <span className="text-white">{fmtUptime(c.uptime_seconds)}</span></div>
        <div><span className="text-g-dim">Health</span> <span className={clsx('font-medium',
          c.health === 'healthy' ? 'text-accent' : c.health === 'unhealthy' ? 'text-red-400' : 'text-yellow-400'
        )}>{c.health}</span></div>
      </div>

      {confirming ? (
        <div className="flex gap-2">
          <button
            onClick={() => { onRestart(c.name); setConfirming(false) }}
            className="flex-1 text-xs py-1.5 rounded-lg bg-red-500/20 text-red-400 hover:bg-red-500/30 transition-colors font-medium"
          >
            Confirm Restart
          </button>
          <button
            onClick={() => setConfirming(false)}
            className="flex-1 text-xs py-1.5 rounded-lg bg-white/5 text-g-muted hover:bg-white/10 transition-colors"
          >
            Cancel
          </button>
        </div>
      ) : (
        <button
          onClick={() => setConfirming(true)}
          className="w-full text-xs py-1.5 rounded-lg bg-white/5 text-g-muted hover:text-white hover:bg-white/10 transition-colors flex items-center justify-center gap-1.5"
        >
          <RefreshCw size={11} /> Restart
        </button>
      )}
    </div>
  )
}

// ── Log viewer ────────────────────────────────────────────────────────────────
const SERVICES = [
  'telegram-bot','ensemble','executor','payment','admin-api','postgres','redis','dashboard',
]

function LogViewer() {
  const [service, setService] = useState('telegram-bot')
  const preRef = useRef<HTMLPreElement>(null)
  const { data, isFetching, refetch } = useQuery({
    queryKey: ['cc:logs', service],
    queryFn: () => getCC_Logs(service, 50),
    refetchInterval: 30_000,
  })

  useEffect(() => {
    if (preRef.current) preRef.current.scrollTop = preRef.current.scrollHeight
  }, [data])

  return (
    <div className="rounded-xl border border-g-border bg-g-card p-4 flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Terminal size={15} className="text-accent" />
          <span className="text-sm font-semibold text-white">Container Logs</span>
        </div>
        <div className="flex items-center gap-2">
          <select
            value={service}
            onChange={e => setService(e.target.value)}
            className="text-xs bg-g-deep border border-g-border rounded-lg px-2 py-1.5 text-g-text"
          >
            {SERVICES.map(s => <option key={s} value={s}>{s}</option>)}
          </select>
          <button
            onClick={() => refetch()}
            className="p-1.5 rounded-lg bg-white/5 hover:bg-white/10 text-g-muted hover:text-white transition-colors"
          >
            <RefreshCw size={13} className={isFetching ? 'animate-spin' : ''} />
          </button>
        </div>
      </div>
      <pre
        ref={preRef}
        className="h-64 overflow-y-auto text-[11px] font-mono leading-relaxed text-g-muted bg-black/30 rounded-lg p-3 whitespace-pre-wrap break-all"
      >
        {data?.content || data?.error || 'No logs'}
      </pre>
    </div>
  )
}

// ── Main page ─────────────────────────────────────────────────────────────────
export default function ControlCentre() {
  const qc = useQueryClient()

  const { data: containers = [], isLoading: loadingContainers } = useQuery({
    queryKey: ['cc:containers'],
    queryFn: getCC_Containers,
    refetchInterval: 15_000,
  })
  const { data: sys } = useQuery({
    queryKey: ['cc:system'],
    queryFn: getCC_System,
    refetchInterval: 15_000,
  })
  const { data: redis } = useQuery({
    queryKey: ['cc:redis'],
    queryFn: getCC_Redis,
    refetchInterval: 20_000,
  })
  const { data: pg } = useQuery({
    queryKey: ['cc:postgres'],
    queryFn: getCC_Postgres,
    refetchInterval: 30_000,
  })

  const restartMut = useMutation({
    mutationFn: restartContainer,
    onSuccess: () => {
      setTimeout(() => qc.invalidateQueries({ queryKey: ['cc:containers'] }), 3000)
    },
  })

  const healthy = Array.isArray(containers)
    ? containers.filter((c: any) => c.status === 'running' && c.health === 'healthy').length
    : 0
  const total = Array.isArray(containers) ? containers.length : 0

  return (
    <div className="p-6 space-y-6 max-w-7xl mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">Control Centre</h1>
          <p className="text-g-muted text-sm mt-1">System health, containers & infrastructure</p>
        </div>
        <div className="flex items-center gap-2 text-sm">
          <CheckCircle2 size={14} className="text-accent" />
          <span className="text-accent font-medium">{healthy}</span>
          <span className="text-g-muted">/ {total} healthy</span>
        </div>
      </div>

      {/* System resources */}
      {sys && (
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
          <div className="rounded-xl border border-g-border bg-g-card p-4 space-y-3">
            <div className="flex items-center gap-2 text-sm font-semibold text-white">
              <Cpu size={15} className="text-accent" /> CPU
            </div>
            <ResourceBar
              value={sys.cpu_percent}
              label="Usage"
              color={sys.cpu_percent > 80 ? 'red' : sys.cpu_percent > 60 ? 'yellow' : 'accent'}
            />
          </div>
          <div className="rounded-xl border border-g-border bg-g-card p-4 space-y-3">
            <div className="flex items-center gap-2 text-sm font-semibold text-white">
              <MemoryStick size={15} className="text-accent" /> Memory
            </div>
            <ResourceBar
              value={sys.memory.percent}
              label={`${sys.memory.used_gb}GB / ${sys.memory.total_gb}GB`}
              color={sys.memory.percent > 85 ? 'red' : sys.memory.percent > 70 ? 'yellow' : 'accent'}
            />
          </div>
          <div className="rounded-xl border border-g-border bg-g-card p-4 space-y-3">
            <div className="flex items-center gap-2 text-sm font-semibold text-white">
              <HardDrive size={15} className="text-accent" /> Disk
            </div>
            <ResourceBar
              value={sys.disk.percent}
              label={`${sys.disk.used_gb}GB / ${sys.disk.total_gb}GB`}
              color={sys.disk.percent > 90 ? 'red' : sys.disk.percent > 75 ? 'yellow' : 'accent'}
            />
          </div>
        </div>
      )}

      {/* Redis + Postgres stats */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <div className="rounded-xl border border-g-border bg-g-card p-4 space-y-3">
          <div className="flex items-center gap-2 text-sm font-semibold text-white">
            <Activity size={15} className="text-accent" /> Redis
          </div>
          {redis?.error ? (
            <p className="text-xs text-red-400">{redis.error}</p>
          ) : redis ? (
            <div className="grid grid-cols-2 gap-3 text-xs">
              <Stat label="Keys" value={redis.key_count} />
              <Stat label="Clients" value={redis.connected_clients} />
              <Stat label="Used" value={`${redis.used_memory_mb} MB`} />
              <Stat label="Peak" value={`${redis.peak_memory_mb} MB`} />
            </div>
          ) : <p className="text-xs text-g-dim">Loading…</p>}
        </div>

        <div className="rounded-xl border border-g-border bg-g-card p-4 space-y-3">
          <div className="flex items-center gap-2 text-sm font-semibold text-white">
            <Database size={15} className="text-accent" /> PostgreSQL
          </div>
          {pg?.error ? (
            <p className="text-xs text-red-400">{pg.error}</p>
          ) : pg ? (
            <div className="grid grid-cols-2 gap-3 text-xs">
              <Stat label="Connections" value={pg.connections} />
              <Stat label="DB Size" value={pg.db_size} />
              {Object.entries(pg.by_state || {}).map(([k, v]: any) => (
                <Stat key={k} label={k} value={v} />
              ))}
            </div>
          ) : <p className="text-xs text-g-dim">Loading…</p>}
        </div>
      </div>

      {/* Container grid */}
      <div>
        <h2 className="text-sm font-semibold text-g-muted uppercase tracking-wider mb-3">Containers</h2>
        {loadingContainers ? (
          <p className="text-g-dim text-sm">Loading containers…</p>
        ) : (
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3">
            {(Array.isArray(containers) ? containers : []).map((c: any) => (
              <ContainerCard
                key={c.name}
                c={c}
                onRestart={name => restartMut.mutate(name)}
              />
            ))}
          </div>
        )}
        {restartMut.isPending && (
          <p className="text-xs text-yellow-400 mt-2">Restarting container…</p>
        )}
      </div>

      {/* Log viewer */}
      <LogViewer />
    </div>
  )
}

function Stat({ label, value }: { label: string; value: any }) {
  return (
    <div>
      <p className="text-g-dim">{label}</p>
      <p className="text-white font-medium">{value}</p>
    </div>
  )
}
