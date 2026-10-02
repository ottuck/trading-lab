import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ColorType, createChart, LineSeries, type Time } from 'lightweight-charts'
import { useEffect, useRef, useState } from 'react'
import { backtestApi, type BacktestDetail, type StrategyInfo } from '../api'
import { money, percent, signedMoney, tone } from '../format'
import { useStrategies } from '../strategies'
import { cssVar, useTheme } from '../theme'
import { Term } from './Help'
import { startNewBot } from '../selectedBot'
import { StrategyPicker } from './StrategyPicker'
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

/** '2021-01-04' → '2021년 1월' */
function ym(date: string) {
  return `${date.slice(0, 4)}년 ${Number(date.slice(5, 7))}월`
}

const created = new Intl.DateTimeFormat('ko-KR', { timeZone: 'Asia/Seoul', month: 'long', day: 'numeric' })

type Choice = { symbol: string; strategy: string }

function RunForm({
  choice,
  onChoice,
  onDone,
}: {
  choice: Choice
  onChoice: (c: Choice) => void
  onDone: (id: string) => void
}) {
  const qc = useQueryClient()
  const { list } = useStrategies()
  const { symbol, strategy } = choice
  const setSymbol = (s: string) => onChoice({ ...choice, symbol: s })
  const setStrategy = (s: string) => onChoice({ ...choice, strategy: s })
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
    <section className="bt-form">
      <div className="block-head">
        <h2>과거로 시험해 보기</h2>
        <span className="sub">그 전략을 예전부터 따라 했다면 어땠을지 실제 가격으로 계산해요</span>
      </div>
      <div className="stack">
        <StrategyPicker list={list} value={strategy} onChange={setStrategy} />
        <SymbolPicker label="종목" value={symbol} onChange={setSymbol} />
        <div className="controls">
          <span className="label">기간</span>
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
    </section>
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
        fontFamily: cssVar('--sans'),
      },
      crosshair: { vertLine: { color: cssVar('--chart-cross') }, horzLine: { color: cssVar('--chart-cross') } },
      grid: { vertLines: { visible: false }, horzLines: { color: grid } },
      timeScale: { borderVisible: false },
      rightPriceScale: { mode: 1, borderVisible: false }, // 로그 눈금: 긴 기간의 오르내림을 비교하기 쉽다
    })
    const strat = chart.addSeries(LineSeries, { color: cssVar('--text'), lineWidth: 2, priceLineVisible: false })
    const bench = chart.addSeries(LineSeries, { color: cssVar('--faint'), lineWidth: 1, priceLineVisible: false })
    strat.setData(detail.equity.map((p) => ({ time: p.session_date as Time, value: Number(p.equity) })))
    bench.setData(detail.equity.map((p) => ({ time: p.session_date as Time, value: Number(p.benchmark) })))
    chart.timeScale().fitContent()
    return () => chart.remove()
  }, [detail, theme])
  return <div ref={el} className="bt-chart" />
}

function Fact({ term, a, b, t }: { term: string; a: React.ReactNode; b: React.ReactNode; t?: string | null }) {
  return (
    <div className="fact">
      <div className="label">
        <Term k={term} />
      </div>
      <div className={`value ${tone(t)}`}>{a}</div>
      <div className="sub">{b}</div>
    </div>
  )
}

