# Trading Lab 설계

> **이 문서가 설계의 단일 출처다.** 일정과 진행 상태는 [roadmap.md](roadmap.md), 토스 API 조사 결과는 [tossApi.md](tossApi.md)에 둔다.
> 결정이 바뀌면 그 변경을 담은 PR에서 이 문서도 함께 고친다. 최종 갱신: 2026-10-15.

## 1. 한 줄 정의

토스증권 공식 Open API의 미국 주식 시세로 규칙 기반 전략(나 카피 봇)과 **AI가 매일 비중을 정하는 AI 봇**(14절, 뉴스를 조사하는 시장분석·가격 차트만 보는 캔들분석)을 돌리고, 모든 판단을 먼저 **내부 모의 체결(DRY RUN)**로 신호·주문·포지션·손익과 판단 이유까지 추적하는 개인용 도구. 그 판단을 **1/100 금액으로 실제 토스 계좌에서 따라 한다** (마일스톤 3, AI 봇은 마일스톤 4). **남에게 서비스하지 않고, 나를 대신해 투자하는 앱으로 만든다** (2026-10-03 결정, 이유는 12절).

### 제품의 중심: 나 카피 봇 (2026-10-02 결정)

**"내 투자 습관을 옮긴 봇이, 내가 실제로 투자하지 않은 달에도 내 방식대로 계속 투자했다면 어땠을지 보여준다."**

- **무엇이 다른가:** 비슷한 서비스는 남을 따라 하거나(카피 트레이딩: eToro·Tickeron), 규칙을 직접 설계하게 하거나(Composer by SoFi·Surmount), 정해진 금액을 기계적으로 산다(토스 주식 모으기, PayPay つみたてロボ). **"나"를 기준으로 만들고 "나"와 비교하는 서비스는 찾지 못했다** (2026-10-02 조사, 영어·한국어·일본어).
- **핵심 화면: 나 카피 봇 vs 매달 그냥 사기, 그리고 "평행세계의 나".** 같은 기간·같은 종목에서 **나 카피 봇**(내 규칙을 빠짐없이 지켰다면)과 **매달 그냥 사기**(기계적 적립)를 나란히 보여주고, 내 규칙을 **한 가지씩만** 바꾼 **평행세계의 나**들(고점에도 안 쉬는 나, -20%까지 참는 나, -5%에 바로 사는 나, 떨어졌을 때만 사는 나, 비율 맞추는 나)과, 규칙은 그대로 두고 사는 종목만 바꾼 **2배로 움직이는 종목을 산 나**를 같은 일봉으로 그때그때 계산해(저장하지 않음, `application/parallel.py`) 함께 보여준다. 모두 같은 날 같은 돈을 넣고, 넣은 시점이 달라도 비교할 수 있게 **넣은 시점을 반영한 연 수익률(XIRR)**과 지금 가치만 쓴다 ("두 배로 넣은 나"는 결과가 뻔해 뺐다). 다른 나를 고르면 그 규칙으로 바꿀 수 있다. 규칙 하나의 차이는 작아 곡선이 거의 겹치므로, 비교하는 나들의 성격은 그대로 두고 눈에 띄게 다른 나로 2배 종목을 산 나를 더했다 (2026-10-17, 사용자 결정). 이 나는 같은 일봉의 하루 움직임을 2배로 하고 보수·이자로 연 2%를 뺀 가상 종목(2배 레버리지 ETF 근삿값)을 같은 규칙으로 산다. 종목을 바꾼 나라서 이 나로 바꾸기는 없고, 월간 정리에서도 뺀다. 경고 문구 없이 제목으로 사실만 적는다 (크게 떨어지는 구간이 그래프에 그대로 보인다). 평행세계 그래프는 가치가 아니라 **넣은 돈 대비 수익률(%)**로 그린다 (2026-10-17): 가치 그대로면 입금으로 늘어나는 몫이 커서 나들이 겹쳐 보인다. 0% 선이 넣은 돈 그대로다. 운영 중인 봇의 "나"는 첫 판단일부터 **지금 규칙**으로 다시 계산한 값이라 중간에 규칙을 바꿨다면 실제 기록과 다를 수 있다.
- **다음에 할 일 (`application/plan.py`, `GET /api/bots/{id}/plan`):** 과거는 평행세계가, 미래는 봇이 알려 준다. 다음 입금일(휴장이면 다음 거래일)에 종목별로 살 금액·모아 둘 금액과 이유, "이 가격 아래면 몰아 사기 / 이 가격 위면 쉬기"와 지금 가격까지의 거리, 모아 둔 돈의 내력을 홈에 보여준다. 지금 가격이 그날까지 이어진다고 보고 실제 판단과 같은 규칙 함수(`decide_basket`)로 계산하므로 규칙은 바꾸지 않는다. 다음 장에 체결될 예정 주문은 이미 쓴 돈으로 본다. 비율 맞추기(리밸런싱)는 매수 타이밍이 핵심이라 봇 규칙에는 넣지 않고 평행세계의 "비율 맞추는 나"로만 둔다.
- **평가가 아니라 구경이다.** 점수·등수·"잘했다/못했다" 문장을 붙이지 않고 "이런 나였다면 지금 이만큼"만 보여준다. "닮은 정도" 같은 성적표형 지표와 **실제 계좌와의 비교("실제 나")는 계획에서 뺐다** (2026-10-02, 사용자 결정: 압박을 주고, 실제 거래 증권사가 앱과 다른 경우가 흔하다). 그래서 증권사 연동 없이 질문만으로 쓸 수 있다.
- **쉬운 질문으로 규칙을 만든다 (`#me`, `frontend/src/me.ts`):** 한 화면에 질문 하나씩 4~6개(평소 사는 종목·비율 → 주로 어떻게 사나요(매달 / 떨어졌을 때만) → 한 달 평균 금액 → 넣는 날 → 많이 올랐을 때 → 많이 떨어졌을 때)를 고르면 `dip_saver` 값이 되고, 쉬운 말 요약과 지난 10년 "나처럼 했다면 vs 매달 그냥 샀다면"을 보여준 뒤 버튼 하나로 봇을 만들어 시작한다. 첫 화면은 무엇을 하는지(1분, 정답 없음, 계좌 연결 안 함)를 먼저 안내한다. 매도는 묻지 않고 "팔지 않아요"로 둔다. AI 자유 대화(N6)는 보류했다: 사람은 자기 투자 방식을 말로 정확히 설명하기 어려워 선택지로 고르게 하는 편이 더 정확하고 만족도도 높다.
- **복사할 수 없는 투자 (2026-10-03 결정):** 그때그때 기분이나 뉴스를 보고 사고팔거나 며칠·몇 주 단위로 자주 사고파는 투자는 규칙으로 옮길 수 없어 대상이 아니다. "매달 얼마, 많이 오르면 쉬고, 떨어지면 몰아 사기"처럼 말로 정할 수 있는 습관만 따라 하고 파는 습관은 아직 복사하지 않는다. 규칙 함수가 판단해야 백테스트와 DRY RUN이 같고(원칙 3) 재현된다(원칙 9).
- **AI의 역할은 "질문 → 규칙 값"까지다** (규칙 봇). AI가 낸 값은 정해진 규칙 틀(스키마)로 검증하고, 쉬운 말 요약과 10년 백테스트를 보여준 뒤 사람이 확정한다. **AI 봇**(14절)만 AI가 종목 비중을 판단한다. 두 경우 모두 체결·한도는 규칙·엔진이 하므로 원칙 3·9가 유지된다.
- **홈 첫 화면은 늘 나 카피 봇이다.** 나 카피 봇이 있으면 홈은 "나처럼 했을 때 vs 매달 그냥 샀다면"(넣은 돈 대비, 판정 문장 없음), 바로 아래 오늘의 판단(봇이 매일 하는 판단을 먼저 보게, 2026-10-22), 다음에 할 일, 월간 정리 한 줄, 평행세계의 나(시작한 지 1년이 안 되면 날마다, 넘으면 달마다 그린다), [자세히 보기](`#bot/{id}`, 예전 봇 화면)이고, 없으면 세 단계 소개와 [나 카피하기]다. 봇마다 주소가 따로라 뒤로 가기로 직전 봇에 돌아가고, 폰(960px 미만)에서는 맨 위 가로 칩으로 봇을 바꾼다. 큰 숫자의 기본 기간은 "시작 이후"라 봇 목록의 수익률과 같다.
- 규칙 하나하나의 차이는 작다: 실제 가격 10년 백테스트에서 QQQ +188.2% vs 매달 그냥 사기 +188.3%, VOO +105.7% vs +107.5%였고, 라쿠텐증권의 S&P500 25년 검증(적립 + 하락 시 추가 매수)도 연 0.5~0.8%p 개선에 그쳤다. 그래서 결과를 성적표가 아니라 **"이런 나였다면" 하고 가볍게 구경하는 재미**로 보여주는 편이 맞다. 작업 순서는 [roadmap.md](roadmap.md)의 "나 카피 봇" 트랙.

## 2. 첫 완성 범위 (MWP)

| 포함 | 제외 (MWP 이후) |
| --- | --- |
| 사용자 1명, 미국 상장 종목, USD, 소수점 수량(6자리, 금액 기준), 매수·매도 | 실제 계좌 주문, 공식 모의투자(토스에 없음) |
| **봇 하나가 여러 종목**(최대 10개, 모으기 전략만, 비율 합 100, 현금 공유, 2026-10-02~). 봇 여러 개를 홈 오른쪽 봇 목록에서 골라 하나씩 보기 | 봇 여러 개를 묶는 포트폴리오 위험 한도 |
| 규칙 전략 **1개**(매달 넣고 사 모으는 "나처럼 투자", 유명 전략 4종은 2026-10-08에 없앴다), 봉 주기 **1개**(일봉) | AI 전략 (마일스톤 4에서 AI 봇으로 더했다, 14절). 전략 편집기는 계획에서 뺐다 (2026-10-02) |
| 백테스트와 정기 DRY RUN이 같은 전략 함수 사용 | 실시간 시세로 판단하기, WebSocket 시세 |
| **실시간 화면 표시**: Worker가 거래 시간 중 30초마다 현재가와 진행 중 일봉을 REST로 받아 "지금 가치"와 차트의 오늘 봉(흐리게)에 반영 (판단에는 안 씀) | |
| 홈·시험해 보기·설정 화면, 시작·일시정지·중지·수동 1회 실행, 앱 안의 기록(최근 활동). 텔레그램 알림은 만들었지만 기본으로 끈다 (2026-10-02) | |
| **레버리지 ETF**(QLD·TQQQ·SOXL) 백테스트·DRY RUN: 배수 표시, 주의 안내, 이상치 기준 완화 | 레버리지 전용 위험 한도 (보유 기간·손절 등) |
| 재시작 복구, 중복 모의 주문 방지, 데이터 이상 시 주문 차단 | |

관심 목록: `VOO`, `QQQ`, `QLD`, `TQQQ`, `SOXL`, `NVDA`, `GLD`, `MAGS`, `EWY`, `EWJ` (`WATCHLIST_SYMBOLS`). Worker가 하루 한 번(새 봇의 종목처럼 정보가 없는 종목은 바로) 토스 `/stocks`로 레버리지 배수를 `instruments`에 저장하고, 배수가 1보다 크면 하루 변동 이상치 기준을 50%에서 90%로 넓힌다.

**MWP 완료 조건:** 서버에서 정기 DRY RUN이 돌고, 중복 주문 0건, 데이터 이상·API 실패 때 신규 주문 차단이 기록되며, 화면에서 현재 상태와 마지막 판단 이유를 바로 이해할 수 있다. 처음 정했던 "2주 무개입 운영"과 백업 복원 연습은 하지 않기로 했다 (2026-10-04, 사용자 결정: 운영하면서 고치고, 복원 절차는 필요할 때 만든다).

## 3. 반드시 지킬 원칙

이 프로젝트에서 틀리면 비용이 큰 것들이다. 코드 리뷰 기준으로도 쓴다.

1. **실거래 경로는 스위치 뒤에만 있다.** Worker는 `LIVE_TRADING=true`일 때만 토스 주문 어댑터(`adapters/toss/trader.py`, `Trader` 규약)를 만든다. 꺼져 있으면 실제 주문 코드가 동작할 길이 없다. 켜져 있어도 봇마다 "실제로 따라 하기"(1/100)를 켜야 하고, 한도 안의 주문은 바로 나가며 한도를 넘으면 사람이 승인한다 (아래 "Worker 평가 1회의 흐름" 12번). 나 카피 봇은 사기만 한다. AI 봇은 모의 매수 × 1/100로 사고, 모의로 판 비율만큼 이 봇이 실제로 산 수량에서 판다 (14절). 모의 체결은 `adapters/sim`과 `domain/trading.py`가 맡는다.
2. **완료된 봉만 쓴다.** 진행 중인 봉으로 판단하지 않는다. 토스는 미국 날짜 D의 일봉을 정규장 전부터 데이마켓 체결로 채워 내려주므로, **D일 정규장 마감 + 여유 시간 전의 D일 봉은 버린다.** 백테스트도 같은 규칙을 따르며, 판단 시점 이후의 데이터를 참조하면 테스트가 실패해야 한다.
3. **판단과 체결을 분리한다.** T 봉으로 판단하고 T+1 봉 규칙으로 체결한다. 백테스트와 DRY RUN이 같은 규칙을 쓴다.
4. **판단 하나에 주문은 최대 하나다.** `bot_id + symbol + bar_ts + mode`에 DB 유일 제약을 건다. Worker가 실수로 두 개 떠도 중복 주문이 생기지 않는다.
5. **모르면 멈춘다.** 데이터 누락·지연, API 오류, 장 운영 판정 불일치, DB 오류가 있으면 신규 주문 없이 이유를 기록한다. 단, Worker 재시작은 "모르는 상태"가 아니다. 평가가 멱등이고 체결가가 봉 데이터로 정해지므로, 실행 중이던 봇은 재시작 뒤 그대로 이어서 돌고 밀린 평가를 바로 처리한다 (2026-10-02: 재시작 뒤 멈춰 있던 것을 이어서 돌게 바꿨다, roadmap "운영 교훈").
6. **토스 토큰은 Worker 한 곳에서만 발급한다.** 토큰은 클라이언트당 1개만 유효해서, 두 곳에서 발급하면 서로를 무효화한다. API 서버는 토스를 호출하지 않는다.
7. **돈과 시간은 정확한 타입으로 다룬다.** 가격·금액은 `Decimal`(DB `numeric`)로 저장하고 float를 쓰지 않는다. DB 시각은 UTC로 저장하고, 장 판정은 `America/New_York`, 화면 표시는 KST로 한다.
8. **비밀값과 시세 데이터는 저장소에 넣지 않는다.** 토스 데이터는 제3자 배포가 금지돼 있다. 테스트 fixture는 합성 데이터로 만들고, 실제 응답은 로컬에서만 쓴다.
9. **재현할 수 있어야 한다.** 모든 실행·백테스트는 전략 버전, 파라미터, 데이터 범위, 비용 가정을 함께 저장한다. AI 봇(14절)은 판단마다 입력·출처·출력·모델·지침 버전을 기록하고, 기록된 판단으로 다시 돌리면 같은 결과가 나와야 한다 (AI를 다시 부르면 다를 수 있으므로 판단 자체가 재현의 원본이다).

## 4. 아키텍처

시드니 Lightsail VM 한 대에서 Docker Compose로 DB·API·Worker·Cloudflare Tunnel을 실행한다. 운영 화면은 Cloudflare Access로 본인만 접속하고, SSH 관리·예비 화면 경로는 Tailscale을 쓴다. 앱·DB 공개 인바운드 포트는 없다. 서버 준비 때 연 콘솔 SSH(22번) 차단은 아직 확인하지 않았으며 roadmap의 남은 작업이다. 데모는 같은 서버의 별도 API·DB 계정으로 공개한다.

**서버 자원 (2026-10-14 측정):** 2 vCPU, RAM 1906MB, 스왑 2GB(`bootstrap.sh`가 만든 `/swapfile`), 디스크 58GB 중 11GB 사용. 같은 서버에 ur-check와 puny-chat도 돈다. RAM은 컨테이너가 약 870MB, 시스템(dockerd·Tailscale·CI 러너 등)이 약 450MB를 쓰고 가용은 약 590MB, 스왑은 약 770MB를 쓰는 중이다 (메모리 압박 지표는 0, 로드 평균 0.1). 프로젝트별 RAM은 Trading Lab 운영 약 245MB·데모 약 200MB, puny-chat 약 310MB, ur-check 약 115MB이고, 스왑으로 밀려난 양은 Trading Lab이 약 580MB로 대부분이다 (worker가 평가 때 최대 303MB까지 올랐다가 밀려난다). `docker stats`는 스왑에 나간 메모리를 세지 않아 실제보다 작게 보이므로, 크기를 볼 때는 cgroup의 `memory.current`+`memory.swap.current`를 함께 본다. 여유가 모자라면 서버를 4GB 플랜으로 올리는 것이 가장 단순하다.

```mermaid
flowchart LR
    ME[본인 브라우저·폰] -->|HTTPS · 본인 인증| ACCESS[Cloudflare Access]
    PUBLIC[데모 방문자] -->|HTTPS| CF[Cloudflare]
    ACCESS --> CF
    ADMIN[관리 기기] -->|Tailscale SSH · 예비 HTTPS| VM
    subgraph VM[Lightsail 시드니 · 고정 IP]
        TUNNEL[cloudflared: 서버에서 밖으로 연결] --> API[api: FastAPI + React 정적 파일]
        TUNNEL --> DEMO[demo-api: 예시 데이터 · 변경 차단]
        API <--> DB[(PostgreSQL: 운영 DB + 데모 DB)]
        DEMO -->|데모 전용 계정| DB
        WORKER[worker: 수집·평가·모의체결·실주문·AI] <--> DB
    end
    CF <-->|Tunnel| TUNNEL
    WORKER -->|고정 송신 IP| TOSS[토스증권 시세·계좌·주문 API]
    WORKER --> AI[Claude: 시장분석·캔들분석]
```

### 구성 요소

| 구성 요소 | 책임 | 하지 않는 일 |
| --- | --- | --- |
| **worker** | 토스 토큰 보유, 시세·계좌 수집, 장 운영 판정, 정기 평가, 위험 검사, 모의·실제 주문과 체결 확인, AI 판단, 백테스트 실행, heartbeat | HTTP 요청 처리 |
| **api** | 화면 제공, 조회 API, 명령 기록(시작·중지·수동 실행·백테스트 요청), 설정 저장 | 토스 호출, 긴 계산 |
| **db** | 모든 상태의 원본. 봉 캐시, 설정 버전, 명령 큐, 실행·판단·주문·체결·포지션·이벤트 | — |
| **frontend** | 상태 확인과 제어. API를 주기적으로 조회 (MWP는 polling) | 비즈니스 로직 |

API와 Worker는 같은 Python 패키지를 다른 진입점으로 실행한다. 둘은 **DB를 통해서만 대화한다.** API가 `commands` 테이블에 명령을 쓰면 Worker가 읽어 처리하고 결과를 기록한다. 큐 시스템(Redis·Celery 등)은 필요해질 때까지 두지 않는다.

### 코드 구조

```text
backend/
  src/trading_lab/
    domain/          # 순수 로직: 봉, 지표, 전략, 위험 규칙, 모의 체결 규칙 (외부 의존 없음)
      broker.py      # 증권사 연결 규약(Broker)과 증권사와 무관한 시세·계좌 형식, 오류 2종
      advisor.py     # AI 판단 규약(Advisor)과 입력 요약·규칙 검사 (AI 공급자와 무관)
      candles.py     # 캔들분석 AI 봇의 익명 입력(지수화·글자)과 되돌리기
      live.py        # 실제 주문 규칙: 비율·한도·승인·일부 팔기 수량
      events.py      # 이벤트 종류·내용 형식·이유 코드 (엔진 → 알림·화면 규약)
    application/     # 유스케이스 (FastAPI를 모른다)
      dry_run.py     #   평가 1회 (엔진)
      bots.py        #   봇 관리: 만들기·설정·종목·이름·초기화·삭제·명령
      bot_status.py  #   봇 상태 계산: 종목별·실시간 평가, 마지막 판단, 자산 곡선
      queries.py     #   조회: 일봉(+진행 중 봉), 종목, 최근 활동, 기록
      research.py    #   계산해 보기: 백테스트, 평행세계, 따라 하기
      ai_judge.py    #   AI 봇 판단 1회: 비용 상한 → AI 호출 → 규칙 검사 → 기록 (14절)
      ai_view.py     #   AI 봇 화면: 오늘의 판단·기록·비용, 나 카피 봇과 비교
      journal.py     #   매매일지: 판단일마다 근거·결정·주문, 지우거나 다시 시작하기 전 보관
      live.py        #   실제로 따라 하기: 계획 → 승인 → 보내기 → 체결 확인
      messages.py    #   알림·화면 공용 문장
      errors.py      #   서비스 오류 3종 (NotFound·Invalid·Conflict)
    adapters/toss/   # 토스 HTTP 클라이언트, 토큰 관리, 응답 → domain/broker 형식 변환
    adapters/claude/ # Claude API 판단 (웹 검색·구조화 출력·요금) → domain/advisor 형식
    adapters/sim/    # 모의 브로커
    persistence/     # SQLAlchemy 모델과 이름 붙인 조회·저장 함수 (쿼리는 여기서만 만든다)
    api/             # FastAPI 진입점. routes/는 요청 해석 → 서비스 호출 → 응답 변환만 한다
    worker/          # Worker 진입점과 루프
  migrations/        # Alembic
  tests/
frontend/            # React + Vite
deploy/              # 운영용 compose, 서버 준비 스크립트, 백업 스크립트
infra/lightsail/     # Terraform: Lightsail 인스턴스·Static IP·방화벽·자동 스냅샷
compose.yaml         # 로컬 개발용 (PostgreSQL)
```

