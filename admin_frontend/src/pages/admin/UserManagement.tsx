import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  getAdminCustomers, bulkChangeTier, bulkSuspend,
  getAdminUsers, createAdminUser, updateAdminUser, getAuditLog,
} from '../../api/endpoints'
import {
  Users, ShieldCheck, ClipboardList, Search, Download,
  ChevronLeft, ChevronRight, Plus, Check, X, Ban,
} from 'lucide-react'
import clsx from 'clsx'

// ── helpers ───────────────────────────────────────────────────────────────────
function exportCsv(rows: any[]) {
  const headers = [
    'id','telegram_id','username','tier','status','queries_today',
    'stripe_customer_id','stripe_subscription_id','created_at',
  ]
  const lines = [
    headers.join(','),
    ...rows.map(r => headers.map(h => JSON.stringify(r[h] ?? '')).join(',')),
  ]
  const blob = new Blob([lines.join('\n')], { type: 'text/csv' })
  const url = URL.createObjectURL(blob)
  const a   = document.createElement('a')
  a.href = url; a.download = 'customers.csv'; a.click()
  URL.revokeObjectURL(url)
}

const TIERS    = ['trial','starter','pro','elite']
const STATUSES = ['active','suspended','cancelled','pending']

// ── Bulk action bar ───────────────────────────────────────────────────────────
function BulkBar({
  selected, rows, onClear
}: { selected: Set<number>; rows: any[]; onClear: () => void }) {
  const qc = useQueryClient()
  const [newTier, setNewTier] = useState('')

  const tierMut = useMutation({
    mutationFn: () => bulkChangeTier([...selected], newTier),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['admin:customers'] }); onClear() },
  })
  const suspendMut = useMutation({
    mutationFn: () => bulkSuspend([...selected]),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['admin:customers'] }); onClear() },
  })

  if (selected.size === 0) return null

  return (
    <div className="flex items-center gap-3 p-3 rounded-xl border border-accent/20 bg-accent/5 text-sm">
      <span className="text-accent font-medium">{selected.size} selected</span>
      <button
        onClick={() => exportCsv(rows.filter(r => selected.has(r.id)))}
        className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-white/5 text-g-muted hover:text-white hover:bg-white/10 transition-colors text-xs"
      >
        <Download size={12} /> Export CSV
      </button>
      <div className="flex items-center gap-1.5">
        <select
          value={newTier}
          onChange={e => setNewTier(e.target.value)}
          className="text-xs bg-g-deep border border-g-border rounded-lg px-2 py-1.5 text-g-text"
        >
          <option value="">Change tier…</option>
          {TIERS.map(t => <option key={t} value={t}>{t}</option>)}
        </select>
        <button
          onClick={() => tierMut.mutate()}
          disabled={!newTier || tierMut.isPending}
          className="text-xs px-3 py-1.5 rounded-lg bg-accent/10 text-accent hover:bg-accent/20 transition-colors disabled:opacity-40"
        >
          Apply
        </button>
      </div>
      <button
        onClick={() => suspendMut.mutate()}
        disabled={suspendMut.isPending}
        className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg bg-red-500/10 text-red-400 hover:bg-red-500/20 transition-colors"
      >
        <Ban size={12} /> Suspend All
      </button>
      <button onClick={onClear} className="ml-auto text-g-dim hover:text-white">
        <X size={14} />
      </button>
    </div>
  )
}

