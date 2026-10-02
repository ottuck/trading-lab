import { useQuery } from '@tanstack/react-query'
import {
  CandlestickSeries,
  ColorType,
  createChart,
  createSeriesMarkers,
  HistogramSeries,
  LineSeries,
  type IChartApi,
  type ISeriesApi,
  type SeriesMarker,
  type Time,
} from 'lightweight-charts'
import { useEffect, useMemo, useRef, useState } from 'react'
import { api, type Bar, type Bot } from '../api'
import { sourceLabel } from '../source'
import { cssVar, useTheme } from '../theme'

function sma(bars: Bar[], n: number) {
  const out: { time: Time; value: number }[] = []
  let sum = 0
  bars.forEach((b, i) => {
    sum += Number(b.close)
    if (i >= n) sum -= Number(bars[i - n].close)
    if (i >= n - 1) out.push({ time: b.date as Time, value: sum / n })
  })
  return out
}

type Series = { candles: ISeriesApi<'Candlestick'>; volume: ISeriesApi<'Histogram'>; up: string; down: string }

/** 진행 중인 오늘 봉은 흐리게 그린다 (아직 확정이 아니다). */
function drawLive(s: Series, b: Bar) {
  const rising = Number(b.close) >= Number(b.open)
  const color = `${rising ? s.up : s.down}80`
  const time = b.date as Time
  s.candles.update({
    time,
    open: Number(b.open),
    high: Number(b.high),
    low: Number(b.low),
    close: Number(b.close),
    color,
    wickColor: color,
  })
  s.volume.update({ time, value: Number(b.volume), color: `${rising ? s.up : s.down}25` })
}

const RANGES = [
  { label: '3개월', days: 63 },
  { label: '6개월', days: 126 },
  { label: '1년', days: 252 },
  { label: '3년', days: 750 },
]

