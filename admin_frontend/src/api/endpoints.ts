import api from './client'

// Auth
export const login = (email: string, password: string) =>
  api.post('/auth/login', { email, password }).then(r => r.data)

export const getMe = () =>
  api.get('/auth/me').then(r => r.data)

// Dashboard
export const getKpis = () =>
  api.get('/api/dashboard/kpis').then(r => r.data)

export const getAlerts = () =>
  api.get('/api/dashboard/alerts').then(r => r.data)

export const getActivity = () =>
  api.get('/api/dashboard/activity').then(r => r.data)

// Trading
export const getBots = () =>
  api.get('/api/trading/bots').then(r => r.data)

export const getBotDetail = (profile: string) =>
  api.get(`/api/trading/bots/${profile}`).then(r => r.data)

export const getEnsemble = () =>
  api.get('/api/trading/ensemble').then(r => r.data)

export const getTrades = (page = 1, limit = 50) =>
  api.get(`/api/trading/trades?page=${page}&limit=${limit}`).then(r => r.data)

export const getSignals = () =>
  api.get('/api/trading/signals').then(r => r.data)

// Clients
export const getClients = (params: Record<string, any> = {}) =>
  api.get('/api/clients', { params }).then(r => r.data)

export const getClientDetail = (id: number) =>
  api.get(`/api/clients/${id}`).then(r => r.data)

export const updateClientTier = (id: number, tier: string) =>
  api.put(`/api/clients/${id}/tier`, { tier }).then(r => r.data)

export const updateClientStatus = (id: number, status: string) =>
  api.put(`/api/clients/${id}/status`, { status }).then(r => r.data)

// Billing
export const getBillingSummary = () =>
  api.get('/api/billing/summary').then(r => r.data)

export const getPlans = () =>
  api.get('/api/billing/plans').then(r => r.data)

export const getEmailSignups = (page = 1) =>
  api.get(`/api/billing/email-signups?page=${page}`).then(r => r.data)

// Infrastructure
export const getServices = () =>
  api.get('/api/infra/services').then(r => r.data)

export const getSystem = () =>
  api.get('/api/infra/system').then(r => r.data)

export const getLogs = (service: string, lines: number = 100) =>
  api.get(`/api/infra/logs?service=${service}&lines=${lines}`).then(r => r.data)

// Settings
export const getAdminUsers = () =>
  api.get('/api/settings/users').then(r => r.data)

export const createAdminUser = (data: { email: string; password: string; role: string }) =>
  api.post('/api/settings/users', data).then(r => r.data)

export const updateAdminUser = (id: number, data: { role?: string; is_active?: boolean }) =>
  api.put(`/api/settings/users/${id}`, data).then(r => r.data)

export const getAuditLog = (page = 1) =>
  api.get(`/api/settings/audit?page=${page}`).then(r => r.data)

export const getEnvStatus = () =>
  api.get('/api/settings/env-status').then(r => r.data)

// ── Bot trading data ────────────────────────────────────────────────────────
export const getBotHeartbeats = () =>
  api.get('/api/bots/heartbeats').then(r => r.data)

export const getBotPositions = (params: { bot?: string; open_only?: boolean; closed_since_hours?: number; limit?: number } = {}) =>
  api.get('/api/bots/positions', { params }).then(r => r.data)

export const getBotEvents = (params: { bot?: string; event_type?: string; limit?: number; page?: number } = {}) =>
  api.get('/api/bots/events', { params }).then(r => r.data)

export const getBotStats = () =>
  api.get('/api/bots/stats').then(r => r.data)

// ── Oracle coordinator ───────────────────────────────────────────────────────
export const getOracleStatus = () =>
  api.get('/api/oracle/status').then(r => r.data)

export const getOracleAlerts = () =>
  api.get('/api/oracle/alerts').then(r => r.data)

export const dismissOracleAlert = (id: number) =>
  api.delete(`/api/oracle/alerts/${id}`).then(r => r.data)

export const dismissAllOracleAlerts = () =>
  api.delete('/api/oracle/alerts').then(r => r.data)

// ── AI Analytics ─────────────────────────────────────────────────────────────
export const getAnalyticsOverview = (days: number) =>
  api.get(`/api/analytics/overview?days=${days}`).then(r => r.data)

export const getAnalyticsTimeline = (days: number) =>
  api.get(`/api/analytics/timeline?days=${days}`).then(r => r.data)

export const getAnalyticsModelAccuracy = (days: number) =>
  api.get(`/api/analytics/model-accuracy?days=${days}`).then(r => r.data)

