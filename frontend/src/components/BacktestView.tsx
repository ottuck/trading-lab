import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ColorType, createChart, LineSeries, type Time } from 'lightweight-charts'
import { useEffect, useRef, useState } from 'react'
import { api, backtestApi, botApi, type BacktestDetail, type BacktestSummary, type StrategyInfo, type SymbolWeight } from '../api'
import { useCurrency } from '../currency'
import { money, percent, roundMoney, setAmount, shares, signedMoney, tone } from '../format'
import { isAiBot, isMeBot, useStrategies } from '../strategies'
import { useDemo, usePriceWord } from '../demo'
import { cssVar, useTheme } from '../theme'
import { FxNote } from './Currency'
import { Term } from './Help'
import { goTo, openBot, selectBot, startMeEdit, startNewBot } from '../selectedBot'
import { toConfig, toDraft } from '../botConfig'
import { ParallelWorlds } from './Parallel'
import { PresetFields } from './PresetFields'
import { StrategyGlyph } from './StrategyGlyph'
import { activeOf, basketLabel } from '../basket'
import { BasketPicker } from './SymbolPicker'

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

const STRATEGY = 'dip_saver' // 시험해 보기는 나 카피 봇(나처럼 투자) 규칙만 한다
const DEFAULT_BASKET: SymbolWeight[] = [
  { symbol: 'QQQ', weight: 50 },
  { symbol: 'VOO', weight: 50 },
]

/** 나 카피 봇 소개 카드와, AI 봇은 과거로 시험하지 않는다는 안내. */
function Intro({ info, aiBotId }: { info?: StrategyInfo; aiBotId?: number }) {
  return (
    <div className="bt-modes">
      {info && (
        <div className="bt-main">
          <span className="bt-main-text">
            <span className="eyebrow">나 카피 봇</span>
            <span className="title">{info.nickname}</span>
            <span className="desc">{info.summary}</span>
          </span>
          <StrategyGlyph name={info.name} className="bt-main-glyph" />
        </div>
      )}
      {/* AI는 지난 일의 결과를 이미 알고 있어 과거 시험이 부풀려진다 (project.md 14절) */}
      <p className="bt-ai-note">
        AI 봇은 과거로 시험하지 않아요. AI가 지난 일의 결과를 이미 알고 있어서 실제보다 좋게 나오거든요. 대신 오늘부터 모의 투자하며 나 카피 봇과
        같은 돈으로 나란히 비교해요.
        {aiBotId != null && (
          <>
            {' '}
            <button className="link" onClick={() => openBot(aiBotId)}>
              AI 봇 비교 보기 →
            </button>
          </>
        )}
      </p>
    </div>
  )
}

/** 결과를 만들 때 고른 기간(3·5·10년)을 되찾는다. 어느 것에도 가깝지 않으면 "가능한 처음부터". */
function periodOf(s: BacktestSummary): number {
  const days = (new Date(s.created_at).getTime() - new Date(s.metrics.start).getTime()) / 86_400_000
  const hit = PERIODS.find((p) => p.years && Math.abs(days / 365.25 - p.years) < 0.1)
  return hit?.years ?? 0
}

