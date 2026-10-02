import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api, backtestApi, botApi } from '../api'
import { money, percent } from '../format'
import { DAYS, DEPOSITS, DIP, HOT, START, describe, toParams, type Answers, type Option } from '../me'
import { suggestName } from '../basket'
import { selectBot } from '../selectedBot'
import { EquityChart } from './BacktestView'
import { BasketPicker } from './SymbolPicker'

/* 질문으로 나 만들기: 한 화면에 질문 하나씩 (토스식). 답하면 바로 다음 질문으로 넘어가고,
   마지막에 쉬운 말 요약과 "나처럼 10년 했다면 vs 매달 그냥 사기"를 보여준 뒤 봇으로 시작한다. */

const QUESTIONS = 5
const YEARS = 10

function tenYearsAgo() {
  const d = new Date()
  d.setFullYear(d.getFullYear() - YEARS)
  return d.toISOString().slice(0, 10)
}

const ym = (date: string) => `${date.slice(0, 4)}년 ${Number(date.slice(5, 7))}월`

function Choices({ options, value, onPick }: { options: Option[]; value: number; onPick: (v: number) => void }) {
  return (
    <div className="me-options">
      {options.map((o) => (
        <button key={o.value} className="me-option" aria-pressed={o.value === value} onClick={() => onPick(o.value)}>
          <span className="title">{o.label}</span>
          {o.sub && <span className="sub">{o.sub}</span>}
        </button>
      ))}
    </div>
  )
}

function Question({ n, title, hint, children }: { n: number; title: string; hint?: string; children: React.ReactNode }) {
  return (
    <>
      <div className="me-progress" aria-label={`질문 ${n} / ${QUESTIONS}`}>
        <span className="tnum">
          {n} / {QUESTIONS}
        </span>
        <div className="bar">
          <i style={{ width: `${(n / QUESTIONS) * 100}%` }} />
        </div>
      </div>
      <h1 className="me-q">{title}</h1>
      {hint && <p className="me-hint">{hint}</p>}
      {children}
    </>
  )
}

function Result({ answers, onEdit }: { answers: Answers; onEdit: () => void }) {
  const qc = useQueryClient()
  const params = toParams(answers)
  const body = {
    symbol: answers.symbols[0].symbol,
    symbols: answers.symbols.length > 1 ? answers.symbols : undefined,
    strategy: 'dip_saver',
    params,
    start: tenYearsAgo(),
  }
  // 같은 답이면 다시 계산하지 않는다 (결과는 시험해 보기의 지난 시험에도 남는다).
  const { data, error } = useQuery({
    queryKey: ['me-backtest', JSON.stringify(body)],
    queryFn: async () => {
      const result = await backtestApi.run(body)
      void qc.invalidateQueries({ queryKey: ['backtests'] })
      return result
    },
    staleTime: Infinity,
    refetchOnWindowFocus: false,
    retry: false,
  })
  const bots = useQuery({ queryKey: ['bots'], queryFn: api.bots })
  const start = useMutation({
    mutationFn: async () => {
      const taken = (bots.data ?? []).map((b) => b.name)
      const bot = await botApi.create({
        strategy: 'dip_saver',
        params,
        commission_rate: '0.001',
        slippage_bps: '5',
        max_position_value: null,
        max_order_value: null,
        name: suggestName(
          answers.symbols.map((s) => s.symbol),
          'dip_saver',
          taken,
        ),
        symbol: body.symbol,
        symbols: body.symbols,
        initial_cash: String(answers.deposit),
      })
      await api.command(bot.id, 'START')
      return bot
    },
    onSuccess: (bot) => {
      void qc.invalidateQueries({ queryKey: ['bots'] })
      selectBot(bot.id)
      location.hash = 'dashboard'
    },
  })
  const m = data?.metrics
  return (
    <>
      <h1 className="me-q">이런 나예요</h1>
      <ul className="me-summary">
        {describe(answers).map((line) => (
          <li key={line}>{line}</li>
        ))}
      </ul>

      <h2 className="me-sub">{m ? `${ym(m.start)}부터 이렇게 했다면` : `지난 ${YEARS}년 동안 이렇게 했다면`}</h2>
      {error ? (
        <div className="alert">계산하지 못했어요: {error.message}</div>
      ) : !data || !m ? (
        <div className="line-empty">실제 가격으로 계산하는 중…</div>
      ) : (
        <>
          <div className="me-worlds">
            <div className="me-world">
              <div className="label legend">
                <i className="strat" />
                나처럼 했다면
              </div>
              <div className="value tnum">{money(m.final_equity)}</div>
              <div className="sub">해마다 평균 {percent(m.cagr)}</div>
            </div>
            <div className="me-world">
              <div className="label legend">
                <i className="bench" />
                매달 그냥 샀다면
              </div>
              <div className="value tnum">{money(m.benchmark_final_equity)}</div>
              <div className="sub">해마다 평균 {percent(m.benchmark_cagr)}</div>
            </div>
          </div>
          <EquityChart detail={data} />
          <p className="faint small">
            둘 다 같은 날 같은 돈({money(m.contributed ?? m.initial_cash)})을 넣었어요. 실제 가격으로 계산했고, 재미로 보는
            비교예요.
          </p>
        </>
      )}

      <div className="me-nav">
        <button onClick={onEdit}>답 고치기</button>
        {data && (
          <button className="link" onClick={() => (location.hash = 'backtest')}>
            자세히 보기
          </button>
        )}
        <button className="primary" disabled={start.isPending || !data} onClick={() => start.mutate()}>
          {start.isPending ? '만드는 중…' : '이 나로 모의 투자 시작'}
        </button>
      </div>
      {start.error && <div className="bad small">{start.error.message}</div>}
      <p className="faint small">모의 투자는 실제 계좌와 상관없어요. 시작하면 이번 달 넣는 돈으로 바로 시작해요.</p>
    </>
  )
}

