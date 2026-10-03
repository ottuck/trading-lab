/* 전략마다 언제 사고파는지 보여주는 작은 그림. 빨간 점은 사는 때, 파란 점은 파는 때, 점선은 기준선.
   이모지 대신 규칙을 한눈에 보여준다 (N8). 색은 토큰만 써서 두 테마에서 같게 보인다. */

const price = { fill: 'none', stroke: 'var(--muted)', strokeWidth: 1.5, strokeLinejoin: 'round' as const }
const rule = { stroke: 'var(--text)', strokeWidth: 1.2, strokeDasharray: '3 3', fill: 'none' }
const faint = { stroke: 'var(--faint)', strokeWidth: 1.2, strokeDasharray: '3 3', fill: 'none' }
const buy = (cx: number, cy: number) => <circle cx={cx} cy={cy} r={4} fill="var(--rise)" />
const sell = (cx: number, cy: number) => <circle cx={cx} cy={cy} r={4} fill="var(--fall)" />

const GLYPHS: Record<string, React.ReactNode> = {
  // 빠른 평균이 느린 평균을 올라서면 사고, 내려서면 판다
  sma_cross: (
    <>
      <path d="M4 44 C20 40 30 30 46 26 S70 14 88 18 S112 34 126 40 S146 46 156 44" {...price} />
      <path d="M4 46 C30 42 50 32 70 26 S110 26 130 36 S150 44 156 44" {...rule} />
      {buy(38, 33)}
      {sell(118, 33)}
    </>
  ),
  // 최근 최고가를 넘으면 사고, 최근 최저가 아래로 가면 판다
  donchian: (
    <>
      <path d="M4 26 H90" {...rule} />
      <path d="M4 44 H156" {...faint} />
      <path d="M4 38 L16 30 L28 36 L40 28 L52 34 L64 29 L76 33 L90 22 L104 12 L116 16 L128 26 L140 40 L152 50" {...price} />
      {buy(90, 22)}
      {sell(143, 44)}
    </>
  ),
  // 200일 평균 위에 있을 때만 들고 있는다
  trend_filter: (
    <>
      <path d="M34 30 L46 22 L58 26 L70 16 L82 20 L94 12 L106 18 L118 30 L118 32 L34 32 Z" fill="var(--accent-soft)" />
      <path d="M4 32 H156" {...rule} />
      <path d="M4 42 L20 38 L34 30 L46 22 L58 26 L70 16 L82 20 L94 12 L106 18 L118 30 L130 42 L144 46 L156 40" {...price} />
      {buy(34, 31)}
      {sell(119, 31)}
    </>
  ),
  // 오르는 흐름 속에서 짧게 확 빠지면 사고, 반등하면 판다
  rsi2: (
    <>
      <path d="M4 40 L24 34 L44 28 L60 24 L70 44 L78 48 L90 28 L104 20 L124 16 L156 10" {...price} />
      {buy(78, 48)}
      {sell(96, 25)}
    </>
  ),
  // 나처럼 투자: 매달 산다(칸), 고점엔 쉬고 모은다(빈 칸), 하락장엔 모은 돈까지 몰아 산다(큰 막대)
  dip_saver: (
    <>
      {[8, 26, 98, 116, 134].map((x) => (
        <rect key={x} x={x} y={40} width={12} height={12} rx={2} fill="var(--faint)" />
      ))}
      {[44, 62].map((x) => (
        <rect key={x} x={x} y={40} width={12} height={12} rx={2} fill="none" stroke="var(--faint)" strokeDasharray="2 2" />
      ))}
      <rect x={80} y={16} width={12} height={36} rx={2} fill="var(--rise)" />
    </>
  ),
}

export function StrategyGlyph({ name, className = '' }: { name: string; className?: string }) {
  const glyph = GLYPHS[name]
  if (!glyph) return null
  return (
    <svg className={`glyph ${className}`} viewBox="0 0 160 56" preserveAspectRatio="xMinYMid meet" aria-hidden="true">
      {glyph}
    </svg>
  )
}
