import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ColorType, createChart, LineSeries, type Time } from 'lightweight-charts'
import { useEffect, useRef, useState } from 'react'
import { backtestApi, type BacktestDetail } from '../api'
import { kstTime, money, percent, signedMoney, tone } from '../format'
import { paramsText, parseParams, STRATEGY_LABEL } from '../strategies'

function cssVar(name: string) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim()
}

function RunForm({ onDone }: { onDone: (id: string) => void }) {
  const qc = useQueryClient()
  const { data: strategies } = useQuery({ queryKey: ['strategies'], queryFn: backtestApi.strategies, refetchInterval: false })
  const [symbol, setSymbol] = useState('QQQ')
  const [strategy, setStrategy] = useState('sma_cross')
  const [params, setParams] = useState('fast=50,slow=200')
  const [start, setStart] = useState('2010-01-04')
  const run = useMutation({
    mutationFn: () =>
      backtestApi.run({ symbol, strategy, params: parseParams(params), start: start || undefined }),
    onSuccess: (d) => {
      void qc.invalidateQueries({ queryKey: ['backtests'] })
      onDone(d.id)
    },
  })
  const pick = (name: string) => {
    setStrategy(name)
    const s = strategies?.find((x) => x.name === name)
    if (s) setParams(paramsText(s.default_params))
  }
  return (
    <form
      className="form"
      onSubmit={(e) => {
        e.preventDefault()
        run.mutate()
      }}
    >
      <label>
        종목
        <input value={symbol} onChange={(e) => setSymbol(e.target.value.toUpperCase())} size={6} />
      </label>
      <label>
        전략
        <select value={strategy} onChange={(e) => pick(e.target.value)}>
          {(strategies ?? []).map((s) => (
            <option key={s.name} value={s.name}>
              {STRATEGY_LABEL[s.name] ?? s.name}
            </option>
          ))}
        </select>
      </label>
      <label>
        파라미터
        <input value={params} onChange={(e) => setParams(e.target.value)} size={24} />
      </label>
      <label>
        첫 판단일
        <input type="date" value={start} onChange={(e) => setStart(e.target.value)} />
      </label>
      <button type="submit" className="primary" disabled={run.isPending}>
        {run.isPending ? '실행 중…' : '백테스트 실행'}
      </button>
      {run.error && <span className="down small">{run.error.message}</span>}
    </form>
  )
}

function EquityChart({ detail }: { detail: BacktestDetail }) {
  const el = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!el.current) return
    const chart = createChart(el.current, {
      autoSize: true,
      layout: { background: { type: ColorType.Solid, color: 'transparent' }, textColor: cssVar('--muted') },
      grid: { vertLines: { color: 'rgba(255,255,255,0.05)' }, horzLines: { color: 'rgba(255,255,255,0.05)' } },
      rightPriceScale: { mode: 1 }, // 로그 스케일: 긴 기간의 낙폭을 비교하기 쉽다
    })
    const strat = chart.addSeries(LineSeries, { color: cssVar('--accent'), lineWidth: 2, title: '전략' })
    const bench = chart.addSeries(LineSeries, { color: cssVar('--muted'), lineWidth: 1, title: '매수 후 보유' })
    strat.setData(detail.equity.map((p) => ({ time: p.session_date as Time, value: Number(p.equity) })))
    bench.setData(detail.equity.map((p) => ({ time: p.session_date as Time, value: Number(p.benchmark) })))
    chart.timeScale().fitContent()
    return () => chart.remove()
  }, [detail])
  return <div ref={el} className="chart" />
}

