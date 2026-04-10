import clsx from 'clsx'

const COLORS: Record<string, string> = {
  // Tiers
  trial:    'bg-gray-500/20 text-gray-300 border-gray-500/30',
  starter:  'bg-blue-500/20 text-blue-300 border-blue-500/30',
  pro:      'bg-purple-500/20 text-purple-300 border-purple-500/30',
  elite:    'bg-yellow-500/20 text-yellow-300 border-yellow-500/30',
  // Statuses
  active:   'bg-green-500/20 text-green-300 border-green-500/30',
  suspended:'bg-red-500/20 text-red-300 border-red-500/30',
  cancelled:'bg-gray-500/20 text-gray-300 border-gray-500/30',
  pending:  'bg-yellow-500/20 text-yellow-300 border-yellow-500/30',
  // Bot statuses
  live:     'bg-green-500/20 text-green-300 border-green-500/30',
  stale:    'bg-yellow-500/20 text-yellow-300 border-yellow-500/30',
  unknown:  'bg-gray-500/20 text-gray-300 border-gray-500/30',
  // Service statuses
  running:  'bg-green-500/20 text-green-300 border-green-500/30',
  stopped:  'bg-red-500/20 text-red-300 border-red-500/30',
  healthy:  'bg-green-500/20 text-green-300 border-green-500/30',
  unhealthy:'bg-red-500/20 text-red-300 border-red-500/30',
  unreachable:'bg-red-500/20 text-red-300 border-red-500/30',
  not_found:'bg-gray-500/20 text-gray-300 border-gray-500/30',
}

interface Props {
  value: string
  dot?: boolean
}

export default function StatusBadge({ value, dot }: Props) {
  const cls = COLORS[value?.toLowerCase()] || 'bg-gray-500/20 text-gray-300 border-gray-500/30'
  return (
    <span className={clsx(
      'inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-xs font-medium border',
      cls
    )}>
      {dot && (
        <span className={clsx(
          'w-1.5 h-1.5 rounded-full',
          value === 'live' || value === 'active' || value === 'healthy' || value === 'running'
            ? 'bg-green-400 animate-pulse'
            : 'bg-current opacity-60'
        )} />
      )}
      {value}
    </span>
  )
}
