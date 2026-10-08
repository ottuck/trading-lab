/* 전략마다 언제 사는지 보여주는 작은 그림. 이모지 대신 규칙을 한눈에 보여준다 (N8).
   색은 토큰만 써서 두 테마에서 같게 보인다. */

const GLYPHS: Record<string, React.ReactNode> = {
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