`domain`은 FastAPI, httpx, SQLAlchemy를 import하지 않는다. **쿼리는 `persistence`에서만 만든다 (2026-10-19):** `application`·`api`·`worker`는 `sqlalchemy` 본체(`select`·`func` 등)를 import하지 않고, `persistence`의 이름 붙인 함수(`first_decision_date`, `pending_orders`, `month_bought` …)를 부른다. `Session`(`sqlalchemy.orm`)과 오류(`sqlalchemy.exc`)는 쓸 수 있고, `session.get`·`add`·`commit`은 작업 단위로서 서비스가 직접 부른다. Spring식 Repository 인터페이스는 두지 않는다 (DB를 바꿀 계획이 없고 테스트도 실제 PostgreSQL로 한다). `cli.py`(운영 도구)는 예외다. 계층의 방향(`persistence`·`adapters`는 위 계층을 모르고, `application`은 `adapters`·`api`·`worker`를 모른다)도 함께 테스트한다. 토스 어댑터(`adapters/toss`)는 `adapters/brokers.py`만 import한다. Worker와 CLI는 증권사 이름(`WORKER_MARKET_SOURCE`, CLI는 `DEFAULT_BROKER`)을 `connect_broker`·`make_trader`에 넘겨 `Broker`·`Trader` 규약으로 받고, 엔진·저장소·API는 `domain/broker.py`의 규약과 형식만 안다. 두 규칙 모두 테스트(import 검사)로 강제한다 (2026-10-22). 그래서 증권사를 바꾸려면 규약을 지키는 어댑터를 만들고 `brokers.py`의 `BROKERS`에 한 줄을 더한 뒤 설정 값만 바꾸면 된다. 증권사를 여러 곳 동시에 쓰는 구조는 아니다 (`live_control.trader`와 `WORKER_MARKET_SOURCE`가 하나). 계좌 읽기 스위치 `TOSS_ACCOUNT_ENABLED`와 키 이름(`TOSS_*`)은 배포 설정을 건드리지 않으려고 그대로 두었다. **이름과 개념도 나눈다 (2026-10-04, 사용자 결정):** 엔진·저장소·API·화면 코드의 표·함수·경로 이름에 증권사 이름(toss)을 쓰지 않는다 (`broker_account`, `/api/broker-account`). 증권사별 규칙(토스 멱등 키 10분, 금액 주문 접수 시간, 오류 코드, 계좌 헤더 등)은 어댑터 안에만 두고, 엔진에는 규약의 값(접수 시간대, 멱등 유효 시간, 증권사 무관 거절 이유 코드)으로만 넘긴다. 저장 데이터에 남는 것은 출처 코드(`source`)뿐이고, 사람이 읽는 증권사 이름은 프론트엔드 `source.ts`가 정한다. 증권사 이름이 남아도 되는 곳은 어댑터, 조립 지점(Worker 진입점·CLI·설정 `TOSS_*`), 문서뿐이다.

### Worker 평가 1회의 흐름

```text
명령 확인 → 장 운영 판정 → 완료 봉 수집·검증 → 이전 대기 주문 체결(T+1 규칙)
→ 전략 판단 → 위험 검사 → 모의 주문 생성 → 상태·다음 평가 시각 저장 → heartbeat
```

1. **Worker는 하나만 동작한다.** 시작할 때 PostgreSQL advisory lock을 잡고, 못 잡으면 잡을 때까지 기다린다. 토스 토큰도 이 프로세스만 보유한다.
2. 잠금을 얻으면 `RUNNING` 봇은 그대로 두고 "이어서 실행" 이벤트를 남긴다. 텔레그램은 멈춘 동안 판단할 때가 지난 봇만 알린다 (`overdue`). `next_evaluation_at`이 지났으면 첫 tick에서 바로 평가한다. 놓친 거래일은 기존처럼 기록만 한다.
3. 15초마다 미처리 명령 → `RUNNING`이면서 `next_evaluation_at`이 지난 봇 평가 순서로 돈다. heartbeat는 따로 15초마다 남긴다 (`worker/heartbeat.py`: 한 바퀴가 AI 판단처럼 오래 걸려도 살아 있게 보이도록). 메인 루프가 10분 넘게 다음 바퀴를 시작하지 못하면 남기지 않아 멈춘 Worker를 살아 있게 보이지 않는다.
4. 평가 대상은 "정규장 마감 + 2시간이 지난 가장 최근 거래일"이다. 여러 종목 봇은 **모든 종목**의 그날 봉이 있고 판단 구간 검사를 통과해야 판단한다 (하나라도 아니면 전체를 미룬다: 현금을 함께 쓰므로 일부만 먼저 판단하면 백테스트와 순서가 달라진다). 토스 캘린더가 거래일이 아니라고 하거나, 그날 봉이 없거나, 판단 구간 봉에 누락·이상치가 있으면 판단 없이 `SKIPPED`를 남기고 15분 뒤 다시 시도한다.
5. 이전 대기 주문은 판단일 다음 거래일 시가로 체결한다. 체결·판단·주문·잔고 변경은 한 트랜잭션이다.
6. `bot_id + symbol + session_date + mode` 유일 제약과 "봇당 대기 주문 1개" 부분 유일 인덱스가 중복 모의 주문을 막는다. 같은 봉을 다시 평가하면 아무것도 하지 않는다.
7. 증권사 오류는 두 종류로만 본다. `BrokerAccessError`(허용 IP·인증, 토스 403·401 반복)와 예상하지 못한 오류는 봇을 `ERROR`로 바꾸고, 그 밖의 `BrokerError`(429·5xx·네트워크)는 `SKIPPED` 후 재시도한다. 어댑터가 httpx 오류까지 이 두 종류로 바꿔 넘긴다.
8. Worker가 멈춰 있던 동안의 거래일은 소급 판단하지 않고 `missed_sessions` 경고만 남긴다.
9. 봇 평가와 별도로 30분마다 관심 종목(`WATCHLIST_SYMBOLS`, 기본 10종목) 일봉이 최신 완료 거래일까지 있는지 보고, 뒤처진 종목만 증분 동기화한다 (백테스트 데이터 최신화). 실패는 경고만 남긴다.
10. 토스 모드에서는 하루 한 번(정보가 아직 없는 봇 종목은 바로 한 번) 관심·봇 종목 정보(레버리지 배수)를, 미국 거래 시간(뉴욕 일 20:00~금 20:00, 데이마켓 포함) 중 30초마다 봇 종목 현재가와 진행 중 일봉(`/candles` 최신 1개)을 받아 저장한다. 원/달러 매매기준율(`Broker.exchange_rate`)은 거래 시간과 상관없이 한 시간마다 `exchange_rates`에 저장한다 (W1, 화면 원화 보기). 화면 표시용이라 실패해도 로그만 남긴다.
11. **실제 증권사 계좌 읽기 (실거래 R1, 2026-10-04~):** 조립 지점이 계좌 읽기를 켜면(운영: `TOSS_ACCOUNT_ENABLED=true`, 토스 모드에서만) 1시간마다 `Broker.account_snapshot`으로 주문 가능 금액(달러·원)·보유·최근 30일 주문을 읽어 `broker_account`에 덮어쓴다. 계좌번호와 원본 응답은 저장하지 않고, 출처 코드(`source`)만 남겨 화면 이름("토스증권 계좌")은 프론트엔드가 정한다. 실패하면 마지막 값은 두고 종류(`access` 권한·허용 IP / `temporary` 일시 장애)와 시각만 적는다. 주문은 내지 않는다. **실제 계좌 대조:** 읽을 때마다 종목별로 "계좌 보유 ≥ 봇의 실제 매수·매도 체결을 합산한 순보유 수량(체결 10분 뒤부터)"인지 본다. 직접 산 주식이 섞일 수 있어 같은지가 아니라 적지 않은지만 본다. 적으면 맞을 때까지 새 실제 주문을 모두 승인을 받고 내며, 결과가 바뀔 때만 `live_reconcile`로 알린다. **조회 타이밍:** 정기 조회는 방치형 운영과 드문 입금 주기를 고려해 1시간으로 둔다. 봇의 주문 접수·UNKNOWN 주문 식별·부분 체결량 변화·체결/취소/거절 확인 뒤에는 같은 Worker 루프에서 계좌를 추가 조회한다. 한 루프의 여러 주문 변화는 조회 한 번으로 모은다. 주문 뒤 조회 실패는 요청을 유지해 최소 1분 간격으로, 일반 정기 조회 실패는 1시간 뒤 다시 시도한다. Worker 재시작 때도 첫 루프에서 읽는다. 화면은 DB에 저장된 값을 30초마다 확인하며 직접 증권사를 호출하지 않는다. 직접 입금·수동 거래는 정상 동작 시 다음 1시간 조회와 화면 갱신 뒤 보이고, 봇 주문은 증권사 반영 및 체결 확인(1분 주기) 뒤에 보인다. Worker 지연·증권사 장애 때는 더 늦을 수 있으므로 마지막 조회 시각을 함께 보여준다.
12. **실제로 따라 사기 (실거래 R2, 2026-10-04~, `application/live.py`):** 매 tick마다 (1) 따라 사기를 켠 봇(`bots.live_ratio`, 켠 뒤의 모의 매수만)의 새 모의 매수마다 실제 주문을 하나 만든다: 금액 = 모의 매수 예산 × 비율(센트 아래 버림), 낼 날 = 판단 다음 거래일. 레버리지 종목·비상 중지면 건너뛰고, $1 미만이면 버리지 않고 모아 두었다가(`reason=carried`) 같은 종목 다음 주문에 더해 $1이 넘으면 함께 산다(`carried_into`), 봇 한도(1건 $20·봇마다 한 달 $50)를 넘거나 실제 계좌 대조에 부족이 있으면 승인을 기다린다 (한도 안의 주문은 묻지 않는다). **계좌 전체 상한:** 모든 봇을 합쳐 한 달 $100(`LiveLimits.account_month`)은 승인해도 넘을 수 없다. 만들 때 넘으면 `account_limit`으로 넘기고, 승인하려 할 때도 다시 따져 거절한다 (2026-10-09). (2) `Trader.order_window`가 열리고 5분 뒤 `SENDING`으로 먼저 적고(commit) `place_amount_buy`로 보낸다. 결과를 모르면 `Trader.idempotency_window` 안에서만 같은 키로 다시 보내고, 그 뒤에는 `find_orders`로 찾으며 하나로 확정하지 못하면 `UNKNOWN`. **불명 주문이 하나라도 남으면 계좌 전체 신규 실제 주문 생성·전송·승인을 막고 매수 금액을 원래 거래일의 월 한도에 계속 예약한다** (삭제한 봇·지난달 주문도 차단 대상). 같은 전송 묶음의 다음 주문도 다시 확인하며, 이미 보낸 주문의 체결 조회는 계속한다. 불명 주문은 1분마다 조회만 하며 재전송하지 않는다. 부분 체결 뒤 취소된 매수는 체결 금액을 월 한도에 남긴다. 창이 닫히면 놓친 주문은 넘긴다. **달러 부족:** 주문을 만들 때 마지막으로 읽은 달러 잔고와 그날 주문 합계를 비교해 모자라면 미리 알리고(`live_funds`), 보내기 직전 `Trader.available_cash`로 다시 확인해 모자라면 보내지 않고 넘긴다(`no_funds`, 다음 달에 더하지 않음). 잔고를 읽지 못하면(네트워크·인증 오류) 보내지 않고 다음 tick에 다시 묻는다. 접수 시간이 끝날 때까지 못 읽으면 놓친 주문(`missed`)으로 넘긴다 (2026-10-09, 예전에는 못 읽어도 그대로 보냈다). (3) 보낸 주문은 1분마다 `get_order`로 체결을 확인한다. 체결·거절·취소·확인 불가는 그대로 기록한다. 이벤트 `live_order`로 알림(승인 요청·체결·문제). 실패해도 모의 판단과 무관하다.
13. **AI 봇 판단 (마일스톤 4, 2026-10-06~, `application/ai_judge.py`):** AI 봇을 평가할 때 그날 판단 기록이 없으면 평가를 되돌리고, 봇 행을 잠그지 않은 채 조립 지점이 넘긴 `Advisor`(Claude)를 불러 판단을 `ai_judgments`에 적은 뒤 다시 평가한다. 판단은 `trading.rebalance`가 팔 금액·살 금액으로 바꾼다. 실패·형식 오류·비용 상한이면 그날은 그대로 둔다 (14절).

봇 상태(`STOPPED`, `RUNNING`, `PAUSED`, `ERROR`)는 Worker 프로세스의 생존과 별개다. 명령: `START`(→ RUNNING, 즉시 1회 평가), `PAUSE`(RUNNING → PAUSED), `STOP`, `RUN_ONCE`(상태는 그대로 두고 1회 평가). 화면에는 "멈추기(`PAUSE`) / 시작(`START`)"만 둔다. `STOP`과 `RUN_ONCE`는 일반 사용자에게 차이가 없거나(판단은 하루 한 번 자동) 헷갈려서 API·CLI에만 남긴다. 화면에서는 `PAUSED`와 `STOPPED`를 모두 "멈춤"으로 보여준다.

판단·체결 함수(`domain/trading.py`)는 백테스트와 Worker가 함께 쓴다. `replay` CLI로 과거 거래일마다 정기 평가를 재생해 백테스트와 체결이 같은지 확인한다.

### 결과 불명 주문 확인 (2026-10-10)

화면 상단의 **확인 필요 카드**는 최근 20건 밖의 주문과 삭제한 봇의 주문도 보여 준다. 비상 중지 해제나 승인은 UNKNOWN 차단을 우회하지 못한다. Worker가 종목·방향·금액(매도는 수량)·접수 시각을 대조해 증권사 주문을 하나로 찾으면 체결 조회로 이어가고 차단을 푼다. 다른 기록에 이미 연결된 주문 번호는 재사용하지 않는다.

- **주문 번호 입력:** 증권사 앱에서 확인한 번호를 입력한다. 번호는 조회의 단서이고, 입력만으로 차단을 풀거나 체결로 만들지 않는다. Worker가 같은 조건의 주문을 조회로 확인해야 한다. 잘못된 번호나 조회 오류·여러 후보면 계속 막는다.
- **미접수 확인:** 증권사 앱의 주문 내역과 보유를 모두 확인해 접수·체결되지 않은 것이 확실할 때만 확인창을 통해 정리한다. 이 주문은 `SKIPPED / confirmed_not_placed`로 남겨 재전송하지 않고 예약 금액을 해제한다. 확인할 수 없으면 그대로 둔다. 사람이 잘못 확인하면 안전장치를 풀 수 있다는 한계가 있다.
- 정리는 `POST /api/live-orders/{id}/resolve` (`confirmed: true`, `broker_order_id`: 확인한 번호 또는 미접수의 `null`)로 요청한다. API는 DB만 바꾸고 증권사는 Worker만 부른다. 수동 확인과 조회 복구는 이벤트에 기록한다.
- 차단이 풀린 뒤에도 다른 UNKNOWN과 비상 중지 상태를 확인한다. 대기 주문은 원래 접수 시간 안에서만 진행하고, 시간이 지났으면 넘긴다. 놓친 주문을 새 날짜로 옮기지 않는다.
- 일부 체결 뒤 취소된 매수도 체결 금액을 월 한도에 남긴다. 체결 수량은 있지만 금액이 없으면 원래 주문 금액을 보수적으로 예약한다.

### 연결이 끊겼을 때 (2026-10-19)

- **주문 전:** 잔고·접수 시간을 묻지 못하면 보내지 않고 다음 tick에 다시 묻는다. 끝까지 못 물으면 놓친 주문(`missed`)이다.
- **주문 중:** 결과를 모르면 `SENDING`으로 두고 같은 키로 다시 보내거나(멱등 시간 안) 조회로 찾는다(그 뒤). 조회도 못 하면 `SENDING`/`SENT`로 남아 연결되면 이어진다.
- **알림:** 연결이 안 돼 3분 넘게 보낸 결과(`SENDING`)나 체결(`SENT`)을 확인하지 못하면 주문마다 한 번 `live_order`(`stalled`)로 알린다. 차단은 `UNKNOWN`이 될 때만 건다. 중복 알림 방지는 메모리라 Worker를 다시 켜면 한 번 더 올 수 있다.
- **Worker 루프:** 예상하지 못한 오류가 나도 프로세스는 죽지 않고 다음 주기에 다시 한다(외부 heartbeat만 건너뛰어 지속되면 감시가 알린다). 알 수 없는 명령은 `REJECTED`로 넘긴다.
- **API:** 예상하지 못한 오류도 `{"detail"}` 모양의 500으로 돌려준다. 일봉이 없을 때의 오류(`NoData`)는 400이다.

### 핵심 데이터

| 테이블 | 내용 |
| --- | --- |
| `daily_bars` | `(symbol, session_date)` PK, 미국 거래일 기준. OHLCV(`numeric`, 정밀도 제한 없음, 수정주가), `source`, `fetched_at`. 1분봉은 필요해질 때 별도 테이블 |
| `bots` | 대표 종목(`symbol`, 첫 종목)과 종목·비율 목록(`symbols`, JSONB `[{symbol, weight}]`), 전략 이름·파라미터, 상태·사유, 초기 현금, 수수료·슬리피지, 위험 한도, `next_evaluation_at` |
| `bot_accounts` | 봇의 모의 현금·실현 손익·**넣은 돈**(`contributed`, 시작 금액 + 입금, 수익률의 기준)·모아 둔 돈(`reserve`, 모으기 전략이 고점 때 쌓아 두고 하락장에만 쓰는 현금) (실제 토스 계좌와 무관) |
| `bot_deposits` | 모으기 전략의 정기 입금. `(bot_id, month)` PK로 한 달 한 번 |
| `bot_positions` | 봇의 종목별 보유 수량(소수점 6자리)·평균 단가(수수료 포함). `(bot_id, symbol)` PK |
| `commands` | 화면 명령 큐 (`START`, `PAUSE`, `STOP`, `RUN_ONCE`), 처리 시각·결과 |
| `runs` | 평가 1회: 계기(정기·수동), 대상 거래일, `OK`·`SKIPPED`·`ERROR`, 사유 |
| `decisions` | 판단·사유·지표·차단 사유, **당시 전략·비용·위험 한도 스냅샷**. 유일 키 `bot_id + symbol + session_date + mode` |
| `sim_orders` | 모의 주문(판단당 최대 1개, 종목 `symbol`, **봇·종목당 대기 주문 1개**): `PENDING` → `FILLED`·`UNFILLED`, 체결일·수량·가격·수수료·실현 손익, 모으기 매수 예산(`budget`, 없으면 현금 전부) |
| `backtests` | 입력 조건(여러 종목이면 `symbols`에 종목·비율, 데이터 범위, 전략·파라미터, 비용, 위험 한도, 코드 버전)과 지표·체결·판단·자산 곡선 |
| `events` | 심각도별 기록 (텔레그램 알림·최근 활동의 원본). 종류(`EventKind`)와 종류별 `data` 형식, 판단을 미룬·멈춘 이유 코드는 `domain/events.py`가 정한다. 알림 문장은 `data`만 읽고 `message`(로그 원문)는 해석하지 않는다. 모든 종류가 문장으로 바뀌는지 테스트가 확인한다 |
| `instruments` | 종목명, 유형, 레버리지 배수 (토스 `/stocks`, 하루 한 번 + 새 종목은 바로) |
| `quotes` | 종목별 최신 현재가 1행 (`price`, `quoted_at`). 화면 "지금 가치"용, 판단에는 안 씀 |
| `exchange_rates` | 통화 쌍(`base`·`quote`)마다 최신 환율 1행: 매매기준율(화면 환산), 살 때 환율(참고), 시각, 출처 코드. 판단·주문·저장 금액은 늘 달러이고 원화는 화면에서 바꿔 보기만 한다 (W1) |
| `live_orders` | 실제 주문 (실거래 R2). 모의 매수 1건에 최대 하나(`sim_order_id` 유일), 중복 방지 키(`key`, 판단 키에서 만듦) 유일. 상태 `WAITING_APPROVAL`→`APPROVED`→`SENDING`(보내기 전에 먼저 적음)→`SENT`→`FILLED`, 또는 `SKIPPED`·`REJECTED`·`CANCELED`·`UNKNOWN`. 이유 코드, 증권사 주문 번호, 출처 코드, 체결 수량·금액. 봇을 지우거나 다시 시작해도 남는다(연결만 비움) |
| `live_control` | 실거래 전체 상태 1행: 비상 중지, Worker에 주문 어댑터가 있는지(출처 코드, 꺼지면 NULL), 실제 계좌 대조 결과(`shortfall`: 보유가 봇이 산 수량보다 적은 종목, `checked_at`) |
| `notify_settings` | 텔레그램 알림 설정 1행: 켜기, 범위(`live` 실제 주문만 / `all`), Worker에 토큰이 있는지 |
| `broker_account` | 실제 증권사 계좌를 마지막으로 읽은 결과 1행 (실거래 R1): 출처 코드, 주문 가능 금액(달러·원), 보유·최근 주문(JSONB, 금액은 문자열), 읽은 시각, 마지막 실패 종류. 모의 봇 기록과 섞지 않는다 |
| `live_bars` | 종목별 진행 중 일봉 1행. API `/bars`가 완료 봉보다 새 날짜일 때만 `live: true`로 끝에 붙인다. `daily_bars`와 섞지 않는다 |
| `ai_judgments` | AI 판단 기록 (마일스톤 4, 14절). 봇·판단일마다 1행(유일), 지우지 않는다. 전략(`ai_judge`·`ai_candle`, 한 달 비용 상한을 따로 센다), 결과(`OK`·`FAILED`·`INVALID`·`OVER_BUDGET`), 넘긴 입력 요약, 목표 비중(현금은 `CASH`)·이유·시장 요약, 검색한 말·출처(주소·제목), 모델·지침 버전·출처 코드, 토큰·검색 횟수·비용, 실패 이유. 매매일지용 한 문장(`decision`)과 근거(`basis`, 지침 2026-10-22부터). 시험 판단(CLI)은 봇 없이 |
| `journal_archives` | 보관한 매매일지 (2026-10-22). 봇을 지우거나(`DELETED`) 처음부터 다시 시작하기(`RESET`) 직전의 일지를 그때 만든 모양 그대로(`days` JSONB) 1행에 남긴다. 봇 이름·전략·기간. 지우지 않고, 봇을 지우면 연결만 비운다 (판단·모의 주문 원본은 예전처럼 지운다) |
| `worker_heartbeat` | Worker 마지막 생존 시각, 버전 |

