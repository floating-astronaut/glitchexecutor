import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  getTgStatus, getTgStats, getTgLogs, getTgUsers,
  tgBroadcast, tgBroadcastPreview,
  tgResetUserQueries, tgSendDM, tgSuspendUser,
} from '../../api/endpoints'
import {
  MessageCircle, Users, Activity, RefreshCw,
  Send, RotateCcw, Ban, CheckCircle2, XCircle,
  Search, ChevronLeft, ChevronRight, X,
} from 'lucide-react'
import clsx from 'clsx'

// ── Bot status bar ────────────────────────────────────────────────────────────
function BotStatusBar() {
  const { data } = useQuery({
    queryKey: ['tg:status'],
    queryFn: getTgStatus,
    refetchInterval: 15_000,
  })
  const running = data?.running
  return (
    <div className="flex items-center gap-3 rounded-xl border border-g-border bg-g-card px-4 py-3">
      <span className={clsx('w-2.5 h-2.5 rounded-full', running ? 'bg-accent animate-pulse' : 'bg-red-500')} />
      <span className="text-sm font-medium text-white">Telegram Bot</span>
      <span className={clsx('text-xs px-2 py-0.5 rounded-full font-medium',
        running ? 'bg-accent/10 text-accent' : 'bg-red-500/10 text-red-400'
      )}>
        {data?.status ?? '—'}
      </span>
      <span className="text-xs text-g-muted ml-auto">Health: {data?.health ?? '—'}</span>
    </div>
  )
}

// ── Stat card ─────────────────────────────────────────────────────────────────
function StatCard({ label, value, icon: Icon, sub }: { label: string; value: any; icon: any; sub?: string }) {
  return (
    <div className="rounded-xl border border-g-border bg-g-card p-4">
      <div className="flex items-center gap-2 text-g-muted text-xs mb-2">
        <Icon size={13} className="text-accent" /> {label}
      </div>
      <p className="text-2xl font-bold text-white">{value ?? '—'}</p>
      {sub && <p className="text-xs text-g-dim mt-1">{sub}</p>}
    </div>
  )
}

// ── Broadcast form ────────────────────────────────────────────────────────────
const TIERS = ['', 'trial', 'starter', 'pro', 'elite']

function BroadcastForm() {
  const [message, setMessage]   = useState('')
  const [tier, setTier]         = useState('')
  const [preview, setPreview]   = useState<number | null>(null)
  const [sent, setSent]         = useState<{ sent: number; failed: number } | null>(null)

  const previewQ = useQuery({
    queryKey: ['tg:broadcast-preview', tier],
    queryFn: () => tgBroadcastPreview(tier || undefined),
    enabled: false,
  })

  const broadcastMut = useMutation({
    mutationFn: tgBroadcast,
    onSuccess: (data) => {
      setSent(data)
      setMessage('')
      setPreview(null)
    },
  })

  const handlePreview = async () => {
    const res = await previewQ.refetch()
    setPreview(res.data?.count ?? 0)
  }

  return (
    <div className="rounded-xl border border-g-border bg-g-card p-4 space-y-3">
      <div className="flex items-center gap-2">
        <Send size={15} className="text-accent" />
        <span className="text-sm font-semibold text-white">Broadcast Message</span>
      </div>

      <textarea
        value={message}
        onChange={e => { setMessage(e.target.value); setSent(null); setPreview(null) }}
        placeholder="Type your message… HTML supported (e.g. <b>bold</b>)"
        rows={4}
        maxLength={4096}
        className="w-full bg-g-deep border border-g-border rounded-lg p-3 text-sm text-white placeholder:text-g-dim resize-none focus:outline-none focus:border-accent/50"
      />
      <div className="flex items-center justify-between text-xs text-g-dim">
        <span>{message.length} / 4096 chars</span>
      </div>

      <div className="flex items-center gap-3">
        <select
          value={tier}
          onChange={e => { setTier(e.target.value); setPreview(null) }}
          className="text-xs bg-g-deep border border-g-border rounded-lg px-3 py-2 text-g-text"
        >
          <option value="">All active users</option>
          {TIERS.filter(Boolean).map(t => (
            <option key={t} value={t}>{t.charAt(0).toUpperCase() + t.slice(1)} tier</option>
          ))}
        </select>

        <button
          onClick={handlePreview}
          disabled={!message.trim()}
          className="text-xs px-3 py-2 rounded-lg bg-white/5 text-g-muted hover:text-white hover:bg-white/10 transition-colors disabled:opacity-40"
        >
          Preview Recipients
        </button>

        {preview !== null && (
          <span className="text-xs text-accent font-medium">{preview} recipients</span>
        )}
      </div>

      {sent && (
        <div className="flex items-center gap-2 text-xs">
          <CheckCircle2 size={13} className="text-accent" />
          <span className="text-accent">Sent to {sent.sent}</span>
          {sent.failed > 0 && <span className="text-red-400">· {sent.failed} failed</span>}
        </div>
      )}

      {broadcastMut.isError && (
        <p className="text-xs text-red-400">{(broadcastMut.error as any)?.response?.data?.detail || 'Broadcast failed'}</p>
      )}

      <button
        onClick={() => broadcastMut.mutate({ message, tier: tier || undefined })}
        disabled={!message.trim() || broadcastMut.isPending}
        className="w-full py-2 rounded-lg bg-accent text-black text-sm font-semibold hover:bg-accent/90 transition-colors disabled:opacity-40"
      >
        {broadcastMut.isPending ? 'Sending…' : 'Send Broadcast'}
      </button>
    </div>
  )
}

