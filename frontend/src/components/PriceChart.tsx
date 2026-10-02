import { useQuery } from '@tanstack/react-query'
import {
  CandlestickSeries,
  ColorType,
  createChart,
  createSeriesMarkers,
  HistogramSeries,
  LineSeries,
  type SeriesMarker,
  type Time,
} from 'lightweight-charts'
import { useEffect, useRef, useState } from 'react'
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

  useEffect(() => {
    if (!el.current || !bars.data?.length) return
    // 이동평균은 전체 봉으로 계산하고, 화면에는 선택한 기간만 보여준다.
    const shown = bars.data.slice(-days)
    const from = shown[0].date
    const text = cssVar('--muted')
    const grid = cssVar('--chart-grid')
    const up = cssVar('--ok')
    const down = cssVar('--bad')
    const chart = createChart(el.current, {
      autoSize: true,
      layout: {
        background: { type: ColorType.Solid, color: 'transparent' },
        textColor: text,
        fontFamily: 'Pretendard Variable, system-ui, sans-serif',
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
      const colors = [cssVar('--accent'), cssVar('--dry')]
      ;[bot.params.fast, bot.params.slow].forEach((n, i) => {
        const line = chart.addSeries(LineSeries, { color: colors[i], lineWidth: 2, priceLineVisible: false })
        line.setData(sma(bars.data, n).filter((p) => String(p.time) >= from))
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
        text: `${o.side === 'BUY' ? '삼' : '팜'} ${o.qty}주`,
      })
    }
    markers.sort((a, b) => String(a.time).localeCompare(String(b.time)))
    createSeriesMarkers(candles, markers)
    chart.timeScale().fitContent()
    return () => chart.remove()
  }, [bars.data, decisions.data, orders.data, bot.strategy, bot.params, days, theme])

  const last = bars.data?.at(-1)
  return (
    <section className="card">
      <div className="panel-head">
        <div className="card-title">
          가격 차트 <span className="sub">{bot.symbol}</span>
        </div>
        <div className="controls">
          {RANGES.map((r) => (
            <button key={r.days} className={`seg ${r.days === days ? 'active' : ''}`} onClick={() => setDays(r.days)}>
              {r.label}
            </button>
          ))}
        </div>
      </div>
      {bot.strategy === 'sma_cross' && (
        <div className="small muted" style={{ marginTop: 8 }}>
          <span style={{ color: 'var(--accent)' }}>━ 최근 {bot.params.fast}일 평균</span>{'  '}
          <span style={{ color: 'var(--dry)' }}>━ {bot.params.slow}일 평균</span> · ▲ 산 날 · ▼ 판 날
        </div>
      )}
      <div ref={el} className="chart" />
      <div className="chart-foot">
        마지막 장 마감 {last?.date ?? '—'} · {last ? `$${Number(last.close).toFixed(2)}` : '—'} · 가격 출처{' '}
        {sourceLabel(bot.data_source)}
      </div>
    </section>
  )
}
