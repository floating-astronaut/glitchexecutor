import { useState, useMemo, useEffect } from 'react'
import clsx from 'clsx'

export interface Column<T> {
  key: string
  label: string
  render?: (row: T) => React.ReactNode
  className?: string
}

interface Props<T> {
  columns: Column<T>[]
  data: T[]
  keyField?: string
  loading?: boolean
  emptyText?: string
  className?: string
  dateField?: string
  defaultPageSize?: number
}

export default function DataTable<T extends Record<string, any>>({
  columns, data, keyField = 'id', loading, emptyText = 'No data', className,
  dateField, defaultPageSize = 10,
}: Props<T>) {
  const [pageSize, setPageSize] = useState(defaultPageSize)
  const [currentPage, setCurrentPage] = useState(1)
  const [fromDate, setFromDate] = useState('')
  const [toDate, setToDate] = useState('')

  // Reset to page 1 when filters, page size, or data changes
  useEffect(() => { setCurrentPage(1) }, [fromDate, toDate, pageSize, data])

  // Compute min/max dates from data so the picker is constrained to available range
  const { minDate, maxDate } = useMemo(() => {
    if (!dateField || data.length === 0) return { minDate: '', maxDate: '' }
    let min = Infinity, max = -Infinity
    for (const row of data) {
      const val = row[dateField]
      if (!val) continue
      const t = new Date(val).getTime()
      if (!isNaN(t)) { if (t < min) min = t; if (t > max) max = t }
    }
    const fmt = (ts: number) => new Date(ts).toISOString().slice(0, 10)
    return {
      minDate: isFinite(min) ? fmt(min) : '',
      maxDate: isFinite(max) ? fmt(max) : '',
    }
  }, [data, dateField])

  const filtered = useMemo(() => {
    if (!dateField || (!fromDate && !toDate)) return data
    const from = fromDate ? new Date(fromDate).getTime() : -Infinity
    const to   = toDate   ? new Date(toDate + 'T23:59:59').getTime() : Infinity
    return data.filter(row => {
      const val = row[dateField]
      if (!val) return false
      const t = new Date(val).getTime()
      return t >= from && t <= to
    })
  }, [data, dateField, fromDate, toDate])

  const totalPages = Math.max(1, Math.ceil(filtered.length / pageSize))
  const page = Math.min(currentPage, totalPages)
  const paginated = filtered.slice((page - 1) * pageSize, page * pageSize)

  const hasDateFilter = !!(fromDate || toDate)
  const isDateEmpty = hasDateFilter && filtered.length === 0

  // Build page number buttons (show up to 7: first, last, current ±2 with ellipsis)
  const pageButtons = useMemo(() => {
    if (totalPages <= 7) return Array.from({ length: totalPages }, (_, i) => i + 1)
    const pages: (number | '…')[] = []
    const add = (n: number) => { if (!pages.includes(n)) pages.push(n) }
    add(1)
    if (page > 3) pages.push('…')
    for (let i = Math.max(2, page - 2); i <= Math.min(totalPages - 1, page + 2); i++) add(i)
    if (page < totalPages - 2) pages.push('…')
    add(totalPages)
    return pages
  }, [totalPages, page])

  return (
    <div className={clsx('space-y-2', className)}>
      {/* Toolbar */}
      <div className="flex flex-wrap items-center gap-3">
        {dateField && (
          <div className="flex items-center gap-2 text-xs text-g-muted">
            <span>From</span>
            <input
              type="date"
              value={fromDate}
              min={minDate}
              max={toDate || maxDate}
              onChange={e => setFromDate(e.target.value)}
              style={{ colorScheme: 'dark' }}
              className="bg-g-deep border border-g-border rounded px-2 py-1 text-g-text text-xs focus:outline-none focus:border-accent cursor-pointer"
            />
            <span>To</span>
            <input
              type="date"
              value={toDate}
              min={fromDate || minDate}
              max={maxDate}
              onChange={e => setToDate(e.target.value)}
              style={{ colorScheme: 'dark' }}
              className="bg-g-deep border border-g-border rounded px-2 py-1 text-g-text text-xs focus:outline-none focus:border-accent cursor-pointer"
            />
            {hasDateFilter && (
              <button
                onClick={() => { setFromDate(''); setToDate('') }}
                className="text-g-muted hover:text-white transition-colors"
              >
                ✕
              </button>
            )}
          </div>
        )}
        <div className="flex items-center gap-2 text-xs text-g-muted ml-auto">
          <span>Rows per page</span>
          <select
            value={pageSize}
            onChange={e => setPageSize(Number(e.target.value))}
            className="bg-g-deep border border-g-border rounded px-2 py-1 text-g-text text-xs focus:outline-none focus:border-accent"
          >
            <option value={10}>10</option>
            <option value={50}>50</option>
            <option value={100}>100</option>
          </select>
        </div>
      </div>

      {/* Table */}
      <div className="overflow-x-auto rounded-xl border border-g-border">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-g-border bg-g-deep">
              {columns.map(col => (
                <th
                  key={col.key}
                  className={clsx(
                    'text-left px-4 py-3 text-xs font-semibold text-g-muted uppercase tracking-wider',
                    col.className
                  )}
                >
                  {col.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr>
                <td colSpan={columns.length} className="text-center py-8 text-g-muted">
                  Loading…
                </td>
              </tr>
            ) : isDateEmpty ? (
              <tr>
                <td colSpan={columns.length} className="text-center py-8 text-g-muted">
                  No data for this date range
                </td>
              </tr>
            ) : paginated.length === 0 ? (
              <tr>
                <td colSpan={columns.length} className="text-center py-8 text-g-muted">
                  {emptyText}
                </td>
              </tr>
            ) : (
              paginated.map((row, i) => (
                <tr
                  key={row[keyField] ?? i}
                  className="border-b border-g-border/50 hover:bg-white/2 transition-colors"
                >
                  {columns.map(col => (
                    <td key={col.key} className={clsx('px-4 py-3 text-g-text', col.className)}>
                      {col.render ? col.render(row) : String(row[col.key] ?? '—')}
                    </td>
                  ))}
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      {!loading && filtered.length > 0 && (
        <div className="flex items-center justify-between text-xs text-g-muted">
          <span>
            {filtered.length === data.length
              ? `${filtered.length} rows`
              : `${filtered.length} of ${data.length} rows`}
          </span>
          <div className="flex items-center gap-1">
            <button
              onClick={() => setCurrentPage(p => Math.max(1, p - 1))}
              disabled={page === 1}
              className="px-2 py-1 rounded border border-g-border disabled:opacity-30 hover:enabled:bg-g-deep transition-colors"
            >
              ‹
            </button>
            {pageButtons.map((b, i) =>
              b === '…' ? (
                <span key={`ellipsis-${i}`} className="px-1">…</span>
              ) : (
                <button
                  key={b}
                  onClick={() => setCurrentPage(b as number)}
                  className={clsx(
                    'px-2 py-1 rounded border transition-colors',
                    b === page
                      ? 'border-accent text-accent'
                      : 'border-g-border hover:bg-g-deep'
                  )}
                >
                  {b}
                </button>
              )
            )}
            <button
              onClick={() => setCurrentPage(p => Math.min(totalPages, p + 1))}
              disabled={page === totalPages}
              className="px-2 py-1 rounded border border-g-border disabled:opacity-30 hover:enabled:bg-g-deep transition-colors"
            >
              ›
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
