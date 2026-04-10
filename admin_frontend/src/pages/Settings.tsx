import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  getAdminUsers, createAdminUser, updateAdminUser,
  getAuditLog, getEnvStatus
} from '../api/endpoints'
import DataTable, { Column } from '../components/ui/DataTable'
import Modal from '../components/ui/Modal'
import { UserPlus, Check, X, ShieldCheck } from 'lucide-react'
import { formatDistanceToNow } from 'date-fns'
import clsx from 'clsx'

type Tab = 'users' | 'audit' | 'environment'

export default function Settings() {
  const [tab, setTab] = useState<Tab>('users')
  const [showAdd, setShowAdd] = useState(false)
  const [form, setForm] = useState({ email: '', password: '', role: 'admin' })
  const [saving, setSaving] = useState(false)
  const qc = useQueryClient()

  const { data: users = [] } = useQuery({ queryKey: ['adminUsers'], queryFn: getAdminUsers })
  const { data: audit }      = useQuery({ queryKey: ['auditLog'],  queryFn: () => getAuditLog(1), enabled: tab === 'audit' })
  const { data: envStatus }  = useQuery({ queryKey: ['envStatus'], queryFn: getEnvStatus,      enabled: tab === 'environment' })

  const handleCreateUser = async (e: React.FormEvent) => {
    e.preventDefault()
    setSaving(true)
    try {
      await createAdminUser(form)
      qc.invalidateQueries({ queryKey: ['adminUsers'] })
      setShowAdd(false)
      setForm({ email: '', password: '', role: 'admin' })
    } finally {
      setSaving(false)
    }
  }

  const toggleActive = async (user: any) => {
    await updateAdminUser(user.id, { is_active: !user.is_active })
    qc.invalidateQueries({ queryKey: ['adminUsers'] })
  }

  const userCols: Column<any>[] = [
    { key: 'email',    label: 'Email',    render: r => <span className="text-white">{r.email}</span> },
    { key: 'role',     label: 'Role',     render: r => (
      <span className="text-xs bg-g-border text-g-text px-2 py-0.5 rounded-full">{r.role}</span>
    )},
    { key: 'is_active', label: 'Active', render: r => r.is_active
      ? <Check size={14} className="text-green-400" />
      : <X size={14} className="text-red-400" />
    },
    { key: 'last_login', label: 'Last Login', render: r => r.last_login
      ? formatDistanceToNow(new Date(r.last_login), { addSuffix: true })
      : 'Never'
    },
    { key: 'actions', label: '', render: r => (
      <button
        onClick={() => toggleActive(r)}
        className="text-xs text-g-muted hover:text-white transition-colors"
      >
        {r.is_active ? 'Disable' : 'Enable'}
      </button>
    )},
  ]

  const auditCols: Column<any>[] = [
    { key: 'admin_email', label: 'Admin' },
    { key: 'action',      label: 'Action' },
    { key: 'target_type', label: 'Target', render: r => `${r.target_type || '—'} #${r.target_id || ''}` },
    { key: 'ip_address',  label: 'IP', render: r => <span className="font-mono text-xs">{r.ip_address || '—'}</span> },
    { key: 'created_at',  label: 'Time', render: r => r.created_at
      ? formatDistanceToNow(new Date(r.created_at), { addSuffix: true })
      : '—'
    },
  ]

  return (
    <div className="space-y-6">
      {/* Tabs */}
      <div className="flex gap-1 border-b border-g-border">
        {(['users', 'audit', 'environment'] as Tab[]).map(t => (
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
            {t === 'environment' ? 'Environment' : t.charAt(0).toUpperCase() + t.slice(1)}
          </button>
        ))}
      </div>

      {/* Users */}
      {tab === 'users' && (
        <div className="space-y-4">
          <div className="flex justify-between items-center">
            <span className="text-sm text-g-muted">{users.length} admin user{users.length !== 1 ? 's' : ''}</span>
            <button
              onClick={() => setShowAdd(true)}
              className="flex items-center gap-2 px-4 py-2 bg-accent text-black text-sm font-semibold rounded-lg hover:bg-accent/90 transition-colors"
            >
              <UserPlus size={14} />
              Add User
            </button>
          </div>
          <DataTable columns={userCols} data={users} emptyText="No admin users" />
        </div>
      )}

      {/* Audit */}
      {tab === 'audit' && (
        <div>
          <div className="text-xs text-g-muted mb-3">{audit?.total ?? 0} audit entries</div>
          <DataTable
            columns={auditCols}
            data={audit?.entries || []}
            emptyText="No audit entries"
          />
        </div>
      )}

      {/* Environment */}
      {tab === 'environment' && (
        <div className="space-y-3">
          <div className="flex items-center gap-2 text-xs text-g-muted mb-4">
            <ShieldCheck size={14} className="text-accent" />
            Values are never shown — only presence is indicated
          </div>
          {envStatus && Object.entries(envStatus).map(([key, present]) => (
            <div key={key} className="flex items-center justify-between bg-g-card border border-g-border rounded-xl px-4 py-3">
              <span className="font-mono text-sm text-g-text">{key}</span>
              {present
                ? <Check size={16} className="text-green-400" />
                : <X size={16} className="text-red-400" />
              }
            </div>
          ))}
        </div>
      )}

      {/* Add User Modal */}
      <Modal open={showAdd} onClose={() => setShowAdd(false)} title="Add Admin User">
        <form onSubmit={handleCreateUser} className="space-y-4">
          <div>
            <label className="block text-xs text-g-muted mb-1.5">Email</label>
            <input
              type="email"
              required
              value={form.email}
              onChange={e => setForm(f => ({ ...f, email: e.target.value }))}
              className="w-full bg-g-deep border border-g-border rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-accent/50"
            />
          </div>
          <div>
            <label className="block text-xs text-g-muted mb-1.5">Password</label>
            <input
              type="password"
              required
              value={form.password}
              onChange={e => setForm(f => ({ ...f, password: e.target.value }))}
              className="w-full bg-g-deep border border-g-border rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-accent/50"
            />
          </div>
          <div>
            <label className="block text-xs text-g-muted mb-1.5">Role</label>
            <select
              value={form.role}
              onChange={e => setForm(f => ({ ...f, role: e.target.value }))}
              className="w-full bg-g-deep border border-g-border rounded-lg px-3 py-2 text-sm text-g-text focus:outline-none focus:border-accent/50"
            >
              <option value="admin">Admin</option>
              <option value="ops">Ops</option>
              <option value="viewer">Viewer</option>
            </select>
          </div>
          <div className="flex gap-3 pt-2">
            <button
              type="button"
              onClick={() => setShowAdd(false)}
              className="flex-1 px-4 py-2 text-sm text-g-muted border border-g-border rounded-lg hover:bg-white/5"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={saving}
              className="flex-1 px-4 py-2 text-sm bg-accent text-black font-semibold rounded-lg hover:bg-accent/90 disabled:opacity-50"
            >
              {saving ? 'Creating…' : 'Create User'}
            </button>
          </div>
        </form>
      </Modal>
    </div>
  )
}
