# 토스증권 Open API 조사

> 출처: 공식 문서 `https://openapi.tossinvest.com/openapi-docs/` (overview.md, faq.md, OpenAPI JSON **v1.2.19**). 조사일 2026-10-01.
> 이 문서는 **공식 문서에 적힌 사실**과 **직접 호출로 확인한 사실**을 구분해 적는다. 확인 전 항목은 `미확인`으로 둔다.
> 프로젝트 설계는 [project.md](project.md), 일정은 [roadmap.md](roadmap.md).

## 1. 한눈에 보기

| 항목 | 내용 | 프로젝트 영향 |
| --- | --- | --- |
| 인증 | OAuth 2.0 Client Credentials. `POST /oauth2/token` | refresh token 없음 → 만료 전 재발급 |
| 토큰 수명 | `expires_in` = **86399초 (24시간)** ✅ | 만료 1시간 전 재발급 |
| **토큰 개수** | **클라이언트당 유효 토큰 1개.** 새로 발급하면 이전 토큰은 즉시 `401 token-revoked` | **토큰은 Worker 한 곳만 발급·보유.** 로컬 개발과 서버가 같은 client를 쓰면 서로 무효화 |
| **허용 IP** | 등록되지 않은 IP는 REST `403`, WebSocket handshake `403`. 클라우드 대역이라고 차단하지는 않음 | 고정 공인 IP 필수. 등록 가능 개수·변경 절차는 `미확인` |
| 시세 범위 | 국내·미국 주식 시세, 종목 정보, 환율, 장 운영 시간 | 관심 목록 10종목 모두 `ACTIVE`로 조회됨 ✅ (7절) |
| 미국 시세 원천 | **일부 미국 거래소 기준, NBBO 아님.** 세션별로 원천이 다를 수 있음 | 거래량 지표 신뢰도 낮음. 이상 고가·저가 필터 필요 |
| 캔들 | `1m`, `1d`만. 요청당 최대 200개, `before` 페이지네이션 | QQQ 일봉 전체(6934개) 35회 호출 |
| 과거 데이터 | 문서: 미국 2021-11-30 이후. **실측: 일봉은 상장일부터 (QQQ 1999-03-10, VOO 2010-09-09), 1분봉은 2021-12 무렵부터** ✅ | 일봉 장기 백테스트 가능 (닷컴·2008·2020·2022 포함) |
| **진행 중 일봉** | 미국 날짜 D의 일봉은 정규장 전부터 데이마켓·프리마켓 체결로 채워져 내려오고, 정규장 이후 정규장 값으로 바뀐다 (실측) | **D일 정규장 마감 + 여유 시간 전에는 D일 일봉을 쓰지 않는다** |
| 수정주가 | 기본 `adjusted=true`. 가격 × 비율 반올림, 거래량 ÷ 비율 버림 | 기업행동 발생 시 캐시 재수집 필요 |
| 과거 정정 | 과거 캔들은 사후 정정·동기화 없음 | 단, 수정주가 반영으로 값이 바뀔 수 있음 |
| 상장폐지 | 과거 시세 조회 불가 (`404`) | 생존 편향 존재 (MWP 종목에는 영향 적음) |
| 샌드박스·모의투자 | 문서에 없음 | 내부 DRY RUN을 직접 구현 |
| 데이터 이용 정책 | **본인 매매 목적 한정. 비상업이어도 제3자 배포 금지** | 대시보드는 비공개(Tailscale). 받은 시세 데이터를 Git·공개 위치에 올리지 않음 |

## 2. 시작 절차 (공식)

1. 토스증권 WTS 로그인 → 설정 > Open API에서 `client_id`, `client_secret` 발급
2. 같은 화면 하단 **허용 IP 관리**에서 호출할 공인 IP 등록
3. `POST /oauth2/token` (form-urlencoded: `grant_type=client_credentials`, `client_id`, `client_secret`)
4. 모든 호출에 `Authorization: Bearer {access_token}`. 계좌·주문·조건주문 API는 `X-Tossinvest-Account: {accountSeq}` 추가

