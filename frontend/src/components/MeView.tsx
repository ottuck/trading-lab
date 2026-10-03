import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { api, backtestApi, botApi, type Bot } from '../api'
import { money, percent } from '../format'
import { DAYS, DEPOSITS, DIP, HOT, START, STYLES, answersOf, describe, stepsOf, toParams, type Answers, type Option } from '../me'
import { suggestName } from '../basket'
import { endMeEdit, goTo, selectBot, useMeEdit } from '../selectedBot'
import { isMeBot } from '../strategies'
import { toConfig, toDraft } from '../botConfig'
import { EquityChart } from './BacktestView'
import { ParallelWorlds } from './Parallel'
import { BasketPicker } from './SymbolPicker'

/* 나 카피하기: 한 화면에 질문 하나씩 (토스식). 답하면 바로 다음 질문으로 넘어가고,
   마지막에 쉬운 말 요약과 "나처럼 10년 했다면 vs 매달 그냥 사기"를 보여준 뒤 봇으로 시작한다. */

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

function Question({ n, of, title, hint, children }: { n: number; of: number; title: string; hint?: string; children: React.ReactNode }) {
  return (
    <>
      <div className="me-progress" aria-label={`질문 ${n} / ${of}`}>
        <span className="tnum">
          {n} / {of}
        </span>
        <div className="bar">
          <i style={{ width: `${(n / of) * 100}%` }} />
        </div>
      </div>
      <h1 className="me-q">{title}</h1>
      {hint && <p className="me-hint">{hint}</p>}
      {children}
    </>
  )
}

function Result({
  answers,
  editing,
  onEdit,
  onAdopt,
}: {
  answers: Answers
  editing?: Bot
  onEdit: () => void
  onAdopt: (p: Record<string, number>) => void
}) {
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
      goTo('dashboard')
    },
  })
  // 질문 다시 하기: 같은 나 카피 봇의 규칙(과 종목)을 바꾼다. 다음 판단부터 적용된다.
  const change = useMutation({
    mutationFn: async (bot: Bot) => {
      await botApi.updateConfig(bot.id, { ...toConfig(toDraft(bot), bot), params })
      const before = bot.symbols.filter((s) => s.weight > 0)
      if (JSON.stringify(before) !== JSON.stringify(answers.symbols)) await botApi.updateSymbols(bot.id, answers.symbols)
      return bot
    },
    onSuccess: (bot) => {
      void qc.invalidateQueries({ queryKey: ['bots'] })
      endMeEdit()
      selectBot(bot.id)
      goTo('dashboard')
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
          {m.final_equity === m.benchmark_final_equity && (
            <p className="me-preview">결과가 매달 그냥 사기와 똑같은 나예요. 이 기간에는 규칙이 사는 때를 바꾸지 않았어요.</p>
          )}
          <EquityChart detail={data} />
          <p className="faint small">
            둘 다 같은 날 같은 돈({money(m.contributed ?? m.initial_cash)})을 넣었어요. 실제 가격으로 계산했고, 재미로 보는
            비교예요.
          </p>
        </>
      )}

      {data && m && (
        <ParallelWorlds
          queryKey={['parallel', JSON.stringify(body)]}
          fetch={() => backtestApi.parallel(body)}
          sub={() => `${ym(m.start)}부터, 규칙을 하나씩 바꿨다면`}
          chooseLabel="로 바꾸기"
          onChoose={onAdopt}
        />
      )}

      <div className="me-nav">
        <button onClick={onEdit}>답 고치기</button>
        {data && (
          <button className="link" onClick={() => (location.hash = 'backtest')}>
            자세히 보기
          </button>
        )}
        {editing ? (
          <button className="primary" disabled={change.isPending || !data} onClick={() => change.mutate(editing)}>
            {change.isPending ? '바꾸는 중…' : `${editing.name} 규칙 바꾸기`}
          </button>
        ) : (
          <button className="primary" disabled={start.isPending || !data} onClick={() => start.mutate()}>
            {start.isPending ? '만드는 중…' : '이 나로 모의 투자 시작'}
          </button>
        )}
      </div>
      {(start.error ?? change.error) && <div className="bad small">{(start.error ?? change.error)?.message}</div>}
      <p className="faint small">
        {editing
          ? '바꾸면 다음 판단부터 이 규칙으로 해요. 지금까지의 기록은 그대로예요.'
          : '모의 투자는 실제 계좌와 상관없어요. 시작하면 이번 달 넣는 돈으로 바로 시작해요.'}
      </p>
    </>
  )
}

