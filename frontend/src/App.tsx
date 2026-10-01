import { useEffect, useState } from 'react'

type Health = {
  version: string
  db: 'ok' | 'down'
  worker: { alive: boolean; worker_id: string | null; last_seen_at: string | null } | null
}

const POLL_MS = 10_000

function useHealth() {
  const [health, setHealth] = useState<Health | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    const load = async () => {
      try {
        const res = await fetch('/api/health')
        const body = (await res.json()) as Health
        if (!cancelled) {
          setHealth(body)
          setError(null)
        }
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e))
      }
    }
    void load()
    const id = setInterval(load, POLL_MS)
    return () => {
      cancelled = true
      clearInterval(id)
    }
  }, [])

  return { health, error }
}

function Status({ ok, label }: { ok: boolean; label: string }) {
  return <span style={{ color: ok ? 'var(--ok)' : 'var(--bad)' }}>● {label}</span>
}

export default function App() {
  const { health, error } = useHealth()
  const worker = health?.worker

  return (
    <main>
      <header style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
        <h1 style={{ margin: 0, fontSize: 22 }}>Quant Lab</h1>
        <span
          style={{
            color: 'var(--dry)',
            border: '1px solid var(--dry)',
            borderRadius: 4,
            padding: '0 6px',
            fontSize: 12,
            fontWeight: 600,
          }}
        >
          DRY RUN
        </span>
      </header>

      <section
        style={{
          marginTop: 24,
          padding: 16,
          background: 'var(--panel)',
          border: '1px solid var(--border)',
          borderRadius: 8,
        }}
      >
        <h2 style={{ margin: '0 0 12px', fontSize: 16 }}>시스템 상태</h2>
        {error && <Status ok={false} label={`API 연결 실패: ${error}`} />}
        {!error && !health && <span style={{ color: 'var(--muted)' }}>불러오는 중…</span>}
        {health && (
          <ul style={{ listStyle: 'none', padding: 0, margin: 0, display: 'grid', gap: 6 }}>
            <li>
              <Status ok={health.db === 'ok'} label={`DB ${health.db === 'ok' ? '정상' : '연결 안 됨'}`} />
            </li>
            <li>
              <Status ok={!!worker?.alive} label={`Worker ${worker?.alive ? '동작 중' : '정지'}`} />
              {worker?.last_seen_at && (
                <span style={{ color: 'var(--muted)', marginLeft: 8 }}>
                  마지막 신호 {new Date(worker.last_seen_at).toLocaleString('ko-KR')}
                </span>
              )}
            </li>
            <li style={{ color: 'var(--muted)' }}>버전 {health.version}</li>
          </ul>
        )}
      </section>
    </main>
  )
}
