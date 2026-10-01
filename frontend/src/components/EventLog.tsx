import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { api } from '../api'

const LEVELS = ['', 'INFO', 'WARN', 'ERROR'] as const

// 로그는 KST 초 단위까지 보여준다 (운영 콘솔처럼).
const ts = new Intl.DateTimeFormat('sv-SE', {
  timeZone: 'Asia/Seoul',
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
  hour12: false,
})

export function EventLog() {
  const [level, setLevel] = useState<(typeof LEVELS)[number]>('')
  const { data, isLoading } = useQuery({ queryKey: ['events', level], queryFn: () => api.events(level) })
  return (
    <section className="card">
      <div className="panel-head">
        <div className="card-title">
          시스템 로그 <span className="sub">KST · 최근 200건</span>
        </div>
        <div className="controls">
          {LEVELS.map((l) => (
            <button key={l} className={`seg ${l === level ? 'active' : ''}`} onClick={() => setLevel(l)}>
              {l || '전체'}
            </button>
          ))}
        </div>
      </div>
      <div className="terminal" style={{ marginTop: 14 }}>
        {isLoading && <div className="muted">불러오는 중…</div>}
        {data && !data.length && <div className="muted">기록이 없습니다.</div>}
        {data?.map((e) => (
          <div key={e.id} className="line">
            <span className="ts">{ts.format(new Date(e.at))}</span>{' '}
            <span className={`level-${e.level}`}>[{e.level}]</span> <span className="muted">{e.kind}:</span>{' '}
            {e.message}
            {e.run_id && <span className="ts"> (run {e.run_id.slice(0, 8)})</span>}
          </div>
        ))}
      </div>
    </section>
  )
}
