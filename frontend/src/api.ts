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
  events: (level?: string) =>
    request<EventItem[]>(`/api/events?limit=200${level ? `&level=${level}` : ''}`),
  bars: (symbol: string) => request<Bar[]>(`/api/bars/${symbol}?limit=750`),
  command: (botId: number, kind: CommandKind) =>
    request<{ id: number }>(`/api/bots/${botId}/commands`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ kind }),
    }),
}