// ── Bot logs ──────────────────────────────────────────────────────────────────
function BotLogs() {
  const { data: logsData, isFetching, refetch } = useQuery({
    queryKey: ['tg:logs'],
    queryFn: () => getTgLogs(50),
    refetchInterval: 30_000,
  })
  return (
    <div className="rounded-xl border border-g-border bg-g-card p-4 space-y-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Activity size={15} className="text-accent" />
          <span className="text-sm font-semibold text-white">Bot Logs</span>
          <span className="text-xs text-g-dim">(last 50 lines)</span>
        </div>
        <button
          onClick={() => refetch()}
          className="p-1.5 rounded-lg bg-white/5 hover:bg-white/10 text-g-muted hover:text-white transition-colors"
        >
          <RefreshCw size={13} className={isFetching ? 'animate-spin' : ''} />
        </button>
      </div>
      <pre className="h-48 overflow-y-auto text-[11px] font-mono leading-relaxed text-g-muted bg-black/30 rounded-lg p-3 whitespace-pre-wrap break-all">
        {(logsData as any)?.content || (logsData as any)?.error || 'No logs available'}
      </pre>
    </div>
  )
}

// ── User action modal ─────────────────────────────────────────────────────────
function UserActionModal({ user, onClose }: { user: any; onClose: () => void }) {
  const qc = useQueryClient()
  const [dmMsg, setDmMsg]   = useState('')
  const [dmSent, setDmSent] = useState(false)

  const resetMut = useMutation({
    mutationFn: () => tgResetUserQueries(user.id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['tg:users'] }),
  })
  const dmMut = useMutation({
    mutationFn: () => tgSendDM(user.id, dmMsg),
    onSuccess: () => { setDmSent(true); setDmMsg('') },
  })
  const suspendMut = useMutation({
    mutationFn: (suspend: boolean) => tgSuspendUser(user.id, suspend),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['tg:users'] })
      onClose()
    },
  })

  return (
    <div className="fixed inset-0 bg-black/60 z-50 flex items-center justify-center p-4" onClick={onClose}>
      <div
        className="bg-g-deep border border-g-border rounded-2xl p-5 w-full max-w-md space-y-4"
        onClick={e => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between">
          <div>
            <p className="font-semibold text-white">
              @{user.username || 'unknown'}{' '}
              <span className="text-xs font-mono text-g-muted">#{user.telegram_id}</span>
            </p>
            <p className="text-xs text-g-dim mt-0.5">
              Tier: <span className="text-accent">{user.tier}</span>
              {' · '} Queries today: <span className="text-white">{user.queries_today}</span>
              {' · '} Status: <span className={user.status === 'active' ? 'text-accent' : 'text-red-400'}>{user.status}</span>
            </p>
          </div>
          <button onClick={onClose} className="text-g-dim hover:text-white">
            <X size={16} />
          </button>
        </div>

        {/* Reset queries */}
        <div className="flex items-center justify-between p-3 rounded-lg bg-white/5">
          <div>
            <p className="text-sm text-white font-medium">Reset Queries</p>
            <p className="text-xs text-g-dim">Set queries_today back to 0</p>
          </div>
          <button
            onClick={() => resetMut.mutate()}
            disabled={resetMut.isPending}
            className="text-xs px-3 py-1.5 rounded-lg bg-accent/10 text-accent hover:bg-accent/20 transition-colors font-medium disabled:opacity-40"
          >
            {resetMut.isPending ? '…' : <RotateCcw size={13} />}
          </button>
        </div>
        {resetMut.isSuccess && <p className="text-xs text-accent -mt-2">Queries reset ✓</p>}

        {/* Send DM */}
        <div className="space-y-2">
          <p className="text-sm text-white font-medium">Send Direct Message</p>
          <textarea
            value={dmMsg}
            onChange={e => { setDmMsg(e.target.value); setDmSent(false) }}
            placeholder="Message text… HTML supported"
            rows={3}
            maxLength={4096}
            className="w-full bg-g-deep border border-g-border rounded-lg p-2.5 text-sm text-white placeholder:text-g-dim resize-none focus:outline-none focus:border-accent/50"
          />
          <button
            onClick={() => dmMut.mutate()}
            disabled={!dmMsg.trim() || dmMut.isPending}
            className="w-full py-1.5 rounded-lg bg-white/5 text-g-muted hover:text-white hover:bg-white/10 transition-colors text-sm disabled:opacity-40 flex items-center justify-center gap-1.5"
          >
            <Send size={13} /> {dmMut.isPending ? 'Sending…' : 'Send DM'}
          </button>
          {dmSent && <p className="text-xs text-accent">Message sent ✓</p>}
          {dmMut.isError && <p className="text-xs text-red-400">Failed to send DM</p>}
        </div>

        {/* Suspend / Unsuspend */}
        <div className="border-t border-g-border pt-3">
          {user.status === 'suspended' ? (
            <button
              onClick={() => suspendMut.mutate(false)}
              disabled={suspendMut.isPending}
              className="w-full py-2 rounded-lg bg-accent/10 text-accent hover:bg-accent/20 transition-colors text-sm font-medium"
            >
              <CheckCircle2 size={13} className="inline mr-1.5" />
              Unsuspend User
            </button>
          ) : (
            <button
              onClick={() => suspendMut.mutate(true)}
              disabled={suspendMut.isPending}
              className="w-full py-2 rounded-lg bg-red-500/10 text-red-400 hover:bg-red-500/20 transition-colors text-sm font-medium"
            >
              <Ban size={13} className="inline mr-1.5" />
              Suspend User
            </button>
          )}
        </div>
      </div>
    </div>
  )
}