export function MeView() {
  const qc = useQueryClient()
  // 규칙 바꾸기 대상은 처음 열 때 한 번만 읽는다 (아래 정리로 전역 값이 풀려도 유지).
  const [editId] = useState(useMeEdit())
  const editing = qc.getQueryData<Bot[]>(['bots'])?.find((b) => b.id === editId && isMeBot(b))
  // #me를 떠나면 규칙 바꾸기 모드를 푼다.
  useEffect(() => endMeEdit, [])
  // 0: 소개, 1~n: 질문(답에 따라 4~6개), n+1: 결과. 규칙 바꾸기는 소개 없이 첫 질문부터.
  const [at, setAt] = useState(editing ? 1 : 0)
  const [a, setA] = useState<Answers>(() => (editing ? answersOf(editing) : START))
  const [customDeposit, setCustomDeposit] = useState('')
  const steps = stepsOf(a)
  const step = at >= 1 && at <= steps.length ? steps[at - 1] : null
  const set = (patch: Partial<Answers>) => setA({ ...a, ...patch })
  // 하나만 고르는 질문은 고르면 바로 다음으로 넘어간다.
  const pick = (patch: Partial<Answers>) => {
    set(patch)
    setAt(at + 1)
  }
  const total = a.symbols.reduce((sum, s) => sum + s.weight, 0)
  const nav = (ready = true) => (
    <div className="me-nav">
      <button onClick={() => setAt(at - 1)}>이전</button>
      <button className="primary" disabled={!ready} onClick={() => setAt(at + 1)}>
        다음
      </button>
    </div>
  )
  const q = (title: string, hint: string, body: React.ReactNode, ready = true) => (
    <Question n={at} of={steps.length} title={title} hint={hint}>
      {body}
      {nav(ready)}
    </Question>
  )

  return (
    <div className="me">
      <div className="me-top">
        <button className="link" onClick={() => (location.hash = 'dashboard')}>
          나가기
        </button>
      </div>

      {at === 0 && (
        <>
          <p className="me-eyebrow">나 카피 봇</p>
          <h1 className="me-q">지금부터 당신의 투자 습관을 복사할게요</h1>
          <p className="me-hint">평소 어떻게 투자하는지 몇 가지만 물어볼게요. 답한 그대로 따라 하는 봇이 만들어져요.</p>
          <ul className="me-points">
            <li>
              <b>1분이면 끝나요</b>
              <span>질문 4~6개, 고르기만 하면 돼요.</span>
            </li>
            <li>
              <b>정답은 없어요</b>
              <span>잘하는 투자 말고, 평소 하던 그대로 골라 주세요.</span>
            </li>
            <li>
              <b>계좌는 연결하지 않아요</b>
              <span>어느 증권사를 쓰든 상관없어요.</span>
            </li>
          </ul>
          <p className="me-preview">
            다 답하면 지난 {YEARS}년을 실제 가격으로 계산해 <b>나처럼 했다면</b>과 <b>매달 그냥 샀다면</b>을 나란히
            보여드려요.
          </p>
          <div className="me-nav">
            <button className="primary" onClick={() => setAt(1)}>
              시작하기
            </button>
          </div>
          <div className="me-limit">
            <b>아직 복사하기 어려운 투자도 있어요.</b> 그때그때 기분이나 뉴스를 보고 사고팔거나, 며칠·몇 주 단위로 자주 사고파는
            투자는 규칙으로 옮길 수 없어요. &quot;매달 얼마, 많이 오르면 쉬고, 떨어지면 몰아 사기&quot;처럼 말로 정할 수 있는 습관만
            따라 해요. 파는 습관도 아직 복사하지 않아요 (산 주식은 계속 들고 있어요).
          </div>
        </>
      )}

      {step === 'symbols' &&
        q(
          '평소에 어떤 종목을 사나요?',
          '어느 증권사에서 사든 괜찮아요. 평소 사는 그대로 골라 주세요.',
          <BasketPicker value={a.symbols} onChange={(symbols) => set({ symbols })} />,
          a.symbols.length > 0 && total === 100,
        )}

      {step === 'style' &&
        q(
          '주로 어떻게 사나요?',
          '딱 맞지 않아도 더 가까운 쪽을 골라 주세요.',
          <Choices options={STYLES} value={a.regular} onPick={(regular) => pick({ regular })} />,
        )}

      {step === 'deposit' &&
        q(
          '투자에 쓰는 돈은 한 달 평균 얼마쯤이에요?',
          '매달 사지 않아도 괜찮아요. 1년 동안 넣는 돈을 12로 나눈 정도로, 달러로 골라 주세요.',
          <>
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
                  aria-label="한 달 평균 직접 입력"
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
          </>,
          a.deposit > 0,
        )}

      {step === 'day' &&
        q(
          '보통 언제 넣나요?',
          '월급날처럼 매달 돈이 들어오는 날이요. 정해진 날이 없어도 괜찮아요.',
          <Choices options={DAYS} value={a.day} onPick={(day) => pick({ day })} />,
        )}

      {step === 'hot' &&
        q(
          '많이 오른 것 같을 때는 어떻게 하나요?',
          '쉬는 달에 넣은 돈은 쓰지 않고 모아 둬요.',
          <Choices options={HOT} value={a.hot} onPick={(hot) => pick({ hot })} />,
        )}

      {step === 'dip' &&
        q(
          a.regular ? '많이 떨어지면 언제 몰아서 사나요?' : '얼마나 떨어지면 사나요?',
          a.regular ? '그때는 입금일이 아니어도 모아 둔 돈까지 다 사요.' : '그때 모아 둔 돈을 한꺼번에 사요.',
          <Choices options={DIP} value={a.dip} onPick={(dip) => pick({ dip })} />,
        )}

      {at > steps.length && (
        <Result
          answers={a}
          editing={editing}
          onEdit={() => setAt(1)}
          onAdopt={(p) => {
            // 고른 다른 나의 규칙으로 바꾸고 처음부터 다시 보여준다 (종목·날짜는 그대로).
            setA({ ...a, deposit: p.deposit, hot: p.hot, dip: p.dip, regular: p.regular })
            window.scrollTo({ top: 0, behavior: 'smooth' })
          }}
        />
      )}
    </div>
  )
}