function Detail({ id }: { id: string }) {
  const { data } = useQuery({ queryKey: ['backtest', id], queryFn: () => backtestApi.get(id), refetchInterval: false })
  if (!data) return <p className="muted">불러오는 중…</p>
  const m = data.metrics
  const rows: [string, string, string, string?][] = [
    ['최종 자산', money(m.final_equity), money(m.benchmark_final_equity)],
    ['총 수익률', percent(m.total_return), percent(m.benchmark_total_return), m.total_return],
    ['연평균 (CAGR)', percent(m.cagr), percent(m.benchmark_cagr), m.cagr],
    ['최대 낙폭', percent(m.max_drawdown), percent(m.benchmark_max_drawdown), m.max_drawdown],
  ]
  return (
    <section className="panel">
      <div className="panel-head">
        <h2>
          {data.symbol} · {STRATEGY_LABEL[data.strategy] ?? data.strategy}{' '}
          <span className="muted small">{paramsText(data.params)}</span>
        </h2>
        <span className="muted small">
          {m.start} ~ {m.end} · 수수료 {Number(data.commission_rate) * 100}% · 슬리피지 {data.slippage_bps}bp · T 종가 판단
          → T+1 시가 체결
        </span>
      </div>
      <div className="bt-summary">
        <table className="compact">
          <thead>
            <tr>
              <th />
              <th className="num">전략</th>
              <th className="num">매수 후 보유</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(([label, a, b, t]) => (
              <tr key={label}>
                <td>{label}</td>
                <td className={`num ${tone(t)}`}>{a}</td>
                <td className="num">{b}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <div>
          <div className="muted small">보유 비중 {percent(m.exposure).replace('+', '')}</div>
          <div className="muted small">
            왕복 거래 {m.round_trips}회 · 승률 {m.win_rate == null ? '—' : percent(m.win_rate).replace('+', '')}
          </div>
          <div className="muted small">데이터 {data.data_start} ~ {data.data_end} (warmup 포함)</div>
        </div>
      </div>
      <EquityChart detail={data} />
      <h3>체결 ({data.fills.length}건, 최근 순)</h3>
      <table>
        <thead>
          <tr>
            <th>판단일</th>
            <th>체결일</th>
            <th>구분</th>
            <th className="num">수량</th>
            <th className="num">가격</th>
            <th className="num">실현 손익</th>
          </tr>
        </thead>
        <tbody>
          {[...data.fills].reverse().slice(0, 50).map((f) => (
            <tr key={`${f.fill_date}-${f.side}`}>
              <td>{f.signal_date}</td>
              <td>{f.fill_date}</td>
              <td className={f.side === 'BUY' ? 'up' : 'down'}>{f.side === 'BUY' ? '매수' : '매도'}</td>
              <td className="num">{f.qty}</td>
              <td className="num">{money(f.price)}</td>
              <td className={`num ${tone(f.realized_pnl)}`}>{signedMoney(f.realized_pnl)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  )
}

export function BacktestView() {
  const { data: list } = useQuery({ queryKey: ['backtests'], queryFn: backtestApi.list, refetchInterval: false })
  const [selected, setSelected] = useState<string | null>(null)
  const current = selected ?? list?.[0]?.id ?? null
  return (
    <>
      <section className="panel">
        <h2>백테스트</h2>
        <p className="muted small">
          DB에 저장된 일봉(수정주가)으로 실행합니다. 같은 판단·체결 함수를 정기 DRY RUN도 그대로 씁니다.
        </p>
        <RunForm onDone={setSelected} />
        {list && list.length > 0 && (
          <table>
            <thead>
              <tr>
                <th>실행 시각</th>
                <th>종목</th>
                <th>전략</th>
                <th>기간</th>
                <th className="num">CAGR</th>
                <th className="num">최대 낙폭</th>
                <th className="num">보유 시 CAGR</th>
              </tr>
            </thead>
            <tbody>
              {list.map((b) => (
                <tr key={b.id} className={b.id === current ? 'selected' : 'clickable'} onClick={() => setSelected(b.id)}>
                  <td className="nowrap">{kstTime(b.created_at)}</td>
                  <td>{b.symbol}</td>
                  <td>
                    {b.strategy} <span className="muted small">{paramsText(b.params)}</span>
                  </td>
                  <td className="nowrap">
                    {b.metrics.start.slice(0, 4)}~{b.metrics.end.slice(0, 4)}
                  </td>
                  <td className={`num ${tone(b.metrics.cagr)}`}>{percent(b.metrics.cagr)}</td>
                  <td className="num">{percent(b.metrics.max_drawdown)}</td>
                  <td className="num">{percent(b.metrics.benchmark_cagr)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
      {current && <Detail id={current} />}
    </>
  )
}
