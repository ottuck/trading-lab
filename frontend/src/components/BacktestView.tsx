import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ColorType, createChart, LineSeries, type Time } from 'lightweight-charts'
import { useEffect, useRef, useState } from 'react'
import { backtestApi, type BacktestDetail, type StrategyInfo } from '../api'
import { kstTime, money, percent, signedMoney, tone } from '../format'
import { strategyTitle, useStrategies } from '../strategies'
import { cssVar, useTheme } from '../theme'
import { Term } from './Help'
import { SymbolPicker } from './SymbolPicker'

const PERIODS = [
  { label: '최근 3년', years: 3 },
  { label: '최근 5년', years: 5 },
  { label: '최근 10년', years: 10 },
  { label: '가능한 처음부터', years: 0 },
]

function startDate(years: number): string | undefined {
  if (!years) return undefined
  const d = new Date()
  d.setFullYear(d.getFullYear() - years)
  return d.toISOString().slice(0, 10)
}

export function StrategyPicker({
  list,
  value,
  onChange,
}: {
  list: StrategyInfo[]
  value: string
  onChange: (name: string) => void
}) {
  return (
    <div className="pick-grid">
      {list.map((s) => (
        <button key={s.name} className={`pick ${s.name === value ? 'active' : ''}`} onClick={() => onChange(s.name)}>
          <div className="pick-title">
            {s.emoji} {s.nickname}
          </div>
          <div className="pick-desc">{s.summary}</div>
          <div className="pick-meta">
            위험 {s.risk} · 거래 {s.trades}
          </div>
        </button>
      ))}
    </div>
  )
}

function RunForm({ onDone }: { onDone: (id: string) => void }) {
  const qc = useQueryClient()
  const { list } = useStrategies()
  const [symbol, setSymbol] = useState('QQQ')
  const [strategy, setStrategy] = useState('sma_cross')
  const [years, setYears] = useState(10)
  const run = useMutation({
    mutationFn: () => {
      const info = list.find((s) => s.name === strategy)
      return backtestApi.run({ symbol, strategy, params: info?.default_params ?? {}, start: startDate(years) })
    },
    onSuccess: (d) => {
      void qc.invalidateQueries({ queryKey: ['backtests'] })
      onDone(d.id)
    },
  })
  return (
    <div className="stack">
      <div>
        <div className="label" style={{ marginBottom: 6 }}>
          어떤 전략으로?
        </div>
        <StrategyPicker list={list} value={strategy} onChange={setStrategy} />
      </div>
      <SymbolPicker label="어떤 종목을?" value={symbol} onChange={setSymbol} />
      <div className="controls">
        <span className="label">언제부터?</span>
        {PERIODS.map((p) => (
          <button key={p.years} className={`seg ${p.years === years ? 'active' : ''}`} onClick={() => setYears(p.years)}>
            {p.label}
          </button>
        ))}
      </div>
      <div className="controls">
        <button className="primary" disabled={run.isPending || !list.length} onClick={() => run.mutate()}>
          {run.isPending ? '계산 중…' : '$10,000로 시험해 보기'}
        </button>
        {run.error && <span className="bad small">{run.error.message}</span>}
      </div>
    </div>
  )
}

function EquityChart({ detail }: { detail: BacktestDetail }) {
  const el = useRef<HTMLDivElement>(null)
  const { theme } = useTheme()
  useEffect(() => {
    if (!el.current) return
    const grid = cssVar('--chart-grid')
    const chart = createChart(el.current, {
      autoSize: true,
      layout: {
        background: { type: ColorType.Solid, color: 'transparent' },
        textColor: cssVar('--muted'),
        fontFamily: 'Pretendard Variable, system-ui, sans-serif',
      },
      grid: { vertLines: { color: grid }, horzLines: { color: grid } },
      timeScale: { borderColor: grid },
      rightPriceScale: { mode: 1, borderColor: grid }, // 로그 눈금: 긴 기간의 오르내림을 비교하기 쉽다
    })
    const strat = chart.addSeries(LineSeries, { color: cssVar('--accent'), lineWidth: 2, title: '전략' })
    const bench = chart.addSeries(LineSeries, { color: cssVar('--muted'), lineWidth: 1, title: '그냥 보유' })
    strat.setData(detail.equity.map((p) => ({ time: p.session_date as Time, value: Number(p.equity) })))
    bench.setData(detail.equity.map((p) => ({ time: p.session_date as Time, value: Number(p.benchmark) })))
    chart.timeScale().fitContent()
    return () => chart.remove()
  }, [detail, theme])
  return <div ref={el} className="chart" />
}