export function MeView() {
  // 0: 소개, 1~5: 질문, 6: 결과
  const [step, setStep] = useState(0)
  const [a, setA] = useState<Answers>(START)
  const [customDeposit, setCustomDeposit] = useState('')
  const set = (patch: Partial<Answers>) => setA({ ...a, ...patch })
  // 하나만 고르는 질문은 고르면 바로 다음으로 넘어간다.
  const pick = (patch: Partial<Answers>) => {
    set(patch)
    setStep(step + 1)
  }
  const total = a.symbols.reduce((sum, s) => sum + s.weight, 0)
  const back = (
    <button onClick={() => setStep(step - 1)} disabled={step === 0}>
      이전
    </button>
  )

  return (
    <div className="me">
      <div className="me-top">
        <button className="link" onClick={() => (location.hash = 'dashboard')}>
          나가기
        </button>
      </div>

      {step === 0 && (
        <>
          <h1 className="me-q">나처럼 투자하는 봇을 만들어 볼까요?</h1>
          <p className="me-hint">
            질문 {QUESTIONS}개에 답하면 그대로 따라 하는 규칙이 만들어져요. 그 규칙으로 지난 {YEARS}년을 실제 가격으로 계산해 &quot;매달
            그냥 사기&quot;와 나란히 보여드려요. 실제 계좌는 연결하지 않아요.
          </p>
          <div className="me-nav">
            <button className="primary" onClick={() => setStep(1)}>
              시작하기
            </button>
          </div>
        </>
      )}

      {step === 1 && (
        <Question n={1} title="평소에 어떤 종목을 사나요?" hint="어느 증권사에서 사든 괜찮아요. 평소 사는 그대로 골라 주세요.">
          <BasketPicker value={a.symbols} onChange={(symbols) => set({ symbols })} />
          <div className="me-nav">
            {back}
            <button className="primary" disabled={!a.symbols.length || total !== 100} onClick={() => setStep(2)}>
              다음
            </button>
          </div>
        </Question>
      )}

      {step === 2 && (
        <Question n={2} title="한 달에 얼마 정도 넣나요?" hint="달러로 골라 주세요. 엔이나 원으로 넣는다면 비슷한 금액이면 돼요.">
          <Choices
            options={DEPOSITS}
            value={customDeposit ? -1 : a.deposit}
            onPick={(deposit) => {
              setCustomDeposit('')
              pick({ deposit })
            }}
          />
          <div className="me-custom">
            <span className="dollar">
              $
              <input
                inputMode="numeric"
                placeholder="직접 입력"
                aria-label="한 달에 넣는 돈 직접 입력"
                value={customDeposit}
                onChange={(e) => {
                  const v = e.target.value.replace(/[^0-9]/g, '')
                  setCustomDeposit(v)
                  if (Number(v) > 0) set({ deposit: Number(v) })
                }}
                size={8}
              />
            </span>
          </div>
          <div className="me-nav">
            {back}
            <button className="primary" disabled={!(a.deposit > 0)} onClick={() => setStep(3)}>
              다음
            </button>
          </div>
        </Question>
      )}

      {step === 3 && (
        <Question n={3} title="보통 언제 넣나요?" hint="월급날처럼 매달 돈이 들어오는 날이요. 쉬는 날이면 그다음 거래일에 넣어요.">
          <Choices options={DAYS} value={a.day} onPick={(day) => pick({ day })} />
          <div className="me-nav">
            {back}
            <button className="primary" onClick={() => setStep(4)}>
              다음
            </button>
          </div>
        </Question>
      )}

      {step === 4 && (
        <Question n={4} title="많이 오른 것 같을 때는 어떻게 하나요?" hint="쉬는 달에 넣은 돈은 쓰지 않고 모아 둬요.">
          <Choices options={HOT} value={a.hot} onPick={(hot) => pick({ hot })} />
          <div className="me-nav">
            {back}
            <button className="primary" onClick={() => setStep(5)}>
              다음
            </button>
          </div>
        </Question>
      )}

      {step === 5 && (
        <Question n={5} title="많이 떨어지면 언제 몰아서 사나요?" hint="그때는 입금일이 아니어도 모아 둔 돈까지 다 사요.">
          <Choices options={DIP} value={a.dip} onPick={(dip) => pick({ dip })} />
          <div className="me-nav">
            {back}
            <button className="primary" onClick={() => setStep(6)}>
              다음
            </button>
          </div>
        </Question>
      )}

      {step === 6 && <Result answers={a} onEdit={() => setStep(1)} />}
    </div>
  )
}