Base URL: `https://openapi.tossinvest.com`, WebSocket: `wss://openapi-ws.tossinvest.com/ws/v1`

## 3. MWP에서 쓰는 엔드포인트

| 엔드포인트 | 용도 | Rate limit 그룹 (초당) |
| --- | --- | --- |
| `POST /oauth2/token` | 토큰 발급 | `AUTH` 5 |
| `GET /api/v1/candles` | 1분봉·일봉 | `MARKET_DATA_CHART` 20 |
| `GET /api/v1/prices` | 현재가 (최대 200종목) | `MARKET_DATA` 15 |
| `GET /api/v1/stocks` | 종목 정보 (상장 상태, 레버리지 배수 등) | `STOCK` 5 |
| `GET /api/v1/market-calendar/US` | 미국 장 운영 시간 | `MARKET_INFO` 3 |
| `GET /api/v1/exchange-rate` | KRW↔USD 환율 (화면 표시용, 선택) | `MARKET_INFO` 3 |
| `GET /api/v1/commissions` | 매매 수수료율 (비용 가정 근거) | `ORDER_INFO` 6 · 계좌 헤더 필요 |

한도는 사전 공지 없이 바뀔 수 있다. 모든 응답의 `X-RateLimit-Limit/Remaining/Reset` 헤더를 기록하고, `429`면 `Retry-After`만큼 기다린 뒤 지수 백오프와 jitter를 적용한다.

### 캔들 `GET /api/v1/candles`

| 파라미터 | 값 |
| --- | --- |
| `symbol` (필수) | US는 티커 (`VOO`). `[A-Za-z0-9.-]` |
| `interval` (필수) | `1m` \| `1d` |
| `count` | 1–200, 기본 100 |
| `before` | ISO 8601, **inclusive**. 응답의 `nextBefore`를 그대로 전달. `+`는 `%2B`로 인코딩 |
| `adjusted` | 기본 `true` |

응답 `result.candles[]`는 **최신순(내림차순)**이다. 필드는 `timestamp`, `openPrice`, `highPrice`, `lowPrice`, `closePrice`, `volume`, `currency`이며 **가격·거래량은 decimal 문자열**이다 (float 변환 금지, `Decimal`로 파싱).

봉 시각 규칙:

- `1m`: **봉 종료 시각.** `[timestamp − 1분, timestamp)` 구간을 집계한다. 따라서 `timestamp <= now`인 봉도 막 끝난 직후에는 늦게 도착한 체결이 반영되지 않았을 수 있다. 완료 판정은 `timestamp + 여유 시간 <= now`로 한다.
- `1d`: 해당 거래일의 **현지 자정**. 미국 일봉의 OHLC는 **정규장 공식 종가 기준**이며 프리·애프터·데이마켓 체결은 포함하지 않는다. 거래량은 시간외가 섞일 수 있다.
- 1분봉 합계로 일봉을 재구성할 수 없다 (집계 범위가 다름). 일봉 전략은 일봉 API를 직접 사용한다.
- 체결이 없는 1분 구간은 직전 종가로 채운 **거래량 0 봉**이 내려온다 (오류 아님).
- 미국 1분봉은 장외·특수 체결이 섞인 **이상 고가·저가**가 있을 수 있고 걸러지지 않는다.

### 미국 장 운영 시간 `GET /api/v1/market-calendar/US`

- `date`(미국 현지 날짜) 기준으로 **전일·당일·익일 3영업일**만 반환한다. 세션은 `dayMarket`, `preMarket`, `regularMarket`, `afterMarket`이며 휴장이면 모두 `null`이다. 시간은 KST(+09:00).
- **연간 휴장일 목록은 주지 않는다.** 백테스트·장기 스케줄에는 `exchange_calendars`(XNYS)를 쓰고, 실행 시점의 개장 판정은 토스 캘린더를 우선한다. 둘이 다르면 신규 주문을 막고 경고한다.

## 4. 오류 처리 기준

응답 envelope: 성공 `{"result": ...}`, 실패 `{"error": {"requestId", "code", "message", "data"}}`. `requestId`(= `X-Request-Id` 헤더)는 항상 로그에 남긴다.

