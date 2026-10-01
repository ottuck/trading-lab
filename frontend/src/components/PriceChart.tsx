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
import { useEffect, useRef } from 'react'
import { api, type Bar, type Bot } from '../api'

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

export function PriceChart({ bot }: { bot: Bot }) {
  const el = useRef<HTMLDivElement>(null)
  const bars = useQuery({ queryKey: ['bars', bot.symbol], queryFn: () => api.bars(bot.symbol) })
  const decisions = useQuery({ queryKey: ['decisions', bot.id], queryFn: () => api.decisions(bot.id) })
  const orders = useQuery({ queryKey: ['orders', bot.id], queryFn: () => api.orders(bot.id) })

  useEffect(() => {
    if (!el.current || !bars.data?.length) return
    const text = cssVar('--muted')
    const grid = cssVar('--border')
    const up = cssVar('--ok')
    const down = cssVar('--bad')
    const chart = createChart(el.current, {
      autoSize: true,
      layout: { background: { type: ColorType.Solid, color: 'transparent' }, textColor: text },
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
      bars.data.map((b) => ({
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
      bars.data.map((b) => ({
        time: b.date as Time,
        value: Number(b.volume),
        color: Number(b.close) >= Number(b.open) ? `${up}55` : `${down}55`,
      })),
    )
    if (bot.strategy === 'sma_cross') {
      const colors = [cssVar('--accent'), cssVar('--dry')]
      ;[bot.params.fast, bot.params.slow].forEach((n, i) => {
        const line = chart.addSeries(LineSeries, { color: colors[i], lineWidth: 2, priceLineVisible: false })
        line.setData(sma(bars.data, n))
      })
    }

    // 판단(BUY/SELL 신호)과 모의 체결을 표시한다.
    const markers: SeriesMarker<Time>[] = []
    for (const d of decisions.data ?? []) {
      if (d.action === 'HOLD') continue
      markers.push({
        time: d.session_date as Time,
        position: d.action === 'BUY' ? 'belowBar' : 'aboveBar',
        shape: 'circle',
        color: cssVar('--muted'),
        text: `${d.action} 신호`,
      })
    }
    for (const o of orders.data ?? []) {
      if (o.status !== 'FILLED' || !o.fill_date) continue
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
  }, [bars.data, decisions.data, orders.data, bot.strategy, bot.params])

  const last = bars.data?.at(-1)
  return (
    <section className="panel">
      <div className="panel-head">
        <h2>
          {bot.symbol} <span className="muted">일봉</span>
        </h2>
        {bot.strategy === 'sma_cross' && (
          <span className="muted small">
            <span style={{ color: 'var(--accent)' }}>━ SMA{bot.params.fast}</span>{' '}
            <span style={{ color: 'var(--dry)' }}>━ SMA{bot.params.slow}</span> · ● 신호 · ▲▼ 모의 체결
          </span>
        )}
      </div>
      <div ref={el} className="chart" />
      <p className="muted small">
        출처: 토스증권 Open API 일봉(수정주가, 정규장 기준) · 미국 거래일 · 마지막 봉 {last?.date ?? '—'} · 정규장 마감 2시간
        뒤부터 완료 봉으로 사용
      </p>
    </section>
  )
}