## 5. 기술 스택

| 영역 | 선택 | 이유 |
| --- | --- | --- |
| 언어·패키지 | Python 3.14, **uv** | 빠른 설치와 잠금 파일 (`backend/.python-version`) |
| API | FastAPI, Pydantic v2, pydantic-settings | 타입 기반 검증, 설정 분리 |
| DB 접근 | SQLAlchemy 2.0, Alembic, psycopg 3 | 마이그레이션 관리, `numeric` ↔ `Decimal` |
| HTTP | httpx (동기 클라이언트로 시작) | Worker는 단일 루프. 비동기는 필요할 때 |
| 데이터 처리 | 순수 Python·Decimal, pandas·matplotlib | 지표·체결 계산은 순수 로직, pandas는 거래소 달력 어댑터, matplotlib는 익명 캔들 차트 생성 |
| 시장 달력 | `exchange_calendars` (XNYS) + 토스 캘린더 | 토스는 3영업일만 제공 |
| 테스트·품질 | pytest, respx(HTTP 목, Phase 2), ruff, mypy(strict) | Windows에서는 `python -m mypy`로 실행 |
| DB | PostgreSQL 17 (로컬·운영 모두 컨테이너) | 같은 버전으로 개발·운영 |
| 프론트엔드 | React, TypeScript, Vite, oxlint, TanStack Query·Lightweight Charts(Phase 4) | polling·캐시, 금융 차트 |
| 실행 | Docker Compose | 로컬 → Lightsail → OCI/홈서버로 그대로 이동 |
| 접근 | **`https://app.trading-lab.me`** (Cloudflare Tunnel + Access, 본인 이메일만, 2026-10-03~). Tailscale(`tailscale serve`)은 관리용·예비 경로로 남긴다 (6절) | 앱·DB 공개 포트 0개, MWP에 로그인 구현 불필요 |
| AI | Anthropic Python SDK. 시장분석 AI 봇은 Claude Sonnet 5.5(웹 검색 서버 도구), 캔들분석 AI 봇은 Claude Opus 5.5(검색 없음), 둘 다 JSON 스키마 출력 | AI 봇 판단 (14절). Worker만 호출 |
| CI | GitHub Actions (`.github/workflows/ci.yml`): ruff, mypy, pytest(+PostgreSQL 17 서비스), oxlint, tsc·vite build | `dev`를 향한 PR에서만 돈다. 문서·인프라만 바뀌면 건너뛴다. 월 2,000분 한도를 아끼려고 같은 코드를 두 번 돌리지 않으며(2026-10-14), backend와 frontend는 한 잡이다 (잡마다 분 단위로 올림해 과금) |

## 6. 인프라와 운영

### 운영 환경