| 상황 | 코드 | Worker 동작 |
| --- | --- | --- |
| 토큰 만료 | `401 expired-token` | 재발급 1회 후 재시도 |
| 토큰 무효화 | `401 token-revoked` | **다른 프로세스가 토큰을 발급한 신호.** 재발급하되 반복되면 `ERROR` 전환 후 알림 (토큰 경합) |
| 허용 IP 아님 | `403 edge-blocked` / `forbidden` | 재시도 금지. `ERROR` 전환, 송신 IP를 로그에 표시 |
| 종목 없음 | `404 stock-not-found` | 해당 종목 비활성화 |
| 호출 한도 | `429 rate-limit-exceeded` 등 | `Retry-After` → 백오프 |
| 점검·장애 | `500 maintenance` / `internal-error` | 백오프 재시도. 데이터가 오래되면 신규 주문 차단 |

## 5. 나중 단계(실거래·실시간)에서 쓸 사실

- **주문 멱등성:** 주문 생성에 `clientOrderId`가 있다. 같은 값으로 처리 중이면 `409 request-in-progress`, 내용이 다르면 `422 idempotency-key-conflict`. 내부 판단 키(`bot_id + symbol + bar_ts + mode`)에서 `clientOrderId`를 만들면 외부 주문까지 중복 방지를 이어갈 수 있다.
- 동일 종목에 반대 방향 미체결 주문이 있으면 `409 opposite-pending-order-exists`.
- 미국 금액 주문은 정규장에서만 가능 (`422 amount-order-outside-regular-hours`).
- 레버리지·인버스 ETF는 앱에서 사전 요건(위험 고지 등)을 마쳐야 한다 (`422 prerequisite-required`).
- 짧은 시간에 소액 주문을 대량 반복하면 어뷰징으로 일정 시간 매매가 제한된다.
- 주문 조회는 주문 1건당 1행(평균 체결가·총 수량)이다. 건별 체결은 WebSocket `personal:order`만 제공한다.
- 조건주문(SINGLE·OCO·OTO)이 있다. 손절·익절을 서버 측 조건주문으로 거는 방식을 실거래 단계에서 검토한다.
- WebSocket: 계정당 동시 연결 2개 (초과 시 **가장 오래된 연결이 끊김**), 연결당 구독 100건, 선언 5회/초. 구독은 full-replace 방식이다. 클라이언트 송신이 180초 없으면 끊기므로 60초마다 `PING`을 보낸다. 시세 채널은 LOSSY(sequence 없음), 주문 채널은 세션 내 LOSSLESS이며 재연결 후 `GET /api/v1/orders`로 재동기화한다.

## 6. 직접 확인할 항목 (로드맵 Phase 0)

| # | 질문 | 확인 방법 | 결과 |
| --- | --- | --- | --- |
| 1 | 허용 IP를 몇 개까지 등록하나? 즉시 반영되나? | WTS 화면 | 개수 미확인. 등록 직후 호출 성공 (2026-10-01) |
| 2 | client를 여러 개(로컬용·서버용) 발급할 수 있나? | WTS 화면 | 미확인 |
| 3 | 실제 `expires_in` 값 | 토큰 발급 응답 | ✅ 86399초 |
| 4 | 관심 목록 후보의 `/stocks`·`/candles` 응답 | 조회 | ✅ 10종목 모두 지원 (7절) |
| 5 | 일봉 최초 시점과 페이지네이션 동작 | `before` 반복 조회 | ✅ 상장일부터 제공, `nextBefore`로 끝까지 순회, 중복 0 |
| 6 | 미국 일봉이 **언제 확정되나** (정규장 마감 후 몇 분) | 마감 후 반복 조회 | ⏳ 확정값이 정규장 기준인 것은 확인. **확정까지 걸리는 시간은 미측정** (KST 05:00 이후 `finality` 반복 실행 필요) |
| 7 | 1분봉 보존 기간 | 이진 탐색 | ✅ 약 1764일 (2021-12 초까지) |
| 8 | 실제 rate limit 헤더 값 | 응답 헤더 | ✅ 문서와 동일 (STOCK 5, MARKET_INFO 3, MARKET_DATA_CHART 20) |
| 9 | 미국 서머타임 전환 시 캘린더·봉 시각 표현 | 2026-11-01 전후 조회 | ⏳ 과거 봉으로 일부 확인 (7절). 캘린더는 전환 후 재확인 |

