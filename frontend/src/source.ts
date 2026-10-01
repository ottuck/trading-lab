// 일봉 출처 표시. 운영은 토스, 데모·테스트는 합성 데이터다.
export function sourceLabel(source: string | null | undefined): string {
  if (source === 'toss') return '토스증권 Open API 일봉(수정주가, 정규장 기준)'
  if (source === 'synthetic') return '합성 데이터 (데모)'
  return source ?? '—'
}
