// 백엔드 응답 타입과 호출. 금액(Decimal)은 JSON 문자열로 온다.

export type Money = string

export type Health = {
  version: string
  db: 'ok' | 'down'
  worker: { alive: boolean; worker_id: string | null; last_seen_at: string | null } | null
}

/** 종목과 비율(%). 봇의 비율 합은 100이다. */
export type SymbolWeight = { symbol: string; weight: number }

/** 종목 하나의 보유와 평가 (장 마감 기준 + 있으면 실시간). */
export type Position = {
  symbol: string
  weight: number
  qty: Money
  avg_cost: Money
  last_close: Money | null
  last_close_date: string | null
  market_value: Money | null
  unrealized_pnl: Money | null
  live_price?: Money | null
  live_at?: string | null
  live_change?: Money | null
}

/** qty·avg_cost·last_close·live_price는 대표 종목(첫 종목), 평가금액·손익·자산은 모든 종목 합계. */
export type Account = {
  initial_cash: Money
  cash: Money
  qty: Money // 소수점 6자리까지 (2026-10-02~)
  avg_cost: Money
  realized_pnl: Money
  last_close: Money | null
  last_close_date: string | null
  market_value: Money | null
  unrealized_pnl: Money | null
  equity: Money | null
  total_return: Money | null // 넣은 돈 대비
  contributed: Money // 넣은 돈 (시작 금액 + 정기 입금)
  // 실시간(화면 표시용). 판단은 장 마감 기준 값을 쓴다.
  live_price?: Money | null
  live_at?: string | null
  live_change?: Money | null
  live_equity?: Money | null
  live_unrealized_pnl?: Money | null
  reserve: Money // 모으기 전략이 고점 때 모아 둔 돈
  positions: Position[]
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
  symbol: string
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
  symbol: string
  side: 'BUY' | 'SELL'
  status: 'PENDING' | 'FILLED' | 'UNFILLED'
  signal_date: string
  fill_date: string | null
  qty: Money | null
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
  symbols: SymbolWeight[] // 종목과 비율. 첫 종목이 대표 종목
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
  last_decisions: Decision[] // 마지막 판단일의 종목별 판단
  pending_order: Order | null
  pending_orders: Order[]
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

/** 하루 자산. contributed는 넣은 돈, benchmark는 같은 돈으로 그냥 들고 있었다면. */
export type EquityPoint = { date: string; equity: Money; contributed: Money; benchmark: Money; live?: boolean }

export type Bar = { date: string; open: Money; high: Money; low: Money; close: Money; volume: Money; live?: boolean }

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, init)
  if (!res.ok && res.status !== 503) {
    // FastAPI의 {"detail": "..."}는 사람이 읽는 문장만 보여준다.
    const text = await res.text()
    let message = text.slice(0, 200)
    try {
      const detail = (JSON.parse(text) as { detail?: unknown }).detail
      if (typeof detail === 'string') message = detail
    } catch {
      // JSON이 아니면 원문 일부를 그대로 쓴다.
    }
    throw new Error(message || `요청 실패 (${res.status})`)
  }
  if (res.status === 204) return undefined as T
  return (await res.json()) as T
}

export const api = {
  health: () => request<Health>('/api/health'),
  bots: () => request<Bot[]>('/api/bots'),
  orders: (botId: number) => request<Order[]>(`/api/bots/${botId}/orders?limit=20`),
  decisions: (botId: number) => request<Decision[]>(`/api/bots/${botId}/decisions?limit=500`),
  equity: (botId: number) => request<EquityPoint[]>(`/api/bots/${botId}/equity`),
  activity: (botId: number, kind?: string, limit = 10) =>
    request<ActivityItem[]>(`/api/activity?bot_id=${botId}&limit=${limit}${kind ? `&kind=${kind}` : ''}`),
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
  accumulates: boolean // 매달 입금하고 사 모으는 전략 (팔지 않음)
  preset_label: string
  // 프리셋과 따로 고르는 규칙 (예: 고점에 쉬기). 프리셋을 바꿔도 유지된다.
  choices: { key: string; label: string; options: { value: number; label: string }[]; hint: string; requires: string }[]
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
  // 2026-10-02 이후: 정기 입금 (모으기 전략). 없으면 입금 없음
  contributed?: Money
  deposits?: number
}

export type BacktestSummary = {
  id: string
  created_at: string
  symbol: string
  symbols?: SymbolWeight[] | null // 여러 종목 시험이면 종목과 비율
  strategy: string
  params: Record<string, number>
  metrics: BacktestMetrics
}

export type BacktestFill = {
  side: 'BUY' | 'SELL'
  signal_date: string
  fill_date: string
  qty: Money
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
  symbols?: SymbolWeight[]
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

export type BotCreate = BotConfig & { name: string; symbol: string; symbols?: SymbolWeight[]; initial_cash: string }

export type ConfigEvent = EventItem & { data: { before?: Record<string, unknown>; after?: Record<string, unknown> } | null }

const json = (method: string, body: unknown): RequestInit => ({
  method,
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body),
})

export const botApi = {
  create: (body: BotCreate) => request<Bot>('/api/bots', json('POST', body)),
  updateConfig: (botId: number, body: BotConfig) => request<Bot>(`/api/bots/${botId}/config`, json('PUT', body)),
  updateSymbols: (botId: number, symbols: SymbolWeight[]) => request<Bot>(`/api/bots/${botId}/symbols`, json('PUT', { symbols })),
  rename: (botId: number, name: string) => request<Bot>(`/api/bots/${botId}`, json('PATCH', { name })),
  reset: (botId: number) => request<Bot>(`/api/bots/${botId}/reset`, { method: 'POST' }),
  remove: (botId: number) => request<void>(`/api/bots/${botId}`, { method: 'DELETE' }),
  history: (botId: number) =>
    request<ConfigEvent[]>(`/api/events?bot_id=${botId}&kind=config_change&limit=20`),
}
