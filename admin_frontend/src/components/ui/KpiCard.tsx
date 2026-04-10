import clsx from 'clsx'
import { LucideIcon } from 'lucide-react'

interface Props {
  label: string
  value: string | number
  sub?: string
  icon?: LucideIcon
  accent?: boolean
  trend?: 'up' | 'down' | 'neutral'
}

export default function KpiCard({ label, value, sub, icon: Icon, accent, trend }: Props) {
  return (
    <div className={clsx(
      'rounded-xl border p-4 flex flex-col gap-3 bg-g-card',
      accent ? 'border-accent/30' : 'border-g-border',
    )}>
      <div className="flex items-center justify-between">
        <span className="text-xs text-g-muted font-medium uppercase tracking-wider">{label}</span>
        {Icon && (
          <span className={clsx(
            'p-1.5 rounded-lg',
            accent ? 'bg-accent/10 text-accent' : 'bg-white/5 text-g-muted'
          )}>
            <Icon size={14} />
          </span>
        )}
      </div>
      <div>
        <div className={clsx(
          'text-2xl font-bold',
          accent ? 'text-accent' : 'text-white'
        )}>
          {value}
        </div>
        {sub && (
          <div className={clsx(
            'text-xs mt-0.5',
            trend === 'up' ? 'text-green-400' :
            trend === 'down' ? 'text-red-400' :
            'text-g-muted'
          )}>
            {sub}
          </div>
        )}
      </div>
    </div>
  )
}
