# 토스증권 Open API 조사

> 출처: 공식 문서 `https://openapi.tossinvest.com/openapi-docs/` (overview.md, faq.md, OpenAPI JSON **v1.2.19**). 조사일 2026-10-01.
> 이 문서는 **공식 문서에 적힌 사실**과 **직접 호출로 확인한 사실**을 구분해 적는다. 확인 전 항목은 `미확인`으로 둔다.
> 프로젝트 설계는 [project.md](project.md), 일정은 [roadmap.md](roadmap.md).

## 1. 한눈에 보기

| 항목 | 내용 | 프로젝트 영향 |
| --- | --- | --- |
| 인증 | OAuth 2.0 Client Credentials. `POST /oauth2/token` | refresh token 없음 → 만료 전 재발급 |
| 토큰 수명 | `expires_in` 반환 (예시 86400초 = 24h) | 실제 값은 응답으로 확인 |
| **토큰 개수** | **클라이언트당 유효 토큰 1개.** 새로 발급하면 이전 토큰은 즉시 `401 token-revoked` | **토큰은 Worker 한 곳만 발급·보유.** 로컬 개발과 서버가 같은 client를 쓰면 서로 무효화 |
| **허용 IP** | 등록되지 않은 IP는 REST `403`, WebSocket handshake `403`. 클라우드 대역이라고 차단하지는 않음 | 고정 공인 IP 필수. 등록 가능 개수·변경 절차는 `미확인` |
| 시세 범위 | 국내·미국 주식 시세, 종목 정보, 환율, 장 운영 시간 | 미국 ETF(VOO·QQQ 등) 지원 여부는 호출로 확인 |
| 미국 시세 원천 | **일부 미국 거래소 기준, NBBO 아님.** 세션별로 원천이 다를 수 있음 | 거래량 지표 신뢰도 낮음. 이상 고가·저가 필터 필요 |
| 캔들 | `1m`, `1d`만. 요청당 최대 200개, `before` 페이지네이션 | 일봉 5년 ≈ 7회 호출 |
| 과거 데이터 | **미국 2021-11-30 이후**, 국내 2022-11-23 이후 | 장기 백테스트에는 부족 (하락장 표본 1회) |
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
| 1 | 허용 IP를 몇 개까지 등록하나? 즉시 반영되나? | WTS 화면 | 미확인 |
| 2 | client를 여러 개(로컬용·서버용) 발급할 수 있나? | WTS 화면 | 미확인 |
| 3 | 실제 `expires_in` 값 | 토큰 발급 응답 | 미확인 |
| 4 | `VOO`, `QQQ` 및 관심 목록 후보의 `/stocks`·`/candles` 응답 | 조회 | 미확인 |
| 5 | 일봉 최초 시점(2021-11-30)과 페이지네이션 동작 | `before` 반복 조회 | 미확인 |
| 6 | 미국 일봉이 **언제 확정되나** (정규장 마감 후 몇 분) | 마감 후 반복 조회해 OHLC 변화 관찰 | 미확인 |
| 7 | 1분봉 보존 기간 (며칠 전까지 조회되나) | `before` 반복 조회 | 미확인 |
| 8 | 실제 rate limit 헤더 값 | 응답 헤더 | 미확인 |
| 9 | 미국 서머타임 전환 시 캘린더·봉 시각 표현 | 2026-11-01 전후 조회 | 미확인 |

확인 결과는 이 표와 1절에 날짜와 함께 반영한다.