function RunForm({
  basket,
  seed,
  onBasket,
  onDone,
}: {
  basket: SymbolWeight[]
  seed?: BacktestSummary
  onBasket: (v: SymbolWeight[]) => void
  onDone: (id: string) => void
}) {
  const qc = useQueryClient()
  const { byName } = useStrategies()
  const { data: bots } = useQuery({ queryKey: ['bots'], queryFn: api.bots })
  const meBot = bots?.find(isMeBot)
  const aiBot = bots?.find(isAiBot)
  // 나 카피 봇이 있으면 질문은 그 봇의 규칙 바꾸기다 (데모의 예시 봇은 바꿀 수 없어 새로 해 본다)
  const editMe = useDemo() ? undefined : meBot
  const priceWord = usePriceWord()
  const info = byName[STRATEGY]
  // 고른 규칙을 기억한다. 고르지 않았으면 기본값. 아래에 보이는 결과(seed)가 있으면 그 규칙·기간으로 시작한다.
  const [picked, setPicked] = useState<Record<string, number> | null>(() => seed?.params ?? null)
  const [years, setYears] = useState(() => (seed ? periodOf(seed) : 10))
  const params = picked ?? info?.default_params ?? {}
  const total = basket.reduce((sum, b) => sum + b.weight, 0)
  const run = useMutation({
    // 시작 금액은 보내지 않는다 (서버가 첫 달 입금액으로 시작한다).
    mutationFn: () =>
      backtestApi.run({
        symbol: basket[0].symbol,
        symbols: basket,
        strategy: STRATEGY,
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
        <span className="sub">예전부터 그렇게 했다면 어땠을지 {priceWord}으로 계산해요</span>
      </div>
      <div className="stack">
        <Intro info={info} aiBotId={aiBot?.id} />
        <div className="bt-mine">
          <div className="bt-mine-text">
            <b>{editMe ? '내 규칙을 바꾸려면, 다시 카피하기' : '내 규칙을 모르겠다면, 나 카피하기'}</b>
            <span className="muted small">
              {editMe
                ? `질문 몇 개에 다시 답하면 ${editMe.name}의 규칙이 바뀌어요. 바꾸기 전에 지난 10년을 먼저 보여줘요.`
                : '질문 몇 개에 답하면 내 투자 습관이 규칙이 되고 지난 10년을 바로 보여줘요. 1분이면 끝나요.'}
            </span>
          </div>
          <div className="bt-mine-actions">
            <button className="accent" onClick={() => (editMe ? startMeEdit(editMe.id) : goTo('me'))}>
              {editMe ? '다시 카피하기 →' : '질문으로 내 규칙 정하기 →'}
            </button>
            {meBot && (
              <button
                onClick={() => {
                  setPicked(meBot.params)
                  onBasket(activeOf(meBot.symbols))
                }}
              >
                {meBot.name} 설정 불러오기
              </button>
            )}
          </div>
        </div>
        {info && <PresetFields info={info} params={params} onChange={setPicked} />}
        <BasketPicker value={basket} onChange={onBasket} />
        <div className="controls">
          <span className="label">기간</span>
          {PERIODS.map((p) => (
            <button key={p.years} className={`seg ${p.years === years ? 'active' : ''}`} onClick={() => setYears(p.years)}>
              {p.label}
            </button>
          ))}
        </div>
        <div className="controls">
          <button className="primary" disabled={run.isPending || !info || total !== 100} onClick={() => run.mutate()}>
            {run.isPending ? '계산 중…' : `매달 ${setAmount(Number(params.deposit ?? 0))}씩 시험해 보기`}
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
  const { currency, rate } = useCurrency()
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
      localization: { priceFormatter: roundMoney },
    })
    const strat = chart.addSeries(LineSeries, { color: cssVar('--text'), lineWidth: 2, priceLineVisible: false })
    const bench = chart.addSeries(LineSeries, { color: cssVar('--faint'), lineWidth: 1, priceLineVisible: false })
    strat.setData(detail.equity.map((p) => ({ time: p.session_date as Time, value: Number(p.equity) })))
    bench.setData(detail.equity.map((p) => ({ time: p.session_date as Time, value: Number(p.benchmark) })))
    chart.timeScale().fitContent()
    return () => chart.remove()
  }, [detail, theme, currency, rate])
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
  const demo = useDemo()
  const { data } = useQuery({ queryKey: ['backtest', id], queryFn: () => backtestApi.get(id), refetchInterval: false })
  const [showTrades, setShowTrades] = useState(false)
  const qc = useQueryClient()
  const { data: bots } = useQuery({ queryKey: ['bots'], queryFn: api.bots })
  // 나 카피 봇은 하나만 만들 수 있다: 이미 있으면 새로 만들지 않고 이 시험의 규칙·종목을 그 봇에 적용한다.
  const meBot = demo ? undefined : bots?.find(isMeBot)
  const applyToMe = async (params: Record<string, number>) => {
    if (!meBot || !data) return
    const next = activeOf(data.symbols ?? [{ symbol: data.symbol, weight: 100 }])
    try {
      await botApi.updateConfig(meBot.id, { ...toConfig(toDraft(meBot), meBot), params })
      if (JSON.stringify(activeOf(meBot.symbols)) !== JSON.stringify(next)) await botApi.updateSymbols(meBot.id, next)
      await qc.invalidateQueries({ queryKey: ['bots'] })
      selectBot(meBot.id)
      goTo('dashboard')
    } catch (e) {
      window.alert(`바꾸지 못했어요: ${e instanceof Error ? e.message : e}`)
    }
  }
  if (!data) return <div className="line-empty">불러오는 중…</div>
  const m = data.metrics
  const abs = (v: string | null | undefined) => percent(v).replace('+', '')
  const paid = m.contributed ?? m.initial_cash
  const gain = String(Number(m.final_equity) - Number(paid))
  const bench = '매달 그냥 사기' // 넣을 때마다 바로 사는 것이 비교 기준이다
  return (
    <section className="bt-result">
      <div className="hero-head">
        <div>
          <div className="bot-line">
            <span className="name">{info?.nickname ?? data.strategy}</span>
            <span>
              · {basketLabel(data.symbols, data.symbol)} · {ym(m.start)}부터 매달 {setAmount(Number(data.params.deposit ?? 0))}씩 넣었다면 (모두{' '}
              {money(paid)})
            </span>
          </div>
          <div className="hero-value">{money(m.final_equity)}</div>
          <div className="hero-delta">
            <span className={tone(m.total_return)}>
              {signedMoney(gain)} ({percent(m.total_return)})
            </span>
            <span className="when">해마다 평균 {percent(m.cagr)}</span>
          </div>
          <FxNote />
        </div>
        {!demo && (
          <div className="hero-actions">
            {meBot ? (
              <button
                className="primary"
                onClick={() =>
                  window.confirm(
                    `${meBot.name}의 규칙과 종목을 이 시험의 값으로 바꿀까요?
나 카피 봇은 하나만 만들 수 있어서 새로 만들지 않고 이 봇을 바꿔요. 다음 판단부터 적용되고 지금까지의 기록은 그대로예요.`,
                  ) && void applyToMe(data.params)
                }
              >
                이 규칙을 {meBot.name}에 적용
              </button>
            ) : (
              <button
                className="primary"
                onClick={() =>
                  startNewBot({ symbol: data.symbol, symbols: data.symbols ?? undefined, strategy: data.strategy, params: data.params })
                }
              >
                이 규칙으로 모의 투자 시작
              </button>
            )}
          </div>
        )}
      </div>
      {/* 나처럼 투자는 판정하지 않는다 (평가가 아니라 구경, project.md 1절) */}
      <EquityChart detail={data} />
      <div className="eq-foot">
        <span className="legend">
          <i className="strat" />이 규칙
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
          b={`${data.fills.length}번 샀어요 · 팔지 않아요`}
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
                  <th className="num">이 규칙</th>
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
                </tr>
              </thead>
              <tbody>
                {[...data.fills].reverse().map((f) => (
                  <tr key={`${f.fill_date}-${f.side}`}>
                    <td className="d">{f.fill_date}</td>
                    <td>
                      <span className="side-tag rise">샀어요</span>
                    </td>
                    <td className="qty">{shares(f.qty)}주</td>
                    <td className="num">{money(f.price)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <p className="strategy-meta">
          가정: 장 마감 가격으로 판단하고 다음 날 장이 열릴 때 사요. 토스증권 수수료 0.1%와 조금 불리한 체결 가격을
          반영했어요. 과거 결과가 미래를 보장하지는 않아요.
        </p>
      </section>
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
        chooseLabel={meBot ? '로 바꾸기' : '로 모의 투자 시작'}
        confirm={meBot ? `${meBot.name}의 규칙과 종목을 바꿀까요? 다음 판단부터 적용되고 지금까지의 기록은 그대로예요.` : undefined}
        onChoose={
          demo
            ? undefined
            : meBot
              ? applyToMe
              : (params) => startNewBot({ symbol: data.symbol, symbols: data.symbols ?? undefined, strategy: data.strategy, params })
        }
      />
    </section>
  )
}

export function BacktestView() {
  const { byName } = useStrategies()
  const { data: list } = useQuery({ queryKey: ['backtests'], queryFn: backtestApi.list, refetchInterval: false })
  const [selected, setSelected] = useState<string | null>(null)
  const current = selected ?? list?.[0]?.id ?? null
  const currentInfo = list?.find((b) => b.id === current)
  // 양식의 선택(종목)은 아래에 보이는 결과와 맞춘다. 직접 바꾸면 그 선택을 따른다.
  const [picked, setPicked] = useState<SymbolWeight[] | null>(null)
  const basket = picked ?? (currentInfo ? activeOf(currentInfo.symbols ?? [{ symbol: currentInfo.symbol, weight: 100 }]) : DEFAULT_BASKET)
  const show = (id: string) => {
    setSelected(id)
    setPicked(null)
  }
  return (
    <div className="home bt">
      <div className="home-main">
        {/* 양식은 보이는 결과에 맞춘다. 방금 시험한 결과는 목록에 늦게 들어오므로 들어온 뒤 한 번 더 맞춘다. */}
        <RunForm key={`${current}:${currentInfo ? 1 : 0}`} basket={basket} seed={currentInfo} onBasket={setPicked} onDone={show} />
        {current ? (
          <Result key={current} id={current} info={byName[STRATEGY]} />
        ) : (
          <div className="bt-result line-empty">아직 시험한 결과가 없어요. 위에서 규칙과 종목을 골라 시험해 보세요.</div>
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
                    {byName[STRATEGY]?.nickname ?? STRATEGY} · {b.symbols?.map((x) => x.symbol).join('·') ?? b.symbol}
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
