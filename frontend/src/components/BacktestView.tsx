import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ColorType, createChart, LineSeries, type Time } from 'lightweight-charts'
import { useEffect, useRef, useState } from 'react'
import { api, backtestApi, type BacktestDetail, type StrategyInfo, type SymbolWeight } from '../api'
import { money, percent, shares, signedMoney, tone } from '../format'
import { isMeBot, useStrategies } from '../strategies'
import { cssVar, useTheme } from '../theme'
import { Term } from './Help'
import { goTo, startNewBot } from '../selectedBot'
import { ParallelWorlds } from './Parallel'
import { PresetFields } from './PresetFields'
import { StrategyGlyph } from './StrategyGlyph'
import { activeOf, basketLabel } from '../basket'
import { BasketPicker, SymbolPicker } from './SymbolPicker'

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

type Choice = { symbol: string; strategy: string; symbols?: SymbolWeight[] | null }

/** 나처럼 투자가 주력, 유명 전략들은 아래 참고용 작은 목록. */
function StrategyModes({ list, value, onChange }: { list: StrategyInfo[]; value: string; onChange: (name: string) => void }) {
  const me = list.find((s) => s.accumulates)
  const refs = list.filter((s) => !s.accumulates)
  const ref = refs.find((s) => s.name === value)
  return (
    <div className="bt-modes">
      {me && (
        <button className={`bt-main ${value === me.name ? 'active' : ''}`} aria-pressed={value === me.name} onClick={() => onChange(me.name)}>
          <span className="bt-main-text">
            <span className="eyebrow">나 카피 봇</span>
            <span className="title">{me.nickname}</span>
            <span className="desc">{me.summary}</span>
          </span>
          <StrategyGlyph name={me.name} className="bt-main-glyph" />
        </button>
      )}
      <div className="bt-refs">
        <span className="label">유명 전략 참고</span>
        {/* 그림과 설명이 위, 고르는 버튼이 아래. 아직 안 골랐어도 자리를 잡아 두어 버튼이 움직이지 않게 한다. */}
        <div className={`bt-ref-desc ${ref ? '' : 'empty'}`}>
          {ref ? (
            <>
              <StrategyGlyph name={ref.name} />
              <div>
                <div className="title">{ref.nickname}</div>
                <p>
                  {ref.summary} <span className="faint">위험 {ref.risk} · 거래 {ref.trades}</span>
                </p>
              </div>
            </>
          ) : (
            <p>유명한 투자법을 고르면 언제 사고파는지 그림으로 보여드려요. 나처럼 투자와 비교해 볼 때 써요.</p>
          )}
        </div>
        <div className="bt-ref-list">
          {refs.map((s) => (
            <button key={s.name} className={`seg ${s.name === value ? 'active' : ''}`} aria-pressed={s.name === value} onClick={() => onChange(s.name)}>
              {s.nickname}
            </button>
          ))}
        </div>
      </div>
    </div>
  )
}

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
  const { list, byName } = useStrategies()
  const { data: bots } = useQuery({ queryKey: ['bots'], queryFn: api.bots })
  const meBot = bots?.find(isMeBot)
  // 전략마다 고른 프리셋 값을 기억한다. 고르지 않았으면 기본값.
  const [picked, setPicked] = useState<Record<string, Record<string, number>>>({})
  const { symbol, strategy } = choice
  const setSymbol = (s: string) => onChoice({ ...choice, symbol: s, symbols: null })
  // 모으기 전략은 여러 종목(최대 10개)을 비율대로 시험한다.
  const basket = choice.symbols?.length ? choice.symbols : [{ symbol, weight: 100 }]
  const setBasket = (v: SymbolWeight[]) => onChoice({ ...choice, symbol: v[0].symbol, symbols: v })
  const setStrategy = (s: string) => onChoice({ ...choice, strategy: s })
  const [years, setYears] = useState(10)
  const info = byName[strategy]
  const params = picked[strategy] ?? info?.default_params ?? {}
  const multi = !!info?.accumulates && basket.length > 1
  const total = basket.reduce((sum, b) => sum + b.weight, 0)
  const run = useMutation({
    // 모으기 전략은 시작 금액을 보내지 않는다 (서버가 첫 달 입금액으로 시작한다).
    mutationFn: () =>
      backtestApi.run({
        symbol: multi ? basket[0].symbol : symbol,
        symbols: multi ? basket : undefined,
        strategy,
        params,
        start: startDate(years),
      }),
    onSuccess: (d) => {
      void qc.invalidateQueries({ queryKey: ['backtests'] })
      onDone(d.id)
    },
  })
  return (
    <section className="bt-form">
      <div className="block-head">
        <h2>과거로 시험해 보기</h2>
        <span className="sub">예전부터 그렇게 했다면 어땠을지 실제 가격으로 계산해요</span>
      </div>
      <div className="stack">
        <StrategyModes list={list} value={strategy} onChange={setStrategy} />
        {info?.accumulates && (
          <div className="bt-mine">
            {meBot && (
              <button
                onClick={() => {
                  setPicked({ ...picked, [strategy]: meBot.params })
                  setBasket(activeOf(meBot.symbols))
                }}
              >
                {meBot.name} 규칙 불러오기
              </button>
            )}
            <button className="link" onClick={() => goTo('me')}>
              질문으로 내 규칙 정하기 (나 카피하기)
            </button>
          </div>
        )}
        {info && <PresetFields info={info} params={params} onChange={(p) => setPicked({ ...picked, [strategy]: p })} />}
        {info?.accumulates ? (
          <BasketPicker value={basket} onChange={setBasket} />
        ) : (
          <SymbolPicker label="종목" value={symbol} onChange={setSymbol} />
        )}
        <div className="controls">
          <span className="label">기간</span>
          {PERIODS.map((p) => (
            <button key={p.years} className={`seg ${p.years === years ? 'active' : ''}`} onClick={() => setYears(p.years)}>
              {p.label}
            </button>
          ))}
        </div>
        <div className="controls">
          <button className="primary" disabled={run.isPending || !list.length || (multi && total !== 100)} onClick={() => run.mutate()}>
            {run.isPending
              ? '계산 중…'
              : info?.accumulates
                ? `매달 $${params.deposit?.toLocaleString('en-US')}씩 시험해 보기`
                : '$10,000로 시험해 보기'}
          </button>
          {run.error && <span className="bad small">{run.error.message}</span>}
        </div>
      </div>
    </section>
  )
}