function Metric({ term, a, b, t }: { term: string; a: string; b: string; t?: string | null }) {
  return (
    <div className="metric">
      <div className="label">
        <Term k={term} />
      </div>
      <div className={`value md ${tone(t)}`}>{a}</div>
      <div className="faint small">그냥 보유 {b}</div>
    </div>
  )
}

function Detail({ id, info }: { id: string; info?: StrategyInfo }) {
  const { data } = useQuery({ queryKey: ['backtest', id], queryFn: () => backtestApi.get(id), refetchInterval: false })
  const [showTrades, setShowTrades] = useState(false)
  if (!data) return <section className="card muted">불러오는 중…</section>
  const m = data.metrics
  const won = Number(m.final_equity) >= Number(m.benchmark_final_equity)
  const abs = (v: string | null | undefined) => percent(v).replace('+', '')
  return (
    <section className="card stack">
      <div className="card-title" style={{ marginBottom: 0 }}>
        {strategyTitle(info, data.strategy)} <span className="sub">{data.symbol}</span>
      </div>
      <div className="verdict">
        <div className="muted small">
          {m.start.slice(0, 4)}년 {Number(m.start.slice(5, 7))}월에 {money(m.initial_cash)}로 시작했다면
        </div>
        <div className="value big">{money(m.final_equity)}</div>
        <div className={`small ${tone(m.total_return)}`} style={{ fontWeight: 700 }}>
          {percent(m.total_return)} · 해마다 평균 {percent(m.cagr)}
        </div>
        <div className="muted" style={{ marginTop: 8 }}>
          <Term k="그냥 들고 있었다면" /> {money(m.benchmark_final_equity)} ({percent(m.benchmark_total_return)})
        </div>
        <div className={won ? 'ok' : 'warn'} style={{ marginTop: 6, fontWeight: 600 }}>
          {won ? '👍 그냥 들고 있는 것보다 결과가 좋았어요.' : '그냥 들고 있는 게 더 많이 벌었어요.'}{' '}
          {Number(m.max_drawdown) > Number(m.benchmark_max_drawdown)
            ? `${won ? '게다가' : '대신'} 가장 크게 떨어진 폭은 ${abs(m.max_drawdown)}로, 그냥 보유(${abs(m.benchmark_max_drawdown)})보다 작았어요.`
            : ''}
        </div>
      </div>
      <div className="metric-grid">
        <Metric term="연평균 수익률" a={percent(m.cagr)} b={percent(m.benchmark_cagr)} t={m.cagr} />
        <Metric term="가장 크게 떨어진 폭" a={abs(m.max_drawdown)} b={abs(m.benchmark_max_drawdown)} />
        {m.volatility !== undefined && <Metric term="가격 출렁임" a={abs(m.volatility)} b={abs(m.benchmark_volatility)} />}
        {m.sharpe !== undefined && (
          <Metric
            term="위험 대비 수익 점수"
            a={m.sharpe == null ? '—' : Number(m.sharpe).toFixed(2)}
            b={m.benchmark_sharpe == null ? '—' : Number(m.benchmark_sharpe).toFixed(2)}
          />
        )}
        <div className="metric">
          <div className="label">
            <Term k="투자 중이던 기간" />
          </div>
          <div className="value md">{abs(m.exposure)}</div>
          <div className="faint small">
            거래 {m.round_trips}번 · <Term k="이긴 거래 비율">이긴 비율</Term> {m.win_rate == null ? '—' : abs(m.win_rate)}
          </div>
        </div>
      </div>
      <EquityChart detail={data} />
      <div className="faint small">파란 선: 이 전략 · 회색 선: 그냥 들고 있었을 때 (눈금은 비율 기준)</div>
      {m.annual_returns && m.annual_returns.length > 0 && (
        <>
          <h3 style={{ margin: '8px 0 0' }}>해마다 어땠나요?</h3>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>연도</th>
                  <th className="num">이 전략</th>
                  <th className="num">그냥 보유</th>
                </tr>
              </thead>
              <tbody>
                {[...m.annual_returns].reverse().map((y) => (
                  <tr key={y.year}>
                    <td>{y.year}</td>
                    <td className={`num ${tone(y.strategy)}`}>{percent(y.strategy)}</td>
                    <td className={`num ${tone(y.benchmark)}`}>{percent(y.benchmark)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
      <button className="link" onClick={() => setShowTrades(!showTrades)}>
        {showTrades ? '거래 내역 숨기기' : `거래 내역 보기 (${data.fills.length}건)`}
      </button>
      {showTrades && (
        <ul className="trades">
          {[...data.fills].reverse().map((f) => (
            <li key={`${f.fill_date}-${f.side}`}>
              <span className={`side ${f.side === 'BUY' ? 'rise' : 'fall'}`}>{f.side === 'BUY' ? '샀어요' : '팔았어요'}</span>
              <div>
                <div>
                  {f.qty}주 · 한 주 {money(f.price)}
                </div>
                <div className="faint small">{f.fill_date}</div>
              </div>
              {f.realized_pnl != null && <span className={`pnl ${tone(f.realized_pnl)}`}>{signedMoney(f.realized_pnl)}</span>}
            </li>
          ))}
        </ul>
      )}
      <div className="faint small">
        가정: 장 마감 가격으로 판단하고 다음 날 장이 열릴 때 사고팔아요. 토스증권 수수료 0.1%와 조금 불리한 체결 가격을
        반영했어요. 과거 결과가 미래를 보장하지는 않아요.
      </div>
    </section>
  )
}

export function BacktestView() {
  const { byName } = useStrategies()
  const { data: list } = useQuery({ queryKey: ['backtests'], queryFn: backtestApi.list, refetchInterval: false })
  const [selected, setSelected] = useState<string | null>(null)
  const current = selected ?? list?.[0]?.id ?? null
  const currentInfo = list?.find((b) => b.id === current)
  return (
    <>
      <section className="card stack">
        <div>
          <div className="card-title" style={{ marginBottom: 4 }}>
            과거로 시험해 보기
          </div>
          <div className="muted small">전략을 고르면, 그 전략을 예전부터 따라 했다면 어땠을지 실제 가격으로 계산해요.</div>
        </div>
        <RunForm onDone={setSelected} />
      </section>
      {current && <Detail id={current} info={currentInfo ? byName[currentInfo.strategy] : undefined} />}
      {list && list.length > 0 && (
        <section className="card">
          <div className="card-title">지난 시험</div>
          <ul className="history">
            {list.map((b) => (
              <li key={b.id} className={b.id === current ? 'selected' : ''} onClick={() => setSelected(b.id)}>
                <div>
                  <div>
                    {strategyTitle(byName[b.strategy], b.strategy)} · {b.symbol}
                  </div>
                  <div className="faint small">
                    {b.metrics.start.slice(0, 4)}년부터 · {kstTime(b.created_at)}
                  </div>
                </div>
                <div style={{ textAlign: 'right' }}>
                  <div className={tone(b.metrics.cagr)} style={{ fontWeight: 700 }}>
                    연 {percent(b.metrics.cagr)}
                  </div>
                  <div className="faint small">보유 연 {percent(b.metrics.benchmark_cagr)}</div>
                </div>
              </li>
            ))}
          </ul>
        </section>
      )}
    </>
  )
}
