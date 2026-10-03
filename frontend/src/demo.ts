import { useQuery } from '@tanstack/react-query'
import { api } from './api'

/** 포트폴리오 데모(D2)인지. 데모는 예시 시세만 있고 봇을 만들거나 바꿀 수 없다 (서버가 막는다). */
export function useDemo(): boolean {
  const { data } = useQuery({ queryKey: ['health'], queryFn: api.health })
  return !!data?.demo
}

/** 계산에 쓴 가격을 부르는 말. 데모는 예시 시세라 "실제 가격"이라고 쓰지 않는다. */
export function usePriceWord(): string {
  return useDemo() ? '예시 가격' : '실제 가격'
}