export function EquityChart({ detail }: { detail: BacktestDetail }) {
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
      // 10년 일봉(약 2,500개)이 좁은 화면에도 다 들어오게 막대 간격 하한을 낮춘다 (기본 0.5px).
      timeScale: { borderVisible: false, minBarSpacing: 0.01 },
      rightPriceScale: { mode: 1, borderVisible: false }, // 로그 눈금: 긴 기간의 오르내림을 비교하기 쉽다
      localization: { priceFormatter: (v: number) => `$${Math.round(v).toLocaleString('en-US')}` },
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
  const paid = m.contributed ?? m.initial_cash
  const monthly = (m.deposits ?? 0) > 0
  const gain = String(Number(m.final_equity) - Number(paid))
  // 입금이 있으면 비교 기준은 "넣을 때마다 바로 사기"다.
  const bench = monthly ? '매달 그냥 사기' : '그냥 보유'
  return (
    <section className="bt-result">
      <div className="hero-head">
        <div>
          <div className="bot-line">
            <span className="name">{info?.nickname ?? data.strategy}</span>
            <span>
              · {basketLabel(data.symbols, data.symbol)} ·{' '}
              {monthly
                ? `${ym(m.start)}부터 매달 $${data.params.deposit?.toLocaleString('en-US')}씩 넣었다면 (모두 ${money(paid)})`
                : `${ym(m.start)}부터 ${money(m.initial_cash)}로 시작했다면`}
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
          <button className="primary" onClick={() => startNewBot({ symbol: data.symbol, symbols: data.symbols ?? undefined, strategy: data.strategy, params: data.params })}>
            이 전략으로 모의 투자 시작
          </button>
        </div>
      </div>
      <p className="bt-verdict">
        <span className={`mark ${won ? 'rise' : 'fall'}`} />
        <span>
          {monthly
            ? won
              ? '매달 그냥 산 것보다 결과가 좋았어요.'
              : '매달 그냥 산 게 더 많이 벌었어요.'
            : won
              ? '그냥 들고 있는 것보다 결과가 좋았어요.'
              : '그냥 들고 있는 게 더 많이 벌었어요.'}{' '}
          {smallerDrop &&
            `${won ? '게다가' : '대신'} 가장 크게 떨어진 폭은 ${abs(m.max_drawdown)}로, ${bench}(${abs(m.benchmark_max_drawdown)})보다 작았어요.`}
        </span>
      </p>

      <EquityChart detail={data} />
      <div className="eq-foot">
        <span className="legend">
          <i className="strat" />이 전략
        </span>
        <span className="legend">
          <i className="bench" />
          <Term k="그냥 들고 있었다면">{bench}</Term> {money(m.benchmark_final_equity)} ({percent(m.benchmark_total_return)})
        </span>
        <span className="paper">눈금은 비율 기준</span>
      </div>

      <div className="facts bt-facts">
        <Fact term="연평균 수익률" a={percent(m.cagr)} b={`${bench} ${percent(m.benchmark_cagr)}`} t={m.cagr} />
        <Fact term="가장 크게 떨어진 폭" a={abs(m.max_drawdown)} b={`${bench} ${abs(m.benchmark_max_drawdown)}`} />
        {m.volatility !== undefined && (
          <Fact term="가격 출렁임" a={abs(m.volatility)} b={`${bench} ${abs(m.benchmark_volatility)}`} />
        )}
        {m.sharpe !== undefined && (
          <Fact
            term="위험 대비 수익 점수"
            a={m.sharpe == null ? '—' : Number(m.sharpe).toFixed(2)}
            b={`${bench} ${m.benchmark_sharpe == null ? '—' : Number(m.benchmark_sharpe).toFixed(2)}`}
          />
        )}
        <Fact
          term="투자 중이던 기간"
          a={abs(m.exposure)}
          b={
            monthly ? (
              `${data.fills.length}번 샀어요 · 팔지 않아요`
            ) : (
              <>
                거래 {m.round_trips}번 · <Term k="이긴 거래 비율">이긴 비율</Term> {m.win_rate == null ? '—' : abs(m.win_rate)}
              </>
            )
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
                  <th className="num">{bench}</th>
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
                    <td className="qty">{shares(f.qty)}주</td>
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
      {data.strategy === 'dip_saver' && (
        <ParallelWorlds
          queryKey={['parallel', data.id]}
          fetch={() =>
            backtestApi.parallel({
              symbol: data.symbol,
              symbols: data.symbols ?? undefined,
              params: data.params,
              start: m.start,
              initial_cash: m.initial_cash,
            })
          }
          sub={() => `${ym(m.start)}부터, 규칙을 하나씩 바꿨다면`}
          chooseLabel="로 모의 투자 시작"
          onChoose={(params) => startNewBot({ symbol: data.symbol, symbols: data.symbols ?? undefined, strategy: data.strategy, params })}
        />
      )}
    </section>
  )
}

export function BacktestView() {
  const { byName } = useStrategies()
  const { data: list } = useQuery({ queryKey: ['backtests'], queryFn: backtestApi.list, refetchInterval: false })
  const [selected, setSelected] = useState<string | null>(null)
  const current = selected ?? list?.[0]?.id ?? null
  const currentInfo = list?.find((b) => b.id === current)
  // 양식의 선택(전략·종목)은 아래에 보이는 결과와 맞춘다. 직접 바꾸면 그 선택을 따른다.
  const [picked, setPicked] = useState<Choice | null>(null)
  const choice = picked ?? (currentInfo ? { symbol: currentInfo.symbol, strategy: currentInfo.strategy, symbols: activeOf(currentInfo.symbols ?? []) } : { symbol: 'QQQ', strategy: 'dip_saver', symbols: [{ symbol: 'QQQ', weight: 50 }, { symbol: 'VOO', weight: 50 }] })
  const show = (id: string) => {
    setSelected(id)
    setPicked(null)
  }
  return (
    <div className="home bt">
      <div className="home-main">
        <RunForm choice={choice} onChoice={setPicked} onDone={show} />
        {current ? (
          <Result key={current} id={current} info={currentInfo ? byName[currentInfo.strategy] : undefined} />
        ) : (
          <div className="bt-result line-empty">아직 시험한 결과가 없어요. 위에서 전략과 종목을 골라 시험해 보세요.</div>
        )}
      </div>
      {list && list.length > 0 && (
        <aside className="home-side">
          <div className="bot-list">
            <div className="bot-list-head">지난 시험</div>
            {list.map((b) => (
              <button key={b.id} className={`bt-item ${b.id === current ? 'active' : ''}`} aria-current={b.id === current} onClick={() => show(b.id)}>
                <div>
                  <div className="sym">
                    {byName[b.strategy]?.nickname ?? b.strategy} · {b.symbols?.map((x) => x.symbol).join('·') ?? b.symbol}
                  </div>
                  <div className="sub">
                    {b.metrics.start.slice(0, 4)}년부터 · {created.format(new Date(b.created_at))}
                  </div>
                </div>
                <div className="r">
                  <div className={`ret ${tone(b.metrics.cagr)}`}>연 {percent(b.metrics.cagr)}</div>
                  <div className="sub">
                    {(b.metrics.deposits ?? 0) > 0 ? '매달 그냥' : '보유'} {percent(b.metrics.benchmark_cagr)}
                  </div>
                </div>
              </button>
            ))}
          </div>
        </aside>
      )}
    </div>
  )
}