// ── User table ────────────────────────────────────────────────────────────────
function UserTable() {
  const [page, setPage]       = useState(1)
  const [search, setSearch]   = useState('')
  const [q, setQ]             = useState('')
  const [selected, setSelected] = useState<any | null>(null)

  const { data, isLoading } = useQuery({
    queryKey: ['tg:users', page, q],
    queryFn: () => getTgUsers({ page, limit: 20, search: q }),
    keepPreviousData: true,
  } as any)

  const totalPages = Math.ceil(((data as any)?.total || 0) / 20)
  const customers: any[] = (data as any)?.customers || []

  return (
    <div className="rounded-xl border border-g-border bg-g-card">
      <div className="flex items-center justify-between p-4 border-b border-g-border">
        <div className="flex items-center gap-2">
          <Users size={15} className="text-accent" />
          <span className="text-sm font-semibold text-white">Bot Users</span>
          <span className="text-xs text-g-dim">({(data as any)?.total ?? 0} total)</span>
        </div>
        <div className="flex items-center gap-2">
          <input
            value={search}
            onChange={e => setSearch(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter') { setQ(search); setPage(1) } }}
            placeholder="Search username / ID…"
            className="text-xs bg-g-deep border border-g-border rounded-lg px-3 py-1.5 text-g-text placeholder:text-g-dim w-44 focus:outline-none focus:border-accent/50"
          />
          <button
            onClick={() => { setQ(search); setPage(1) }}
            className="p-1.5 rounded-lg bg-white/5 hover:bg-white/10 text-g-muted hover:text-white transition-colors"
          >
            <Search size={13} />
          </button>
        </div>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-g-border">
              {['Username', 'Telegram ID', 'Tier', 'Status', 'Queries', 'Joined', ''].map(h => (
                <th key={h} className="px-4 py-2.5 text-left text-xs text-g-dim font-medium">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {isLoading ? (
              <tr><td colSpan={7} className="px-4 py-6 text-center text-g-dim text-xs">Loading…</td></tr>
            ) : customers.length === 0 ? (
              <tr><td colSpan={7} className="px-4 py-6 text-center text-g-dim text-xs">No users found</td></tr>
            ) : customers.map((c: any) => (
              <tr key={c.id} className="border-b border-g-border/50 hover:bg-white/[0.02] transition-colors">
                <td className="px-4 py-3 text-white">@{c.username || '—'}</td>
                <td className="px-4 py-3 font-mono text-xs text-g-muted">{c.telegram_id}</td>
                <td className="px-4 py-3">
                  <span className="text-xs px-2 py-0.5 rounded-full bg-accent/10 text-accent font-medium">{c.tier}</span>
                </td>
                <td className="px-4 py-3">
                  <span className={clsx('text-xs font-medium', c.status === 'active' ? 'text-accent' : 'text-red-400')}>
                    {c.status}
                  </span>
                </td>
                <td className="px-4 py-3 text-g-muted">{c.queries_today}</td>
                <td className="px-4 py-3 text-g-dim text-xs">
                  {c.created_at ? new Date(c.created_at).toLocaleDateString() : '—'}
                </td>
                <td className="px-4 py-3">
                  <button
                    onClick={() => setSelected(c)}
                    className="text-xs px-2 py-1 rounded-lg bg-white/5 text-g-muted hover:text-white hover:bg-white/10 transition-colors"
                  >
                    Actions
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-between px-4 py-3 border-t border-g-border">
          <span className="text-xs text-g-dim">Page {page} of {totalPages}</span>
          <div className="flex gap-1">
            <button
              onClick={() => setPage(p => Math.max(1, p - 1))}
              disabled={page === 1}
              className="p-1 rounded text-g-muted hover:text-white disabled:opacity-30"
            >
              <ChevronLeft size={14} />
            </button>
            <button
              onClick={() => setPage(p => Math.min(totalPages, p + 1))}
              disabled={page === totalPages}
              className="p-1 rounded text-g-muted hover:text-white disabled:opacity-30"
            >
              <ChevronRight size={14} />
            </button>
          </div>
        </div>
      )}

      {selected && (
        <UserActionModal user={selected} onClose={() => setSelected(null)} />
      )}
    </div>
  )
}

// ── Main page ─────────────────────────────────────────────────────────────────
export default function TelegramBot() {
  const { data: stats } = useQuery({
    queryKey: ['tg:stats'],
    queryFn: getTgStats,
    refetchInterval: 30_000,
  })

  return (
    <div className="p-6 space-y-6 max-w-7xl mx-auto">
      <div>
        <h1 className="text-2xl font-bold text-white">Telegram Bot</h1>
        <p className="text-g-muted text-sm mt-1">Manage users, broadcast messages and monitor the bot</p>
      </div>

      <BotStatusBar />

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <StatCard icon={Users}    label="Total Users"   value={stats?.total_users}   sub="All-time registrations" />
        <StatCard icon={Activity} label="Active Today"  value={stats?.active_today}  sub="Queried at least once" />
        <StatCard icon={MessageCircle} label="New Today" value={stats?.new_today}   sub="Registered today" />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <BroadcastForm />
        <BotLogs />
      </div>

      <UserTable />
    </div>
  )
}
