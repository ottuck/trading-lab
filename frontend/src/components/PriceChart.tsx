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

function cssVar(name: string) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim()
}

const RANGES = [
  { label: '60일', days: 60 },
  { label: '120일', days: 120 },
  { label: '250일', days: 250 },
  { label: '3년', days: 750 },
]

export function PriceChart({ bot }: { bot: Bot }) {
  const el = useRef<HTMLDivElement>(null)
  const [days, setDays] = useState(250)
  const bars = useQuery({ queryKey: ['bars', bot.symbol], queryFn: () => api.bars(bot.symbol) })
  const decisions = useQuery({ queryKey: ['decisions', bot.id], queryFn: () => api.decisions(bot.id) })
  const orders = useQuery({ queryKey: ['orders', bot.id], queryFn: () => api.orders(bot.id) })

  useEffect(() => {
    if (!el.current || !bars.data?.length) return
    // 이동평균은 전체 봉으로 계산하고, 화면에는 선택한 기간만 보여준다.
    const shown = bars.data.slice(-days)
    const from = shown[0].date
    const text = cssVar('--muted')
    const grid = 'rgba(255,255,255,0.05)'
    const up = cssVar('--ok')
    const down = cssVar('--bad')
    const chart = createChart(el.current, {
      autoSize: true,
      layout: {
        background: { type: ColorType.Solid, color: 'transparent' },
        textColor: text,
        fontFamily: 'Pretendard Variable, system-ui, sans-serif',
      },
      crosshair: { vertLine: { color: '#4ea1ff55' }, horzLine: { color: '#4ea1ff55' } },
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
        text: `${o.side} ${o.qty}주`,
      })
    }
    markers.sort((a, b) => String(a.time).localeCompare(String(b.time)))
    createSeriesMarkers(candles, markers)
    chart.timeScale().fitContent()
    return () => chart.remove()
  }, [bars.data, decisions.data, orders.data, bot.strategy, bot.params, days])

  const last = bars.data?.at(-1)
  return (
    <section className="card">
      <div className="panel-head">
        <div className="card-title">
          일봉 차트 <span className="sub">{bot.symbol}</span>
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
          <span style={{ color: 'var(--accent)' }}>━ SMA{bot.params.fast}</span>{'  '}
          <span style={{ color: 'var(--dry)' }}>━ SMA{bot.params.slow}</span> · ● 신호 · ▲▼ 모의 체결
        </div>
      )}
      <div ref={el} className="chart" />
      <div className="chart-foot">
        {bot.symbol} — {Math.min(days, bars.data?.length ?? 0)}봉, 최근 {last?.date ?? '—'} 종가{' '}
        {last ? `${Number(last.close).toFixed(2)}` : '—'} · 출처 {sourceLabel(bot.data_source)} · 정규장 마감 2시간 뒤 완료 봉
      </div>
    </section>
  )
}
