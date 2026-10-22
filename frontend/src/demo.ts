import { useQuery } from '@tanstack/react-query'
import { api } from './api'

/** 포트폴리오 데모(D2)인지. 데모는 예시 시세만 있고 봇을 만들거나 바꿀 수 없다 (서버가 막는다). */
export function useDemo(): boolean {
  const { data } = useQuery({ queryKey: ['health'], queryFn: api.health })
  return !!data?.demo
}

/** 데모의 AI 예시 판단은 화면에서 한 번만 알린다 (판단 문장은 실제 봇과 같은 말투). */
export const demoAiNote = (candle: boolean): string =>
  candle
    ? '예시 판단이에요. 데모는 실제 AI가 아니라 정해진 규칙으로 데모 차트를 보고 판단을 만들어요 (비용 없음).'
    : '예시 판단이에요. 데모는 실제 AI가 아니라 정해진 규칙으로 판단을 만들고, 시장 분위기 지수와 뉴스도 데모 가격에 맞춘 예시예요 (비용 없음).'

/** 계산에 쓴 가격을 부르는 말. 데모는 예시 시세라 "실제 가격"이라고 쓰지 않는다. */
export function usePriceWord(): string {
  return useDemo() ? '예시 가격' : '실제 가격'
}