function Result({ id, info }: { id: string; info?: StrategyInfo }) {
  const { data } = useQuery({ queryKey: ['backtest', id], queryFn: () => backtestApi.get(id), refetchInterval: false })
  const [showTrades, setShowTrades] = useState(false)
  if (!data) return <div className="line-empty">불러오는 중…</div>
  const m = data.metrics
  const won = Number(m.final_equity) >= Number(m.benchmark_final_equity)
  const smallerDrop = Number(m.max_drawdown) > Number(m.benchmark_max_drawdown)
  const abs = (v: string | null | undefined) => percent(v).replace('+', '')
  const gain = String(Number(m.final_equity) - Number(m.initial_cash))
  return (
    <section className="bt-result">
      <div className="hero-head">
        <div>
          <div className="bot-line">
            <span className="name">{info?.nickname ?? data.strategy}</span>
            <span>
              · {data.symbol} · {ym(m.start)}부터 {money(m.initial_cash)}로 시작했다면
            </span>
          </div>
          <div className="hero-value">{money(m.final_equity)}</div>
          <div className="hero-delta">
            <span className={tone(m.total_return)}>
              {signedMoney(gain)} ({percent(m.total_return)})
            </span>
            <span className="when">해마다 평균 {percent(m.cagr)}</span>
          </div>
        </div>
        <div className="hero-actions">
          <button className="primary" onClick={() => startNewBot({ symbol: data.symbol, strategy: data.strategy, params: data.params })}>
            이 전략으로 모의 투자 시작
          </button>
        </div>
      </div>
      <p className="bt-verdict">
        <span className={`mark ${won ? 'rise' : 'fall'}`} />
        <span>
          {won ? '그냥 들고 있는 것보다 결과가 좋았어요.' : '그냥 들고 있는 게 더 많이 벌었어요.'}{' '}
          {smallerDrop &&
            `${won ? '게다가' : '대신'} 가장 크게 떨어진 폭은 ${abs(m.max_drawdown)}로, 그냥 보유(${abs(m.benchmark_max_drawdown)})보다 작았어요.`}
        </span>
      </p>

      <EquityChart detail={data} />
      <div className="eq-foot">
        <span className="legend">
          <i className="strat" />이 전략
        </span>
        <span className="legend">
          <i className="bench" />
          <Term k="그냥 들고 있었다면">그냥 보유</Term> {money(m.benchmark_final_equity)} ({percent(m.benchmark_total_return)})
        </span>
        <span className="paper">눈금은 비율 기준</span>
      </div>

      <div className="facts bt-facts">
        <Fact term="연평균 수익률" a={percent(m.cagr)} b={`그냥 보유 ${percent(m.benchmark_cagr)}`} t={m.cagr} />
        <Fact term="가장 크게 떨어진 폭" a={abs(m.max_drawdown)} b={`그냥 보유 ${abs(m.benchmark_max_drawdown)}`} />
        {m.volatility !== undefined && (
          <Fact term="가격 출렁임" a={abs(m.volatility)} b={`그냥 보유 ${abs(m.benchmark_volatility)}`} />
        )}
        {m.sharpe !== undefined && (
          <Fact
            term="위험 대비 수익 점수"
            a={m.sharpe == null ? '—' : Number(m.sharpe).toFixed(2)}
            b={`그냥 보유 ${m.benchmark_sharpe == null ? '—' : Number(m.benchmark_sharpe).toFixed(2)}`}
          />
        )}
        <Fact
          term="투자 중이던 기간"
          a={abs(m.exposure)}
          b={
            <>
              거래 {m.round_trips}번 · <Term k="이긴 거래 비율">이긴 비율</Term> {m.win_rate == null ? '—' : abs(m.win_rate)}
            </>
          }
        />
      </div>

      {m.annual_returns && m.annual_returns.length > 0 && (
        <section className="block">
          <div className="block-head">
            <h2>해마다 어땠나요?</h2>
          </div>
          <div className="table-wrap">
            <table className="ledger">
              <thead>
                <tr>
                  <th>연도</th>
                  <th className="num">이 전략</th>
                  <th className="num">그냥 보유</th>
                  <th className="num">차이</th>
                </tr>
              </thead>
              <tbody>
                {[...m.annual_returns].reverse().map((y) => {
                  const diff = String((Number(y.strategy) - Number(y.benchmark)) * 100)
                  return (
                    <tr key={y.year}>
                      <td className="d">{y.year}</td>
                      <td className={`num ${tone(y.strategy)}`}>{percent(y.strategy)}</td>
                      <td className={`num ${tone(y.benchmark)}`}>{percent(y.benchmark)}</td>
                      <td className="num faint">
                        {Number(diff) > 0 ? '+' : ''}
                        {Number(diff).toFixed(1)}%p
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </section>
      )}

      <section className="block">
        <div className="block-head">
          <h2>거래 내역</h2>
          <span className="sub">{data.fills.length}건</span>
          {data.fills.length > 0 && (
            <button className="link" aria-expanded={showTrades} onClick={() => setShowTrades(!showTrades)}>
              {showTrades ? '숨기기' : '펼쳐 보기'}
            </button>
          )}
        </div>
        {showTrades && (
          <div className="table-wrap">
            <table className="ledger">
              <thead>
                <tr>
                  <th>날짜</th>
                  <th>내용</th>
                  <th className="qty">수량</th>
                  <th className="num">한 주 가격</th>
                  <th className="num">확정 손익</th>
                </tr>
              </thead>
              <tbody>
                {[...data.fills].reverse().map((f) => (
                  <tr key={`${f.fill_date}-${f.side}`}>
                    <td className="d">{f.fill_date}</td>
                    <td>
                      <span className={`side-tag ${f.side === 'BUY' ? 'rise' : 'fall'}`}>{f.side === 'BUY' ? '샀어요' : '팔았어요'}</span>
                    </td>
                    <td className="qty">{f.qty}주</td>
                    <td className="num">{money(f.price)}</td>
                    <td className={`num ${tone(f.realized_pnl)}`}>
                      {f.realized_pnl != null ? signedMoney(f.realized_pnl) : <span className="faint">—</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <p className="strategy-meta">
          가정: 장 마감 가격으로 판단하고 다음 날 장이 열릴 때 사고팔아요. 토스증권 수수료 0.1%와 조금 불리한 체결 가격을
          반영했어요. 과거 결과가 미래를 보장하지는 않아요.
        </p>
      </section>
    </section>
  )
}

export function BacktestView() {
  const { byName } = useStrategies()
  const { data: list } = useQuery({ queryKey: ['backtests'], queryFn: backtestApi.list, refetchInterval: false })
  const [selected, setSelected] = useState<string | null>(null)
  const current = selected ?? list?.[0]?.id ?? null
  const currentInfo = list?.find((b) => b.id === current)
  // 위쪽 선택(전략·종목)은 아래에 보이는 결과와 맞춘다. 직접 바꾸면 그 선택을 따른다.
  const [picked, setPicked] = useState<Choice | null>(null)
  const choice = picked ?? (currentInfo ? { symbol: currentInfo.symbol, strategy: currentInfo.strategy } : { symbol: 'QQQ', strategy: 'sma_cross' })
  const show = (id: string) => {
    setSelected(id)
    setPicked(null)
  }
  return (
    <div className="home bt">
      <div className="home-main">
        {current ? (
          <Result key={current} id={current} info={currentInfo ? byName[currentInfo.strategy] : undefined} />
        ) : (
          <div className="line-empty">아직 시험한 결과가 없어요. 아래에서 전략과 종목을 골라 시험해 보세요.</div>
        )}
        <RunForm choice={choice} onChoice={setPicked} onDone={show} />
      </div>
      {list && list.length > 0 && (
        <aside className="home-side">
          <div className="bot-list">
            <div className="bot-list-head">지난 시험</div>
            {list.map((b) => (
              <button key={b.id} className={`bt-item ${b.id === current ? 'active' : ''}`} aria-current={b.id === current} onClick={() => show(b.id)}>
                <div>
                  <div className="sym">
                    {byName[b.strategy]?.nickname ?? b.strategy} · {b.symbol}
                  </div>
                  <div className="sub">
                    {b.metrics.start.slice(0, 4)}년부터 · {created.format(new Date(b.created_at))}
                  </div>
                </div>
                <div className="r">
                  <div className={`ret ${tone(b.metrics.cagr)}`}>연 {percent(b.metrics.cagr)}</div>
                  <div className="sub">보유 {percent(b.metrics.benchmark_cagr)}</div>
                </div>
              </button>
            ))}
          </div>
        </aside>
      )}
    </div>
  )
}