// ── Customers tab ─────────────────────────────────────────────────────────────
function CustomersTab() {
  const [page, setPage]       = useState(1)
  const [search, setSearch]   = useState('')
  const [q, setQ]             = useState('')
  const [tier, setTier]       = useState('')
  const [status, setStatus]   = useState('')
  const [selected, setSelected] = useState<Set<number>>(new Set())

  const { data, isLoading } = useQuery({
    queryKey: ['admin:customers', page, q, tier, status],
    queryFn: () => getAdminCustomers({ page, limit: 25, search: q, tier, status }),
    keepPreviousData: true,
  } as any)

  const customers: any[] = (data as any)?.customers || []
  const totalPages = Math.ceil(((data as any)?.total || 0) / 25)

  const toggleAll = () =>
    setSelected(selected.size === customers.length
      ? new Set()
      : new Set(customers.map((c: any) => c.id))
    )
  const toggleOne = (id: number) =>
    setSelected(prev => {
      const next = new Set(prev)
      next.has(id) ? next.delete(id) : next.add(id)
      return next
    })

  return (
    <div className="space-y-3">
      {/* Filters */}
      <div className="flex flex-wrap items-center gap-2">
        <div className="flex items-center gap-1 flex-1 min-w-48">
          <input
            value={search}
            onChange={e => setSearch(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter') { setQ(search); setPage(1) } }}
            placeholder="Search username / ID / Stripe…"
            className="w-full text-xs bg-g-deep border border-g-border rounded-lg px-3 py-2 text-g-text placeholder:text-g-dim focus:outline-none focus:border-accent/50"
          />
          <button
            onClick={() => { setQ(search); setPage(1) }}
            className="p-2 rounded-lg bg-white/5 hover:bg-white/10 text-g-muted hover:text-white transition-colors"
          >
            <Search size={13} />
          </button>
        </div>
        <select value={tier} onChange={e => { setTier(e.target.value); setPage(1) }}
          className="text-xs bg-g-deep border border-g-border rounded-lg px-2 py-2 text-g-text">
          <option value="">All tiers</option>
          {TIERS.map(t => <option key={t} value={t}>{t}</option>)}
        </select>
        <select value={status} onChange={e => { setStatus(e.target.value); setPage(1) }}
          className="text-xs bg-g-deep border border-g-border rounded-lg px-2 py-2 text-g-text">
          <option value="">All statuses</option>
          {STATUSES.map(s => <option key={s} value={s}>{s}</option>)}
        </select>
        <button
          onClick={() => exportCsv(customers)}
          className="flex items-center gap-1.5 text-xs px-3 py-2 rounded-lg bg-white/5 text-g-muted hover:text-white hover:bg-white/10 transition-colors"
        >
          <Download size={12} /> Export Page
        </button>
      </div>

      <BulkBar selected={selected} rows={customers} onClear={() => setSelected(new Set())} />

      {/* Table */}
      <div className="rounded-xl border border-g-border bg-g-card overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-g-border">
                <th className="px-3 py-2.5">
                  <input
                    type="checkbox"
                    checked={customers.length > 0 && selected.size === customers.length}
                    onChange={toggleAll}
                    className="accent-accent"
                  />
                </th>
                {['ID','Username','Tier','Status','Queries','Stripe ID','Joined'].map(h => (
                  <th key={h} className="px-4 py-2.5 text-left text-xs text-g-dim font-medium">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {isLoading ? (
                <tr><td colSpan={8} className="px-4 py-6 text-center text-g-dim text-xs">Loading…</td></tr>
              ) : customers.length === 0 ? (
                <tr><td colSpan={8} className="px-4 py-6 text-center text-g-dim text-xs">No customers found</td></tr>
              ) : customers.map((c: any) => (
                <tr key={c.id} className={clsx(
                  'border-b border-g-border/50 transition-colors',
                  selected.has(c.id) ? 'bg-accent/5' : 'hover:bg-white/[0.02]'
                )}>
                  <td className="px-3 py-3">
                    <input type="checkbox" checked={selected.has(c.id)} onChange={() => toggleOne(c.id)} className="accent-accent" />
                  </td>
                  <td className="px-4 py-3 font-mono text-xs text-g-dim">{c.id}</td>
                  <td className="px-4 py-3 text-white">@{c.username || '—'}</td>
                  <td className="px-4 py-3">
                    <span className="text-xs px-2 py-0.5 rounded-full bg-accent/10 text-accent">{c.tier}</span>
                  </td>
                  <td className="px-4 py-3">
                    <span className={clsx('text-xs font-medium', c.status === 'active' ? 'text-accent' : 'text-red-400')}>
                      {c.status}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-g-muted">{c.queries_today}</td>
                  <td className="px-4 py-3 font-mono text-xs text-g-dim max-w-32 truncate" title={c.stripe_customer_id || ''}>
                    {c.stripe_customer_id ? c.stripe_customer_id.slice(0, 18) + '…' : '—'}
                  </td>
                  <td className="px-4 py-3 text-g-dim text-xs">
                    {c.created_at ? new Date(c.created_at).toLocaleDateString() : '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {/* Pagination */}
        <div className="flex items-center justify-between px-4 py-3 border-t border-g-border">
          <span className="text-xs text-g-dim">{(data as any)?.total ?? 0} total · Page {page} of {Math.max(1, totalPages)}</span>
          <div className="flex gap-1">
            <button onClick={() => setPage(p => Math.max(1, p - 1))} disabled={page === 1} className="p-1 rounded text-g-muted hover:text-white disabled:opacity-30">
              <ChevronLeft size={14} />
            </button>
            <button onClick={() => setPage(p => Math.min(totalPages, p + 1))} disabled={page >= totalPages} className="p-1 rounded text-g-muted hover:text-white disabled:opacity-30">
              <ChevronRight size={14} />
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

// ── Create admin modal ────────────────────────────────────────────────────────
function CreateAdminModal({ onClose }: { onClose: () => void }) {
  const qc = useQueryClient()
  const [form, setForm] = useState({ email: '', password: '', role: 'admin' })

  const mut = useMutation({
    mutationFn: () => createAdminUser(form),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['admin:users'] }); onClose() },
  })

  return (
    <div className="fixed inset-0 bg-black/60 z-50 flex items-center justify-center p-4" onClick={onClose}>
      <div className="bg-g-deep border border-g-border rounded-2xl p-5 w-full max-w-sm space-y-4" onClick={e => e.stopPropagation()}>
        <div className="flex items-center justify-between">
          <p className="font-semibold text-white">Create Admin User</p>
          <button onClick={onClose} className="text-g-dim hover:text-white"><X size={15} /></button>
        </div>
        <div className="space-y-3">
          {(['email','password'] as const).map(k => (
            <input
              key={k}
              type={k === 'password' ? 'password' : 'text'}
              placeholder={k.charAt(0).toUpperCase() + k.slice(1)}
              value={form[k]}
              onChange={e => setForm(f => ({ ...f, [k]: e.target.value }))}
              className="w-full bg-g-card border border-g-border rounded-lg px-3 py-2.5 text-sm text-white placeholder:text-g-dim focus:outline-none focus:border-accent/50"
            />
          ))}
          <select
            value={form.role}
            onChange={e => setForm(f => ({ ...f, role: e.target.value }))}
            className="w-full bg-g-card border border-g-border rounded-lg px-3 py-2.5 text-sm text-g-text"
          >
            <option value="admin">Admin</option>
            <option value="viewer">Viewer</option>
          </select>
        </div>
        {mut.isError && (
          <p className="text-xs text-red-400">{(mut.error as any)?.response?.data?.detail || 'Error creating user'}</p>
        )}
        <button
          onClick={() => mut.mutate()}
          disabled={!form.email || !form.password || mut.isPending}
          className="w-full py-2.5 rounded-lg bg-accent text-black text-sm font-semibold hover:bg-accent/90 transition-colors disabled:opacity-40"
        >
          {mut.isPending ? 'Creating…' : 'Create User'}
        </button>
      </div>
    </div>
  )
}

// ── Admin users tab ───────────────────────────────────────────────────────────
function AdminUsersTab() {
  const qc = useQueryClient()
  const [showCreate, setShowCreate] = useState(false)

  const { data = [], isLoading } = useQuery({
    queryKey: ['admin:users'],
    queryFn: getAdminUsers,
  })

  const updateMut = useMutation({
    mutationFn: ({ id, data }: { id: number; data: any }) => updateAdminUser(id, data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['admin:users'] }),
  })

  return (
    <div className="space-y-3">
      <div className="flex justify-end">
        <button
          onClick={() => setShowCreate(true)}
          className="flex items-center gap-1.5 text-sm px-3 py-2 rounded-lg bg-accent text-black font-semibold hover:bg-accent/90 transition-colors"
        >
          <Plus size={14} /> New Admin User
        </button>
      </div>

      <div className="rounded-xl border border-g-border bg-g-card overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-g-border">
              {['Email','Role','Active','Created'].map(h => (
                <th key={h} className="px-4 py-2.5 text-left text-xs text-g-dim font-medium">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {isLoading ? (
              <tr><td colSpan={4} className="px-4 py-6 text-center text-g-dim text-xs">Loading…</td></tr>
            ) : (data as any[]).map((u: any) => (
              <tr key={u.id} className="border-b border-g-border/50 hover:bg-white/[0.02]">
                <td className="px-4 py-3 text-white">{u.email}</td>
                <td className="px-4 py-3">
                  <select
                    defaultValue={u.role}
                    onChange={e => updateMut.mutate({ id: u.id, data: { role: e.target.value } })}
                    className="text-xs bg-g-deep border border-g-border rounded px-2 py-1 text-g-text"
                  >
                    <option value="admin">admin</option>
                    <option value="viewer">viewer</option>
                  </select>
                </td>
                <td className="px-4 py-3">
                  <button
                    onClick={() => updateMut.mutate({ id: u.id, data: { is_active: !u.is_active } })}
                    className={clsx('w-8 h-4 rounded-full transition-colors relative',
                      u.is_active ? 'bg-accent' : 'bg-white/20'
                    )}
                  >
                    <span className={clsx('absolute top-0.5 w-3 h-3 rounded-full bg-white transition-all',
                      u.is_active ? 'left-4' : 'left-0.5'
                    )} />
                  </button>
                </td>
                <td className="px-4 py-3 text-g-dim text-xs">
                  {u.created_at ? new Date(u.created_at).toLocaleDateString() : '—'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {showCreate && <CreateAdminModal onClose={() => setShowCreate(false)} />}
    </div>
  )
}

// ── Audit log tab ─────────────────────────────────────────────────────────────
function AuditTab() {
  const [page, setPage] = useState(1)
  const { data, isLoading } = useQuery({
    queryKey: ['admin:audit', page],
    queryFn: () => getAuditLog(page),
    keepPreviousData: true,
  } as any)

  const entries: any[] = (data as any)?.entries || (data as any) || []
  const totalPages = (data as any)?.pages || 1

  return (
    <div className="rounded-xl border border-g-border bg-g-card overflow-hidden">
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-g-border">
              {['When','Actor','Action','Target','Detail'].map(h => (
                <th key={h} className="px-4 py-2.5 text-left text-xs text-g-dim font-medium">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {isLoading ? (
              <tr><td colSpan={5} className="px-4 py-6 text-center text-g-dim text-xs">Loading…</td></tr>
            ) : entries.length === 0 ? (
              <tr><td colSpan={5} className="px-4 py-6 text-center text-g-dim text-xs">No audit entries</td></tr>
            ) : entries.map((e: any, i: number) => (
              <tr key={i} className="border-b border-g-border/50 hover:bg-white/[0.02]">
                <td className="px-4 py-3 text-g-dim text-xs whitespace-nowrap">
                  {e.created_at ? new Date(e.created_at).toLocaleString() : '—'}
                </td>
                <td className="px-4 py-3 text-g-muted text-xs">{e.actor_email || e.actor || '—'}</td>
                <td className="px-4 py-3">
                  <span className="text-xs px-2 py-0.5 rounded-full bg-accent/10 text-accent font-mono">{e.action}</span>
                </td>
                <td className="px-4 py-3 text-g-muted text-xs">{e.target_type} #{e.target_id}</td>
                <td className="px-4 py-3 text-g-dim text-xs font-mono truncate max-w-xs" title={JSON.stringify(e.detail)}>
                  {e.detail ? JSON.stringify(e.detail).slice(0, 60) : '—'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {totalPages > 1 && (
        <div className="flex items-center justify-between px-4 py-3 border-t border-g-border">
          <span className="text-xs text-g-dim">Page {page} of {totalPages}</span>
          <div className="flex gap-1">
            <button onClick={() => setPage(p => Math.max(1, p - 1))} disabled={page === 1} className="p-1 rounded text-g-muted hover:text-white disabled:opacity-30">
              <ChevronLeft size={14} />
            </button>
            <button onClick={() => setPage(p => Math.min(totalPages, p + 1))} disabled={page >= totalPages} className="p-1 rounded text-g-muted hover:text-white disabled:opacity-30">
              <ChevronRight size={14} />
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

// ── Main page ─────────────────────────────────────────────────────────────────
type Tab = 'customers' | 'admins' | 'audit'

const TABS: { id: Tab; label: string; icon: any }[] = [
  { id: 'customers', label: 'Customers',   icon: Users },
  { id: 'admins',    label: 'Admin Users', icon: ShieldCheck },
  { id: 'audit',     label: 'Audit Log',   icon: ClipboardList },
]

export default function UserManagement() {
  const [tab, setTab] = useState<Tab>('customers')

  return (
    <div className="p-6 space-y-5 max-w-7xl mx-auto">
      <div>
        <h1 className="text-2xl font-bold text-white">User Management</h1>
        <p className="text-g-muted text-sm mt-1">Full customer database, admin accounts and audit trail</p>
      </div>

      {/* Tab bar */}
      <div className="flex gap-1 border-b border-g-border">
        {TABS.map(t => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={clsx(
              'flex items-center gap-2 px-4 py-2.5 text-sm font-medium border-b-2 transition-colors',
              tab === t.id
                ? 'border-accent text-accent'
                : 'border-transparent text-g-muted hover:text-g-text'
            )}
          >
            <t.icon size={14} />
            {t.label}
          </button>
        ))}
      </div>

      {tab === 'customers' && <CustomersTab />}
      {tab === 'admins'    && <AdminUsersTab />}
      {tab === 'audit'     && <AuditTab />}
    </div>
  )
}
