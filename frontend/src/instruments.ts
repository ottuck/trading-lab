import { useQuery } from '@tanstack/react-query'
import { api, type Instrument } from './api'

// Worker가 아직 종목 정보를 못 받았을 때(로컬 모드 등)의 기본 목록
export const FALLBACK = ['QQQ', 'VOO', 'QLD', 'TQQQ', 'SOXL', 'NVDA', 'GLD', 'MAGS', 'EWY', 'EWJ']

export function leverageOf(list: Instrument[] | undefined, symbol: string): number {
  return Number(list?.find((i) => i.symbol === symbol)?.leverage_factor ?? 1)
}

export function useInstruments() {
  return useQuery({ queryKey: ['instruments'], queryFn: api.instruments, staleTime: 60_000 })
}
