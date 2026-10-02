// 백엔드 응답 타입과 호출. 금액(Decimal)은 JSON 문자열로 온다.

export type Money = string

export type Health = {
  version: string
  db: 'ok' | 'down'
  worker: { alive: boolean; worker_id: string | null; last_seen_at: string | null } | null
}

export type Account = {
  initial_cash: Money
  cash: Money
  qty: number
  avg_cost: Money
  realized_pnl: Money
  last_close: Money | null
  last_close_date: string | null
  market_value: Money | null
  unrealized_pnl: Money | null
  equity: Money | null
  total_return: Money | null
  // 실시간(화면 표시용). 판단은 장 마감 기준 값을 쓴다.
  live_price?: Money | null
  live_at?: string | null
  live_change?: Money | null
  live_equity?: Money | null
  live_unrealized_pnl?: Money | null
}

export type Instrument = {
  symbol: string
  name: string | null
  leverage_factor: Money | null
  live_price: Money | null
  live_at: string | null
}

export type Decision = {
  id: number
  session_date: string
  action: 'BUY' | 'SELL' | 'HOLD'
  target_long: boolean
  holding: boolean
  reason: string
  indicators: Record<string, string>
  blocked: string | null
  created_at: string
  plain_reason: string
  plain_action: string
}

export type Order = {
  id: number
  side: 'BUY' | 'SELL'
  status: 'PENDING' | 'FILLED' | 'UNFILLED'
  signal_date: string
  fill_date: string | null
  qty: number | null
  price: Money | null
  commission: Money | null
  realized_pnl: Money | null
  note: string | null
}

export type Run = {
  id: string
  trigger: 'SCHEDULED' | 'MANUAL'
  started_at: string
  finished_at: string | null
  session_date: string | null
  status: 'RUNNING' | 'OK' | 'SKIPPED' | 'ERROR'
  detail: string | null
}

export type BotState = 'STOPPED' | 'RUNNING' | 'PAUSED' | 'ERROR'
export type CommandKind = 'START' | 'PAUSE' | 'STOP' | 'RUN_ONCE'

export type Bot = {
  id: number
  name: string
  symbol: string
  strategy: string
  params: Record<string, number>
  state: BotState
  state_reason: string | null
  commission_rate: Money
  slippage_bps: Money
  risk: Record<string, string | null>
  next_evaluation_at: string | null
  account: Account
  last_decision: Decision | null
  pending_order: Order | null
  last_run: Run | null
  data_latest_date: string | null
  data_fetched_at: string | null
  data_source: string | null
}

export type EventItem = {
  id: number
  at: string
  level: 'INFO' | 'WARN' | 'ERROR'
  kind: string
  message: string
  bot_id: number | null
  run_id: string | null
}

export type Bar = { date: string; open: Money; high: Money; low: Money; close: Money; volume: Money }

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, init)
  if (!res.ok && res.status !== 503) {
    const text = await res.text()
    throw new Error(`${res.status} ${text.slice(0, 200)}`)
  }
  return (await res.json()) as T
}

export const api = {
  health: () => request<Health>('/api/health'),
  bots: () => request<Bot[]>('/api/bots'),
  orders: (botId: number) => request<Order[]>(`/api/bots/${botId}/orders?limit=20`),
  decisions: (botId: number) => request<Decision[]>(`/api/bots/${botId}/decisions?limit=500`),
  activity: (botId: number, kind?: string) =>
    request<ActivityItem[]>(`/api/activity?bot_id=${botId}&limit=${kind ? 10 : 8}${kind ? `&kind=${kind}` : ''}`),
  events: (level?: string) =>
    request<EventItem[]>(`/api/events?limit=200${level ? `&level=${level}` : ''}`),
  bars: (symbol: string) => request<Bar[]>(`/api/bars/${symbol}?limit=750`),
  instruments: () => request<Instrument[]>('/api/instruments'),
  command: (botId: number, kind: CommandKind) =>
    request<{ id: number }>(`/api/bots/${botId}/commands`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ kind }),
    }),
}

export type StrategyInfo = {
  name: string
  nickname: string
  emoji: string
  summary: string
  risk: string
  trades: string
  presets: { key: string; label: string; params: Record<string, number> }[]
  default_params: Record<string, number>
}

export type ActivityItem = { id: number; at: string; icon: string; title: string; body: string; level: string }

export type BacktestMetrics = {
  start: string
  end: string
  initial_cash: Money
  final_equity: Money
  total_return: Money
  cagr: Money
  max_drawdown: Money
  exposure: Money
  round_trips: number
  win_rate: Money | null
  benchmark_final_equity: Money
  benchmark_total_return: Money
  benchmark_cagr: Money
  benchmark_max_drawdown: Money
  // 2026-10-02 이후 저장된 백테스트에만 있음
  volatility?: Money
  sharpe?: Money | null
  benchmark_volatility?: Money
  benchmark_sharpe?: Money | null
  annual_returns?: { year: number; strategy: Money; benchmark: Money }[]
}

export type BacktestSummary = {
  id: string
  created_at: string
  symbol: string
  strategy: string
  params: Record<string, number>
  metrics: BacktestMetrics
}

export type BacktestFill = {
  side: 'BUY' | 'SELL'
  signal_date: string
  fill_date: string
  qty: number
  price: Money
  commission: Money
  realized_pnl: Money | null
}

export type BacktestDetail = BacktestSummary & {
  data_start: string
  data_end: string
  commission_rate: Money
  slippage_bps: Money
  fills: BacktestFill[]
  equity: { session_date: string; equity: Money; benchmark: Money }[]
}

export type BacktestRequest = {
  symbol: string
  strategy: string
  params: Record<string, number>
  start?: string
  initial_cash?: string
}

export const backtestApi = {
  strategies: () => request<StrategyInfo[]>('/api/strategies'),
  list: () => request<BacktestSummary[]>('/api/backtests?limit=30'),
  get: (id: string) => request<BacktestDetail>(`/api/backtests/${id}`),
  run: (body: BacktestRequest) =>
    request<BacktestDetail>('/api/backtests', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
}

export type BotConfig = {
  strategy: string
  params: Record<string, number>
  commission_rate: string
  slippage_bps: string
  max_position_value: string | null
  max_order_value: string | null
}

export type BotCreate = BotConfig & { name: string; symbol: string; initial_cash: string }

export type ConfigEvent = EventItem & { data: { before?: Record<string, unknown>; after?: Record<string, unknown> } | null }

const json = (method: string, body: unknown): RequestInit => ({
  method,
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body),
})

export const botApi = {
  create: (body: BotCreate) => request<Bot>('/api/bots', json('POST', body)),
  updateConfig: (botId: number, body: BotConfig) => request<Bot>(`/api/bots/${botId}/config`, json('PUT', body)),
  history: (botId: number) =>
    request<ConfigEvent[]>(`/api/events?bot_id=${botId}&kind=config_change&limit=20`),
}
