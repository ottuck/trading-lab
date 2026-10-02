import { useState } from 'react'
import { GLOSSARY } from '../glossary'

/** 용어 옆에 붙는 ⓘ. 누르면 쉬운 설명이 펼쳐진다. */
export function Term({ k, children }: { k: string; children?: React.ReactNode }) {
  const [open, setOpen] = useState(false)
  const text = GLOSSARY[k]
  return (
    <span className="term">
      {children ?? k}
      {text && (
        <button className="info" aria-label={`${k} 설명`} onClick={() => setOpen(!open)}>
          ⓘ
        </button>
      )}
      {open && text && (
        <span className="tip" onClick={() => setOpen(false)}>
          {text}
        </span>
      )}
    </span>
  )
}

/** 헤더의 "도움말" 버튼과 용어 설명 창. */
export function HelpButton() {
  const [open, setOpen] = useState(false)
  return (
    <>
      <button className="icon-btn" aria-label="도움말" title="도움말" onClick={() => setOpen(true)}>
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
          <circle cx="12" cy="12" r="9" />
          <path d="M9.6 9.2a2.5 2.5 0 0 1 4.8.9c0 1.7-2.4 2.2-2.4 3.9M12 17h.01" />
        </svg>
      </button>
      {open && (
        <div className="modal-backdrop" onClick={() => setOpen(false)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <div className="panel-head">
              <div className="card-title">용어 설명</div>
              <button className="ghost" onClick={() => setOpen(false)}>
                닫기
              </button>
            </div>
            <p className="muted small">
              이 앱은 실제 돈을 쓰지 않는 <b>모의 투자</b>예요. 실제 미국 주식 가격으로 전략을 따라 했다면 어땠을지 매일
              계산해요.
            </p>
            <dl className="glossary">
              {Object.entries(GLOSSARY).map(([term, text]) => (
                <div key={term}>
                  <dt>{term}</dt>
                  <dd>{text}</dd>
                </div>
              ))}
            </dl>
          </div>
        </div>
      )}
    </>
  )
}
