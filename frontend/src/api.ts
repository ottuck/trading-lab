// 백엔드 응답 타입과 호출. 금액(Decimal)은 JSON 문자열로 온다.

export type Money = string

export type Health = {
  version: string
  db: 'ok' | 'down'
  worker: { alive: boolean; worker_id: string | null; last_seen_at: string | null } | null
  demo?: boolean // 예시 데이터로 보는 공개 데모
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

/** 화면 원화 환산용 원/달러 매매기준율 (W1). 아직 받지 못했으면 null. */
export type Fx = { base: string; quote: string; rate: Money; as_of: string; source: string }

/** 실제 증권사 계좌를 마지막으로 읽은 결과 (실거래 R1). 읽기를 켜지 않았으면 null. */
export type BrokerAccount = {
  source: string | null // 출처 코드, 이름은 source.ts
  cash_usd: Money | null
  cash_krw: Money | null
  holdings: { symbol: string; name: string; currency: string; qty: Money; avg_price: Money; last_price: Money; value: Money }[]
  orders: { symbol: string; side: 'BUY' | 'SELL'; status: string; currency: string; ordered_at: string; amount: Money | null; qty: Money }[]
  fetched_at: string | null
  error: 'access' | 'temporary' | null // 권한·허용 IP 문제 | 일시 장애
  error_at: string | null
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
  budget?: Money | null // 이 주문에 쓸 돈 (나처럼 투자)
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
  live_ratio: Money | null // 실제로 따라 사기 비율 (꺼짐이면 null)
  live_streak: number // 연속으로 문제없이 체결된 실제 주문
}

/** 실제 주문 1건 (실거래 R2) */
export type LiveOrder = {
  id: number
  bot_id: number | null
  bot_name: string | null
  symbol: string
  side: 'BUY' | 'SELL'
  quantity: Money | null // 파는 수량 (이 봇이 실제로 산 만큼)
  signal_date: string
  trade_date: string
  amount: Money
  state: 'WAITING_APPROVAL' | 'APPROVED' | 'SENDING' | 'SENT' | 'FILLED' | 'CANCELED' | 'REJECTED' | 'SKIPPED' | 'UNKNOWN'
  reason: string | null
  filled_qty: Money | null
  filled_amount: Money | null
  carried_into: number | null // 작아서 모아 둔 몫이 더해진 주문
  created_at: string
  updated_at: string
}

export type Live = {
  trader: string | null // 실거래 스위치가 켜졌으면 증권사 출처 코드
  halted: boolean
  auto_after: number
  per_order: Money
  per_month: Money
  per_trade: Money // 사고팔기 봇 한 건 한도
  ratios: string[]
  shortfall: { symbol: string; held: Money; bought: Money }[] // 실제 계좌 대조: 봇이 산 것보다 적은 종목
  checked_at: string | null
  orders: LiveOrder[]
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
  fx: () => request<Fx | null>('/api/fx'),
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
  brokerAccount: () => request<BrokerAccount | null>('/api/broker-account'),
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
  summary: string
  risk: string
  trades: string
  presets: { key: string; label: string; params: Record<string, number> }[]
  default_params: Record<string, number>
  accumulates: boolean // 매달 입금하고 사 모으는 전략 (팔지 않음)
  ai: boolean // AI가 판단하는 전략 (시험해 보기·전략 고르기에는 나오지 않는다)
  preset_label: string
  // 프리셋과 따로 고르는 규칙 (예: 고점에 쉬기). 프리셋을 바꿔도 유지된다.
  choices: { key: string; label: string; options: { value: number; label: string }[]; hint: string; requires: string }[]
}

// 평행세계의 나 (나처럼 투자 전용, 저장하지 않음)
export type World = {
  key: string // me(나), dca(매달 그냥 사기), 그 밖은 규칙을 하나 바꾼 나
  title: string
  params: Record<string, number> | null
  final_equity: string
  contributed: string
  cagr: string
  same_as_me: boolean
  equity: { date: string; equity: string }[]
  recent: { month: string; bought: string }[] // 지난달·이번 달에 산 금액 (월간 정리)
}
export type Parallel = { start: string | null; end: string | null; worlds: World[]; note: string | null }

// AI 봇 (마일스톤 4): 하루 한 번 AI가 정한 목표 비중과 이유·출처. 현금은 CASH 키
export type AiDay = {
  session_date: string
  status: 'OK' | 'FAILED' | 'INVALID' | 'OVER_BUDGET'
  summary: string | null
  weights: Record<string, number> | null // 목표 비중 %
  weights_before: Record<string, Money> // 판단할 때의 비중 %
  reasons: Record<string, string> | null
  sources: { url: string; title: string; used?: boolean }[] // used: AI가 판단의 근거로 쓴 기사 (앞에 온다)
  queries: string[]
  model: string | null
  cost: Money | null
  error: string | null
  created_at: string
}
export type AiOverview = { latest: AiDay | null; history: AiDay[]; spent: Money; budget: Money }
export type ParallelRequest = {
  symbol: string
  symbols?: SymbolWeight[]
  params: Record<string, number>
  start?: string
  initial_cash?: string
}

// 따라 하기: 나 카피 봇이 다음에 할 일 (지금 가격이 이어진다면)
export type SymbolPlan = {
  symbol: string
  weight: number
  close: Money
  state: 'dip' | 'hot' | 'wait' | 'normal'
  dip_price: Money // 이 가격 이하면 모아 둔 돈까지 몰아 산다
  hot_price: Money | null // 이 가격 이상이면 그달은 쉰다
  buy: Money
  save: Money
}
export type Plan = {
  as_of: string
  deposit_date: string
  deposit: Money
  symbols: SymbolPlan[]
  reserve: Money
  reserve_items: { month: string; symbol: string; amount: Money }[]
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
  parallel: (body: ParallelRequest) =>
    request<Parallel>('/api/parallel', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }),
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
  parallel: (botId: number) => request<Parallel>(`/api/bots/${botId}/parallel`),
  ai: (botId: number) => request<AiOverview>(`/api/bots/${botId}/ai`),
  aiCompare: (botId: number) => request<Parallel>(`/api/bots/${botId}/ai/compare`),
  plan: (botId: number) => request<Plan | null>(`/api/bots/${botId}/plan`),
  updateSymbols: (botId: number, symbols: SymbolWeight[]) => request<Bot>(`/api/bots/${botId}/symbols`, json('PUT', { symbols })),
  rename: (botId: number, name: string) => request<Bot>(`/api/bots/${botId}`, json('PATCH', { name })),
  reset: (botId: number) => request<Bot>(`/api/bots/${botId}/reset`, { method: 'POST' }),
  remove: (botId: number) => request<void>(`/api/bots/${botId}`, { method: 'DELETE' }),
  setLive: (botId: number, ratio: string | null) => request<Bot>(`/api/bots/${botId}/live`, json('PUT', { ratio })),
  history: (botId: number) =>
    request<ConfigEvent[]>(`/api/events?bot_id=${botId}&kind=config_change&limit=20`),
}

export type NotifyScope = 'live' | 'all'
export type Notify = { available: boolean; enabled: boolean; scope: NotifyScope }

export const notifyApi = {
  get: () => request<Notify>('/api/notify'),
  update: (enabled: boolean, scope: NotifyScope) => request<Notify>('/api/notify', json('PUT', { enabled, scope })),
  test: () => request<void>('/api/notify/test', { method: 'POST' }),
}

export const liveApi = {
  get: () => request<Live>('/api/live'),
  approve: (orderId: number) => request<Live>(`/api/live-orders/${orderId}/approve`, { method: 'POST' }),
  decline: (orderId: number) => request<Live>(`/api/live-orders/${orderId}/decline`, { method: 'POST' }),
  halt: (halted: boolean) => request<Live>('/api/live/halt', json('POST', { halted })),
}