export const getAnalyticsConfidenceDist = (days: number) =>
  api.get(`/api/analytics/confidence-distribution?days=${days}`).then(r => r.data)

export const getAnalyticsCorrelation = (days: number) =>
  api.get(`/api/analytics/correlation?days=${days}`).then(r => r.data)

export const getAnalyticsHistory = (days: number, limit = 100) =>
  api.get(`/api/analytics/history?days=${days}&limit=${limit}`).then(r => r.data)

export const getAnalyticsLive = () =>
  api.get('/api/analytics/live').then(r => r.data)

// ── Interactive Brokers ───────────────────────────────────────────────────────
export const getIBStatus = () =>
  api.get('/api/ib/status').then(r => r.data)

export const getIBAccount = () =>
  api.get('/api/ib/account').then(r => r.data)

export const getIBPositions = () =>
  api.get('/api/ib/positions').then(r => r.data)

export const getIBQuote = (symbol: string, secType = 'STK', exchange = 'SMART', currency = 'USD') =>
  api.get('/api/ib/quote', { params: { symbol, sec_type: secType, exchange, currency } }).then(r => r.data)

export const getIBHistorical = (params: {
  symbol: string
  sec_type: string
  exchange: string
  currency: string
  bar_size: string
  duration: string
  what_to_show?: string
}) => api.get('/api/ib/historical', { params }).then(r => r.data)

// ── Control Centre ────────────────────────────────────────────────────────────
export const getCC_Containers  = () => api.get('/api/cc/containers').then(r => r.data)
export const restartContainer  = (name: string) => api.post(`/api/cc/containers/${name}/restart`).then(r => r.data)
export const getCC_System      = () => api.get('/api/cc/system').then(r => r.data)
export const getCC_Redis       = () => api.get('/api/cc/redis').then(r => r.data)
export const getCC_Postgres    = () => api.get('/api/cc/postgres').then(r => r.data)
export const getCC_Logs        = (service: string, lines = 50) =>
  api.get(`/api/cc/logs?service=${service}&lines=${lines}`).then(r => r.data)

// ── Telegram Bot Management ──────────────────────────────────────────────────
export const getTgStatus         = () => api.get('/api/tg/status').then(r => r.data)
export const getTgStats          = () => api.get('/api/tg/stats').then(r => r.data)
export const getTgLogs           = (lines = 50) => api.get(`/api/tg/logs?lines=${lines}`).then(r => r.data)
export const getTgUsers          = (params: Record<string, any> = {}) => api.get('/api/tg/users', { params }).then(r => r.data)
export const tgBroadcast         = (data: { message: string; tier?: string }) => api.post('/api/tg/broadcast', data).then(r => r.data)
export const tgBroadcastPreview  = (tier?: string) => api.get('/api/tg/broadcast/preview', { params: { tier } }).then(r => r.data)
export const tgResetUserQueries  = (id: number) => api.post(`/api/tg/users/${id}/reset-queries`).then(r => r.data)
export const tgSendDM            = (id: number, message: string) => api.post(`/api/tg/users/${id}/send-dm`, { message }).then(r => r.data)
export const tgSuspendUser       = (id: number, suspend: boolean) => api.post(`/api/tg/users/${id}/suspend`, { suspend }).then(r => r.data)

// ── User Management (Admin) ──────────────────────────────────────────────────
export const getAdminCustomers    = (params: Record<string, any> = {}) => api.get('/api/admin/customers', { params }).then(r => r.data)
export const bulkChangeTier       = (ids: number[], tier: string) => api.post('/api/admin/customers/bulk-tier', { ids, tier }).then(r => r.data)
export const bulkSuspend          = (ids: number[]) => api.post('/api/admin/customers/bulk-suspend', { ids }).then(r => r.data)
export const updateCustomerPrefs  = (id: number, prefs: Record<string, any>) => api.put(`/api/admin/customers/${id}/preferences`, prefs).then(r => r.data)

// Oracle live proxy
export const getOracleLive = (endpoint: string) =>
  api.get(`/api/oracle/live/${endpoint}`).then(r => r.data)

// Oracle control
export const oracleKillAll = () =>
  api.post('/api/oracle/control/kill').then(r => r.data)

export const oracleStopBot = (bot: string) =>
  api.post(`/api/oracle/control/stop/${bot}`).then(r => r.data)

export const oracleStartBot = (bot: string) =>
  api.post(`/api/oracle/control/start/${bot}`).then(r => r.data)