| 항목 | 선택 |
| --- | --- |
| 서버 | AWS Lightsail **시드니(ap-southeast-2), 2GB RAM / 2 vCPU**, Ubuntu 24.04 LTS. **리전 결정 (2026-10-08, 사용자):** 서울이 아니라 시드니로 간다. 사용자의 AWS 계정은 기존 방식(루트·IAM 사용자 로그인)이 안 돼 새 가입 방식 "Sign up for AWS (new)"(2026-09 출시, 콘솔에 `assumed-role/AccountFullAccessRole`로 보임, CLI는 `aws login`)만 쓴다. 이 방식은 프로젝트 하나가 AWS 계정 하나이고, **연락처 주소의 국가로 리전이 정해진다: 한국·일본 등 아시아 태평양은 시드니(`ap-southeast-2`), 미국은 오하이오, 유럽은 스톡홀름만** 되며 주소를 바꿔도 리전은 안 바뀐다 ([AWS Regions for your projects](https://docs.aws.amazon.com/accounts/latest/reference/project-regions.html)). 서울 등 다른 리전은 "고급 기능 활성화"(무료, 되돌릴 수 없음, 유료 플랜 필요)나 기존 방식 가입으로만 쓸 수 있고, 시드니의 리소스는 자동으로 옮겨지지 않는다 ([Activate advanced AWS features](https://docs.aws.amazon.com/accounts/latest/reference/activate-advanced-features.html)). Lightsail·EC2·IAM·CloudFormation은 새 방식에서 지원된다 ([지원 서비스](https://docs.aws.amazon.com/accounts/latest/reference/supported-services-sign-up-new.html)). 토스까지 지연이 늘지만(서울 약 5ms → 시드니 약 150ms) 하루 한 번 판단하는 구조라 동작에는 영향이 없다. **무료 플랜 주의:** 무료 플랜은 가입 후 최대 6개월 또는 크레딧($100~200)이 다 닳을 때까지만이고, 끝나면 유예(약 90일) 뒤 계정이 닫혀 자원이 지워진다. 24시간 도는 Worker가 있으므로 **유료 플랜으로 올려 두어야 한다.** 과거 AWS 계정이 있으면 무료 크레딧 대상이 아닐 수 있다 (가입 화면에서 확인). 유료 플랜의 프로젝트별 월 지출 한도(최소 월 $20)는 넘으면 **프로젝트를 멈춘다(Worker도 멈춤)**. 한도는 예상 비용(Lightsail 약 $12 + 스냅샷)보다 넉넉히($30 이상) 잡는다. 고급 기능을 활성화하면 이 지출 한도는 사라진다 |
| 비용 | 약 $12/월 (공인 IPv4 포함 번들. 시드니 가격은 서울과 조금 다를 수 있어 생성 시 확인). Tailscale·GitHub 비공개 저장소는 무료 |
| 고정 IP | Lightsail Static IP를 붙이고 그 IP를 토스 허용 IP에 등록 |
| 방화벽 | 처음엔 Lightsail 콘솔 브라우저 SSH(22번, 콘솔 대역만)만 허용. Tailscale SSH가 동작하면 인바운드 전부 차단. **지금 (2026-10-21):** 22번(콘솔 대역만)과 같은 서버의 Puny Chat이 쓰는 80·443(모두 허용)이 열려 있다. 80·443은 콘솔에서 먼저 열렸고 `infra/lightsail/main.tf`를 실제에 맞췄다 (빼고 apply하면 Puny Chat이 끊긴다) |
| 비밀값 | **저장소 안 `.secrets/`** (`.gitignore`·`.dockerignore`로 제외, 로컬·서버 같은 위치): `env`(DB 비밀번호·`DATABASE_URL`, 부트스트랩이 생성. 선택으로 오류 보고용 `SENTRY_DSN`을 넣는다: 운영 api·worker가 읽고, 데모는 `demo.env`를 써서 보내지 않는다)와 `worker.env`(토스 키·`TOSS_ACCOUNT_ENABLED`·`LIVE_TRADING`·Claude 키 `ANTHROPIC_API_KEY`·텔레그램·`HEARTBEAT_PING_URL`, **worker 컨테이너에만** 주입). 둘 다 권한 600. 개발용 실행은 루트 `.env`를 쓴다. **토스 키 만료 2027-09-28** (발급 2026-09-28, 1년). 만료 전 WTS에서 재발급하고 `worker.env` 교체 |
| 서버 생성 | Terraform(`infra/lightsail`). 콘솔에서 손으로 만들지 않는다 |
| 배포 | **이미지는 CI가 만든다 (2026-10-08, GHCR):** `main`에 push되면(CI는 작업 PR에서 이미 돌았으므로 다시 돌지 않는다, 2026-10-14) `.github/workflows/deploy.yml`이 ① GitHub 호스팅 러너에서 이미지를 빌드해(프론트 포함 단일 이미지, `linux/amd64`) `ghcr.io/ottuck/trading-lab`에 커밋 해시와 `latest` 태그로 올리고 ② 운영 서버(Lightsail 시드니)의 self-hosted 러너(Linux, 라벨 `trading-lab`, systemd 서비스, 밖으로만 연결)가 받아 둔 코드(`SRC`)와 비밀값 폴더(저장소 변수 `DEPLOY_SECRETS_DIR` → `SECRETS_DIR`, Compose의 `env_file`이 이것을 읽음)로 `bash deploy/deploy.sh`를 실행한다. `deploy.sh`는 이미지를 `pull`해서 `compose up -d`만 한다 (서버에서 빌드하지 않는다. 서버는 `TAG`로 받을 버전을 정하고, 롤백은 `TAG=<이전 커밋 해시> bash deploy/deploy.sh`). 비공개 이미지라 받기 전에 작업 안에서 `GITHUB_TOKEN`으로 `docker login ghcr.io`를 하고 끝나면 로그아웃한다 (서버에 토큰을 남기지 않는다). 그다음 `/api/health`를 확인한다. 봇이 판단 중(AI 판단 포함)이면 `deploy.sh`가 Worker를 다시 띄우기 직전에 `/api/health`의 `evaluating`(30분 안에 시작한 `RUNNING` 실행이 있는지)을 보고 끝날 때까지 기다린다 (최대 60분, 2026-10-09에 시간대 기준 17:45~19:30 대기를 바꿨다). 문서·인프라만 바뀐 push는 배포도 건너뛴다 (2026-10-14). 서버의 안 쓰는 옛 이미지는 `deploy.sh`가 운영 배포 끝에 `docker image prune`으로 지운다 (하루 안에 받은 것은 남김, 같은 서버의 다른 프로젝트 이미지는 건드리지 않게 CI가 붙인 `org.opencontainers.image.source` 라벨로 이 이미지만 좁힌다, 2026-10-19). GHCR의 오래된 이미지는 배포 뒤 `cleanup` 작업(`actions/delete-package-versions`, 분을 아끼려고 서버 러너에서 돈다)이 최근 30개 버전(약 10번 배포)만 남기고 지운다 (실패해도 배포는 그대로, 롤백은 이 범위 안에서만 된다). ARM 서버로 옮길 때의 문제는 6절 "이전 계획"에 적어 두었다. 운영 배포 다음에 데모도 **같은 커밋의 이미지로 자동 배포**한다 (2026-10-09). 데모 배포가 실패해도 운영은 유지되므로 데모 단계 결과는 따로 확인한다. `bash deploy/deploy.sh demo`는 수동 재배포 경로다. `index.html`은 `no-cache`, 해시 붙은 `assets/`는 오래 캐시해 배포 뒤 바로 새 화면이 보인다. Actions는 체크아웃한 코드 경로(`SRC`)를 배포 스크립트에 넘긴다. Compose 프로젝트 이름은 `quant-lab-prod`. 컨테이너 로그는 `x-logging`으로 파일 3개(10MB씩)까지만 보관한다 (2026-10-21, 모든 컨테이너 로그 합계 30MB를 측정하고 UR Check·모니터링과 같은 값으로 맞춤. 다음 배포 때 컨테이너가 다시 만들어지며 적용된다) |
| 마이그레이션 | `migrate` 일회성 서비스가 성공해야 api·worker가 시작 (`depends_on: service_completed_successfully`) |
| 백업 | `deploy/backup.sh`를 cron이 매일 03:00 UTC(12:00 KST, 평가 시각과 겹치지 않음)에 실행, `pg_dump` 7일 보관 + Lightsail 자동 스냅샷. **운영 배포 직전에도 `deploy.sh`가 같은 스크립트로 덤프를 남긴다** (마이그레이션이 DB를 바꾸기 전, 2026-10-19). 비밀값 폴더의 `backups/`에 7일 보관하고, 덤프가 실패하면 배포하지 않는다 (DB가 아직 없는 첫 배포는 건너뛰고, 급하면 `SKIP_BACKUP=1`). 덤프가 반쪽으로 남지 않게 임시 파일에 쓴 뒤 옮긴다 |
| 모니터링 | 화면의 Worker 상태: 마지막 heartbeat가 45초 안이면 살아 있다. **잘 돌 때는 아무것도 보이지 않고, 멈췄거나 서버에 닿지 않을 때만** 위 점과 화면 맨 위 한 줄("프로그램이 멈췄어요 (3분 전)")로 알린다. 그 밖에 마지막 실행 표시, `docker compose logs`, 앱의 기록(최근 활동·전체 기록 서랍). **텔레그램 알림**은 화면 설정에서 켜고 범위를 고른다 (9절). 켜면 Worker가 `events` 테이블을 따라가며 보내고, 매주 마지막 거래일 판단 뒤에는 **주간 리포트**(이번 주 자산 변화(입금 제외), 그냥 보유 대비, 거래 횟수)를 보낸다. 아무것도 하지 않는 날의 일일 점검과 월급 입금은 앱 기록에만 남긴다. 한 번에 생긴 소식은 한 통으로 묶는다(3,800자 넘으면 나눔). 알림 실패는 판단에 영향이 없다. **외부 heartbeat**: `HEARTBEAT_PING_URL`(Healthchecks.io 등)에 5분마다 신호를 보내 Worker·서버가 멈추면 외부 서비스가 알린다. **반복 오류 로그**: Worker 주기와 실제 주문 처리에서 같은 오류(같은 곳, 같은 종류)가 되풀이되면 처음 한 번과 그 뒤 1시간마다만 스택과 함께 ERROR로 남기고, 그 사이는 한 줄 WARNING, 성공하면 몇 번 반복됐는지 INFO로 남긴다 (`worker/repeat_log.py`, 2026-10-21, 오류 수집 서비스 한도와 로그 용량을 아끼려고). **오류 보고 (Sentry, 2026-10-23)**: `SENTRY_DSN`이 있으면 ERROR로 남긴 로그(API의 500은 uvicorn이 ERROR로 남긴다)와 처리 안 된 예외를 Sentry(Cloud 무료, 프로젝트 `quant-lab`)로 보낸다. 없으면 꺼진다. 보내는 것은 오류 종류·스택(파일·함수·줄 번호)·짧은 메시지 300자뿐이고, 지역 변수·소스 코드 줄·요청·사용자·breadcrumb·로그의 추가 값·서버 이름·SQL과 그 값은 보내지 않는다. 메시지에 든 토큰·키·URL의 계정 정보·이메일·9자리 이상 숫자(계좌 번호 등)는 가린다. 같은 오류(같은 예외 종류, 같은 위치)는 한 시간에 한 번만 보낸다(무료 한도 월 5,000건 보호). 릴리스는 이미지에 넣은 커밋 해시(`GIT_SHA`→`SENTRY_RELEASE`)다. 주문·판단 동작에는 관여하지 않는다 (`adapters/error_reporting.py`) |

**Healthchecks 알림을 한국어로** (선택, 사용자가 Healthchecks 화면에서 설정): 기본 HealthchecksBot 메시지는 영어라, Integrations → Webhook으로 우리 텔레그램 봇이 직접 보내게 할 수 있다. 대가로 텔레그램 봇 토큰을 Healthchecks에 저장하게 된다 (이 봇은 내 채팅에 메시지만 보낼 수 있어 유출 영향은 작다). 설정 후 HealthchecksBot 연동은 지운다.

| 항목 | 값 |
| --- | --- |
| URL (down·up 공통) | `https://api.telegram.org/bot<봇 토큰>/sendMessage`, 방식 `POST` |
| 헤더 | `Content-Type: application/json` |
| down 본문 | `{"chat_id": "<채팅 ID>", "text": "⚠️ Trading Lab 프로그램이 응답하지 않아요\n20분 넘게 신호가 없어요. 서버가 꺼졌는지 확인해 주세요."}` |
| up 본문 | `{"chat_id": "<채팅 ID>", "text": "✅ Trading Lab 프로그램이 다시 응답해요"}` |

서버 리소스는 처음부터 Terraform으로 관리한다. 이미지는 CI가 GHCR에 올리고, 운영 배포는 위 "배포" 항목처럼 서버의 self-hosted 러너가 받아서 띄운다. 서버를 옮기면 그 서버에 러너만 다시 등록한다.

**서버 준비 절차** (Terraform과 스크립트로 재현한다):

| 단계 | 누가 | 작업 |
| --- | --- | --- |
| 1. AWS 자격 증명 | 사용자 | 개발 PC에서 `aws login`(AWS CLI 2.32 이상, 브라우저 로그인으로 12시간짜리 임시 자격 증명, 액세스 키를 만들지 않는다)을 실행하고 리전은 `ap-southeast-2`로 둔다. 키·토큰은 Claude·저장소에 넘기지 않는다. Terraform이 이 자격 증명을 읽는지는 `terraform plan`으로 확인하고, 안 되면 `aws configure export-credentials --format env`로 환경변수를 내보낸다 |
| 2. 서버 생성 | 사용자 실행 | `cd infra/lightsail && terraform init && terraform plan && terraform apply` → 인스턴스(시드니 2GB, Ubuntu 24.04), Static IP, 자동 스냅샷, 방화벽(브라우저 SSH만). 출력된 `static_ip`를 메모 |
| 3. 토스 허용 IP | 사용자 | WTS > 설정 > Open API > 허용 IP에 `static_ip` 추가 |
| 4. Tailscale 먼저 | 사용자 | Lightsail 콘솔의 브라우저 SSH에서 `curl -fsSL https://tailscale.com/install.sh \| sh && sudo tailscale up --ssh --hostname quant-lab` → 링크로 로그인. 개발 PC에도 Tailscale 설치·로그인 |
| 5. 원격 작업 | Claude (개발 PC → `tailscale ssh ubuntu@quant-lab`) | deploy key 생성 → `gh repo deploy-key add`(읽기 전용) → `git clone` → `sudo bash deploy/bootstrap.sh` → `sudo tailscale serve --bg 8000` |
| 6. 토스 키·알림 | 사용자 | `.secrets/worker.env`에 토스 키, 텔레그램 토큰·채팅 ID, `HEARTBEAT_PING_URL` 입력 (`tailscale ssh` 또는 브라우저 SSH, 키는 대화에 붙이지 않음) |
| 7. Tailscale 접근 제한 | 사용자 | 필요하면 Tailscale ACL에서 서버 접근을 본인 기기로만 제한 (개인 tailnet이면 기본값으로 충분) |
| 8. 배포·봇 시작 | 서버 | 로컬에서 토스를 호출하는 프로세스를 모두 멈춘 뒤 `bash deploy/deploy.sh` → `docker compose -f deploy/compose.prod.yaml exec api python -m trading_lab.cli bot create my-copy QQQ --params deposit=1000 --cash 1000` → 화면에서 시작 |

브라우저 SSH용 22번 포트(Lightsail 콘솔 대역만)는 Tailscale SSH가 동작하면 `aws_lightsail_instance_public_ports`에서 지워 인바운드를 모두 닫는다. Terraform 상태 파일(`*.tfstate`)은 개발 PC에만 두고 Git에 넣지 않는다.

### 도메인과 바깥 접속 (마일스톤 2, 2026-10-02 결정)

운영 화면은 폰·다른 PC에서 Tailscale 앱 없이도 **도메인 + Cloudflare Tunnel + Cloudflare Access(이메일 인증)**로 접속한다. 여전히 **본인만** 쓰는 구성이다 (토스 데이터는 제3자에게 보여줄 수 없다, tossApi.md 1절). 누구나 쓰는 서비스는 하지 않는다 (12절).

| 항목 | 내용 |
| --- | --- |
| 도메인 | Cloudflare Registrar 또는 다른 등록 업체에서 구매하고 DNS를 Cloudflare에 둔다. 비용은 연 $10~15 정도 (구매 시 확인) |
| Tunnel | `cloudflared` 컨테이너를 운영 Compose에 추가해 서버에서 Cloudflare로 **밖으로만** 연결한다. 공개 인바운드 포트는 계속 0개, api는 지금처럼 127.0.0.1(컨테이너 네트워크)만 듣는다. Tunnel 토큰은 `.secrets/cloudflared.env` |
| Access | 앱 앞에 Access 정책을 두고 **본인 이메일 한 개만** 허용 (이메일로 받은 일회용 코드로 로그인). 화면에 로그인을 따로 만들지 않는다. 세션 유지 기간은 길게(예: 1개월) 잡아 PWA로 열 때 자주 묻지 않게 한다. 무료 플랜 범위(사용자 수 한도)는 착수 시 확인 |
| SSH | 서버 관리용 SSH는 Tailscale을 그대로 쓴다. 화면 접속만 옮긴 뒤 Tailscale을 완전히 뺄지는 그때 정한다 |
| API 이중 확인 | Access가 막지만 정책 실수로 열리는 일에 대비해, api가 **Cloudflare를 거쳐 온 요청(`cf-ray` 헤더)**은 Access 토큰(`Cf-Access-Jwt-Assertion` 헤더 또는 `CF_Authorization` 쿠키, RS256)을 팀 공개 키와 AUD 태그로 확인하고 없으면 403 (`api/access.py`). Tailscale로 온 요청은 그대로 둔다. **다른 사이트가 사용자의 브라우저로 보낸 바꾸기 요청도 거절한다 (2026-10-19):** POST·PUT·DELETE에 브라우저가 붙이는 `Sec-Fetch-Site`가 `same-origin`·`none`이 아니면(`cross-site`·`same-site`) 403이다. 주문 승인·비상 중지 같은 요청에 본문이 없어도 다른 사이트의 웹 페이지가 대신 보내지 못하게 하는 장치이고, 헤더가 없는 curl·서버끼리의 호출은 통과한다. `.secrets/env`에 `CF_ACCESS_TEAM`·`CF_ACCESS_AUD`가 있을 때만 켜진다. **Access 로그인은 되는데 화면에 `{"detail":"로그인이 필요해요"}`가 나오면** `CF_ACCESS_AUD`가 지금 Access 앱의 AUD 태그와 다른 것이다 (2026-10-04에 겪음: 로그인 페이지 주소의 `kid` 값이 AUD). `.secrets/env`를 고치고 `api`만 다시 띄운다 |
| PWA | Access 뒤에서는 매니페스트 요청에도 로그인 쿠키가 필요하므로 `<link rel="manifest" crossorigin="use-credentials">` |
| 확인 | Access 로그인 없이 도메인으로 열면 화면·API 모두 막히는지, 서버 공인 IP로 직접 들어오는 경로가 없는지 |

**연결 완료 (2026-10-03):** 주소 `https://app.trading-lab.me`, Access 앱 `app`(정책: 본인 이메일 하나, 세션 1개월, 일회용 코드), 터널 `quant-lab`(Public hostname → `http://api:8000`). 확인한 것: 로그인 없이 `/`·`/api/*`·매니페스트가 모두 Access 로그인으로 넘어감(앱 ID가 `CF_ACCESS_AUD`와 같음), Cloudflare를 거친 것처럼 꾸민 요청은 토큰이 없거나 가짜면 api가 403, api는 `127.0.0.1:8000`에만 열림(앱·DB 공개 포트 0개), 폰·노트북 로그인 후 정상, Tailscale 주소도 그대로 동작.

**Tailscale은 이제 필요할 때만:** 도메인 접속은 Tailscale과 상관없이 인터넷으로 된다 (폰에서 Tailscale을 꺼 둬도 된다. 확인할 때 끈 것은 Tailscale 없이도 열리는지 보려고). Lightsail의 Tailscale은 관리용·예비 경로로 켜 둔다. **관리 접속을 나중에 바꾼다면** Cloudflare One 앱(기기 전체 트래픽을 보내는 회사용 클라이언트)보다 **Access 브라우저 SSH**(같은 터널, 같은 이메일 정책)로 관리 접속까지 옮겨 Tailscale을 뺄 수 있다. 그때 정한다.

**다시 만들 때의 순서:** 도메인 구매(DNS는 Cloudflare) → Zero Trust 팀 이름 → Tunnel을 만들고 토큰을 `.secrets/cloudflared.env`에 `TUNNEL_TOKEN=...`로 저장(Public hostname → `HTTP` `api:8000`) → Access 앱(Self-hosted, 정책 Allow = 본인 이메일 하나, One-time PIN, 세션 1개월)을 만들고 AUD 태그와 팀 이름을 `.secrets/env`의 `CF_ACCESS_AUD`·`CF_ACCESS_TEAM`에 → `bash deploy/deploy.sh`(토큰 파일이 있으면 tunnel이 켜짐) → 로그인 없이 막히는지, 로그인 후 화면·API·PWA 설치가 되는지, Access 토큰 없는 Cloudflare 요청을 api가 403으로 막는지 확인.

### 개발 PC에서 서버로 옮김 (2026-10-08)

서버가 준비되기 전에는 개발 PC에서 운영 구성(`deploy/compose.prod.yaml`, Compose 이름 `quant-lab-prod`, 같은 `.secrets/`) 그대로 돌려 운영 이력을 쌓았다. PC가 꺼지거나 절전하면 평가가 빠지고 가정용 IP가 바뀌면 토스 403이 나서 시드니 서버로 옮겼다. 옮기는 순서는 로컬 Worker 정지 → `pg_dump` → 서버에서 `pg_restore` → 서버 Worker 시작이고, **Worker를 두 곳에서 동시에 돌리지 않는다** (토스 토큰이 하나라서). 남은 정리(22번 포트 닫기, 개발 PC의 운영 컨테이너 정리)는 roadmap.md "서버 이전".

### 로컬 개발

개발 PC에서는 `compose.yaml`로 PostgreSQL만 띄우고 API·Worker·프론트엔드는 각각 직접 실행한다. **토스 client는 계정당 1개만 발급된다 (2026-10-01 확인).** 같은 client로 토큰을 발급하면 다른 쪽 토큰이 무효화되므로, 서버 Worker가 동작한 뒤로는 로컬에서 토스를 호출하지 않는다. 로컬 개발은 저장된 봉(서버 DB 덤프)이나 합성 데이터로 한다. Worker는 기본값 `WORKER_MARKET_SOURCE=stored`로 토스를 호출하지 않고, 운영 서버만 `toss`로 둔다. 로컬 호출이 꼭 필요하면 서버 Worker를 멈추고 호출한 뒤 다시 시작한다. 허용 IP는 여러 개 등록할 수 있어 개발 PC IP와 서버 IP를 함께 둔다.

```bash
docker compose up -d db
uv run alembic upgrade head
uv run uvicorn trading_lab.api.main:app --reload
uv run python -m trading_lab.worker
npm --prefix frontend run dev
```

자주 쓰는 CLI (`backend`에서, 2026-10-22 README에서 옮김):

```bash
uv run python -m trading_lab.cli sync-bars QQQ VOO                                # 토스 일봉 동기화 (처음 전체, 이후 증분)
uv run python -m trading_lab.cli backtest QQQ --params deposit=1000,dip=15 --save  # 백테스트
uv run python -m trading_lab.cli bot create my-copy QQQ --params deposit=1000      # DRY RUN 봇
uv run python -m trading_lab.cli bot cmd <봇 ID> START                            # START·PAUSE·STOP·RUN_ONCE
uv run python -m trading_lab.cli bot create-ai "시장분석 AI 봇"                   # 시장분석 AI 봇 (관심 10종목)
uv run python -m trading_lab.cli ai-judge QQQ VOO GLD --show                      # AI에 넘길 입력 보기 (--show 빼면 실제로 1번 판단, 비용 듦)
uv run python -m trading_lab.cli ai-judge QQQ VOO GLD --candle                    # 캔들분석 판단 1번 (--show면 익명 표, --effort low|medium|high)
uv run python -m trading_lab.cli replay QQQ --start 2024-01-02 --end 2026-09-30   # 정기 평가 재생 vs 백테스트
uv run python -m trading_lab.cli notify chat-id                                   # 텔레그램 채팅 ID 확인 (봇에게 먼저 메시지)
uv run scripts/toss_probe.py                                                    # 토스 API 읽기 전용 탐색
DATABASE_URL=postgresql+psycopg://quant:quant@localhost:5432/quant_lab_portfolio \
  uv run python -m trading_lab.cli seed-demo                                      # 데모 DB에 예시 시세·예시 봇·예시 환율
```

비밀값(토스 키, Claude 키, 텔레그램 토큰 등)은 저장소 안 `.secrets/`(Git 제외)에 둔다. 처음에는 `cp .env.example .env`로 시작한다 (기본값은 토스를 부르지 않는다).

### 이전 계획 (Lightsail → OCI / 홈서버)

- **서울로 옮기고 싶어지면** (계정 제약이 풀렸을 때) 같은 절차로 `region`·`availability_zone`·`bundle_id`만 바꿔 새로 만든다. 송신 IP가 바뀌므로 아래 순서를 따른다.
- **ARM 서버(OCI·맥북 등)로 옮길 때 걸리는 것 (2026-10-08 메모):**
  - 이미지가 `linux/amd64`만이라 ARM에서는 안 뜨거나 느린 에뮬레이션으로 돈다. 워크플로 `image` 작업의 `platforms`에 `linux/arm64`를 더해야 한다. 같은 러너에서 에뮬레이션(QEMU)으로 빌드하면 몇 분이 10분 넘게 늘 수 있어, 길어지면 ARM 러너(`ubuntu-24.04-arm`, 비공개 저장소에서 쓸 수 있는지·요금 확인)로 따로 빌드해 합친다.
  - 서버 러너도 ARM용 파일(`actions-runner-linux-arm64`)로 다시 설치한다. 맥이면 라벨이 `macOS`라 `deploy.yml`의 `runs-on: [self-hosted, quant-lab, Linux]`을 고쳐야 한다.
  - 맥은 Docker Desktop·OrbStack 위에서 돈다. 절전·재부팅 때 Docker가 멈추는 문제는 아래 홈서버 항목과 같다.
  - Postgres·cloudflared 이미지는 ARM을 지원한다. 파이썬 의존성은 `uv sync`가 arm64 휠을 받는지(matplotlib·pandas·numpy 등) 첫 빌드에서 확인한다.
  - 서버 IP가 바뀌므로 아래 "송신 IP가 바뀐다" 순서를 따른다.

- 서버에 의존하는 것은 Compose 파일, env 파일, DB 덤프뿐이므로 새 서버에서 `pg_restore` 후 같은 Compose를 실행하면 된다.
- **송신 IP가 바뀐다.** 허용 IP는 여러 개 등록할 수 있으므로 새 IP를 먼저 추가하고, 구 서버 Worker를 멈춘 뒤 새 Worker를 시작하고, 마지막에 구 IP를 지운다. Worker를 두 곳에서 동시에 돌리지 않는다 (토큰 경합).
- **홈서버는 가정용 회선 IP가 바뀔 수 있다.** 이때는 토스 호출만 고정 IP를 가진 소형 VPS를 거쳐 나가게 한다 (WireGuard 또는 Tailscale exit node). Lightsail을 가장 작은 플랜으로 줄여 송신 게이트웨이로 남기는 것이 가장 간단한 후보다.

## 7. 전략·백테스트 규칙

| 항목 | 값 |
| --- | --- |
| 봉 주기 | **일봉 (결정).** 미국장은 한국 밤 시간이라 사람이 지켜보기 어렵고, 하루 한 번 평가라 실패 지점이 적다. 토스 일봉은 상장일부터 제공된다 |
| 평가 시각 | 정규장 마감(서머타임 KST 05:00, 표준시 06:00, 조기 폐장 반영) **+ 2시간** 이후. 저장 뒤 값이 바뀌면 동기화가 `resync`로 감지한다 |
| 체결 규칙 | T일 종가로 판단 → **T+1일 시가로 체결** (정한 예산만큼). DRY RUN도 T+1 시가가 확정된 뒤 같은 가격으로 체결을 기록 |
| 비용 | **토스증권 공식 요율**: 위탁수수료 0.1% ($0.01 미만 절사), 매도 시 SEC Fee max(매도대금×0.00206%, $0.01) 추가. 슬리피지 5bp(매수는 올리고 매도는 내림). 환전 수수료는 USD 기준 DRY RUN이라 제외. 실행 기록에 함께 저장 |
| 전략 | 나처럼 투자(`dip_saver`, 나 카피 봇), 시장분석 AI(`ai_judge`), 캔들분석 AI(`ai_candle`) 세 종류다. 과거 백테스트는 규칙 봇만 제공하고 AI 봇은 기록된 판단 재생과 앞으로의 운영으로 비교한다. 수량은 체결 시점 현금으로 **금액 기준·소수점 6자리** 계산(토스 금액 주문과 같음, 최소 주문 $1, $10 이하 수수료 무료), 위험 한도(종목 최대 보유 금액, 1회 최대 주문 금액) 적용 |
| 모으기 전략 (`dip_saver`, "나처럼 모으기") | 아래 "모으기 전략 규칙" |
| 백테스트 데이터 | 토스 일봉 `adjusted=true`, 상장일부터 (QQQ 1999-03-10~, 닷컴·2008·2020·2022 하락장 포함) |
| 비교 기준·지표 | 같은 기간 매수 후 보유 (입금이 있으면 같은 돈을 넣자마자 다음 날 시가에 사는 "매달 그냥 사기"). 총 수익률(넣은 돈 대비), 연평균(입금이 있으면 넣은 시점을 반영한 XIRR, 없으면 CAGR), 최대 낙폭·연 변동성·샤프 지수(무위험 0)·연도별 수익률(입금 효과를 뺀 시간가중 수익률), 보유 비중 |
| 위험 한도 | 종목별 최대 보유 금액·1회 주문 금액 구현. 일봉 1종목은 거래일당 판단 1회라 하루 주문 수는 구조적으로 1건 이하. 하루 손실 한도·주문 간 최소 간격은 다종목·장중 전략 도입 때 추가 |

**모으기 전략 규칙 (`dip_saver`, "나처럼 모으기": 사용자의 실제 투자 습관을 옮긴 전략)**

- **입금:** 매달 `day`일(기본 25일, 휴장이면 그 뒤 첫 판단일) `deposit`달러(기본 $1,000)를 넣고 팔지 않는다. 입금액은 달러로 딱 떨어지게 정한다 (예전 $675·$1,350은 엔화에서 온 값이라 원화로 보면 애매했다). 선택지는 월 $500·$1,000·$2,000(나 카피하기는 $300~$3,000)이고 그 밖은 직접 입력(상한 $100,000). 기준은 달러이고, 원화로 볼 때는 "$1,000 (약 134만 원)"처럼 어림값만 덧붙인다 (`setAmount`).
- **시작 금액이 시작한 달의 입금이다 (사용자 결정):** 시작한 달에는 입금일에 또 넣지 않고 다음 달부터 넣는다 (실제로 따라 하면 첫 달에 두 배가 되는 것을 막는다). 입금 기록이 없으면 첫 판단일의 달을 넣은 달로 보고(`persistence.bots.deposited_month`), 백테스트도 같다.
- **종목:** 최대 10개를 비율대로 한 계좌로 다룬다 (예: VOO 50·QQQ 50).
- **판단일마다:** 종가가 최근 252일 종가 최고보다 `dip`%(10) 이상 낮으면 **모아 둔 현금까지 모두** 산다. 200일 평균보다 `hot`%(10) 이상 높으면 사지 않고 현금으로 모은다 (`hot=0`이면 고점에도 쉬지 않음). 그 밖에는 입금일에 **그달 입금액만큼** 산다. `regular=0`("떨어졌을 때만 사기")이면 평소에도 사지 않고 모아 두다가 하락장에만 산다.
- **여러 종목:** 입금일에 고점인 종목의 몫은 모아 둔 돈이 되고, 평소인 종목들은 모아 둔 돈을 뺀 현금을 비율대로 나눠 사며, 하락장인 종목들은 남은 현금을 모아 둔 돈까지 비율대로 나눠 산다 (`decide_basket`). 쉬는 날 들어온 돈은 `bot_accounts.reserve`로 따로 두고 하락장에만 쓴다.
- **구현:** 전략은 `Signal.spend`(`DEPOSIT`·`ALL`·`NONE`)로 쓸 돈만 알리고, `decide_basket`이 예산(`budget`)을 정해 주문에 남긴다. 소수점(금액 기준) 체결이라 주가가 입금액보다 비싸도 입금액만큼 산다. 입금은 `DepositPlan` 한 규칙을 백테스트와 DRY RUN이 같이 쓰고 `bot_deposits`(봇·월 PK)로 한 달 한 번을 보장한다.
- **규칙 고르기:** 매달 넣는 돈(프리셋 또는 직접 입력)과 따로 "고점에 쉬기"(+10·+15·+20%·안 쉼), "하락장 기준"(-10·-15·-20%)을 고른다 (`StrategyInfo.choices`). 하락장에 쓰는 돈은 "모아 둔 돈 전부" 하나만 둔다: "절반"은 하락장 단위 상태가 더 필요하고 Worker가 멈춘 날이 있으면 백테스트와 어긋나기 쉽다.
- **상장 1년 미만 종목:** 이력이 warmup(252일)보다 짧으면 한 달(`min_bars` 21거래일) 이력부터 있는 만큼의 최고가·평균으로 판단하고 이유도 "상장 뒤 최고가"처럼 쓴다. 이력이 warmup 이상이면 warmup을 채운 날부터 판단한다.
- **결과:** 실제 가격 10년 백테스트에서 규칙 12가지 조합이 모두 매달 그냥 사기와 ±2%p 안이었다 (예: QQQ 50·VOO 50 +145~149% vs +147.9%).

## 8. 화면

**원칙: 주식을 잘 모르는 사람도 쓸 수 있게 한다 (토스 스타일).** 전문 용어 대신 쉬운 말을 쓰고, 꼭 필요한 용어는 ⓘ와 도움말(용어 설명)로 풀어 준다. 파라미터는 직접 입력하지 않고 선택지로 고른다. 판단 이유·알림·활동 문장은 `application/messages.py` 한곳에서 만들어 텔레그램과 화면이 같은 말을 쓴다. 디자인은 Robinhood식 구성(큰 숫자 하나와 자산 그래프가 먼저)에 Vercel·Raycast식 톤을 따른다: 회색 단계와 가는 선으로 구획을 나누고, 카드는 요약 패널과 봇 목록에만 쓰며, 상태는 칩 대신 색 점과 글자로, 주 버튼은 검정(어두운 테마는 흰색) 하나에 나머지 동작은 ⋯ 메뉴로 둔다. 글꼴은 숫자·영문 Geist, 한글 Pretendard다. 밝은 테마와 어두운 테마를 둘 다 지원한다. 기본은 시스템 설정을 따르고 헤더의 밝기 메뉴로 바꾸며, 고른 값은 브라우저에만 저장한다. 색은 `index.css` 토큰에서만 가져오고 차트도 같은 토큰을 읽어 테마가 바뀌면 다시 그린다. 로고는 글자색 사각형 위의 상승선 마크 + "Trading Lab" 워드마크이고, "모의 투자" 안내는 자산 그래프 아래 한 줄과 도움말에서 한다. 가격·손익 색은 국내 관례대로 **오르면 빨강, 내리면 파랑**(매수 빨강, 매도 파랑)이고, 상태 색(정상 초록, 오류 빨강)과는 토큰을 나눠 쓴다(`--rise`/`--fall` vs `--ok`/`--bad`). PWA 매니페스트와 아이콘이 있어 폰에서 "홈 화면에 추가"하면 주소창 없이 앱처럼 열린다 (서비스 워커·오프라인 캐시는 없음: 항상 최신 데이터를 본다). 봇 화면은 1개씩 본다. 홈 오른쪽(폰에서는 맨 위) 봇 목록(상태·최근 3개월 자산 미니 그래프·수익률)에서 고르고, 고른 봇은 브라우저에 기억한다. 홈 첫 화면의 자산 그래프는 `GET /api/bots/{id}/equity`가 첫 판단일부터 체결 기록을 장 마감 가격에 다시 적용해 만든 하루 단위 값이며, 마우스를 올리면 큰 숫자가 그날 값으로 바뀐다. 최근 활동은 첫 화면에서 빼고 거래 내역의 "전체 기록 보기" 서랍으로 옮겼다 (2026-10-02). 가격 차트는 확정 봉이 바뀔 때만 다시 그리고 오늘 진행 중 봉은 제자리에서 갱신해 확대·이동 상태를 유지한다.

| 화면 | 내용 |
| --- | --- |
| 홈 | 지금 모의 자산(큰 숫자, 기간 손익은 그사이 넣은 돈을 뺀 값)과 자산 그래프(1주~전체, 3개월이 안 된 봇은 전체가 기본, 회색 선은 같은 돈으로 그냥 보유, 점선 계단은 넣은 돈, 산 날·판 날 점), 제어(멈추기 또는 시작 + 매매일지 + 그 봇의 설정 + ⋯ 메뉴의 처음부터 다시 시작·봇 삭제), 비교 줄(이 봇·그냥 보유·넣은 돈과 한 줄 평가), 요약 패널(다음 판단·마지막 판단·아직 안 판 주식의 손익·이미 판 주식의 손익, 모으기 봇은 뒤쪽을 넣은 돈으로), 오늘의 판단(쉬운 말 이유), 들고 있는 주식, 가격 차트(3개월~3년), 거래 내역(최근 5건, 전체 기록 서랍), 전략 소개. 오른쪽(폰에서는 맨 위 칩과 맨 아래 목록) 봇 목록 아래 **실제 계좌 카드**: 달러 큰 숫자 아래 줄마다 이름은 왼쪽·숫자는 오른쪽(원화, 이번 달 산·판 금액, 안 판 주식 손익, 판 주식 손익, 승인 기다림). 누르면 숫자 자리를 둥근 막대로 가리고 이 브라우저에 기억한다. 실제로 따라 하기를 켜면 맨 위에 한도를 넘는 주문의 "실제로 살까요?" 승인 카드 |
| 매매일지 (`#journal/{id}`, 2026-10-22) | 봇 하나의 판단일마다 한 일 한 문장, 근거, 그래서 낸 모의 주문과 체결(다음 날 시가·수량·한 주 가격·금액·확정 손익), 입금. 나 카피 봇은 종목마다 쉬운 말 이유와 판단에 쓴 숫자("1년 최고가 $759.66보다 4.5% 낮고, 200일 평균 …보다 7.2% 높아요"), AI 봇은 AI가 쓴 한 문장·근거 2~4개·시장(차트) 요약·종목마다 지금 → 목표 비중과 이유·근거 기사. 달마다 나누고, 주문·입금·비중 변화가 없는 날은 이어진 만큼 한 줄("6일 동안 그대로 들고 있었어요")로 묶어 펼쳐 본다. 아래에 처음부터 다시 시작하기 전 일지와 지운 봇의 일지(보관본, `#journal/archive/{id}`). 들어가는 곳 (2026-10-22 사용자 지적으로 봇 화면 동선 보강): 홈의 [매매일지]; 봇 화면 맨 위 제어 줄의 [매매일지](데모에서도 보인다), 오늘의 판단 아래 "지난 판단과 거래는 매매일지에서 →", 거래 내역의 "매매일지에서 모두 보기 →", AI 봇 판단 기록의 링크. 거래 내역 아래 "알림과 설정을 바꾼 기록 보기"는 예전의 기록 서랍이다 (판단·거래는 매매일지, 알림·설정 기록은 서랍). 처음부터 다시 시작·봇 삭제 확인창은 그 전 매매일지를 보관한다고 알린다. API `GET /api/bots/{id}/journal`·`/api/journal/deleted`·`/api/journal/archives/{id}`. 화면의 "숫자 보기"도 같은 숫자 문장을 쓴다 |
| 시험해 보기 | 홈과 같은 2단 구성. 왼쪽 위에 시험 양식(나 카피 봇 소개·규칙(매달 넣는 돈 등)·종목·기간. 나처럼 투자 하나뿐이다), 그 아래 결과: 최종 금액 큰 숫자와 수익, 이 규칙 vs 매달 그냥 사기 자산 곡선(비율 눈금), 쉬운 이름의 지표 요약 패널(연평균 수익률, 가장 크게 떨어진 폭, 가격 출렁임, 위험 대비 수익 점수, 투자 중이던 기간), 해마다 결과, 거래 내역(접어 둠). **양식은 지금 보이는 결과의 종목·규칙·기간에 맞춘다.** 오른쪽(폰에서는 맨 아래)에 지난 시험 목록: 같은 조건으로 다시 시험하면 지난 결과를 지우고 하나만 남긴다(종목·비율·규칙·금액·비용이 같고 시험 시작이 같은 달). "시험해 보기" 버튼은 계산만 하고 봇을 만들지 않는다. 결과의 "이 규칙으로 모의 투자 시작"은 종목·규칙이 채워진 새 봇 양식으로 가고(나 카피 봇이 이미 있으면 "이 규칙을 나 카피 봇에 적용"), 봇이 만들어지는 곳(설정의 새 봇, 나 카피하기, 홈의 AI 봇 만들기)은 모두 만들기 직전에 확인 창으로 무엇을 만드는지 먼저 보여준다 |
| 설정 | **설정 탭은 앱 전체에 하나인 것만 (2026-10-22, 사용자 결정):** 토스증권 계좌(달러·원화 칸, 들고 있는 주식, 봇이 낸 실제 주문의 산·판 금액과 손익, 최근 주문), AI 비용(이번 달 합계와 봇마다 쓴 돈 / 상한), 텔레그램 알림(끄기·실제 주문만·모의 투자 소식까지, 테스트), 실제 주문 모두 멈추기, 그리고 봇 목록(누르면 그 봇의 설정)과 [+ 새 봇 만들기](`#new`). **봇 하나의 설정은 봇 화면의 [설정](`#bot/{id}/settings`, 나 카피 봇은 홈의 [설정]으로도)**: 한 화면에 한 봇만이라 어느 봇 설정인지 헷갈리지 않는다. 왼쪽 섹션 설명·오른쪽 입력, 저장 버튼 하나, 맨 아래 빨간 테두리의 되돌릴 수 없는 동작(처음부터 다시 시작·봇 삭제. 실제로 산 주식이 있으면 그 주식은 남는다고 알린다). 전략 카드, 반응 속도(프리셋), 체결 가격 가정(보수적/보통/이상적), 최대 투자 금액($1 이상, 모으기 봇은 칸을 숨김), 실제로 따라 하기(끄기·1/100, 그 봇의 금액으로 계산한 실제 금액). 수수료는 토스 요율 고정. **돌아가는 중에도 바꿀 수 있고 다음 판단부터 적용**된다 (API와 Worker 평가가 같은 봇 행을 잠가 순서가 정해진다). 이름 바꾸기(20자까지), 바꾼 기록(무엇을 바꿨는지 쉬운 말로). 금액 칸은 숫자만 받고 문자를 치면 "숫자만 입력할 수 있어요", 상한을 넘으면 알려 준다. 새 봇은 이름을 종목·전략으로 자동 제안하고 기본으로 만들자마자 시작한다 |

전략 별명: 나처럼 투자(`dip_saver`), 뉴스·금리 보고 판단(`ai_judge`, 시장분석 AI 봇), 차트만 보고 판단(`ai_candle`, 캔들분석 AI 봇). 이모지 대신 규칙 그림(`StrategyGlyph`)을 쓴다. 로그 화면은 두지 않는다 (원시 기록은 API `/api/events`로만).

## 9. 결정 현황

| 항목 | 상태 | 메모 |
| --- | --- | --- |
| 첫 종목 | **결정: `QQQ`** (2026-10-01) | 이력이 가장 길고(1999~) 하락장 표본이 많다. VOO는 두 번째 후보 |
| 유명 전략 4종 제거 (2026-10-08) | **결정: 이동평균 교차·200일선·RSI2·돈치안을 없앴다. 남기는 전략은 나처럼 투자(나 카피 봇)와 AI 봇뿐이다** (사용자 결정) | 서비스 색깔을 "나를 대신해 투자하는 앱"으로 굳히려고 남의 공식을 돌려 보는 기능을 뺐다. 과거 비교는 평행세계의 나가 맡고, 4종을 평행세계에 옮기지도 않는다 (평행세계는 내 규칙을 한 가지씩만 바꾼다). 시험해 보기 화면은 지우지 않고 나처럼 투자 하나만 시험하게 줄였다. 데모의 예시 봇은 나 카피 봇·시장분석 AI 봇이다. 저장해 둔 4종 시험 결과는 마이그레이션 0021이 지우고, `seed-demo`는 없어진 전략의 예시 봇을 지운다. 사고팔기 봇만 쓰던 코드(보통 전략 판단·실거래 한 건 한도·화면의 모으기 아닌 갈래·왕복 거래/승률 지표)도 함께 지웠다. 이제 모든 전략 신호는 쓸 돈(`Spend`)을 갖고 매달 입금한다. **남은 정리:** `Signal.long`·`DecisionRecord.target_long`은 나 카피 봇에서 항상 true인데, DB 컬럼(`decisions.target_long`)과 화면 표시가 얽혀 있어 두었다 (지우려면 마이그레이션 필요, roadmap "앞으로 계획") |
| 봉 주기 | **결정: 일봉** (2026-10-01) | 정규장 마감 + 2시간 뒤 평가 |
| 이름 | **결정: Trading Lab** (2026-10-15, 사용자) | 퀀트 연구가 아니라 나를 대신해 투자하는 봇이라 도메인(`trading-lab.me`)에 맞춰 통일. **바꾼 것:** 패키지 `trading_lab`, 화면 이름, `localStorage` 키 `trading-lab:*`, 패키지 이름, GitHub 저장소·GHCR 이미지(`ghcr.io/ottuck/trading-lab`, compose는 워크플로의 `IMAGE`를 먼저 쓰고 없으면 이 이름)·러너 라벨 `trading-lab`. **남긴 것:** DB 이름·계정(`quant_lab`·`quant_lab_demo`·`quant`), Compose 프로젝트·네트워크 이름(`quant-lab-prod`·`quant-lab-demo`·`quant-lab-edge`·`quant-lab-dbnet`: 프로젝트 이름이 바뀌면 데이터 볼륨(`db-data`)이 새로 생겨 DB가 비어 보인다), 서버의 폴더·백업 경로·cron 이름, Terraform 인스턴스 이름 `quant-lab-02`(Lightsail에서 못 바꾼다)·`project` 태그, 터널 이름, Tailscale 호스트 이름. 모두 서버 안에서만 쓰이고 화면에 보이지 않는다 |
| 초기 모의 현금 | **결정: $10,000** | |
| 수수료·슬리피지 | **결정: 0.1% + 매도 SEC Fee · 5bp** | 2026-10-02 계좌 수수료 조회 API와 토스증권 공지(2025-12-01 표준 요율 0.1%)로 확인 |
| 제품의 중심 아이디어 | **결정: 나 카피 봇** (2026-10-02, 사용자 확인) | 1절. 나 카피 봇 vs 매달 그냥 사기와 평행세계의 나를 핵심 화면으로 (2026-10-02 수정). 재미있게 나오면 홈 첫 화면 |
| 텔레그램 알림 | **결정: 화면 설정에서 켜고 고른다** (2026-10-04, 사용자 결정) | 설정 맨 위 "계좌와 알림"에서 끄기 / 실제 주문만(승인 요청·체결·실제 주문 문제·봇 멈춤) / 모의 투자 소식까지(모의 신호·체결, 주간 정리, 판단 미룸·누락, AI 판단 실패, 다시 시작·삭제, 밀린 판단이 있던 재시작), 테스트 메시지 보내기. 실제로 따라 하는 봇의 AI 판단 실패는 그날 실제 주문도 없으므로 "실제 주문만"에서도 보낸다. 일일 점검·입금·설정 변경·시작/멈춤은 앱 기록에만. 값은 `notify_settings` 1행에 두고 Worker의 알림이 매 주기 읽는다. 봇 토큰·채팅 ID는 비밀값이라 `.secrets/worker.env`에만 두고 Worker가 있는지만 적는다(`available`). `TELEGRAM_ENABLED`는 처음 시작 값으로만 쓴다. Worker 정지 감시(Healthchecks)는 유지 |
| AI 사용 범위 | **결정: 규칙 봇은 질문 → 규칙 값까지, AI 봇만 비중 판단** (2026-10-02, 2026-10-06 AI 봇 추가) | 규칙 봇에서 AI는 매매 판단을 하지 않는다. AI 봇은 정해 준 종목과 현금 사이 비중만 정하고 주문·체결·한도는 엔진이 한다 (14절) |
| 실제 계좌 비교 ("실제 나") | **결정: 계획에서 뺀다** (2026-10-02, 사용자 결정) | 성적표처럼 압박을 주고, 실제 거래 증권사가 앱과 다른 경우가 흔하다. 대신 평행세계의 나(1절). 토스 계좌 조사 결과(tossApi.md 9절)는 실거래 단계용으로 남긴다 |
| 나 카피 봇의 종목 수 | **결정: 최대 10개** (2026-10-02) | 평소 가장 많이 사는 종목부터 고르게 하고, 10개보다 적게(보통 2~5개) 고르도록 안내한다. 수십 개 종목을 사고파는 사용자는 대상이 아니다 |
| 여러 종목 봇 | **결정·구현: 봇 하나 = 계좌 하나, 최대 10개 종목** (2026-10-02) | 모으기 전략만. 종목별 비율(합 100), 현금 공유. **만든 뒤 종목·비율 바꾸기** (2026-10-03, 설정 → 종목과 비율, `PUT /api/bots/{id}/symbols`): 다음 판단부터 적용하고 바꾼 기록은 `config_change` 이벤트로 남긴다. 모으기 전략에서 뺀 종목을 들고 있으면(또는 주문 예정이면) `symbols`에 **비율 0**으로 남겨 시세·평가에는 쓰고 더 사지 않는다 (팔지 않음). 팔고 사는 전략은 들고 있는 종목을 뺄 수 없다 (팔 기회를 잃으므로). 바꾼 뒤에는 그 봇의 DRY RUN이 처음 조건의 백테스트와 달라진다. 한 종목 봇은 지금과 같게 동작 (재생 = 백테스트 일치 테스트) |
| 모의 체결 수량 | **결정·구현: 금액 기준·소수점 6자리** (2026-10-02) | 월 금액이 주가보다 적어도 그대로 산다. 토스 금액 주문(소수점 매수)과 같은 방식. 초기에는 정수 주식이었고 현재는 소수점 수량 |
| 실거래 범위 (마일스톤 3) | **결정: 나 카피 봇의 1/100 축소판을 토스 계좌에서 따라 산다** (2026-10-04, 사용자 결정) | 실제 큰돈 투자(목표 매달 10만엔 ≈ 100만원)는 일본 moomoo에서 하고 이 앱과 잇지 않는다. 나 카피 봇(모의)은 그 목표 금액으로 돌리고, 토스 계좌는 모의 주문 금액 × 1/100을 같은 날·같은 종목에 금액 주문으로 산다. 원칙 1은 안전장치(실거래 스위치·비상 중지·한도·중복 방지·대조)와 함께 주문 경로를 연다. 단계는 roadmap.md "실거래 트랙" |
| AI 봇 실거래 | **결정: 바로 1/100로 따라 한다** (2026-10-07, 사용자 결정) | 사기는 모의 매수 × 1/100, 팔기는 실제로 산 수량에서 모의로 판 비율만큼. 안전장치는 마일스톤 3 그대로 (14절) |
| 실거래 넓히기 (R3) | **결정: 비율은 1/100만, 레버리지는 QLD·TQQQ만, 파는 전략은 실거래, 고정 IP 서버는 별도 인프라 트랙** (2026-10-06, 사용자 결정) | AI 봇: 모의로 살 때 그 금액 × 1/100을 금액 주문으로(한도를 넘으면 승인), 모의로 팔 때 이 봇이 실제로 산 수량 중 모의로 판 비율만큼(모두 팔 때는 전부) 소수점 수량 시장가로 판다(`Trader.place_quantity_sell`). 켜기 전 모의 보유를 파는 신호는 넘긴다. 손실 범위는 봇이 모의로 쓴 돈의 1/100 안이다 (유명 전략 4종과 함께 현금 전부로 사고파는 사고팔기 봇은 없앴다, 2026-10-08) |
| AI 퀀트봇 (마일스톤 4) | **결정: 매일 판단, 나 카피 봇과 같은 매달 입금, 지표 + 웹 검색, Claude Sonnet 5.5** (2026-10-06, 사용자 결정) | AI가 시장을 조사해 정해 준 종목 안에서 비중을 정하는 봇. 과거 백테스트 없이 앞으로의 모의 운영으로 나 카피 봇·매달 그냥 사기와 비교한다. 설계는 14절, 단계는 roadmap "AI 퀀트봇" |
| 데모와 운영을 같은 기계에 | **결정: 실거래 뒤에도 분리하지 않는다** (2026-10-03, 사용자 결정) | 데모에는 키가 없고, 네트워크·DB·비밀값을 나눴다 (11-1절) |
| 이름 | **결정: 기능은 "나 카피 봇", 전략은 "나처럼 투자", 질문은 "나 카피하기"** (2026-10-03, 사용자 결정) | 봇 기본 이름은 나처럼 투자면 "나 카피 봇"("도플갱어 봇"도 검토했지만 "나 카피 봇"이 더 직관적이라 골랐다), AI 봇은 "시장분석 AI 봇". 전략 이모지는 아마추어 느낌이 나서 뺐고, 대신 **규칙 그림**(나처럼 투자는 매달 칸·쉬는 달 빈 칸·하락장 큰 막대)을 넣는다 (`StrategyGlyph`, 2026-10-03) |
| 홈·시험해 보기 배치 (N8) | **결정: 나 카피 봇이 늘 첫 자리** (2026-10-03) | 홈 첫 화면은 나 카피 봇(없으면 세 단계 소개와 [나 카피하기], 그 아래 "만들면 홈이 이렇게 바뀌어요" 예시 화면을 흐리게), 봇 목록은 "나 카피 봇"·"AI 봇"·"다른 봇"으로 나눈다 ("전략"은 너무 전문적이라 뺐다). "다른 봇"은 유명 전략 4종을 없앤 뒤 새로 만들 것이 없어 예전에 만든 봇이 있을 때만 보인다. 시험해 보기는 "나처럼 투자" 소개 카드 하나(유명 전략 참고 목록은 2026-10-08에 없앴다). 나 카피 봇 설정은 전략 고르기 대신 "내 규칙" 요약과 [다시 카피하기]. **나 카피 봇은 하나다:** 있으면 나 카피하기는 어디서 열든(봇 목록, 설정 메뉴, 시험해 보기, `#me`) 그 봇의 다시 카피하기다 (데모는 예시 봇을 바꿀 수 없어 늘 새로). 시작·멈추기를 누른 뒤 Worker가 반영하기 전에는 "시작하는 중"·"멈추는 중"으로 보인다. 아무 봇도 고르지 않았으면 나 카피 봇을 고른 것으로 본다 |
| 바깥 접속 | **결정·완료: 도메인 + Cloudflare Tunnel·Access** (2026-10-02 결정, 2026-10-03 연결, `app.trading-lab.me`) | 본인 이메일만 허용. 앱·DB 공개 포트 0개 유지. 6절 |
| 누구나 쓰는 서비스 | **결정: 하지 않는다** (2026-10-03, 사용자 결정) | 나를 대신해 투자하는 앱으로 간다. 남에게 쓸 수 있는 시세 계약이 최소 월 $250 수준이라 개인 프로젝트로는 어렵다. 이유는 12절 |
| 백테스트 엔진 | **제안: 자체 엔진 유지** (2026-10-01, 사용자 확인 대기) | QuantConnect LEAN(Docker)은 검토 후 보류. 판단·체결 함수를 백테스트와 DRY RUN이 공유하는 구조(replay 일치 검증)를 지키기 위해서다. 장중·다종목·복잡한 주문으로 넓힐 때 연구용 교차 검증 도구로 다시 검토 |
| 실제 주문 승인 (2026-10-08) | **결정: 한도 안의 주문은 묻지 않고 바로 낸다. "처음 3번 승인"과 1/10 버튼은 없앴다** (사용자 결정: 어차피 계속 보면서 작업한다) | 한도(1건 $20·한 달 $50)를 넘는 사는 주문과, 실제 계좌의 보유가 봇이 산 수량보다 적은 동안의 새 주문만 승인을 받는다. 거절·취소는 결과를 기록하고 다음 주문을 이어간다. **확인 불가(`UNKNOWN`)는 계좌 전체 신규 주문·승인을 막는다** (2026-10-10 보완). 비율은 1/100 하나뿐이다. 봇 삭제·다시 시작 확인창은 실제로 산 주식이 있으면 "토스 계좌의 주식은 그대로 남는다"를 알리고, 다시 시작이면 첫 판단의 매수도 실제로 새로 산다는 것까지 알린다 (`has_real_fills`). 입력 상한: 매달 넣는 돈 $100,000(`MAX_DEPOSIT`)·시작 금액 $1,000,000(`MAX_CASH`) |
| 전략마다 봇 하나 (2026-10-08) | **결정: 나 카피 봇(`dip_saver`)·시장분석 AI(`ai_judge`)·캔들분석 AI(`ai_candle`)는 전략마다 하나만 만들 수 있다** (사용자 결정) | 서버가 같은 전략의 두 번째 봇을 막는다 (409, `application/bots.ONE_PER_STRATEGY`, 만들 때와 전략을 바꿀 때). 제한은 이름이 아니라 **전략**에 건다: 캔들분석 AI 봇도 다른 전략이라 따로 하나 만들 수 있고, 이름은 "시장분석 AI 봇"·"캔들분석 AI 봇"처럼 구분하는 이름표다. 새 AI 봇의 이름은 종류대로 "시장분석 AI 봇"·"캔들분석 AI 봇"이다. 예전에 "AI 봇"으로 만든 시장분석 봇은 마이그레이션 0023이 "시장분석 AI 봇"으로 바꿨다 (캔들분석 AI 봇이 생겨 "AI 봇"만으로는 구분되지 않아서, 2026-10-08 사용자 요청. 직접 지은 이름은 두고, 설정의 이름 바꾸기로 언제든 바꿀 수 있다). 전략 별명도 무엇을 보고 판단하는지로 짓는다: 시장분석은 "뉴스·금리 보고 판단", 캔들분석은 "차트만 보고 판단". |
| 캔들분석 AI 봇 설계 (2026-10-08) | **결정: 가격만 보는 AI 봇을 따로 더한다. 입력은 익명화한 일봉·주봉 차트 그림 + 짧은 숫자 요약(2026-10-09 변경), 웹 검색 없음, 시작한 날부터 앞으로만 비교한다** (사용자 결정) | 나 카피 봇의 규칙도 일봉 종가 몇 개로 계산하는 공식이라, 이 봇이 묻는 것은 "같은 가격만 보고 AI가 내 규칙보다 나은가"다. 설계는 14절 "캔들분석 AI 봇". **토스 시세 원본 일봉을 AI에 보낸다** (시장분석 AI 봇은 요약만 보낸다): 내 매매 판단을 위한 처리이고 사용자가 확인했다. 지수로 바꾸고 종목 이름·날짜를 가려서 보낸다. 한 달 비용 상한은 시장분석 AI 봇과 따로 두고 봇마다 쓴 비용을 보여준다 |
| 기업 분석은 시장분석 AI 봇에 (2026-10-08) | **방향: 기업 가치·실적 분석은 캔들분석 AI 봇이 아니라 시장분석 AI 봇의 지침에 더한다** (사용자 아이디어) | 캔들분석은 가격만, 시장분석은 정보를 보게 나눠야 두 봇의 차이가 "어떤 정보를 쓰는가"로 남는다. 내용은 14절 "시장분석 AI 봇에 기업 분석 더하기" |
| 실제 계좌 손익 (2026-10-08) | **결정: 봇이 낸 실제 주문의 산·판 금액과 손익을 홈 계좌 카드와 설정의 토스 계좌에 보여준다** (사용자 요청) | `/api/live`가 체결된 실제 주문을 거래일 순으로 `domain/live.real_ledger`에 넣어 계산한다: 이번 달 산·판 금액, **확정 손익 = 판 금액 - 평균 단가 × 판 수량**(봇·종목마다), 봇이 산 채로 들고 있는 주식의 원가와 지금 값(토스 현재가, 없으면 최근 종가)으로 **평가 손익**. 화면은 늘 달러. **어림값이다:** 수수료는 빼지 않았고 봇이 낸 주문만 세므로 실제 계좌에 직접 산 주식은 포함하지 않는다. 판 적이 없으면 확정 손익은 숨긴다 |
| 원화와 환전 | **결정: 자동 환전은 없다** (2026-10-08, 사용자 확인) | 달러 주문에는 달러 잔고만 쓰인다. 다른 외국 주식 앱처럼 먼저 달러로 바꿔 두어야 하고, 화면은 원화 칸에 "달러로 바꿔야 주문에 쓸 수 있어요"라고 알린다 |
| 실거래는 1/100 축소판이다 (마일스톤 3~) | **결정: 비율은 키우지 않는다** (2026-10-06, 사용자 결정) | 실제 계좌는 같은 판단이 진짜 돈으로도 움직이는지 확인하는 곳이라 금액이 작다. $1 미만 몫은 모아 두었다가 사고, 일부 팔기의 $1 미만은 넘긴다 |

## 10. 작업 방식

- **브랜치:** `dev`에서 `feat/`, `fix/`, `docs/`, `chore/` 접두어 작업 브랜치를 만들고 PR로 `dev`에 합친다 (squash). 검증된 묶음은 `dev → main` PR을 열고(이 PR과 main push에는 CI가 돌지 않는다. 작업 PR의 CI가 통과한 코드만 합치므로, main push는 바로 배포된다) **Claude가 `git push origin dev:main`으로 main을 dev 위치로 fast-forward**한다 (2026-10-09, 사용자 결정). 병합 버튼을 쓰지 않으므로 main과 dev는 같은 커밋을 가리키고 이력이 한 줄로 남으며, GitHub이 PR을 merged로 표시한다. 버튼으로 병합하면 마지막에 쓴 방식(작업 PR의 squash)이 기본값이라 squash 병합이 두 번 났고(#238, #242), 그때마다 dev에 내용 없는 병합으로 이력을 이어야 했다. fast-forward가 안 되면(main에만 있는 커밋이 생기면) 밀어 넣지 말고 원인을 확인한다. 릴리스 표시는 마일스톤 태그로 한다. `main`은 항상 배포 가능한 상태다.
- **PR:** 한국어로 쓰고 변경 내용, 검증 방법과 결과, 제한 사항을 적는다. CI가 있으면 통과해야 한다.
- **Merge 권한 (2026-10-01):** Claude가 작업 브랜치 → `dev`, `dev → main` 모두 merge할 수 있다. 단 **큰 문제가 있으면 merge하지 않고 사용자에게 묻는다.** 큰 문제의 예: CI 실패, 설계 원칙(3절) 위반이나 변경, 실거래 경로 추가, 비밀값·시세 데이터 노출 위험, 비용이 드는 리소스 생성, 되돌리기 어려운 DB 변경.
- **계획은 언제든 바뀐다 (2026-10-09, 사용자):** 회사의 위에서 정한 계획이 아니라 개인 사이드 프로젝트다. 예전 결정과 새 결정이 겹치면 **최근 결정이 앞선다.** 예전 결정을 이유로 새 요청을 미루지 않고, 바뀐 결정은 이 문서에서 지우거나 고친다 (예: "마일스톤 4를 지켜보는 동안 AI 지침을 바꾸지 않는다"는 없앴다). 지침을 바꿔도 판단 기록의 지침 버전으로 언제부터인지 구분된다.
- **문서:** 매 작업 전에 이 문서와 [roadmap.md](roadmap.md)의 현재 단계를 확인한다. 설계가 바뀌면 같은 PR에서 문서를 고친다. 단계가 끝나면 roadmap의 상태를 갱신한다. **README는 영어로, 앱을 처음 보는 사람에게 필요한 소개(무엇인지·화면·할 수 있는 것·짜임·주의)만 둔다 (2026-10-22, 사용자 결정).** 개발·운영(로컬 실행·CLI·설정·배포·설계 판단)은 이 문서가 맡는다. 날짜가 붙은 작업 일지(코드 목록·측정값 나열)는 적지 않고, 결정과 그 이유, 지금의 동작만 남긴다.
- **커밋에 넣지 않는 것:** API 키, 토큰, 계좌 정보, 실제 토스 응답 데이터, `docs/references/` 이미지. 가짜 키도 넣지 않고 `.env.example`에는 변수 이름만 둔다.
- **공급자 기능:** 공식 문서와 실제 호출로 확인하기 전에는 사실로 적지 않는다.

## 11. 알려진 한계

첫 MWP는 정기 모의 운영까지였고, 현재는 1/100 실거래와 AI 두 종류가 추가됐다. 실거래 결과 불명 처리는 4절, AI 관찰 단계는 roadmap에 둔다. 아래는 알고 남겨 둔 한계이며, 모의 결과를 실제 수익으로 읽으면 안 되는 이유이기도 하다.

**모의 체결·비용**

| 한계 | 영향 | 대응·계획 |
| --- | --- | --- |
| 체결은 "다음 거래일 시가 + 슬리피지 가정"으로 계산한다. 호가·유동성·부분 체결이 없다 | 장 시작 직후 급변이나 얇은 호가에서 실제보다 유리하게 나올 수 있다 | 슬리피지 선택지(보수적 0.1%)로 민감도만 본다 |
| 모의 체결은 토스 금액 주문처럼 소수점(6자리)으로 산다 (2026-10-02~). 최소 주문 $1, 체결금액 $10 이하는 수수료 무료 | 실제 토스에서 금액 주문은 시장가·정규장 종료 1시간 전까지만 된다. 모의 체결(다음 날 시가)은 그 안이지만, 소수점 매수가 안 되는 종목은 실제와 다를 수 있다 | 실거래 단계에서 종목별 소수점 가능 여부를 확인한다 |
| 환전 수수료·환율, 양도소득세(연 250만 원 초과분 22%), 배당 세금은 넣지 않는다 | 원화 기준 실제 수익은 더 낮다 | USD 기준 비교용으로만 본다. 화면의 원화 보기(roadmap W1)는 오늘 환율로 바꾼 값이라 환차익은 들어가지 않는다 |
| 배당을 모의 잔고에 넣지 않는다. 토스 수정주가(`adjusted=true`)가 배당까지 반영하는지는 확인하지 못했다 | 배당이 있는 종목은 모의 수익이 조금 낮게, 백테스트 "그냥 보유"는 배당 반영 여부에 따라 다르게 나온다 | 필요해지면 배당 이력 API를 조사한다 |
| **보유 중 액면분할·병합이 생기면 잔고 수량·평균 단가를 맞추지 않는다.** 일봉은 수정주가로 자동 재동기화(`resync`)되지만 이미 체결된 주문과 잔고는 예전 기준이다 | 분할 뒤 평가 손익이 크게 틀어진다 (예: 2:1 분할이면 반토막 손실처럼 보임). 재동기화는 알림 없이 내부 기록만 남는다 | **분할 의심 보호 (2026-10-09):** 들고 있는 종목의 마지막 모의 체결가가 지금 저장된 그날 시가와 1.2배 넘게 다르면(`domain/bars.split_suspected`) 봇을 `ERROR`로 멈추고 알린다. 설정의 "처음부터 다시 시작"으로 새 기준에서 다시 계산한다. 잔고를 분할 비율로 보정하는 기능은 아직 없다 |
| 봇마다 정한 시작 금액·정기 입금을 쓰는 독립 모의 계좌다 | 두 봇을 합친 위험(같은 나스닥 노출)은 보지 않는다 | 포트폴리오 위험 한도는 MWP 이후 |

**판단·전략**

| 한계 | 영향 | 대응·계획 |
| --- | --- | --- |
| 하루 한 번, 정규장 마감 2시간 뒤에만 판단한다 (서머타임 중 한국 07:00쯤, 11월~3월 표준시에는 08:00쯤) | 장중 급락에 대응하지 못한다. 손절·익절 주문이 없다 | 설계상 선택. 실시간 판단은 WebSocket과 함께 다시 검토 |
| Worker가 멈춘 동안의 거래일은 소급 판단하지 않는다 (`missed_sessions` 알림만) | 멈춘 사이 신호가 바뀌었다면 놓친다. 대기 주문은 원래 날짜 시가로 체결된다 | 개발 PC에서 Lightsail로 옮겨 재부팅 의존을 줄였다. 서버 장애로 놓친 판단은 소급하지 않는다 |
| 레버리지 ETF 전용 위험 한도가 없다 | 3배 상품도 1배와 같은 규칙으로 전액 투자한다. 변동성 손실·큰 낙폭에 그대로 노출 | 화면 안내만. 보유 기간·손절 한도는 MWP 이후 |
| 규칙 봇은 나 카피 봇 하나이고 자동 파라미터 탐색은 제공하지 않는다 | 투자 습관을 재현하는 비교이고 최적 전략을 찾아 주지 않는다. 백테스트 결과는 미래를 보장하지 않는다 | AI 두 종류는 과거 백테스트 대신 시작 이후 기록으로 비교한다 (14절) |

**데이터**

| 한계 | 영향 | 대응·계획 |
| --- | --- | --- |
| 토스 미국 시세는 일부 거래소 기준이고 NBBO가 아니다 | 거래량은 참고용, 고가·저가가 다른 사이트와 조금 다를 수 있다 | 공식 종가 기준 일봉만 판단에 쓴다 |
| 상장폐지 종목의 과거 시세를 받을 수 없다 | 백테스트에 생존 편향이 있다 (관심 10종목에는 영향 작음) | — |
| 토스 client당 유효 토큰 1개 | Worker가 도는 동안 개발 PC에서 토스를 부르면 Worker 토큰이 무효가 된다 (Worker가 한 번 재발급해 복구) | 토스 호출은 Worker만 한다 |
| 실시간 가격은 REST 30초 주기, 봇 종목만 | 화면은 최대 40초쯤 늦다. 토스 앱처럼 틱마다 바뀌지 않는다. 휴장일에도 같은 값을 다시 받는다 | 판단과 무관한 표시용. WebSocket은 필요해질 때 |
| 오늘 진행 중 봉은 정규장 전(데이마켓·프리마켓) 거래부터 채워진다 | 정규장 전에는 공식 일봉과 시가·고가·저가가 다르다 | 흐리게 표시하고 확정 전이라고 안내 |

**운영**

| 한계 | 영향 | 대응·계획 |
| --- | --- | --- |
| 시드니 Lightsail로 옮겼고 운영 마무리 확인이 남았다 | 콘솔 SSH(22번) 차단·정기 평가·계좌 조회 주기 확인이 아직 roadmap에 남아 있다 | 남은 항목을 확인한 뒤 체크한다. 개발 PC의 운영 컨테이너도 정리 대상 |
| 서버·Worker·PostgreSQL 프로세스가 각각 1개다 (이중화 없음) | 서버 장애 시 모의 평가·실제 주문이 지연되거나 빠진다. 데모와 운영도 자원을 공유한다 (데모 api 384MiB·seeder 512MiB 상한) | Healthchecks로 감지하고 복구한다. 개인용 소액 운영의 비용 선택 |
| 백업 스크립트·cron 구성은 있고 새 서버에서 정기 실행 확인은 남았다 | 정기 실행을 확인하기 전에는 최근 복구 지점이 보장되지 않는다 | 6절의 기존 구성과 roadmap 체크를 따른다. 이전할 때 pg_dump → pg_restore는 수행했다. 별도 정기 복원 연습을 완료 조건으로 두지 않는다 (사용자 결정) |
| 텔레그램 알림은 설정에서 켜야 온다. Worker·서버가 멈추는 것은 외부 heartbeat(Healthchecks, 기본 영어)도 알린다 | 알림을 끄면 판단 실패·데이터 문제는 앱을 열어야 보인다 | 한국어 webhook 설정은 6절 |
| 화면에 로그인이 없다 | 앱 자체에는 로그인이 없다 | 도메인은 Cloudflare Access(본인 이메일 일회용 코드)가 앞에서 막고 API도 Access 토큰을 다시 확인한다. Tailscale 경로는 tailnet 기기만 (6절) |

**AI 봇 (마일스톤 4, 14절)**

| 한계 | 영향 | 대응·계획 |
| --- | --- | --- |
| 같은 상황에서도 판단이 날마다 달라질 수 있다 | 같은 지표·뉴스라도 비중이 바뀔 수 있다 | 지침이 "이유 없이 바꾸지 말 것"을 요구하고, 자산 2%보다 작은 차이는 사고팔지 않는다. 판단은 모두 기록해 그 기록으로 재현한다 |
| 과거 성과로 검증할 수 없다 | 모델이 과거 결과를 알아 백테스트가 부풀려진다 | 시작한 날부터 나 카피 봇·매달 그냥 사기와 같은 돈으로 앞으로만 비교한다 |
| 이유와 출처는 AI가 쓴 글이다 | 사실과 다르거나 날짜가 어긋난 기사를 근거로 쓸 수 있다 | 검색어·출처 링크를 함께 보여 준다. 미국 소식은 영어·믿을 만한 경제 뉴스 우선, 위키백과 제외 |
| 판단은 하루 한 번, 장 마감 2시간 뒤 | 장중 급변에 대응하지 않는다 | 규칙 봇과 같은 설계 선택 |
| 외부 API와 비용에 기댄다 | 장애·키 만료·크레딧 부족이면 그날은 그대로 둔다 | 실패는 알리고 다음 날 다시 부른다. 한 달 비용 상한 |

## 11-1. 포트폴리오 데모 (2026-10-03 결정, 마일스톤 3 앞)

누구나 볼 수 있는 데모를 **운영과 따로** 띄운다. 토스 시세와 그것으로 계산한 결과는 남에게 보여줄 수 없으므로 데모는 **합성 예시 시세**만 쓴다. 같은 코드에 설정만 다르게(데모 모드) 띄우고, 토스·주문 키는 아예 넣지 않는다. 운영과 데모는 시드니 Lightsail에서 별도 Compose 프로젝트로 실행하고 같은 Tunnel에 `demo.trading-lab.me`를 연결한다 (2026-10-08 이전). **실거래를 시작해도 데모는 같은 기계에 둔다** (2026-10-03, 사용자 결정. 처음 계획은 다른 기계로 옮기는 것이었다). 대신 데모에는 토스·주문 키를 넣지 않고, 데모 DB 계정·비밀값을 나누고(DB는 운영 Postgres 안의 별도 데이터베이스, 운영 DB 접속 권한 없음), 데모는 `quant-lab-edge` 네트워크로만 터널과 이어져 운영 api·Worker에 닿지 않으며, 바꾸기 요청은 막는다. 실거래 키는 운영 Worker에만 둔다. 단계는 roadmap.md "포트폴리오 데모 트랙".

**구성 (D3, 2026-10-03):** `deploy/compose.demo.yaml`(이름 `quant-lab-demo`): `demo-migrate`, `demo-seeder`(6시간마다 `seed-demo`: 예시 시세를 오늘까지 늘리고 예시 봇을 이어서 평가), `demo-api`(`DEMO_MODE=true`, 바꾸기 요청은 403). Worker·토스 키·Access 설정은 없다. **DB는 운영 Postgres 컨테이너 안의 별도 데이터베이스 `quant_lab_demo`다 (2026-10-08, 컨테이너를 하나로 합침).** 데모 전용 계정 `quant_demo`는 그 DB의 소유자일 뿐 운영 DB(`quant_lab`)에는 접속 권한이 없다(`CONNECT` 회수). 데모는 `quant-lab-dbnet` 네트워크로만 운영 Postgres(별칭 `shared-db`)에 닿고 운영 api·worker와는 네트워크가 다르다. 비밀값은 `.secrets/demo.env`(`DEMO_DB_PASSWORD`, 그 비밀번호로 만든 `DATABASE_URL`)뿐이고, 데모는 `bash deploy/deploy.sh demo`로 띄운다 (운영이 먼저 떠 있어야 하며 이 스크립트가 계정·DB·권한을 멱등하게 만든다). **처음엔 수동이었으나 2026-10-09부터 deploy 워크플로가 운영 다음에 같은 이미지로 부른다** (사용자 결정: 데모가 옛 이미지로 남아 새 봇이 안 보였고, 서버에는 GHCR 로그인이 없어 손으로 부르면 이미지를 받지 못한다. 데모 실패는 운영 배포를 실패로 만들지 않는다). `reset-demo.sh`는 떠 있는 데모의 이미지 태그를 읽어 받지 않고(`PULL=0`) 다시 띄운다. 데모 데이터는 예시라 운영 DB 백업(`backup.sh`)에 넣지 않는다. **시세 만드는 법이 바뀌면 시드가 스스로 처음부터 다시 채운다** (2026-10-09): DB의 예시 종가가 새로 만든 값과 하나라도 다르면 예시 봇·지난 시험·AI 판단·예시 시세를 지우고 다시 만든다 (옛 시세로 쌓은 기록이 새 시세와 어긋나지 않게). **예시 AI 판단 버전이 바뀌면 그 AI 봇만 고친다** (2026-10-22): 문장만 바뀌었으면 저장된 입력으로 문장만 다시 쓰고(몇 초), 비중 규칙이 바뀌었으면 그 봇만 지우고 1년치를 다시 채운다(몇 분, 봇 번호가 바뀜). 버전 규칙은 14절 "데모 판단 문장". 그 밖에는 매번 새로 채우지 않고 이어서 채운다. **시드는 이름이 같은 봇이 있으면 새로 만들지 않고 이어서 채우므로**(`DEMO_BOTS`의 값을 바꿔도 이미 있는 봇은 그대로) 예시 봇의 값만 바꿨을 때는 `bash deploy/reset-demo.sh`(Git Bash)로 운영 Postgres 안의 데모 데이터베이스만 지우고 다시 채운다 (2026-10-08, 운영 DB·Worker는 그대로, 방문자의 지난 시험 목록은 사라진다). 바깥 접속은 운영의 `cloudflared`가 `demo.trading-lab.me` → `http://demo-api:8000`으로 잇는다. 둘은 `quant-lab-edge` 네트워크만 함께 쓰고 운영 api·Worker는 그 네트워크에 없어 데모에서 닿지 않는다. Cloudflare 대시보드에서 터널에 Public hostname `demo`를 더하고 **Access 앱은 만들지 않는다** (누구나 본다. Access 앱은 `app.trading-lab.me`만 덮는다). **링크 미리보기 (2026-10-16):** `frontend/index.html`의 OG·트위터 카드 메타와 `public/og-image.png`(1200×630, 데모 화면)가 디스코드·슬랙·카카오톡 썸네일을 만든다. 운영·데모가 같은 이미지라 `og:url`·`og:image`는 크롤러가 받을 수 있는 데모 주소로 고정했다 (운영은 Access가 막아 어차피 못 본다). 이미지를 바꾸면 SNS 쪽 캐시 때문에 파일 이름이나 `?v=` 쿼리를 바꿔 다시 확인한다.


**예시 시세 (D1, 2026-10-09 업그레이드, `application/demo_prices.py`):** 하루하루의 값은 모두 난수로 만들고 큰 흐름만 실제 역사를 닮게 한다. 처음 판은 시장 하나의 움직임에 종목마다 베타만큼 따라가고 하락장을 기간에 고르게 나눠 얹어서, 흔들림이 늘 같고(초과 첨도 약 0, 4배 표준편차 날 0번) 급락이 일직선이며 하락장마다 성격이 같았다 (2020에 TQQQ가 2022보다 더 빠지는 등 실제와 거꾸로). 사용자 결정으로 나중에 아쉽지 않게 한 번에 고쳤다.

| 부분 | 만드는 법 |
| --- | --- |
| 큰 흐름 (2006-01 ~ 2025-04) | 미국 대형주 시장의 큰 고점·바닥 약 80개를 경유점(시작일 = 100, 대략)으로 두고 그 사이를 난수 흔들림으로 잇는다 (브라운 다리). 경유점마다 그 구간이 평소보다 몇 배 요동쳤는지(stress)를 둔다 (2017 0.4, 리먼 뒤 4.2, 2020년 3월 5). 실제 경유점은 구간의 고점·바닥이므로, 구간마다 흔들림을 최대 40번 다시 뽑아 경유점 바깥으로 3% 넘게 벗어나지 않는 것을 고른다. 일봉을 따라 그리지는 않는다 (그러면 실제 데이터를 숨겨 공개하는 셈) |
| 무리 | 기술주·반도체·금·한국·일본마다 큰 사건 때의 위치(경유점)를 두고 그 사이는 시장을 베타만큼 따라가며 맞춘다. NVDA도 자기 경유점을 둔다 (2008 -85%, 2022 -66%, AI 붐). NVDA는 반도체지만 나스닥100에서 큰 몫이라 기술주 무리에 둔다 (실제 상관 QQQ 0.74 > SOXL 0.67) |
| 잔결 | 흔들림 몰림(GARCH 0.06·0.91), 두꺼운 꼬리(t분포 자유도 6, 5배에서 자름). 위기에는 무리만의 흔들림이 덜 커지고(모두 함께 움직임), 종목만의 흔들림은 잔잔한 장에서도 줄지 않는다 (회사 소식은 매일 나온다) |
| 개별 사건 | 개별 주식(NVDA)은 2·5·8·11월 22일 무렵 실적 갭 (표준편차 약 5%, 시가에 전부) |
| 캔들 | 시가 갭은 그날 움직임의 일부(미국 40%, 금·한국·일본은 미국 장 밖에서 움직여 60%) + 흔들림 비례 난수, 꼬리 길이도 그날의 흔들림에 비례 |
| 2025-04 뒤 (가상의 미래) | 순한 상승장·보통 장이 1년 남짓마다 바뀌고(종목·무리의 기대 수익은 현실적으로: NVDA 연 15% 안팎), 평균 1년 반에 조정장(-10~18%), 6년에 하락장(-22~32%)이 날짜순 난수로 온다 (30년 모의: 연평균 약 9%, 조정 10번·하락장 4번, 연변동 19%). 실제 시장을 따라가지 않으므로(사용자 결정) 손볼 일이 없다. 실제 큰 사건을 넣고 싶을 때만 경유점을 더한다. 씨앗은 앞 1년 반이 무난한 것(-16% 조정 한 번)으로 골랐다 (같은 빈도라도 씨앗에 따라 지금이 폭락장 한가운데일 수 있다) |

지난 값은 바뀌지 않는다: 경유점 구간은 구간마다 따로 난수를 뽑고 미래는 날짜순으로만 뽑으므로, 시드가 6시간마다 오늘까지 다시 만들어도 앞의 값이 그대로다 (테스트). **실제 시장을 따라가게 하는 것은 하지 않는다** (2026-10-09, 사용자 결정: 늦게 반영하면 지난 값이 바뀌어 데모를 다시 채워야 하고, 토스 데이터를 공개 데모로 넘기는 통로가 필요하며, 데모는 실제가 아니라고 밝히고 있어 얻는 게 적다).

**맞춰 본 결과 (실제는 로컬의 토스 일봉 2년과 널리 알려진 역사, 비교 그림·수치는 이 PC에서만 보고 저장소에 넣지 않는다):** 연변동 VOO 17%(실제 16%)·QQQ 23%(21%)·NVDA 45%(44%), 고가~저가 폭/표준편차 1.05 안팎(실제 1.05), 시가 갭/표준편차 0.42(0.43), 상관 VOO-QQQ 0.94(0.95)·QQQ-NVDA 0.73(0.74)·VOO-GLD 0.18(0.17)·VOO-EWY 0.53(0.53). 하락장 깊이 TQQQ 2020 -73%(실제 약 -70%)·2022 -82%(약 -79%), NVDA 2008 -89%(약 -85%)·2022 -71%(약 -66%), QQQ 2020 -32%(약 -28%).

**120일 차트로 본 느낌 (2026-10-09 두 번째 손질, 사용자 리뷰):** 20년 통계가 맞아도 몇 달짜리 차트는 달라 보일 수 있어, 실제 최근 120일과 합성 120일 창 여럿을 세로축 폭을 같게 놓고 비교했다. 처음 판은 가상 미래의 기대 수익이 높아(NVDA 연 35% 안팎) 계단처럼 오르고, 실적 갭(7%)에 흔들림이 몰려 평소 날이 조용했다. 기대 수익을 낮추고(NVDA 연 15% 안팎), 실적 갭을 5%로, 잔잔한 국면의 흔들림을 실제 수준으로 올리고, 무리 흔들림을 장기 수준(한국 25%, 금 16%, 일본 13%)으로 맞췄다. NVDA 최근 창: 변동 38%(실제 39%), 몸통 1.12%(1.18%). 해 보고 되돌린 것: 경유점 바깥 허용 폭을 구간 길이에 비례해 넓히기 (폭락 구간 바닥이 경유점보다 깊어지고 2013년의 매끈함은 그대로였다). 남은 차이: 2013년처럼 경유점 사이가 크게 오른 순탄한 구간은 자로 그은 듯 매끈하다 (실제 2013 하반기도 6개월 +17%에 눌림 4% 안팎이었고, 여러 창의 오락가락 정도 중앙값은 실제와 같다 0.11·0.11). 한국·반도체의 최근 2년 흔들림(실제 68%·125%)은 실제가 유난히 컸던 때라 맞추지 않았다.
## 12. 서비스화하지 않는 이유 (2026-10-03 결정)

"나 카피 봇"은 여러 사람이 쓰는 서비스에도 어울리지만, **나를 대신해 투자하는 개인용 앱으로 확정한다.** 남에게 열려면 아래를 모두 풀어야 하는데, 첫 번째만으로도 개인 프로젝트 규모를 넘는다. 2026-10-02~03 웹 조사 기준이며 법률 자문은 받지 않았다.

| 걸림돌 | 내용 |
| --- | --- |
| **시세 데이터** | 토스 시세는 본인 매매 목적 한정, 비상업이어도 제3자 배포 금지 (tossApi.md 1절). 차트를 빼도 안 된다: 판단 정보("1년 최고가보다 8% 낮아요")도 토스 데이터로 계산한 결과라 남을 위한 계산에 쓰는 것 자체가 범위 밖이다. 무료 API(yfinance·Tiingo·Alpaca·Massive 등)는 대부분 개인·비상업·재배포 금지. 앱에 표시 가능한 계약은 **Tiingo 표시 재배포 월 $250(스타트업)**, EODHD B2B 월 $399부터다. TradingView 위젯은 공개 사이트에 무료로 넣을 수 있지만(로고 유지) 그림만 보여 줘서 숫자를 꺼내 계산할 수 없다 |
| **투자 자문 규제** | 사람마다 다른 매매 추천은 투자자문업(알고리즘 추천은 로보어드바이저 테스트베드까지)이다. "봇은 사용자를 복사할 뿐 추천하지 않는다, 결과는 지난 일로만 보여준다"면 도구로 볼 여지가 있지만, 봇이 종목·비율을 알아서 정하거나 매매 알림을 보내면 선을 넘는다 |
| **실거래 대행** | 남의 계좌로 자동 매매하면 투자일임업 등 인가 대상일 가능성이 크다. 증권사 파트너 API(예: Alpaca Broker API)와 인가가 필요하다 |
| **일본에서 낸다면** | 규제는 조금 유리하다: 투자 조언업(投資助言・代理業) 등록은 보수를 받는 조언이 대상이라 무료 도구나 누구나 살 수 있는 분석 소프트웨어는 등록 대상에서 빠진다는 해석이 일반적이다 (유료 회원제로 판단 정보를 주면 등록 필요, 남의 계좌 자동 매매는 투자운용업). 데이터는 똑같이 막힌다: 미국 주식은 같은 업체 계약, 일본 주식의 J-Quants(무료~월 ¥1,650)는 개인 사적 이용 한정이라 남에게 앱을 제공하려면 J-Quants Pro 계약이 필요하다 |
| **사용자 1명 구조** | 로그인·사용자 테이블 없음, Worker·토큰 1개. 로그인, 사용자별 데이터 분리, 개인정보처리방침이 필요하다 |

다시 검토한다면 출발점은 시세 업체에 "원시 가격은 보여주지 않고 파생 판단 정보만 표시, 차트는 TradingView" 구성으로 견적을 묻는 것이다. 코드 쪽은 `adapters/toss` 옆에 시세 어댑터를 하나 추가하면 되고, 사용자마다 Worker를 상시로 돌릴 필요도 없어 생각보다 작다.

## 13. 공개 데모 원칙 (2026-10-03)

포트폴리오로 외부에 보여줄 때 막히는 것은 실거래 여부가 아니라 **토스 시세를 남에게 보여주는 것**이다 (페이퍼 거래만 공개해도 화면이 토스 시세면 제3자 배포). 그래서 운영과 데모를 나눈다.

| | 운영 | 공개 데모 |
| --- | --- | --- |
| 시세 | 토스 | 합성 데이터, 또는 화면 표시가 허용되는 소스 (12절) |
| 거래 | 모의 + (마일스톤 3 이후) 실거래 | **모의만.** 실제 계좌 연결·실거래 경로는 꺼 둔다 |
| 접속 | Cloudflare Access, 본인만 (6절) | 누구나. 봇 여러 개가 미리 돌고 있는 상태로 보여준다 |

- **같은 이미지를 데모 모드로 하나 더 띄운다.** 별도 DB에 데모 시세를 채우고 Worker는 토스를 부르지 않는다 (`WORKER_MARKET_SOURCE=stored`와 같은 방식). 화면에는 "데모 데이터" 안내를 둔다. 데모에서는 봇 시작·멈춤·삭제를 막거나 주기적으로 초기화한다.
- **야후 차트 페이지를 따로 만들지 않는다.** yfinance는 비공식이라 공개 화면에 쓰기 어렵다. 실제 시장 차트가 꼭 필요하면 공식 임베드 위젯(TradingView 등, 이용 조건은 착수 시 확인)을 쓰고, 봇 계산은 데모 시세로 한다.
- **저장소는 비공개이고 모든 권리를 보유한다 (2026-10-22, 사용자 결정).** MIT를 걷어내고 `LICENSE`를 "All rights reserved"로 바꿨다: 코드·문서·설계의 사용·복제·배포를 허락하지 않고, 토스증권·Anthropic 등 외부 API와 데이터에 대한 권리도 주지 않는다 (토스 API를 쓰는 코드라 자유 라이선스는 위험하다). 공개 데모는 화면만 보여주며 코드 사용 허락이 아니다. 저장소를 누군가에게 보여주게 되면 그 전에 Git 이력에 비밀값이 없는지 점검한다. 실거래 구현은 실제 계좌 화면 대신 멱등성·비상 중지·소액 한도를 검증하는 테스트로 보여준다.
- **README 캡처는 데모 화면으로 다시 찍는다.** 지금 캡처의 차트도 토스 시세다.
- 실제 수익률은 공개하지 않는다. "이 봇을 따라 하라"로 읽히면 투자 권유처럼 보일 수 있다.

## 14. AI 봇 (마일스톤 4, 2026-10-06 결정)

**AI가 시장을 조사해 매일 판단하고, 정해 준 종목 안에서만 사고파는 봇.** 규칙 봇(나 카피 봇)은 그대로 두고 전략 하나(`ai_judge`)로 더했다. 종목은 관심 목록 10종목(VOO·QQQ·QLD·TQQQ·SOXL·NVDA·GLD·MAGS·EWY·EWJ)이고, 돈은 나 카피 봇과 같은 날·같은 금액을 매달 넣는다 (2026-10-06 사용자 결정). 단계와 실측은 roadmap.md "AI 퀀트봇".

**나누는 선: AI는 비중만, 나머지는 엔진**

| AI가 정하는 것 | 엔진이 정하는 것 (규칙 봇과 같은 규칙) |
| --- | --- |
| 종목과 현금 사이의 **목표 비중**(정수 %, 합 100), 종목마다 쉬운 말 이유 한두 문장, 오늘의 시장 요약 | 목표와 지금의 차이 → 팔 금액·살 금액(`trading.rebalance`), 자산의 2%보다 작은 차이는 그대로, 체결(판단 다음 거래일 시가, 팔기 먼저·사기 나중), 수수료·슬리피지, 위험 한도, 중복 방지, 매달 입금(`DepositPlan`) |

봇의 종목 비율은 쓰지 않는다(똑같이 나눠 저장만 하고 화면에 보이지 않는다). 목표가 0이면 남김없이 팔고, 판 돈이 들어올 것까지 어림해 살 금액을 맞춘다. 정해 주지 않은 종목을 말하거나 비중 합이 100이 아니면 형식 오류(`INVALID`)로 보고 그날은 지금 보유를 그대로 둔다 (원칙 5).

**하루 흐름 (Worker 평가 안에서)**

1. 평가가 체결·입금까지 한 뒤 그날(봇·판단일) 판단 기록이 없으면 모두 되돌린다.
2. 봇 행을 잠그지 않은 채 AI를 부른다 (30초 넘게 걸려서). 이번 달 비용이 상한 이상이면 부르지 않고 `OVER_BUDGET`으로 적는다.
3. 판단을 기록하고 처음부터 다시 평가한다. AI는 그날 체결·입금이 반영된 상태와 지난 판단을 보고, 같은 날을 다시 평가해도 AI를 다시 부르지 않는다.
4. 실패(네트워크·인증·거절·형식 오류)는 그날 판단 없음으로 끝난다. 봇을 `ERROR`로 바꾸지 않고 알림(`ai_judgment`, 비용 상한은 그달 처음 한 번만)을 보낸 뒤 다음 판단일에 다시 부른다. 한 달 비용이 상한의 80%를 넘는 판단에서는 미리 알림(`ai_budget_near`, 그달 한 번)을 보낸다. 돈이 드는 일이라 두 알림 모두 실제로 따라 하지 않는 AI 봇도 "실제 주문만" 범위에서 보낸다. 설정 맨 위 "AI 비용"에서 AI 봇마다 사용액·상한·월말 예상을 한눈에 본다 (2026-10-22). 같은 판단일은 다시 부르지 않는다 (매번 비용이 들고 결과가 달라질 수 있어서).

**입력 (시장분석 AI 봇은 토스 시세를 요약만 보낸다):** 종목마다 판단일 종가, 200일 평균 대비, 1년 최고가 대비, 1·3·12개월 수익률, 3개월 변동성, 지금 비중, 레버리지 배수와 봇의 자산·현금 비중·넣은 돈·매달 입금, 지난 판단, 지금 시각(`as_of`)을 넘긴다. 원본 일봉은 보내지 않는다 (토스 시세는 본인 매매 목적 한정, tossApi.md 1절. AI에게 보내는 것은 내 매매 판단을 위한 처리로 본다. 캔들분석 AI 봇은 이 선을 넘어 지수로 바꾼 일봉을 보낸다, 아래). 뉴스·금리·실적은 AI가 웹 검색으로 찾는다 (기본 검색 도구 `web_search_20250305`, 최대 5번, 검색 위치 미국, 미국 소식은 영어로·믿을 만한 경제 뉴스 우선, 같은 주제 재검색 금지, 막는 사이트: 위키백과·지역 뉴스·예측시장·질 낮은 전망 글). AI는 답에 **판단의 근거가 된 기사 주소(evidence) 3~6개**를 함께 낸다. 실제 검색 결과에 있는 주소만 인정하고(주소 표기 차이는 맞춰 비교), 화면은 근거 기사를 먼저, 나머지 검색 결과는 접어서 보여준다. 결과를 서버에서 걸러 주는 최신 검색 도구(`web_search_20260209`)는 AI가 기사 주소를 거의 보지 못해 근거를 1개만 댔고 같은 검색을 되풀이해서 쓰지 않는다 (2026-10-07 실측: 기본 도구 근거 5개·검색 3번·$0.147, 최신 도구 1개·5번·$0.188).

**피드백 (두 AI 봇 공통, 2026-10-09 사용자 요청, `domain/feedback.py`):** 최근 판단 5개(오래된 것부터, 마지막이 "지난 판단")마다 "그 비중대로 그날 종가에 들고 있었다면 오늘까지 몇 %"(result)와 "같은 현금 비중으로 레버리지가 아닌 종목을 똑같이 나눠 들고 있었다면 몇 %"(even)를 함께 넘긴다. 체결·입금은 빼고 판단 자체만 본다. 비교 기준에 레버리지와 0% 현금을 넣으면 오르는 장에서 늘 기준이 이겨 AI가 레버리지·현금 줄이기로 쏠릴 수 있어서, 현금 비중을 맞추고 레버리지를 빼 **종목 고르기만** 견주게 했다 (첫 실측에서 3배 종목이 들어간 기준이 +3.9% 대 +1.7%로 앞서는 것을 보고 고침). 지침은 며칠 결과로 뒤집지 말고 같은 방향으로 여러 번 빗나갈 때만 돌아보라고 한다. 캔들분석에는 날짜 없이 "N거래일 전"과 오늘 글자로 넘긴다.

**시장 분위기 (시장분석 AI 봇만, 2026-10-09):** CNN Fear & Greed 지수(0~100)의 오늘 값을 AI가 웹 검색으로 한 번 확인하고 요약에 쉬운 말로 적는다 (예: "시장 분위기 지수 45, 보통"). 공식 API가 없어 비공식 주소를 받아 오지 않고 검색으로 확인한다. 지수 하나로 비중을 크게 바꾸지 않는다. 실측: 검색 3번 → 4번, 판단 한 번 약 $0.18.

**판단 기록 (`ai_judgments`, 재현의 원본):** 봇·판단일마다 1행(유일 키), 지우지 않는다. 결과(`OK`·`FAILED`·`INVALID`·`OVER_BUDGET`)와 실패 이유, 넘긴 입력 요약, 모델 ID, 지침 버전, 목표 비중·이유·시장 요약·한 문장(`decision`)·근거(`basis`), 검색어와 출처(주소·제목·근거로 썼는지, 기사 본문은 저장하지 않음), 토큰·검색 횟수·비용. 기록된 판단을 순서대로 다시 적용하는 재생(`run_backtest(judgments=…)`)이 모의 운영과 같은 체결을 내는지 테스트한다 (원칙 3·9의 AI 봇 판). 판단 없이 AI 봇을 백테스트하면 거절한다.

**과거 백테스트를 하지 않는 이유:** 모델은 학습한 시점까지 시장이 어떻게 흘러갔는지 알고 있어, 과거 날짜로 판단을 시키면 미래를 아는 상태로 판단하게 된다. 그래서 AI 봇은 **시작한 날부터 앞으로만** 비교한다: 같은 날·같은 금액을 넣는 나 카피 봇 규칙과 매달 그냥 사기를 나란히 두고, 넣은 시점 반영 연 수익률(XIRR)과 지금 가치를 보여준다. 점수·판정은 붙이지 않는다 (1절).

**화면:** 봇 자세히 보기에서 오늘의 AI 판단(오늘 한 일 한 문장과 근거, 시장 요약, 종목마다 지금 → 목표 비중과 이유, 내일 낼 모의 주문, 검색어·기사 링크, 이 판단과 이번 달 비용), 이 AI 봇 vs 먼저 시작한 다른 AI 봇 vs 나 카피 봇(이 봇이 처음 판단한 날부터 같은 날·같은 돈. 이 봇 값은 기록된 판단 재생이라 모의 기록과 같고, 먼저 시작한 다른 AI 봇은 그날 이 봇의 시작 금액·입금으로 시작했다면을 그 봇의 기록된 판단으로 다시 돌린다. 나중에 시작한 AI 봇은 그 봇 화면에서 비교한다. 나 카피 봇 규칙은 지금 규칙으로 입금을 AI 봇과 같게 다시 계산), 판단 기록(최근 7일, 더 보기, 매매일지로 가는 링크). 위 자산 그래프의 기준선은 "관심 종목 N개 똑같이 나눠 매달 사기", 비교 카드의 "매달 그냥 사기"는 나 카피 봇 종목을 샀다면(나 카피 봇이 없으면 관심 종목을 똑같이 나눠)이라 이름에 무엇을 샀는지 밝힌다. 시험해 보기에는 AI 봇이 없는 이유를 한 줄로 알리고 이 비교로 이끈다. 봇 목록의 "AI 봇" 묶음에서 아직 없는 종류(시장분석·캔들분석)마다 한 줄 설명과 [+ 만들기]로 만든다 (관심 종목 전부, 입금은 나 카피 봇과 같게, 이름은 "시장분석 AI 봇"·"캔들분석 AI 봇"). 비교 카드와 그래프의 이름은 봇 이름이다. 캔들분석 AI 봇은 검색어·기사가 없고 "종목 이름과 날짜를 가린 가격 차트만 보고 판단해요"를 알린다. 이번 달 비용은 그 봇 전략의 합과 상한이고, 봇 설정에도 보인다. API `GET /api/bots/{id}/ai`·`/ai/compare`.

**실제로 따라 하기 (2026-10-07, 사용자 결정: 바로 실제 돈으로):** 마일스톤 3의 안전장치(실거래 스위치·1/100·한도·대조·비상 중지)를 그대로 쓴다. 사기는 모의 매수 금액 × 1/100 (모으기 봇 한도 1건 $20·한 달 $50, $1 미만은 모아 두었다가 함께). 팔기는 이 봇이 실제로 산 수량에서 모의 보유 중 판 비율만큼 (`domain/live.partial_sell_qty`, 판 금액 $1 미만이면 넘김). 켜기 전의 모의 보유는 실제로 없으므로 그 몫의 팔기 신호는 "실제로 산 주식이 없음"으로 넘긴다. 레버리지는 QLD·TQQQ만.

**경계와 비용**

- 엔진은 `domain/advisor.py` 규약(입력 요약 → 판단)만 알고, Claude API 호출·웹 검색·구조화 출력·요금표·모델 이름은 `adapters/claude` 안에만 둔다 (증권사와 같은 방식, 4절). 엔진·저장소·API·화면 이름에 공급자 이름이 들어오면 구조 테스트가 실패한다.
- 호출은 Worker만 한다. 키는 `.secrets/worker.env`의 `ANTHROPIC_API_KEY`(worker 컨테이너에만). 키가 없으면 AI 봇은 판단하지 않고 이유를 남긴다.
- 모델은 Claude Sonnet 5.5 (거절되면 서버가 다른 모델로 이어 답하고 그 모델 이름·요금으로 기록). 판단 한 번 실측 $0.07~0.14, 매일이면 한 달 약 $2~3. **한 달 비용 상한**(시장분석 `AI_MONTHLY_BUDGET` 기본 $15, 캔들분석 `AI_CANDLE_MONTHLY_BUDGET` 기본 $5, 판단 기록의 전략으로 따로 센다)을 넘으면 그달 남은 날은 판단하지 않는다. 요금은 입력 100만 토큰 $2·출력 $10, 웹 검색 1,000번 $10 (2026-10-06 기준).

**데모:** 데모에는 AI 키가 없다. `application/demo_advisor.py`가 정해진 규칙(레버리지 아닌 종목 중 200일 평균 위·3개월 수익 플러스인 것을 5개까지, 변동성 역수 비율, 한 종목 30%까지, 현금 20% 이상, 담을 종목이 같으면 지난 비중 유지)으로 같은 규약의 예시 판단을 만들고, 화면은 "예시 판단"이라고 알린다. 근거는 데모 가격에 맞춰 지어낸 "예시 뉴스"다 (아래 "판단 근거를 매매일지에"). `seed-demo`가 예시 AI 봇을 1년 전부터 돌려 둔다 (하루 평가가 무거워 다른 예시 봇의 2년보다 짧게).

### 판단 규칙 한눈에: 지켜지는 규칙과 부탁하는 규칙 (2026-10-22)

사용자 요청: AI 봇이 어떤 규칙으로 움직이는지 알고리즘으로 정리한다. **AI 봇은 비중을 정하는 한 단계(아래 3)만 AI에 맡기고 나머지는 모두 코드 규칙이다.** AI의 답은 같은 입력에도 흔들리므로, 그 한 단계를 정해진 규칙으로 바꾸면 같은 입력에 늘 같은 답을 내는 알고리즘 봇이 된다 (데모의 `application/demo_advisor.py`가 그렇게 만든 예다).

```text
매일 미국 장 마감 뒤, AI 봇마다:

1. 입력 만들기 (domain/advisor.make_request)
   판단일 = 모든 종목의 마지막 일봉 날짜, 상장 21일 미만 종목은 뺀다
   종목마다 종가·200일 평균 대비·1년 최고가 대비·1·3·12개월 수익률·3개월 변동성·지금 비중·레버리지 배수
   봇의 자산·현금 비중·넣은 돈·매달 입금·지난 판단, 최근 판단 5개의 결과(피드백)
   캔들분석이면 이름·날짜·가격을 가린다 ("종목 A~J", 판단일 종가 = 100인 지수, 일봉 90·주봉 52)

2. 부를지 정하기 (application/ai_judge.judge_bot)
   그날 판단 기록이 있음        → 아무것도 안 함 (하루 한 번)
   AI 키 없음·판단할 종목 없음 → FAILED
   이번 달 그 전략 비용 ≥ 상한 → OVER_BUDGET (그달 처음만 경고)

3. AI 판단  ← 여기만 AI (같은 입력에도 답이 흔들린다)
   시장분석: Sonnet 5.5, 웹 검색 최대 5번 / 캔들분석: Opus 5.5, 차트 그림 + 요약, 검색 없음
   답은 JSON 형식으로 강제한다: 종목(+CASH)마다 정수 비중·이유, 요약, 한 문장, 근거

4. 답 검사 (domain/advisor.check_advice)
   정해 주지 않은 종목 / 0~100 밖 / 합 ≠ 100 → INVALID
   캔들분석은 글자를 종목으로 되돌린다. 실제 검색 결과에 없는 기사 주소는 버린다
   기록한다. 이번 판단으로 한 달 비용이 상한의 80%를 처음 넘으면 미리 알린다

5. 주문 만들기 (domain/trading.rebalance)
   OK가 아니면 모두 그대로 둔다
   band = max(최소 주문 금액, 자산 × 2%)
   보유 중인데 목표 0 → 전부 팔기 / 보유 - 목표 ≥ band → 팔기 / 목표 - 보유 ≥ band → 사기 / 그 밖 → 그대로
   살 돈 = 현금 + 판 돈(수수료·슬리피지 뺀 어림), 모자라면 사기를 비율대로 줄인다
   최소 주문 금액·위험 한도에 걸린 사기는 그대로 두고 차단 이유를 남긴다

6. 체결: 다음 거래일 시가, 팔기 먼저 → 사기
```

| 구분 | 규칙 | 어기면 |
| --- | --- | --- |
| **코드가 지키는 규칙** (늘 지켜진다) | 봇·판단일마다 판단 한 번, 한 달 비용 상한, 정해 준 종목과 현금만, 비중은 0~100 정수·합 100, 지어낸 기사 주소는 버림, 자산 2%보다 작은 차이는 사고팔지 않음, 팔기 먼저, 살 돈이 모자라면 비율대로 줄임, 최소 주문 금액·위험 한도, 다음 거래일 시가 체결 | 그날 판단 없음(`INVALID`·`FAILED`·`OVER_BUDGET`) → 보유를 그대로 둔다. 한도에 걸린 주문은 막는다 |
| **AI에게 부탁하는 규칙** (지침, `adapters/claude`) | 지난 판단 유지가 기본이고 분명한 이유가 있을 때만 바꾼다, 시장 분위기 지수 하나로 크게 바꾸지 않는다, 피드백 한두 번으로 뒤집지 않는다, 레버리지는 하락장에서 손실이 커진다, 믿을 만한 뉴스만 근거로 쓴다(시장분석), 종목을 짐작하지 않고 차트만 본다(캔들분석) | 코드가 검사하지 않는다. 같은 입력에도 비중이 흔들린다 (캔들분석 실측 8~14%p, 아래 "모델") |

부탁하는 규칙 중 코드로 옮길 수 있는 것(예: 하루에 바꾸는 비중의 상한, 레버리지 종목 합계 상한)을 옮기면 흔들림의 폭을 코드로 묶을 수 있다. 다만 비중 자체를 규칙으로 정하면 그 봇은 AI 봇이 아니라 알고리즘 봇이고, 과거 백테스트도 할 수 있게 된다 (AI 봇은 미래를 아는 상태로 판단하게 되어 하지 않는다, 위 "과거 백테스트를 하지 않는 이유").

**지금처럼 둔다 (2026-10-22 사용자 결정):** AI 봇은 AI의 판단과 그 흔들림을 지켜보는 봇으로 둔다. 비중을 규칙으로 정하면 백테스트를 돌리며 더 나은 규칙을 찾는 일이 되고, 그것은 나 카피 봇 같은 규칙 봇의 몫이다. 그래서 부탁하는 규칙을 코드로 옮기지 않는다.

### 판단 근거를 매매일지에 (2026-10-22)

사용자 요청: AI 봇의 판단을 "이런 근거로 이렇게 투자했다"로 알기 쉽게 남긴다 (두 AI 봇 모두). 답에 두 칸을 더 받는다: **`decision`**(오늘 무엇을 어떻게 했는지 한 문장, 바꾸지 않았으면 그렇다고)과 **`basis`**(그렇게 정한 근거 2~4개). 두 칸이 빠져도 판단은 쓴다 (비중이 본체). 그 전 판단은 매매일지에서 시장 요약을 근거 자리에 보여준다.

- **두 봇의 근거는 종류가 다르다 (지침 `2026-10-22.2`·`candle-2026-10-22.2`, 사용자 지적: 기록만 보면 두 봇이 같아 보인다).** 시장분석 AI 봇의 근거는 **뉴스**다: 줄마다 기사에서 확인한 소식(금리·물가·실적·정책·큰 사건)과 그것이 종목에 어떤 뜻인지, 그리고 그 기사 주소를 `{text, url}`로 답한다. 주소는 실제 검색 결과에 있을 때만 그 주소·제목을 남기고(`_cite`), 없으면 비운다. 가격 지표만으로 된 근거는 종목 이유(`reason`)에 쓴다. 캔들분석 AI 봇의 근거는 **차트**에서 본 것만이고 출처가 없다. 저장은 `ai_judgments.basis = [{text, url, title}]` (`.1` 지침의 판단은 글자만 있는 목록이라 읽을 때 맞춘다). 매매일지·오늘의 AI 판단은 줄 끝에 기사 사이트(누르면 기사)를 단다.
- **반복 문장 없애기:** 무엇을 했는지는 `decision`에 있으므로 근거마다 "그래서 ~했어요"를 붙이지 말고 문장 모양을 매번 똑같이 쓰지 않게 했다. 종목 이유는 소식·지표를 먼저 쓰고 비중을 어떻게 했는지로 끝낸다.
- **데모 (2026-10-22 사용자 결정):** 데모의 시장분석 예시 판단은 데모 가격 흐름에 맞춰 **지어낸 "예시 뉴스"**를 근거로 단다 (시장 분위기·가장 강한 종목·약해진 종목, 시장이 내린 달은 금리 걱정 같은 식). 실제 매체 이름·기사 주소는 쓰지 않고 출처 자리에 "예시 뉴스"라고 밝힌다. 캔들분석 예시 판단은 오르는 종목을 한 줄로 묶고 약해진 종목을 한 줄로 쓴다 (차트만).
- **데모 판단 문장 (2026-10-22 사용자 결정):** "예시 판단"이라는 안내는 화면(오늘의 AI 판단, 매매일지 머리)에 한 번만 두고, 판단 문장(summary)에는 넣지 않는다. 문장은 실제 봇과 같은 말투로 쓴다. 시장분석은 시장 분위기 지수(데모 가격의 한 달 수익·200일 평균과의 거리로 만든 예시) → 시장 흐름 → 가장 강한·약한 종목 → 한 일 순서다. 캔들분석은 전체 차트 모양 → 강한·약한 종목 → 한 일 순서다. 예시 판단 버전은 "규칙.문장"이다 (`demo-2`, `demo-candle-2`, 문장 번호가 없으면 처음 문장). `seed-demo`가 예전 버전 판단을 고친다.
  - **문장만 바꿀 때:** 뒤 번호만 올린다 (`demo-2.1`). 그러면 `seed-demo`가 저장된 입력(`ai_judgments.request`)으로 예시 판단을 다시 내어 문장(summary·decision·basis·reasons)만 바꾼다. 몇 초면 끝나고 봇 번호도 그대로다. 다시 낸 비중이 기록과 하나라도 다르면 거래가 달라지므로 문장만 바꾸지 않고 아래처럼 다시 채운다.
  - **비중 규칙을 바꿀 때:** 앞을 올린다 (`demo-3`). 그러면 그 예시 AI 봇을 지우고 1년치를 처음부터 다시 채운다 (몇 분 걸리고 봇 번호가 바뀐다).
  - AI 판단 기록은 원래 고치거나 지우지 않는다. 데모 DB의 예시 판단만 예외다.

### 캔들분석 AI 봇 (2026-10-08 설계·구현·운영 시작, 현재 관찰 중)

이 절의 위쪽은 공통 뼈대(나누는 선·하루 흐름·판단 기록·실제로 따라 하기·경계와 비용)와 **"시장분석 AI 봇"**(뉴스·금리·실적을 웹 검색으로 조사)을 함께 적었다. 캔들분석 AI 봇은 **같은 뼈대에 입력과 지침만 다르다:** 별도 전략(`ai_candle`)이고 이름표는 "캔들분석 AI 봇", 종목은 같은 관심 10종목, 입금은 나 카피 봇과 같다. 봇은 전략마다 하나라서(9절) 시장분석 AI 봇과 각각 하나씩 만든다.

**왜 만드나:** 이 봇이 보태는 것은 10종목을 서로 견주어 한꺼번에 비중을 정하는 판단과, 공식으로 짜기 어려운 캔들 모양 읽기다 (나 카피 봇의 규칙은 종가 몇 개만 본다). 확인하려는 것은 "같은 가격만 보고 AI가 내 규칙보다 나은가"이고, 비교 대상은 나 카피 봇·시장분석 AI 봇·매달 그냥 사기다. 기업 가치·뉴스는 이 봇에 넣지 않는다: 그것은 시장분석 AI 봇의 몫이고, 입력을 섞으면 어느 쪽 덕인지 알 수 없다.

**입력 (익명 숫자 표로 생성한 차트 그림 + 짧은 요약):**

| 항목 | 정한 것 |
| --- | --- |
| 형식 | **차트 그림 + 짧은 숫자 요약** (2026-10-09 바꿈, 아래 "입력 형식 실험"). 종목마다 익명 표로 직접 그린 800×500 PNG 한 장(위 일봉·아래 주봉, 빨강 오른 봉·파랑 내린 봉, 세로축은 오늘 = 100인 지수, `adapters/charts.py`)과 요약 6개(20일·60일 전 대비, 90일 최고·최저가 대비, 52주 최고가 대비, 최근 20일 하루 평균 움직임). 남의 차트 화면을 캡처하지 않는다 (약관·깨짐). 거래량은 뺀다 (미국 거래량 신뢰도가 낮다, tossApi.md 1절). 판단 기록에는 그림 대신 익명 표를 남긴다 (같은 표면 늘 같은 그림) |
| 봉 수 | 종목마다 일봉 90개 + 주봉 52개 |
| 가격 | 판단일 종가를 100으로 맞춘 지수 (실제 가격은 보이지 않는다) |
| 종목·날짜 | 이름을 가려 "종목 A~J"로 부르고 순서를 섞는다. 날짜는 "N일 전"으로만 보인다. 서버가 판단을 받은 뒤 글자를 종목으로 되돌린다 |
| 레버리지 | 배수(2배·3배)만 알린다. 위험 판단에 필요하고 종목이 특정되지 않는다 |
| 그 밖 | 지금 비중·현금·지난 판단은 시장분석 AI 봇과 같다. 웹 검색 도구는 주지 않는다 |

**익명화와 되돌리기 (`domain/candles.py`):** `make_request(candles=True)`가 같은 종목으로 익명 입력을 만든다. 글자 순서는 판단일로 섞어 같은 날을 다시 만들면 같은 표가 나온다. 지난 판단도 오늘 글자로 바꾸고, 지금 종목이 아닌 이름은 넘기지 않는다. 캔들 공급자(`CandleAdvisor`)는 익명 입력만 받는다: 엔진이 `Unmasking`으로 감싸 답의 글자를 종목으로, 이유·요약 문장의 "종목 X"를 종목 이름으로(뒤 조사도 받침에 맞게) 되돌린 뒤 시장분석 AI 봇과 같은 규칙으로 검사한다. "종목 X"가 아닌 꼴로 쓴 글자는 그대로 둔다 (틀린 이름이 들어가는 것보다 낫다). 판단 기록의 입력에는 AI가 본 표와 대응표(`candles`)를 함께 남긴다.

**지침 요지 (`adapters/claude/candles.py`, 웹 검색 도구 없음):** 가격 모양·추세·변동성·종목끼리의 강약만 근거로 쓴다. 종목이 무엇인지 짐작하거나 아는 시장 이야기를 근거로 쓰지 않는다. 다른 종목은 꼭 "종목 B" 꼴로 부른다 (되돌리기가 이 꼴만 바꾼다). 읽는 사람은 지수를 모르므로 차트 숫자 대신 "오늘보다 12% 높았던 곳"처럼 쓴다 (첫 실측에서 "112까지 올랐다가"처럼 지수가 그대로 나와 더했다). 형식(정수 % 합 100, 종목마다 쉬운 말 이유)은 시장분석 AI 봇과 같다.

**판단 전 일봉 검사:** 시장분석 AI 봇과 같이 최근 23개 봉만 본다 (오래된 이상치 하나로 봇이 오래 멈추지 않게). AI가 보는 1년 구간의 이상 봉은 막지 않는다. 2026-10-08 실제 관심 10종목의 1년 구간을 검사했을 때 문제는 없었다.

**평가: 시작한 날부터 앞으로만.** 이름과 날짜를 가려도 NVDA·TQQQ 같은 유명한 모양은 모델이 알아볼 수 있어서 익명화는 과거 백테스트의 오염을 줄일 뿐 없애지 못한다. 그래서 과거 백테스트로 성과를 말하지 않는다 (위 "과거 백테스트를 하지 않는 이유"와 같다). 점수·판정은 붙이지 않는다.

**모델: Claude Opus 5.5, 생각하는 양 중간 (2026-10-09 결정, 일관성 시험):** 실제 토스 일봉으로 서로 다른 시장 상황 5개 날짜에 같은 익명 입력을 설정마다 3번씩 물었고, Opus high는 한 번 더 돌려 6번씩 모았다. 다시 물을 때마다 바뀌는 비중 평균: Sonnet 5.5 high 13.9%p, Opus 5.5 high 9.9%p(6번), Opus 5.5 medium 8.2%p. Opus는 5개 날짜 중 4개에서 Sonnet보다 덜 흔들렸다(약 30% 적음). **같은 설정을 다시 돌려도 7.3%p와 11.7%p로 달라질 만큼 시험 오차가 커서**, Opus high와 medium의 차이(1.7%p)는 구분되지 않는다 (같은 날 high·medium 판단 사이 거리 11.6%p도 한 설정 안의 흔들림과 비슷). 두 모델 모두 이유는 실제 수치와 맞게 읽었고(90일 고점, 하락일 등) 형식 오류는 없었다. 같은 차트에 크게 흔들리면 이유 없는 매매와 실제 주문이 잦아지므로 Opus를 쓰고, 생각하는 양은 high·medium이 오차 안에서 같아 출력이 조금 적은 중간으로 정했다 (사용자 결정) (시험 비용 $3.15 + $4.20). **어느 모델이든 같은 차트에 8~14%p 흔들리는 것이 지금 캔들분석의 한계다** (줄일 후보: 비중 단위를 거칠게, 여러 번 받아 평균, 입력 형식 조정: 아래 그림 + 요약 방식을 적용했다). 두 모델 모두 많이 오른 종목을 쫓기보다 흔들림이 작은 종목에 나눠 담는 편이었다.

**입력 형식 실험 (2026-10-09, Opus 5.5 medium, 5개 날짜 × 3번):** 다시 물을 때 바뀌는 비중이 숫자 표 11.5%p(앞선 시험과 합치면 약 9.9%p), 그림만 10.7%p, **그림 + 짧은 요약 8.0%p**. 시험 오차(±3~4%p)를 생각하면 "숫자 표보다 나쁘지 않다"가 정확하지만, 입력이 약 2.5만 토큰에서 약 8천 토큰으로 줄어 판단 한 번이 $0.135에서 $0.06으로 준다. 세 방식 모두 이유는 실제 수치와 맞았고(급락장의 GLD 고점 대비 약 5%, 90일 고점 등) 그림 쪽은 "아래꼬리가 긴 봉"처럼 캔들 모양도 짚었다. 정보는 같지만(그림은 같은 숫자로 그린다) AI가 긴 숫자 열보다 그림에서 모양을 더 쉽게 읽고, 정확한 값은 요약이 채운다. 그림 그리기는 서버에서 하므로 AI 비용이 없다 (실험 비용 $3.80).

**비용:** 입력 약 8.4천~8.8천 토큰(그림 10장 약 5.3천 + 글), 출력 약 1.3천 토큰으로 판단 한 번 약 $0.06. 매일(한 달 약 21거래일)이면 약 $1.3. **한 달 비용 상한은 시장분석 AI 봇과 따로 둔다** (가안: 캔들분석 $5). 상한은 `AI_CANDLE_MONTHLY_BUDGET`(기본 $5)이고 판단 기록의 전략으로 시장분석 AI 봇과 따로 센다. 봇 화면의 이번 달 비용도 그 봇 전략의 합이다. **생각하는 양(effort)은 중간:** 판단 기록의 지침 버전에 생각하는 양을 함께 남긴다 (`candle-…/medium`, 그 전 판단은 `/high`).

**실제로 따라 하기:** 한다 (사용자 결정). 마일스톤 3 안전장치(실거래 스위치·1/100·한도·대조·비상 중지)를 시장분석 AI 봇과 똑같이 쓴다. **시작:** 봇을 만들어 시작을 누른 순간부터다 (그날부터 앞으로만 비교한다).

**데모의 예시 판단 (확정, 2026-10-08 사용자 결정):** AI 키가 없으므로 시장분석 데모 봇처럼 규칙으로 만든 예시 판단을 `Advisor` 규약 뒤에 둔다 (화면은 "예시 판단"이라고 알린다). 데모도 실제 봇과 같은 익명 숫자 표를 받아 익명화·지수화·글자 되돌리기를 똑같이 거친다. 규칙: 배수 1배 종목 중 지수가 90일 평균 위이고 최근 20일 수익이 플러스인 것 상위 4개, 한 종목 30%까지·현금 20% 이상, 담을 종목이 같으면 지난 비중 유지 (시장분석 데모의 200일 평균·3개월 수익·변동성 역수와 겹치지 않게 표 안의 최근 모양만 쓴다). 숫자는 구현 때 데모 시세에 맞춰 고친다. 실제 운영 봇의 판단을 데모에 옮기지 않는다 (13절). `seed-demo`가 예시 캔들분석 AI 봇도 시장분석 예시 봇처럼 1년 전부터 돌려 둔다.

**정하지 않은 것:** 마일스톤 번호.

### 시장분석 AI 봇에 기업 분석 더하기 (계획, 2026-10-08 방향)

**방향:** 기업 가치·실적을 보는 일은 캔들분석 AI 봇이 아니라 **시장분석 AI 봇의 몫**이다. 캔들분석은 가격만, 시장분석은 정보(뉴스·금리·기업)를 보게 나눠야 두 봇의 차이가 "어떤 정보를 쓰는가"로 남는다.

**지금:** 시장분석 AI 봇의 지침은 이미 "실적"과 "각 종목에 관한 최근 소식"을 찾으라고 한다. 하지만 종목마다 무엇을 볼지 정해 주지 않아 시장 전체 뉴스 위주로 읽는다. 또 종목 10개 중 개별 기업은 NVDA 하나뿐이라 기업 분석이 닿는 범위가 좁다 (효과는 다종목 자동 실행으로 개별 종목이 늘 때 커진다).

**더할 것 (지침 `adapters/claude/advisor.py` SYSTEM과 검색 횟수만 바뀐다, 엔진·규약·화면 틀은 그대로):**

| 종목 | 볼 것 |
| --- | --- |
| 개별 기업 (NVDA) | 최근 분기 실적이 예상보다 어땠는지(매출·이익), 다음 분기 전망, 다음 실적 발표일, 값이 비싼 편인지(주가수익비율), 큰 사업 소식 |
| 주제 ETF (MAGS·QQQ·SOXL·QLD·TQQQ) | 이름만 보지 말고 담은 상위 기업 몇 개의 실적과 전망 |
| 나라 ETF (EWY·EWJ) | 그 나라 경제와 환율, 정책 |
| GLD | 금리·달러·안전자산 수요 |
| VOO | 시장 전체 실적 흐름 |

실적 발표 주간의 종목을 먼저 본다. 근거(evidence)는 지금처럼 검색 결과에 나온 기사 주소만 인정하고, 많이 담거나 바꾼 종목은 그 종목의 기업 기사를 하나 이상 요구한다. 말투는 쉬운 말을 유지한다 (1절).

**비용:** 검색 한도를 5번에서 8번으로 올리고 읽는 글이 늘어 판단 한 번이 $0.07~0.14에서 $0.15~0.25쯤으로 늘 것으로 어림한다 (한 달 $3~5, 상한 $15 안. 적용 뒤 실측으로 고친다). 재무제표 같은 별도 데이터 원천은 더하지 않는다: 웹 검색으로 충분한지 먼저 본다.

**언제:** 하고 싶을 때 지침 버전(`PROMPT_VERSION`)을 올려 적용한다 ("마일스톤 4를 지켜보는 동안 지침을 바꾸지 않는다"는 2026-10-09에 없앴다, 10절). 판단 기록에 지침 버전이 남으므로 "언제부터 기업 분석을 봤는지"는 기록으로 구분되고, 비교 화면에 지침이 바뀐 날을 표시한다. 시작한 날부터 앞으로만 보는 평가라 과거 오염 문제는 없다.

## 참고 자료

- [토스증권 Open API](https://developers.tossinvest.com/) — 조사 요약은 [tossApi.md](tossApi.md)
- [한국투자증권 Open API 예제](https://github.com/koreainvestment/open-trading-api) — 미국 주식 거래 흐름 참고용. 토스 형식에 그대로 대입하지 않는다
- [tossinvest-cli](https://github.com/JungHoonGhae/tossinvest-cli) — API 탐색 참고. 실행 의존성으로 쓰지 않는다
- [Lightweight Charts](https://tradingview.github.io/lightweight-charts/), [exchange_calendars](https://github.com/gerrymanoim/exchange_calendars), [Tailscale serve](https://tailscale.com/kb/1312/serve)
