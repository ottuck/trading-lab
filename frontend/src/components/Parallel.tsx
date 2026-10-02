import { useMutation, useQuery } from '@tanstack/react-query'
import { ColorType, createChart, LineSeries, type Time } from 'lightweight-charts'
import { useEffect, useRef, useState } from 'react'
import type { Parallel, World } from '../api'
import { money, percent } from '../format'
import { cssVar, useTheme } from '../theme'

/* 평행세계의 나 (N4): 내 규칙을 하나씩 바꾼 나들을 같은 기간에 나란히 본다.
   점수·등수·"잘했다" 문장은 붙이지 않고, 순서도 결과와 상관없이 늘 같다 (project.md 1절). */

/** 나와 무엇이 다른지 한 줄로: "고점에 쉬기 +15% → 안 쉼" */
function diff(me: Record<string, number>, other: Record<string, number> | null): string {
  if (!other) return '규칙 없이 넣을 때마다 바로 사요'
  const said: Record<string, (v: number) => string> = {
    regular: (v) => (v ? '매달 사기' : '떨어졌을 때만 사기'),
    hot: (v) => (v ? `+${v}%에 쉬기` : '고점에도 사기'),
    dip: (v) => `-${v}%에 몰아 사기`,
  }
  const key = Object.keys(said).find((k) => (me[k] ?? 1) !== (other[k] ?? 1))
  return key ? `${said[key](me[key] ?? 1)} → ${said[key](other[key] ?? 1)}` : ''
}

function Chart({ me, other }: { me: World; other: World }) {
  const el = useRef<HTMLDivElement>(null)
  const { theme } = useTheme()
  useEffect(() => {
    if (!el.current) return
    const chart = createChart(el.current, {
      autoSize: true,
      layout: { background: { type: ColorType.Solid, color: 'transparent' }, textColor: cssVar('--muted'), fontFamily: cssVar('--sans') },
      crosshair: { vertLine: { color: cssVar('--chart-cross') }, horzLine: { color: cssVar('--chart-cross') } },
      grid: { vertLines: { visible: false }, horzLines: { color: cssVar('--chart-grid') } },
      timeScale: { borderVisible: false, minBarSpacing: 0.01 },
      rightPriceScale: { mode: 1, borderVisible: false },
      localization: { locale: 'ko-KR', priceFormatter: (v: number) => `$${Math.round(v).toLocaleString('en-US')}` },
      handleScroll: false,
      handleScale: false,
    })
    const line = (w: World, color: string, width: 1 | 2) =>
      chart
        .addSeries(LineSeries, { color, lineWidth: width, priceLineVisible: false, lastValueVisible: false })
        .setData(w.equity.map((p) => ({ time: p.date as Time, value: Number(p.equity) })))
    line(other, cssVar('--accent'), 2)
    line(me, cssVar('--text'), 2)
    chart.timeScale().fitContent()
    return () => chart.remove()
  }, [me, other, theme])
  return <div ref={el} className="pw-chart" />
}

type Props = {
  queryKey: unknown[]
  fetch: () => Promise<Parallel>
  sub: (p: Parallel) => string
  chooseLabel?: string
  confirm?: string // 있으면 고르기 전에 한 번 더 묻는다
  onChoose?: (params: Record<string, number>) => Promise<unknown> | void
}

export function ParallelWorlds({ queryKey, fetch, sub, chooseLabel, confirm, onChoose }: Props) {
  const { data, error } = useQuery({ queryKey, queryFn: fetch, staleTime: 10 * 60_000, refetchOnWindowFocus: false, retry: false })
  const [picked, setPicked] = useState('dca')
  const [asking, setAsking] = useState(false)
  const choose = useMutation({
    mutationFn: async (params: Record<string, number>) => onChoose?.(params),
    onSuccess: () => setAsking(false),
  })
  const worlds = data?.worlds ?? []
  const me = worlds.find((w) => w.key === 'me')
  const other = worlds.find((w) => w.key === picked) ?? worlds.find((w) => w.key !== 'me')
  // 1년이 안 되면 연 수익률이 부풀려 보이므로 넣은 돈 대비로 보여준다.
  const long = !!data?.start && !!data.end && Date.parse(data.end) - Date.parse(data.start) >= 365 * 86_400_000
  const rate = (w: World) =>
    long ? `해마다 평균 ${percent(w.cagr)}` : `넣은 돈보다 ${percent(String(Number(w.final_equity) / Number(w.contributed) - 1))}`
  return (
    <section className="block pw">
      <div className="block-head">
        <h2>평행세계의 나</h2>
        {data && <span className="sub">{sub(data)}</span>}
      </div>
      {error ? (
        <div className="line-empty">계산하지 못했어요: {error.message}</div>
      ) : !data ? (
        <div className="line-empty">다른 나들을 계산하는 중…</div>
      ) : !me || !other ? (
        <div className="line-empty">{data.note ?? '아직 비교할 수 없어요.'}</div>
      ) : (
        <>
          <Chart me={me} other={other} />
          <div className="pw-legend">
            <span className="legend">
              <i className="pw-mine" />나
            </span>
            <span className="legend">
              <i className="other" />
              {other.title}
            </span>
          </div>
          <div className="pw-list" role="listbox" aria-label="평행세계의 나">
            {worlds.map((w) => {
              return (
                <button
                  key={w.key}
                  role="option"
                  aria-selected={w.key === other.key}
                  className={`pw-item ${w.key === 'me' ? 'pw-mine' : ''}`}
                  disabled={w.key === 'me'}
                  onClick={() => {
                    setPicked(w.key)
                    setAsking(false)
                  }}
                >
                  <div>
                    <div className="title">{w.title}</div>
                    <div className="sub">
                      {w.key === 'me' ? '지금 규칙 그대로' : w.same_as_me ? '이 기간엔 나와 같았어요' : diff(me.params ?? {}, w.params)}
                    </div>
                  </div>
                  <div className="r">
                    <div className="value tnum">{money(w.final_equity)}</div>
                    <div className="sub">{rate(w)}</div>
                  </div>
                </button>
              )
            })}
          </div>
          {onChoose && other.params && other.key !== 'me' && (
            <div className="pw-choose">
              {asking ? (
                <>
                  <span className="small">{confirm}</span>
                  <button className="primary" disabled={choose.isPending} onClick={() => choose.mutate(other.params!)}>
                    바꾸기
                  </button>
                  <button onClick={() => setAsking(false)}>취소</button>
                </>
              ) : (
                <button onClick={() => (confirm ? setAsking(true) : choose.mutate(other.params!))}>
                  &quot;{other.title}&quot;{chooseLabel}
                </button>
              )}
              {choose.error && <span className="bad small">{choose.error.message}</span>}
              {choose.isSuccess && !asking && confirm && <span className="ok small">바꿨어요. 다음 판단부터 적용돼요.</span>}
            </div>
          )}
        </>
      )}
    </section>
  )
}