## 7. 실측 결과 (2026-10-01, 개발 PC, `scripts/toss_probe.py`)

원본 응답은 저장하지 않았다. 아래는 요약값이다.

**종목 (`/stocks`)**: 관심 목록 10종목 모두 `ACTIVE`, `USD`.

| 종목 | market | 유형 | leverageFactor |
| --- | --- | --- | --- |
| VOO, GLD, MAGS, EWY, EWJ | AMEX | ETF | 1 |
| QQQ | NASDAQ | ETF | 1 |
| QLD | AMEX | ETF | 2 |
| TQQQ | NASDAQ | ETF | 3 |
| SOXL | AMEX | ETF | 3 |
| NVDA | NASDAQ | STOCK | null |

NYSE Arca 상장 ETF도 `AMEX`로 표시된다. 레버리지 판정은 `leverageFactor > 1`로 한다.

**일봉 이력**

| 종목 | 개수 | 범위 | 4일 넘는 공백 |
| --- | --- | --- | --- |
| VOO | 4040 | 2010-09-09 ~ | 2012-10-26 → 10-31 (허리케인 샌디 휴장) |
| QQQ | 6934 | 1999-03-10 ~ | 2001-09-10 → 09-17 (9·11), 2006-12-29 → 2007-01-03 (포드 전 대통령 장례), 2012 샌디 |

공백은 모두 실제 휴장이다. 일봉 이력은 문서의 "2021-11-30 이후"보다 훨씬 길다.

**일봉 시각**: `timestamp`는 미국 현지 자정을 KST로 표현한 값이다. 서머타임 중에는 `13:00+09:00`, 표준시에는 `14:00+09:00`. **저장할 때는 시각이 아니라 미국 거래일(date)로 변환해 키로 쓴다.**

**일봉 값의 기준 (VOO 2026-09-30)**: 일봉 시가 704.58은 정규장 첫 1분봉(22:31 KST 봉) 시가와 같고, 종가 700.86은 마지막 1분봉 종가(700.73)가 아닌 공식 종가(클로징 옥션)다. 즉 **확정된 일봉은 정규장 공식 OHLC**다.

**진행 중 일봉**: 조회 시각 2026-10-01 16:11 KST(미국 10-01 정규장 시작 전)에 이미 `2026-10-01` 일봉이 데이마켓 체결로 채워져 있었다 (VOO 거래량 27,463). 몇 분 사이에 종가가 바뀌는 것도 관찰했다 (QQQ 748.17 → 748.19). 이 봉은 정규장 이후 정규장 값으로 대체된다.

**미국 세션 (`/market-calendar/US`, 서머타임 중, KST)**: 데이마켓 09:00–17:00, 프리마켓 17:00–22:30, 정규장 22:30–05:00(+1일), 애프터마켓 05:00–08:50(+1일). 미국 날짜 D의 거래는 KST D일 09:00부터 D+1일 08:50까지다.

**1분봉**: 데이마켓 시간에도 1분봉이 있다. 체결이 없는 분은 **봉이 빠진다** (30분 중 2분 누락, 거래량 0 봉은 없음). FAQ의 "거래량 0 봉" 설명은 국내 기준으로 보이며, 미국 1분봉은 빠진 분을 허용하도록 검증한다.

**수정주가 (NVDA 2024-06-10 10:1 분할)**: `adjusted=true`는 분할 전 종가를 1/10로 보정(1208.88 → 120.888, 거래량 ×10), `adjusted=false`는 원래 값을 준다. 백테스트는 `adjusted=true`, 체결 가격 표시는 필요하면 `false`를 쓴다.

**토큰**: 실행마다 새 토큰을 발급했고 이전 토큰 무효화로 인한 문제는 없었다 (동시 사용 프로세스 없음).
