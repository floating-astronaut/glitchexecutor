import { useQuery } from '@tanstack/react-query'
import { getBillingSummary, getPlans, getEmailSignups } from '../api/endpoints'
import KpiCard from '../components/ui/KpiCard'
import DataTable, { Column } from '../components/ui/DataTable'
import { DollarSign, Users, Mail, TrendingUp } from 'lucide-react'
import { formatDistanceToNow } from 'date-fns'

export default function Billing() {
  const { data: summary } = useQuery({ queryKey: ['billingSummary'], queryFn: getBillingSummary, refetchInterval: 60_000 })
  const { data: plans = [] } = useQuery({ queryKey: ['plans'], queryFn: getPlans })
  const { data: signupsData } = useQuery({ queryKey: ['emailSignups'], queryFn: () => getEmailSignups(1) })

  const signupCols: Column<any>[] = [
    { key: 'email',  label: 'Email' },
    { key: 'source', label: 'Source', render: r => (
      <span className="text-xs bg-g-border text-g-text px-2 py-0.5 rounded-full">{r.source || 'landing'}</span>
    )},
    { key: 'signed_up_at', label: 'Date', render: r => r.signed_up_at
      ? formatDistanceToNow(new Date(r.signed_up_at), { addSuffix: true })
      : '—'
    },
  ]

  const PLAN_COLORS: Record<string, string> = {
    starter: 'border-blue-500/30 bg-blue-500/5',
    pro:     'border-purple-500/30 bg-purple-500/5',
    elite:   'border-yellow-500/30 bg-yellow-500/5',
  }

  return (
    <div className="space-y-6">
      {/* KPIs */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <KpiCard
          label="MRR"
          value={`$${(summary?.mrr_usd ?? 0).toLocaleString()}`}
          icon={DollarSign}
          accent
        />
        <KpiCard
          label="ARR"
          value={`$${(summary?.arr_usd ?? 0).toLocaleString()}`}
          icon={TrendingUp}
        />
        <KpiCard
          label="Active Subscribers"
          value={summary?.total_active ?? 0}
          icon={Users}
        />
        <KpiCard
          label="Trial Users"
          value={summary?.total_trial ?? 0}
          icon={Users}
        />
      </div>

      {/* Plans */}
      <div>
        <h2 className="text-sm font-semibold text-white mb-3">Plans</h2>
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
          {plans.map((plan: any) => (
            <div
              key={plan.id}
              className={`bg-g-card border rounded-xl p-4 ${PLAN_COLORS[plan.id] || 'border-g-border'}`}
            >
              <div className="flex justify-between items-start mb-3">
                <div>
                  <h3 className="font-bold text-white">{plan.name}</h3>
                  <p className="text-xs text-g-muted">{plan.tagline}</p>
                </div>
                <div className="text-right">
                  <div className="text-lg font-bold text-white">${plan.price_mo}/mo</div>
                  <div className="text-xs text-g-muted">${plan.price_yr}/yr</div>
                </div>
              </div>
              <div className="space-y-1 text-xs text-g-muted">
                <div>Analyses: <span className="text-g-text">{plan.analyses === -1 ? 'Unlimited' : plan.analyses}</span></div>
                <div>Execution: <span className="text-g-text">{plan.execution || 'None'}</span></div>
                <div>Subscribers: <span className="text-white font-semibold">{plan.subscriber_count}</span></div>
                <div>Revenue: <span className="text-accent font-semibold">
                  ${(summary?.by_tier?.[plan.id]?.revenue ?? 0).toLocaleString()}/mo
                </span></div>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Email signups */}
      <div>
        <h2 className="text-sm font-semibold text-white mb-3 flex items-center gap-2">
          <Mail size={16} className="text-accent" />
          Email Signups ({signupsData?.total ?? 0})
        </h2>
        <DataTable
          columns={signupCols}
          data={signupsData?.signups || []}
          emptyText="No email signups yet"
          dateField="signed_up_at"
        />
      </div>
    </div>
  )
}
