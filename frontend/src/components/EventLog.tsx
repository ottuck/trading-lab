import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { api } from '../api'
import { kstTime } from '../format'

const LEVELS = ['', 'INFO', 'WARN', 'ERROR'] as const

export function EventLog() {
  const [level, setLevel] = useState<(typeof LEVELS)[number]>('')
  const { data, isLoading } = useQuery({ queryKey: ['events', level], queryFn: () => api.events(level) })
  return (
    <section className="panel">
      <div className="panel-head">
        <h2>로그</h2>
        <div className="controls">
          {LEVELS.map((l) => (
            <button key={l} className={l === level ? 'active' : ''} onClick={() => setLevel(l)}>
              {l || '전체'}
            </button>
          ))}
        </div>
      </div>
      {isLoading && <p className="muted">불러오는 중…</p>}
      {data && !data.length && <p className="muted">기록이 없습니다.</p>}
      {data && data.length > 0 && (
        <table>
          <thead>
            <tr>
              <th>시각</th>
              <th>수준</th>
              <th>종류</th>
              <th>내용</th>
              <th>실행 ID</th>
            </tr>
          </thead>
          <tbody>
            {data.map((e) => (
              <tr key={e.id}>
                <td className="nowrap">{kstTime(e.at)}</td>
                <td className={`level-${e.level}`}>{e.level}</td>
                <td className="nowrap">{e.kind}</td>
                <td>{e.message}</td>
                <td className="muted small mono">{e.run_id?.slice(0, 8) ?? ''}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  )
}
