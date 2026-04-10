import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { getServices, getSystem, getLogs } from '../api/endpoints'
import StatusBadge from '../components/ui/StatusBadge'
import { Server, Cpu, HardDrive, MemoryStick, RefreshCw } from 'lucide-react'

function ProgressBar({ label, value, color = 'bg-accent' }: { label: string; value: number; color?: string }) {
  return (
    <div>
      <div className="flex justify-between text-xs text-g-muted mb-1">
        <span>{label}</span>
        <span>{value}%</span>
      </div>
      <div className="h-2 bg-g-border rounded-full overflow-hidden">
        <div
          className={`h-full rounded-full transition-all ${color}`}
          style={{ width: `${Math.min(100, value)}%` }}
        />
      </div>
    </div>
  )
}

export default function Infrastructure() {
  const [logService, setLogService] = useState('payment')
  const [logLines, setLogLines] = useState(100)
  const [logContent, setLogContent] = useState<string | null>(null)
  const [logLoading, setLogLoading] = useState(false)

  const { data: services = [], isLoading: svcLoading, refetch: refetchSvc } = useQuery({
    queryKey: ['services'],
    queryFn: getServices,
    refetchInterval: 30_000,
  })

  const { data: system } = useQuery({
    queryKey: ['system'],
    queryFn: getSystem,
    refetchInterval: 10_000,
  })

  const fetchLogs = async () => {
    setLogLoading(true)
    try {
      const res = await getLogs(logService, logLines)
      setLogContent(res.content || res.error || 'No output')
    } finally {
      setLogLoading(false)
    }
  }

  const cpuColor = (system?.cpu_percent ?? 0) > 80 ? 'bg-red-400' : (system?.cpu_percent ?? 0) > 60 ? 'bg-yellow-400' : 'bg-accent'
  const memColor = (system?.memory?.percent ?? 0) > 85 ? 'bg-red-400' : (system?.memory?.percent ?? 0) > 70 ? 'bg-yellow-400' : 'bg-accent'
  const diskColor = (system?.disk?.percent ?? 0) > 90 ? 'bg-red-400' : (system?.disk?.percent ?? 0) > 75 ? 'bg-yellow-400' : 'bg-accent'

  return (
    <div className="space-y-6">
      {/* System metrics */}
      <div className="bg-g-card border border-g-border rounded-xl p-5">
        <h2 className="text-sm font-semibold text-white mb-4 flex items-center gap-2">
          <Cpu size={16} className="text-accent" />
          System Metrics
        </h2>
        {system ? (
          <div className="space-y-4">
            <ProgressBar label={`CPU — ${system.cpu_percent}%`} value={system.cpu_percent} color={cpuColor} />
            <ProgressBar
              label={`Memory — ${system.memory.used_gb}GB / ${system.memory.total_gb}GB`}
              value={system.memory.percent}
              color={memColor}
            />
            <ProgressBar
              label={`Disk — ${system.disk.used_gb}GB / ${system.disk.total_gb}GB`}
              value={system.disk.percent}
              color={diskColor}
            />
          </div>
        ) : (
          <p className="text-g-muted text-sm">Loading system metrics…</p>
        )}
      </div>

      {/* Services */}
      <div>
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-sm font-semibold text-white flex items-center gap-2">
            <Server size={16} className="text-accent" />
            Services
          </h2>
          <button
            onClick={() => refetchSvc()}
            className="text-g-muted hover:text-white transition-colors"
            title="Refresh"
          >
            <RefreshCw size={14} />
          </button>
        </div>

        {svcLoading ? (
          <p className="text-g-muted text-sm">Loading…</p>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
            {(Array.isArray(services) ? services : []).map((svc: any) => (
              <div key={svc.name} className="bg-g-card border border-g-border rounded-xl p-4">
                <div className="flex items-center justify-between mb-2">
                  <span className="font-mono text-xs text-white">{svc.name}</span>
                  <StatusBadge value={svc.status} dot />
                </div>
                <div className="text-xs text-g-muted space-y-0.5">
                  <div>Image: <span className="text-g-text truncate block">{svc.image}</span></div>
                  {svc.health !== 'none' && (
                    <div>Health: <StatusBadge value={svc.health} /></div>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Log viewer */}
      <div className="bg-g-card border border-g-border rounded-xl p-5">
        <h2 className="text-sm font-semibold text-white mb-4">Log Viewer</h2>
        <div className="flex flex-wrap gap-3 mb-4">
          <select
            value={logService}
            onChange={e => setLogService(e.target.value)}
            className="bg-g-deep border border-g-border rounded-lg px-3 py-2 text-sm text-g-text focus:outline-none focus:border-accent/50"
          >
            {['payment', 'ensemble', 'telegram-bot', 'executor', 'postgres', 'redis', 'admin-api'].map(s => (
              <option key={s} value={s}>{s}</option>
            ))}
          </select>
          <select
            value={logLines}
            onChange={e => setLogLines(Number(e.target.value))}
            className="bg-g-deep border border-g-border rounded-lg px-3 py-2 text-sm text-g-text focus:outline-none focus:border-accent/50"
          >
            {[50, 100, 200, 500].map(n => (
              <option key={n} value={n}>{n} lines</option>
            ))}
          </select>
          <button
            onClick={fetchLogs}
            disabled={logLoading}
            className="px-4 py-2 bg-accent text-black text-sm font-semibold rounded-lg hover:bg-accent/90 disabled:opacity-50 transition-colors"
          >
            {logLoading ? 'Loading…' : 'Fetch Logs'}
          </button>
        </div>
        {logContent && (
          <pre className="bg-g-deep border border-g-border rounded-lg p-4 text-xs text-g-text font-mono overflow-auto max-h-96 whitespace-pre-wrap">
            {logContent}
          </pre>
        )}
      </div>
    </div>
  )
}