export function PriceChart({ bot }: { bot: Bot }) {
  const el = useRef<HTMLDivElement>(null)
  const [days, setDays] = useState(252)
  const { theme } = useTheme()
  const bars = useQuery({ queryKey: ['bars', bot.symbol], queryFn: () => api.bars(bot.symbol) })
  const decisions = useQuery({ queryKey: ['decisions', bot.id], queryFn: () => api.decisions(bot.id) })
  const orders = useQuery({ queryKey: ['orders', bot.id], queryFn: () => api.orders(bot.id) })

  // 확정 봉이 바뀔 때만 차트를 새로 만들고, 오늘 봉(30초마다 바뀜)은 제자리에서 고친다.
  // 그래야 확대·이동해 둔 화면이 갱신 때마다 초기화되지 않는다.
  const completed = useMemo(() => (bars.data ?? []).filter((b) => !b.live), [bars.data])
  const liveBar = bars.data?.find((b) => b.live)
  const completedKey = `${completed.length}:${completed.at(-1)?.date}:${completed.at(-1)?.close}`
  const completedRef = useRef(completed)
  const liveRef = useRef(liveBar)
  const series = useRef<Series | null>(null)
  // 아래 차트 effect보다 먼저 실행되도록 앞에 둔다 (effect는 선언 순서대로 실행된다).
  useEffect(() => {
    completedRef.current = completed
    liveRef.current = liveBar
  })

  useEffect(() => {
    const all = completedRef.current
    if (!el.current || !all.length) return
    // 이동평균은 전체 확정 봉으로 계산하고, 화면에는 선택한 기간만 보여준다.
    const shown = all.slice(-days)
    const from = shown[0].date
    const text = cssVar('--muted')
    const grid = cssVar('--chart-grid')
    const up = cssVar('--rise')
    const down = cssVar('--fall')
    const chart: IChartApi = createChart(el.current, {
      autoSize: true,
      layout: {
        background: { type: ColorType.Solid, color: 'transparent' },
        textColor: text,
        fontFamily: cssVar('--sans'),
      },
      crosshair: { vertLine: { color: cssVar('--chart-cross') }, horzLine: { color: cssVar('--chart-cross') } },
      grid: { vertLines: { color: grid }, horzLines: { color: grid } },
      timeScale: { borderColor: grid },
      rightPriceScale: { borderColor: grid },
    })
    const candles = chart.addSeries(CandlestickSeries, {
      upColor: up,
      downColor: down,
      borderVisible: false,
      wickUpColor: up,
      wickDownColor: down,
    })
    candles.setData(
      shown.map((b) => ({
        time: b.date as Time,
        open: Number(b.open),
        high: Number(b.high),
        low: Number(b.low),
        close: Number(b.close),
      })),
    )
    const volume = chart.addSeries(HistogramSeries, { priceScaleId: 'vol', priceFormat: { type: 'volume' } })
    chart.priceScale('vol').applyOptions({ scaleMargins: { top: 0.85, bottom: 0 } })
    volume.setData(
      shown.map((b) => ({
        time: b.date as Time,
        value: Number(b.volume),
        color: Number(b.close) >= Number(b.open) ? `${up}40` : `${down}40`,
      })),
    )
    if (bot.strategy === 'sma_cross') {
      const colors = [cssVar('--line-fast'), cssVar('--dry')]
      ;[bot.params.fast, bot.params.slow].forEach((n, i) => {
        const line = chart.addSeries(LineSeries, { color: colors[i], lineWidth: 2, priceLineVisible: false })
        line.setData(sma(all, n).filter((p) => String(p.time) >= from))
      })
    }

    // 판단(BUY/SELL 신호)과 모의 체결을 표시한다.
    const markers: SeriesMarker<Time>[] = []
    for (const d of decisions.data ?? []) {
      if (d.action === 'HOLD' || d.session_date < from) continue
      markers.push({
        time: d.session_date as Time,
        position: d.action === 'BUY' ? 'belowBar' : 'aboveBar',
        shape: 'circle',
        color: cssVar('--muted'),
        size: 0.6,
      })
    }
    for (const o of orders.data ?? []) {
      if (o.status !== 'FILLED' || !o.fill_date || o.fill_date < from) continue
      markers.push({
        time: o.fill_date as Time,
        position: o.side === 'BUY' ? 'belowBar' : 'aboveBar',
        shape: o.side === 'BUY' ? 'arrowUp' : 'arrowDown',
        color: o.side === 'BUY' ? up : down,
        text: `${o.side === 'BUY' ? '산' : '판'} ${o.qty}주`,
      })
    }
    markers.sort((a, b) => String(a.time).localeCompare(String(b.time)))
    createSeriesMarkers(candles, markers)
    series.current = { candles, volume, up, down }
    if (liveRef.current) drawLive(series.current, liveRef.current)
    chart.timeScale().fitContent()
    return () => {
      series.current = null
      chart.remove()
    }
  }, [completedKey, liveBar?.date, decisions.data, orders.data, bot.strategy, bot.params, days, theme])

  useEffect(() => {
    if (series.current && liveBar) drawLive(series.current, liveBar)
  }, [liveBar])

  const last = completed.at(-1)
  return (
    <section className="block">
      <div className="block-head">
        <h2>가격 차트</h2>
        <span className="sub">{bot.symbol}</span>
        <div className="ranges" role="group" aria-label="기간" style={{ marginLeft: 'auto' }}>
          {RANGES.map((r) => (
            <button key={r.days} className={r.days === days ? 'active' : ''} aria-pressed={r.days === days} onClick={() => setDays(r.days)}>
              {r.label}
            </button>
          ))}
        </div>
      </div>
      {bot.strategy === 'sma_cross' && (
        <div className="small muted">
          <span style={{ color: 'var(--line-fast)' }}>━ 최근 {bot.params.fast}일 평균</span>{'  '}
          <span style={{ color: 'var(--dry)' }}>━ {bot.params.slow}일 평균</span> · ▲ 산 날 · ▼ 판 날
          {liveBar && ' · 흐린 봉: 오늘 진행 중'}
        </div>
      )}
      <div ref={el} className="chart" />
      <div className="chart-foot">
        마지막 장 마감 {last?.date ?? '—'} · {last ? `$${Number(last.close).toFixed(2)}` : '—'} · 가격 출처{' '}
        {sourceLabel(bot.data_source)}
        {liveBar && (
          <>
            <br />
            오늘({liveBar.date}) 봉은 실시간이에요. 정규장 전 거래부터 채워지고, 장 마감 2시간 뒤 확정돼요.
          </>
        )}
      </div>
    </section>
  )
}
